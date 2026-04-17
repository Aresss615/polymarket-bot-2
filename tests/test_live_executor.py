"""Tests for LiveExecutor maker-first execution and reconciliation."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from eth_abi import decode as abi_decode

from config import Market, OpenOrder, Signal
from order_executor import LiveExecutor


def _make_signal(side="YES", token_ids=None, outcomes=None, outcome_prices=None):
    token_ids = token_ids or ["0xYES", "0xNO"]
    outcomes = outcomes or ["Up", "Down"]
    outcome_prices = outcome_prices or [0.80, 0.20]
    market = Market(
        condition_id="0x1",
        question="BTC Up or Down?",
        slug="btc-updown-5m-123",
        outcomes=outcomes,
        outcome_prices=outcome_prices,
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
    return LiveExecutor(private_key=f"0x{'11' * 32}"), instance


def _response(payload):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


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

    result = executor.place_order(_make_signal(side="YES"), size=4.0, entry_price=0.80)

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

    result = executor.place_order(_make_signal(side="YES"), size=4.0, entry_price=0.80)

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

    result = executor.place_order(_make_signal(side="YES"), size=4.0, entry_price=0.80)

    assert result.filled is False
    assert result.needs_reconciliation is False
    assert "insufficient balance" in result.reason


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_exception(MockClient):
    executor, instance = _make_executor(MockClient)
    instance.create_order.side_effect = Exception("connection timeout")

    result = executor.place_order(_make_signal(side="YES"), size=4.0, entry_price=0.80)

    assert result.filled is False
    assert result.needs_reconciliation is False
    assert "connection timeout" in result.reason


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_no_side_token(MockClient):
    executor, instance = _make_executor(MockClient)
    instance.get_order_book.return_value = {
        "bids": [{"price": "0.19", "size": "25"}],
        "asks": [{"price": "0.21", "size": "25"}],
        "tick_size": "0.01",
    }
    instance.create_order.return_value = {"signed": True}
    instance.post_order.return_value = {"success": True, "orderID": "no-order", "status": "LIVE"}

    result = executor.place_order(_make_signal(side="NO"), size=1.0, entry_price=0.20)

    assert result.order_id == "no-order"
    call_args = instance.create_order.call_args[0][0]
    assert call_args.token_id == "0xNO"


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_uses_reversed_up_token_without_false_drift_reject(MockClient):
    executor, instance = _make_executor(MockClient)
    instance.get_order_book.return_value = {
        "bids": [{"price": "0.43", "size": "25"}],
        "asks": [{"price": "0.45", "size": "25"}],
        "tick_size": "0.01",
    }
    instance.create_order.return_value = {"signed": True}
    instance.post_order.return_value = {"success": True, "orderID": "rev-order", "status": "LIVE"}

    signal = _make_signal(
        side="YES",
        token_ids=["0xDOWN", "0xUP"],
        outcomes=["Down", "Up"],
        outcome_prices=[0.56, 0.44],
    )
    result = executor.place_order(signal, size=4.0, entry_price=0.44)

    assert result.status == "submitted"
    assert "market moved above signal price" not in result.reason
    call_args = instance.create_order.call_args[0][0]
    assert call_args.token_id == "0xUP"


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

    result = executor.place_order(_make_signal(side="YES"), size=4.0, entry_price=0.98)

    assert result.fill_price == 0.98
    call_args = instance.create_order.call_args[0][0]
    assert call_args.price == 0.98


@patch("order_executor.RUNTIME_DATA_PLANE.market_cache.snapshot")
@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_refreshes_broken_cached_book_before_quoting(MockClient, mock_snapshot):
    mock_snapshot.return_value = {
        "best_bid": 0.01,
        "best_ask": 0.99,
        "spread": 0.98,
        "midpoint": 0.50,
        "tick_size": 0.01,
        "book_age_ms": 50.0,
    }
    executor, instance = _make_executor(MockClient)
    instance.get_order_book.return_value = {
        "bids": [{"price": "0.98", "size": "25"}],
        "asks": [{"price": "0.99", "size": "25"}],
        "tick_size": "0.01",
    }
    instance.create_order.return_value = {"signed": True}
    instance.post_order.return_value = {"success": True, "orderID": "refresh-order", "status": "LIVE"}

    result = executor.place_order(_make_signal(side="YES"), size=4.0, entry_price=0.98)

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


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_redeem_condition_submits_safe_relayer_payload(MockClient):
    funder = "0x2222222222222222222222222222222222222222"
    executor = LiveExecutor(
        private_key=f"0x{'11' * 32}",
        funder=funder,
        wallet_type="safe",
        relayer_api_key="relayer-key",
    )
    executor._session = MagicMock()
    executor._session.request.side_effect = [
        _response({"nonce": "7"}),
        _response(
            {
                "transactionID": "redeem-123",
                "transactionHash": "",
                "state": "STATE_NEW",
            }
        ),
    ]

    condition_id = "0x" + ("ab" * 32)
    result = executor.redeem_condition(condition_id)

    assert result.status == "pending"
    assert result.transaction_id == "redeem-123"

    submit_call = executor._session.request.call_args_list[1]
    assert submit_call.args[0] == "POST"
    assert submit_call.args[1].endswith("/submit")
    assert submit_call.kwargs["headers"]["RELAYER_API_KEY"] == "relayer-key"
    assert submit_call.kwargs["headers"]["RELAYER_API_KEY_ADDRESS"] == executor.signer_address

    payload = submit_call.kwargs["json"]
    assert payload["type"] == "SAFE"
    assert payload["to"] == "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
    assert payload["proxyWallet"].lower() == funder.lower()
    calldata = payload["data"]
    assert calldata.startswith("0x01b7037c")
    collateral, parent_collection, encoded_condition, index_sets = abi_decode(
        ["address", "bytes32", "bytes32", "uint256[]"],
        bytes.fromhex(calldata[10:]),
    )
    assert collateral.lower() == "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"
    assert parent_collection == b"\x00" * 32
    assert encoded_condition.hex() == condition_id[2:]
    assert index_sets == (1, 2)


@pytest.mark.parametrize(
    ("state", "expected_status", "expected_success"),
    [
        ("STATE_NEW", "pending", True),
        ("STATE_CONFIRMED", "confirmed", True),
        ("STATE_FAILED", "failed", False),
    ],
)
@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_get_redemption_status_maps_relayer_states(
    MockClient,
    state,
    expected_status,
    expected_success,
):
    executor = LiveExecutor(
        private_key=f"0x{'11' * 32}",
        funder="0x2222222222222222222222222222222222222222",
        wallet_type="safe",
        relayer_api_key="relayer-key",
    )
    executor._session = MagicMock()
    executor._session.request.return_value = _response(
        [
            {
                "transactionID": "redeem-123",
                "transactionHash": "0xabc",
                "state": state,
                "errorMsg": "boom" if state == "STATE_FAILED" else "",
            }
        ]
    )

    result = executor.get_redemption_status("redeem-123")

    assert result.status == expected_status
    assert result.success is expected_success
    assert result.transaction_id == "redeem-123"
    assert result.transaction_hash == "0xabc"


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_size_expansion_rejected(MockClient):
    """5-share minimum expanding a $2 order to $4.45 (>2x limit) must be rejected."""
    executor, instance = _make_executor(MockClient)
    instance.get_order_book.return_value = {
        "bids": [{"price": "0.88", "size": "25"}],
        "asks": [{"price": "0.91", "size": "25"}],
        "tick_size": "0.01",
    }

    # size=2.0, entry_price=0.90 → limit_price=0.89, estimated_shares≈2.25
    # 5-share floor → shares=5.0, actual_size=4.45
    # 4.45 > 2.0 * 2.0 (LIVE_MAX_SIZE_EXPANSION) → rejected
    result = executor.place_order(_make_signal(side="YES"), size=2.0, entry_price=0.90)

    assert result.filled is False
    assert "size expansion" in result.reason
    assert instance.create_order.call_count == 0
