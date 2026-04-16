from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from config import Market
from copy_trading import CopyTradingBot
from order_executor import PaperExecutor


def _market():
    return Market(
        condition_id="0xcopy",
        question="BTC Up or Down?",
        slug="btc-updown-5m-123",
        outcomes=["Up", "Down"],
        outcome_prices=[0.8, 0.2],
        token_ids=["0xYES", "0xNO"],
        end_date=datetime.now(timezone.utc) + timedelta(minutes=5),
        active=True,
    )


def _activity_row(tx_hash: str, ts: int, size: float = 5.0):
    return {
        "transactionHash": tx_hash,
        "timestamp": ts,
        "slug": "btc-updown-5m-123",
        "outcome": "Up",
        "price": 0.8,
        "size": size,
    }


@patch("copy_trading.log_trade")
@patch("copy_trading.log_trade_jsonl")
@patch("copy_trading.save_trades")
@patch("copy_trading.requests.get")
def test_copy_bot_seeds_baseline_then_copies_new_trade(mock_get, mock_save, mock_log_jsonl, mock_log_trade):
    baseline = [_activity_row("0xold", 1000)]
    with_new_trade = baseline + [_activity_row("0xnew", 1001)]

    first_resp = MagicMock()
    first_resp.raise_for_status = MagicMock()
    first_resp.json.return_value = baseline

    second_resp = MagicMock()
    second_resp.raise_for_status = MagicMock()
    second_resp.json.return_value = with_new_trade

    mock_get.side_effect = [first_resp, second_resp]

    cache = MagicMock()
    cache.resolve.return_value = _market()

    bot = CopyTradingBot(
        target_wallet="0xtarget",
        executor=PaperExecutor(),
        metadata_cache=cache,
    )

    assert bot.poll_once() == []
    copied = bot.poll_once()

    assert len(copied) == 1
    assert copied[0].strategy == "copy_trade"
    assert copied[0].bucket == "wallet_copy"
    assert copied[0].session_id.startswith("copy-")
    mock_log_trade.assert_called_once()
    mock_log_jsonl.assert_called_once()
    mock_save.assert_called_once()

