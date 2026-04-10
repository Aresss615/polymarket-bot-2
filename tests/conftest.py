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
