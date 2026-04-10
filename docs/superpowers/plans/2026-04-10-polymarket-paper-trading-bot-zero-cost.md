# Polymarket Paper Trading Bot (Zero-Cost) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a paper trading bot that monitors Polymarket markets using two strategies — resolution arbitrage (matching news headlines to markets via Groq LLM) and crypto level markets (betting on obvious price outcomes near expiry) — with a Rich terminal dashboard and CSV trade logging. Total API cost: $0.

**Architecture:** Synchronous Python with threading. Engine loop polls Polymarket markets every 30s and news every 5 minutes. Two strategies run independently each tick. Dashboard runs on the main thread via Rich Live. All trades are paper-only, logged to CSV. LLM calls use Groq free tier with automatic model fallback (70B primary, 8B when rate-limited).

**Tech Stack:** Python 3.14, requests, groq, feedparser, rich, python-dotenv, pytest

---

## File Structure

```
polymarket-bot-2/
├── pyproject.toml          # Dependencies, pytest config
├── .env.example            # Template for API keys
├── .gitignore              # Python ignores + .env + trades.csv
├── config.py               # Constants, API URLs, data models
├── price_feed.py           # OKX price fetch, Bybit fallback
├── market_fetcher.py       # Polymarket Gamma + CLOB API client
├── news_fetcher.py         # Google News RSS
├── level_analyzer.py       # Crypto level strategy (regex + math)
├── arbitrage_analyzer.py   # Resolution arbitrage (Groq LLM matching)
├── engine.py               # Main trading engine loop
├── logger.py               # CSV trade logging
├── dashboard.py            # Rich terminal UI
├── main.py                 # Entry point
└── tests/
    ├── conftest.py         # Shared fixtures
    ├── test_config.py      # Model tests
    ├── test_logger.py      # CSV read/write tests
    ├── test_price_feed.py  # Mocked OKX/Bybit tests
    ├── test_market_fetcher.py  # Mocked Gamma/CLOB tests
    ├── test_news_fetcher.py    # Mocked RSS tests
    ├── test_level_analyzer.py  # Regex + signal logic tests
    ├── test_arbitrage_analyzer.py  # Mocked Groq tests
    └── test_engine.py      # Engine coordination tests
```

**Responsibilities:**

| File | Responsibility |
|------|---------------|
| `config.py` | All constants, API URLs, thresholds, and dataclass models (`Market`, `Article`, `LevelMarket`, `Signal`, `Trade`) |
| `price_feed.py` | `get_price(coin) -> float | None` — OKX primary, Bybit fallback |
| `market_fetcher.py` | `fetch_active_markets() -> list[Market]` from Gamma API; `get_market_price(token_id) -> float | None` from CLOB API |
| `news_fetcher.py` | `fetch_google_news() -> list[Article]` from Google News RSS |
| `level_analyzer.py` | `parse_level_market(market) -> LevelMarket | None`, `find_level_markets(markets) -> list[LevelMarket]`, `analyze_level_opportunity(level_market, price, now) -> Signal | None` |
| `arbitrage_analyzer.py` | `analyze_headlines(articles, markets) -> list[Signal]` — calls Groq (70B primary, 8B fallback) for reading comprehension matching |
| `engine.py` | `Engine` class with `tick() -> list[Trade]`, `run(interval)`, `stop()`, `execute_paper_trade(signal) -> Trade` |
| `logger.py` | `init_csv()`, `log_trade(trade)`, `read_trades() -> list[Trade]` |
| `dashboard.py` | `make_dashboard(engine) -> Layout`, `run_dashboard(engine)` — Rich Live display |
| `main.py` | Entry point — init, start engine thread, run dashboard, handle Ctrl+C |

---

## Rate Limit Budget

All free-tier, $0 total.

| API | Rate Limit | Our Usage | Headroom |
|-----|-----------|-----------|----------|
| Groq `llama-3.3-70b-versatile` | 1,000 RPD / 100K TPD | ~288 RPD (5min poll) | 71% spare |
| Groq `llama-3.1-8b-instant` (fallback) | 14,400 RPD / 500K TPD | Only on 429s | Massive |
| Polymarket Gamma | 15,000/10s | ~2,880/day | Negligible |
| Polymarket CLOB | Unlimited (read) | ~2,880/day | — |
| OKX v5 | 20/2s | ~2,880/day | Fine |
| Bybit v5 | Generous | Fallback only | — |
| Google News RSS | Unlimited | ~288/day | — |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "polymarket-bot"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "requests>=2.31",
    "groq>=0.11",
    "feedparser>=6.0",
    "rich>=13.0",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 2: Create .env.example**

```
GROQ_API_KEY=your-groq-api-key
```

- [ ] **Step 3: Create .gitignore**

```
__pycache__/
*.pyc
*.pyo
.env
trades.csv
.venv/
*.egg-info/
dist/
build/
.pytest_cache/
```

- [ ] **Step 4: Create tests/__init__.py**

```python
```

(Empty file — makes `tests/` a package for pytest discovery.)

- [ ] **Step 5: Create virtual environment and install dependencies**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: All dependencies install successfully.

- [ ] **Step 6: Verify pytest runs**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest --co -q
```

Expected: `no tests ran` (no test files yet).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .env.example .gitignore tests/__init__.py
git commit -m "chore: project scaffolding with dependencies and pytest config"
```

---

## Task 2: config.py — Constants and Data Models

**Files:**
- Create: `config.py`
- Create: `tests/conftest.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the tests**

Create `tests/test_config.py`:

```python
from datetime import datetime, timezone

from config import (
    Market,
    Article,
    LevelMarket,
    Signal,
    Trade,
    GAMMA_API_URL,
    CLOB_API_URL,
    OKX_API_URL,
    BYBIT_API_URL,
    GOOGLE_NEWS_RSS_URL,
    GROQ_PRIMARY_MODEL,
    GROQ_FALLBACK_MODEL,
    SUPPORTED_COINS,
    ARBITRAGE_CONFIDENCE_THRESHOLD,
    LEVEL_CLEARANCE_PCT,
    LEVEL_WINDOW_MINUTES,
    TRADE_SIZE,
    STARTING_BALANCE,
    NEWS_POLL_INTERVAL,
)


def test_market_dataclass():
    m = Market(
        condition_id="0xabc",
        question="Will BTC be above $84,000?",
        slug="btc-above-84k",
        outcomes=["Yes", "No"],
        outcome_prices=[0.65, 0.35],
        token_ids=["0xyes", "0xno"],
        end_date=datetime(2026, 4, 10, 21, 0, tzinfo=timezone.utc),
        active=True,
    )
    assert m.condition_id == "0xabc"
    assert m.outcome_prices[0] == 0.65
    assert m.active is True


def test_article_dataclass():
    a = Article(
        title="Fed raises rates",
        source="Reuters",
        url="https://example.com",
        published_at=datetime(2026, 4, 10, tzinfo=timezone.utc),
    )
    assert a.title == "Fed raises rates"
    assert a.source == "Reuters"


def test_signal_dataclass():
    m = Market(
        condition_id="0x1",
        question="Test?",
        slug="test",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
        token_ids=["0xa", "0xb"],
        end_date=None,
        active=True,
    )
    s = Signal(market=m, strategy="level", side="YES", confidence=0.95, reason="test")
    assert s.strategy == "level"
    assert s.confidence == 0.95


