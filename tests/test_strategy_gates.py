from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from config import Market, Signal
from engine import Engine
from order_executor import OrderExecutor


class _StubExecutor(OrderExecutor):
    def __init__(self):
        self.calls = []

    def place_order(self, signal, size, entry_price):
        self.calls.append(
            {
                "market_slug": signal.market.slug,
                "side": signal.side,
                "size": size,
                "entry_price": entry_price,
            }
        )
        raise AssertionError("executor should be mocked in this test")


def _market(outcome_prices):
    return Market(
        condition_id="0xgate",
        question="BTC Up or Down?",
        slug="btc-updown-5m-123",
        outcomes=["Up", "Down"],
        outcome_prices=outcome_prices,
        token_ids=["0xYES", "0xNO"],
        end_date=datetime.now(timezone.utc) + timedelta(minutes=1),
        active=True,
    )


@patch("engine.read_trades", return_value=[])
@patch("engine.log_trade_jsonl")
@patch("engine.log_settlement")
@patch("engine.log_risk_block")
def test_engine_blocks_news_arbitrage_when_disabled(mock_block, mock_settlement, mock_jsonl, mock_read):
    engine = Engine()
    signal = Signal(
        market=_market([0.8, 0.2]),
        strategy="arbitrage",
        side="YES",
        confidence=1.0,
        reason="news",
        bucket="news_experimental",
    )

    trade, stage, reason = engine._try_execute(signal)
    assert trade is None
    assert stage == "analysis_skip"
    assert "disabled" in reason


@patch("engine.read_trades", return_value=[])
@patch("engine.log_trade_jsonl")
@patch("engine.log_settlement")
@patch("engine.log_risk_block")
def test_engine_allows_low_entry_no_side_when_strategy_marks_signal_live(
    mock_block,
    mock_settlement,
    mock_jsonl,
    mock_read,
):
    executor = _StubExecutor()
    engine = Engine(executor=executor)
    signal = Signal(
        market=_market([0.45, 0.55]),
        strategy="updown",
        side="NO",
        confidence=0.9,
        reason="test",
        bucket="no_mean_reversion",
    )

    sentinel_trade = SimpleNamespace(entry_price=0.55)
    with (
        patch.object(engine, "_position_size_for_signal", return_value=0.5),
        patch.object(
            engine.risk_manager,
            "check_trade_allowed",
            return_value=MagicMock(allowed=True, reason=""),
        ),
        patch.object(engine, "execute_paper_trade", return_value=sentinel_trade) as mock_execute,
    ):
        trade, stage, reason = engine._try_execute(signal)

    assert trade is sentinel_trade
    assert stage == "traded"
    assert "filled @" in reason
    mock_execute.assert_called_once_with(signal)

