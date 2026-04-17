import time
import warnings

import requests
import urllib3

from config import (
    CHAINLINK_REQUIRED_15M,
    BYBIT_API_URL,
    MAX_REFERENCE_AGE_SECONDS_FALLBACK,
    MAX_REFERENCE_AGE_SECONDS_REALTIME,
    MAX_REFERENCE_AGE_SECONDS,
    OKX_API_URL,
    REFERENCE_LOOKBACK_SECONDS,
    RTDS_STRICT_MODE,
    SUPPORTED_COINS,
    WINDOW_OPEN_TRUST_TOLERANCE_SECONDS,
)
from runtime_data import RUNTIME_DATA_PLANE, WEBSOCKET_CLIENT_AVAILABLE
from state_cache import REFERENCE_CACHE

# Python 3.14 on macOS has broken SSL cert verification for most CEX APIs.
# On Windows/Linux this works fine, so only disable on macOS.
import sys as _sys

_session = requests.Session()
if _sys.platform == "darwin":
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
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

_CG_ID_TO_COIN = {v: k for k, v in COINGECKO_IDS.items()}
CRYPTOCOMPARE_API_URL = "https://min-api.cryptocompare.com/data"

# Legacy price history used by tests and the analyzer.
_price_history: dict[str, list[tuple[float, float]]] = {}
_HISTORY_WINDOW = 180

# Source failure tracking: skip sources that repeatedly fail
_source_failures: dict[str, int] = {"okx": 0, "bybit": 0, "cryptocompare": 0, "coingecko": 0}
_source_disabled_until: dict[str, float] = {"okx": 0, "bybit": 0, "cryptocompare": 0, "coingecko": 0}
_SOURCE_FAIL_THRESHOLD = 3
_SOURCE_RETRY_INTERVAL = 300


def _is_source_available(source: str) -> bool:
    if _source_failures[source] < _SOURCE_FAIL_THRESHOLD:
        return True
    if time.time() >= _source_disabled_until[source]:
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


def get_price_cryptocompare(coin: str) -> float | None:
    if not _is_source_available("cryptocompare"):
        return None
    try:
        resp = _session.get(
            f"{CRYPTOCOMPARE_API_URL}/price",
            params={"fsym": coin.upper(), "tsyms": "USD"},
            timeout=3,
        )
        resp.raise_for_status()
        payload = resp.json()
        price = payload.get("USD")
        if price in (None, ""):
            raise ValueError(f"missing USD price for {coin}")
        _record_source_success("cryptocompare")
        return float(price)
    except Exception:
        _record_source_failure("cryptocompare")
        return None


def _record_price(coin: str, price: float, *, source: str = "poll", chainlink: bool = False) -> None:
    now = time.time()
    if not chainlink:
        history = _price_history.setdefault(coin, [])
        history.append((now, price))
        cutoff = now - _HISTORY_WINDOW
        _price_history[coin] = [(t, p) for t, p in history if t >= cutoff]
    REFERENCE_CACHE.update(coin, price, source=source, chainlink=chainlink, timestamp=now)


def inject_reference_price(
    coin: str,
    price: float,
    *,
    source: str = "manual",
    chainlink: bool = False,
    timestamp: float | None = None,
) -> None:
    """Test/streaming hook for updating the reference cache without polling."""
    ts = timestamp if timestamp is not None else time.time()
    if not chainlink:
        history = _price_history.setdefault(coin.upper(), [])
        history.append((ts, price))
        cutoff = ts - _HISTORY_WINDOW
        _price_history[coin.upper()] = [(t, p) for t, p in history if t >= cutoff]
    REFERENCE_CACHE.update(coin.upper(), price, source=source, chainlink=chainlink, timestamp=ts)