def test_trade_dataclass():
    t = Trade(
        timestamp=datetime.now(timezone.utc),
        market_slug="test",
        question="Test?",
        strategy="level",
        side="YES",
        entry_price=0.65,
        size=10.0,
        confidence=0.95,
        reason="test reason",
    )
    assert t.size == 10.0
    assert t.entry_price == 0.65


def test_constants():
    assert GAMMA_API_URL == "https://gamma-api.polymarket.com"
    assert CLOB_API_URL == "https://clob.polymarket.com"
    assert OKX_API_URL == "https://www.okx.com/api/v5"
    assert BYBIT_API_URL == "https://api.bybit.com/v5"
    assert GOOGLE_NEWS_RSS_URL == "https://news.google.com/rss/search"
    assert GROQ_PRIMARY_MODEL == "llama-3.3-70b-versatile"
    assert GROQ_FALLBACK_MODEL == "llama-3.1-8b-instant"
    assert ARBITRAGE_CONFIDENCE_THRESHOLD == 0.85
    assert LEVEL_CLEARANCE_PCT == 0.015
    assert LEVEL_WINDOW_MINUTES == 10
    assert NEWS_POLL_INTERVAL == 300
    assert TRADE_SIZE == 10.0
    assert STARTING_BALANCE == 1000.0
    assert "BTC" in SUPPORTED_COINS
    assert SUPPORTED_COINS["BTC"] == "BTC-USDT"
```

- [ ] **Step 2: Create shared test fixtures**

Create `tests/conftest.py`:

```python
import pytest
from datetime import datetime, timezone

from config import Market, Article, LevelMarket


@pytest.fixture
def sample_market():
    return Market(
        condition_id="0xabc123",
        question="Will BTC be above $84,000 at 5pm ET on April 10?",
        slug="btc-above-84000-apr-10",
        outcomes=["Yes", "No"],
        outcome_prices=[0.65, 0.35],
        token_ids=["0xtoken_yes", "0xtoken_no"],
        end_date=datetime(2026, 4, 10, 21, 0, tzinfo=timezone.utc),
        active=True,
    )


@pytest.fixture
def sample_non_level_market():
    return Market(
        condition_id="0xdef456",
        question="Will the Fed raise rates in April?",
        slug="fed-raise-rates-april",
        outcomes=["Yes", "No"],
        outcome_prices=[0.40, 0.60],
        token_ids=["0xtoken_yes2", "0xtoken_no2"],
        end_date=datetime(2026, 4, 30, 21, 0, tzinfo=timezone.utc),
        active=True,
    )


@pytest.fixture
def sample_article():
    return Article(
        title="Federal Reserve raises interest rates by 0.25%",
        source="Reuters",
        url="https://reuters.com/article/123",
        published_at=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_level_market(sample_market):
    return LevelMarket(
        market=sample_market,
        coin="BTC",
        threshold=84000.0,
        direction="above",
        expiry=sample_market.end_date,
    )


@pytest.fixture
def tmp_csv(tmp_path):
    return tmp_path / "test_trades.csv"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 4: Implement config.py**

Create `config.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest tests/test_config.py -v
```

Expected: All 5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add config.py tests/conftest.py tests/test_config.py
git commit -m "feat: add config module with constants and data models"
```

---

## Task 3: logger.py — CSV Trade Logging

**Files:**
- Create: `logger.py`
- Create: `tests/test_logger.py`

- [ ] **Step 1: Write the tests**

Create `tests/test_logger.py`:

```python
from datetime import datetime, timezone

from config import Trade
from logger import init_csv, log_trade, read_trades, CSV_FIELDS


def _make_trade(**overrides):
    defaults = dict(
        timestamp=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
        market_slug="btc-above-84k",
        question="Will BTC be above $84,000?",
        strategy="level",
        side="YES",
        entry_price=0.65,
        size=10.0,
        confidence=0.95,
        reason="price is 2% above threshold",
    )
    defaults.update(overrides)
    return Trade(**defaults)


def test_init_csv_creates_header(tmp_csv):
    init_csv(tmp_csv)
    content = tmp_csv.read_text()
    assert "timestamp" in content
    assert "market_slug" in content
    assert "strategy" in content


def test_init_csv_idempotent(tmp_csv):
    init_csv(tmp_csv)
    init_csv(tmp_csv)
    lines = tmp_csv.read_text().strip().split("\n")
    assert len(lines) == 1  # only one header


def test_log_trade_writes_row(tmp_csv):
    trade = _make_trade()
    log_trade(trade, tmp_csv)
    lines = tmp_csv.read_text().strip().split("\n")
    assert len(lines) == 2  # header + 1 trade
    assert "btc-above-84k" in lines[1]
    assert "level" in lines[1]
    assert "YES" in lines[1]


def test_log_multiple_trades(tmp_csv):
    log_trade(_make_trade(market_slug="trade-1"), tmp_csv)
    log_trade(_make_trade(market_slug="trade-2"), tmp_csv)
    lines = tmp_csv.read_text().strip().split("\n")
    assert len(lines) == 3  # header + 2 trades


def test_read_trades_empty(tmp_csv):
    trades = read_trades(tmp_csv)
    assert trades == []


def test_read_trades_roundtrip(tmp_csv):
    original = _make_trade()
    log_trade(original, tmp_csv)
    trades = read_trades(tmp_csv)
    assert len(trades) == 1
    assert trades[0].market_slug == "btc-above-84k"
    assert trades[0].side == "YES"
    assert trades[0].entry_price == 0.65
    assert trades[0].size == 10.0
    assert trades[0].confidence == 0.95


def test_csv_fields_match_trade():
    trade = _make_trade()
    for field in CSV_FIELDS:
        assert hasattr(trade, field), f"Trade missing field: {field}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest tests/test_logger.py -v
```

Expected: `ModuleNotFoundError: No module named 'logger'`

- [ ] **Step 3: Implement logger.py**

Create `logger.py`:

```python
import csv
from datetime import datetime
from pathlib import Path

from config import Trade, TRADES_CSV

CSV_FIELDS = [
    "timestamp",
    "market_slug",
    "question",
    "strategy",
    "side",
    "entry_price",
    "size",
    "confidence",
    "reason",
]


def init_csv(path: Path = TRADES_CSV) -> None:
    if not path.exists():
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_FIELDS)


def log_trade(trade: Trade, path: Path = TRADES_CSV) -> None:
    init_csv(path)
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                trade.timestamp.isoformat(),
                trade.market_slug,
                trade.question,
                trade.strategy,
                trade.side,
                f"{trade.entry_price:.4f}",
                f"{trade.size:.2f}",
                f"{trade.confidence:.2f}",
                trade.reason,
            ]
        )


def read_trades(path: Path = TRADES_CSV) -> list[Trade]:
    if not path.exists():
        return []
    trades = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(
                Trade(
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    market_slug=row["market_slug"],
                    question=row["question"],
                    strategy=row["strategy"],
                    side=row["side"],
                    entry_price=float(row["entry_price"]),
                    size=float(row["size"]),
                    confidence=float(row["confidence"]),
                    reason=row["reason"],
                )
            )
    return trades
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest tests/test_logger.py -v
```

Expected: All 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add logger.py tests/test_logger.py
git commit -m "feat: add CSV trade logger with read/write roundtrip"
```

---

## Task 4: price_feed.py — OKX + Bybit Price Fetching

