from dataclasses import dataclass, field
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

# --- Crypto UpDown Settings ---
MIN_SECONDS_TO_CLOSE = 5       # Skip markets closing in <5s
MAX_SECONDS_TO_CLOSE = 120     # Only target markets closing within 120s
CRYPTO_NEAR_CERTAIN_UPPER = 0.92  # Skip markets already priced >92%
CRYPTO_NEAR_CERTAIN_LOWER = 0.08  # Skip markets already priced <8%
MIN_EDGE = 0.03                # Minimum edge to trade
MIN_LIQUIDITY = 500            # Minimum liquidity in dollars

# --- Arbitrage Settings ---
ARBITRAGE_CONFIDENCE_THRESHOLD = 0.85
NEWS_POLL_INTERVAL = 300  # 5 minutes

# --- Trading Settings ---
STARTING_BALANCE = 20.0
BET_FRACTION = 0.10       # risk 10% of balance per trade
MIN_BET = 1.0             # never bet less than $1
MAX_BET = 50.0            # never bet more than $50
TICK_INTERVAL = 10.0      # seconds between ticks (fast for crypto updown)

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
class UpDownMarket:
    market: Market
    coin: str
    interval_minutes: int
    seconds_to_close: int
    up_outcome_index: int  # 0 or 1


@dataclass
class Article:
    title: str
    source: str
    url: str
    published_at: datetime | None


@dataclass
class Signal:
    market: Market
    strategy: str  # "updown" or "arbitrage"
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
    status: str = "pending"   # pending, won, lost
    payout: float = 0.0
    end_date: datetime | None = None
