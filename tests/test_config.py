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
