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
