import csv
from datetime import datetime
from pathlib import Path

from config import Trade, TRADES_CSV

CSV_FIELDS = [
    "timestamp",
    "market_slug",
    "question",
    "strategy",
    "side",
    "entry_price",
    "size",
    "confidence",
    "reason",
    "status",
    "payout",
    "end_date",
    "market_type",
]


def init_csv(path: Path = TRADES_CSV) -> None:
    if not path.exists():
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_FIELDS)


def log_trade(trade: Trade, path: Path = TRADES_CSV) -> None:
    init_csv(path)
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                trade.timestamp.isoformat(),
                trade.market_slug,
                trade.question,
                trade.strategy,
                trade.side,
                f"{trade.entry_price:.4f}",
                f"{trade.size:.2f}",
                f"{trade.confidence:.2f}",
                trade.reason,
                trade.status,
                f"{trade.payout:.2f}",
                trade.end_date.isoformat() if trade.end_date else "",
                trade.market_type,
            ]
        )


def save_trades(trades: list[Trade], path: Path = TRADES_CSV) -> None:
    """Rewrite the entire CSV with current trade state."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_FIELDS)
        for trade in trades:
            writer.writerow(
                [
                    trade.timestamp.isoformat(),
                    trade.market_slug,
                    trade.question,
                    trade.strategy,
                    trade.side,
                    f"{trade.entry_price:.4f}",
                    f"{trade.size:.2f}",
                    f"{trade.confidence:.2f}",
                    trade.reason,
                    trade.status,
                    f"{trade.payout:.2f}",
                    trade.end_date.isoformat() if trade.end_date else "",
                    trade.market_type,
                ]
            )


def read_trades(path: Path = TRADES_CSV) -> list[Trade]:
    if not path.exists():
        return []
    trades = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(
                Trade(
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    market_slug=row["market_slug"],
                    question=row["question"],
                    strategy=row["strategy"],
                    side=row["side"],
                    entry_price=float(row["entry_price"]),
                    size=float(row["size"]),
                    confidence=float(row["confidence"]),
                    reason=row["reason"],
                    status=row.get("status", "pending"),
                    payout=float(row.get("payout", 0)),
                    end_date=(
                        datetime.fromisoformat(row["end_date"])
                        if row.get("end_date")
                        else None
                    ),
                    market_type=row.get("market_type", "5m"),
                )
            )
    return trades