**Files:**
- Create: `price_feed.py`
- Create: `tests/test_price_feed.py`

- [ ] **Step 1: Write the tests**

Create `tests/test_price_feed.py`:

```python
from unittest.mock import patch, MagicMock

from price_feed import get_price_okx, get_price_bybit, get_price


def _mock_okx_response(price: str):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"data": [{"last": price}]}
    return resp


def _mock_bybit_response(price: str):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"result": {"list": [{"lastPrice": price}]}}
    return resp


@patch("price_feed.requests.get")
def test_get_price_okx_success(mock_get):
    mock_get.return_value = _mock_okx_response("84500.5")
    price = get_price_okx("BTC-USDT")
    assert price == 84500.5
    mock_get.assert_called_once()
    assert "instId" in str(mock_get.call_args)


@patch("price_feed.requests.get")
def test_get_price_okx_failure(mock_get):
    mock_get.side_effect = Exception("timeout")
    price = get_price_okx("BTC-USDT")
    assert price is None


@patch("price_feed.requests.get")
def test_get_price_bybit_success(mock_get):
    mock_get.return_value = _mock_bybit_response("84500.5")
    price = get_price_bybit("BTC-USDT")
    assert price == 84500.5


@patch("price_feed.requests.get")
def test_get_price_bybit_failure(mock_get):
    mock_get.side_effect = Exception("timeout")
    price = get_price_bybit("BTC-USDT")
    assert price is None


@patch("price_feed.get_price_okx")
def test_get_price_uses_okx_first(mock_okx):
    mock_okx.return_value = 84500.5
    price = get_price("BTC")
    assert price == 84500.5


@patch("price_feed.get_price_bybit")
@patch("price_feed.get_price_okx")
def test_get_price_falls_back_to_bybit(mock_okx, mock_bybit):
    mock_okx.return_value = None
    mock_bybit.return_value = 84500.5
    price = get_price("BTC")
    assert price == 84500.5


@patch("price_feed.get_price_okx")
def test_get_price_unsupported_coin(mock_okx):
    price = get_price("FAKECOIN")
    assert price is None
    mock_okx.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest tests/test_price_feed.py -v
```

Expected: `ModuleNotFoundError: No module named 'price_feed'`

- [ ] **Step 3: Implement price_feed.py**

Create `price_feed.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest tests/test_price_feed.py -v
```

Expected: All 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add price_feed.py tests/test_price_feed.py
git commit -m "feat: add price feed with OKX primary and Bybit fallback"
```

---

## Task 5: market_fetcher.py — Polymarket API Client

**Files:**
- Create: `market_fetcher.py`
- Create: `tests/test_market_fetcher.py`

- [ ] **Step 1: Write the tests**

Create `tests/test_market_fetcher.py`:

```python
from unittest.mock import patch, MagicMock
import json

from market_fetcher import fetch_active_markets, get_market_price


SAMPLE_GAMMA_RESPONSE = [
    {
        "conditionId": "0xabc123",
        "question": "Will BTC be above $84,000 at 5pm ET?",
        "slug": "btc-above-84k",
        "outcomes": '["Yes","No"]',
        "outcomePrices": '["0.65","0.35"]',
        "clobTokenIds": '["0xyes","0xno"]',
        "endDate": "2026-04-10T21:00:00Z",
        "active": True,
    },
    {
        "conditionId": "0xdef456",
        "question": "Will the Fed raise rates?",
        "slug": "fed-rates",
        "outcomes": '["Yes","No"]',
        "outcomePrices": '["0.40","0.60"]',
        "clobTokenIds": '["0xyes2","0xno2"]',
        "endDate": "2026-04-30T21:00:00Z",
        "active": True,
    },
]


def _mock_gamma_response():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = SAMPLE_GAMMA_RESPONSE
    return resp


@patch("market_fetcher.requests.get")
def test_fetch_active_markets(mock_get):
    mock_get.return_value = _mock_gamma_response()
    markets = fetch_active_markets()
    assert len(markets) == 2
    assert markets[0].condition_id == "0xabc123"
    assert markets[0].question == "Will BTC be above $84,000 at 5pm ET?"
    assert markets[0].outcome_prices == [0.65, 0.35]
    assert markets[0].token_ids == ["0xyes", "0xno"]
    assert markets[0].end_date is not None
    assert markets[1].slug == "fed-rates"


@patch("market_fetcher.requests.get")
def test_fetch_active_markets_with_list_fields(mock_get):
    """Gamma API sometimes returns lists instead of JSON strings."""
    data = [
        {
            "conditionId": "0x111",
            "question": "Test?",
            "slug": "test",
            "outcomes": ["Yes", "No"],
            "outcomePrices": [0.5, 0.5],
            "clobTokenIds": ["0xa", "0xb"],
            "endDate": "2026-04-10T21:00:00Z",
            "active": True,
        }
    ]
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = data
    mock_get.return_value = resp
    markets = fetch_active_markets()
    assert len(markets) == 1
    assert markets[0].outcome_prices == [0.5, 0.5]


@patch("market_fetcher.requests.get")
def test_fetch_active_markets_skips_bad_data(mock_get):
    data = [{"bad": "data"}, SAMPLE_GAMMA_RESPONSE[0]]
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = data
    mock_get.return_value = resp
    markets = fetch_active_markets()
    assert len(markets) == 1


@patch("market_fetcher.requests.get")
def test_get_market_price_success(mock_get):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"mid": "0.65"}
    mock_get.return_value = resp
    price = get_market_price("0xtoken_yes")
    assert price == 0.65


@patch("market_fetcher.requests.get")
def test_get_market_price_failure(mock_get):
    mock_get.side_effect = Exception("timeout")
    price = get_market_price("0xtoken_yes")
    assert price is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest tests/test_market_fetcher.py -v
```

Expected: `ModuleNotFoundError: No module named 'market_fetcher'`

- [ ] **Step 3: Implement market_fetcher.py**

Create `market_fetcher.py`:

```python
import json

import requests

from config import GAMMA_API_URL, CLOB_API_URL, Market


def _parse_json_or_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return []


def fetch_active_markets(limit: int = 100) -> list[Market]:
    resp = requests.get(
        f"{GAMMA_API_URL}/markets",
        params={"active": "true", "closed": "false", "limit": limit},
        timeout=10,
    )
    resp.raise_for_status()

    markets = []
    for m in resp.json():
        try:
            prices_raw = _parse_json_or_list(m.get("outcomePrices", "[]"))
            prices = [float(p) for p in prices_raw]

            token_ids = _parse_json_or_list(m.get("clobTokenIds", "[]"))

            outcomes_raw = _parse_json_or_list(m.get("outcomes", '["Yes","No"]'))
            outcomes = [str(o) for o in outcomes_raw]

            end_date = None
            if m.get("endDate"):
                from datetime import datetime

                end_date = datetime.fromisoformat(
                    m["endDate"].replace("Z", "+00:00")
                )

            markets.append(
                Market(
                    condition_id=m["conditionId"],
                    question=m.get("question", ""),
                    slug=m.get("slug", ""),
                    outcomes=outcomes,
                    outcome_prices=prices,
                    token_ids=token_ids,
                    end_date=end_date,
                    active=m.get("active", True),
                )
            )
        except (KeyError, ValueError, json.JSONDecodeError):
            continue
    return markets


