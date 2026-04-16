from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from market_fetcher import (
    fetch_active_markets,
    find_updown_markets,
    get_market_price,
    fetch_resolved_market,
)
from config import Market


SAMPLE_GAMMA_RESPONSE = [
    {
        "conditionId": "0xabc123",
        "question": "BTC-USDT Up or Down?",
        "slug": "btc-updown-5m-12345",
        "outcomes": '["Up","Down"]',
        "outcomePrices": '["0.55","0.45"]',
        "clobTokenIds": '["0xup","0xdown"]',
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
    assert markets[0].slug == "btc-updown-5m-12345"
    assert markets[0].outcome_prices == [0.55, 0.45]
    assert markets[0].token_ids == ["0xup", "0xdown"]
    assert markets[0].end_date is not None
    assert markets[1].slug == "fed-rates"


@patch("market_fetcher.requests.get")
def test_fetch_active_markets_with_list_fields(mock_get):
    data = [
        {
            "conditionId": "0x111",
            "question": "Test?",
            "slug": "test",
            "outcomes": ["Up", "Down"],
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
def test_fetch_active_markets_filters_esports(mock_get):
    data = [
        {
            "conditionId": "0xaaa",
            "question": "Dota 2: Team A vs Team B",
            "slug": "dota2-team-a-team-b-2026-04-13",
            "outcomes": '["Yes","No"]',
            "outcomePrices": '["0.5","0.5"]',
            "clobTokenIds": '["0xy","0xn"]',
            "endDate": "2026-04-30T21:00:00Z",
            "active": True,
        },
        {
            "conditionId": "0xbbb",
            "question": "Will CPI come in below forecast?",
            "slug": "us-cpi-below-forecast",
            "outcomes": '["Yes","No"]',
            "outcomePrices": '["0.44","0.56"]',
            "clobTokenIds": '["0xy2","0xn2"]',
            "endDate": "2026-04-30T21:00:00Z",
            "active": True,
        },
    ]

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = data
    mock_get.return_value = resp

    markets = fetch_active_markets()
    assert len(markets) == 1
    assert markets[0].slug == "us-cpi-below-forecast"


def test_find_updown_markets_matches_slug():
    now = datetime.now(timezone.utc)
    m1 = Market(
        condition_id="0x1",
        question="BTC Up or Down?",
        slug="btc-updown-5m-123",
        outcomes=["Up", "Down"],
        outcome_prices=[0.55, 0.45],
        token_ids=["0xa", "0xb"],
        end_date=now + timedelta(seconds=20),
        active=True,
    )
    m2 = Market(
        condition_id="0x2",
        question="Fed rates?",
        slug="fed-rates",
        outcomes=["Yes", "No"],
        outcome_prices=[0.4, 0.6],
        token_ids=["0xc", "0xd"],
        end_date=now + timedelta(seconds=40),
        active=True,
    )
    results = find_updown_markets([m1, m2])
    assert len(results) == 1
    assert results[0].coin == "BTC"
    assert results[0].interval_minutes == 5


def test_find_updown_markets_respects_time_window():
    now = datetime.now(timezone.utc)
    # 15m shadow mode now includes the mid-life discovery window (180-480s).
    m = Market(
        condition_id="0x3",
        question="ETH Up or Down?",
        slug="eth-updown-15m-456",
        outcomes=["Up", "Down"],
        outcome_prices=[0.5, 0.5],
        token_ids=["0xa", "0xb"],
        end_date=now + timedelta(seconds=200),
        active=True,
    )
    results = find_updown_markets([m])
    assert len(results) == 1
    assert results[0].interval_minutes == 15


def test_find_updown_markets_skips_15m_gap_between_windows():
    now = datetime.now(timezone.utc)
    m = Market(
        condition_id="0xgap",
        question="ETH Up or Down?",
        slug="eth-updown-15m-999",
        outcomes=["Up", "Down"],
        outcome_prices=[0.5, 0.5],
        token_ids=["0xa", "0xb"],
        end_date=now + timedelta(seconds=120),
        active=True,
    )
    results = find_updown_markets([m])
    assert results == []


def test_find_updown_markets_15m_in_window():
    """15m markets within the close window should be discovered."""
    now = datetime.now(timezone.utc)
    m = Market(
        condition_id="0x5",
        question="ETH Up or Down?",
        slug="eth-updown-15m-456",
        outcomes=["Up", "Down"],
        outcome_prices=[0.7, 0.3],
        token_ids=["0xa", "0xb"],
        end_date=now + timedelta(seconds=45),
        active=True,
    )
    results = find_updown_markets([m])
    assert len(results) == 1
    assert results[0].interval_minutes == 15
    assert results[0].coin == "ETH"


def test_find_updown_detects_interval():
    now = datetime.now(timezone.utc)
    m = Market(
        condition_id="0x4",
        question="SOL Up or Down?",
        slug="sol-updown-15m-789",
        outcomes=["Up", "Down"],
        outcome_prices=[0.5, 0.5],
        token_ids=["0xa", "0xb"],
        end_date=now + timedelta(seconds=30),
        active=True,
    )
    results = find_updown_markets([m])
    assert len(results) == 1
    assert results[0].interval_minutes == 15
    assert results[0].coin == "SOL"


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


@patch("market_fetcher.requests.get")
def test_fetch_resolved_market_detects_near_boundary_resolution(mock_get):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = [
        {
            "outcomes": '["Up","Down"]',
            "outcomePrices": '["0.9999","0.0001"]',
        }
    ]
    mock_get.return_value = resp

    resolved = fetch_resolved_market("btc-updown-5m-123")
    assert resolved is not None
    assert resolved["outcomes"] == ["Up", "Down"]
    # Prices should be snapped to clean 1.0/0.0
    assert resolved["outcome_prices"] == [1.0, 0.0]


@patch("market_fetcher.requests.get")
def test_fetch_resolved_market_detects_relaxed_threshold(mock_get):
    """Gamma may briefly show 0.97/0.03 during indexing — should still detect."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = [
        {
            "outcomes": '["Up","Down"]',
            "outcomePrices": '["0.97","0.03"]',
        }
    ]
    mock_get.return_value = resp

    resolved = fetch_resolved_market("btc-updown-5m-123")
    assert resolved is not None
    assert resolved["outcome_prices"] == [1.0, 0.0]


@patch("market_fetcher.requests.get")
def test_fetch_resolved_market_returns_none_when_not_resolved(mock_get):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = [
        {
            "outcomes": '["Up","Down"]',
            "outcomePrices": '["0.73","0.27"]',
        }
    ]
    mock_get.return_value = resp

    assert fetch_resolved_market("btc-updown-5m-123") is None


@patch("market_fetcher.requests.get")
def test_fetch_resolved_market_falls_back_to_closed(mock_get):
    first = MagicMock()
    first.raise_for_status = MagicMock()
    first.json.return_value = []  # slug-only lookup returns nothing

    second = MagicMock()
    second.raise_for_status = MagicMock()
    second.json.return_value = [
        {
            "outcomes": '["Up","Down"]',
            "outcomePrices": '["0.0000","1.0000"]',
        }
    ]

    mock_get.side_effect = [first, second]
    resolved = fetch_resolved_market("btc-updown-5m-123")

    assert resolved is not None
    assert resolved["outcome_prices"] == [0.0, 1.0]
    assert mock_get.call_count == 2  # slug, then slug+closed
