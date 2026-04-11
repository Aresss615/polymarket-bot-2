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
# 5-minute markets
MIN_SECONDS_TO_CLOSE_5M = 5       # Skip markets closing in <5s
MAX_SECONDS_TO_CLOSE_5M = 45      # Trade 5m markets closing within 45s
MIN_SECONDS_TO_TRADE_5M = 5       # Don't place trades with <5s remaining

# 15-minute markets — wider window since they're longer duration
MIN_SECONDS_TO_CLOSE_15M = 10     # Skip markets closing in <10s
MAX_SECONDS_TO_CLOSE_15M = 120    # Trade 15m markets closing within 2 minutes
MIN_SECONDS_TO_TRADE_15M = 10     # Higher cutoff — more time needed for execution

# Legacy aliases used by market_fetcher fetch_active_markets (interval-agnostic)
MIN_SECONDS_TO_CLOSE = 5
MAX_SECONDS_TO_CLOSE = 120        # Widened to accommodate 15m window
MIN_SECONDS_TO_TRADE = 5          # Per-interval override happens in analyzer
CRYPTO_NEAR_CERTAIN_UPPER = 0.88  # Skip markets already priced >88%
CRYPTO_NEAR_CERTAIN_LOWER = 0.12  # Skip markets already priced <12%
CRYPTO_SKIP_BAND_LOW = 0.38    # Skip "coin flip" zone: implied 38-62% has no edge
CRYPTO_SKIP_BAND_HIGH = 0.62
MIN_EDGE = 0.05                # Minimum edge to trade
MIN_LIQUIDITY = 500            # Minimum liquidity in dollars
MAX_BETS_PER_CYCLE = 5         # Max concurrent bets per 5-min cycle (raised: XRP/SOL are profitable)

# Per-coin minimum edge overrides — based on historical win rate and profitability
COIN_MIN_EDGE = {
    "BTC": 0.07,   # 60% WR, +$10.45 — most efficiently priced, NO side loses money, needs big edge
    "ETH": 0.06,   # 72% WR, +$22.57 — marginal, tighten filter
    "DOGE": 0.06,  # 78% WR, +$31.02 — solid performer
    "HYPE": 0.06,  # 81% WR, +$18.79 — good WR, slight bump from default
    # XRP: 85% WR, +$68.29 — uses default 0.05, best performer
    # SOL: 79% WR, +$50.62 — uses default 0.05
    # BNB: 79% WR, +$36.46 — uses default 0.05
}

# --- Arbitrage Settings ---
ARBITRAGE_CONFIDENCE_THRESHOLD = 0.85
NEWS_POLL_INTERVAL = 300  # 5 minutes

# --- Trading Settings ---
STARTING_BALANCE = 20.0
BET_FRACTION = 0.15       # risk 15% of balance per trade (data supports higher fraction at 72%+ WR)
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
    market_type: str = "5m"    # "5m" or "15m"
