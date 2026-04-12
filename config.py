from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()

# --- Trading Mode ---
TRADING_MODE = os.getenv("TRADING_MODE", "paper")  # "paper", "simulation", "live"
_LIVE_BALANCE = float(os.getenv("LIVE_BALANCE", "5.0"))

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
MAX_SECONDS_TO_CLOSE_5M = 35      # 31-60s is 88% WR (best bucket); tightened to 45s — user prefers later entries
MIN_SECONDS_TO_TRADE_5M = 5       # Don't place trades with <5s remaining

# 15-minute markets — wider window since they're longer duration
MIN_SECONDS_TO_CLOSE_15M = 10     # Skip markets closing in <10s
MAX_SECONDS_TO_CLOSE_15M = 45     # Was 60; tightened to 45s to match 5m window
MIN_SECONDS_TO_TRADE_15M = 10     # Higher cutoff — more time needed for execution

# Legacy aliases used by market_fetcher fetch_active_markets (interval-agnostic)
MIN_SECONDS_TO_CLOSE = 5
MAX_SECONDS_TO_CLOSE = 120        # Widened to accommodate 15m window
MIN_SECONDS_TO_TRADE = 5          # Per-interval override happens in analyzer
CRYPTO_NEAR_CERTAIN_UPPER = 0.88  # Skip markets already priced >88%
CRYPTO_NEAR_CERTAIN_LOWER = 0.12  # Skip markets already priced <12%
CRYPTO_SKIP_BAND_LOW = 0.40    # Was 0.38; <0.60 entry has 58% WR — tighten
CRYPTO_SKIP_BAND_HIGH = 0.60   # Was 0.62; symmetric
MIN_EDGE = 0.05                # Minimum edge to trade
MIN_LIQUIDITY = 500            # Minimum liquidity in dollars
MAX_BETS_PER_CYCLE = 5         # Max concurrent bets per 5-min cycle (raised: XRP/SOL are profitable)
# --- Strategy Versioning ---
# Bump this every time you change strategy parameters. Analytics will only
# evaluate trades from the current version, preventing historical leakage.
STRATEGY_VERSION = 9

# Minimum trades in current patch before evaluating performance
MIN_PATCH_TRADES_FOR_EVAL = 20

# --- 15-Minute Market Adaptive Thresholds ---
# Instead of a static on/off flag, 15m mode is evaluated dynamically per-patch.
# These thresholds control when 15m markets are enabled/disabled/tightened.
ENABLE_15M_MIN_WIN_RATE = 0.65       # minimum win rate to keep 15m enabled
ENABLE_15M_MIN_PROFIT_FACTOR = 1.0   # minimum profit factor (gross profit / gross loss)
ENABLE_15M_MIN_AVG_PNL = 0.0         # minimum average PnL per trade

# Adaptive tightening: when performance is marginal, tighten these instead of disabling
ADAPTIVE_CONFIDENCE_BOOST = 0.10     # require this much more confidence when tightening
ADAPTIVE_EDGE_BOOST = 0.03           # require this much more edge when tightening

# Per-coin minimum edge overrides — based on historical win rate and profitability
COIN_MIN_EDGE = {
    "BTC": 0.08,   # 64% WR, -$7.17 — keep high, plus BTC NO is blacklisted
    # ETH, DOGE, HYPE: use default 0.05. Prior 0.06-0.08 overrides compounded
    # with NO premium + fee deduction to create 10%+ floors, killing volume.
}

# --- Signal Adjustments (data-driven from 451-trade analysis) ---
NO_SIDE_EDGE_PREMIUM = 0.01   # 1% extra; non-BTC NO was ~80% WR, BTC NO handled by blacklist
BTC_NO_BLACKLISTED = True      # BTC NO ~48% WR historically — block entirely

# --- Fee Model ---
MAX_TAKER_FEE_RATE = 0.018    # 1.8% dynamic taker fee at price 0.50, lower at extremes

# --- Risk Management ---
DAILY_MAX_LOSS = 10.0          # stop trading if daily realized losses exceed this
MAX_OPEN_EXPOSURE = 25.0       # max $ at risk across all pending trades
MAX_CONSECUTIVE_LOSSES = 5     # pause 1 cycle after this many consecutive losses
MAX_EXPOSURE_PER_COIN = 10.0   # max $ exposure on any single coin
SLIPPAGE_BUFFER = 0.02         # extra edge buffer for simulation/live modes

# --- Live Trading ($5 bankroll) ---
LIVE_MAX_BET = 5.00            # Polymarket min is 5 shares; at 0.90 = $4.50
LIVE_MIN_BET = 1.00            # base size (executor bumps to 5 shares minimum)
LIVE_DAILY_MAX_LOSS = 2.0      # stop at $2 daily loss (40% of bankroll)
LIVE_MAX_OPEN_EXPOSURE = 3.0   # max $3 at risk simultaneously

# --- Arbitrage Settings ---
ARBITRAGE_CONFIDENCE_THRESHOLD = 0.85
NEWS_POLL_INTERVAL = 300  # 5 minutes

# --- Trading Settings ---
STARTING_BALANCE = _LIVE_BALANCE if TRADING_MODE == "live" else 20.0
BET_FRACTION = 0.08       # base risk fraction per trade (was 0.15; reduced to prevent outsized losses)
MIN_BET = 1.0             # never bet less than $1
MAX_BET = 10.0            # never bet more than $10 (was $50; $20 losses took 23 wins to recover)
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
    strategy_version: int = 0  # patch version that generated this trade
    fees: float = 0.0          # execution fees charged
    fill_price: float | None = None  # actual fill price (None = same as entry_price)


@dataclass
class OrderResult:
    """Result of an order execution attempt."""
    filled: bool
    fill_price: float
    fill_size: float
    fees: float
    slippage: float
    latency_ms: float
    order_id: str
    status: str       # "filled", "partial", "rejected"
    reason: str = ""  # rejection reason if applicable


@dataclass
class RiskConfig:
    """Configuration for risk management."""
    daily_max_loss: float = DAILY_MAX_LOSS
    max_open_exposure: float = MAX_OPEN_EXPOSURE
    max_consecutive_losses: int = MAX_CONSECUTIVE_LOSSES
    max_exposure_per_coin: float = MAX_EXPOSURE_PER_COIN
