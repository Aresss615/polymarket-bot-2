import csv
from datetime import datetime
from pathlib import Path

from config import OpenOrder, Trade, OPEN_ORDERS_CSV, TRADES_CSV

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
    "strategy_version",
    "fees",
    "fill_price",
    "order_id",
    "executor_type",
]

OPEN_ORDER_FIELDS = [
    "order_id",
    "created_at",
    "updated_at",
    "market_slug",
    "question",
    "condition_id",
    "token_id",
    "strategy",
    "side",
    "confidence",
    "reason",
    "end_date",
    "market_type",
    "strategy_version",
    "executor_type",
    "limit_price",
    "requested_size",
    "requested_shares",
    "reserved_size",
    "confirmed_fill_size",
    "confirmed_fill_shares",
    "confirmed_fees",
    "status",
    "raw_status",
]


def init_csv(path: Path = TRADES_CSV) -> None:
    if not path.exists():
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_FIELDS)


def init_open_orders_csv(path: Path = OPEN_ORDERS_CSV) -> None:
    if not path.exists():
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(OPEN_ORDER_FIELDS)


def _iso_or_blank(value: datetime | None) -> str:
    return value.isoformat() if value else ""


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
                trade.strategy_version,
                f"{trade.fees:.4f}",
                f"{trade.fill_price:.4f}" if trade.fill_price is not None else "",
                trade.order_id,
                trade.executor_type,
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
                    trade.strategy_version,
                    f"{trade.fees:.4f}",
                    f"{trade.fill_price:.4f}" if trade.fill_price is not None else "",
                    trade.order_id,
                    trade.executor_type,
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
                    strategy_version=int(row.get("strategy_version", 0)),
                    fees=float(row.get("fees", 0)),
                    fill_price=(
                        float(row["fill_price"])
                        if row.get("fill_price")
                        else None
                    ),
                    order_id=row.get("order_id", ""),
                    executor_type=row.get("executor_type", ""),
                )
            )
    return trades


def save_open_orders(open_orders: list[OpenOrder], path: Path = OPEN_ORDERS_CSV) -> None:
    """Rewrite persisted live order state."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(OPEN_ORDER_FIELDS)
        for order in open_orders:
            writer.writerow(
                [
                    order.order_id,
                    order.created_at.isoformat(),
                    order.updated_at.isoformat(),
                    order.market_slug,
                    order.question,
                    order.condition_id,
                    order.token_id,
                    order.strategy,
                    order.side,
                    f"{order.confidence:.6f}",
                    order.reason,
                    _iso_or_blank(order.end_date),
                    order.market_type,
                    order.strategy_version,
                    order.executor_type,
                    f"{order.limit_price:.6f}",
                    f"{order.requested_size:.6f}",
                    f"{order.requested_shares:.6f}",
                    f"{order.reserved_size:.6f}",
                    f"{order.confirmed_fill_size:.6f}",
                    f"{order.confirmed_fill_shares:.6f}",
                    f"{order.confirmed_fees:.6f}",
                    order.status,
                    order.raw_status,
                ]
            )


def read_open_orders(path: Path = OPEN_ORDERS_CSV) -> list[OpenOrder]:
    if not path.exists():
        return []

    open_orders = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("order_id"):
                continue
            open_orders.append(
                OpenOrder(
                    order_id=row["order_id"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    market_slug=row["market_slug"],
                    question=row["question"],
                    condition_id=row["condition_id"],
                    token_id=row["token_id"],
                    strategy=row["strategy"],
                    side=row["side"],
                    confidence=float(row["confidence"]),
                    reason=row["reason"],
                    end_date=(
                        datetime.fromisoformat(row["end_date"])
                        if row.get("end_date")
                        else None
                    ),
                    market_type=row["market_type"],
                    strategy_version=int(row.get("strategy_version", 0)),
                    executor_type=row.get("executor_type", ""),
                    limit_price=float(row["limit_price"]),
                    requested_size=float(row["requested_size"]),
                    requested_shares=float(row["requested_shares"]),
                    reserved_size=float(row["reserved_size"]),
                    confirmed_fill_size=float(row.get("confirmed_fill_size", 0.0)),
                    confirmed_fill_shares=float(row.get("confirmed_fill_shares", 0.0)),
                    confirmed_fees=float(row.get("confirmed_fees", 0.0)),
                    status=row.get("status", "submitted"),
                    raw_status=row.get("raw_status", ""),
                )
            )
    return open_orders
