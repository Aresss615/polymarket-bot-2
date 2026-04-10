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
