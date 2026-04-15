from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()

# --- Trading Mode ---
TRADING_MODE = os.getenv("TRADING_MODE", "paper")  # "paper", "simulation", "live"
_LIVE_BALANCE = float(os.getenv("LIVE_BALANCE", "5.0"))
SIMULATION_STARTING_BALANCE = float(os.getenv("SIMULATION_STARTING_BALANCE", "10000.0"))
PAPER_STARTING_BALANCE = float(os.getenv("PAPER_STARTING_BALANCE", "50.0"))
MONITOR_HOST = os.getenv("MONITOR_HOST", "127.0.0.1")
MONITOR_PORT = int(os.getenv("MONITOR_PORT", "8765"))

# --- API Endpoints ---
GAMMA_API_URL = "https://gamma-api.polymarket.com"
CLOB_API_URL = "https://clob.polymarket.com"
OKX_API_URL = "https://www.okx.com/api/v5"
BYBIT_API_URL = "https://api.bybit.com/v5"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
POLYMARKET_MARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
POLYMARKET_USER_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
POLYMARKET_RTDS_WS_URL = "wss://ws-live-data.polymarket.com/"
KALSHI_WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"

# --- Offline Research / LLM Settings ---
# These remain for offline research and labeling. They are intentionally disabled
# for live trading decisions in v11.
GROQ_PRIMARY_MODEL = "llama-3.3-70b-versatile"
GROQ_FALLBACK_MODEL = "llama-3.1-8b-instant"
ARBITRAGE_CONFIDENCE_THRESHOLD = 0.85
NEWS_POLL_INTERVAL = 300  # retained for offline research tooling

# --- Strategy Versioning ---
CODEX_VERSION = "1.3"
STRATEGY_VERSION = 13
MIN_PATCH_TRADES_FOR_EVAL = 20

# --- Strategy Modes ---
STRATEGY_MODE_DISABLED = "disabled"
STRATEGY_MODE_SHADOW = "shadow"
STRATEGY_MODE_LIVE = "live"

UPDOWN_5M_STRATEGY_MODE = os.getenv("UPDOWN_5M_STRATEGY_MODE", STRATEGY_MODE_LIVE)
UPDOWN_15M_STRATEGY_MODE = os.getenv("UPDOWN_15M_STRATEGY_MODE", STRATEGY_MODE_SHADOW)
BTC_NO_STRATEGY_MODE = os.getenv("BTC_NO_STRATEGY_MODE", STRATEGY_MODE_SHADOW)
ARBITRAGE_STRATEGY_MODE = os.getenv("ARBITRAGE_STRATEGY_MODE", STRATEGY_MODE_DISABLED)
STRUCTURAL_ARB_STRATEGY_MODE = os.getenv("STRUCTURAL_ARB_STRATEGY_MODE", STRATEGY_MODE_SHADOW)

VALID_STRATEGY_MODES = {
    STRATEGY_MODE_DISABLED,
    STRATEGY_MODE_SHADOW,
    STRATEGY_MODE_LIVE,
}


def normalize_strategy_mode(value: str | None, default: str = STRATEGY_MODE_DISABLED) -> str:
    mode = (value or "").strip().lower()
    return mode if mode in VALID_STRATEGY_MODES else default


# --- Crypto Deterministic Engine Settings ---
# 5-minute candidate path: only trade the measured cost-clearing window.
MIN_SECONDS_TO_CLOSE_5M = 15
MAX_SECONDS_TO_CLOSE_5M = 60
MIN_SECONDS_TO_TRADE_5M = 15

# 15-minute path stays shadow-only by default and only analyses two windows.
MIN_SECONDS_TO_CLOSE_15M = 25
MAX_SECONDS_TO_CLOSE_15M = 480
MIN_SECONDS_TO_TRADE_15M = 25
WINDOWS_15M = ((180, 480), (25, 70))

