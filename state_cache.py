from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_datetime(value: datetime | float | None) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (float, int)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    return _utc_now()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_levels(levels: list[Any] | None) -> list[tuple[float, float]]:
    normalized: list[tuple[float, float]] = []
    for level in levels or []:
        if isinstance(level, dict):
            price = _safe_float(level.get("price"))
            size = _safe_float(level.get("size", level.get("quantity", 0.0)))
        elif isinstance(level, (list, tuple)) and len(level) >= 2:
            price = _safe_float(level[0])
            size = _safe_float(level[1])
        else:
            continue
        if price <= 0 or size < 0:
            continue
        normalized.append((price, size))
    return normalized


@dataclass
class MarketState:
    token_id: str
    market_slug: str = ""
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    midpoint: float | None = None
    microprice: float | None = None
    top_obi: float | None = None
    top3_obi: float | None = None
    tick_size: float | None = None
    updated_at: datetime | None = None
    source: str = ""
    resolved: bool = False


@dataclass
class ReferenceState:
    symbol: str
    price: float | None = None
    chainlink_price: float | None = None
    updated_at: datetime | None = None
    chainlink_updated_at: datetime | None = None
    source: str = ""


class MarketStateCache:
    def __init__(self):
        self._states: dict[str, MarketState] = {}
        self._last_heartbeat: datetime | None = None

    def update_from_book(
        self,
        token_id: str,
        bids: list[Any] | None,
        asks: list[Any] | None,
        *,
        market_slug: str = "",
        source: str = "book",
        timestamp: datetime | float | None = None,
        tick_size: float | None = None,
    ) -> MarketState:
        bid_levels = _normalize_levels(bids)
        ask_levels = _normalize_levels(asks)
        best_bid = bid_levels[0][0] if bid_levels else None
        best_ask = ask_levels[0][0] if ask_levels else None
        spread = None
        midpoint = None
        microprice = None
        top_obi = None
        top3_obi = None

        if best_bid is not None and best_ask is not None:
            spread = max(best_ask - best_bid, 0.0)
            midpoint = (best_bid + best_ask) / 2.0

        top_bid_size = bid_levels[0][1] if bid_levels else 0.0
        top_ask_size = ask_levels[0][1] if ask_levels else 0.0
        top_total = top_bid_size + top_ask_size
        if best_bid is not None and best_ask is not None and top_total > 0:
            microprice = ((best_ask * top_bid_size) + (best_bid * top_ask_size)) / top_total
            top_obi = (top_bid_size - top_ask_size) / top_total

        bid3 = sum(size for _, size in bid_levels[:3])
        ask3 = sum(size for _, size in ask_levels[:3])
        total3 = bid3 + ask3
        if total3 > 0:
            top3_obi = (bid3 - ask3) / total3

        state = self._states.get(token_id, MarketState(token_id=token_id))
        state.market_slug = market_slug or state.market_slug
        state.best_bid = best_bid
        state.best_ask = best_ask
        state.spread = spread
        state.midpoint = midpoint
        state.microprice = microprice
        state.top_obi = top_obi
        state.top3_obi = top3_obi
        state.tick_size = tick_size if tick_size is not None else state.tick_size
        state.updated_at = _to_datetime(timestamp)
        state.source = source
        self._states[token_id] = state
        self._last_heartbeat = state.updated_at
        return state

    def update_best_bid_ask(
        self,
        token_id: str,
        *,
        best_bid: float | None,
        best_ask: float | None,
        market_slug: str = "",
        source: str = "best_bid_ask",
        timestamp: datetime | float | None = None,
        tick_size: float | None = None,
    ) -> MarketState:
        state = self._states.get(token_id, MarketState(token_id=token_id))
        state.market_slug = market_slug or state.market_slug
        state.best_bid = best_bid
        state.best_ask = best_ask
        if best_bid is not None and best_ask is not None:
            state.spread = max(best_ask - best_bid, 0.0)
            state.midpoint = (best_bid + best_ask) / 2.0
        state.tick_size = tick_size if tick_size is not None else state.tick_size
        state.updated_at = _to_datetime(timestamp)
        state.source = source
        self._states[token_id] = state
        self._last_heartbeat = state.updated_at
        return state

    def update_tick_size(
        self,
        token_id: str,
        *,
        tick_size: float,
        market_slug: str = "",
        source: str = "tick_size_change",
        timestamp: datetime | float | None = None,
    ) -> MarketState:
        state = self._states.get(token_id, MarketState(token_id=token_id))
        state.market_slug = market_slug or state.market_slug
        state.tick_size = tick_size
        state.updated_at = _to_datetime(timestamp)
        state.source = source
        self._states[token_id] = state
        self._last_heartbeat = state.updated_at
        return state

    def mark_resolved(self, token_id: str, *, timestamp: datetime | float | None = None) -> None:
        state = self._states.get(token_id, MarketState(token_id=token_id))
        state.resolved = True
        state.updated_at = _to_datetime(timestamp)
        self._states[token_id] = state
        self._last_heartbeat = state.updated_at

    def get(self, token_id: str) -> MarketState | None:
        return self._states.get(token_id)

    def snapshot(self, token_id: str) -> dict[str, float | str | bool | None]:
        state = self.get(token_id)
        if not state:
            return {}
        return {
            "token_id": state.token_id,
            "market_slug": state.market_slug,
            "best_bid": state.best_bid,
            "best_ask": state.best_ask,
            "spread": state.spread,
            "midpoint": state.midpoint,
            "microprice": state.microprice,
            "top_obi": state.top_obi,
            "top3_obi": state.top3_obi,
            "tick_size": state.tick_size,
            "resolved": state.resolved,
            "book_age_ms": None if state.updated_at is None else max((_utc_now() - state.updated_at).total_seconds() * 1000.0, 0.0),
        }

    def age_seconds(self, token_id: str) -> float | None:
        state = self._states.get(token_id)
        if not state or not state.updated_at:
            return None
        return max((_utc_now() - state.updated_at).total_seconds(), 0.0)

    def feed_healthy(self, max_age_seconds: float) -> bool:
        if self._last_heartbeat is None:
            return False
        return (_utc_now() - self._last_heartbeat).total_seconds() <= max_age_seconds


