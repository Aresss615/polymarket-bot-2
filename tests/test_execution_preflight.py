from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from config import Market, Signal
from order_executor import LiveExecutor


def _signal(
    *,
    outcomes=None,
    outcome_prices=None,
    token_ids=None,
    side="YES",
):
    outcomes = outcomes or ["Up", "Down"]
    outcome_prices = outcome_prices or [0.80, 0.20]
    token_ids = token_ids or ["0xYES", "0xNO"]
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


def _make_executor(mock_client_cls, market_data_client):
    instance = mock_client_cls.return_value
    instance.create_or_derive_api_creds.return_value = MagicMock()
    instance.get_balance_allowance.return_value = {}
    return LiveExecutor(private_key=f"0x{'11' * 32}", market_data_client=market_data_client), instance


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_rejects_stale_quote(MockClient):
    md = MagicMock()
    md.get_execution_quote.return_value = MagicMock(
        best_ask=0.81,
        depth_usd=500.0,
        tick_size=0.01,
        fetched_at=datetime.now(timezone.utc) - timedelta(seconds=30),
    )
    md.get_book_snapshot.return_value = MagicMock(min_order_size=0.1)
    executor, instance = _make_executor(MockClient, md)

    result = executor.place_order(_signal(), size=2.0, entry_price=0.80)

    assert result.filled is False
    assert "stale quote" in result.reason
    instance.create_order.assert_not_called()


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_rejects_thin_depth(MockClient):
    md = MagicMock()
    md.get_execution_quote.return_value = MagicMock(
        best_ask=0.81,
        depth_usd=5.0,
        tick_size=0.01,
        fetched_at=datetime.now(timezone.utc),
    )
    md.get_book_snapshot.return_value = MagicMock(min_order_size=0.1)
    executor, instance = _make_executor(MockClient, md)

    result = executor.place_order(_signal(), size=10.0, entry_price=0.80)

    assert result.filled is False
    assert "insufficient depth" in result.reason
    instance.create_order.assert_not_called()


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_rejects_signal_price_when_book_has_moved(MockClient):
    md = MagicMock()
    md.get_execution_quote.return_value = MagicMock(
        best_ask=0.99,
        depth_usd=500.0,
        tick_size=0.01,
        fetched_at=datetime.now(timezone.utc),
    )
    md.get_book_snapshot.return_value = MagicMock(min_order_size=0.1)
    executor, instance = _make_executor(MockClient, md)
    instance.get_order_book.return_value = {
        "bids": [{"price": "0.99", "size": "25"}],
        "asks": [{"price": "1.00", "size": "25"}],
        "tick_size": "0.01",
    }

    result = executor.place_order(_signal(), size=2.0, entry_price=0.51)

    assert result.filled is False
    assert "market moved above signal price" in result.reason
    instance.create_order.assert_not_called()


@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_uses_inverted_outcome_token_for_preflight(MockClient):
    md = MagicMock()
    md.get_execution_quote.return_value = MagicMock(
        best_ask=0.45,
        depth_usd=500.0,
        tick_size=0.01,
        fetched_at=datetime.now(timezone.utc),
    )
    md.get_book_snapshot.return_value = MagicMock(min_order_size=0.1)
    executor, instance = _make_executor(MockClient, md)
    instance.get_order_book.side_effect = [
        {
            "bids": [{"price": "0.44", "size": "25"}],
            "asks": [{"price": "0.45", "size": "25"}],
            "tick_size": "0.01",
        }
    ]
    instance.create_order.return_value = {"signed": True}
    instance.post_order.return_value = {"success": True, "orderID": "order-123", "status": "LIVE"}

    signal = _signal(
        outcomes=["Down", "Up"],
        outcome_prices=[0.56, 0.44],
        token_ids=["0xDOWN", "0xUP"],
        side="YES",
    )
    result = executor.place_order(signal, size=2.0, entry_price=0.44)

    assert result.filled is False
    assert result.order_id == "order-123"
    create_args = instance.create_order.call_args[0][0]
    assert create_args.token_id == "0xUP"