# Legacy aliases used by market discovery.
MIN_SECONDS_TO_CLOSE = min(MIN_SECONDS_TO_CLOSE_5M, MIN_SECONDS_TO_CLOSE_15M)
MAX_SECONDS_TO_CLOSE = max(MAX_SECONDS_TO_CLOSE_5M, MAX_SECONDS_TO_CLOSE_15M)
MIN_SECONDS_TO_TRADE = MIN_SECONDS_TO_TRADE_5M

CRYPTO_NEAR_CERTAIN_UPPER = 0.94
CRYPTO_NEAR_CERTAIN_LOWER = 0.06
CRYPTO_SHADOW_ONLY_UPPER = 0.97
CRYPTO_SHADOW_ONLY_LOWER = 0.03
CANDIDATE_MIN_ENTRY_PRICE = 0.40
CRYPTO_SKIP_BAND_LOW = 0.40
CRYPTO_SKIP_BAND_HIGH = 0.60
MIN_LIQUIDITY = 500
MAX_BETS_PER_CYCLE = 5
SIMULATION_MAX_BETS_PER_CYCLE = 1_000_000

MAX_REFERENCE_AGE_SECONDS = 2.0
REFERENCE_LOOKBACK_SECONDS = 20.0
REFERENCE_PRICE_NEUTRAL_BAND = 0.0006
REFERENCE_RETURN_PROBABILITY_SCALE_5M = 0.006
REFERENCE_RETURN_PROBABILITY_SCALE_15M = 0.009
WINDOW_OPEN_TRUST_TOLERANCE_SECONDS = 2.0
ACTUAL_MOVE_STRONG_RETURN_5M = 0.0030
ACTUAL_MOVE_STRONG_RETURN_15M = 0.0050
ACTUAL_MOVE_FLAT_RETURN_5M = 0.0008
ACTUAL_MOVE_FLAT_RETURN_15M = 0.0012
ACTUAL_MOVE_MAX_BOOK_AGE_MS = 1500.0
ACTUAL_MOVE_MAX_SPREAD = 0.03
ACTUAL_MOVE_EDGE_COST_MULTIPLE = 2.5
ACTUAL_MOVE_CANDIDATE_MAX_PRICE = 0.78
ACTUAL_MOVE_HIGH_PROB_UPPER = 0.90
MIN_EDGE = 0.06
MIN_EDGE_NEUTRAL = 0.09
MIN_EDGE_15M_MID = 0.10
MIN_EDGE_15M_CLOSE = 0.12
NO_SIDE_EDGE_PREMIUM = 0.02
SLIPPAGE_BUDGET = 0.010
CANCELLATION_COST_BUDGET = 0.005
COST_CLEARING_MULTIPLIER = 2.0
CHAINLINK_REQUIRED_15M = True
BTC_NO_MIN_SHADOW_SAMPLES = 200

# --- Candle-Aware Regime Rules ---
TREND_STRONG_INTERVAL_RETURN_5M = 0.0025
TREND_STRONG_INTERVAL_RETURN_15M = 0.0045
TREND_STRONG_LATE_RETURN_60S_5M = 0.0008
TREND_STRONG_LATE_RETURN_60S_15M = 0.0012
TREND_STRONG_LATE_RETURN_20S_5M = 0.0003
TREND_STRONG_LATE_RETURN_20S_15M = 0.0005
UNCERTAIN_INTERVAL_RETURN_5M = 0.0015
UNCERTAIN_INTERVAL_RETURN_15M = 0.0025
TREND_STRONG_MIN_BODY_RATIO = 0.60
TREND_MIXED_MAX_BODY_RATIO = 0.40

LIVE_CONFIDENCE_CAP = 0.90
NON_STRONG_CONFIDENCE_CAP = 0.75

TREND_STRONG_FOLLOW_SIZE_MULTIPLIER = 1.25
TREND_MIXED_SIZE_MULTIPLIER = 0.50
UNCERTAIN_SIZE_MULTIPLIER = 1.00
EXTREME_PRICE_SIZE_CAP_MULTIPLIER = 0.50

