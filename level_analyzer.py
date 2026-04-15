"""Deterministic analysis for crypto up/down interval markets."""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from config import (
    ACTUAL_MOVE_CANDIDATE_MAX_PRICE,
    ACTUAL_MOVE_EDGE_COST_MULTIPLE,
    ACTUAL_MOVE_FLAT_RETURN_15M,
    ACTUAL_MOVE_FLAT_RETURN_5M,
    ACTUAL_MOVE_HIGH_PROB_UPPER,
    ACTUAL_MOVE_MAX_BOOK_AGE_MS,
    ACTUAL_MOVE_MAX_SPREAD,
    ACTUAL_MOVE_STRONG_RETURN_15M,
    ACTUAL_MOVE_STRONG_RETURN_5M,
    BTC_NO_STRATEGY_MODE,
    BTC_TOXIC_FLOW_EXTRA_EDGE,
    BTC_TOXIC_FLOW_SIZE_MULTIPLIER,
    BTC_TOXIC_FLOW_STRONG_ZSCORE,
    BTC_TOXIC_FLOW_WEAK_ZSCORE,
    CANCELLATION_COST_BUDGET,
    CANDIDATE_COINS,
    CANDIDATE_MIN_ENTRY_PRICE,
    CHAINLINK_REQUIRED_15M,
    COIN_CLUSTERS,
    COST_CLEARING_MULTIPLIER,
    CRYPTO_NEAR_CERTAIN_LOWER,
    CRYPTO_NEAR_CERTAIN_UPPER,
    CRYPTO_SHADOW_ONLY_LOWER,
    CRYPTO_SHADOW_ONLY_UPPER,
    EXTREME_PRICE_SIZE_CAP_MULTIPLIER,
    LIVE_CONFIDENCE_CAP,
    LIVE_MAKER_MAX_SPREAD,
    MAX_REFERENCE_AGE_SECONDS,
    MAX_TAKER_FEE_RATE,
    MIN_EDGE,
    MIN_EDGE_15M_CLOSE,
    MIN_EDGE_15M_MID,
    MIN_EDGE_NEUTRAL,
    MIN_SECONDS_TO_TRADE_15M,
    MIN_SECONDS_TO_TRADE_5M,
    NO_SIDE_EDGE_PREMIUM,
    NON_STRONG_CONFIDENCE_CAP,
    REFERENCE_PRICE_NEUTRAL_BAND,
    REFERENCE_RETURN_PROBABILITY_SCALE_15M,
    REFERENCE_RETURN_PROBABILITY_SCALE_5M,
    SLIPPAGE_BUDGET,
    SHADOW_ONLY_COINS,
    STRATEGY_MODE_DISABLED,
    STRATEGY_MODE_LIVE,
    STRATEGY_MODE_SHADOW,
    TREND_MIXED_MAX_BODY_RATIO,
    TREND_MIXED_SIZE_MULTIPLIER,
    TREND_STRONG_FOLLOW_SIZE_MULTIPLIER,
    TREND_STRONG_INTERVAL_RETURN_15M,
    TREND_STRONG_INTERVAL_RETURN_5M,
    TREND_STRONG_LATE_RETURN_20S_15M,
    TREND_STRONG_LATE_RETURN_20S_5M,
    TREND_STRONG_LATE_RETURN_60S_15M,
    TREND_STRONG_LATE_RETURN_60S_5M,
    TREND_STRONG_MIN_BODY_RATIO,
    UNCERTAIN_INTERVAL_RETURN_15M,
    UNCERTAIN_INTERVAL_RETURN_5M,
    UNCERTAIN_SIZE_MULTIPLIER,
    WINDOW_OPEN_TRUST_TOLERANCE_SECONDS,
    Signal,
    UPDOWN_15M_STRATEGY_MODE,
    UPDOWN_5M_STRATEGY_MODE,
    UpDownMarket,
    normalize_strategy_mode,
)
from price_feed import get_price_momentum, get_reference_snapshot, is_price_stale
from state_cache import MARKET_CACHE

log = logging.getLogger(__name__)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _sign(value: float | None, epsilon: float = 1e-12) -> int:
    if value is None or abs(value) <= epsilon:
        return 0
    return 1 if value > 0 else -1


def _polymarket_taker_fee(price: float) -> float:
    return max(0.0, MAX_TAKER_FEE_RATE * (1.0 - 2.0 * abs(price - 0.50)))


@dataclass
class UpdownAnalysis:
    """Structured analysis result for monitoring, telemetry, and execution."""

    udm: UpDownMarket
    signal: Signal | None
    reason: str
    decision_stage: str
    seconds_to_close: float
    implied_up_prob: float | None = None
    model_up_prob: float | None = None
    signal_side: str = ""
    direction: str = ""
    confidence: float = 0.0
    entry_price: float | None = None
    raw_edge: float | None = None
    effective_edge: float | None = None
    estimated_fee: float | None = None
    min_edge: float | None = None
    momentum: float | None = None
    price_state: str = "unknown"
    strategy_mode: str = STRATEGY_MODE_DISABLED
    reference_age_seconds: float | None = None
    reference_zscore: float | None = None
    size_multiplier: float = 1.0
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    decision_latency_ms: float = 0.0
    thesis_id: str = ""
    selected_side_probability: float | None = None
    interval_open: float | None = None
    interval_high: float | None = None
    interval_low: float | None = None
    interval_close: float | None = None
    interval_return: float | None = None
    late_return_60s: float | None = None
    late_return_20s: float | None = None
    body_ratio: float | None = None
    wick_imbalance: float | None = None
    candle_regime: str = ""
    trend_alignment: str = ""
    market_yes_at_open: float | None = None
    market_yes_at_decision: float | None = None
    market_yes_at_close: float | None = None
    contrarian_block_reason: str = ""
    wallet_signal_source: str = ""
    wallet_lead_score: float | None = None
    wallet_cluster: str = ""
    legacy_model_up_prob: float | None = None
    legacy_signal_side: str = ""
    window_start_ts: float | None = None
    window_open_price: float | None = None
    window_open_source: str = ""
    window_open_price_trusted: bool = False
    actual_window_return: float | None = None
    actual_move_regime: str = ""
    actual_move_side: str = ""
    strategy_route: str = ""

    def to_record(self) -> dict:
        market = self.udm.market
        up_price, down_price = _up_down_prices(self.udm)
        return {
            "strategy": "updown",
            "strategy_mode": self.strategy_mode,
            "coin": self.udm.coin,
            "question": market.question,
            "market_slug": market.slug,
            "market_type": f"{self.udm.interval_minutes}m",
            "interval_minutes": self.udm.interval_minutes,
            "seconds_to_close": round(self.seconds_to_close, 1),
            "signal_side": self.signal_side,
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "decision_stage": self.decision_stage,
            "reason": self.reason,
            "implied_up_prob": _round_or_none(self.implied_up_prob),
            "model_up_prob": _round_or_none(self.model_up_prob),
            "selected_side_probability": _round_or_none(self.selected_side_probability),
            "entry_price": _round_or_none(self.entry_price),
            "raw_edge": _round_or_none(self.raw_edge),
            "effective_edge": _round_or_none(self.effective_edge),
            "estimated_fee": _round_or_none(self.estimated_fee),
            "min_edge": _round_or_none(self.min_edge),
            "momentum": _round_or_none(self.momentum),
            "price_state": self.price_state,
            "reference_age_seconds": _round_or_none(self.reference_age_seconds),
            "reference_zscore": _round_or_none(self.reference_zscore),
            "size_multiplier": _round_or_none(self.size_multiplier),
            "best_bid": _round_or_none(self.best_bid),
            "best_ask": _round_or_none(self.best_ask),
            "spread": _round_or_none(self.spread),
            "decision_latency_ms": _round_or_none(self.decision_latency_ms),
            "thesis_id": self.thesis_id,
            "up_price": _round_or_none(up_price),
            "down_price": _round_or_none(down_price),
            "interval_open": _round_or_none(self.interval_open),
            "interval_high": _round_or_none(self.interval_high),
            "interval_low": _round_or_none(self.interval_low),
            "interval_close": _round_or_none(self.interval_close),
            "interval_return": _round_or_none(self.interval_return),
            "late_return_60s": _round_or_none(self.late_return_60s),
            "late_return_20s": _round_or_none(self.late_return_20s),
            "body_ratio": _round_or_none(self.body_ratio),
            "wick_imbalance": _round_or_none(self.wick_imbalance),
            "candle_regime": self.candle_regime,
            "trend_alignment": self.trend_alignment,
            "market_yes_at_open": _round_or_none(self.market_yes_at_open),
            "market_yes_at_decision": _round_or_none(self.market_yes_at_decision),
            "market_yes_at_close": _round_or_none(self.market_yes_at_close),
            "contrarian_block_reason": self.contrarian_block_reason,
            "wallet_signal_source": self.wallet_signal_source,
            "wallet_lead_score": _round_or_none(self.wallet_lead_score),
            "wallet_cluster": self.wallet_cluster,
            "legacy_model_up_prob": _round_or_none(self.legacy_model_up_prob),
            "legacy_signal_side": self.legacy_signal_side,
            "window_start_ts": _round_or_none(self.window_start_ts, digits=3),
            "window_open_price": _round_or_none(self.window_open_price),
            "window_open_source": self.window_open_source,
            "window_open_price_trusted": self.window_open_price_trusted,
            "actual_window_return": _round_or_none(self.actual_window_return),
            "actual_move_regime": self.actual_move_regime,
            "actual_move_side": self.actual_move_side,
            "strategy_route": self.strategy_route,
        }


