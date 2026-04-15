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

from config import (
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
    MAX_TAKER_FEE_RATE,
    OpenOrder,
    OrderResult,
    Signal,
)
from price_feed import get_reference_snapshot
from runtime_data import RUNTIME_DATA_PLANE

_COIN_RE = re.compile(r"^([a-z]+)-updown-", re.IGNORECASE)


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


class PaperExecutor(OrderExecutor):
    """Instant fill at quoted price with zero fees.

    Preserves the original paper trading behavior exactly.
    """

    def place_order(self, signal: Signal, size: float, entry_price: float) -> OrderResult:
        shares = size / entry_price if entry_price > 0 else 0.0
        token_index = 0 if signal.side == "YES" else 1
        token_id = signal.market.token_ids[token_index] if len(signal.market.token_ids) > token_index else ""
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
        token_index = 0 if signal.side == "YES" else 1
        token_id = signal.market.token_ids[token_index] if len(signal.market.token_ids) > token_index else ""

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

    def __init__(self, private_key: str, chain_id: int = 137, funder: str = None):
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OpenOrderParams, OrderArgs, OrderType, TradeParams

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
        self._OpenOrderParams = OpenOrderParams
        self._TradeParams = TradeParams

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
    def _floor_to_tick(price: float, tick_size: float) -> float:
        tick = max(tick_size, 0.01)
        floored = math.floor((price + 1e-9) / tick) * tick
        return round(max(tick, min(0.99, floored)), 2)

    def _get_book_snapshot(self, token_id: str) -> dict:
        cached = RUNTIME_DATA_PLANE.market_cache.snapshot(token_id)
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
        try:
            book = self._client.get_order_book(token_id)
        except Exception:
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
        token_idx = 0 if signal.side == "YES" else 1
        if token_idx >= len(signal.market.token_ids):
            return self._make_rejection(
                entry_price=entry_price,
                latency_ms=0.0,
                reason=f"no token_id for index {token_idx}",
                requested_size=size,
                requested_shares=0.0,
                metadata=metadata,
            )

        token_id = signal.market.token_ids[token_idx]

        book_snapshot = self._get_book_snapshot(token_id)
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

        min_shares = 5.0
        shares = max(round(size / limit_price, 2), min_shares)
        actual_size = round(shares * limit_price, 2)

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