# BTC toxic-flow filter
BTC_TOXIC_FLOW_WEAK_ZSCORE = 0.5
BTC_TOXIC_FLOW_STRONG_ZSCORE = 1.0
BTC_TOXIC_FLOW_EXTRA_EDGE = 0.03
BTC_TOXIC_FLOW_SIZE_MULTIPLIER = 0.5

# --- 15-Minute Market Adaptive Thresholds ---
# The stats helper still computes this for monitoring, but 15m is shadow-only by
# default and never promoted to live automatically.
ENABLE_15M_MIN_WIN_RATE = 0.65
ENABLE_15M_MIN_PROFIT_FACTOR = 1.0
ENABLE_15M_MIN_AVG_PNL = 0.0
ADAPTIVE_CONFIDENCE_BOOST = 0.10
ADAPTIVE_EDGE_BOOST = 0.03

# --- Fee Model ---
MAX_TAKER_FEE_RATE = 0.018

# --- Risk Management ---
# Legacy absolute limits are retained as fallbacks when account equity is
# unavailable. The new engine sizes off equity percentages first.
DAILY_MAX_LOSS = 20.0
MAX_OPEN_EXPOSURE = 25.0
MAX_CONSECUTIVE_LOSSES = 5
MAX_EXPOSURE_PER_COIN = 10.0
CONSECUTIVE_LOSS_COOLDOWN_CYCLES = 1

TARGET_POSITION_PCT = 0.02
HARD_POSITION_CAP_PCT = 0.05
MAX_OPEN_EXPOSURE_PCT = 0.15
DAILY_REALIZED_LOSS_LIMIT_PCT = 0.05
MAX_DRAWDOWN_PCT = 0.10
PER_COIN_LOSS_STREAK = 3
PER_COIN_COOLDOWN_MINUTES = 30
GLOBAL_LOSS_STREAK = 5
GLOBAL_COOLDOWN_MINUTES = 60
MAX_POSITIONS_PER_COIN = 1
MAX_POSITIONS_PER_THESIS = 2
MAX_THESIS_EXPOSURE_PCT = 0.06
MAX_POSITIONS_PER_CLUSTER = 2
MAX_CLUSTER_EXPOSURE_PCT = 0.03
CLUSTER_SLIPPAGE_BREACH_LIMIT = 3
COIN_MARKOUT_BREACH_LIMIT = 3

# --- Live Trading ---
LIVE_MAX_BET = 5.00
LIVE_MIN_BET = 1.00
LIVE_DAILY_MAX_LOSS = 6.0
LIVE_MAX_OPEN_EXPOSURE = 6.0
LIVE_MAKER_POST_ONLY = True
LIVE_MAKER_IMPROVEMENT_TICKS = 1
LIVE_MAKER_MAX_AGE_SECONDS = 1.0
LIVE_MAKER_15M_MAX_AGE_SECONDS = 2.0
LIVE_MAKER_MAX_SPREAD = 0.04
LIVE_MAKER_MAX_SPREAD_TICKS = 4
LIVE_MAKER_DRIFT_TICKS = 2
LIVE_MAKER_OBI_AGAINST_THRESHOLD = 0.60
LIVE_MAKER_REFERENCE_REVERSAL = 0.0008  # 0.08%
FEED_HEARTBEAT_STALE_SECONDS = 3.0
REALTIME_DISCOVERY_REFRESH_SECONDS = 60.0
ENABLE_REALTIME_DATA_PLANE = os.getenv("ENABLE_REALTIME_DATA_PLANE", "1") == "1"