def _round_or_none(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _up_down_prices(udm: UpDownMarket) -> tuple[float | None, float | None]:
    prices = udm.market.outcome_prices
    if len(prices) < 2:
        return None, None
    if udm.up_outcome_index == 0:
        return prices[0], prices[1]
    return prices[1], prices[0]


def _trade_direction(signal_side: str, up_outcome_index: int) -> str:
    if not signal_side:
        return ""
    predicts_up = (signal_side == "YES") == (up_outcome_index == 0)
    return "BUY" if predicts_up else "SELL"


def _build_analysis(
    udm: UpDownMarket,
    *,
    signal: Signal | None,
    reason: str,
    decision_stage: str,
    seconds_to_close: float,
    implied_up_prob: float | None = None,
    model_up_prob: float | None = None,
    signal_side: str = "",
    confidence: float = 0.0,
    entry_price: float | None = None,
    raw_edge: float | None = None,
    effective_edge: float | None = None,
    estimated_fee: float | None = None,
    min_edge: float | None = None,
    momentum: float | None = None,
    price_state: str = "unknown",
    strategy_mode: str = STRATEGY_MODE_DISABLED,
    reference_age_seconds: float | None = None,
    reference_zscore: float | None = None,
    size_multiplier: float = 1.0,
    best_bid: float | None = None,
    best_ask: float | None = None,
    spread: float | None = None,
    decision_latency_ms: float = 0.0,
    thesis_id: str = "",
    selected_side_probability: float | None = None,
    interval_open: float | None = None,
    interval_high: float | None = None,
    interval_low: float | None = None,
    interval_close: float | None = None,
    interval_return: float | None = None,
    late_return_60s: float | None = None,
    late_return_20s: float | None = None,
    body_ratio: float | None = None,
    wick_imbalance: float | None = None,
    candle_regime: str = "",
    trend_alignment: str = "",
    market_yes_at_open: float | None = None,
    market_yes_at_decision: float | None = None,
    market_yes_at_close: float | None = None,
    contrarian_block_reason: str = "",
    wallet_signal_source: str = "",
    wallet_lead_score: float | None = None,
    wallet_cluster: str = "",
    legacy_model_up_prob: float | None = None,
    legacy_signal_side: str = "",
    window_start_ts: float | None = None,
    window_open_price: float | None = None,
    window_open_source: str = "",
    window_open_price_trusted: bool = False,
    actual_window_return: float | None = None,
    actual_move_regime: str = "",
    actual_move_side: str = "",
    strategy_route: str = "",
) -> UpdownAnalysis:
    return UpdownAnalysis(
        udm=udm,
        signal=signal,
        reason=reason,
        decision_stage=decision_stage,
        seconds_to_close=seconds_to_close,
        implied_up_prob=implied_up_prob,
        model_up_prob=model_up_prob,
        signal_side=signal_side,
        direction=_trade_direction(signal_side, udm.up_outcome_index),
        confidence=confidence,
        entry_price=entry_price,
        raw_edge=raw_edge,
        effective_edge=effective_edge,
        estimated_fee=estimated_fee,
        min_edge=min_edge,
        momentum=momentum,
        price_state=price_state,
        strategy_mode=strategy_mode,
        reference_age_seconds=reference_age_seconds,
        reference_zscore=reference_zscore,
        size_multiplier=size_multiplier,
        best_bid=best_bid,
        best_ask=best_ask,
        spread=spread,
        decision_latency_ms=decision_latency_ms,
        thesis_id=thesis_id,
        selected_side_probability=selected_side_probability,
        interval_open=interval_open,
        interval_high=interval_high,
        interval_low=interval_low,
        interval_close=interval_close,
        interval_return=interval_return,
        late_return_60s=late_return_60s,
        late_return_20s=late_return_20s,
        body_ratio=body_ratio,
        wick_imbalance=wick_imbalance,
        candle_regime=candle_regime,
        trend_alignment=trend_alignment,
        market_yes_at_open=market_yes_at_open,
        market_yes_at_decision=market_yes_at_decision,
        market_yes_at_close=market_yes_at_close,
        contrarian_block_reason=contrarian_block_reason,
        wallet_signal_source=wallet_signal_source,
        wallet_lead_score=wallet_lead_score,
        wallet_cluster=wallet_cluster,
        legacy_model_up_prob=legacy_model_up_prob,
        legacy_signal_side=legacy_signal_side,
        window_start_ts=window_start_ts,
        window_open_price=window_open_price,
        window_open_source=window_open_source,
        window_open_price_trusted=window_open_price_trusted,
        actual_window_return=actual_window_return,
        actual_move_regime=actual_move_regime,
        actual_move_side=actual_move_side,
        strategy_route=strategy_route,
    )


def _reference_probability(reference_return: float, zscore: float | None, interval_minutes: int) -> float:
    scale = (
        REFERENCE_RETURN_PROBABILITY_SCALE_15M
        if interval_minutes == 15
        else REFERENCE_RETURN_PROBABILITY_SCALE_5M
    )
    zscore_component = 0.0 if zscore is None else _clamp(zscore, -3.0, 3.0) * 0.02
    probability = 0.5 + (reference_return / max(scale, 1e-9)) + zscore_component
    return _clamp(probability, 0.02, 0.98)


def _min_edge_for_setup(
    *,
    side: str,
    interval_minutes: int,
    seconds_to_close: float,
    interval_return: float,
) -> float:
    neutral_setup = abs(interval_return) < REFERENCE_PRICE_NEUTRAL_BAND
    if interval_minutes == 15:
        if seconds_to_close >= 180:
            threshold = MIN_EDGE_15M_MID
        else:
            threshold = MIN_EDGE_15M_CLOSE
    else:
        threshold = MIN_EDGE_NEUTRAL if neutral_setup else MIN_EDGE
    if side == "NO":
        threshold += NO_SIDE_EDGE_PREMIUM
    return threshold


def _strategy_mode_for_signal(udm: UpDownMarket, side: str) -> str:
    if udm.coin in SHADOW_ONLY_COINS or udm.interval_minutes == 15:
        mode = STRATEGY_MODE_SHADOW
    elif udm.coin in CANDIDATE_COINS:
        base = UPDOWN_15M_STRATEGY_MODE if udm.interval_minutes == 15 else UPDOWN_5M_STRATEGY_MODE
        mode = normalize_strategy_mode(base, STRATEGY_MODE_DISABLED)
    else:
        mode = STRATEGY_MODE_DISABLED
    if udm.coin == "BTC" and side == "NO":
        btc_mode = normalize_strategy_mode(BTC_NO_STRATEGY_MODE, STRATEGY_MODE_SHADOW)
        if mode == STRATEGY_MODE_LIVE and btc_mode != STRATEGY_MODE_LIVE:
            return btc_mode
    return mode


def _thesis_id(udm: UpDownMarket) -> str:
    bucket = "close" if udm.seconds_to_close <= 70 else "mid"
    return f"crypto-ref:{udm.coin}:{udm.interval_minutes}m:{bucket}"


def _cluster_id(coin: str) -> str:
    return COIN_CLUSTERS.get(coin, "crypto_other")


def _interval_thresholds(interval_minutes: int) -> tuple[float, float, float, float]:
    if interval_minutes == 15:
        return (
            TREND_STRONG_INTERVAL_RETURN_15M,
            TREND_STRONG_LATE_RETURN_60S_15M,
            TREND_STRONG_LATE_RETURN_20S_15M,
            UNCERTAIN_INTERVAL_RETURN_15M,
        )
    return (
        TREND_STRONG_INTERVAL_RETURN_5M,
        TREND_STRONG_LATE_RETURN_60S_5M,
        TREND_STRONG_LATE_RETURN_20S_5M,
        UNCERTAIN_INTERVAL_RETURN_5M,
    )


def _actual_move_thresholds(interval_minutes: int) -> tuple[float, float]:
    if interval_minutes == 15:
        return ACTUAL_MOVE_STRONG_RETURN_15M, ACTUAL_MOVE_FLAT_RETURN_15M
    return ACTUAL_MOVE_STRONG_RETURN_5M, ACTUAL_MOVE_FLAT_RETURN_5M


def _window_start_ts(udm: UpDownMarket) -> float | None:
    if udm.market.end_date is None:
        return None
    return udm.market.end_date.timestamp() - float(udm.interval_minutes * 60)


def _actual_move_regime(actual_window_return: float | None, interval_minutes: int) -> str:
    if actual_window_return is None:
        return ""
    strong_threshold, flat_threshold = _actual_move_thresholds(interval_minutes)
    magnitude = abs(actual_window_return)
    if magnitude >= strong_threshold:
        return "strong"
    if magnitude <= flat_threshold:
        return "flat"
    return "mid"


def _book_snapshot_for_side(market, side: str) -> dict:
    if not side or not market.token_ids:
        return {}
    selected_index = 0 if side == "YES" else 1
    if selected_index >= len(market.token_ids):
        return {}
    return MARKET_CACHE.snapshot(market.token_ids[selected_index])


def _reason_suffix(
    *,
    actual_window_return: float | None,
    late_return_60s: float | None,
    late_return_20s: float | None,
    body_ratio: float | None,
    window_open_source: str = "",
) -> str:
    parts: list[str] = []
    if actual_window_return is not None:
        parts.append(f"actual {actual_window_return:+.3%}")
    if late_return_60s is not None:
        parts.append(f"60s {late_return_60s:+.3%}")
    if late_return_20s is not None:
        parts.append(f"20s {late_return_20s:+.3%}")
    if body_ratio is not None:
        parts.append(f"body {body_ratio:.2f}")
    if window_open_source:
        parts.append(f"open {window_open_source}")
    return " | ".join(parts)


def _synthesize_candle_metrics(
    reference_price: float | None,
    interval_return: float | None,
) -> tuple[float | None, float | None, float | None, float | None]:
    if reference_price is None or interval_return is None:
        return None, None, None, None
    denominator = 1.0 + interval_return
    if abs(denominator) <= 1e-9:
        return None, None, None, None
    interval_close = reference_price
    interval_open = interval_close / denominator
    interval_high = max(interval_open, interval_close)
    interval_low = min(interval_open, interval_close)
    return interval_open, interval_high, interval_low, interval_close


def _normalize_reference_metrics(reference: dict, reference_price: float | None, reference_return: float | None) -> dict:
    interval_open = reference.get("interval_open")
    interval_high = reference.get("interval_high")
    interval_low = reference.get("interval_low")
    interval_close = reference.get("interval_close")
    interval_return = reference.get("interval_return", reference_return)
    late_return_60s = reference.get("late_return_60s", reference_return)
    late_return_20s = reference.get("late_return_20s", reference_return)
    body_ratio = reference.get("body_ratio")
    wick_imbalance = reference.get("wick_imbalance")

    if None in (interval_open, interval_high, interval_low, interval_close):
        synth_open, synth_high, synth_low, synth_close = _synthesize_candle_metrics(
            reference_price,
            interval_return,
        )
        interval_open = interval_open if interval_open is not None else synth_open
        interval_high = interval_high if interval_high is not None else synth_high
        interval_low = interval_low if interval_low is not None else synth_low
        interval_close = interval_close if interval_close is not None else synth_close

    if interval_close is None:
        interval_close = reference_price
    if interval_return is None and None not in (interval_open, interval_close) and interval_open not in (None, 0.0):
        interval_return = (interval_close - interval_open) / interval_open

    if body_ratio is None or wick_imbalance is None:
        if None not in (interval_open, interval_high, interval_low, interval_close):
            price_range = max((interval_high or 0.0) - (interval_low or 0.0), 0.0)
            if price_range > 1e-12:
                body = abs((interval_close or 0.0) - (interval_open or 0.0))
                upper_wick = max((interval_high or 0.0) - max(interval_open or 0.0, interval_close or 0.0), 0.0)
                lower_wick = max(min(interval_open or 0.0, interval_close or 0.0) - (interval_low or 0.0), 0.0)
                if body_ratio is None:
                    body_ratio = body / price_range
                if wick_imbalance is None:
                    wick_imbalance = (upper_wick - lower_wick) / price_range
            else:
                if body_ratio is None:
                    body_ratio = 0.0
                if wick_imbalance is None:
                    wick_imbalance = 0.0

    return {
        "interval_open": interval_open,
        "interval_high": interval_high,
        "interval_low": interval_low,
        "interval_close": interval_close,
        "interval_return": interval_return,
        "late_return_60s": late_return_60s,
        "late_return_20s": late_return_20s,
        "body_ratio": body_ratio,
        "wick_imbalance": wick_imbalance,
    }


def _classify_candle_regime(
    *,
    interval_return: float | None,
    late_return_60s: float | None,
    late_return_20s: float | None,
    body_ratio: float | None,
    interval_minutes: int,
) -> str:
    strong_interval, strong_late_60s, strong_late_20s, uncertain_interval = _interval_thresholds(interval_minutes)
    if interval_return is None or body_ratio is None:
        return "uncertain"
    if abs(interval_return) < uncertain_interval:
        return "uncertain"

    signs = (
        _sign(interval_return),
        _sign(late_return_60s),
        _sign(late_return_20s),
    )
    strong = (
        late_return_60s is not None
        and late_return_20s is not None
        and abs(interval_return) >= strong_interval
        and abs(late_return_60s) >= strong_late_60s
        and abs(late_return_20s) >= strong_late_20s
        and signs[0] != 0
        and signs[0] == signs[1] == signs[2]
        and body_ratio >= TREND_STRONG_MIN_BODY_RATIO
    )
    if strong:
        return "trend_strong"

    mixed = body_ratio < TREND_MIXED_MAX_BODY_RATIO
    if signs[0] != 0:
        if signs[1] != 0 and signs[1] != signs[0]:
            mixed = True
        if signs[2] != 0 and signs[2] != signs[0]:
            mixed = True
    if late_return_60s is not None and late_return_20s is not None:
        if _sign(late_return_60s) != 0 and _sign(late_return_20s) != 0 and _sign(late_return_60s) != _sign(late_return_20s):
            mixed = True
    return "trend_mixed" if mixed else "uncertain"


def _trend_side(reference_return: float | None) -> str:
    sign = _sign(reference_return)
    if sign > 0:
        return "YES"
    if sign < 0:
        return "NO"
    return ""


def _late_reversal_side(late_return_60s: float | None, late_return_20s: float | None) -> str:
    sign_60 = _sign(late_return_60s)
    sign_20 = _sign(late_return_20s)
    if sign_60 == 0 or sign_20 == 0 or sign_60 != sign_20:
        return ""
    return "YES" if sign_60 > 0 else "NO"


def _trend_alignment(
    *,
    candle_regime: str,
    side: str,
    interval_return: float | None,
    late_return_60s: float | None,
    late_return_20s: float | None,
) -> str:
    interval_side = _trend_side(interval_return)
    late_side = _late_reversal_side(late_return_60s, late_return_20s)
    if candle_regime == "trend_strong":
        return "follow_trend" if side == interval_side else "contrarian"
    if candle_regime == "trend_mixed":
        if late_side and interval_side and late_side != interval_side and side == late_side:
            return "late_reversal"
        if interval_side:
            return "follow_trend" if side == interval_side else "contrarian"
    return "uncertain_mispricing"


def _model_driver_return(
    interval_return: float | None,
    late_return_60s: float | None,
    late_return_20s: float | None,
    fallback_return: float | None,
) -> float | None:
    weighted_sum = 0.0
    total_weight = 0.0
    for value, weight in (
        (interval_return, 0.55),
        (late_return_60s, 0.30),
        (late_return_20s, 0.15),
        (fallback_return, 0.15),
    ):
        if value is None:
            continue
        weighted_sum += value * weight
        total_weight += weight
    if total_weight <= 0:
        return None
    return weighted_sum / total_weight


def _confidence_cap(candle_regime: str) -> float:
    if candle_regime == "trend_strong":
        return LIVE_CONFIDENCE_CAP
    return NON_STRONG_CONFIDENCE_CAP


def _confidence_score(
    *,
    edge_net: float,
    min_edge: float,
    interval_return: float | None,
    late_return_60s: float | None,
    late_return_20s: float | None,
    candle_regime: str,
    interval_minutes: int,
) -> float:
    strong_interval, strong_late_60s, strong_late_20s, uncertain_interval = _interval_thresholds(interval_minutes)
    edge_component = _clamp(edge_net / max(min_edge, 0.01), 0.0, 2.0) / 2.0
    interval_component = min(abs(interval_return or 0.0) / max(strong_interval, uncertain_interval, 1e-9), 1.5) / 1.5
    late_component = min(
        (
            abs(late_return_60s or 0.0) / max(strong_late_60s, 1e-9)
            + abs(late_return_20s or 0.0) / max(strong_late_20s, 1e-9)
        ) / 2.0,
        1.5,
    ) / 1.5

    confidence = 0.25 + 0.35 * edge_component + 0.20 * interval_component + 0.20 * late_component
    if candle_regime == "trend_mixed":
        confidence *= 0.85
    elif candle_regime == "uncertain":
        confidence *= 0.80
    return _clamp(confidence, 0.05, _confidence_cap(candle_regime))


def _size_multiplier(
    *,
    candle_regime: str,
    trend_alignment: str,
    strategy_mode: str,
    entry_price: float,
) -> float:
    if candle_regime == "trend_strong":
        size = TREND_STRONG_FOLLOW_SIZE_MULTIPLIER if trend_alignment == "follow_trend" else 0.0
    elif candle_regime == "trend_mixed":
        size = TREND_MIXED_SIZE_MULTIPLIER
    else:
        size = UNCERTAIN_SIZE_MULTIPLIER

    if strategy_mode == STRATEGY_MODE_LIVE and (entry_price < 0.10 or entry_price > 0.90):
        size = min(size, EXTREME_PRICE_SIZE_CAP_MULTIPLIER)
    return size


def _side_probability(side: str, model_up_prob: float) -> float:
    return model_up_prob if side == "YES" else (1.0 - model_up_prob)


def _side_aware_reason(
    *,
    coin: str,
    candle_regime: str,
    model_up_prob: float,
    side: str,
    selected_side_probability: float,
    market_price: float,
    edge_net: float,
    interval_return: float | None,
    late_return_60s: float | None,
    late_return_20s: float | None,
    seconds_to_close: float,
) -> str:
    detail_parts = []
    if interval_return is not None:
        detail_parts.append(f"interval {interval_return:+.3%}")
    if late_return_60s is not None:
        detail_parts.append(f"60s {late_return_60s:+.3%}")
    if late_return_20s is not None:
        detail_parts.append(f"20s {late_return_20s:+.3%}")
    detail_suffix = f", {' | '.join(detail_parts)}" if detail_parts else ""
    underpricing = selected_side_probability - market_price
    return (
        f"{coin} {candle_regime}, model UP {model_up_prob:.0%}; selected {side} {selected_side_probability:.0%} "
        f"vs market {market_price:.0%}; underpriced by {underpricing:.1%}, net edge {edge_net:.1%}, "
        f"{seconds_to_close:.0f}s to close{detail_suffix}"
    )


def _analyze_actual_move_first(
    udm: UpDownMarket,
    *,
    actual_seconds: float,
    up_price: float,
    down_price: float,
    strategy_mode: str,
    thesis_id: str,
    extra_min_edge: float,
    t0: float,
) -> UpdownAnalysis:
    coin = udm.coin
    market = udm.market
    window_start_ts = _window_start_ts(udm)
    reference = get_reference_snapshot(
        coin,
        interval_minutes=udm.interval_minutes,
        window_start_ts=window_start_ts,
        window_tolerance_seconds=WINDOW_OPEN_TRUST_TOLERANCE_SECONDS,
    )
    reference_price = reference.get("active_reference_price") or reference.get("price")
    reference_age = reference.get("active_reference_age_seconds")
    reference_return = reference.get("return_lookback")
    reference_zscore = reference.get("zscore")
    chainlink_price = reference.get("chainlink_price")
    chainlink_age = reference.get("chainlink_age_seconds")
    window_open_price = reference.get("window_open_price")
    window_open_source = reference.get("window_open_source") or ""
    window_open_price_trusted = bool(reference.get("window_open_price_trusted"))
    metrics = {
        "interval_open": None,
        "interval_high": None,
        "interval_low": None,
        "interval_close": None,
    }
    interval_return = None
    late_return_60s = None
    late_return_20s = None
    body_ratio = None
    wick_imbalance = None
    candle_regime = ""
    trend_alignment = ""
    best_bid = None
    best_ask = None
    spread = None
    book_age_ms = None
    tick_size = None
    model_up_prob = None
    selected_side_probability = None
    entry_price = None
    edge_gross = None
    edge_net = None
    estimated_fee = None
    min_edge = None
    size_multiplier = 1.0
    actual_window_return = None
    actual_move_regime = ""
    actual_move_side = ""
    strategy_route = ""
    legacy_model_up_prob = None
    legacy_signal_side = ""
    contrarian_block_reason = ""

    def build_skip(
        reason: str,
        *,
        price_state: str,
        signal_side: str = "",
        route: str = "",
        override_mode: str | None = None,
    ) -> UpdownAnalysis:
        blocked_state = price_state
        if contrarian_block_reason and price_state in {"strong_move_no_confirmation", "low_edge"}:
            blocked_state = "contrarian_block_actual_move"
        return _build_analysis(
            udm,
            signal=None,
            reason=reason,
            decision_stage="analysis_skip",
            seconds_to_close=actual_seconds,
            implied_up_prob=up_price,
            model_up_prob=model_up_prob if model_up_prob is not None else legacy_model_up_prob if legacy_model_up_prob is not None else up_price,
            signal_side=signal_side,
            entry_price=entry_price,
            raw_edge=edge_gross,
            effective_edge=edge_net,
            estimated_fee=estimated_fee,
            min_edge=min_edge,
            momentum=actual_window_return if actual_window_return is not None else interval_return,
            price_state=blocked_state,
            strategy_mode=override_mode or strategy_mode,
            reference_age_seconds=reference_age,
            reference_zscore=reference_zscore,
            size_multiplier=size_multiplier,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            decision_latency_ms=(time.time() - t0) * 1000,
            thesis_id=thesis_id,
            selected_side_probability=selected_side_probability,
            interval_open=metrics["interval_open"],
            interval_high=metrics["interval_high"],
            interval_low=metrics["interval_low"],
            interval_close=metrics["interval_close"],
            interval_return=interval_return,
            late_return_60s=late_return_60s,
            late_return_20s=late_return_20s,
            body_ratio=body_ratio,
            wick_imbalance=wick_imbalance,
            candle_regime=candle_regime,
            trend_alignment=trend_alignment,
            market_yes_at_decision=up_price,
            contrarian_block_reason=contrarian_block_reason,
            legacy_model_up_prob=legacy_model_up_prob,
            legacy_signal_side=legacy_signal_side,
            window_start_ts=window_start_ts,
            window_open_price=window_open_price,
            window_open_source=window_open_source,
            window_open_price_trusted=window_open_price_trusted,
            actual_window_return=actual_window_return,
            actual_move_regime=actual_move_regime,
            actual_move_side=actual_move_side,
            strategy_route=route or strategy_route,
        )

    if reference_price is None or reference_age is None or reference_age > MAX_REFERENCE_AGE_SECONDS:
        return build_skip(
            f"{coin} skip: reference data stale ({reference_age if reference_age is not None else 'na'}s)",
            price_state="stale",
        )
    if udm.interval_minutes == 15 and CHAINLINK_REQUIRED_15M:
        if chainlink_price is None or chainlink_age is None or chainlink_age > MAX_REFERENCE_AGE_SECONDS:
            return build_skip(f"{coin} skip: 15m requires fresh Chainlink reference", price_state="no_chainlink")
    if not window_open_price_trusted or window_open_price in (None, 0.0):
        return build_skip(
            f"{coin} skip: missing trusted exact window open",
            price_state="missing_exact_open",
            route="missing_exact_open",
        )

    actual_window_return = (reference_price - window_open_price) / window_open_price
    actual_move_regime = _actual_move_regime(actual_window_return, udm.interval_minutes)
    actual_move_side = _trend_side(actual_window_return)
    metrics = _normalize_reference_metrics(reference, reference_price, actual_window_return)
    interval_return = metrics["interval_return"]
    late_return_60s = metrics["late_return_60s"]
    late_return_20s = metrics["late_return_20s"]
    body_ratio = metrics["body_ratio"]
    wick_imbalance = metrics["wick_imbalance"]
    candle_regime = _classify_candle_regime(
        interval_return=interval_return,
        late_return_60s=late_return_60s,
        late_return_20s=late_return_20s,
        body_ratio=body_ratio,
        interval_minutes=udm.interval_minutes,
    )
    legacy_model_up_prob = _reference_probability(
        _model_driver_return(interval_return, late_return_60s, late_return_20s, reference_return) or actual_window_return,
        reference_zscore,
        udm.interval_minutes,
    )
    legacy_signal_side = "YES" if legacy_model_up_prob >= up_price else "NO"
    if actual_move_regime == "strong" and actual_move_side and legacy_signal_side != actual_move_side:
        contrarian_block_reason = (
            f"{coin} blocked legacy contrarian {legacy_signal_side} against strong actual {actual_move_side}"
        )

    detail_suffix = _reason_suffix(
        actual_window_return=actual_window_return,
        late_return_60s=late_return_60s,
        late_return_20s=late_return_20s,
        body_ratio=body_ratio,
        window_open_source=window_open_source,
    )
    if actual_move_regime == "flat":
        trend_alignment = "range_shadow_only"
        return build_skip(
            f"{coin} skip: flat window shadow only ({detail_suffix})",
            price_state="flat_window_shadow_only",
            route="range_or_flat",
            override_mode=STRATEGY_MODE_SHADOW,
        )
    if actual_move_regime != "strong" or not actual_move_side:
        trend_alignment = "mid_skip"
        return build_skip(
            f"{coin} skip: mid regime no trade ({detail_suffix})",
            price_state="mid_regime_no_trade",
            route="mid_skip",
        )

    entry_price = up_price if actual_move_side == "YES" else down_price
    market_state = _book_snapshot_for_side(market, actual_move_side)
    best_bid = market_state.get("best_bid")
    best_ask = market_state.get("best_ask")
    spread = market_state.get("spread")
    book_age_ms = market_state.get("book_age_ms")
    tick_size = market_state.get("tick_size")
    trend_alignment = "follow_trend"
    strategy_route = "trend_follow_candidate"
    confirmed = (
        _sign(actual_window_return) != 0
        and _sign(late_return_60s) == _sign(actual_window_return)
        and _sign(late_return_20s) == _sign(actual_window_return)
        and body_ratio is not None
        and body_ratio >= TREND_STRONG_MIN_BODY_RATIO
        and best_bid is not None
        and best_ask is not None
        and book_age_ms is not None
        and book_age_ms <= ACTUAL_MOVE_MAX_BOOK_AGE_MS
        and spread is not None
        and spread <= ACTUAL_MOVE_MAX_SPREAD
    )
    if not confirmed:
        return build_skip(
            f"{coin} skip: strong move not confirmed ({detail_suffix})",
            price_state="strong_move_no_confirmation",
            signal_side=legacy_signal_side if contrarian_block_reason else "",
            route="trend_follow_candidate",
        )

    strategy_mode = _strategy_mode_for_signal(udm, actual_move_side)
    if strategy_mode == STRATEGY_MODE_LIVE and entry_price < CANDIDATE_MIN_ENTRY_PRICE:
        strategy_mode = STRATEGY_MODE_SHADOW
    size_multiplier = _size_multiplier(
        candle_regime="trend_strong",
        trend_alignment=trend_alignment,
        strategy_mode=strategy_mode,
        entry_price=entry_price,
    )
    model_up_prob = _reference_probability(actual_window_return, reference_zscore, udm.interval_minutes)
    selected_side_probability = _side_probability(actual_move_side, model_up_prob)
    edge_gross = max(selected_side_probability - entry_price, 0.0)
    estimated_fee = _polymarket_taker_fee(entry_price)
    expected_cost = estimated_fee + SLIPPAGE_BUDGET + CANCELLATION_COST_BUDGET
    edge_net = edge_gross - expected_cost
    min_edge = max(
        _min_edge_for_setup(
            side=actual_move_side,
            interval_minutes=udm.interval_minutes,
            seconds_to_close=actual_seconds,
            interval_return=actual_window_return,
        ),
        expected_cost * ACTUAL_MOVE_EDGE_COST_MULTIPLE,
    ) + extra_min_edge

    if reference_zscore is not None and coin == "BTC":
        if actual_move_side == "NO" and reference_zscore > BTC_TOXIC_FLOW_STRONG_ZSCORE:
            return build_skip(
                f"{coin} skip: BTC toxic flow z-score {reference_zscore:+.2f} against NO",
                price_state="toxic_flow",
                signal_side=actual_move_side,
                route="trend_follow_candidate",
            )
        if actual_move_side == "YES" and reference_zscore < -BTC_TOXIC_FLOW_STRONG_ZSCORE:
            return build_skip(
                f"{coin} skip: BTC toxic flow z-score {reference_zscore:+.2f} against YES",
                price_state="toxic_flow",
                signal_side=actual_move_side,
                route="trend_follow_candidate",
            )
        if actual_move_side == "NO" and BTC_TOXIC_FLOW_WEAK_ZSCORE < reference_zscore <= BTC_TOXIC_FLOW_STRONG_ZSCORE:
            size_multiplier *= BTC_TOXIC_FLOW_SIZE_MULTIPLIER
        if actual_move_side == "YES" and -BTC_TOXIC_FLOW_STRONG_ZSCORE <= reference_zscore < -BTC_TOXIC_FLOW_WEAK_ZSCORE:
            size_multiplier *= BTC_TOXIC_FLOW_SIZE_MULTIPLIER

    if entry_price > ACTUAL_MOVE_HIGH_PROB_UPPER:
        return build_skip(
            f"{coin} skip: too late or overpriced ({detail_suffix})",
            price_state="too_late_high_prob",
            signal_side=actual_move_side,
            route="too_late_or_overpriced",
            override_mode=STRATEGY_MODE_SHADOW,
        )
    if entry_price > ACTUAL_MOVE_CANDIDATE_MAX_PRICE:
        return build_skip(
            f"{coin} high-probability shadow only ({detail_suffix})",
            price_state="too_late_high_prob",
            signal_side=actual_move_side,
            route="high_prob_shadow",
            override_mode=STRATEGY_MODE_SHADOW,
        )
    if strategy_mode == STRATEGY_MODE_LIVE and edge_gross < expected_cost * COST_CLEARING_MULTIPLIER:
        return build_skip(
            f"{coin} skip: gross edge {edge_gross:.1%} does not clear "
            f"{COST_CLEARING_MULTIPLIER:.1f}x cost buffer {expected_cost:.1%}",
            price_state="low_edge",
            signal_side=actual_move_side,
            route="trend_follow_candidate",
        )
    if edge_net < min_edge:
        return build_skip(
            f"{coin} skip: net edge {edge_net:.1%} < min {min_edge:.1%} "
            f"(selected {actual_move_side} {selected_side_probability:.0%} vs market {entry_price:.0%})",
            price_state="low_edge",
            signal_side=actual_move_side,
            route="trend_follow_candidate",
        )

    confidence = _confidence_score(
        edge_net=edge_net,
        min_edge=min_edge,
        interval_return=actual_window_return,
        late_return_60s=late_return_60s,
        late_return_20s=late_return_20s,
        candle_regime="trend_strong",
        interval_minutes=udm.interval_minutes,
    )
    reason = (
        f"{coin} actual-move follow {actual_move_side}; model UP {model_up_prob:.0%}; "
        f"selected {actual_move_side} {selected_side_probability:.0%} vs market {entry_price:.0%}; "
        f"net edge {edge_net:.1%}, {actual_seconds:.0f}s to close, {detail_suffix}"
    )
    signal = Signal(
        market=market,
        strategy="updown",
        side=actual_move_side,
        confidence=confidence,
        reason=reason,
        strategy_mode=strategy_mode,
        market_type=f"{udm.interval_minutes}m",
        coin=coin,
        edge_gross=edge_gross,
        edge_net=edge_net,
        reference_symbol=coin,
        reference_price=reference_price,
        reference_age_seconds=reference_age,
        reference_zscore=reference_zscore,
        best_bid=best_bid if best_bid is not None else entry_price,
        best_ask=best_ask if best_ask is not None else entry_price,
        spread=spread if spread is not None else min(LIVE_MAKER_MAX_SPREAD, 0.01),
        decision_latency_ms=(time.time() - t0) * 1000,
        thesis_id=thesis_id,
        size_multiplier=size_multiplier,
        model_up_probability=model_up_prob,
        selected_side_probability=selected_side_probability,
        interval_open=metrics["interval_open"],
        interval_high=metrics["interval_high"],
        interval_low=metrics["interval_low"],
        interval_close=metrics["interval_close"],
        interval_return=interval_return,
        late_return_60s=late_return_60s,
        late_return_20s=late_return_20s,
        body_ratio=body_ratio,
        wick_imbalance=wick_imbalance,
        candle_regime=candle_regime,
        trend_alignment=trend_alignment,
        market_yes_at_decision=up_price,
        contrarian_block_reason=contrarian_block_reason,
        window_start_ts=window_start_ts,
        window_open_price=window_open_price,
        window_open_source=window_open_source,
        window_open_price_trusted=window_open_price_trusted,
        actual_window_return=actual_window_return,
        actual_move_regime=actual_move_regime,
        actual_move_side=actual_move_side,
        strategy_route=strategy_route,
        cluster_id=_cluster_id(coin),
        signal_epoch_id=market.slug,
        book_age_ms=book_age_ms,
        tick_size=tick_size,
        expected_fill_price=best_ask if best_ask is not None else entry_price,
        expected_cost=expected_cost,
    )
    return _build_analysis(
        udm,
        signal=signal,
        reason=reason,
        decision_stage="analysis_ready",
        seconds_to_close=actual_seconds,
        implied_up_prob=up_price,
        model_up_prob=model_up_prob,
        signal_side=actual_move_side,
        confidence=confidence,
        entry_price=entry_price,
        raw_edge=edge_gross,
        effective_edge=edge_net,
        estimated_fee=estimated_fee,
        min_edge=min_edge,
        momentum=actual_window_return,
        price_state="strong_actual_move",
        strategy_mode=strategy_mode,
        reference_age_seconds=reference_age,
        reference_zscore=reference_zscore,
        size_multiplier=size_multiplier,
        best_bid=signal.best_bid,
        best_ask=signal.best_ask,
        spread=signal.spread,
        decision_latency_ms=signal.decision_latency_ms,
        thesis_id=thesis_id,
        selected_side_probability=selected_side_probability,
        interval_open=metrics["interval_open"],
        interval_high=metrics["interval_high"],
        interval_low=metrics["interval_low"],
        interval_close=metrics["interval_close"],
        interval_return=interval_return,
        late_return_60s=late_return_60s,
        late_return_20s=late_return_20s,
        body_ratio=body_ratio,
        wick_imbalance=wick_imbalance,
        candle_regime=candle_regime,
        trend_alignment=trend_alignment,
        market_yes_at_decision=up_price,
        contrarian_block_reason=contrarian_block_reason,
        legacy_model_up_prob=legacy_model_up_prob,
        legacy_signal_side=legacy_signal_side,
        window_start_ts=window_start_ts,
        window_open_price=window_open_price,
        window_open_source=window_open_source,
        window_open_price_trusted=window_open_price_trusted,
        actual_window_return=actual_window_return,
        actual_move_regime=actual_move_regime,
        actual_move_side=actual_move_side,
        strategy_route=strategy_route,
    )


def analyze_updown_market_detail(udm: UpDownMarket, extra_min_edge: float = 0.0) -> UpdownAnalysis:
    """Return a structured analysis result for one up/down market."""

    t0 = time.time()
    market = udm.market
    coin = udm.coin
    actual_seconds = float(udm.seconds_to_close)
    strategy_mode = normalize_strategy_mode(
        UPDOWN_15M_STRATEGY_MODE if udm.interval_minutes == 15 else UPDOWN_5M_STRATEGY_MODE,
        STRATEGY_MODE_DISABLED,
    )
    thesis_id = _thesis_id(udm)

    if len(market.outcome_prices) < 2:
        reason = f"{coin} skip: <2 outcome prices"
        return _build_analysis(
            udm,
            signal=None,
            reason=reason,
            decision_stage="analysis_skip",
            seconds_to_close=actual_seconds,
            strategy_mode=strategy_mode,
            thesis_id=thesis_id,
        )

    if market.end_date:
        actual_seconds = max(0.0, (market.end_date - datetime.now(timezone.utc)).total_seconds())

    min_seconds = MIN_SECONDS_TO_TRADE_15M if udm.interval_minutes == 15 else MIN_SECONDS_TO_TRADE_5M
    if actual_seconds < min_seconds:
        reason = f"{coin} skip: {actual_seconds:.0f}s left < {min_seconds}s min"
        return _build_analysis(
            udm,
            signal=None,
            reason=reason,
            decision_stage="analysis_skip",
            seconds_to_close=actual_seconds,
            strategy_mode=strategy_mode,
            thesis_id=thesis_id,
        )

    up_price, down_price = _up_down_prices(udm)
    if up_price is None or down_price is None:
        reason = f"{coin} skip: invalid up/down prices"
        return _build_analysis(
            udm,
            signal=None,
            reason=reason,
            decision_stage="analysis_skip",
            seconds_to_close=actual_seconds,
            strategy_mode=strategy_mode,
            thesis_id=thesis_id,
        )

    return _analyze_actual_move_first(
        udm,
        actual_seconds=actual_seconds,
        up_price=up_price,
        down_price=down_price,
        strategy_mode=strategy_mode,
        thesis_id=thesis_id,
        extra_min_edge=extra_min_edge,
        t0=t0,
    )

    reference = get_reference_snapshot(coin, interval_minutes=udm.interval_minutes)
    reference_price = reference.get("price")
    reference_age = reference.get("age_seconds")
    reference_return = reference.get("return_lookback")
    reference_zscore = reference.get("zscore")
    chainlink_price = reference.get("chainlink_price")
    chainlink_age = reference.get("chainlink_age_seconds")

    if reference_price is None or reference_age is None:
        if is_price_stale(coin, max_age=MAX_REFERENCE_AGE_SECONDS):
            reference_age = reference_age if reference_age is not None else MAX_REFERENCE_AGE_SECONDS + 1.0
        else:
            fallback_return = get_price_momentum(coin)
            if fallback_return is not None:
                reference_price = 1.0
                reference_age = 0.0
                reference_return = fallback_return

    if reference_price is None or reference_age is None or reference_age > MAX_REFERENCE_AGE_SECONDS:
        reason = f"{coin} skip: reference data stale ({reference_age if reference_age is not None else 'na'}s)"
        return _build_analysis(
            udm,
            signal=None,
            reason=reason,
            decision_stage="analysis_skip",
            seconds_to_close=actual_seconds,
            implied_up_prob=up_price,
            model_up_prob=up_price,
            price_state="stale",
            strategy_mode=strategy_mode,
            reference_age_seconds=reference_age,
            thesis_id=thesis_id,
            market_yes_at_decision=up_price,
        )

    if reference_return is None:
        reason = f"{coin} skip: insufficient reference history"
        return _build_analysis(
            udm,
            signal=None,
            reason=reason,
            decision_stage="analysis_skip",
            seconds_to_close=actual_seconds,
            implied_up_prob=up_price,
            model_up_prob=up_price,
            price_state="no_data",
            strategy_mode=strategy_mode,
            reference_age_seconds=reference_age,
            thesis_id=thesis_id,
            market_yes_at_decision=up_price,
        )

    if udm.interval_minutes == 15 and CHAINLINK_REQUIRED_15M:
        if chainlink_price is None or chainlink_age is None or chainlink_age > MAX_REFERENCE_AGE_SECONDS:
            reason = f"{coin} skip: 15m requires fresh Chainlink reference"
            return _build_analysis(
                udm,
                signal=None,
                reason=reason,
                decision_stage="analysis_skip",
                seconds_to_close=actual_seconds,
                implied_up_prob=up_price,
                model_up_prob=up_price,
                price_state="no_chainlink",
                strategy_mode=strategy_mode,
                reference_age_seconds=reference_age,
                reference_zscore=reference_zscore,
                thesis_id=thesis_id,
                market_yes_at_decision=up_price,
            )

    metrics = _normalize_reference_metrics(reference, reference_price, reference_return)
    interval_return = metrics["interval_return"]
    late_return_60s = metrics["late_return_60s"]
    late_return_20s = metrics["late_return_20s"]
    body_ratio = metrics["body_ratio"]
    wick_imbalance = metrics["wick_imbalance"]
    candle_regime = _classify_candle_regime(
        interval_return=interval_return,
        late_return_60s=late_return_60s,
        late_return_20s=late_return_20s,
        body_ratio=body_ratio,
        interval_minutes=udm.interval_minutes,
    )

    driver_return = _model_driver_return(
        interval_return,
        late_return_60s,
        late_return_20s,
        reference_return,
    )
    if driver_return is None:
        reason = f"{coin} skip: insufficient candle metrics"
        return _build_analysis(
            udm,
            signal=None,
            reason=reason,
            decision_stage="analysis_skip",
            seconds_to_close=actual_seconds,
            implied_up_prob=up_price,
            model_up_prob=up_price,
            price_state="no_candle",
            strategy_mode=strategy_mode,
            reference_age_seconds=reference_age,
            reference_zscore=reference_zscore,
            thesis_id=thesis_id,
            interval_open=metrics["interval_open"],
            interval_high=metrics["interval_high"],
            interval_low=metrics["interval_low"],
            interval_close=metrics["interval_close"],
            interval_return=interval_return,
            late_return_60s=late_return_60s,
            late_return_20s=late_return_20s,
            body_ratio=body_ratio,
            wick_imbalance=wick_imbalance,
            candle_regime=candle_regime,
            market_yes_at_decision=up_price,
        )

    model_up_prob = _reference_probability(driver_return, reference_zscore, udm.interval_minutes)
    side = "YES" if model_up_prob >= up_price else "NO"
    entry_price = up_price if side == "YES" else down_price
    selected_side_probability = _side_probability(side, model_up_prob)
    trend_alignment = _trend_alignment(
        candle_regime=candle_regime,
        side=side,
        interval_return=interval_return,
        late_return_60s=late_return_60s,
        late_return_20s=late_return_20s,
    )
    market_prob = entry_price
    edge_gross = max(selected_side_probability - market_prob, 0.0)
    min_edge = _min_edge_for_setup(
        side=side,
        interval_minutes=udm.interval_minutes,
        seconds_to_close=actual_seconds,
        interval_return=interval_return or reference_return or 0.0,
    ) + extra_min_edge
    strategy_mode = _strategy_mode_for_signal(udm, side)
    contrarian_block_reason = ""

    if candle_regime == "trend_strong" and trend_alignment == "contrarian":
        contrarian_block_reason = (
            f"{coin} skip: trend_strong blocks contrarian {side} "
            f"(interval {interval_return:+.3%}, 60s {late_return_60s:+.3%}, 20s {late_return_20s:+.3%}, body {body_ratio:.2f})"
        )
        return _build_analysis(
            udm,
            signal=None,
            reason=contrarian_block_reason,
            decision_stage="analysis_skip",
            seconds_to_close=actual_seconds,
            implied_up_prob=up_price,
            model_up_prob=model_up_prob,
            signal_side=side,
            entry_price=entry_price,
            raw_edge=edge_gross,
            min_edge=min_edge,
            momentum=interval_return,
            price_state="trend_strong",
            strategy_mode=strategy_mode,
            reference_age_seconds=reference_age,
            reference_zscore=reference_zscore,
            thesis_id=thesis_id,
            selected_side_probability=selected_side_probability,
            interval_open=metrics["interval_open"],
            interval_high=metrics["interval_high"],
            interval_low=metrics["interval_low"],
            interval_close=metrics["interval_close"],
            interval_return=interval_return,
            late_return_60s=late_return_60s,
            late_return_20s=late_return_20s,
            body_ratio=body_ratio,
            wick_imbalance=wick_imbalance,
            candle_regime=candle_regime,
            trend_alignment=trend_alignment,
            market_yes_at_decision=up_price,
            contrarian_block_reason=contrarian_block_reason,
        )

    size_multiplier = _size_multiplier(
        candle_regime=candle_regime,
        trend_alignment=trend_alignment,
        strategy_mode=strategy_mode,
        entry_price=entry_price,
    )

    if reference_zscore is not None and coin == "BTC":
        if side == "NO" and reference_zscore > BTC_TOXIC_FLOW_STRONG_ZSCORE:
            reason = f"{coin} skip: BTC toxic flow z-score {reference_zscore:+.2f} against NO"
            return _build_analysis(
                udm,
                signal=None,
                reason=reason,
                decision_stage="analysis_skip",
                seconds_to_close=actual_seconds,
                implied_up_prob=up_price,
                model_up_prob=model_up_prob,
                signal_side=side,
                entry_price=entry_price,
                raw_edge=edge_gross,
                min_edge=min_edge,
                momentum=interval_return,
                price_state="toxic_flow",
                strategy_mode=_strategy_mode_for_signal(udm, side),
                reference_age_seconds=reference_age,
                reference_zscore=reference_zscore,
                thesis_id=thesis_id,
                selected_side_probability=selected_side_probability,
                interval_open=metrics["interval_open"],
                interval_high=metrics["interval_high"],
                interval_low=metrics["interval_low"],
                interval_close=metrics["interval_close"],
                interval_return=interval_return,
                late_return_60s=late_return_60s,
                late_return_20s=late_return_20s,
                body_ratio=body_ratio,
                wick_imbalance=wick_imbalance,
                candle_regime=candle_regime,
                trend_alignment=trend_alignment,
                market_yes_at_decision=up_price,
            )
        if side == "YES" and reference_zscore < -BTC_TOXIC_FLOW_STRONG_ZSCORE:
            reason = f"{coin} skip: BTC toxic flow z-score {reference_zscore:+.2f} against YES"
            return _build_analysis(
                udm,
                signal=None,
                reason=reason,
                decision_stage="analysis_skip",
                seconds_to_close=actual_seconds,
                implied_up_prob=up_price,
                model_up_prob=model_up_prob,
                signal_side=side,
                entry_price=entry_price,
                raw_edge=edge_gross,
                min_edge=min_edge,
                momentum=interval_return,
                price_state="toxic_flow",
                strategy_mode=_strategy_mode_for_signal(udm, side),
                reference_age_seconds=reference_age,
                reference_zscore=reference_zscore,
                thesis_id=thesis_id,
                selected_side_probability=selected_side_probability,
                interval_open=metrics["interval_open"],
                interval_high=metrics["interval_high"],
                interval_low=metrics["interval_low"],
                interval_close=metrics["interval_close"],
                interval_return=interval_return,
                late_return_60s=late_return_60s,
                late_return_20s=late_return_20s,
                body_ratio=body_ratio,
                wick_imbalance=wick_imbalance,
                candle_regime=candle_regime,
                trend_alignment=trend_alignment,
                market_yes_at_decision=up_price,
            )
        if side == "NO" and BTC_TOXIC_FLOW_WEAK_ZSCORE < reference_zscore <= BTC_TOXIC_FLOW_STRONG_ZSCORE:
            size_multiplier *= BTC_TOXIC_FLOW_SIZE_MULTIPLIER
            min_edge += BTC_TOXIC_FLOW_EXTRA_EDGE
        if side == "YES" and -BTC_TOXIC_FLOW_STRONG_ZSCORE <= reference_zscore < -BTC_TOXIC_FLOW_WEAK_ZSCORE:
            size_multiplier *= BTC_TOXIC_FLOW_SIZE_MULTIPLIER
            min_edge += BTC_TOXIC_FLOW_EXTRA_EDGE

    selected_token_id = ""
    if market.token_ids:
        selected_index = 0 if side == "YES" else 1
        if selected_index < len(market.token_ids):
            selected_token_id = market.token_ids[selected_index]
    market_state = MARKET_CACHE.snapshot(selected_token_id) if selected_token_id else {}
    best_bid = market_state.get("best_bid") or entry_price
    best_ask = market_state.get("best_ask") or entry_price
    spread = market_state.get("spread")
    book_age_ms = market_state.get("book_age_ms")
    tick_size = market_state.get("tick_size")

    estimated_fee = _polymarket_taker_fee(entry_price)
    expected_cost = estimated_fee + SLIPPAGE_BUDGET + CANCELLATION_COST_BUDGET
    edge_net = edge_gross - expected_cost
    price_state = candle_regime

    if strategy_mode == STRATEGY_MODE_LIVE and entry_price < CANDIDATE_MIN_ENTRY_PRICE:
        strategy_mode = STRATEGY_MODE_SHADOW

    if strategy_mode == STRATEGY_MODE_LIVE and edge_gross < expected_cost * COST_CLEARING_MULTIPLIER:
        reason = (
            f"{coin} skip: gross edge {edge_gross:.1%} does not clear "
            f"{COST_CLEARING_MULTIPLIER:.1f}x cost buffer {expected_cost:.1%}"
        )
        return _build_analysis(
            udm,
            signal=None,
            reason=reason,
            decision_stage="analysis_skip",
            seconds_to_close=actual_seconds,
            implied_up_prob=up_price,
            model_up_prob=model_up_prob,
            signal_side=side,
            entry_price=entry_price,
            raw_edge=edge_gross,
            effective_edge=edge_net,
            estimated_fee=estimated_fee,
            min_edge=min_edge,
            momentum=interval_return,
            price_state=price_state,
            strategy_mode=strategy_mode,
            reference_age_seconds=reference_age,
            reference_zscore=reference_zscore,
            size_multiplier=size_multiplier,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            decision_latency_ms=(time.time() - t0) * 1000,
            thesis_id=thesis_id,
            selected_side_probability=selected_side_probability,
            interval_open=metrics["interval_open"],
            interval_high=metrics["interval_high"],
            interval_low=metrics["interval_low"],
            interval_close=metrics["interval_close"],
            interval_return=interval_return,
            late_return_60s=late_return_60s,
            late_return_20s=late_return_20s,
            body_ratio=body_ratio,
            wick_imbalance=wick_imbalance,
            candle_regime=candle_regime,
            trend_alignment=trend_alignment,
            market_yes_at_decision=up_price,
        )

    if edge_net < min_edge:
        reason = (
            f"{coin} skip: net edge {edge_net:.1%} < min {min_edge:.1%} "
            f"(selected {side} {selected_side_probability:.0%} vs market {market_prob:.0%})"
        )
        return _build_analysis(
            udm,
            signal=None,
            reason=reason,
            decision_stage="analysis_skip",
            seconds_to_close=actual_seconds,
            implied_up_prob=up_price,
            model_up_prob=model_up_prob,
            signal_side=side,
            entry_price=entry_price,
            raw_edge=edge_gross,
            effective_edge=edge_net,
            estimated_fee=estimated_fee,
            min_edge=min_edge,
            momentum=interval_return,
            price_state=price_state,
            strategy_mode=strategy_mode,
            reference_age_seconds=reference_age,
            reference_zscore=reference_zscore,
            size_multiplier=size_multiplier,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            decision_latency_ms=(time.time() - t0) * 1000,
            thesis_id=thesis_id,
            selected_side_probability=selected_side_probability,
            interval_open=metrics["interval_open"],
            interval_high=metrics["interval_high"],
            interval_low=metrics["interval_low"],
            interval_close=metrics["interval_close"],
            interval_return=interval_return,
            late_return_60s=late_return_60s,
            late_return_20s=late_return_20s,
            body_ratio=body_ratio,
            wick_imbalance=wick_imbalance,
            candle_regime=candle_regime,
            trend_alignment=trend_alignment,
            market_yes_at_decision=up_price,
        )

    if strategy_mode == STRATEGY_MODE_LIVE and (
        entry_price >= CRYPTO_SHADOW_ONLY_UPPER or entry_price <= CRYPTO_SHADOW_ONLY_LOWER
    ):
        strategy_mode = STRATEGY_MODE_SHADOW

    confidence = _confidence_score(
        edge_net=edge_net,
        min_edge=min_edge,
        interval_return=interval_return,
        late_return_60s=late_return_60s,
        late_return_20s=late_return_20s,
        candle_regime=candle_regime,
        interval_minutes=udm.interval_minutes,
    )
    reason = _side_aware_reason(
        coin=coin,
        candle_regime=candle_regime,
        model_up_prob=model_up_prob,
        side=side,
        selected_side_probability=selected_side_probability,
        market_price=market_prob,
        edge_net=edge_net,
        interval_return=interval_return,
        late_return_60s=late_return_60s,
        late_return_20s=late_return_20s,
        seconds_to_close=actual_seconds,
    )
    signal = Signal(
        market=market,
        strategy="updown",
        side=side,
        confidence=confidence,
        reason=reason,
        strategy_mode=strategy_mode,
        market_type=f"{udm.interval_minutes}m",
        coin=coin,
        edge_gross=edge_gross,
        edge_net=edge_net,
        reference_symbol=coin,
        reference_price=reference_price,
        reference_age_seconds=reference_age,
        reference_zscore=reference_zscore,
        best_bid=best_bid,
        best_ask=best_ask,
        spread=spread if spread is not None else (0.0 if entry_price <= 0 else min(LIVE_MAKER_MAX_SPREAD, 0.01)),
        decision_latency_ms=(time.time() - t0) * 1000,
        thesis_id=thesis_id,
        size_multiplier=size_multiplier,
        model_up_probability=model_up_prob,
        selected_side_probability=selected_side_probability,
        interval_open=metrics["interval_open"],
        interval_high=metrics["interval_high"],
        interval_low=metrics["interval_low"],
        interval_close=metrics["interval_close"],
        interval_return=interval_return,
        late_return_60s=late_return_60s,
        late_return_20s=late_return_20s,
        body_ratio=body_ratio,
        wick_imbalance=wick_imbalance,
        candle_regime=candle_regime,
        trend_alignment=trend_alignment,
        market_yes_at_decision=up_price,
        contrarian_block_reason=contrarian_block_reason,
        cluster_id=_cluster_id(coin),
        signal_epoch_id=market.slug,
        book_age_ms=book_age_ms,
        tick_size=tick_size,
        expected_fill_price=best_ask if best_ask is not None else entry_price,
        expected_cost=expected_cost,
    )
    return _build_analysis(
        udm,
        signal=signal,
        reason=reason,
        decision_stage="analysis_ready",
        seconds_to_close=actual_seconds,
        implied_up_prob=up_price,
        model_up_prob=model_up_prob,
        signal_side=side,
        confidence=confidence,
        entry_price=entry_price,
        raw_edge=edge_gross,
        effective_edge=edge_net,
        estimated_fee=estimated_fee,
        min_edge=min_edge,
        momentum=interval_return,
        price_state=price_state,
        strategy_mode=strategy_mode,
        reference_age_seconds=reference_age,
        reference_zscore=reference_zscore,
        size_multiplier=size_multiplier,
        best_bid=signal.best_bid,
        best_ask=signal.best_ask,
        spread=signal.spread,
        decision_latency_ms=signal.decision_latency_ms,
        thesis_id=thesis_id,
        selected_side_probability=selected_side_probability,
        interval_open=metrics["interval_open"],
        interval_high=metrics["interval_high"],
        interval_low=metrics["interval_low"],
        interval_close=metrics["interval_close"],
        interval_return=interval_return,
        late_return_60s=late_return_60s,
        late_return_20s=late_return_20s,
        body_ratio=body_ratio,
        wick_imbalance=wick_imbalance,
        candle_regime=candle_regime,
        trend_alignment=trend_alignment,
        market_yes_at_decision=up_price,
        contrarian_block_reason=contrarian_block_reason,
    )


def analyze_updown_market(udm: UpDownMarket, extra_min_edge: float = 0.0) -> tuple[Signal | None, str]:
    """Analyze an up/down market for trading signals."""
    analysis = analyze_updown_market_detail(udm, extra_min_edge=extra_min_edge)
    return analysis.signal, analysis.reason
