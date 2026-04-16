import time
from unittest.mock import patch, MagicMock

import pytest

from price_feed import (
    _price_history,
    _source_disabled_until,
    _source_failures,
    ensure_reference_recent,
    get_price,
    get_price_age,
    get_prices_batch,
    get_price_bybit,
    get_price_coingecko,
    get_price_momentum,
    get_price_okx,
)
from state_cache import REFERENCE_CACHE


@pytest.fixture(autouse=True)
def _reset_price_feed_state():
    _price_history.clear()
    for source in _source_failures:
        _source_failures[source] = 0
        _source_disabled_until[source] = 0
    REFERENCE_CACHE._states.clear()
    REFERENCE_CACHE._history.clear()
    REFERENCE_CACHE._chainlink_history.clear()
    yield


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


def _mock_coingecko_response(coin_id: str, price: float):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {coin_id: {"usd": price}}
    return resp


@patch("price_feed._session.get")
def test_get_price_okx_success(mock_get):
    mock_get.return_value = _mock_okx_response("84500.5")
    price = get_price_okx("BTC-USDT")
    assert price == 84500.5
    mock_get.assert_called_once()
    assert "instId" in str(mock_get.call_args)


@patch("price_feed._session.get")
def test_get_price_okx_failure(mock_get):
    mock_get.side_effect = Exception("timeout")
    price = get_price_okx("BTC-USDT")
    assert price is None


@patch("price_feed._session.get")
def test_get_price_bybit_success(mock_get):
    mock_get.return_value = _mock_bybit_response("84500.5")
    price = get_price_bybit("BTC-USDT")
    assert price == 84500.5


@patch("price_feed._session.get")
def test_get_price_bybit_failure(mock_get):
    mock_get.side_effect = Exception("timeout")
    price = get_price_bybit("BTC-USDT")
    assert price is None


@patch("price_feed._session.get")
def test_get_price_coingecko_success(mock_get):
    mock_get.return_value = _mock_coingecko_response("bitcoin", 84500.0)
    price = get_price_coingecko("BTC")
    assert price == 84500.0


@patch("price_feed._session.get")
def test_get_price_coingecko_failure(mock_get):
    mock_get.side_effect = Exception("timeout")
    price = get_price_coingecko("BTC")
    assert price is None


def test_get_price_coingecko_unknown_coin():
    assert get_price_coingecko("FAKECOIN") is None


@patch("price_feed.get_price")
@patch("price_feed._session.get")
def test_get_prices_batch_falls_back_to_direct_fetch_for_missing_coins(mock_get, mock_direct):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"bitcoin": {"usd": 84500.0}}
    mock_get.return_value = resp
    mock_direct.return_value = 2300.0

    result = get_prices_batch({"BTC", "ETH"})

    assert result["BTC"] == 84500.0
    assert result["ETH"] == 2300.0
    mock_direct.assert_called_once_with("ETH")


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


@patch("price_feed.get_price_coingecko")
@patch("price_feed.get_price_bybit")
@patch("price_feed.get_price_okx")
def test_get_price_falls_back_to_coingecko(mock_okx, mock_bybit, mock_cg):
    mock_okx.return_value = None
    mock_bybit.return_value = None
    mock_cg.return_value = 84000.0
    price = get_price("BTC")
    assert price == 84000.0


@patch("price_feed.get_price_okx")
def test_get_price_unsupported_coin(mock_okx):
    price = get_price("FAKECOIN")
    assert price is None
    mock_okx.assert_not_called()


# --- Momentum tests ---


def test_get_price_momentum_no_history():
    """No history -> None."""
    _price_history.clear()
    # Mock get_price to return None so no new data is added
    with patch("price_feed.get_price_okx", return_value=None), \
         patch("price_feed.get_price_bybit", return_value=None), \
         patch("price_feed.get_price_coingecko", return_value=None):
        result = get_price_momentum("NOSUCHCOIN")
    assert result is None


def test_get_price_momentum_with_history():
    """Momentum computed from price history."""
    _price_history.clear()
    now = time.time()
    _price_history["TEST"] = [
        (now - 35, 100.0),
        (now - 25, 101.0),
        (now - 15, 102.0),
    ]
    # Mock get_price to add a current price
    with patch("price_feed.get_price_okx", return_value=None), \
         patch("price_feed.get_price_bybit", return_value=None), \
         patch("price_feed.get_price_coingecko", return_value=None):
        # Manually add current price since mock returns None
        _price_history["TEST"].append((now, 103.0))
        result = get_price_momentum("TEST")
    # Should compare 103.0 vs ~100.0 (30s ago) = +3%
    assert result is not None
    assert result > 0


def test_get_price_age_prefers_reference_cache_timestamp():
    REFERENCE_CACHE._states.clear()
    REFERENCE_CACHE._history.clear()
    REFERENCE_CACHE._chainlink_history.clear()
    _price_history.clear()

    now = time.time()
    REFERENCE_CACHE.update("BTC", 84500.0, source="test", timestamp=now - 1.25)

    age = get_price_age("BTC")

    assert age is not None
    assert age < 2.0


def test_ensure_reference_recent_refreshes_stale_cache():
    REFERENCE_CACHE._states.clear()
    REFERENCE_CACHE._history.clear()
    REFERENCE_CACHE._chainlink_history.clear()

    stale_ts = time.time() - 10.0
    REFERENCE_CACHE.update("BTC", 84000.0, source="stale", timestamp=stale_ts)

    def _refresh(coin: str):
        REFERENCE_CACHE.update(coin, 84500.0, source="test_refresh", timestamp=time.time())
        return 84500.0

    with patch("price_feed.get_price", side_effect=_refresh) as mock_get_price:
        assert ensure_reference_recent("BTC", max_age=2.0) is True

    mock_get_price.assert_called_once_with("BTC")
