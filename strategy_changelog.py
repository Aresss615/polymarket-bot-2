"""Track strategy parameter changes over time."""

import json
from datetime import datetime, timezone
from pathlib import Path

CHANGELOG_PATH = Path("strategy_changelog.json")


def record_change(
    what: str,
    old_value: str,
    new_value: str,
    last_trade_slug: str,
    path: Path = CHANGELOG_PATH,
) -> None:
    """Append a strategy change entry to the changelog."""
    entries = read_changelog(path)
    entries.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "what": what,
        "old_value": old_value,
        "new_value": new_value,
        "last_trade_slug": last_trade_slug,
    })
    with open(path, "w") as f:
        json.dump(entries, f, indent=2)


def read_changelog(path: Path = CHANGELOG_PATH) -> list[dict]:
    """Read all changelog entries."""
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)
