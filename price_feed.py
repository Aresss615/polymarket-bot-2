import requests

from config import OKX_API_URL, BYBIT_API_URL, SUPPORTED_COINS

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
        bybit_symbol = symbol.replace("-", "")
        resp = requests.get(
            f"{BYBIT_API_URL}/market/tickers",
            params={"category": "spot", "symbol": bybit_symbol},
            timeout=5,
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
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": cg_id, "vs_currencies": "usd"},
            timeout=5,
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
            return price
        price = get_price_bybit(symbol)
        if price is not None:
            return price
    return get_price_coingecko(coin)
