"""Tests for LiveExecutor.

Tests the executor's logic without making real API calls.
ClobClient is mocked to simulate responses.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from config import Market, OpenOrder, Signal
from py_clob_client.exceptions import PolyApiException
from order_executor import LiveExecutor


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


def _make_open_order(**overrides):
    defaults = dict(
        order_id="order-123",
        created_at=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
        market_slug="btc-updown-5m-123",
        question="BTC Up or Down?",
        condition_id="0x1",
        token_id="0xYES",
        strategy="updown",
        side="YES",
        confidence=0.8,
        reason="test",
        end_date=None,
        market_type="5m",
        strategy_version=9,
        executor_type="LiveExecutor",
        limit_price=0.82,
        requested_size=4.10,
        requested_shares=5.0,
        reserved_size=4.10,
        confirmed_fill_size=0.0,
        confirmed_fill_shares=0.0,
        confirmed_fees=0.0,
        status="submitted",
        raw_status="live",
    )
    defaults.update(overrides)
    return OpenOrder(**defaults)


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_init(MockClient):
    """LiveExecutor initializes ClobClient and derives API creds."""
    _, instance = _make_executor(MockClient)
    MockClient.assert_called_once()
    instance.set_api_creds.assert_called_once()


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_successful_order_returns_submitted(MockClient):
    """Successful submit does not count as a fill until reconciliation."""
    executor, instance = _make_executor(MockClient)
    instance.create_order.return_value = {"signed": True}
    instance.post_order.return_value = {"success": True, "orderID": "order-123", "status": "LIVE"}

    signal = _make_signal(side="YES")
    result = executor.place_order(signal, size=1.0, entry_price=0.80)

    assert result.filled is False
    assert result.order_id == "order-123"
    assert result.status == "submitted"
    assert result.needs_reconciliation is True
    assert result.terminal is False
    assert result.reserved_size > 0
    assert result.fill_size == 0.0


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_rejected_order(MockClient):
    """Rejected order returns filled=False with error message."""
    executor, instance = _make_executor(MockClient)
    instance.create_order.return_value = {"signed": True}
    instance.post_order.return_value = {"errorMsg": "insufficient balance"}

    signal = _make_signal(side="YES")
    result = executor.place_order(signal, size=1.0, entry_price=0.80)

    assert result.filled is False
    assert result.needs_reconciliation is False
    assert "insufficient balance" in result.reason


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_fok_retries_with_gtc(MockClient):
    """FOK full-fill rejection should retry with GTC and still return submitted."""
    executor, instance = _make_executor(MockClient)
    instance.create_order.return_value = {"signed": True}
    instance.post_order.side_effect = [
        {"errorMsg": "order couldn't be fully filled. FOK orders are fully filled or killed."},
        {"success": True, "orderID": "gtc-order-123", "status": "MATCHED"},
    ]

    signal = _make_signal(side="YES")
    result = executor.place_order(signal, size=1.0, entry_price=0.80)

    assert result.filled is False
    assert result.order_id == "gtc-order-123"
    assert result.status == "submitted"
    assert result.needs_reconciliation is True
    assert instance.post_order.call_count == 2


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_fok_retries_with_gtc_from_error_key(MockClient):
    """FOK full-fill rejection in the generic error field should also retry."""
    executor, instance = _make_executor(MockClient)
    instance.create_order.return_value = {"signed": True}
    instance.post_order.side_effect = [
        {"error": "order couldn't be fully filled. FOK orders are fully filled or killed."},
        {"success": True, "orderID": "gtc-order-456", "status": "LIVE"},
    ]

    signal = _make_signal(side="YES")
    result = executor.place_order(signal, size=1.0, entry_price=0.80)

    assert result.filled is False
    assert result.order_id == "gtc-order-456"
    assert result.status == "submitted"
    assert instance.post_order.call_count == 2


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_fok_retries_with_gtc_from_poly_api_exception(MockClient):
    """PolyApiException with the FOK full-fill message should also retry."""
    executor, instance = _make_executor(MockClient)
    instance.create_order.return_value = {"signed": True}
    instance.post_order.side_effect = [
        PolyApiException(error_msg="order couldn't be fully filled. FOK orders are fully filled or killed."),
        {"success": True, "orderID": "gtc-order-789", "status": "LIVE"},
    ]

    signal = _make_signal(side="YES")
    result = executor.place_order(signal, size=1.0, entry_price=0.80)

    assert result.filled is False
    assert result.order_id == "gtc-order-789"
    assert result.status == "submitted"
    assert instance.post_order.call_count == 2


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_exception(MockClient):
    """Network errors are caught and returned as rejected."""
    executor, instance = _make_executor(MockClient)
    instance.create_order.side_effect = Exception("connection timeout")

    signal = _make_signal(side="YES")
    result = executor.place_order(signal, size=1.0, entry_price=0.80)

    assert result.filled is False
    assert result.needs_reconciliation is False
    assert "connection timeout" in result.reason


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_no_side_token(MockClient):
    """NO side buys token at index 1."""
    executor, instance = _make_executor(MockClient)
    instance.create_order.return_value = {"signed": True}
    instance.post_order.return_value = {"success": True, "orderID": "no-order", "status": "LIVE"}

    signal = _make_signal(side="NO")
    result = executor.place_order(signal, size=1.0, entry_price=0.20)

    assert result.order_id == "no-order"
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
    result = executor.place_order(signal, size=0.05, entry_price=0.80)

    assert result.filled is False
    assert "shares too small" in result.reason


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_price_capped_at_99(MockClient):
    """Limit price is capped at 0.99 even when entry + 0.02 > 0.99."""
    executor, instance = _make_executor(MockClient)
    instance.create_order.return_value = {"signed": True}
    instance.post_order.return_value = {"success": True, "orderID": "cap-order", "status": "LIVE"}

    signal = _make_signal(side="YES")
    result = executor.place_order(signal, size=1.0, entry_price=0.98)

    assert result.fill_price == 0.99
    call_args = instance.create_order.call_args[0][0]
    assert call_args.price == 0.99


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_reconcile_order_with_confirmed_partial_fill(MockClient):
    executor, instance = _make_executor(MockClient)
    instance.get_order.return_value = {
        "status": "LIVE",
        "original_size": "5",
        "size_matched": "2",
    }
    instance.get_trades.return_value = [
        {
            "status": "CONFIRMED",
            "taker_order_id": "order-123",
            "size": "2",
            "price": "0.82",
            "fee_rate_bps": "100",
        }
    ]

    result = executor.reconcile_order(_make_open_order())

    assert result.filled is True
    assert result.status == "partial"
    assert abs(result.fill_shares - 2.0) < 1e-9
    assert abs(result.fill_size - 1.64) < 1e-9
    assert abs(result.remaining_shares - 3.0) < 1e-9
    assert result.needs_reconciliation is True


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_reconcile_order_ignores_already_booked_fills(MockClient):
    executor, instance = _make_executor(MockClient)
    instance.get_order.return_value = {
        "status": "LIVE",
        "original_size": "5",
        "size_matched": "2",
    }
    instance.get_trades.return_value = [
        {
            "status": "CONFIRMED",
            "taker_order_id": "order-123",
            "size": "2",
            "price": "0.82",
            "fee_rate_bps": "100",
        }
    ]

    result = executor.reconcile_order(
        _make_open_order(
            confirmed_fill_size=1.64,
            confirmed_fill_shares=2.0,
            confirmed_fees=0.0164,
            reserved_size=2.46,
        )
    )

    assert result.filled is False
    assert result.fill_size == 0.0
    assert result.fill_shares == 0.0
    assert result.status == "partial"


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_reconcile_order_with_confirmed_full_fill(MockClient):
    executor, instance = _make_executor(MockClient)
    instance.get_order.return_value = {
        "status": "FILLED",
        "original_size": "5",
        "size_matched": "5",
    }
    instance.get_trades.return_value = [
        {
            "status": "CONFIRMED",
            "taker_order_id": "order-123",
            "size": "5",
            "price": "0.82",
            "fee_rate_bps": "100",
        }
    ]

    result = executor.reconcile_order(_make_open_order())

    assert result.filled is True
    assert result.status == "filled"
    assert result.terminal is True
    assert result.remaining_size == 0.0
    assert result.remaining_shares == 0.0


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_reconcile_order_with_zero_fill_cancel(MockClient):
    executor, instance = _make_executor(MockClient)
    instance.get_order.return_value = {
        "status": "CANCELED",
        "original_size": "5",
        "size_matched": "0",
    }
    instance.get_trades.return_value = []

    result = executor.reconcile_order(_make_open_order())

    assert result.filled is False
    assert result.status == "cancelled"
    assert result.terminal is True
    assert result.remaining_size == 0.0


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_reconcile_order_falls_back_to_get_orders(MockClient):
    executor, instance = _make_executor(MockClient)
    instance.get_order.side_effect = Exception("not found")
    instance.get_orders.return_value = [
        {"status": "FILLED", "original_size": "5", "size_matched": "5"}
    ]
    instance.get_trades.return_value = [
        {
            "status": "CONFIRMED",
            "taker_order_id": "order-123",
            "size": "5",
            "price": "0.82",
            "fee_rate_bps": "100",
        }
    ]

    result = executor.reconcile_order(_make_open_order())

    assert result.status == "filled"
    assert result.terminal is True
