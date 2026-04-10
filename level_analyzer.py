import re
from datetime import datetime, timezone

from config import (
    Market,
    LevelMarket,
    Signal,
    SUPPORTED_COINS,
    LEVEL_CLEARANCE_PCT,
    LEVEL_WINDOW_MINUTES,
)

COINS_PATTERN = "|".join(SUPPORTED_COINS.keys())

LEVEL_RE = re.compile(
    rf"Will\s+({COINS_PATTERN})\s+(?:be|close)\s+(above|below)\s+\$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)


def parse_level_market(market: Market) -> LevelMarket | None:
    match = LEVEL_RE.search(market.question)
    if not match:
        return None
    if not market.end_date:
        return None

    coin = match.group(1).upper()
    direction = match.group(2).lower()
    threshold = float(match.group(3).replace(",", ""))

    return LevelMarket(
        market=market,
        coin=coin,
        threshold=threshold,
        direction=direction,
        expiry=market.end_date,
    )


def find_level_markets(markets: list[Market]) -> list[LevelMarket]:
    results = []
    for m in markets:
        lm = parse_level_market(m)
        if lm:
            results.append(lm)
    return results


def analyze_level_opportunity(
    level_market: LevelMarket,
    current_price: float,
    now: datetime | None = None,
) -> Signal | None:
    if now is None:
        now = datetime.now(timezone.utc)

    minutes_to_expiry = (level_market.expiry - now).total_seconds() / 60

    if minutes_to_expiry < 0 or minutes_to_expiry > LEVEL_WINDOW_MINUTES:
        return None

    clearance = abs(current_price - level_market.threshold) / level_market.threshold

    if clearance < LEVEL_CLEARANCE_PCT:
        return None

    price_above_threshold = current_price > level_market.threshold

    if level_market.direction == "above":
        side = "YES" if price_above_threshold else "NO"
    else:  # "below"
        side = "YES" if not price_above_threshold else "NO"

    reason = (
        f"{level_market.coin} at ${current_price:,.2f} is {clearance:.1%} "
        f"{'above' if price_above_threshold else 'below'} "
        f"${level_market.threshold:,.2f} with {minutes_to_expiry:.0f}min to expiry"
    )

    return Signal(
        market=level_market.market,
        strategy="level",
        side=side,
        confidence=min(clearance / (LEVEL_CLEARANCE_PCT * 3), 1.0),
        reason=reason,
    )
