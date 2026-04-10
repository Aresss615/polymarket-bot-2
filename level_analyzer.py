"""Analyze crypto up/down interval markets.

Strategy: Use the market's own implied probability to find mispriced outcomes.
When the market strongly favors one side (e.g., UP at 0.70), we follow the
trend. When the market is near 50/50, we skip (no edge). We also skip markets
that are already near-certain (priced above 0.92 or below 0.08).
"""

from config import (
    Signal,
    UpDownMarket,
    CRYPTO_NEAR_CERTAIN_UPPER,
    CRYPTO_NEAR_CERTAIN_LOWER,
    MIN_EDGE,
)


def analyze_updown_market(udm: UpDownMarket) -> Signal | None:
    market = udm.market
    if len(market.outcome_prices) < 2:
        return None

    yes_price = market.outcome_prices[0]

    # Derive UP probability from outcome prices
    if udm.up_outcome_index == 0:
        implied_up_prob = yes_price
    else:
        implied_up_prob = 1.0 - yes_price

    # Skip near-certain markets (no edge available)
    if implied_up_prob >= CRYPTO_NEAR_CERTAIN_UPPER or implied_up_prob <= CRYPTO_NEAR_CERTAIN_LOWER:
        return None

    # Follow the market's direction with a small boost
    # If market says UP at 0.60, we estimate 0.65 (trend-following)
    BOOST = 0.05
    if implied_up_prob > 0.5:
        model_up_prob = min(implied_up_prob + BOOST, 0.90)
        direction = "UP"
    elif implied_up_prob < 0.5:
        model_up_prob = max(implied_up_prob - BOOST, 0.10)
        direction = "DOWN"
    else:
        return None  # 50/50, no edge

    # Convert to YES probability
    if udm.up_outcome_index == 0:
        model_yes_prob = model_up_prob
    else:
        model_yes_prob = 1.0 - model_up_prob

    edge = model_yes_prob - yes_price

    if abs(edge) < MIN_EDGE:
        return None

    if edge > 0:
        side = "YES"
    else:
        side = "NO"

    confidence = min(abs(edge) / 0.15, 1.0)

    reason = (
        f"{udm.coin} implied {direction} at {implied_up_prob:.0%}, "
        f"edge {edge:+.1%}, {udm.seconds_to_close}s to close"
    )

    return Signal(
        market=market,
        strategy="updown",
        side=side,
        confidence=confidence,
        reason=reason,
    )
