import time
import warnings

import requests
import urllib3

from config import OKX_API_URL, BYBIT_API_URL, SUPPORTED_COINS

# Python 3.14 on macOS has broken SSL cert verification for most CEX APIs.
# Use a session with verification disabled for public market data endpoints.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_session = requests.Session()
_session.verify = False

# CoinGecko coin ID mapping
COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "DOGE": "dogecoin",
    "XRP": "ripple",
    "BNB": "binancecoin",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "MATIC": "matic-network",
    "NEAR": "near",
    "SUI": "sui",
    "APT": "aptos",
    "ARB": "arbitrum",
    "OP": "optimism",
    "HYPE": "hyperliquid",
}

# Reverse lookup: CoinGecko ID -> our coin ticker
_CG_ID_TO_COIN = {v: k for k, v in COINGECKO_IDS.items()}

# Price history for momentum tracking: coin -> [(timestamp, price), ...]
_price_history: dict[str, list[tuple[float, float]]] = {}
_HISTORY_WINDOW = 120  # keep 2 minutes of price history

# Source failure tracking: skip sources that repeatedly fail
_source_failures: dict[str, int] = {"okx": 0, "bybit": 0, "coingecko": 0}
_source_disabled_until: dict[str, float] = {"okx": 0, "bybit": 0, "coingecko": 0}
_SOURCE_FAIL_THRESHOLD = 3   # failures before disabling
_SOURCE_RETRY_INTERVAL = 300  # re-try disabled source after 5 min


def _is_source_available(source: str) -> bool:
    if _source_failures[source] < _SOURCE_FAIL_THRESHOLD:
        return True
    if time.time() >= _source_disabled_until[source]:
        # Reset and retry
        _source_failures[source] = 0
        return True
    return False


def _record_source_failure(source: str):
    _source_failures[source] += 1
    if _source_failures[source] >= _SOURCE_FAIL_THRESHOLD:
        _source_disabled_until[source] = time.time() + _SOURCE_RETRY_INTERVAL


def _record_source_success(source: str):
    _source_failures[source] = 0


def get_price_okx(symbol: str) -> float | None:
    if not _is_source_available("okx"):
        return None
    try:
        resp = _session.get(
            f"{OKX_API_URL}/market/ticker",
            params={"instId": symbol},
            timeout=2,
        )
        resp.raise_for_status()
        _record_source_success("okx")
        return float(resp.json()["data"][0]["last"])
    except Exception:
        _record_source_failure("okx")
        return None


def get_price_bybit(symbol: str) -> float | None:
    if not _is_source_available("bybit"):
        return None
    try:
        bybit_symbol = symbol.replace("-", "")
        resp = _session.get(
            f"{BYBIT_API_URL}/market/tickers",
            params={"category": "spot", "symbol": bybit_symbol},
            timeout=2,
        )
        resp.raise_for_status()
        _record_source_success("bybit")
        return float(resp.json()["result"]["list"][0]["lastPrice"])
    except Exception:
        _record_source_failure("bybit")
        return None


def get_price_coingecko(coin: str) -> float | None:
    cg_id = COINGECKO_IDS.get(coin)
    if not cg_id:
        return None
    try:
        resp = _session.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": cg_id, "vs_currencies": "usd"},
            timeout=3,
        )
        resp.raise_for_status()
        _record_source_success("coingecko")
        return float(resp.json()[cg_id]["usd"])
    except Exception:
        _record_source_failure("coingecko")
        return None


def get_prices_batch(coins: set[str]) -> dict[str, float]:
    """Fetch prices for multiple coins in a single CoinGecko API call.

    Returns dict of {coin: price} for coins that were successfully fetched.
    """
    cg_ids = []
    for coin in coins:
        cg_id = COINGECKO_IDS.get(coin)
        if cg_id:
            cg_ids.append(cg_id)

    if not cg_ids:
        return {}

    try:
        resp = _session.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(cg_ids), "vs_currencies": "usd"},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        _record_source_success("coingecko")

        result = {}
        for cg_id, price_data in data.items():
            coin = _CG_ID_TO_COIN.get(cg_id)
            if coin and "usd" in price_data:
                price = float(price_data["usd"])
                _record_price(coin, price)
                result[coin] = price
        return result
    except Exception:
        _record_source_failure("coingecko")
        return {}


def get_price(coin: str) -> float | None:
    """Get current price. Tries OKX -> Bybit -> CoinGecko, skipping dead sources."""
    symbol = SUPPORTED_COINS.get(coin)
    if symbol:
        price = get_price_okx(symbol)
        if price is not None:
            _record_price(coin, price)
            return price
        price = get_price_bybit(symbol)
        if price is not None:
            _record_price(coin, price)
            return price
    price = get_price_coingecko(coin)
    if price is not None:
        _record_price(coin, price)
    return price


def _record_price(coin: str, price: float) -> None:
    """Store a price observation for momentum calculation."""
    now = time.time()
    if coin not in _price_history:
        _price_history[coin] = []
    history = _price_history[coin]
    history.append((now, price))
    # Prune old entries
    cutoff = now - _HISTORY_WINDOW
    _price_history[coin] = [(t, p) for t, p in history if t >= cutoff]


def get_price_age(coin: str) -> float | None:
    """Return seconds since last price update for a coin, or None if no data."""
    history = _price_history.get(coin, [])
    if not history:
        return None
    return time.time() - history[-1][0]


def is_price_stale(coin: str, max_age: float = 30.0) -> bool:
    """Return True if the latest price for a coin is older than max_age seconds."""
    age = get_price_age(coin)
    return age is None or age > max_age


def get_price_momentum(coin: str) -> float | None:
    """Get recent price momentum as a percentage change.

    Compares the latest price to the price ~30 seconds ago.
    Returns positive for upward movement, negative for downward.
    Returns None if insufficient data or if price data is stale (>30s old).
    """
    # Only fetch a fresh price if cache is stale or empty — avoids slow
    # sequential OKX→Bybit→CoinGecko fallback during the critical path
    # (batch warming should have already seeded the cache this tick)
    if is_price_stale(coin, max_age=15.0):
        get_price(coin)

    history = _price_history.get(coin, [])
    if len(history) < 2:
        return None

    now = history[-1][0]
    latest_price = history[-1][1]

    # Reject stale data — if the latest price is too old, don't trust momentum
    if time.time() - now > 30:
        return None

    # Find the price closest to 30 seconds ago
    target_time = now - 30
    best_entry = None
    best_diff = float("inf")
    for t, p in history:
        diff = abs(t - target_time)
        if diff < best_diff:
            best_diff = diff
            best_entry = (t, p)

    if best_entry is None or best_entry == history[-1]:
        return None

    # Need at least 10 seconds of history for meaningful momentum
    time_span = now - best_entry[0]
    if time_span < 10:
        return None

    old_price = best_entry[1]
    if old_price == 0:
        return None

    return (latest_price - old_price) / old_price
