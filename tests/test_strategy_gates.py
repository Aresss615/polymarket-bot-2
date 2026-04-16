from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from config import Market, Signal
from engine import Engine


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
def test_engine_blocks_low_entry_no_side(mock_block, mock_settlement, mock_jsonl, mock_read):
    engine = Engine()
    signal = Signal(
        market=_market([0.45, 0.55]),
        strategy="updown",
        side="NO",
        confidence=0.9,
        reason="test",
        bucket="no_mean_reversion",
    )

    trade, stage, reason = engine._try_execute(signal)
    assert trade is None
    assert stage == "analysis_skip"
    assert "low entry" in reason

