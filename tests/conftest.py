import pytest
from datetime import datetime, timezone

from config import Market, UpDownMarket, Article


@pytest.fixture
def sample_market():
    return Market(
        condition_id="0xabc123",
        question="BTC-USDT Up or Down?",
        slug="btc-updown-5m-12345",
        outcomes=["Up", "Down"],
        outcome_prices=[0.55, 0.45],
        token_ids=["0xtoken_up", "0xtoken_down"],
        end_date=datetime(2026, 4, 10, 21, 0, tzinfo=timezone.utc),
        active=True,
    )


@pytest.fixture
def sample_non_updown_market():
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
def sample_updown_market(sample_market):
    return UpDownMarket(
        market=sample_market,
        coin="BTC",
        interval_minutes=5,
        seconds_to_close=45,
        up_outcome_index=0,
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
def tmp_csv(tmp_path):
    return tmp_path / "test_trades.csv"
