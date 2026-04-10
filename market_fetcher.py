import json
from datetime import datetime

import requests

from config import GAMMA_API_URL, CLOB_API_URL, Market


def _parse_json_or_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return []


def fetch_active_markets(limit: int = 100) -> list[Market]:
    resp = requests.get(
        f"{GAMMA_API_URL}/markets",
        params={"active": "true", "closed": "false", "limit": limit},
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