def get_prices_batch(coins: set[str]) -> dict[str, float]:
    """Fetch prices for multiple coins, preferring low-friction batch APIs."""
    normalized_coins = {coin.upper() for coin in coins}
    result: dict[str, float] = {}

    try:
        resp = _session.get(
            f"{CRYPTOCOMPARE_API_URL}/pricemulti",
            params={"fsyms": ",".join(sorted(normalized_coins)), "tsyms": "USD"},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        for symbol, price_data in data.items():
            price = (price_data or {}).get("USD") if isinstance(price_data, dict) else None
            if price in (None, ""):
                continue
            coin = str(symbol).upper()
            _record_price(coin, float(price), source="cryptocompare_batch")
            result[coin] = float(price)
        if result:
            _record_source_success("cryptocompare")
    except Exception:
        _record_source_failure("cryptocompare")

    missing = normalized_coins.difference(result)
    cg_ids = [COINGECKO_IDS[coin] for coin in missing if coin in COINGECKO_IDS]
    if cg_ids:
        try:
            resp = _session.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": ",".join(cg_ids), "vs_currencies": "usd"},
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
            _record_source_success("coingecko")

            for cg_id, price_data in data.items():
                coin = _CG_ID_TO_COIN.get(cg_id)
                if coin and "usd" in price_data:
                    price = float(price_data["usd"])
                    _record_price(coin, price, source="coingecko_batch")
                    result[coin] = price
        except Exception:
            _record_source_failure("coingecko")

    missing = normalized_coins.difference(result)
    for coin in missing:
        price = get_price(coin)
        if price is not None:
            result[coin] = price
    return result


def get_price(coin: str) -> float | None:
    """Get current price. Tries OKX -> Bybit -> CryptoCompare -> CoinGecko."""
    coin = coin.upper()
    symbol = SUPPORTED_COINS.get(coin)
    if symbol:
        price = get_price_okx(symbol)
        if price is not None:
            _record_price(coin, price, source="okx")
            return price
        price = get_price_bybit(symbol)
        if price is not None:
            _record_price(coin, price, source="bybit")
            return price
    price = get_price_cryptocompare(coin)
    if price is not None:
        _record_price(coin, price, source="cryptocompare")
        return price
    price = get_price_coingecko(coin)
    if price is not None:
        _record_price(coin, price, source="coingecko")
    return price


def get_price_age(coin: str) -> float | None:
    cache_age = REFERENCE_CACHE.age_seconds(coin.upper())
    if cache_age is not None:
        return cache_age
    history = _price_history.get(coin.upper(), [])
    if not history:
        return None
    return time.time() - history[-1][0]


def reference_feed_mode() -> str:
    if not RTDS_STRICT_MODE:
        return "poll-fallback"
    if not WEBSOCKET_CLIENT_AVAILABLE or not RUNTIME_DATA_PLANE.reference_stream_available():
        return "poll-fallback"
    if not REFERENCE_CACHE.feed_healthy(MAX_REFERENCE_AGE_SECONDS_REALTIME):
        return "poll-fallback"
    return "realtime"


def active_reference_max_age_seconds() -> float:
    if not RTDS_STRICT_MODE:
        return MAX_REFERENCE_AGE_SECONDS_FALLBACK
    return (
        MAX_REFERENCE_AGE_SECONDS_REALTIME
        if reference_feed_mode() == "realtime"
        else MAX_REFERENCE_AGE_SECONDS_FALLBACK
    )


def reference_feed_status() -> dict:
    diagnostics = RUNTIME_DATA_PLANE.diagnostics()
    return {
        "mode": reference_feed_mode(),
        "strict_mode": RTDS_STRICT_MODE,
        "max_age_seconds": active_reference_max_age_seconds(),
        "reference_feed_healthy": REFERENCE_CACHE.feed_healthy(MAX_REFERENCE_AGE_SECONDS_REALTIME),
        "websocket_client_available": WEBSOCKET_CLIENT_AVAILABLE,
        "runtime": diagnostics,
    }


def is_price_stale(coin: str, max_age: float | None = None) -> bool:
    limit = active_reference_max_age_seconds() if max_age is None else max_age
    age = get_price_age(coin)
    return age is None or age > limit


def ensure_reference_recent(coin: str, max_age: float | None = None) -> bool:
    limit = active_reference_max_age_seconds() if max_age is None else max_age
    coin = coin.upper()
    cached_price = REFERENCE_CACHE.price(coin)
    cached_age = REFERENCE_CACHE.age_seconds(coin)
    if cached_price is not None and cached_age is not None and cached_age <= limit:
        return True
    refreshed_price = get_price(coin)
    if refreshed_price is None:
        return False
    refreshed_age = REFERENCE_CACHE.age_seconds(coin)
    return refreshed_age is not None and refreshed_age <= limit


def get_reference_snapshot(
    coin: str,
    *,
    interval_minutes: int | None = None,
    window_start_ts: float | None = None,
    window_tolerance_seconds: float = WINDOW_OPEN_TRUST_TOLERANCE_SECONDS,
) -> dict:
    coin = coin.upper()
    state = REFERENCE_CACHE.get(coin)
    prefer_chainlink = bool(interval_minutes == 15 and CHAINLINK_REQUIRED_15M)
    snapshot = {
        "coin": coin,
        "price": REFERENCE_CACHE.price(coin),
        "chainlink_price": state.chainlink_price if state else None,
        "age_seconds": REFERENCE_CACHE.age_seconds(coin),
        "chainlink_age_seconds": REFERENCE_CACHE.age_seconds(coin, prefer_chainlink=True),
        "return_lookback": REFERENCE_CACHE.return_over_window(
            coin,
            window_seconds=REFERENCE_LOOKBACK_SECONDS,
        ),
        "zscore": REFERENCE_CACHE.rolling_return_zscore(
            coin,
            window_seconds=REFERENCE_LOOKBACK_SECONDS,
        ),
        "source": state.source if state else "",
        "active_reference_price": REFERENCE_CACHE.price(coin, prefer_chainlink=prefer_chainlink),
        "active_reference_age_seconds": REFERENCE_CACHE.age_seconds(coin, prefer_chainlink=prefer_chainlink),
    }
    if interval_minutes:
        snapshot.update(
            REFERENCE_CACHE.candle_features(
                coin,
                window_seconds=float(interval_minutes * 60),
                prefer_chainlink=prefer_chainlink,
                fallback_to_spot=True,
            )
        )
    if window_start_ts is not None:
        anchor = REFERENCE_CACHE.window_anchor(
            coin,
            target_timestamp=window_start_ts,
            tolerance_seconds=window_tolerance_seconds,
            prefer_chainlink=prefer_chainlink,
            allow_spot_fallback=True,
        )
        snapshot.update(
            {
                "window_start_ts": window_start_ts,
                "window_open_price": anchor.get("price"),
                "window_open_ts": anchor.get("timestamp"),
                "window_open_source": anchor.get("source"),
                "window_open_price_trusted": bool(anchor.get("trusted")),
                "window_open_anchor_age_seconds": anchor.get("anchor_age_seconds"),
            }
        )
    return snapshot


def get_reference_zscore(coin: str, window_seconds: float = REFERENCE_LOOKBACK_SECONDS) -> float | None:
    return REFERENCE_CACHE.rolling_return_zscore(coin.upper(), window_seconds=window_seconds)


def get_reference_return(coin: str, window_seconds: float = REFERENCE_LOOKBACK_SECONDS) -> float | None:
    return REFERENCE_CACHE.return_over_window(coin.upper(), window_seconds=window_seconds)


def get_price_momentum(coin: str) -> float | None:
    """Compatibility wrapper around the new reference-return model."""
    coin = coin.upper()
    if is_price_stale(coin, max_age=MAX_REFERENCE_AGE_SECONDS):
        get_price(coin)
    reference_return = get_reference_return(coin, window_seconds=REFERENCE_LOOKBACK_SECONDS)
    if reference_return is not None:
        return reference_return

    history = _price_history.get(coin, [])
    if len(history) < 2:
        return None

    now = history[-1][0]
    latest_price = history[-1][1]
    target_time = now - REFERENCE_LOOKBACK_SECONDS
    best_entry = None
    best_diff = float("inf")
    for t, p in history:
        diff = abs(t - target_time)
        if diff < best_diff:
            best_diff = diff
            best_entry = (t, p)
    if best_entry is None or best_entry == history[-1]:
        return None
    time_span = now - best_entry[0]
    if time_span < 10:
        return None
    old_price = best_entry[1]
    if old_price == 0:
        return None
    return (latest_price - old_price) / old_price
