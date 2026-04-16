"""Tests for LiveExecutor maker-first execution and reconciliation."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from config import Market, OpenOrder, Signal
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
    instance = mock_client_cls.return_value
    instance.create_or_derive_api_creds.return_value = MagicMock()
    instance.get_order_book.return_value = {
        "bids": [{"price": "0.79", "size": "25"}],
        "asks": [{"price": "0.82", "size": "25"}],
        "tick_size": "0.01",
    }
    return LiveExecutor(private_key="0xdeadbeef"), instance


def _make_open_order(**overrides):
    now = datetime.now(timezone.utc)
    defaults = dict(
        order_id="order-123",
        created_at=now,
        updated_at=now,
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
        limit_price=0.80,
        requested_size=4.00,
        requested_shares=5.0,
        reserved_size=4.00,
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
    _, instance = _make_executor(MockClient)
    MockClient.assert_called_once()
    instance.set_api_creds.assert_called_once()


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_successful_order_returns_submitted(MockClient):
    executor, instance = _make_executor(MockClient)
    instance.create_order.return_value = {"signed": True}
    instance.post_order.return_value = {"success": True, "orderID": "order-123", "status": "LIVE"}

    result = executor.place_order(_make_signal(side="YES"), size=1.0, entry_price=0.80)

    assert result.filled is False
    assert result.order_id == "order-123"
    assert result.status == "submitted"
    assert result.needs_reconciliation is True
    assert result.terminal is False
    assert result.reserved_size > 0
    assert result.fill_size == 0.0
    assert result.fill_price == 0.80
    create_args = instance.create_order.call_args[0][0]
    assert create_args.price == 0.80
    post_args = instance.post_order.call_args[0]
    assert post_args[1] == executor._OrderType.GTC
    assert post_args[2] is True


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_retries_post_only_reject_with_lower_price(MockClient):
    executor, instance = _make_executor(MockClient)
    instance.get_order_book.side_effect = [
        {
            "bids": [{"price": "0.79", "size": "25"}],
            "asks": [{"price": "0.82", "size": "25"}],
            "tick_size": "0.01",
        },
        {
            "bids": [{"price": "0.79", "size": "25"}],
            "asks": [{"price": "0.82", "size": "25"}],
            "tick_size": "0.01",
        },
    ]
    instance.create_order.return_value = {"signed": True}
    instance.post_order.side_effect = [
        {"errorMsg": "post only order would match immediately"},
        {"success": True, "orderID": "maker-order-123", "status": "LIVE"},
    ]

    result = executor.place_order(_make_signal(side="YES"), size=1.0, entry_price=0.80)

    assert result.filled is False
    assert result.order_id == "maker-order-123"
    assert result.status == "submitted"
    assert result.needs_reconciliation is True
    assert instance.post_order.call_count == 2
    assert instance.create_order.call_count == 2
    assert instance.create_order.call_args_list[1][0][0].price == 0.79


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_rejected_order(MockClient):
    executor, instance = _make_executor(MockClient)
    instance.create_order.return_value = {"signed": True}
    instance.post_order.return_value = {"errorMsg": "insufficient balance"}

    result = executor.place_order(_make_signal(side="YES"), size=1.0, entry_price=0.80)

    assert result.filled is False
    assert result.needs_reconciliation is False
    assert "insufficient balance" in result.reason


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_exception(MockClient):
    executor, instance = _make_executor(MockClient)
    instance.create_order.side_effect = Exception("connection timeout")

    result = executor.place_order(_make_signal(side="YES"), size=1.0, entry_price=0.80)

    assert result.filled is False
    assert result.needs_reconciliation is False
    assert "connection timeout" in result.reason


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_no_side_token(MockClient):
    executor, instance = _make_executor(MockClient)
    instance.create_order.return_value = {"signed": True}
    instance.post_order.return_value = {"success": True, "orderID": "no-order", "status": "LIVE"}

    result = executor.place_order(_make_signal(side="NO"), size=1.0, entry_price=0.20)

    assert result.order_id == "no-order"
    call_args = instance.create_order.call_args[0][0]
    assert call_args.token_id == "0xNO"


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_missing_token_id(MockClient):
    executor, _ = _make_executor(MockClient)

    result = executor.place_order(_make_signal(side="NO", token_ids=["0xYES"]), size=1.0, entry_price=0.20)

    assert result.filled is False
    assert "no token_id" in result.reason


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_tiny_shares_rejected(MockClient):
    executor, _ = _make_executor(MockClient)

    result = executor.place_order(_make_signal(side="YES"), size=0.05, entry_price=0.80)

    assert result.filled is False
    assert "shares too small" in result.reason


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_quote_stays_below_ask(MockClient):
    executor, instance = _make_executor(MockClient)
    instance.get_order_book.return_value = {
        "bids": [{"price": "0.97", "size": "25"}],
        "asks": [{"price": "0.99", "size": "25"}],
        "tick_size": "0.01",
    }
    instance.create_order.return_value = {"signed": True}
    instance.post_order.return_value = {"success": True, "orderID": "cap-order", "status": "LIVE"}

    result = executor.place_order(_make_signal(side="YES"), size=1.0, entry_price=0.98)

    assert result.fill_price == 0.98
    call_args = instance.create_order.call_args[0][0]
    assert call_args.price == 0.98


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_reconcile_order_auto_cancels_stale_quote(MockClient):
    executor, instance = _make_executor(MockClient)
    instance.get_order.return_value = {
        "status": "LIVE",
        "original_size": "5",
        "size_matched": "0",
    }
    instance.get_trades.return_value = []
    instance.cancel.return_value = {}

    result = executor.reconcile_order(
        _make_open_order(
            created_at=datetime.now(timezone.utc) - timedelta(seconds=5),
            updated_at=datetime.now(timezone.utc) - timedelta(seconds=5),
        )
    )

    assert result.filled is False
    assert result.status == "cancelled"
    assert result.terminal is True
    assert "maker_quote_age" in result.reason
    instance.cancel.assert_called_once_with("order-123")


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_reconcile_order_auto_cancels_on_midpoint_drift(MockClient):
    executor, instance = _make_executor(MockClient)
    instance.get_order.return_value = {
        "status": "LIVE",
        "original_size": "5",
        "size_matched": "0",
    }
    instance.get_trades.return_value = []
    instance.get_order_book.return_value = {
        "bids": [{"price": "0.74", "size": "25"}],
        "asks": [{"price": "0.76", "size": "25"}],
        "tick_size": "0.01",
    }
    instance.cancel.return_value = {}

    result = executor.reconcile_order(_make_open_order(limit_price=0.82))

    assert result.status == "cancelled"
    assert result.terminal is True
    assert "midpoint_drift" in result.reason
    instance.cancel.assert_called_once_with("order-123")


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
            "price": "0.80",
            "fee_rate_bps": "100",
        }
    ]

    result = executor.reconcile_order(_make_open_order())

    assert result.filled is True
    assert result.status == "partial"
    assert abs(result.fill_shares - 2.0) < 1e-9
    assert abs(result.fill_size - 1.60) < 1e-9
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
            "price": "0.80",
            "fee_rate_bps": "100",
        }
    ]

    result = executor.reconcile_order(
        _make_open_order(
            confirmed_fill_size=1.60,
            confirmed_fill_shares=2.0,
            confirmed_fees=0.016,
            reserved_size=2.40,
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
            "price": "0.80",
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
            "price": "0.80",
            "fee_rate_bps": "100",
        }
    ]

    result = executor.reconcile_order(_make_open_order())

    assert result.status == "filled"
    assert result.terminal is True
