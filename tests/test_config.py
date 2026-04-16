from datetime import datetime, timezone

from config import (
    ARBITRAGE_STRATEGY_MODE,
    Market,
    UpDownMarket,
    Article,
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
    MIN_SECONDS_TO_CLOSE,
    MAX_SECONDS_TO_CLOSE,
    MAX_REFERENCE_AGE_SECONDS,
    BET_FRACTION,
    MIN_BET,
    MAX_BET,
    STARTING_BALANCE,
    NEWS_POLL_INTERVAL,
    STRATEGY_MODE_DISABLED,
    STRATEGY_MODE_LIVE,
    STRATEGY_MODE_SHADOW,
    STRATEGY_VERSION,
)


def test_market_dataclass():
    m = Market(
        condition_id="0xabc",
        question="BTC-USDT Up or Down?",
        slug="btc-updown-5m-123",
        outcomes=["Up", "Down"],
        outcome_prices=[0.55, 0.45],
        token_ids=["0xup", "0xdown"],
        end_date=datetime(2026, 4, 10, 21, 0, tzinfo=timezone.utc),
        active=True,
    )
    assert m.condition_id == "0xabc"
    assert m.outcome_prices[0] == 0.55
    assert m.active is True


def test_updown_market_dataclass():
    m = Market(
        condition_id="0x1",
        question="BTC Up or Down?",
        slug="btc-updown-5m-1",
        outcomes=["Up", "Down"],
        outcome_prices=[0.5, 0.5],
        token_ids=["0xa", "0xb"],
        end_date=datetime(2026, 4, 10, 21, 0, tzinfo=timezone.utc),
        active=True,
    )
    udm = UpDownMarket(market=m, coin="BTC", interval_minutes=5, seconds_to_close=45, up_outcome_index=0)
    assert udm.coin == "BTC"
    assert udm.interval_minutes == 5
    assert udm.up_outcome_index == 0


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
    s = Signal(market=m, strategy="updown", side="YES", confidence=0.95, reason="test")
    assert s.strategy == "updown"
    assert s.confidence == 0.95
    assert s.strategy_mode == "live"


def test_trade_dataclass():
    t = Trade(
        timestamp=datetime.now(timezone.utc),
        market_slug="test",
        question="Test?",
        strategy="updown",
        side="YES",
        entry_price=0.55,
        size=10.0,
        confidence=0.95,
        reason="test reason",
    )
    assert t.size == 10.0
    assert t.entry_price == 0.55
    assert t.status == "pending"
    assert t.payout == 0.0
    assert t.strategy_version == 0
    assert t.strategy_mode == "live"


def test_trade_settlement_fields():
    t = Trade(
        timestamp=datetime.now(timezone.utc),
        market_slug="test",
        question="Test?",
        strategy="updown",
        side="YES",
        entry_price=0.60,
        size=10.0,
        confidence=0.9,
        reason="test",
        status="won",
        payout=16.67,
    )
    assert t.status == "won"
    assert t.payout == 16.67


def test_constants():
    assert GAMMA_API_URL == "https://gamma-api.polymarket.com"
    assert CLOB_API_URL == "https://clob.polymarket.com"
    assert OKX_API_URL == "https://www.okx.com/api/v5"
    assert BYBIT_API_URL == "https://api.bybit.com/v5"
    assert GOOGLE_NEWS_RSS_URL == "https://news.google.com/rss/search"
    assert GROQ_PRIMARY_MODEL == "llama-3.3-70b-versatile"
    assert GROQ_FALLBACK_MODEL == "llama-3.1-8b-instant"
    assert ARBITRAGE_CONFIDENCE_THRESHOLD == 0.85
    assert MIN_SECONDS_TO_CLOSE == 15
    assert MAX_SECONDS_TO_CLOSE == 480
    assert MAX_REFERENCE_AGE_SECONDS == 2.0
    assert NEWS_POLL_INTERVAL == 300
    assert BET_FRACTION == 0.02
    assert MIN_BET == 1.0
    assert MAX_BET == 5.0
    assert STARTING_BALANCE > 0
    assert {STRATEGY_MODE_DISABLED, STRATEGY_MODE_SHADOW, STRATEGY_MODE_LIVE} == {
        "disabled",
        "shadow",
        "live",
    }
    assert ARBITRAGE_STRATEGY_MODE == STRATEGY_MODE_DISABLED
    assert "BTC" in SUPPORTED_COINS
    assert SUPPORTED_COINS["BTC"] == "BTC-USDT"
    assert isinstance(STRATEGY_VERSION, int)
    assert STRATEGY_VERSION >= 1
