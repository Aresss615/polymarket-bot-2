from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()

# --- API Endpoints ---
GAMMA_API_URL = "https://gamma-api.polymarket.com"
CLOB_API_URL = "https://clob.polymarket.com"
OKX_API_URL = "https://www.okx.com/api/v5"
BYBIT_API_URL = "https://api.bybit.com/v5"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"

# --- Groq LLM Settings ---
GROQ_PRIMARY_MODEL = "llama-3.3-70b-versatile"
GROQ_FALLBACK_MODEL = "llama-3.1-8b-instant"

# --- Strategy Settings ---
ARBITRAGE_CONFIDENCE_THRESHOLD = 0.85
LEVEL_CLEARANCE_PCT = 0.015  # 1.5%
LEVEL_WINDOW_MINUTES = 10
NEWS_POLL_INTERVAL = 300  # 5 minutes — fits within 70B's 1K RPD limit
TRADE_SIZE = 10.0  # dollars per paper trade
STARTING_BALANCE = 1000.0

# --- Supported Coins (ticker -> OKX instrument ID) ---
SUPPORTED_COINS = {
    "BTC": "BTC-USDT",
    "ETH": "ETH-USDT",
    "SOL": "SOL-USDT",
    "DOGE": "DOGE-USDT",
    "XRP": "XRP-USDT",
    "BNB": "BNB-USDT",
    "ADA": "ADA-USDT",
    "AVAX": "AVAX-USDT",
    "DOT": "DOT-USDT",
    "LINK": "LINK-USDT",
    "MATIC": "MATIC-USDT",
    "NEAR": "NEAR-USDT",
    "SUI": "SUI-USDT",
    "APT": "APT-USDT",
    "ARB": "ARB-USDT",
    "OP": "OP-USDT",
}

# --- File Paths ---
TRADES_CSV = Path("trades.csv")


# --- Data Models ---


@dataclass
class Market:
    condition_id: str
    question: str
    slug: str
    outcomes: list[str]
    outcome_prices: list[float]
    token_ids: list[str]
    end_date: datetime | None
    active: bool


@dataclass
class Article:
    title: str
    source: str
    url: str
    published_at: datetime | None


@dataclass
class LevelMarket:
    market: Market
    coin: str
    threshold: float
    direction: str  # "above" or "below"
    expiry: datetime


@dataclass
class Signal:
    market: Market
    strategy: str  # "level" or "arbitrage"
    side: str  # "YES" or "NO"
    confidence: float
    reason: str


@dataclass
class Trade:
    timestamp: datetime
    market_slug: str
    question: str
    strategy: str
    side: str
    entry_price: float
    size: float
    confidence: float
    reason: str