def get_market_price(token_id: str) -> float | None:
    try:
        resp = requests.get(
            f"{CLOB_API_URL}/midpoint",
            params={"token_id": token_id},
            timeout=5,
        )
        resp.raise_for_status()
        return float(resp.json()["mid"])
    except Exception:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest tests/test_market_fetcher.py -v
```

Expected: All 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add market_fetcher.py tests/test_market_fetcher.py
git commit -m "feat: add Polymarket market fetcher with Gamma and CLOB APIs"
```

---

## Task 6: news_fetcher.py — Google News RSS

**Files:**
- Create: `news_fetcher.py`
- Create: `tests/test_news_fetcher.py`

Google News RSS is the sole news source. No API key needed, unlimited requests.

- [ ] **Step 1: Write the tests**

Create `tests/test_news_fetcher.py`:

```python
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from config import Article
from news_fetcher import fetch_google_news


@patch("news_fetcher.feedparser.parse")
def test_fetch_google_news_success(mock_parse):
    entry = MagicMock()
    entry.get.side_effect = lambda k, d=None: {
        "title": "Markets rally on trade deal",
        "link": "https://news.google.com/1",
    }.get(k, d)
    entry.published_parsed = (2026, 4, 10, 12, 0, 0, 0, 0, 0)
    entry.source = {"title": "Bloomberg"}

    mock_parse.return_value = MagicMock(entries=[entry])
    articles = fetch_google_news()
    assert len(articles) == 1
    assert articles[0].title == "Markets rally on trade deal"


@patch("news_fetcher.feedparser.parse")
def test_fetch_google_news_multiple_entries(mock_parse):
    entries = []
    for i, title in enumerate(["Headline A", "Headline B", "Headline C"]):
        entry = MagicMock()
        entry.get.side_effect = lambda k, d=None, t=title: {
            "title": t,
            "link": f"https://news.google.com/{t}",
        }.get(k, d)
        entry.published_parsed = (2026, 4, 10, 12, i, 0, 0, 0, 0)
        entry.source = {"title": "AP"}
        entries.append(entry)

    mock_parse.return_value = MagicMock(entries=entries)
    articles = fetch_google_news()
    assert len(articles) == 3
    assert articles[0].title == "Headline A"
    assert articles[2].title == "Headline C"


@patch("news_fetcher.feedparser.parse")
def test_fetch_google_news_no_source(mock_parse):
    entry = MagicMock()
    entry.get.side_effect = lambda k, d=None: {
        "title": "Test headline",
        "link": "https://example.com",
    }.get(k, d)
    entry.published_parsed = None
    entry.source = None

    mock_parse.return_value = MagicMock(entries=[entry])
    articles = fetch_google_news()
    assert len(articles) == 1
    assert articles[0].source == "Google News"
    assert articles[0].published_at is None


@patch("news_fetcher.feedparser.parse")
def test_fetch_google_news_failure(mock_parse):
    mock_parse.side_effect = Exception("parse error")
    articles = fetch_google_news()
    assert articles == []


@patch("news_fetcher.feedparser.parse")
def test_fetch_google_news_deduplicates(mock_parse):
    entries = []
    for title in ["Same headline", "Same headline", "Different headline"]:
        entry = MagicMock()
        entry.get.side_effect = lambda k, d=None, t=title: {
            "title": t,
            "link": "https://example.com",
        }.get(k, d)
        entry.published_parsed = (2026, 4, 10, 12, 0, 0, 0, 0, 0)
        entry.source = {"title": "AP"}
        entries.append(entry)

    mock_parse.return_value = MagicMock(entries=entries)
    articles = fetch_google_news()
    assert len(articles) == 2
    titles = [a.title for a in articles]
    assert "Same headline" in titles
    assert "Different headline" in titles
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest tests/test_news_fetcher.py -v
```

Expected: `ModuleNotFoundError: No module named 'news_fetcher'`

- [ ] **Step 3: Implement news_fetcher.py**

Create `news_fetcher.py`:

```python
from datetime import datetime

import feedparser

from config import GOOGLE_NEWS_RSS_URL, Article


def fetch_google_news(query: str = "politics economy world") -> list[Article]:
    try:
        url = f"{GOOGLE_NEWS_RSS_URL}?q={query.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        seen: set[str] = set()
        articles: list[Article] = []
        for entry in feed.entries[:20]:
            title = entry.get("title", "")
            if title in seen:
                continue
            seen.add(title)

            pub = None
            if (
                hasattr(entry, "published_parsed")
                and entry.published_parsed
            ):
                pub = datetime(*entry.published_parsed[:6])

            source_name = "Google News"
            if hasattr(entry, "source") and isinstance(entry.source, dict):
                source_name = entry.source.get("title", "Google News")

            articles.append(
                Article(
                    title=title,
                    source=source_name,
                    url=entry.get("link", ""),
                    published_at=pub,
                )
            )
        return articles
    except Exception:
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest tests/test_news_fetcher.py -v
```

Expected: All 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add news_fetcher.py tests/test_news_fetcher.py
git commit -m "feat: add Google News RSS fetcher with deduplication"
```

---

## Task 7: level_analyzer.py — Crypto Level Strategy

**Files:**
- Create: `level_analyzer.py`
- Create: `tests/test_level_analyzer.py`

This is the most logic-heavy module — pure functions, no I/O, best test coverage.

- [ ] **Step 1: Write the tests**

Create `tests/test_level_analyzer.py`:

```python
from datetime import datetime, timezone, timedelta

from config import Market, LevelMarket, Signal, LEVEL_CLEARANCE_PCT, LEVEL_WINDOW_MINUTES
from level_analyzer import parse_level_market, find_level_markets, analyze_level_opportunity


# --- parse_level_market tests ---


def test_parse_btc_above(sample_market):
    """sample_market question: 'Will BTC be above $84,000 at 5pm ET on April 10?'"""
    lm = parse_level_market(sample_market)
    assert lm is not None
    assert lm.coin == "BTC"
    assert lm.threshold == 84000.0
    assert lm.direction == "above"
    assert lm.expiry == sample_market.end_date


def test_parse_eth_below():
    m = Market(
        condition_id="0x1",
        question="Will ETH be below $1,800 at 12pm ET on April 11?",
        slug="eth-below-1800",
        outcomes=["Yes", "No"],
        outcome_prices=[0.3, 0.7],
        token_ids=["0xa", "0xb"],
        end_date=datetime(2026, 4, 11, 16, 0, tzinfo=timezone.utc),
        active=True,
    )
    lm = parse_level_market(m)
    assert lm is not None
    assert lm.coin == "ETH"
    assert lm.threshold == 1800.0
    assert lm.direction == "below"


def test_parse_sol_with_decimals():
    m = Market(
        condition_id="0x2",
        question="Will SOL be above $130.50 at 3pm ET?",
        slug="sol-above-130",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
        token_ids=["0xa", "0xb"],
        end_date=datetime(2026, 4, 10, 19, 0, tzinfo=timezone.utc),
        active=True,
    )
    lm = parse_level_market(m)
    assert lm is not None
    assert lm.coin == "SOL"
    assert lm.threshold == 130.50


def test_parse_non_level_market(sample_non_level_market):
    """'Will the Fed raise rates in April?' — not a level market."""
    lm = parse_level_market(sample_non_level_market)
    assert lm is None


