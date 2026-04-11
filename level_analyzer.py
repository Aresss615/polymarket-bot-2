"""Analyze crypto up/down interval markets.

Strategy: Compare CEX price momentum against market-implied probability to find
genuine mispricing. Only trade when:
1. The market has a strong directional signal (outside the 38-62% "coin flip" zone)
2. CEX price movement confirms the market's direction (momentum alignment)
3. We're close enough to expiry that the trend is likely to hold

The key insight: market-implied probability near 50% has no predictive value and
Polymarket charges up to 1.8% dynamic fees there. Real edge comes from strong
directional signals confirmed by actual price action, traded close to expiry.
"""

import logging
from datetime import datetime, timezone

from config import (
    Signal,
    UpDownMarket,
    CRYPTO_NEAR_CERTAIN_UPPER,
    CRYPTO_NEAR_CERTAIN_LOWER,
    CRYPTO_SKIP_BAND_LOW,
    CRYPTO_SKIP_BAND_HIGH,
    MIN_EDGE,
    MIN_SECONDS_TO_TRADE,
    COIN_MIN_EDGE,
)
from price_feed import get_price, get_price_momentum

log = logging.getLogger(__name__)


def analyze_updown_market(udm: UpDownMarket) -> Signal | None:
    market = udm.market
    slug = market.slug

    if len(market.outcome_prices) < 2:
        log.debug("[%s] skip: <2 outcome prices", slug)
        return None

    # Recompute actual seconds remaining from end_date (the snapshot in
    # udm.seconds_to_close may be stale by the time we get here)
    if market.end_date:
        actual_seconds = max(0, (market.end_date - datetime.now(timezone.utc)).total_seconds())
    else:
        actual_seconds = udm.seconds_to_close

    if actual_seconds < MIN_SECONDS_TO_TRADE:
        log.debug("[%s] skip: %.0fs remaining < %ds min", slug, actual_seconds, MIN_SECONDS_TO_TRADE)
        return None

    yes_price = market.outcome_prices[0]

    # Derive UP probability from outcome prices
    if udm.up_outcome_index == 0:
        implied_up_prob = yes_price
    else:
        implied_up_prob = 1.0 - yes_price

    # Skip near-certain markets (no edge available)
    if implied_up_prob >= CRYPTO_NEAR_CERTAIN_UPPER or implied_up_prob <= CRYPTO_NEAR_CERTAIN_LOWER:
        log.debug("[%s] skip: near-certain (implied %.0f%%)", slug, implied_up_prob * 100)
        return None

    # Skip the "coin flip" zone — these are just noise with high fees
    if CRYPTO_SKIP_BAND_LOW <= implied_up_prob <= CRYPTO_SKIP_BAND_HIGH:
        log.debug("[%s] skip: coin-flip zone (implied %.0f%%)", slug, implied_up_prob * 100)
        return None

    # Determine market-implied direction
    if implied_up_prob > 0.5:
        direction = "UP"
        strength = implied_up_prob - 0.5  # 0.0 to 0.38
    else:
        direction = "DOWN"
        strength = 0.5 - implied_up_prob  # 0.0 to 0.38

    # Check CEX price momentum for confirmation
    momentum = get_price_momentum(udm.coin)
    if momentum is not None:
        price_confirms = (
            (direction == "UP" and momentum > 0)
            or (direction == "DOWN" and momentum < 0)
        )
        price_contradicts = (
            (direction == "UP" and momentum < -0.001)
            or (direction == "DOWN" and momentum > 0.001)
        )
    else:
        # No price data available — require stronger market signal
        price_confirms = False
        price_contradicts = False

    # Skip if price actively contradicts the market direction
    if price_contradicts:
        log.debug("[%s] skip: price contradicts %s (momentum %+.3f%%)", slug, direction, (momentum or 0) * 100)
        return None

    # Calculate model probability with dynamic boost
    # Stronger market signal + price confirmation = bigger boost
    if price_confirms:
        # Price agrees — use a confidence-scaled boost
        boost = 0.03 + strength * 0.15  # 0.03 to ~0.09
    else:
        # No price data or neutral — scale boost by strength, require strong signal
        if strength < 0.20:
            log.debug("[%s] skip: weak signal (strength %.0f%%) without price confirmation", slug, strength * 100)
            return None  # Not strong enough without price confirmation (need >=70%)
        boost = 0.02 + strength * 0.15  # 0.05 at strength=0.20 to ~0.077 at 0.38

    if direction == "UP":
        model_up_prob = min(implied_up_prob + boost, 0.95)
    else:
        model_up_prob = max(implied_up_prob - boost, 0.05)

    # Convert to YES probability
    if udm.up_outcome_index == 0:
        model_yes_prob = model_up_prob
    else:
        model_yes_prob = 1.0 - model_up_prob

    edge = model_yes_prob - yes_price

    # Price-dependent edge floor: 70-80% entry prices need more edge since
    # breakeven WR is high there (75% WR at 0.75 entry = breakeven)
    entry_price = yes_price if edge > 0 else (1.0 - yes_price)
    min_edge = COIN_MIN_EDGE.get(udm.coin, MIN_EDGE)
    if 0.70 <= entry_price <= 0.80:
        min_edge = max(min_edge, 0.07)

    if abs(edge) < min_edge:
        log.debug("[%s] skip: edge %.1f%% < min %.1f%% (entry %.0f%%)", slug, abs(edge) * 100, min_edge * 100, entry_price * 100)
        return None

    if edge > 0:
        side = "YES"
    else:
        side = "NO"

    # Confidence scales with edge magnitude and time proximity
    # Closer to expiry = higher confidence, but cap at MIN_SECONDS_TO_TRADE
    time_factor = max(0.5, 1.0 - (actual_seconds - MIN_SECONDS_TO_TRADE) / 30.0)  # 1.0 at 15s, 0.5 at 45s
    edge_factor = min(abs(edge) / 0.12, 1.0)
    confidence = edge_factor * time_factor

    momentum_str = ""
    if momentum is not None:
        momentum_str = f", price {'confirms' if price_confirms else 'neutral'} ({momentum:+.3%})"

    reason = (
        f"{udm.coin} implied {direction} at {implied_up_prob:.0%}, "
        f"edge {edge:+.1%}, {actual_seconds:.0f}s to close{momentum_str}"
    )

    return Signal(
        market=market,
        strategy="updown",
        side=side,
        confidence=confidence,
        reason=reason,
    )
