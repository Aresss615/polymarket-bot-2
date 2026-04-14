"""Order execution abstraction.

Three modes:
- PaperExecutor: instant fill at quoted price, zero fees (current behavior)
- SimulationExecutor: realistic fills with fees, slippage, partial fills
- LiveExecutor: stub for real CLOB execution (not yet implemented)
"""

import random
import uuid
from abc import ABC, abstractmethod

from config import OrderResult, Signal, MAX_TAKER_FEE_RATE


class OrderExecutor(ABC):
    """Base class for order execution."""

    @abstractmethod
    def place_order(self, signal: Signal, size: float, entry_price: float) -> OrderResult:
        """Execute an order and return the result."""


class PaperExecutor(OrderExecutor):
    """Instant fill at quoted price with zero fees.

    Preserves the original paper trading behavior exactly.
    """

    def place_order(self, signal: Signal, size: float, entry_price: float) -> OrderResult:
        return OrderResult(
            filled=True,
            fill_price=entry_price,
            fill_size=size,
            fees=0.0,
            slippage=0.0,
            latency_ms=0.0,
            order_id=f"paper-{uuid.uuid4().hex[:8]}",
            status="filled",
        )


def polymarket_taker_fee(price: float) -> float:
    """Estimate Polymarket dynamic taker fee rate.

    Fee is highest (1.8%) at price 0.50 and decreases toward extremes.
    Formula: fee_rate = MAX_TAKER_FEE_RATE * (1 - 2 * |price - 0.50|)
    Examples: price 0.50 → 1.8%, price 0.75 → 0.9%, price 0.85 → 0.54%
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
            )

        # Fee calculation
        fee_rate = polymarket_taker_fee(entry_price)
        fees = size * fee_rate

        # Adverse slippage: 0.5-1.5% of entry price
        slippage_pct = self._rng.uniform(0.005, 0.015)
        # Slippage always makes the fill worse (higher price for buys)
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

        # Adjust fees for actual fill size
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
        )


class LiveExecutor(OrderExecutor):
    """Real CLOB execution via py-clob-client.

    Places aggressive limit orders (market-taking) on the Polymarket CLOB.
    Requires:
    - POLYMARKET_PRIVATE_KEY env var (EOA private key)
    - Wallet funded with USDC.e on Polygon
    - At least one manual trade completed on polymarket.com UI
    """

    def __init__(self, private_key: str, chain_id: int = 137, funder: str = None):
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs, OrderType

        self._client = ClobClient(
            "https://clob.polymarket.com",
            key=private_key,
            chain_id=chain_id,
            signature_type=2 if funder else 0,
            funder=funder,
        )
        self._client.set_api_creds(self._client.create_or_derive_api_creds())
        self._OrderArgs = OrderArgs
        self._OrderType = OrderType

    def place_order(self, signal: Signal, size: float, entry_price: float) -> OrderResult:
        import time as _time

        def _is_fok_full_fill_error(detail: str) -> bool:
            text = str(detail).lower()
            return (
                "fok" in text
                and "fully filled" in text
                and "killed" in text
            )

        def _error_text(payload) -> str:
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

        token_idx = 0 if signal.side == "YES" else 1
        if token_idx >= len(signal.market.token_ids):
            return OrderResult(
                filled=False, fill_price=entry_price, fill_size=0.0,
                fees=0.0, slippage=0.0, latency_ms=0.0,
                order_id="", status="rejected",
                reason=f"no token_id for index {token_idx}",
            )

        token_id = signal.market.token_ids[token_idx]

        # Aggressive limit: set price slightly above market to ensure fill
        limit_price = round(min(entry_price + 0.02, 0.99), 2)

        # Size in shares: USDC amount / price
        # Polymarket minimum order size is 5 shares
        estimated_shares = size / limit_price
        if estimated_shares < 0.1:
            return OrderResult(
                filled=False,
                fill_price=entry_price,
                fill_size=0.0,
                fees=0.0,
                slippage=0.0,
                latency_ms=0.0,
                order_id="",
                status="rejected",
                reason=f"shares too small ({estimated_shares:.3f} < 0.1)",
            )

        MIN_SHARES = 5.0
        shares = max(round(size / limit_price, 2), MIN_SHARES)
        # Recalculate actual USDC cost from adjusted shares
        actual_size = round(shares * limit_price, 2)

        t0 = _time.time()
        signed_order = None
        try:
            order_args = self._OrderArgs(
                token_id=token_id,
                price=limit_price,
                size=shares,
                side="BUY",
            )
            signed_order = self._client.create_order(order_args)
            resp = self._client.post_order(signed_order, self._OrderType.FOK)

            # FOK rejects if full size cannot fill instantly. Retry with GTC so
            # aggressive orders can still execute instead of being hard-killed.
            if _is_fok_full_fill_error(_error_text(resp)):
                resp = self._client.post_order(signed_order, self._OrderType.GTC)

            latency_ms = (_time.time() - t0) * 1000

            if isinstance(resp, dict) and (resp.get("success") or resp.get("orderID")):
                order_id = resp.get("orderID", resp.get("id", "unknown"))
                fee_rate = polymarket_taker_fee(limit_price)
                fees = actual_size * fee_rate

                return OrderResult(
                    filled=True,
                    fill_price=limit_price,
                    fill_size=actual_size,
                    fees=fees,
                    slippage=limit_price - entry_price,
                    latency_ms=latency_ms,
                    order_id=str(order_id),
                    status="filled",
                )
            else:
                return OrderResult(
                    filled=False, fill_price=entry_price, fill_size=0.0,
                    fees=0.0, slippage=0.0, latency_ms=latency_ms,
                    order_id="", status="rejected",
                    reason=_error_text(resp),
                )
        except Exception as e:
            # Retry once if the failure text matches the known FOK full-fill
            # rejection, regardless of whether the client raised or returned it.
            err_detail = _error_text(e)
            if signed_order is not None and _is_fok_full_fill_error(err_detail):
                try:
                    resp = self._client.post_order(signed_order, self._OrderType.GTC)
                    latency_ms = (_time.time() - t0) * 1000
                    if isinstance(resp, dict) and (resp.get("success") or resp.get("orderID")):
                        order_id = resp.get("orderID", resp.get("id", "unknown"))
                        fee_rate = polymarket_taker_fee(limit_price)
                        fees = actual_size * fee_rate
                        return OrderResult(
                            filled=True,
                            fill_price=limit_price,
                            fill_size=actual_size,
                            fees=fees,
                            slippage=limit_price - entry_price,
                            latency_ms=latency_ms,
                            order_id=str(order_id),
                            status="filled",
                        )
                    err_detail = _error_text(resp)
                except Exception as retry_error:
                    err_detail = _error_text(retry_error)

            latency_ms = (_time.time() - t0) * 1000
            return OrderResult(
                filled=False, fill_price=entry_price, fill_size=0.0,
                fees=0.0, slippage=0.0, latency_ms=latency_ms,
                order_id="", status="rejected",
                reason=err_detail,
            )
