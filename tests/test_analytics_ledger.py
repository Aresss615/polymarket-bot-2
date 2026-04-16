from datetime import datetime, timezone

from analytics import compare_csv_and_ledger, load_trades_from_ledger, session_summary_payload
from config import OrderResult, Trade
from ledger import log_trade_opened, log_trade_settled
from logger import save_trades


def _make_trade(**overrides):
    defaults = dict(
        timestamp=datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc),
        market_slug="btc-updown-5m-123",
        question="BTC Up or Down?",
        strategy="updown",
        side="YES",
        entry_price=0.75,
        size=2.0,
        confidence=0.9,
        reason="test",
        status="won",
        payout=2.67,
        market_type="5m",
        strategy_version=10,
        fees=0.01,
        fill_price=0.75,
        trade_id="trade-1",
        session_id="session-1",
        bucket="yes_momentum",
        expected_value=0.05,
    )
    defaults.update(overrides)
    return Trade(**defaults)


def test_csv_and_ledger_parity(tmp_path):
    csv_path = tmp_path / "trades.csv"
    ledger_path = tmp_path / "ledger.jsonl"
    trade = _make_trade()

    save_trades([trade], path=csv_path)
    log_trade_opened(
        trade,
        OrderResult(
            filled=True,
            fill_price=trade.fill_price or trade.entry_price,
            fill_size=trade.size,
            fees=trade.fees,
            slippage=0.0,
            latency_ms=10.0,
            order_id="order-1",
            status="filled",
        ),
        executor_type="PaperExecutor",
        path=ledger_path,
    )
    log_trade_settled(trade, path=ledger_path)

    parity = compare_csv_and_ledger(csv_path=csv_path, ledger_path=ledger_path)
    assert parity["counts_match"] is True
    assert parity["pnl_match"] is True


def test_session_summary_groups_by_bucket(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    trade = _make_trade()
    log_trade_opened(trade, path=ledger_path)
    log_trade_settled(trade, path=ledger_path)

    trades = load_trades_from_ledger(ledger_path)
    summary = session_summary_payload(trades)

    assert summary["overall"]["settled_trades"] == 1
    assert "yes_momentum" in summary["by_bucket"]
    assert summary["by_bucket"]["yes_momentum"]["trades"] == 1

