import json
from datetime import datetime, timezone

from config import CODEX_VERSION, Trade
import trade_logger


def _make_trade(**overrides):
    defaults = dict(
        timestamp=datetime(2026, 4, 14, 12, 0, tzinfo=timezone.utc),
        market_slug="btc-updown-5m-123",
        question="BTC Up or Down?",
        strategy="updown",
        side="YES",
        entry_price=0.58,
        size=2.9,
        confidence=0.91,
        reason="test reason",
        strategy_version=10,
        executor_type="PaperExecutor",
    )
    defaults.update(overrides)
    return Trade(**defaults)


def test_log_trade_jsonl_includes_codex_version(tmp_path, monkeypatch):
    trade_path = tmp_path / "trades.jsonl"
    monkeypatch.setattr(trade_logger, "TRADES_JSONL", trade_path)

    trade_logger.log_trade_jsonl(_make_trade())

    row = json.loads(trade_path.read_text().strip())
    assert row["codex_version"] == CODEX_VERSION
    assert row["strategy_version"] == 10


def test_log_event_includes_codex_version(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(trade_logger, "EVENTS_JSONL", events_path)

    trade_logger.log_event("risk_block", {"reason": "test"})

    row = json.loads(events_path.read_text().strip())
    assert row["codex_version"] == CODEX_VERSION
    assert row["type"] == "risk_block"


def test_log_signal_event_writes_signal_event_type(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(trade_logger, "EVENTS_JSONL", events_path)

    trade_logger.log_signal_event({
        "market_slug": "btc-updown-5m-123",
        "decision_stage": "traded",
        "direction": "BUY",
    })

    row = json.loads(events_path.read_text().strip())
    assert row["type"] == "signal_event"
    assert row["decision_stage"] == "traded"
    assert row["direction"] == "BUY"