# --- Simulation Research Mode ---
# Research mode should keep gathering data instead of stopping early and
# should behave like a near-unbounded paper bankroll for stress/research runs.
SIMULATION_DAILY_MAX_LOSS = 1_000_000.0
SIMULATION_MAX_OPEN_EXPOSURE = 1_000_000.0
SIMULATION_MAX_EXPOSURE_PER_COIN = 1_000_000.0
SIMULATION_MAX_CONSECUTIVE_LOSSES = 1_000_000
SIMULATION_MAX_DRAWDOWN_PCT = 10.0
SIMULATION_PER_COIN_LOSS_STREAK = 1_000_000
SIMULATION_GLOBAL_LOSS_STREAK = 1_000_000
SIMULATION_PER_COIN_COOLDOWN_MINUTES = 0
SIMULATION_GLOBAL_COOLDOWN_MINUTES = 0
SIMULATION_MAX_POSITIONS_PER_COIN = 1_000_000
SIMULATION_MAX_POSITIONS_PER_THESIS = 1_000_000
SIMULATION_MAX_THESIS_EXPOSURE_PCT = 1_000.0
SIMULATION_MAX_OPEN_EXPOSURE_PCT = 1_000.0
SIMULATION_DAILY_REALIZED_LOSS_LIMIT_PCT = 1_000.0

# --- Trading Settings ---
if TRADING_MODE == "live":
    STARTING_BALANCE = _LIVE_BALANCE
elif TRADING_MODE == "simulation":
    STARTING_BALANCE = SIMULATION_STARTING_BALANCE
else:
    STARTING_BALANCE = PAPER_STARTING_BALANCE
BET_FRACTION = TARGET_POSITION_PCT
MIN_BET = 1.0
MAX_BET = 5.0
TICK_INTERVAL = 10.0

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
    "HYPE": "HYPE-USDT",
}

CANDIDATE_COINS = {"BTC", "SOL"}
SHADOW_ONLY_COINS = {"ETH", "XRP", "BNB"}

COIN_CLUSTERS = {
    "BTC": "crypto_beta",
    "ETH": "crypto_beta",
    "SOL": "crypto_beta",
    "XRP": "crypto_beta",
    "BNB": "crypto_beta",
    "DOGE": "crypto_beta",
    "ADA": "crypto_beta",
    "AVAX": "crypto_beta",
    "DOT": "crypto_beta",
    "LINK": "crypto_beta",
    "MATIC": "crypto_beta",
    "NEAR": "crypto_beta",
    "SUI": "crypto_beta",
    "APT": "crypto_beta",
    "ARB": "crypto_beta",
    "OP": "crypto_beta",
    "HYPE": "crypto_beta",
}

