import json
import re
from datetime import datetime, timedelta, timezone

import requests

from config import (
    GAMMA_API_URL,
    CLOB_API_URL,
    Market,
    UpDownMarket,
    MIN_SECONDS_TO_CLOSE,
    MAX_SECONDS_TO_CLOSE,
    MIN_LIQUIDITY,
)

UPDOWN_SLUG_RE = re.compile(
    r"^([a-z]+)-updown-(\d+)m-\d+$", re.IGNORECASE
)


def _parse_json_or_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return []


def _up_outcome_index(outcomes: list[str]) -> int:
    labels = [str(o).strip().lower() for o in outcomes]
    for idx, label in enumerate(labels):
        if "up" in label:
            return idx
    return 0


def fetch_active_markets() -> list[Market]:
    now = datetime.now(timezone.utc)
    floor = now + timedelta(seconds=MIN_SECONDS_TO_CLOSE)
    cutoff = now + timedelta(seconds=MAX_SECONDS_TO_CLOSE)

    resp = requests.get(
        f"{GAMMA_API_URL}/markets",
        params={
            "active": "true",
            "closed": "false",
            "limit": 250,
            "liquidity_num_min": MIN_LIQUIDITY,
            "order": "endDate",
            "ascending": "true",
            "end_date_min": floor.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_date_max": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        timeout=10,
    )
    resp.raise_for_status()

    markets = []
    for m in resp.json():
        try:
            prices_raw = _parse_json_or_list(m.get("outcomePrices", "[]"))
            prices = [float(p) for p in prices_raw]

            token_ids = _parse_json_or_list(m.get("clobTokenIds", "[]"))

            outcomes_raw = _parse_json_or_list(m.get("outcomes", '["Yes","No"]'))
            outcomes = [str(o) for o in outcomes_raw]

            end_date = None
            if m.get("endDate"):
                end_date = datetime.fromisoformat(
                    m["endDate"].replace("Z", "+00:00")
                )

            markets.append(
                Market(
                    condition_id=m["conditionId"],
                    question=m.get("question", ""),
                    slug=m.get("slug", ""),
                    outcomes=outcomes,
                    outcome_prices=prices,
                    token_ids=token_ids,
                    end_date=end_date,
                    active=m.get("active", True),
                )
            )
        except (KeyError, ValueError, json.JSONDecodeError):
            continue
    return markets


def find_updown_markets(markets: list[Market]) -> list[UpDownMarket]:
    now = datetime.now(timezone.utc)
    results = []
    for m in markets:
        match = UPDOWN_SLUG_RE.match(m.slug)
        if not match:
            continue
        if not m.end_date:
            continue

        coin = match.group(1).upper()
        interval = int(match.group(2))
        secs = max(0, int((m.end_date - now).total_seconds()))

        if secs < MIN_SECONDS_TO_CLOSE or secs > MAX_SECONDS_TO_CLOSE:
            continue

        results.append(
            UpDownMarket(
                market=m,
                coin=coin,
                interval_minutes=interval,
                seconds_to_close=secs,
                up_outcome_index=_up_outcome_index(m.outcomes),
            )
        )
    return results


def get_market_price(token_id: str) -> float | None:
    try:
        resp = requests.get(
            f"{CLOB_API_URL}/midpoint",
            params={"token_id": token_id},
            timeout=5,
        )
        resp.raise_for_status()
        return float(resp.json()["mid"])
    except Exception:
        return None


def fetch_resolved_market(slug: str) -> dict | None:
    """Fetch a market by slug and return resolution info.

    Returns dict with 'outcomes' and 'outcome_prices' if the market
    is resolved (prices are exactly 0/1), or None if not yet resolved.
    """
    query_variants = [
        {"slug": slug},
        {"slug": slug, "active": "false"},
        {"slug": slug, "closed": "true"},
        {"slug": slug, "active": "false", "closed": "true"},
        {"slug": slug, "archived": "true"},
        {"slug": slug, "active": "false", "closed": "true", "archived": "true"},
    ]
    try:
        market = None
        for params in query_variants:
            resp = requests.get(
                f"{GAMMA_API_URL}/markets",
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                market = data[0]
                break

        if market is None:
            return None

        prices_raw = _parse_json_or_list(market.get("outcomePrices", "[]"))
        prices = [float(p) for p in prices_raw]
        outcomes = _parse_json_or_list(market.get("outcomes", '["Yes","No"]'))
        outcomes = [str(o) for o in outcomes]

        if not prices or len(prices) < 2:
            return None

        # Market is resolved when one side is effectively 1 and the other 0.
        # Gamma can occasionally surface tiny float noise around boundaries.
        hi = max(prices[0], prices[1])
        lo = min(prices[0], prices[1])
        is_resolved = hi >= 0.999 and lo <= 0.001
        if not is_resolved:
            return None

        return {"outcomes": outcomes, "outcome_prices": prices}
    except Exception:
        return None
