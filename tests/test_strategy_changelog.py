import json
from datetime import datetime, timezone
from strategy_changelog import record_change, read_changelog


def test_record_and_read_change(tmp_path):
    log_path = tmp_path / "changelog.json"
    record_change(
        what="Increased BTC min edge from 0.07 to 0.10",
        old_value="0.07",
        new_value="0.10",
        last_trade_slug="btc-updown-5m-123",
        path=log_path,
    )

    entries = read_changelog(path=log_path)
    assert len(entries) == 1
    assert entries[0]["what"] == "Increased BTC min edge from 0.07 to 0.10"
    assert entries[0]["old_value"] == "0.07"
    assert entries[0]["new_value"] == "0.10"
    assert entries[0]["last_trade_slug"] == "btc-updown-5m-123"
    assert "timestamp" in entries[0]


def test_multiple_changes_append(tmp_path):
    log_path = tmp_path / "changelog.json"
    record_change("change 1", "a", "b", "slug-1", path=log_path)
    record_change("change 2", "c", "d", "slug-2", path=log_path)

    entries = read_changelog(path=log_path)
    assert len(entries) == 2


def test_read_empty_changelog(tmp_path):
    log_path = tmp_path / "nonexistent.json"
    entries = read_changelog(path=log_path)
    assert entries == []
