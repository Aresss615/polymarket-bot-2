from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config import (
    EVENTS_JSONL,
    HISTORY_ARCHIVE_DIR,
    HISTORY_ARCHIVE_MANIFEST,
    OPEN_ORDERS_CSV,
    TRADES_CSV,
    TRADES_JSONL,
)
from logger import init_csv, init_open_orders_csv


@dataclass(frozen=True)
class HistoryFileSpec:
    source: Path
    kind: str


DEFAULT_HISTORY_FILES = (
    HistoryFileSpec(TRADES_CSV, "csv"),
    HistoryFileSpec(TRADES_JSONL, "jsonl"),
    HistoryFileSpec(EVENTS_JSONL, "jsonl"),
    HistoryFileSpec(OPEN_ORDERS_CSV, "csv"),
)


def _timestamp_slug(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _archive_name(path: Path, timestamp_slug: str) -> str:
    return f"{path.stem}-v13-reset-{timestamp_slug}{path.suffix}"


def _reset_canonical_file(spec: HistoryFileSpec) -> None:
    if spec.kind == "csv" and spec.source.name == TRADES_CSV.name:
        init_csv(spec.source)
        return
    if spec.kind == "csv" and spec.source.name == OPEN_ORDERS_CSV.name:
        init_open_orders_csv(spec.source)
        return
    if spec.kind == "csv":
        init_csv(spec.source)
        return
    spec.source.write_text("", encoding="utf-8")


def archive_and_reset_run(
    *,
    note: str = "pre-v13-reset",
    now: datetime | None = None,
    files: tuple[HistoryFileSpec, ...] = DEFAULT_HISTORY_FILES,
    archive_dir: Path = HISTORY_ARCHIVE_DIR,
    manifest_path: Path = HISTORY_ARCHIVE_MANIFEST,
) -> dict:
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp_slug = _timestamp_slug(now)
    archived_files: list[dict] = []

    for spec in files:
        source = spec.source
        if source.exists():
            size = source.stat().st_size
            destination = archive_dir / _archive_name(source, timestamp_slug)
            shutil.move(str(source), str(destination))
            archived_files.append(
                {
                    "source": source.name,
                    "archived": destination.name,
                    "bytes": size,
                    "kind": spec.kind,
                }
            )
        _reset_canonical_file(spec)

    manifest = {
        "timestamp": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "note": note,
        "archived_files": archived_files,
    }
    with open(manifest_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(manifest, ensure_ascii=True) + "\n")
    return manifest


__all__ = ["HistoryFileSpec", "DEFAULT_HISTORY_FILES", "archive_and_reset_run"]
