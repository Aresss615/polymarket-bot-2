"""Tests for LiveExecutor.

Tests the executor's logic without making real API calls.
ClobClient is mocked to simulate responses.
"""
from unittest.mock import patch, MagicMock

from config import Market, Signal
from order_executor import LiveExecutor, polymarket_taker_fee


def _make_signal(side="YES", token_ids=None):
    token_ids = token_ids or ["0xYES", "0xNO"]
    market = Market(
        condition_id="0x1",
        question="BTC Up or Down?",
        slug="btc-updown-5m-123",
        outcomes=["Up", "Down"],
        outcome_prices=[0.80, 0.20],
        token_ids=token_ids,
        end_date=None,
        active=True,
    )
    return Signal(
        market=market,
        strategy="updown",
        side=side,
        confidence=0.8,
        reason="test",
    )


def _make_executor(mock_client_cls):
    """Helper to create a LiveExecutor with mocked ClobClient."""
    instance = mock_client_cls.return_value
    instance.create_or_derive_api_creds.return_value = MagicMock()
    return LiveExecutor(private_key="0xdeadbeef"), instance


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_init(MockClient):
    """LiveExecutor initializes ClobClient and derives API creds."""
    _, instance = _make_executor(MockClient)
    MockClient.assert_called_once()
    instance.set_api_creds.assert_called_once()


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_successful_order(MockClient):
    """Successful order returns filled OrderResult."""
    executor, instance = _make_executor(MockClient)
    instance.create_order.return_value = {"signed": True}
    instance.post_order.return_value = {"success": True, "orderID": "order-123"}

    signal = _make_signal(side="YES")
    result = executor.place_order(signal, size=1.0, entry_price=0.80)

    assert result.filled is True
    assert result.order_id == "order-123"
    assert result.status == "filled"
    assert result.fill_price == 0.82  # entry + 0.02
    assert result.fees > 0


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_rejected_order(MockClient):
    """Rejected order returns filled=False with error message."""
    executor, instance = _make_executor(MockClient)
    instance.create_order.return_value = {"signed": True}
    instance.post_order.return_value = {"errorMsg": "insufficient balance"}

    signal = _make_signal(side="YES")
    result = executor.place_order(signal, size=1.0, entry_price=0.80)

    assert result.filled is False
    assert "insufficient balance" in result.reason


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_fok_retries_with_gtc(MockClient):
    """FOK full-fill rejection should retry with GTC and succeed."""
    executor, instance = _make_executor(MockClient)
    instance.create_order.return_value = {"signed": True}
    instance.post_order.side_effect = [
        {"errorMsg": "order couldn't be fully filled. FOK orders are fully filled or killed."},
        {"success": True, "orderID": "gtc-order-123"},
    ]

    signal = _make_signal(side="YES")
    result = executor.place_order(signal, size=1.0, entry_price=0.80)

    assert result.filled is True
    assert result.order_id == "gtc-order-123"
    assert instance.post_order.call_count == 2


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_exception(MockClient):
    """Network errors are caught and returned as rejected."""
    executor, instance = _make_executor(MockClient)
    instance.create_order.side_effect = Exception("connection timeout")

    signal = _make_signal(side="YES")
    result = executor.place_order(signal, size=1.0, entry_price=0.80)

    assert result.filled is False
    assert "connection timeout" in result.reason


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_no_side_token(MockClient):
    """NO side buys token at index 1."""
    executor, instance = _make_executor(MockClient)
    instance.create_order.return_value = {"signed": True}
    instance.post_order.return_value = {"success": True, "orderID": "no-order"}

    signal = _make_signal(side="NO")
    result = executor.place_order(signal, size=1.0, entry_price=0.20)

    assert result.filled is True
    # Verify create_order was called with the NO token
    call_args = instance.create_order.call_args[0][0]
    assert call_args.token_id == "0xNO"


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_missing_token_id(MockClient):
    """Missing token_id returns rejected."""
    executor, _ = _make_executor(MockClient)

    signal = _make_signal(side="NO", token_ids=["0xYES"])  # only 1 token
    result = executor.place_order(signal, size=1.0, entry_price=0.20)

    assert result.filled is False
    assert "no token_id" in result.reason


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_tiny_shares_rejected(MockClient):
    """Very small orders (< 0.1 shares) are rejected."""
    executor, _ = _make_executor(MockClient)

    signal = _make_signal(side="YES")
    # size=0.05 at price 0.82 = ~0.06 shares < 0.1
    result = executor.place_order(signal, size=0.05, entry_price=0.80)

    assert result.filled is False
    assert "shares too small" in result.reason


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_price_capped_at_99(MockClient):
    """Limit price is capped at 0.99 even when entry + 0.02 > 0.99."""
    executor, instance = _make_executor(MockClient)
    instance.create_order.return_value = {"signed": True}
    instance.post_order.return_value = {"success": True, "orderID": "cap-order"}

    signal = _make_signal(side="YES")
    result = executor.place_order(signal, size=1.0, entry_price=0.98)

    assert result.filled is True
    assert result.fill_price == 0.99  # capped
    call_args = instance.create_order.call_args[0][0]
    assert call_args.price == 0.99
