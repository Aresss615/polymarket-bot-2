"""Structured JSONL logging for trades and risk events.

Runs alongside CSV — does not replace it. Each line is a self-contained
JSON object suitable for post-hoc analysis via analyze_simulation.py.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from config import Trade, OrderResult

TRADES_JSONL = Path("trades.jsonl")
EVENTS_JSONL = Path("events.jsonl")


def log_trade_jsonl(
    trade: Trade,
    order_result: OrderResult | None = None,
    executor_type: str = "paper",
    snapshot_event: str = "fill",
) -> None:
    """Append one JSON line with a confirmed trade snapshot."""
    record = {
        "type": "trade",
        "snapshot_event": snapshot_event,
        "timestamp": trade.timestamp.isoformat(),
        "market_slug": trade.market_slug,
        "strategy": trade.strategy,
        "side": trade.side,
        "entry_price": trade.entry_price,
        "size": trade.size,
        "confidence": trade.confidence,
        "reason": trade.reason,
        "status": trade.status,
        "payout": trade.payout,
        "market_type": trade.market_type,
        "strategy_version": trade.strategy_version,
        "fees": trade.fees,
        "fill_price": trade.fill_price,
        "order_id": trade.order_id,
        "executor_type": trade.executor_type or executor_type,
    }
    if order_result:
        record["order"] = {
            "fill_price": order_result.fill_price,
            "fill_size": order_result.fill_size,
            "fill_shares": order_result.fill_shares,
            "fees": order_result.fees,
            "slippage": order_result.slippage,
            "latency_ms": order_result.latency_ms,
            "order_id": order_result.order_id,
            "status": order_result.status,
            "reason": order_result.reason,
            "remaining_size": order_result.remaining_size,
            "remaining_shares": order_result.remaining_shares,
            "reserved_size": order_result.reserved_size,
            "requested_size": order_result.requested_size,
            "requested_shares": order_result.requested_shares,
            "needs_reconciliation": order_result.needs_reconciliation,
            "terminal": order_result.terminal,
            "raw_status": order_result.raw_status,
        }
    with open(TRADES_JSONL, "a") as f:
        f.write(json.dumps(record) + "\n")


def log_event(event_type: str, data: dict) -> None:
    """Log a risk or system event."""
    record = {
        "type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **data,
    }
    with open(EVENTS_JSONL, "a") as f:
        f.write(json.dumps(record) + "\n")


def log_settlement(trade: Trade) -> None:
    """Log trade settlement (win/loss resolution)."""
    log_event("settlement", {
        "order_id": trade.order_id,
        "market_slug": trade.market_slug,
        "side": trade.side,
        "status": trade.status,
        "entry_price": trade.entry_price,
        "size": trade.size,
        "payout": trade.payout,
        "fees": trade.fees,
        "executor_type": trade.executor_type,
        "pnl": trade.payout - trade.size if trade.status == "won" else -trade.size,
    })


def log_risk_block(signal_slug: str, reason: str) -> None:
    """Log a trade blocked by risk manager."""
    log_event("risk_block", {
        "market_slug": signal_slug,
        "reason": reason,
    })


def log_order_event(event_name: str, order_id: str, data: dict) -> None:
    """Log order lifecycle events separately from confirmed trade snapshots."""
    log_event("order_event", {
        "event": event_name,
        "order_id": order_id,
        **data,
    })
