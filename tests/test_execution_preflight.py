from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from config import Market, Signal
from order_executor import LiveExecutor


def _signal():
    market = Market(
        condition_id="0x1",
        question="BTC Up or Down?",
        slug="btc-updown-5m-123",
        outcomes=["Up", "Down"],
        outcome_prices=[0.80, 0.20],
        token_ids=["0xYES", "0xNO"],
        end_date=None,
        active=True,
    )
    return Signal(
        market=market,
        strategy="updown",
        side="YES",
        confidence=0.8,
        reason="test",
    )


def _make_executor(mock_client_cls, market_data_client):
    instance = mock_client_cls.return_value
    instance.create_or_derive_api_creds.return_value = MagicMock()
    instance.get_balance_allowance.return_value = {}
    return LiveExecutor(private_key="0xdeadbeef", market_data_client=market_data_client), instance


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