def test_parse_no_end_date():
    m = Market(
        condition_id="0x3",
        question="Will BTC be above $80,000 at 5pm ET?",
        slug="btc-80k",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
        token_ids=["0xa", "0xb"],
        end_date=None,
        active=True,
    )
    lm = parse_level_market(m)
    assert lm is None


def test_parse_with_comma_in_price():
    m = Market(
        condition_id="0x4",
        question="Will BTC be above $100,000 at 5pm ET?",
        slug="btc-100k",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
        token_ids=["0xa", "0xb"],
        end_date=datetime(2026, 4, 10, 21, 0, tzinfo=timezone.utc),
        active=True,
    )
    lm = parse_level_market(m)
    assert lm is not None
    assert lm.threshold == 100000.0


# --- find_level_markets tests ---


def test_find_level_markets(sample_market, sample_non_level_market):
    results = find_level_markets([sample_market, sample_non_level_market])
    assert len(results) == 1
    assert results[0].coin == "BTC"


def test_find_level_markets_empty():
    assert find_level_markets([]) == []


# --- analyze_level_opportunity tests ---


def test_signal_yes_when_price_above_threshold(sample_level_market):
    """BTC at $86,000 is 2.4% above $84,000 threshold — should signal YES."""
    now = sample_level_market.expiry - timedelta(minutes=5)
    signal = analyze_level_opportunity(sample_level_market, 86000.0, now=now)
    assert signal is not None
    assert signal.side == "YES"
    assert signal.strategy == "level"
    assert signal.confidence > 0


def test_signal_no_when_price_below_threshold(sample_level_market):
    """BTC at $82,000 is 2.4% below $84,000 threshold — should signal NO."""
    now = sample_level_market.expiry - timedelta(minutes=5)
    signal = analyze_level_opportunity(sample_level_market, 82000.0, now=now)
    assert signal is not None
    assert signal.side == "NO"


def test_no_signal_when_too_close_to_threshold(sample_level_market):
    """BTC at $84,500 is only 0.6% above $84,000 — below 1.5% clearance."""
    now = sample_level_market.expiry - timedelta(minutes=5)
    signal = analyze_level_opportunity(sample_level_market, 84500.0, now=now)
    assert signal is None


def test_no_signal_when_too_far_from_expiry(sample_level_market):
    """More than 10 minutes to expiry — too early."""
    now = sample_level_market.expiry - timedelta(minutes=30)
    signal = analyze_level_opportunity(sample_level_market, 86000.0, now=now)
    assert signal is None


def test_no_signal_after_expiry(sample_level_market):
    """Market already expired."""
    now = sample_level_market.expiry + timedelta(minutes=5)
    signal = analyze_level_opportunity(sample_level_market, 86000.0, now=now)
    assert signal is None


def test_below_direction_yes():
    """'Will ETH be below $2000' — ETH at $1900 should signal YES."""
    m = Market(
        condition_id="0x5",
        question="Will ETH be below $2,000 at 5pm ET?",
        slug="eth-below-2k",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
        token_ids=["0xa", "0xb"],
        end_date=datetime(2026, 4, 10, 21, 0, tzinfo=timezone.utc),
        active=True,
    )
    lm = LevelMarket(market=m, coin="ETH", threshold=2000.0, direction="below", expiry=m.end_date)
    now = lm.expiry - timedelta(minutes=5)
    signal = analyze_level_opportunity(lm, 1900.0, now=now)
    assert signal is not None
    assert signal.side == "YES"


def test_below_direction_no():
    """'Will ETH be below $2000' — ETH at $2100 should signal NO."""
    m = Market(
        condition_id="0x6",
        question="Will ETH be below $2,000 at 5pm ET?",
        slug="eth-below-2k",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
        token_ids=["0xa", "0xb"],
        end_date=datetime(2026, 4, 10, 21, 0, tzinfo=timezone.utc),
        active=True,
    )
    lm = LevelMarket(market=m, coin="ETH", threshold=2000.0, direction="below", expiry=m.end_date)
    now = lm.expiry - timedelta(minutes=5)
    signal = analyze_level_opportunity(lm, 2100.0, now=now)
    assert signal is not None
    assert signal.side == "NO"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest tests/test_level_analyzer.py -v
```

Expected: `ModuleNotFoundError: No module named 'level_analyzer'`

- [ ] **Step 3: Implement level_analyzer.py**

Create `level_analyzer.py`:

```python
import re
from datetime import datetime, timezone

from config import (
    Market,
    LevelMarket,
    Signal,
    SUPPORTED_COINS,
    LEVEL_CLEARANCE_PCT,
    LEVEL_WINDOW_MINUTES,
)

COINS_PATTERN = "|".join(SUPPORTED_COINS.keys())