# --- File Paths ---
TRADES_CSV = Path("trades.csv")
OPEN_ORDERS_CSV = Path("open_orders.csv")
TRADES_JSONL = Path("trades.jsonl")
EVENTS_JSONL = Path("events.jsonl")
HISTORY_ARCHIVE_DIR = Path("history_archive")
HISTORY_ARCHIVE_MANIFEST = HISTORY_ARCHIVE_DIR / "manifest.jsonl"


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
    strategy: str
    side: str
    confidence: float
    reason: str
    strategy_mode: str = STRATEGY_MODE_LIVE
    market_type: str = "5m"
    coin: str = ""
    edge_gross: float = 0.0
    edge_net: float = 0.0
    reference_symbol: str = ""
    reference_price: float | None = None
    reference_age_seconds: float | None = None
    reference_zscore: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    decision_latency_ms: float = 0.0
    thesis_id: str = ""
    size_multiplier: float = 1.0
    model_up_probability: float | None = None
    selected_side_probability: float | None = None
    interval_open: float | None = None
    interval_high: float | None = None
    interval_low: float | None = None
    interval_close: float | None = None
    interval_return: float | None = None
    late_return_60s: float | None = None
    late_return_20s: float | None = None
    body_ratio: float | None = None
    wick_imbalance: float | None = None
    candle_regime: str = ""
    trend_alignment: str = ""
    market_yes_at_open: float | None = None
    market_yes_at_decision: float | None = None
    market_yes_at_close: float | None = None
    contrarian_block_reason: str = ""
    wallet_signal_source: str = ""
    wallet_lead_score: float | None = None
    wallet_cluster: str = ""
    window_start_ts: float | None = None
    window_open_price: float | None = None
    window_open_source: str = ""
    window_open_price_trusted: bool = False
    actual_window_return: float | None = None
    actual_move_regime: str = ""
    actual_move_side: str = ""
    strategy_route: str = ""
    cluster_id: str = ""
    signal_epoch_id: str = ""
    book_age_ms: float | None = None
    tick_size: float | None = None
    expected_fill_price: float | None = None
    expected_cost: float | None = None
    markout_1s: float | None = None
    markout_5s: float | None = None
    markout_30s: float | None = None


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
    market_type: str = "5m"
    strategy_version: int = 0
    fees: float = 0.0
    fill_price: float | None = None
    order_id: str = ""
    executor_type: str = ""
    edge_gross: float = 0.0
    edge_net: float = 0.0
    reference_symbol: str = ""
    reference_price: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    decision_latency_ms: float = 0.0
    thesis_id: str = ""
    cancel_reason: str = ""
    strategy_mode: str = STRATEGY_MODE_LIVE
    model_up_probability: float | None = None
    selected_side_probability: float | None = None
    interval_open: float | None = None
    interval_high: float | None = None
    interval_low: float | None = None
    interval_close: float | None = None
    interval_return: float | None = None
    late_return_60s: float | None = None
    late_return_20s: float | None = None
    body_ratio: float | None = None
    wick_imbalance: float | None = None
    candle_regime: str = ""
    trend_alignment: str = ""
    market_yes_at_open: float | None = None
    market_yes_at_decision: float | None = None
    market_yes_at_close: float | None = None
    contrarian_block_reason: str = ""
    wallet_signal_source: str = ""
    wallet_lead_score: float | None = None
    wallet_cluster: str = ""
    window_start_ts: float | None = None
    window_open_price: float | None = None
    window_open_source: str = ""
    window_open_price_trusted: bool = False
    actual_window_return: float | None = None
    actual_move_regime: str = ""
    actual_move_side: str = ""
    strategy_route: str = ""
    cluster_id: str = ""
    signal_epoch_id: str = ""
    book_age_ms: float | None = None
    tick_size: float | None = None
    expected_fill_price: float | None = None
    expected_cost: float | None = None
    markout_1s: float | None = None
    markout_5s: float | None = None
    markout_30s: float | None = None


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
    reason: str = ""
    fill_shares: float = 0.0
    remaining_size: float = 0.0
    remaining_shares: float = 0.0
    reserved_size: float = 0.0
    requested_size: float = 0.0
    requested_shares: float = 0.0
    token_id: str = ""
    needs_reconciliation: bool = False
    terminal: bool = True
    raw_status: str = ""
    raw_response: dict = field(default_factory=dict)
    edge_gross: float = 0.0
    edge_net: float = 0.0
    reference_symbol: str = ""
    reference_price: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    decision_latency_ms: float = 0.0
    thesis_id: str = ""
    cancel_reason: str = ""
    strategy_mode: str = STRATEGY_MODE_LIVE
    model_up_probability: float | None = None
    selected_side_probability: float | None = None
    interval_open: float | None = None
    interval_high: float | None = None
    interval_low: float | None = None
    interval_close: float | None = None
    interval_return: float | None = None
    late_return_60s: float | None = None
    late_return_20s: float | None = None
    body_ratio: float | None = None
    wick_imbalance: float | None = None
    candle_regime: str = ""
    trend_alignment: str = ""
    market_yes_at_open: float | None = None
    market_yes_at_decision: float | None = None
    market_yes_at_close: float | None = None
    contrarian_block_reason: str = ""
    wallet_signal_source: str = ""
    wallet_lead_score: float | None = None
    wallet_cluster: str = ""
    window_start_ts: float | None = None
    window_open_price: float | None = None
    window_open_source: str = ""
    window_open_price_trusted: bool = False
    actual_window_return: float | None = None
    actual_move_regime: str = ""
    actual_move_side: str = ""
    strategy_route: str = ""
    cluster_id: str = ""
    signal_epoch_id: str = ""
    book_age_ms: float | None = None
    tick_size: float | None = None
    expected_fill_price: float | None = None
    expected_cost: float | None = None
    markout_1s: float | None = None
    markout_5s: float | None = None
    markout_30s: float | None = None