class ReferenceStateCache:
    def __init__(self, history_limit: int = 600):
        self._states: dict[str, ReferenceState] = {}
        self._history: dict[str, deque[tuple[datetime, float]]] = {}
        self._chainlink_history: dict[str, deque[tuple[datetime, float]]] = {}
        self._last_heartbeat: datetime | None = None
        self._history_limit = history_limit

    def update(
        self,
        symbol: str,
        price: float,
        *,
        source: str = "poll",
        chainlink: bool = False,
        timestamp: datetime | float | None = None,
    ) -> ReferenceState:
        symbol = symbol.upper()
        ts = _to_datetime(timestamp)
        state = self._states.get(symbol, ReferenceState(symbol=symbol))
        if chainlink:
            state.chainlink_price = price
            state.chainlink_updated_at = ts
            history = self._chainlink_history.setdefault(symbol, deque(maxlen=self._history_limit))
            history.append((ts, price))
        else:
            state.price = price
            state.updated_at = ts
            history = self._history.setdefault(symbol, deque(maxlen=self._history_limit))
            history.append((ts, price))
        state.source = source
        self._states[symbol] = state
        self._last_heartbeat = ts
        return state

    def get(self, symbol: str) -> ReferenceState | None:
        return self._states.get(symbol.upper())

    def price(self, symbol: str, *, prefer_chainlink: bool = False) -> float | None:
        state = self.get(symbol)
        if not state:
            return None
        if prefer_chainlink and state.chainlink_price is not None:
            return state.chainlink_price
        return state.price if state.price is not None else state.chainlink_price

    def age_seconds(self, symbol: str, *, prefer_chainlink: bool = False) -> float | None:
        state = self.get(symbol)
        if not state:
            return None
        ts = state.chainlink_updated_at if prefer_chainlink and state.chainlink_updated_at else state.updated_at
        if ts is None:
            return None
        return max((_utc_now() - ts).total_seconds(), 0.0)

    def _history_points(
        self,
        symbol: str,
        *,
        prefer_chainlink: bool = False,
        fallback_to_spot: bool = True,
    ) -> list[tuple[datetime, float]]:
        symbol = symbol.upper()
        if prefer_chainlink:
            chainlink_history = list(self._chainlink_history.get(symbol, ()))
            if chainlink_history:
                return chainlink_history
            if not fallback_to_spot:
                return []
        return list(self._history.get(symbol, ()))

    @staticmethod
    def _nearest_history_point(
        history: list[tuple[datetime, float]],
        *,
        target_timestamp: float,
    ) -> tuple[datetime, float] | None:
        nearest: tuple[datetime, float] | None = None
        best_diff = float("inf")
        for ts, price in history:
            diff = abs(ts.timestamp() - target_timestamp)
            if diff < best_diff:
                nearest = (ts, price)
                best_diff = diff
        return nearest

    def window_anchor(
        self,
        symbol: str,
        *,
        target_timestamp: float,
        tolerance_seconds: float,
        prefer_chainlink: bool = False,
        allow_spot_fallback: bool = True,
    ) -> dict[str, float | str | bool | None]:
        source_name = "chainlink" if prefer_chainlink else "rtds"
        history = self._history_points(
            symbol,
            prefer_chainlink=prefer_chainlink,
            fallback_to_spot=allow_spot_fallback,
        )
        used_fallback = prefer_chainlink and not self._chainlink_history.get(symbol.upper()) and allow_spot_fallback
        if not history:
            return {
                "price": None,
                "timestamp": None,
                "source": "rtds_spot" if used_fallback else source_name,
                "trusted": False,
                "anchor_age_seconds": None,
            }

        nearest = self._nearest_history_point(history, target_timestamp=target_timestamp)
        if nearest is None:
            return {
                "price": None,
                "timestamp": None,
                "source": "rtds_spot" if used_fallback else source_name,
                "trusted": False,
                "anchor_age_seconds": None,
            }

        nearest_ts, nearest_price = nearest
        anchor_age_seconds = abs(nearest_ts.timestamp() - target_timestamp)
        source = "rtds_spot" if used_fallback else source_name
        return {
            "price": nearest_price,
            "timestamp": nearest_ts.timestamp(),
            "source": source,
            "trusted": anchor_age_seconds <= tolerance_seconds,
            "anchor_age_seconds": anchor_age_seconds,
        }

    def return_over_window(
        self,
        symbol: str,
        *,
        window_seconds: float,
        prefer_chainlink: bool = False,
        fallback_to_spot: bool = True,
    ) -> float | None:
        history = self._history_points(
            symbol,
            prefer_chainlink=prefer_chainlink,
            fallback_to_spot=fallback_to_spot,
        )
        if len(history) < 2:
            return None
        latest_ts, latest_price = history[-1]
        target_ts = latest_ts.timestamp() - window_seconds

        anchor_price = None
        for ts, price in reversed(history):
            if ts.timestamp() <= target_ts:
                anchor_price = price
                break
        if anchor_price is None:
            anchor_price = history[0][1]

        if anchor_price <= 0:
            return None
        return (latest_price - anchor_price) / anchor_price

    def ohlc_over_window(
        self,
        symbol: str,
        *,
        window_seconds: float,
        prefer_chainlink: bool = False,
        fallback_to_spot: bool = True,
    ) -> dict[str, float | None]:
        history = self._history_points(
            symbol,
            prefer_chainlink=prefer_chainlink,
            fallback_to_spot=fallback_to_spot,
        )
        if len(history) < 2:
            return {
                "open": None,
                "high": None,
                "low": None,
                "close": None,
                "start_timestamp": None,
                "end_timestamp": None,
                "samples": 0,
            }

        latest_ts, latest_price = history[-1]
        target_ts = latest_ts.timestamp() - window_seconds

        anchor_index = 0
        for index in range(len(history) - 1, -1, -1):
            if history[index][0].timestamp() <= target_ts:
                anchor_index = index
                break

        window_points = history[anchor_index:]
        if len(window_points) < 2:
            return {
                "open": None,
                "high": None,
                "low": None,
                "close": None,
                "start_timestamp": None,
                "end_timestamp": latest_ts,
                "samples": len(window_points),
            }

        prices = [price for _, price in window_points]
        return {
            "open": window_points[0][1],
            "high": max(prices),
            "low": min(prices),
            "close": latest_price,
            "start_timestamp": window_points[0][0],
            "end_timestamp": latest_ts,
            "samples": len(window_points),
        }

    def candle_features(
        self,
        symbol: str,
        *,
        window_seconds: float,
        late_windows: tuple[float, float] = (60.0, 20.0),
        prefer_chainlink: bool = False,
        fallback_to_spot: bool = True,
    ) -> dict[str, float | None]:
        ohlc = self.ohlc_over_window(
            symbol,
            window_seconds=window_seconds,
            prefer_chainlink=prefer_chainlink,
            fallback_to_spot=fallback_to_spot,
        )
        interval_open = ohlc["open"]
        interval_high = ohlc["high"]
        interval_low = ohlc["low"]
        interval_close = ohlc["close"]

        interval_return = None
        if interval_open not in (None, 0.0) and interval_close is not None:
            interval_return = (interval_close - interval_open) / interval_open

        body_ratio = None
        wick_imbalance = None
        if None not in (interval_open, interval_high, interval_low, interval_close):
            price_range = max((interval_high or 0.0) - (interval_low or 0.0), 0.0)
            if price_range > 1e-12:
                body = abs((interval_close or 0.0) - (interval_open or 0.0))
                upper_wick = max((interval_high or 0.0) - max(interval_open or 0.0, interval_close or 0.0), 0.0)
                lower_wick = max(min(interval_open or 0.0, interval_close or 0.0) - (interval_low or 0.0), 0.0)
                body_ratio = body / price_range
                wick_imbalance = (upper_wick - lower_wick) / price_range
            else:
                body_ratio = 0.0
                wick_imbalance = 0.0

        late_60 = self.return_over_window(
            symbol,
            window_seconds=late_windows[0],
            prefer_chainlink=prefer_chainlink,
            fallback_to_spot=fallback_to_spot,
        )
        late_20 = self.return_over_window(
            symbol,
            window_seconds=late_windows[1],
            prefer_chainlink=prefer_chainlink,
            fallback_to_spot=fallback_to_spot,
        )

        return {
            "interval_open": interval_open,
            "interval_high": interval_high,
            "interval_low": interval_low,
            "interval_close": interval_close,
            "interval_return": interval_return,
            "late_return_60s": late_60,
            "late_return_20s": late_20,
            "body_ratio": body_ratio,
            "wick_imbalance": wick_imbalance,
            "history_samples": ohlc["samples"],
        }

    def rolling_return_zscore(
        self,
        symbol: str,
        *,
        window_seconds: float,
        prefer_chainlink: bool = False,
        fallback_to_spot: bool = True,
    ) -> float | None:
        history = self._history_points(
            symbol,
            prefer_chainlink=prefer_chainlink,
            fallback_to_spot=fallback_to_spot,
        )
        if len(history) < 6:
            return None

        returns: list[float] = []
        for index in range(1, len(history)):
            current_ts, current_price = history[index]
            target_ts = current_ts.timestamp() - window_seconds
            anchor_price = None
            for back_index in range(index - 1, -1, -1):
                anchor_ts, candidate_price = history[back_index]
                if anchor_ts.timestamp() <= target_ts:
                    anchor_price = candidate_price
                    break
            if anchor_price is None or anchor_price <= 0:
                continue
            returns.append((current_price - anchor_price) / anchor_price)

        if len(returns) < 5:
            return None
        sigma = pstdev(returns)
        if sigma <= 1e-9:
            return 0.0
        latest_return = returns[-1]
        return (latest_return - mean(returns)) / sigma

    def feed_healthy(self, max_age_seconds: float) -> bool:
        if self._last_heartbeat is None:
            return False
        return (_utc_now() - self._last_heartbeat).total_seconds() <= max_age_seconds


MARKET_CACHE = MarketStateCache()
REFERENCE_CACHE = ReferenceStateCache(history_limit=1200)
