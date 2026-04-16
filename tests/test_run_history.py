import json
from datetime import datetime, timezone

from run_history import HistoryFileSpec, archive_and_reset_run


def test_archive_and_reset_moves_files_and_recreates_canonical(tmp_path):
    trades_csv = tmp_path / "trades.csv"
    trades_jsonl = tmp_path / "trades.jsonl"
    events_jsonl = tmp_path / "events.jsonl"
    open_orders_csv = tmp_path / "open_orders.csv"
    archive_dir = tmp_path / "history_archive"
    manifest_path = archive_dir / "manifest.jsonl"

    trades_csv.write_text("timestamp,market_slug\n2026-04-15T00:00:00+00:00,test\n", encoding="utf-8")
    trades_jsonl.write_text('{"type":"trade"}\n', encoding="utf-8")
    events_jsonl.write_text('{"type":"signal_event"}\n', encoding="utf-8")
    open_orders_csv.write_text("order_id\norder-1\n", encoding="utf-8")

    manifest = archive_and_reset_run(
        note="pre-v13-reset",
        now=datetime(2026, 4, 15, 8, 0, tzinfo=timezone.utc),
        files=(
            HistoryFileSpec(trades_csv, "csv"),
            HistoryFileSpec(trades_jsonl, "jsonl"),
            HistoryFileSpec(events_jsonl, "jsonl"),
            HistoryFileSpec(open_orders_csv, "csv"),
        ),
        archive_dir=archive_dir,
        manifest_path=manifest_path,
    )

    archived_names = {entry["archived"] for entry in manifest["archived_files"]}
    assert "trades-v13-reset-20260415-080000.csv" in archived_names
    assert "trades-v13-reset-20260415-080000.jsonl" in archived_names
    assert "events-v13-reset-20260415-080000.jsonl" in archived_names
    assert "open_orders-v13-reset-20260415-080000.csv" in archived_names

    assert trades_csv.read_text(encoding="utf-8-sig").startswith("timestamp,market_slug")
    assert open_orders_csv.read_text(encoding="utf-8-sig").startswith("order_id,created_at")
    assert trades_jsonl.read_text(encoding="utf-8") == ""
    assert events_jsonl.read_text(encoding="utf-8") == ""

    manifest_rows = manifest_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(manifest_rows) == 1
    payload = json.loads(manifest_rows[0])
    assert payload["note"] == "pre-v13-reset"
    assert len(payload["archived_files"]) == 4


def test_archive_and_reset_is_safe_when_files_are_missing(tmp_path):
    trades_csv = tmp_path / "trades.csv"
    archive_dir = tmp_path / "history_archive"
    manifest_path = archive_dir / "manifest.jsonl"

    manifest = archive_and_reset_run(
        note="empty-reset",
        now=datetime(2026, 4, 15, 9, 0, tzinfo=timezone.utc),
        files=(HistoryFileSpec(trades_csv, "csv"),),
        archive_dir=archive_dir,
        manifest_path=manifest_path,
    )

    assert manifest["archived_files"] == []
    assert trades_csv.exists()
    assert trades_csv.read_text(encoding="utf-8-sig").startswith("timestamp,market_slug")
