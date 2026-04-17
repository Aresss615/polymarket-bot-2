"""Order execution abstraction.

Three modes:
- PaperExecutor: instant fill at quoted price, zero fees (current behavior)
- SimulationExecutor: realistic fills with fees, slippage, partial fills
- LiveExecutor: real CLOB execution with reconciliation-aware order state
"""

import random
import time
import uuid
from datetime import datetime, timezone
import math
from abc import ABC, abstractmethod
from typing import Any
import re

import requests
from eth_abi import encode as abi_encode
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak, to_canonical_address, to_checksum_address
from py_clob_client.config import get_contract_config

from config import (
    APP_CONFIG,
    FEED_HEARTBEAT_STALE_SECONDS,
    LIVE_MAKER_15M_MAX_AGE_SECONDS,
    LIVE_MAKER_DRIFT_TICKS,
    LIVE_MAKER_IMPROVEMENT_TICKS,
    LIVE_MAKER_MAX_AGE_SECONDS,
    LIVE_MAKER_MAX_SPREAD,
    LIVE_MAKER_MAX_SPREAD_TICKS,
    LIVE_MAKER_OBI_AGAINST_THRESHOLD,
    LIVE_MAKER_POST_ONLY,
    LIVE_MAKER_REFERENCE_REVERSAL,
    LIVE_MAX_SIZE_EXPANSION,
    LIVE_MIN_SHARES,
    MAX_TAKER_FEE_RATE,
    OpenOrder,
    OrderResult,
    POLYMARKET_RELAYER_API_KEY,
    POLYMARKET_RELAYER_URL,
    POLYMARKET_WALLET_TYPE,
    RedemptionResult,
    Signal,
    market_side_token_id,
    polymarket_wallet_relayer_type,
    polymarket_wallet_signature_type,
    resolve_polymarket_wallet_type,
)
from price_feed import get_reference_snapshot
from runtime_data import RUNTIME_DATA_PLANE

_COIN_RE = re.compile(r"^([a-z]+)-updown-", re.IGNORECASE)
_SAFE_INIT_CODE_HASH = "0x2bce2127ff07fb632d16c8347c4ebf501f4841168bed00d9e6ef715ddb6fcecf"
_PROXY_INIT_CODE_HASH = "0xd21df8dc65880a8606f09fe0ce3df9b8869287ab0b058be05aa9e8af6330a00b"
_SAFE_FACTORY_ADDRESS = "0xaacFeEa03eb1561C4e67d661e40682Bd20E3541b"
_PROXY_FACTORY_ADDRESS = "0xaB45c5A4B0c941a2F231C04C3f49182e1A254052"
_PROXY_RELAY_HUB_ADDRESS = "0xD216153c06E857cD7f72665E0aF1d7D82172F494"
_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
_ZERO_HASH = "0x" + ("00" * 32)
_SAFE_TX_TYPE_HASH = keccak(
    text=(
        "SafeTx(address to,uint256 value,bytes data,uint8 operation,uint256 safeTxGas,"
        "uint256 baseGas,uint256 gasPrice,address gasToken,address refundReceiver,uint256 nonce)"
    )
)
_EIP712_DOMAIN_TYPE_HASH = keccak(
    text="EIP712Domain(uint256 chainId,address verifyingContract)"
)
_SAFE_OPERATION_CALL = 0
_PROXY_OPERATION_CALL = 1
_CTF_REDEEM_SELECTOR = keccak(
    text="redeemPositions(address,bytes32,bytes32,uint256[])"
)[:4]
_PROXY_SELECTOR = keccak(text="proxy((uint8,address,uint256,bytes)[])")[:4]
_RELAY_SUCCESS_STATES = {"STATE_EXECUTED", "STATE_MINED", "STATE_CONFIRMED"}
_RELAY_PENDING_STATES = {"STATE_NEW"}
_RELAY_FAILED_STATES = {"STATE_INVALID", "STATE_FAILED"}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_coin(slug: str) -> str | None:
    match = _COIN_RE.match(slug or "")
    return match.group(1).upper() if match else None


def _hex_bytes(value: str, expected_len: int | None = None) -> bytes:
    text = str(value or "").strip()
    if text.startswith(("0x", "0X")):
        text = text[2:]
    if len(text) % 2:
        text = f"0{text}"
    data = bytes.fromhex(text) if text else b""
    if expected_len is not None and len(data) != expected_len:
        raise ValueError(f"expected {expected_len} bytes, got {len(data)}")
    return data


def _derive_create2_address(factory: str, salt: bytes, init_code_hash: str) -> str:
    digest = keccak(
        b"\xff"
        + to_canonical_address(factory)
        + salt
        + _hex_bytes(init_code_hash, 32)
    )
    return to_checksum_address(digest[-20:])


def _pack_safe_signature(signature_hex: str) -> str:
    signature = _hex_bytes(signature_hex, 65)
    r = signature[:32]
    s = signature[32:64]
    v = signature[64]
    if v in {0, 1}:
        v += 31
    elif v in {27, 28}:
        v += 4
    else:
        raise ValueError("invalid safe signature v value")
    return f"0x{(r + s + bytes([v])).hex()}"


def _result_metadata_from_signal(signal: Signal) -> dict:
    return {
        "edge_gross": signal.edge_gross,
        "edge_net": signal.edge_net,
        "reference_symbol": signal.reference_symbol or signal.coin,
        "reference_price": signal.reference_price,
        "best_bid": signal.best_bid,
        "best_ask": signal.best_ask,
        "spread": signal.spread,
        "decision_latency_ms": signal.decision_latency_ms,
        "thesis_id": signal.thesis_id,
        "strategy_mode": signal.strategy_mode,
        "model_up_probability": signal.model_up_probability,
        "selected_side_probability": signal.selected_side_probability,
        "interval_open": signal.interval_open,
        "interval_high": signal.interval_high,
        "interval_low": signal.interval_low,
        "interval_close": signal.interval_close,
        "interval_return": signal.interval_return,
        "late_return_60s": signal.late_return_60s,
        "late_return_20s": signal.late_return_20s,
        "body_ratio": signal.body_ratio,
        "wick_imbalance": signal.wick_imbalance,
        "candle_regime": signal.candle_regime,
        "trend_alignment": signal.trend_alignment,
        "market_yes_at_open": signal.market_yes_at_open,
        "market_yes_at_decision": signal.market_yes_at_decision,
        "market_yes_at_close": signal.market_yes_at_close,
        "contrarian_block_reason": signal.contrarian_block_reason,
        "wallet_signal_source": signal.wallet_signal_source,
        "wallet_lead_score": signal.wallet_lead_score,
        "wallet_cluster": signal.wallet_cluster,
        "window_start_ts": signal.window_start_ts,
        "window_open_price": signal.window_open_price,
        "window_open_source": signal.window_open_source,
        "window_open_price_trusted": signal.window_open_price_trusted,
        "window_open_anchor_age_seconds": signal.window_open_anchor_age_seconds,
        "actual_window_return": signal.actual_window_return,
        "actual_move_regime": signal.actual_move_regime,
        "actual_move_side": signal.actual_move_side,
        "strategy_route": signal.strategy_route,
        "cluster_id": signal.cluster_id,
        "signal_epoch_id": signal.signal_epoch_id,
        "book_age_ms": signal.book_age_ms,
        "tick_size": signal.tick_size,
        "expected_fill_price": signal.expected_fill_price,
        "expected_cost": signal.expected_cost,
        "markout_1s": signal.markout_1s,
        "markout_5s": signal.markout_5s,
        "markout_30s": signal.markout_30s,
    }


