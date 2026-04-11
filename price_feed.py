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

# Price history for momentum tracking: coin -> [(timestamp, price), ...]
_price_history: dict[str, list[tuple[float, float]]] = {}
_HISTORY_WINDOW = 120  # keep 2 minutes of price history


def get_price_okx(symbol: str) -> float | None:
    try:
        resp = _session.get(
            f"{OKX_API_URL}/market/ticker",
            params={"instId": symbol},
            timeout=2,
        )
        resp.raise_for_status()
        return float(resp.json()["data"][0]["last"])
    except Exception:
        return None


def get_price_bybit(symbol: str) -> float | None:
    try:
        bybit_symbol = symbol.replace("-", "")
        resp = _session.get(
            f"{BYBIT_API_URL}/market/tickers",
            params={"category": "spot", "symbol": bybit_symbol},
            timeout=2,
        )
        resp.raise_for_status()
        return float(resp.json()["result"]["list"][0]["lastPrice"])
    except Exception:
        return None


def get_price_coingecko(coin: str) -> float | None:
    cg_id = COINGECKO_IDS.get(coin)
    if not cg_id:
        return None
    try:
        resp = _session.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": cg_id, "vs_currencies": "usd"},
            timeout=2,
        )
        resp.raise_for_status()
        return float(resp.json()[cg_id]["usd"])
    except Exception:
        return None


def get_price(coin: str) -> float | None:
    """Get current price. Tries OKX -> Bybit -> CoinGecko."""
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


def get_price_momentum(coin: str) -> float | None:
    """Get recent price momentum as a percentage change.

    Compares the latest price to the price ~30 seconds ago.
    Returns positive for upward movement, negative for downward.
    Returns None if insufficient data.
    """
    # First, fetch a fresh price to update history
    get_price(coin)

    history = _price_history.get(coin, [])
    if len(history) < 2:
        return None

    now = history[-1][0]
    latest_price = history[-1][1]

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
