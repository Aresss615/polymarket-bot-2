import requests

from config import OKX_API_URL, BYBIT_API_URL, SUPPORTED_COINS


def get_price_okx(symbol: str) -> float | None:
    try:
        resp = requests.get(
            f"{OKX_API_URL}/market/ticker",
            params={"instId": symbol},
            timeout=5,
        )
        resp.raise_for_status()
        return float(resp.json()["data"][0]["last"])
    except Exception:
        return None


def get_price_bybit(symbol: str) -> float | None:
    try:
        bybit_symbol = symbol.replace("-", "")  # BTC-USDT -> BTCUSDT
        resp = requests.get(
            f"{BYBIT_API_URL}/market/tickers",
            params={"category": "spot", "symbol": bybit_symbol},
            timeout=5,
        )
        resp.raise_for_status()
        return float(resp.json()["result"]["list"][0]["lastPrice"])
    except Exception:
        return None


def get_price(coin: str) -> float | None:
    symbol = SUPPORTED_COINS.get(coin)
    if not symbol:
        return None
    price = get_price_okx(symbol)
    if price is None:
        price = get_price_bybit(symbol)
    return price