class OrderExecutor(ABC):
    """Base class for order execution."""

    @abstractmethod
    def place_order(self, signal: Signal, size: float, entry_price: float) -> OrderResult:
        """Execute an order and return the result."""

    def reconcile_order(self, open_order: OpenOrder) -> OrderResult | None:
        """Fetch the latest order state and any newly confirmed fills."""
        return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order if the executor supports it."""
        return False

    def supports_redemption(self) -> bool:
        """Whether the executor can submit live redemption transactions."""
        return False

    def redeem_condition(self, condition_id: str) -> RedemptionResult:
        """Submit a winning-condition redemption if supported."""
        return RedemptionResult(
            status="noop",
            success=True,
            terminal=True,
            raw_response={"condition_id": condition_id},
        )

    def get_redemption_status(self, transaction_id: str) -> RedemptionResult:
        """Check the current redemption status if supported."""
        return RedemptionResult(
            status="noop",
            success=True,
            transaction_id=transaction_id,
            terminal=True,
            raw_response={"transaction_id": transaction_id},
        )

    def get_wallet_balance(self) -> float | None:
        """Return live USDC wallet balance, or None if unavailable."""
        return None

    def get_clob_open_token_ids(self) -> set[str]:
        """Return token_ids of all open orders currently on the CLOB."""
        return set()


class PaperExecutor(OrderExecutor):
    """Instant fill at quoted price with zero fees.

    Preserves the original paper trading behavior exactly.
    """

    def place_order(self, signal: Signal, size: float, entry_price: float) -> OrderResult:
        shares = size / entry_price if entry_price > 0 else 0.0
        token_id = market_side_token_id(signal.market, signal.side)
        return OrderResult(
            filled=True,
            fill_price=entry_price,
            fill_size=size,
            fees=0.0,
            slippage=0.0,
            latency_ms=0.0,
            order_id=f"paper-{uuid.uuid4().hex[:8]}",
            status="filled",
            fill_shares=shares,
            requested_size=size,
            requested_shares=shares,
            token_id=token_id,
            **_result_metadata_from_signal(signal),
        )


def polymarket_taker_fee(price: float) -> float:
    """Estimate Polymarket dynamic taker fee rate.

    Fee is highest (1.8%) at price 0.50 and decreases toward extremes.
    Formula: fee_rate = MAX_TAKER_FEE_RATE * (1 - 2 * |price - 0.50|)
    Examples: price 0.50 -> 1.8%, price 0.75 -> 0.9%, price 0.85 -> 0.54%
    """
    return max(0.0, MAX_TAKER_FEE_RATE * (1.0 - 2.0 * abs(price - 0.50)))


class SimulationExecutor(OrderExecutor):
    """Realistic fill simulation with fees, slippage, and partial fills.

    Models:
    - Dynamic taker fees based on entry price
    - Adverse slippage (0.5-1.5% of entry price)
    - Partial fills: 90% chance full, 10% chance 60-90% fill
    - 2% rejection rate (rate limits, stale prices)
    """

    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)

    def place_order(self, signal: Signal, size: float, entry_price: float) -> OrderResult:
        requested_shares = size / entry_price if entry_price > 0 else 0.0
        metadata = _result_metadata_from_signal(signal)
        token_id = market_side_token_id(signal.market, signal.side)

        # 2% rejection
        if self._rng.random() < 0.02:
            return OrderResult(
                filled=False,
                fill_price=entry_price,
                fill_size=0.0,
                fees=0.0,
                slippage=0.0,
                latency_ms=self._rng.uniform(50, 300),
                order_id=f"sim-{uuid.uuid4().hex[:8]}",
                status="rejected",
                reason="simulated rejection (rate limit / stale)",
                requested_size=size,
                requested_shares=requested_shares,
                token_id=token_id,
                **metadata,
            )

        # Fee calculation
        fee_rate = polymarket_taker_fee(entry_price)

        # Adverse slippage: 0.5-1.5% of entry price
        slippage_pct = self._rng.uniform(0.005, 0.015)
        slippage = entry_price * slippage_pct
        fill_price = min(entry_price + slippage, 0.99)

        # Partial fill: 10% chance
        if self._rng.random() < 0.10:
            fill_ratio = self._rng.uniform(0.6, 0.9)
            fill_size = size * fill_ratio
            status = "partial"
        else:
            fill_size = size
            status = "filled"

        fill_shares = fill_size / fill_price if fill_price > 0 else 0.0
        fees = fill_size * fee_rate

        return OrderResult(
            filled=True,
            fill_price=fill_price,
            fill_size=fill_size,
            fees=fees,
            slippage=slippage,
            latency_ms=self._rng.uniform(50, 300),
            order_id=f"sim-{uuid.uuid4().hex[:8]}",
            status=status,
            fill_shares=fill_shares,
            requested_size=size,
            requested_shares=requested_shares,
            token_id=token_id,
            **metadata,
        )


class LiveExecutor(OrderExecutor):
    """Real CLOB execution via py-clob-client with explicit reconciliation."""

    def __init__(
        self,
        private_key: str,
        chain_id: int = 137,
        funder: str = None,
        market_data_client=None,
        wallet_type: str | None = None,
        relayer_api_key: str | None = None,
        relayer_url: str | None = None,
    ):
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OpenOrderParams, OrderArgs, OrderType, TradeParams

        self._chain_id = chain_id
        self._signer_account = Account.from_key(private_key)
        self.signer_address = to_checksum_address(self._signer_account.address)
        self.wallet_type = resolve_polymarket_wallet_type(
            wallet_type or POLYMARKET_WALLET_TYPE,
            funder,
        )
        self._contract_config = get_contract_config(chain_id)
        self._safe_factory = to_checksum_address(_SAFE_FACTORY_ADDRESS)
        self._collateral_address = to_checksum_address(self._contract_config.collateral)
        self._conditional_tokens_address = to_checksum_address(
            self._contract_config.conditional_tokens
        )
        self._proxy_factory = to_checksum_address(_PROXY_FACTORY_ADDRESS)
        self._proxy_relay_hub = to_checksum_address(_PROXY_RELAY_HUB_ADDRESS)
        derived_wallet = self._derive_wallet_address(self.wallet_type)
        self.funder = (
            to_checksum_address(funder)
            if funder
            else derived_wallet
            if self.wallet_type in {"safe", "proxy"}
            else None
        )
        self.redemption_wallet_address = self.funder or self.signer_address
        self.relayer_api_key = relayer_api_key or POLYMARKET_RELAYER_API_KEY
        self.relayer_url = (relayer_url or POLYMARKET_RELAYER_URL).rstrip("/")
        self.relayer_type = polymarket_wallet_relayer_type(self.wallet_type)
        self.redemption_enabled = bool(self.relayer_api_key and self.relayer_type)
        self._session = requests.Session()

        self._client = ClobClient(
            APP_CONFIG.market_data.clob_api_url,
            key=private_key,
            chain_id=chain_id,
            signature_type=polymarket_wallet_signature_type(self.wallet_type),
            funder=self.funder,
        )
        self._client.set_api_creds(self._client.create_or_derive_api_creds())
        self._OrderArgs = OrderArgs
        self._OrderType = OrderType
        self._OpenOrderParams = OpenOrderParams
        self._TradeParams = TradeParams
        self._market_data = market_data_client

    def _derive_wallet_address(self, wallet_type: str) -> str | None:
        if wallet_type == "safe":
            salt = keccak(
                abi_encode(
                    ["address"],
                    [self.signer_address],
                )
            )
            return _derive_create2_address(self._safe_factory, salt, _SAFE_INIT_CODE_HASH)
        if wallet_type == "proxy":
            salt = keccak(to_canonical_address(self.signer_address))
            return _derive_create2_address(self._proxy_factory, salt, _PROXY_INIT_CODE_HASH)
        return None

    def supports_redemption(self) -> bool:
        return self.redemption_enabled

    def get_wallet_balance(self) -> float | None:
        try:
            from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
            result = self._client.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            raw = result.get("balance") if isinstance(result, dict) else getattr(result, "balance", None)
            return float(raw) if raw is not None else None
        except Exception:
            return None

    def get_clob_open_token_ids(self) -> set[str]:
        try:
            orders = self._client.get_orders(self._OpenOrderParams()) or []
            return {
                str(o.get("asset_id") or o.get("token_id") or "")
                for o in orders
                if isinstance(o, dict) and (o.get("asset_id") or o.get("token_id"))
            }
        except Exception:
            return set()

    def _relayer_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.relayer_api_key:
            headers.update(
                {
                    "RELAYER_API_KEY": self.relayer_api_key,
                    "RELAYER_API_KEY_ADDRESS": self.signer_address,
                }
            )
        return headers

    def _relayer_request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        payload: dict | None = None,
    ) -> Any:
        response = self._session.request(
            method,
            f"{self.relayer_url}{path}",
            headers=self._relayer_headers(),
            params=params,
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    def _sign_message_hash(self, hash_hex: str) -> str:
        signed = self._signer_account.sign_message(encode_defunct(hexstr=hash_hex))
        signature = signed.signature.hex()
        return signature if signature.startswith("0x") else f"0x{signature}"

    def _safe_transaction_hash(
        self,
        *,
        safe_address: str,
        to: str,
        value: int,
        data: str,
        operation: int,
        nonce: int,
        safe_tx_gas: int = 0,
        base_gas: int = 0,
        gas_price: int = 0,
        gas_token: str = _ZERO_ADDRESS,
        refund_receiver: str = _ZERO_ADDRESS,
    ) -> str:
        data_hash = keccak(_hex_bytes(data))
        tx_struct_hash = keccak(
            abi_encode(
                [
                    "bytes32",
                    "address",
                    "uint256",
                    "bytes32",
                    "uint8",
                    "uint256",
                    "uint256",
                    "uint256",
                    "address",
                    "address",
                    "uint256",
                ],
                [
                    _SAFE_TX_TYPE_HASH,
                    to_checksum_address(to),
                    int(value),
                    data_hash,
                    int(operation),
                    int(safe_tx_gas),
                    int(base_gas),
                    int(gas_price),
                    to_checksum_address(gas_token),
                    to_checksum_address(refund_receiver),
                    int(nonce),
                ],
            )
        )
        domain_separator = keccak(
            abi_encode(
                ["bytes32", "uint256", "address"],
                [
                    _EIP712_DOMAIN_TYPE_HASH,
                    int(self._chain_id),
                    to_checksum_address(safe_address),
                ],
            )
        )
        return f"0x{keccak(b'\x19\x01' + domain_separator + tx_struct_hash).hex()}"

    def _proxy_transaction_hash(
        self,
        *,
        to: str,
        data: str,
        tx_fee: int,
        gas_price: int,
        gas_limit: int,
        nonce: int,
        relay_hub: str,
        relay_address: str,
    ) -> str:
        payload = (
            b"rlx:"
            + to_canonical_address(self.signer_address)
            + to_canonical_address(to)
            + _hex_bytes(data)
            + int(tx_fee).to_bytes(32, "big")
            + int(gas_price).to_bytes(32, "big")
            + int(gas_limit).to_bytes(32, "big")
            + int(nonce).to_bytes(32, "big")
            + to_canonical_address(relay_hub)
            + to_canonical_address(relay_address)
        )
        return f"0x{keccak(payload).hex()}"

    def _encode_ctf_redeem_calldata(self, condition_id: str) -> str:
        encoded = abi_encode(
            ["address", "bytes32", "bytes32", "uint256[]"],
            [
                self._collateral_address,
                _hex_bytes(_ZERO_HASH, 32),
                _hex_bytes(condition_id, 32),
                [1, 2],
            ],
        )
        return f"0x{(_CTF_REDEEM_SELECTOR + encoded).hex()}"

    def _encode_proxy_transaction_data(self, to: str, data: str) -> str:
        encoded = abi_encode(
            ["(uint8,address,uint256,bytes)[]"],
            [[(_PROXY_OPERATION_CALL, to_checksum_address(to), 0, _hex_bytes(data))]],
        )
        return f"0x{(_PROXY_SELECTOR + encoded).hex()}"

    def _parse_relayer_result(self, payload: Any) -> RedemptionResult:
        if isinstance(payload, list):
            payload = payload[0] if payload else {}
        if not isinstance(payload, dict):
            return RedemptionResult(
                status="failed",
                success=False,
                error=str(payload),
                retryable=True,
                raw_response={"payload": payload},
            )

        state = str(payload.get("state", "")).strip().upper()
        transaction_id = str(
            payload.get("transactionID")
            or payload.get("transactionId")
            or ""
        )
        transaction_hash = str(
            payload.get("transactionHash")
            or payload.get("hash")
            or ""
        )
        error = self._error_text(payload) if state in _RELAY_FAILED_STATES else ""
        if state in _RELAY_SUCCESS_STATES:
            return RedemptionResult(
                status="confirmed",
                success=True,
                transaction_id=transaction_id,
                transaction_hash=transaction_hash,
                terminal=True,
                raw_state=state,
                raw_response=payload,
            )
        if state in _RELAY_PENDING_STATES:
            return RedemptionResult(
                status="pending",
                success=True,
                transaction_id=transaction_id,
                transaction_hash=transaction_hash,
                terminal=False,
                raw_state=state,
                raw_response=payload,
            )
        if state in _RELAY_FAILED_STATES:
            return RedemptionResult(
                status="failed",
                success=False,
                transaction_id=transaction_id,
                transaction_hash=transaction_hash,
                error=error,
                terminal=True,
                retryable=True,
                raw_state=state,
                raw_response=payload,
            )
        if transaction_id:
            return RedemptionResult(
                status="pending",
                success=True,
                transaction_id=transaction_id,
                transaction_hash=transaction_hash,
                terminal=False,
                raw_state=state,
                raw_response=payload,
            )
        return RedemptionResult(
            status="failed",
            success=False,
            error=self._error_text(payload),
            retryable=True,
            raw_state=state,
            raw_response=payload,
        )

    def redeem_condition(self, condition_id: str) -> RedemptionResult:
        if self.wallet_type == "eoa":
            return RedemptionResult(
                status="disabled",
                success=False,
                error="auto-redeem is disabled for eoa wallets in v1",
                terminal=True,
                raw_response={"wallet_type": self.wallet_type},
            )
        if not self.redemption_enabled:
            return RedemptionResult(
                status="disabled",
                success=False,
                error="relayer api key not configured for live redemption",
                terminal=True,
                raw_response={"wallet_type": self.wallet_type},
            )

        try:
            calldata = self._encode_ctf_redeem_calldata(condition_id)
            if self.wallet_type == "safe":
                nonce_payload = self._relayer_request(
                    "GET",
                    "/nonce",
                    params={"address": self.signer_address, "type": self.relayer_type},
                )
                nonce = int(str((nonce_payload or {}).get("nonce", "0")))
                safe_address = to_checksum_address(self.redemption_wallet_address)
                tx_hash = self._safe_transaction_hash(
                    safe_address=safe_address,
                    to=self._conditional_tokens_address,
                    value=0,
                    data=calldata,
                    operation=_SAFE_OPERATION_CALL,
                    nonce=nonce,
                )
                request_payload = {
                    "from": self.signer_address,
                    "to": self._conditional_tokens_address,
                    "proxyWallet": safe_address,
                    "data": calldata,
                    "nonce": str(nonce),
                    "signature": _pack_safe_signature(self._sign_message_hash(tx_hash)),
                    "signatureParams": {
                        "gasPrice": "0",
                        "operation": "0",
                        "safeTxnGas": "0",
                        "baseGas": "0",
                        "gasToken": _ZERO_ADDRESS,
                        "refundReceiver": _ZERO_ADDRESS,
                    },
                    "type": "SAFE",
                    "metadata": f"redeem:{condition_id}",
                }
            else:
                relay_payload = self._relayer_request(
                    "GET",
                    "/relay-payload",
                    params={"address": self.signer_address, "type": self.relayer_type},
                )
                relay_address = str((relay_payload or {}).get("address", ""))
                nonce = int(str((relay_payload or {}).get("nonce", "0")))
                proxy_data = self._encode_proxy_transaction_data(
                    self._conditional_tokens_address,
                    calldata,
                )
                tx_hash = self._proxy_transaction_hash(
                    to=self._proxy_factory,
                    data=proxy_data,
                    tx_fee=0,
                    gas_price=0,
                    gas_limit=10_000_000,
                    nonce=nonce,
                    relay_hub=self._proxy_relay_hub,
                    relay_address=relay_address,
                )
                request_payload = {
                    "from": self.signer_address,
                    "to": self._proxy_factory,
                    "proxyWallet": to_checksum_address(self.redemption_wallet_address),
                    "data": proxy_data,
                    "nonce": str(nonce),
                    "signature": self._sign_message_hash(tx_hash),
                    "signatureParams": {
                        "gasPrice": "0",
                        "gasLimit": "10000000",
                        "relayerFee": "0",
                        "relayHub": self._proxy_relay_hub,
                        "relay": relay_address,
                    },
                    "type": "PROXY",
                    "metadata": f"redeem:{condition_id}",
                }

            response_payload = self._relayer_request(
                "POST",
                "/submit",
                payload=request_payload,
            )
            return self._parse_relayer_result(response_payload)
        except Exception as exc:
            return RedemptionResult(
                status="failed",
                success=False,
                error=self._error_text(exc),
                retryable=True,
                terminal=True,
                raw_response={"condition_id": condition_id},
            )

    def get_redemption_status(self, transaction_id: str) -> RedemptionResult:
        if not transaction_id:
            return RedemptionResult(
                status="failed",
                success=False,
                error="missing transaction id",
                retryable=True,
                terminal=True,
            )
        if not self.redemption_enabled:
            return RedemptionResult(
                status="disabled",
                success=False,
                transaction_id=transaction_id,
                error="relayer api key not configured for live redemption",
                terminal=True,
            )
        try:
            response_payload = self._relayer_request(
                "GET",
                "/transaction",
                params={"id": transaction_id},
            )
            result = self._parse_relayer_result(response_payload)
            if not result.transaction_id:
                result.transaction_id = transaction_id
            return result
        except Exception as exc:
            return RedemptionResult(
                status="failed",
                success=False,
                transaction_id=transaction_id,
                error=self._error_text(exc),
                retryable=True,
                terminal=True,
            )

    @staticmethod
    def _is_fok_full_fill_error(detail: str) -> bool:
        text = str(detail).lower()
        return "fok" in text and "fully filled" in text and "killed" in text

    @staticmethod
    def _is_post_only_reject(detail: str) -> bool:
        text = str(detail).lower()
        return ("post" in text and "only" in text) or "would match" in text or "would take" in text

    @staticmethod
    def _error_text(payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("errorMsg", "error", "error_message", "message", "detail"):
                value = payload.get(key)
                if value:
                    return str(value)
        for key in ("error_msg", "error", "message", "detail", "msg"):
            value = getattr(payload, key, None)
            if value:
                return str(value)
        status_code = getattr(payload, "status_code", None)
        if status_code is not None:
            return f"HTTP {status_code}: {getattr(payload, 'error_msg', payload)}"
        return str(payload)

    @staticmethod
    def _normalize_status(status: Any) -> str:
        return str(status or "").strip().lower()

    @staticmethod
    def _book_attr(payload: Any, field: str, default=None):
        if isinstance(payload, dict):
            return payload.get(field, default)
        return getattr(payload, field, default)

    def _book_price(self, level: Any) -> float:
        return _safe_float(self._book_attr(level, "price"), 0.0)

    @staticmethod
    def _quote_age_seconds(quote: Any) -> float | None:
        fetched_at = getattr(quote, "fetched_at", None)
        if fetched_at is None:
            return None
        if getattr(fetched_at, "tzinfo", None) is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - fetched_at).total_seconds()

    @staticmethod
    def _floor_to_tick(price: float, tick_size: float) -> float:
        tick = max(tick_size, 0.01)
        floored = math.floor((price + 1e-9) / tick) * tick
        return round(max(tick, min(0.99, floored)), 2)

    @staticmethod
    def _cached_book_needs_refresh(book: dict) -> bool:
        if not book:
            return True
        best_bid = _safe_float(book.get("best_bid"), 0.0)
        best_ask = _safe_float(book.get("best_ask"), 0.0)
        tick_size = max(_safe_float(book.get("tick_size"), 0.01), 0.01)
        spread = book.get("spread")
        if spread in (None, "") and best_bid > 0 and best_ask > 0:
            spread = max(best_ask - best_bid, 0.0)
        spread = _safe_float(spread, 0.0)
        book_age_ms = _safe_float(book.get("book_age_ms"), 0.0)
        max_reasonable_spread = max(LIVE_MAKER_MAX_SPREAD, tick_size * LIVE_MAKER_MAX_SPREAD_TICKS)
        if best_bid <= 0 and best_ask <= 0:
            return True
        if book_age_ms > FEED_HEARTBEAT_STALE_SECONDS * 1000.0:
            return True
        if best_bid > 0 and best_ask > 0 and best_ask < best_bid:
            return True
        return best_bid > 0 and best_ask > 0 and spread > max_reasonable_spread * 2.0

    def _get_book_snapshot(self, token_id: str) -> dict:
        cached = RUNTIME_DATA_PLANE.market_cache.snapshot(token_id)
        if cached and not self._cached_book_needs_refresh(cached):
            return {
                "best_bid": cached.get("best_bid") or 0.0,
                "best_ask": cached.get("best_ask") or 0.0,
                "tick_size": cached.get("tick_size") or 0.01,
                "midpoint": cached.get("midpoint") or 0.0,
                "spread": cached.get("spread") or 0.0,
                "microprice": cached.get("microprice"),
                "top_obi": cached.get("top_obi"),
                "top3_obi": cached.get("top3_obi"),
                "book_age_ms": cached.get("book_age_ms"),
            }
        try:
            book = self._client.get_order_book(token_id)
        except Exception:
            if cached:
                return {
                    "best_bid": cached.get("best_bid") or 0.0,
                    "best_ask": cached.get("best_ask") or 0.0,
                    "tick_size": cached.get("tick_size") or 0.01,
                    "midpoint": cached.get("midpoint") or 0.0,
                    "spread": cached.get("spread") or 0.0,
                    "microprice": cached.get("microprice"),
                    "top_obi": cached.get("top_obi"),
                    "top3_obi": cached.get("top3_obi"),
                    "book_age_ms": cached.get("book_age_ms"),
                }
            return {}

        bids = self._book_attr(book, "bids", []) or []
        asks = self._book_attr(book, "asks", []) or []
        best_bid = self._book_price(bids[0]) if bids else 0.0
        best_ask = self._book_price(asks[0]) if asks else 0.0
        tick_size = _safe_float(self._book_attr(book, "tick_size"), 0.01)
        midpoint = 0.0
        microprice = 0.0
        top_obi = 0.0
        top3_obi = 0.0
        if best_bid > 0 and best_ask > 0:
            midpoint = (best_bid + best_ask) / 2.0
        elif best_bid > 0:
            midpoint = best_bid
        elif best_ask > 0:
            midpoint = best_ask
        spread = max(best_ask - best_bid, 0.0) if best_bid > 0 and best_ask > 0 else 0.0

        best_bid_size = _safe_float(self._book_attr(bids[0], "size"), 0.0) if bids else 0.0
        best_ask_size = _safe_float(self._book_attr(asks[0], "size"), 0.0) if asks else 0.0
        top_total = best_bid_size + best_ask_size
        if best_bid > 0 and best_ask > 0 and top_total > 0:
            microprice = ((best_ask * best_bid_size) + (best_bid * best_ask_size)) / top_total
            top_obi = (best_bid_size - best_ask_size) / top_total

        bid3 = sum(_safe_float(self._book_attr(level, "size"), 0.0) for level in bids[:3])
        ask3 = sum(_safe_float(self._book_attr(level, "size"), 0.0) for level in asks[:3])
        total3 = bid3 + ask3
        if total3 > 0:
            top3_obi = (bid3 - ask3) / total3

        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "tick_size": tick_size,
            "midpoint": midpoint,
            "spread": spread,
            "microprice": microprice or None,
            "top_obi": top_obi if top_total > 0 else None,
            "top3_obi": top3_obi if total3 > 0 else None,
            "book_age_ms": 0.0,
        }

    def _maker_limit_price(self, entry_price: float, book: dict) -> float:
        tick_size = max(book.get("tick_size") or 0.01, 0.01)
        best_bid = book.get("best_bid", 0.0)
        best_ask = book.get("best_ask", 0.0)

        quote = entry_price
        if best_ask > 0:
            quote = min(quote, best_ask - tick_size)
        if best_bid > 0:
            quote = min(quote, best_bid + tick_size * LIVE_MAKER_IMPROVEMENT_TICKS)

        quote = self._floor_to_tick(quote, tick_size)

        if best_bid > 0 and best_ask > 0 and quote >= best_ask:
            quote = self._floor_to_tick(best_bid, tick_size)
        return quote

    def _submit_limit_order(
        self,
        *,
        token_id: str,
        shares: float,
        limit_price: float,
        post_only: bool,
    ) -> Any:
        order_args = self._OrderArgs(
            token_id=token_id,
            price=limit_price,
            size=shares,
            side="BUY",
        )
        signed_order = self._client.create_order(order_args)
        return self._client.post_order(signed_order, self._OrderType.GTC, post_only)

    def _make_rejection(
        self,
        *,
        entry_price: float,
        latency_ms: float,
        reason: str,
        requested_size: float,
        requested_shares: float,
        token_id: str = "",
        metadata: dict | None = None,
    ) -> OrderResult:
        return OrderResult(
            filled=False,
            fill_price=entry_price,
            fill_size=0.0,
            fees=0.0,
            slippage=0.0,
            latency_ms=latency_ms,
            order_id="",
            status="rejected",
            reason=reason,
            requested_size=requested_size,
            requested_shares=requested_shares,
            token_id=token_id,
            **(metadata or {}),
        )

    def _normalize_submit_response(
        self,
        *,
        response: Any,
        entry_price: float,
        limit_price: float,
        actual_size: float,
        shares: float,
        token_id: str,
        latency_ms: float,
        raw_context: dict | None = None,
        metadata: dict | None = None,
    ) -> OrderResult:
        if not isinstance(response, dict) or not (response.get("success") or response.get("orderID")):
            return self._make_rejection(
                entry_price=entry_price,
                latency_ms=latency_ms,
                reason=self._error_text(response),
                requested_size=actual_size,
                requested_shares=shares,
                token_id=token_id,
                metadata=metadata,
            )

        order_id = str(response.get("orderID", response.get("id", "")))
        raw_status = self._normalize_status(response.get("status"))
        terminal_statuses = {"cancelled", "canceled", "failed", "rejected", "expired"}
        terminal = raw_status in terminal_statuses
        normalized_status = "submitted" if not terminal else ("cancelled" if "cancel" in raw_status else "rejected")
        reserved_size = 0.0 if terminal else actual_size
        remaining_shares = 0.0 if terminal else shares
        remaining_size = 0.0 if terminal else actual_size

        return OrderResult(
            filled=False,
            fill_price=limit_price,
            fill_size=0.0,
            fees=0.0,
            slippage=limit_price - entry_price,
            latency_ms=latency_ms,
            order_id=order_id,
            status=normalized_status,
            requested_size=actual_size,
            requested_shares=shares,
            token_id=token_id,
            reserved_size=reserved_size,
            remaining_size=remaining_size,
            remaining_shares=remaining_shares,
            needs_reconciliation=not terminal,
            terminal=terminal,
            raw_status=raw_status,
            raw_response=raw_context or response,
            **(metadata or {}),
        )

    def place_order(self, signal: Signal, size: float, entry_price: float) -> OrderResult:
        metadata = _result_metadata_from_signal(signal)
        token_id = market_side_token_id(signal.market, signal.side)
        if not token_id:
            return self._make_rejection(
                entry_price=entry_price,
                latency_ms=0.0,
                reason=f"no token_id for side {signal.side}",
                requested_size=size,
                requested_shares=0.0,
                metadata=metadata,
            )
        if self._market_data is not None:
            try:
                quote = self._market_data.get_execution_quote(token_id, side="BUY")
                quote_age = self._quote_age_seconds(quote) if quote is not None else None
                if quote_age is not None and quote_age > APP_CONFIG.execution.quote_staleness_seconds:
                    return self._make_rejection(
                        entry_price=entry_price,
                        latency_ms=0.0,
                        reason=f"stale quote ({quote_age:.2f}s old)",
                        requested_size=size,
                        requested_shares=(size / entry_price if entry_price > 0 else 0.0),
                        token_id=token_id,
                        metadata=metadata,
                    )
                depth_usd = _safe_float(getattr(quote, "depth_usd", 0.0), 0.0) if quote is not None else 0.0
                if depth_usd and depth_usd < max(APP_CONFIG.execution.min_order_depth_usd, size * 1.2):
                    return self._make_rejection(
                        entry_price=entry_price,
                        latency_ms=0.0,
                        reason=f"insufficient depth (${depth_usd:.2f})",
                        requested_size=size,
                        requested_shares=(size / entry_price if entry_price > 0 else 0.0),
                        token_id=token_id,
                        metadata=metadata,
                    )
            except Exception:
                return self._make_rejection(
                    entry_price=entry_price,
                    latency_ms=0.0,
                    reason="market_data_unavailable",
                    requested_size=size,
                    requested_shares=(size / entry_price if entry_price > 0 else 0.0),
                    token_id=token_id,
                    metadata=metadata,
                )

        book_snapshot = self._get_book_snapshot(token_id)
        if book_snapshot:
            tick_size = max(book_snapshot.get("tick_size") or 0.01, 0.01)
            best_bid = _safe_float(book_snapshot.get("best_bid"), 0.0)
            best_ask = _safe_float(book_snapshot.get("best_ask"), 0.0)
            book_reference_price = best_ask or best_bid
            drift_threshold = max(
                LIVE_MAKER_MAX_SPREAD,
                tick_size * (LIVE_MAKER_DRIFT_TICKS + LIVE_MAKER_IMPROVEMENT_TICKS + 1),
            )
            if book_reference_price > 0 and book_reference_price >= entry_price + drift_threshold:
                return self._make_rejection(
                    entry_price=entry_price,
                    latency_ms=0.0,
                    reason=(
                        f"market moved above signal price "
                        f"({book_reference_price:.2f}>{entry_price:.2f})"
                    ),
                    requested_size=size,
                    requested_shares=(size / entry_price if entry_price > 0 else 0.0),
                    token_id=token_id,
                    metadata={
                        **metadata,
                        "best_bid": best_bid or metadata.get("best_bid"),
                        "best_ask": best_ask or metadata.get("best_ask"),
                        "spread": book_snapshot.get("spread"),
                        "book_age_ms": book_snapshot.get("book_age_ms"),
                        "tick_size": tick_size,
                        "expected_fill_price": book_reference_price,
                    },
                )
        limit_price = self._maker_limit_price(entry_price, book_snapshot) if book_snapshot else round(min(entry_price, 0.99), 2)
        estimated_shares = size / limit_price if limit_price > 0 else 0.0
        if estimated_shares < 0.1:
            return self._make_rejection(
                entry_price=entry_price,
                latency_ms=0.0,
                reason=f"shares too small ({estimated_shares:.3f} < 0.1)",
                requested_size=size,
                requested_shares=estimated_shares,
                token_id=token_id,
                metadata=metadata,
            )

        min_shares = LIVE_MIN_SHARES
        shares = max(round(size / limit_price, 2), min_shares)
        actual_size = round(shares * limit_price, 2)
        if actual_size > size * LIVE_MAX_SIZE_EXPANSION:
            return self._make_rejection(
                entry_price=limit_price,
                latency_ms=0.0,
                reason=f"size expansion {actual_size:.2f} > limit {size * LIVE_MAX_SIZE_EXPANSION:.2f} (min_shares floor)",
                requested_size=size,
                requested_shares=shares,
                token_id=token_id,
                metadata=metadata,
            )

        t0 = time.time()
        try:
            response = self._submit_limit_order(
                token_id=token_id,
                shares=shares,
                limit_price=limit_price,
                post_only=LIVE_MAKER_POST_ONLY,
            )
            if LIVE_MAKER_POST_ONLY and self._is_post_only_reject(self._error_text(response)):
                retry_book = self._get_book_snapshot(token_id)
                retry_tick = max(retry_book.get("tick_size") or 0.01, 0.01)
                retry_price = self._floor_to_tick(max(retry_tick, limit_price - retry_tick), retry_tick)
                if retry_book:
                    retry_price = min(retry_price, self._maker_limit_price(entry_price, retry_book))
                if retry_price > 0 and retry_price < limit_price:
                    limit_price = retry_price
                    book_snapshot = retry_book or book_snapshot
                    response = self._submit_limit_order(
                        token_id=token_id,
                        shares=shares,
                        limit_price=limit_price,
                        post_only=LIVE_MAKER_POST_ONLY,
                    )
            actual_size = round(shares * limit_price, 2)
            latency_ms = (time.time() - t0) * 1000
            return self._normalize_submit_response(
                response=response,
                entry_price=entry_price,
                limit_price=limit_price,
                actual_size=actual_size,
                shares=shares,
                token_id=token_id,
                latency_ms=latency_ms,
                raw_context={
                    "submit": response,
                    "book": book_snapshot,
                    "post_only": LIVE_MAKER_POST_ONLY,
                },
                metadata={
                    **metadata,
                    "best_bid": book_snapshot.get("best_bid") or metadata.get("best_bid"),
                    "best_ask": book_snapshot.get("best_ask") or metadata.get("best_ask"),
                    "spread": book_snapshot.get("spread") if book_snapshot else metadata.get("spread"),
                    "book_age_ms": book_snapshot.get("book_age_ms") if book_snapshot else metadata.get("book_age_ms"),
                    "tick_size": book_snapshot.get("tick_size") if book_snapshot else metadata.get("tick_size"),
                    "expected_fill_price": limit_price,
                },
            )
        except Exception as exc:
            err_detail = self._error_text(exc)
            latency_ms = (time.time() - t0) * 1000
            return self._make_rejection(
                entry_price=entry_price,
                latency_ms=latency_ms,
                reason=err_detail,
                requested_size=actual_size,
                requested_shares=shares,
                token_id=token_id,
                metadata=metadata,
            )

    def cancel_order(self, order_id: str) -> bool:
        try:
            response = self._client.cancel(order_id)
            if isinstance(response, dict):
                return not bool(response.get("errorMsg") or response.get("error"))
            return True
        except Exception:
            return False

    def _cancel_quote_reason(self, open_order: OpenOrder) -> str:
        age_seconds = (datetime.now(timezone.utc) - open_order.created_at).total_seconds()
        max_age = (
            LIVE_MAKER_15M_MAX_AGE_SECONDS
            if open_order.market_type == "15m"
            else LIVE_MAKER_MAX_AGE_SECONDS
        )
        if age_seconds >= max_age:
            return f"maker_quote_age>{max_age:.1f}s"

        book = self._get_book_snapshot(open_order.token_id)
        if not book:
            return "feed_health_stale"

        spread = book.get("spread", 0.0)
        tick_size = max(book.get("tick_size") or 0.01, 0.01)
        midpoint = book.get("midpoint", 0.0)
        best_bid = book.get("best_bid", 0.0)
        microprice = book.get("microprice")
        top_obi = book.get("top_obi")
        top3_obi = book.get("top3_obi")
        spread_ticks = int(round(spread / tick_size)) if tick_size > 0 else 0

        if spread >= LIVE_MAKER_MAX_SPREAD or spread_ticks >= LIVE_MAKER_MAX_SPREAD_TICKS:
            return f"spread_widened>{LIVE_MAKER_MAX_SPREAD:.2f}"
        if midpoint > 0 and midpoint <= open_order.limit_price - LIVE_MAKER_DRIFT_TICKS * tick_size:
            return f"midpoint_drift<{midpoint:.2f}"
        if best_bid > open_order.limit_price + tick_size:
            return f"outbid_by_market>{best_bid:.2f}"
        if microprice is not None and microprice <= open_order.limit_price - tick_size:
            return f"microprice_cross<{microprice:.2f}"
        if top_obi is not None and top_obi <= -LIVE_MAKER_OBI_AGAINST_THRESHOLD:
            return f"top_obi_against<{top_obi:.2f}"
        if top3_obi is not None and top3_obi <= -LIVE_MAKER_OBI_AGAINST_THRESHOLD:
            return f"top3_obi_against<{top3_obi:.2f}"

        coin = open_order.coin or _extract_coin(open_order.market_slug)
        if coin and open_order.reference_price:
            reference = get_reference_snapshot(coin)
            current_price = reference.get("price")
            age = reference.get("age_seconds")
            if age is None or age > FEED_HEARTBEAT_STALE_SECONDS:
                return "feed_health_stale"
            if current_price:
                upper = open_order.reference_price * (1.0 + LIVE_MAKER_REFERENCE_REVERSAL)
                lower = open_order.reference_price * (1.0 - LIVE_MAKER_REFERENCE_REVERSAL)
                if open_order.side == "YES" and current_price <= lower:
                    return f"reference_reversal<{current_price:.4f}"
                if open_order.side == "NO" and current_price >= upper:
                    return f"reference_reversal>{current_price:.4f}"
        return ""

    def _get_order_payload(self, order_id: str) -> dict | None:
        try:
            payload = self._client.get_order(order_id)
            if isinstance(payload, dict) and payload:
                return payload
        except Exception:
            pass

        try:
            results = self._client.get_orders(self._OpenOrderParams(id=order_id))
            if results:
                return results[0]
        except Exception:
            pass
        return None

    def _matching_trade_totals(self, open_order: OpenOrder) -> tuple[float, float, float, int]:
        confirmed_shares = 0.0
        confirmed_cost = 0.0
        confirmed_fees = 0.0
        matches = 0

        try:
            trades = self._client.get_trades(
                self._TradeParams(
                    market=open_order.condition_id,
                    asset_id=open_order.token_id,
                )
            )
        except Exception:
            return confirmed_shares, confirmed_cost, confirmed_fees, matches

        for trade in trades or []:
            status = str(trade.get("status", "")).upper()
            if "CONFIRMED" not in status:
                continue

            matched_shares = 0.0
            price = _safe_float(trade.get("price"), open_order.limit_price)
            fee_rate_bps = _safe_float(trade.get("fee_rate_bps"), 0.0)

            if trade.get("taker_order_id") == open_order.order_id:
                matched_shares = _safe_float(trade.get("size"), 0.0)
            else:
                for maker_order in trade.get("maker_orders") or []:
                    if maker_order.get("order_id") == open_order.order_id:
                        matched_shares = _safe_float(
                            maker_order.get("matched_amount"),
                            _safe_float(trade.get("size"), 0.0),
                        )
                        price = _safe_float(maker_order.get("price"), price)
                        fee_rate_bps = _safe_float(maker_order.get("fee_rate_bps"), fee_rate_bps)
                        break

            if matched_shares <= 0:
                continue

            matches += 1
            fill_cost = matched_shares * price
            confirmed_shares += matched_shares
            confirmed_cost += fill_cost
            confirmed_fees += fill_cost * fee_rate_bps / 10000.0

        return confirmed_shares, confirmed_cost, confirmed_fees, matches

    def reconcile_order(self, open_order: OpenOrder) -> OrderResult:
        t0 = time.time()
        event_snapshot = RUNTIME_DATA_PLANE.order_store.snapshot(open_order.order_id)
        if event_snapshot is not None:
            delta_shares = max(event_snapshot.fill_shares - open_order.confirmed_fill_shares, 0.0)
            fill_price = open_order.limit_price
            if delta_shares > 0 and event_snapshot.fill_size > 0:
                fill_price = event_snapshot.fill_size / delta_shares
            return OrderResult(
                filled=delta_shares > 0,
                fill_price=fill_price,
                fill_size=max(event_snapshot.fill_size - open_order.confirmed_fill_size, 0.0),
                fees=max(event_snapshot.fees - open_order.confirmed_fees, 0.0),
                slippage=(fill_price - open_order.limit_price) if delta_shares > 0 else 0.0,
                latency_ms=(time.time() - t0) * 1000,
                order_id=open_order.order_id,
                status=event_snapshot.status or open_order.status,
                reason="",
                fill_shares=delta_shares,
                remaining_size=event_snapshot.remaining_size if event_snapshot.remaining_size is not None else open_order.reserved_size,
                remaining_shares=event_snapshot.remaining_shares if event_snapshot.remaining_shares is not None else open_order.requested_shares - event_snapshot.fill_shares,
                reserved_size=event_snapshot.remaining_size if event_snapshot.remaining_size is not None else open_order.reserved_size,
                requested_size=open_order.requested_size,
                requested_shares=open_order.requested_shares,
                token_id=open_order.token_id,
                needs_reconciliation=not event_snapshot.terminal,
                terminal=event_snapshot.terminal,
                raw_status=event_snapshot.raw_status or event_snapshot.status,
                edge_gross=open_order.edge_gross,
                edge_net=open_order.edge_net,
                reference_symbol=open_order.reference_symbol,
                reference_price=open_order.reference_price,
                best_bid=open_order.best_bid,
                best_ask=open_order.best_ask,
                spread=open_order.spread,
                decision_latency_ms=open_order.decision_latency_ms,
                thesis_id=open_order.thesis_id,
                cancel_reason=open_order.cancel_reason,
                strategy_mode=open_order.strategy_mode,
                model_up_probability=open_order.model_up_probability,
                selected_side_probability=open_order.selected_side_probability,
                interval_open=open_order.interval_open,
                interval_high=open_order.interval_high,
                interval_low=open_order.interval_low,
                interval_close=open_order.interval_close,
                interval_return=open_order.interval_return,
                late_return_60s=open_order.late_return_60s,
                late_return_20s=open_order.late_return_20s,
                body_ratio=open_order.body_ratio,
                wick_imbalance=open_order.wick_imbalance,
                candle_regime=open_order.candle_regime,
                trend_alignment=open_order.trend_alignment,
                market_yes_at_open=open_order.market_yes_at_open,
                market_yes_at_decision=open_order.market_yes_at_decision,
                market_yes_at_close=open_order.market_yes_at_close,
                contrarian_block_reason=open_order.contrarian_block_reason,
                wallet_signal_source=open_order.wallet_signal_source,
                wallet_lead_score=open_order.wallet_lead_score,
                wallet_cluster=open_order.wallet_cluster,
                window_start_ts=open_order.window_start_ts,
                window_open_price=open_order.window_open_price,
                window_open_source=open_order.window_open_source,
                window_open_price_trusted=open_order.window_open_price_trusted,
                window_open_anchor_age_seconds=open_order.window_open_anchor_age_seconds,
                actual_window_return=open_order.actual_window_return,
                actual_move_regime=open_order.actual_move_regime,
                actual_move_side=open_order.actual_move_side,
                strategy_route=open_order.strategy_route,
                cluster_id=open_order.cluster_id,
                signal_epoch_id=open_order.signal_epoch_id,
                book_age_ms=open_order.book_age_ms,
                tick_size=open_order.tick_size,
                expected_fill_price=open_order.expected_fill_price,
                expected_cost=open_order.expected_cost,
                markout_1s=open_order.markout_1s,
                markout_5s=open_order.markout_5s,
                markout_30s=open_order.markout_30s,
                raw_response=event_snapshot.raw,
            )

        order_payload = self._get_order_payload(open_order.order_id)
        raw_status = self._normalize_status((order_payload or {}).get("status")) or open_order.raw_status

        confirmed_shares, confirmed_cost, confirmed_fees, match_count = self._matching_trade_totals(open_order)
        confirmed_shares = max(confirmed_shares, open_order.confirmed_fill_shares)
        confirmed_cost = max(confirmed_cost, open_order.confirmed_fill_size)
        confirmed_fees = max(confirmed_fees, open_order.confirmed_fees)

        delta_shares = max(confirmed_shares - open_order.confirmed_fill_shares, 0.0)
        delta_cost = max(confirmed_cost - open_order.confirmed_fill_size, 0.0)
        delta_fees = max(confirmed_fees - open_order.confirmed_fees, 0.0)

        matched_shares = confirmed_shares
        original_shares = open_order.requested_shares
        if order_payload:
            original_shares = _safe_float(order_payload.get("original_size"), open_order.requested_shares)
            matched_shares = max(
                matched_shares,
                _safe_float(order_payload.get("size_matched"), confirmed_shares),
            )

        terminal_statuses = {"cancelled", "canceled", "filled", "confirmed", "failed", "rejected", "expired"}
        terminal = raw_status in terminal_statuses
        remaining_shares = max(original_shares - matched_shares, 0.0)
        if terminal and raw_status in {"cancelled", "canceled", "failed", "rejected", "expired"}:
            remaining_shares = 0.0
        remaining_size = remaining_shares * open_order.limit_price

        if remaining_shares <= 1e-9 and (confirmed_shares > 0 or terminal):
            terminal = True

        if delta_shares > 0:
            status = "filled" if remaining_shares <= 1e-9 else "partial"
        elif terminal and confirmed_shares <= 1e-9:
            status = "cancelled" if "cancel" in raw_status else "rejected"
        elif confirmed_shares > 0 and remaining_shares <= 1e-9:
            status = "filled"
        elif confirmed_shares > 0:
            status = "partial"
        else:
            status = "submitted"

        cancel_reason = ""
        if not terminal and delta_shares <= 0:
            cancel_reason = self._cancel_quote_reason(open_order)
            if cancel_reason and self.cancel_order(open_order.order_id):
                terminal = True
                status = "cancelled"
                remaining_shares = 0.0
                remaining_size = 0.0

        fill_price = open_order.limit_price
        if delta_shares > 0:
            fill_price = delta_cost / delta_shares

        latency_ms = (time.time() - t0) * 1000
        return OrderResult(
            filled=delta_shares > 0,
            fill_price=fill_price,
            fill_size=delta_cost,
            fees=delta_fees,
            slippage=fill_price - open_order.limit_price if delta_shares > 0 else 0.0,
            latency_ms=latency_ms,
            order_id=open_order.order_id,
            status=status,
            reason=cancel_reason,
            fill_shares=delta_shares,
            remaining_size=remaining_size,
            remaining_shares=remaining_shares,
            reserved_size=remaining_size,
            requested_size=open_order.requested_size,
            requested_shares=open_order.requested_shares,
            token_id=open_order.token_id,
            needs_reconciliation=not terminal,
            terminal=terminal,
            raw_status=raw_status,
            edge_gross=open_order.edge_gross,
            edge_net=open_order.edge_net,
            reference_symbol=open_order.reference_symbol,
            reference_price=open_order.reference_price,
            best_bid=open_order.best_bid,
            best_ask=open_order.best_ask,
            spread=open_order.spread,
            decision_latency_ms=open_order.decision_latency_ms,
            thesis_id=open_order.thesis_id,
            cancel_reason=cancel_reason,
            strategy_mode=open_order.strategy_mode,
            model_up_probability=open_order.model_up_probability,
            selected_side_probability=open_order.selected_side_probability,
            interval_open=open_order.interval_open,
            interval_high=open_order.interval_high,
            interval_low=open_order.interval_low,
            interval_close=open_order.interval_close,
            interval_return=open_order.interval_return,
            late_return_60s=open_order.late_return_60s,
            late_return_20s=open_order.late_return_20s,
            body_ratio=open_order.body_ratio,
            wick_imbalance=open_order.wick_imbalance,
            candle_regime=open_order.candle_regime,
            trend_alignment=open_order.trend_alignment,
            market_yes_at_open=open_order.market_yes_at_open,
            market_yes_at_decision=open_order.market_yes_at_decision,
            market_yes_at_close=open_order.market_yes_at_close,
            contrarian_block_reason=open_order.contrarian_block_reason,
            wallet_signal_source=open_order.wallet_signal_source,
            wallet_lead_score=open_order.wallet_lead_score,
            wallet_cluster=open_order.wallet_cluster,
            window_start_ts=open_order.window_start_ts,
            window_open_price=open_order.window_open_price,
            window_open_source=open_order.window_open_source,
            window_open_price_trusted=open_order.window_open_price_trusted,
            window_open_anchor_age_seconds=open_order.window_open_anchor_age_seconds,
            actual_window_return=open_order.actual_window_return,
            actual_move_regime=open_order.actual_move_regime,
            actual_move_side=open_order.actual_move_side,
            strategy_route=open_order.strategy_route,
            cluster_id=open_order.cluster_id,
            signal_epoch_id=open_order.signal_epoch_id,
            book_age_ms=open_order.book_age_ms,
            tick_size=open_order.tick_size,
            expected_fill_price=open_order.expected_fill_price,
            expected_cost=open_order.expected_cost,
            markout_1s=open_order.markout_1s,
            markout_5s=open_order.markout_5s,
            markout_30s=open_order.markout_30s,
            raw_response={
                "order": order_payload or {},
                "confirmed_trade_matches": match_count,
                "cancel_reason": cancel_reason,
            },
        )