LEVEL_RE = re.compile(
    rf"Will\s+({COINS_PATTERN})\s+(?:be|close)\s+(above|below)\s+\$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)


def parse_level_market(market: Market) -> LevelMarket | None:
    match = LEVEL_RE.search(market.question)
    if not match:
        return None
    if not market.end_date:
        return None

    coin = match.group(1).upper()
    direction = match.group(2).lower()
    threshold = float(match.group(3).replace(",", ""))

    return LevelMarket(
        market=market,
        coin=coin,
        threshold=threshold,
        direction=direction,
        expiry=market.end_date,
    )


def find_level_markets(markets: list[Market]) -> list[LevelMarket]:
    results = []
    for m in markets:
        lm = parse_level_market(m)
        if lm:
            results.append(lm)
    return results


def analyze_level_opportunity(
    level_market: LevelMarket,
    current_price: float,
    now: datetime | None = None,
) -> Signal | None:
    if now is None:
        now = datetime.now(timezone.utc)

    minutes_to_expiry = (level_market.expiry - now).total_seconds() / 60

    if minutes_to_expiry < 0 or minutes_to_expiry > LEVEL_WINDOW_MINUTES:
        return None

    clearance = abs(current_price - level_market.threshold) / level_market.threshold

    if clearance < LEVEL_CLEARANCE_PCT:
        return None

    price_above_threshold = current_price > level_market.threshold

    if level_market.direction == "above":
        side = "YES" if price_above_threshold else "NO"
    else:  # "below"
        side = "YES" if not price_above_threshold else "NO"

    reason = (
        f"{level_market.coin} at ${current_price:,.2f} is {clearance:.1%} "
        f"{'above' if price_above_threshold else 'below'} "
        f"${level_market.threshold:,.2f} with {minutes_to_expiry:.0f}min to expiry"
    )

    return Signal(
        market=level_market.market,
        strategy="level",
        side=side,
        confidence=min(clearance / LEVEL_CLEARANCE_PCT, 1.0),
        reason=reason,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest tests/test_level_analyzer.py -v
```

Expected: All 14 tests pass.

- [ ] **Step 5: Commit**

```bash
git add level_analyzer.py tests/test_level_analyzer.py
git commit -m "feat: add crypto level analyzer with regex parsing and signal logic"
```

---

## Task 8: arbitrage_analyzer.py — Resolution Arbitrage with Groq

**Files:**
- Create: `arbitrage_analyzer.py`
- Create: `tests/test_arbitrage_analyzer.py`

This is the key module that changed from the original plan. Uses Groq free tier with automatic model fallback: `llama-3.3-70b-versatile` primary, falls back to `llama-3.1-8b-instant` on 429 rate limit errors.

- [ ] **Step 1: Write the tests**

Create `tests/test_arbitrage_analyzer.py`:

```python
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timezone

from groq import RateLimitError

from config import Market, Article, Signal, ARBITRAGE_CONFIDENCE_THRESHOLD
from arbitrage_analyzer import analyze_headlines, _call_groq


def _make_market(slug, question, yes_price=0.5, no_price=0.5):
    return Market(
        condition_id=f"0x{slug}",
        question=question,
        slug=slug,
        outcomes=["Yes", "No"],
        outcome_prices=[yes_price, no_price],
        token_ids=[f"0x{slug}_yes", f"0x{slug}_no"],
        end_date=datetime(2026, 4, 30, tzinfo=timezone.utc),
        active=True,
    )


def _make_article(title):
    return Article(
        title=title,
        source="Reuters",
        url="https://example.com",
        published_at=datetime(2026, 4, 10, tzinfo=timezone.utc),
    )


def _mock_groq_response(text):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = text
    return mock_response


@patch("arbitrage_analyzer.groq.Groq")
def test_analyze_headlines_match(mock_groq_cls):
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client

    mock_client.chat.completions.create.return_value = _mock_groq_response(
        '{"slug": "fed-rate-hike", "side": "YES", "confidence": 0.95, "reason": "headline confirms rate hike"}'
    )

    market = _make_market("fed-rate-hike", "Will the Fed raise rates in April 2026?")
    article = _make_article("Federal Reserve raises rates by 0.25% in April meeting")

    signals = analyze_headlines([article], [market])
    assert len(signals) == 1
    assert signals[0].side == "YES"
    assert signals[0].confidence == 0.95
    assert signals[0].strategy == "arbitrage"
    assert signals[0].market.slug == "fed-rate-hike"


@patch("arbitrage_analyzer.groq.Groq")
def test_analyze_headlines_no_match(mock_groq_cls):
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client

    mock_client.chat.completions.create.return_value = _mock_groq_response("")

    market = _make_market("fed-rate-hike", "Will the Fed raise rates?")
    article = _make_article("Weather forecast: sunny tomorrow")

    signals = analyze_headlines([article], [market])
    assert signals == []


@patch("arbitrage_analyzer.groq.Groq")
def test_analyze_headlines_filters_low_confidence(mock_groq_cls):
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client

    mock_client.chat.completions.create.return_value = _mock_groq_response(
        '{"slug": "fed-rate-hike", "side": "YES", "confidence": 0.60, "reason": "maybe"}'
    )

    market = _make_market("fed-rate-hike", "Will the Fed raise rates?")
    article = _make_article("Fed considering rate options")

    signals = analyze_headlines([article], [market])
    assert signals == []


@patch("arbitrage_analyzer.groq.Groq")
def test_analyze_headlines_multiple_matches(mock_groq_cls):
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client

    mock_client.chat.completions.create.return_value = _mock_groq_response(
        '{"slug": "market-a", "side": "YES", "confidence": 0.90, "reason": "confirmed A"}\n'
        '{"slug": "market-b", "side": "NO", "confidence": 0.88, "reason": "confirmed B"}'
    )

    markets = [
        _make_market("market-a", "Will A happen?"),
        _make_market("market-b", "Will B happen?"),
    ]
    articles = [_make_article("A confirmed"), _make_article("B denied")]

    signals = analyze_headlines(articles, markets)
    assert len(signals) == 2


def test_analyze_headlines_empty_inputs():
    signals = analyze_headlines([], [])
    assert signals == []


@patch("arbitrage_analyzer.groq.Groq")
def test_analyze_headlines_ignores_unknown_slug(mock_groq_cls):
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client

    mock_client.chat.completions.create.return_value = _mock_groq_response(
        '{"slug": "nonexistent-market", "side": "YES", "confidence": 0.95, "reason": "test"}'
    )

    market = _make_market("real-market", "Real question?")
    article = _make_article("Some headline")

    signals = analyze_headlines([article], [market])
    assert signals == []


@patch("arbitrage_analyzer.groq.Groq")
def test_call_groq_falls_back_on_rate_limit(mock_groq_cls):
    """When 70B returns 429, should retry with 8B."""
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client

    # First call (70B) raises RateLimitError, second call (8B) succeeds
    rate_limit_response = MagicMock()
    rate_limit_response.status_code = 429
    rate_limit_response.headers = {}
    rate_limit_error = RateLimitError(
        message="Rate limit exceeded",
        response=rate_limit_response,
        body=None,
    )

    success_response = _mock_groq_response(
        '{"slug": "test", "side": "YES", "confidence": 0.90, "reason": "fallback worked"}'
    )

    mock_client.chat.completions.create.side_effect = [
        rate_limit_error,
        success_response,
    ]

    result = _call_groq(mock_client, "test prompt")
    assert result == '{"slug": "test", "side": "YES", "confidence": 0.90, "reason": "fallback worked"}'

    # Verify two calls were made: first with 70B, then with 8B
    calls = mock_client.chat.completions.create.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["model"] == "llama-3.3-70b-versatile"
    assert calls[1].kwargs["model"] == "llama-3.1-8b-instant"


@patch("arbitrage_analyzer.groq.Groq")
def test_call_groq_returns_empty_on_total_failure(mock_groq_cls):
    """When both models fail, should return empty string."""
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client

    rate_limit_response = MagicMock()
    rate_limit_response.status_code = 429
    rate_limit_response.headers = {}
    rate_limit_error = RateLimitError(
        message="Rate limit exceeded",
        response=rate_limit_response,
        body=None,
    )

    mock_client.chat.completions.create.side_effect = rate_limit_error

    result = _call_groq(mock_client, "test prompt")
    assert result == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest tests/test_arbitrage_analyzer.py -v
```

Expected: `ModuleNotFoundError: No module named 'arbitrage_analyzer'`

- [ ] **Step 3: Implement arbitrage_analyzer.py**

Create `arbitrage_analyzer.py`:

```python
import json

import groq

from config import (
    Market,
    Article,
    Signal,
    ARBITRAGE_CONFIDENCE_THRESHOLD,
    GROQ_PRIMARY_MODEL,
    GROQ_FALLBACK_MODEL,
)


def _call_groq(client: groq.Groq, prompt: str) -> str:
    """Call Groq with 70B primary, fall back to 8B on rate limit."""
    for model in [GROQ_PRIMARY_MODEL, GROQ_FALLBACK_MODEL]:
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content or ""
        except groq.RateLimitError:
            continue
        except Exception:
            return ""
    return ""


def analyze_headlines(
    articles: list[Article], markets: list[Market]
) -> list[Signal]:
    if not articles or not markets:
        return []

    headlines = "\n".join(
        f"- {a.title} ({a.source})" for a in articles[:10]
    )
    market_list = "\n".join(
        f"- [{m.slug}] {m.question} (YES: {m.outcome_prices[0]:.2f}, NO: {m.outcome_prices[1]:.2f})"
        for m in markets[:20]
        if len(m.outcome_prices) >= 2
    )

    prompt = (
        "You are a news-to-prediction-market matcher. Your ONLY job is reading "
        "comprehension — determining if a headline definitively resolves a "
        "prediction market question.\n\n"
        f"HEADLINES:\n{headlines}\n\n"
        f"OPEN MARKETS:\n{market_list}\n\n"
        "For each headline that CLEARLY and DEFINITIVELY resolves a market "
        "question, output a JSON line:\n"
        '{"slug": "market-slug", "side": "YES or NO", "confidence": 0.0-1.0, '
        '"reason": "brief explanation"}\n\n'
        "Rules:\n"
        "- Only match if the headline DIRECTLY answers the market question\n"
        "- confidence must be >= 0.85 to include\n"
        "- Do NOT predict or speculate — only match confirmed facts\n"
        "- If no headlines resolve any markets, output nothing\n"
        "- Output ONLY JSON lines, no other text"
    )

    client = groq.Groq()
    text = _call_groq(client, prompt)

    signals = []
    market_by_slug = {m.slug: m for m in markets}

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
            slug = data.get("slug", "")
            market = market_by_slug.get(slug)
            if not market:
                continue
            confidence = float(data.get("confidence", 0))
            if confidence < ARBITRAGE_CONFIDENCE_THRESHOLD:
                continue
            signals.append(
                Signal(
                    market=market,
                    strategy="arbitrage",
                    side=data.get("side", "YES"),
                    confidence=confidence,
                    reason=data.get("reason", ""),
                )
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            continue

    return signals
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest tests/test_arbitrage_analyzer.py -v
```

Expected: All 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add arbitrage_analyzer.py tests/test_arbitrage_analyzer.py
git commit -m "feat: add resolution arbitrage analyzer with Groq LLM and model fallback"
```

---

## Task 9: engine.py — Main Trading Engine

**Files:**
- Create: `engine.py`
- Create: `tests/test_engine.py`

- [ ] **Step 1: Write the tests**

Create `tests/test_engine.py`:

```python
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from config import Market, Signal, Trade, TRADE_SIZE, STARTING_BALANCE
from engine import Engine


def _make_market(slug="test-market"):
    return Market(
        condition_id=f"0x{slug}",
        question=f"Will {slug} happen?",
        slug=slug,
        outcomes=["Yes", "No"],
        outcome_prices=[0.65, 0.35],
        token_ids=[f"0x{slug}_yes", f"0x{slug}_no"],
        end_date=datetime(2026, 4, 10, 21, 0, tzinfo=timezone.utc),
        active=True,
    )


def _make_signal(market, strategy="level", side="YES", confidence=0.95):
    return Signal(
        market=market,
        strategy=strategy,
        side=side,
        confidence=confidence,
        reason="test reason",
    )


def test_engine_initial_state():
    engine = Engine()
    assert engine.balance == STARTING_BALANCE
    assert engine.trades == []
    assert engine.markets == []
    assert engine.traded_markets == set()
    assert engine.running is False


@patch("engine.log_trade")
def test_execute_paper_trade(mock_log):
    engine = Engine()
    market = _make_market()
    signal = _make_signal(market)

    trade = engine.execute_paper_trade(signal)

    assert trade.market_slug == "test-market"
    assert trade.side == "YES"
    assert trade.entry_price == 0.65  # YES price
    assert trade.size == TRADE_SIZE
    assert trade.strategy == "level"
    assert engine.balance == STARTING_BALANCE - TRADE_SIZE
    assert "test-market" in engine.traded_markets
    mock_log.assert_called_once()


@patch("engine.log_trade")
def test_execute_paper_trade_no_side(mock_log):
    engine = Engine()
    market = _make_market()
    signal = _make_signal(market, side="NO")

    trade = engine.execute_paper_trade(signal)
    assert trade.entry_price == 0.35  # NO price


@patch("engine.log_trade")
def test_duplicate_trade_prevention(mock_log):
    engine = Engine()
    market = _make_market("same-market")
    signal = _make_signal(market)

    engine.execute_paper_trade(signal)
    assert "same-market" in engine.traded_markets
    # Engine.tick() checks traded_markets before calling execute_paper_trade


@patch("engine.fetch_active_markets")
@patch("engine.find_level_markets")
@patch("engine.get_price")
@patch("engine.analyze_level_opportunity")
@patch("engine.log_trade")
def test_tick_executes_level_trade(mock_log, mock_analyze, mock_price, mock_find, mock_fetch):
    market = _make_market("btc-84k")
    signal = _make_signal(market)

    mock_fetch.return_value = [market]
    mock_find.return_value = [MagicMock(coin="BTC")]
    mock_price.return_value = 86000.0
    mock_analyze.return_value = signal

    engine = Engine()
    trades = engine.tick()

    assert len(trades) == 1
    assert trades[0].strategy == "level"
    assert trades[0].side == "YES"


@patch("engine.fetch_active_markets")
@patch("engine.find_level_markets")
@patch("engine.get_price")
@patch("engine.analyze_level_opportunity")
def test_tick_no_signal_no_trade(mock_analyze, mock_price, mock_find, mock_fetch):
    mock_fetch.return_value = [_make_market()]
    mock_find.return_value = [MagicMock(coin="BTC")]
    mock_price.return_value = 84500.0  # too close
    mock_analyze.return_value = None

    engine = Engine()
    trades = engine.tick()
    assert trades == []


@patch("engine.fetch_active_markets")
def test_tick_handles_fetch_error(mock_fetch):
    mock_fetch.side_effect = Exception("network error")
    engine = Engine()
    trades = engine.tick()
    assert trades == []


@patch("engine.log_trade")
def test_balance_decreases_per_trade(mock_log):
    engine = Engine()
    for i in range(3):
        market = _make_market(f"market-{i}")
        signal = _make_signal(market)
        engine.execute_paper_trade(signal)
    assert engine.balance == STARTING_BALANCE - (3 * TRADE_SIZE)


def test_stop():
    engine = Engine()
    engine.running = True
    engine.stop()
    assert engine.running is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest tests/test_engine.py -v
```

Expected: `ModuleNotFoundError: No module named 'engine'`

- [ ] **Step 3: Implement engine.py**

Create `engine.py`:

```python
import time
from datetime import datetime, timezone

from config import (
    Signal,
    Trade,
    TRADE_SIZE,
    STARTING_BALANCE,
    NEWS_POLL_INTERVAL,
)
from market_fetcher import fetch_active_markets
from news_fetcher import fetch_google_news
from price_feed import get_price
from level_analyzer import find_level_markets, analyze_level_opportunity
from arbitrage_analyzer import analyze_headlines
from logger import log_trade


class Engine:
    def __init__(self):
        self.balance = STARTING_BALANCE
        self.trades: list[Trade] = []
        self.markets = []
        self.traded_markets: set[str] = set()
        self.last_news_poll: float = 0
        self.running = False
        self.status = "Initializing"

    def execute_paper_trade(self, signal: Signal) -> Trade:
        price_idx = 0 if signal.side == "YES" else 1
        entry_price = (
            signal.market.outcome_prices[price_idx]
            if len(signal.market.outcome_prices) > price_idx
            else 0.5
        )

        trade = Trade(
            timestamp=datetime.now(timezone.utc),
            market_slug=signal.market.slug,
            question=signal.market.question,
            strategy=signal.strategy,
            side=signal.side,
            entry_price=entry_price,
            size=TRADE_SIZE,
            confidence=signal.confidence,
            reason=signal.reason,
        )
        self.trades.append(trade)
        self.traded_markets.add(signal.market.slug)
        self.balance -= TRADE_SIZE
        log_trade(trade)
        return trade

    def _try_execute(self, signal: Signal) -> Trade | None:
        if signal.market.slug in self.traded_markets:
            return None
        if self.balance < TRADE_SIZE:
            return None
        return self.execute_paper_trade(signal)

    def check_level_markets(self) -> list[Signal]:
        level_markets = find_level_markets(self.markets)
        signals = []
        for lm in level_markets:
            price = get_price(lm.coin)
            if price is None:
                continue
            signal = analyze_level_opportunity(lm, price)
            if signal:
                signals.append(signal)
        return signals

    def check_arbitrage(self) -> list[Signal]:
        articles = fetch_google_news()
        if not articles:
            return []
        return analyze_headlines(articles, self.markets)

    def tick(self) -> list[Trade]:
        now = time.time()
        new_trades = []

        try:
            self.markets = fetch_active_markets()
        except Exception:
            return new_trades

        # Check level markets every tick
        self.status = "Checking level markets"
        for signal in self.check_level_markets():
            trade = self._try_execute(signal)
            if trade:
                new_trades.append(trade)

        # Check news on interval
        if now - self.last_news_poll >= NEWS_POLL_INTERVAL:
            self.status = "Checking news arbitrage"
            self.last_news_poll = now
            for signal in self.check_arbitrage():
                trade = self._try_execute(signal)
                if trade:
                    new_trades.append(trade)

        self.status = "Idle"
        return new_trades

    def run(self, interval: float = 30.0):
        self.running = True
        while self.running:
            self.tick()
            time.sleep(interval)

    def stop(self):
        self.running = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest tests/test_engine.py -v
```

Expected: All 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add engine.py tests/test_engine.py
git commit -m "feat: add trading engine with tick loop and duplicate prevention"
```

---

## Task 10: dashboard.py + main.py — Rich UI and Entry Point

**Files:**
- Create: `dashboard.py`
- Create: `main.py`

No TDD for this task — these are UI/integration modules best verified by running the app.

- [ ] **Step 1: Create dashboard.py**

Create `dashboard.py`:

```python
import time

from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def make_dashboard(engine) -> Layout:
    layout = Layout()

    # --- Header ---
    trade_count = len(engine.trades)
    header_text = (
        f"Polymarket Paper Trading Bot  |  "
        f"Balance: ${engine.balance:,.2f}  |  "
        f"Trades: {trade_count}  |  "
        f"Markets: {len(engine.markets)}  |  "
        f"Status: {engine.status}"
    )
    header = Panel(Text(header_text, style="bold white"), style="blue")

    # --- Level Markets Table ---
    level_table = Table(title="Crypto Level Markets", expand=True)
    level_table.add_column("Question", max_width=55, no_wrap=True)
    level_table.add_column("YES", justify="right", width=8)
    level_table.add_column("NO", justify="right", width=8)
    level_table.add_column("Expiry", width=18)

    for m in engine.markets:
        q = m.question.lower()
        if "above" not in q and "below" not in q:
            continue
        yes_p = f"${m.outcome_prices[0]:.2f}" if m.outcome_prices else "-"
        no_p = f"${m.outcome_prices[1]:.2f}" if len(m.outcome_prices) > 1 else "-"
        expiry = m.end_date.strftime("%m/%d %H:%M UTC") if m.end_date else "-"
        level_table.add_row(m.question[:55], yes_p, no_p, expiry)
        if level_table.row_count >= 12:
            break

    # --- Recent Trades Table ---
    trades_table = Table(title="Recent Trades", expand=True)
    trades_table.add_column("Time", width=10)
    trades_table.add_column("Strategy", width=10)
    trades_table.add_column("Market", max_width=35, no_wrap=True)
    trades_table.add_column("Side", width=6)
    trades_table.add_column("Price", justify="right", width=8)
    trades_table.add_column("Conf", justify="right", width=6)
    trades_table.add_column("Reason", max_width=40, no_wrap=True)

    for t in engine.trades[-15:]:
        side_style = "green" if t.side == "YES" else "red"
        trades_table.add_row(
            t.timestamp.strftime("%H:%M:%S"),
            t.strategy,
            t.market_slug[:35],
            Text(t.side, style=side_style),
            f"${t.entry_price:.2f}",
            f"{t.confidence:.0%}",
            t.reason[:40],
        )

    layout.split_column(
        Layout(header, size=3),
        Layout(level_table, ratio=1),
        Layout(trades_table, ratio=1),
    )
    return layout


def run_dashboard(engine):
    with Live(make_dashboard(engine), refresh_per_second=1, screen=True) as live:
        while engine.running:
            live.update(make_dashboard(engine))
            time.sleep(1)
```

- [ ] **Step 2: Create main.py**

Create `main.py`:

```python
import signal
import sys
import threading

from engine import Engine
from dashboard import run_dashboard
from logger import init_csv


def main():
    init_csv()
    engine = Engine()

    def shutdown(sig, frame):
        engine.stop()
        print("\nShutting down...")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)

    # Start engine loop in background thread
    engine.running = True
    engine_thread = threading.Thread(target=engine.run, daemon=True)
    engine_thread.start()

    # Run dashboard on main thread
    run_dashboard(engine)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run full test suite**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest -v
```

Expected: All tests across all modules pass (approximately 55 tests).

- [ ] **Step 4: Smoke test the app**

Run:
```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
# Quick import check — should exit cleanly with no errors
python -c "from dashboard import make_dashboard; from main import main; print('imports OK')"
```

Expected: `imports OK`

- [ ] **Step 5: Commit**

```bash
git add dashboard.py main.py
git commit -m "feat: add Rich dashboard and main entry point"
```

---

## Verification

After all tasks are complete, run this full verification:

### 1. Full test suite

```bash
cd /Users/jc/dev/projects/polymarket-bot-2
source .venv/bin/activate
python -m pytest -v --tb=short
```

Expected: All ~55 tests pass.

### 2. Import check

```bash
python -c "
import config
import logger
import price_feed
import market_fetcher
import news_fetcher
import level_analyzer
import arbitrage_analyzer
import engine
import dashboard
import main
print('All modules import successfully')
"
```

### 3. Live run (requires Groq API key)

```bash
# Set up .env file first:
# cp .env.example .env
# Edit .env with your GROQ_API_KEY

python main.py
```

Expected: Rich dashboard appears showing:
- Header with balance ($1,000.00), trade count, market count
- Crypto level markets table (populated from Polymarket)
- Recent trades table (empty initially, fills as signals trigger)

Press Ctrl+C to stop.

### 4. Check trades.csv

After the bot runs for a while and executes trades:

```bash
cat trades.csv
```

Expected: CSV with header row and any executed paper trades.

---

## API Reference (Quick Lookup)

| API | Base URL | Auth | Rate Limit | Cost |
|-----|----------|------|------------|------|
| Groq (70B) | `https://api.groq.com/openai/v1` | API key | 1K RPD / 100K TPD | Free |
| Groq (8B fallback) | `https://api.groq.com/openai/v1` | API key | 14.4K RPD / 500K TPD | Free |
| Polymarket Gamma | `https://gamma-api.polymarket.com` | None | 15k/10s | Free |
| Polymarket CLOB | `https://clob.polymarket.com` | None (read) | — | Free |
| OKX v5 | `https://www.okx.com/api/v5` | None (public) | 20/2s | Free |
| Bybit v5 | `https://api.bybit.com/v5` | None (public) | — | Free |
| Google News RSS | `https://news.google.com/rss/search` | None | Unlimited | Free |