@dataclass
class OpenOrder:
    """Persisted live order state awaiting reconciliation."""

    order_id: str
    created_at: datetime
    updated_at: datetime
    market_slug: str
    question: str
    condition_id: str
    token_id: str
    strategy: str
    side: str
    confidence: float
    reason: str
    end_date: datetime | None
    market_type: str
    strategy_version: int
    executor_type: str
    limit_price: float
    requested_size: float
    requested_shares: float
    reserved_size: float
    confirmed_fill_size: float = 0.0
    confirmed_fill_shares: float = 0.0
    confirmed_fees: float = 0.0
    status: str = "submitted"
    raw_status: str = ""
    edge_gross: float = 0.0
    edge_net: float = 0.0
    reference_symbol: str = ""
    reference_price: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    decision_latency_ms: float = 0.0
    thesis_id: str = ""
    cancel_reason: str = ""
    strategy_mode: str = STRATEGY_MODE_LIVE
    coin: str = ""
    model_up_probability: float | None = None
    selected_side_probability: float | None = None
    interval_open: float | None = None
    interval_high: float | None = None
    interval_low: float | None = None
    interval_close: float | None = None
    interval_return: float | None = None
    late_return_60s: float | None = None
    late_return_20s: float | None = None
    body_ratio: float | None = None
    wick_imbalance: float | None = None
    candle_regime: str = ""
    trend_alignment: str = ""
    market_yes_at_open: float | None = None
    market_yes_at_decision: float | None = None
    market_yes_at_close: float | None = None
    contrarian_block_reason: str = ""
    wallet_signal_source: str = ""
    wallet_lead_score: float | None = None
    wallet_cluster: str = ""
    window_start_ts: float | None = None
    window_open_price: float | None = None
    window_open_source: str = ""
    window_open_price_trusted: bool = False
    actual_window_return: float | None = None
    actual_move_regime: str = ""
    actual_move_side: str = ""
    strategy_route: str = ""
    cluster_id: str = ""
    signal_epoch_id: str = ""
    book_age_ms: float | None = None
    tick_size: float | None = None
    expected_fill_price: float | None = None
    expected_cost: float | None = None
    markout_1s: float | None = None
    markout_5s: float | None = None
    markout_30s: float | None = None


@dataclass
class RiskConfig:
    """Configuration for risk management."""

    daily_max_loss: float = DAILY_MAX_LOSS
    max_open_exposure: float = MAX_OPEN_EXPOSURE
    max_consecutive_losses: int = MAX_CONSECUTIVE_LOSSES
    max_exposure_per_coin: float = MAX_EXPOSURE_PER_COIN
    max_drawdown_pct: float = MAX_DRAWDOWN_PCT
    consecutive_loss_cooldown_cycles: int = CONSECUTIVE_LOSS_COOLDOWN_CYCLES
    target_position_pct: float = TARGET_POSITION_PCT
    hard_position_cap_pct: float = HARD_POSITION_CAP_PCT
    max_open_exposure_pct: float = MAX_OPEN_EXPOSURE_PCT
    daily_realized_loss_limit_pct: float = DAILY_REALIZED_LOSS_LIMIT_PCT
    per_coin_loss_streak: int = PER_COIN_LOSS_STREAK
    per_coin_cooldown_minutes: int = PER_COIN_COOLDOWN_MINUTES
    global_loss_streak: int = GLOBAL_LOSS_STREAK
    global_cooldown_minutes: int = GLOBAL_COOLDOWN_MINUTES
    max_positions_per_coin: int = MAX_POSITIONS_PER_COIN
    max_positions_per_thesis: int = MAX_POSITIONS_PER_THESIS
    max_thesis_exposure_pct: float = MAX_THESIS_EXPOSURE_PCT
    max_positions_per_cluster: int = MAX_POSITIONS_PER_CLUSTER
    max_cluster_exposure_pct: float = MAX_CLUSTER_EXPOSURE_PCT
