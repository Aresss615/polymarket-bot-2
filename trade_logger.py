"""Structured JSONL logging for trades and risk events.

Runs alongside CSV and is replayable by ``order_id``. Consumers should treat the
stream as event-sourced snapshots: later rows for the same order supersede
earlier rows, while settlement and risk events remain append-only.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from config import CODEX_VERSION, EVENTS_JSONL, OrderResult, TRADES_JSONL, Trade


def _write_jsonl(path: Path, record: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=True) + "\n")


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
        "trade_key": trade.order_id or f"legacy:{trade.timestamp.isoformat()}:{trade.market_slug}:{trade.side}",
        "timestamp": trade.timestamp.isoformat(),
        "market_slug": trade.market_slug,
        "question": trade.question,
        "strategy": trade.strategy,
        "strategy_mode": trade.strategy_mode,
        "side": trade.side,
        "entry_price": trade.entry_price,
        "size": trade.size,
        "confidence": trade.confidence,
        "reason": trade.reason,
        "status": trade.status,
        "payout": trade.payout,
        "market_type": trade.market_type,
        "codex_version": CODEX_VERSION,
        "strategy_version": trade.strategy_version,
        "fees": trade.fees,
        "fill_price": trade.fill_price,
        "order_id": trade.order_id,
        "executor_type": trade.executor_type or executor_type,
        "edge_gross": trade.edge_gross,
        "edge_net": trade.edge_net,
        "reference_symbol": trade.reference_symbol,
        "reference_price": trade.reference_price,
        "best_bid": trade.best_bid,
        "best_ask": trade.best_ask,
        "spread": trade.spread,
        "decision_latency_ms": trade.decision_latency_ms,
        "thesis_id": trade.thesis_id,
        "cancel_reason": trade.cancel_reason,
        "model_up_probability": trade.model_up_probability,
        "selected_side_probability": trade.selected_side_probability,
        "interval_open": trade.interval_open,
        "interval_high": trade.interval_high,
        "interval_low": trade.interval_low,
        "interval_close": trade.interval_close,
        "interval_return": trade.interval_return,
        "late_return_60s": trade.late_return_60s,
        "late_return_20s": trade.late_return_20s,
        "body_ratio": trade.body_ratio,
        "wick_imbalance": trade.wick_imbalance,
        "candle_regime": trade.candle_regime,
        "trend_alignment": trade.trend_alignment,
        "market_yes_at_open": trade.market_yes_at_open,
        "market_yes_at_decision": trade.market_yes_at_decision,
        "market_yes_at_close": trade.market_yes_at_close,
        "contrarian_block_reason": trade.contrarian_block_reason,
        "wallet_signal_source": trade.wallet_signal_source,
        "wallet_lead_score": trade.wallet_lead_score,
        "wallet_cluster": trade.wallet_cluster,
        "window_start_ts": trade.window_start_ts,
        "window_open_price": trade.window_open_price,
        "window_open_source": trade.window_open_source,
        "window_open_price_trusted": trade.window_open_price_trusted,
        "actual_window_return": trade.actual_window_return,
        "actual_move_regime": trade.actual_move_regime,
        "actual_move_side": trade.actual_move_side,
        "strategy_route": trade.strategy_route,
        "cluster_id": trade.cluster_id,
        "signal_epoch_id": trade.signal_epoch_id,
        "book_age_ms": trade.book_age_ms,
        "tick_size": trade.tick_size,
        "expected_fill_price": trade.expected_fill_price,
        "expected_cost": trade.expected_cost,
        "markout_1s": trade.markout_1s,
        "markout_5s": trade.markout_5s,
        "markout_30s": trade.markout_30s,
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
            "edge_gross": order_result.edge_gross,
            "edge_net": order_result.edge_net,
            "reference_symbol": order_result.reference_symbol,
            "reference_price": order_result.reference_price,
            "best_bid": order_result.best_bid,
            "best_ask": order_result.best_ask,
            "spread": order_result.spread,
            "decision_latency_ms": order_result.decision_latency_ms,
            "thesis_id": order_result.thesis_id,
            "cancel_reason": order_result.cancel_reason,
            "strategy_mode": order_result.strategy_mode,
            "model_up_probability": order_result.model_up_probability,
            "selected_side_probability": order_result.selected_side_probability,
            "interval_open": order_result.interval_open,
            "interval_high": order_result.interval_high,
            "interval_low": order_result.interval_low,
            "interval_close": order_result.interval_close,
            "interval_return": order_result.interval_return,
            "late_return_60s": order_result.late_return_60s,
            "late_return_20s": order_result.late_return_20s,
            "body_ratio": order_result.body_ratio,
            "wick_imbalance": order_result.wick_imbalance,
            "candle_regime": order_result.candle_regime,
            "trend_alignment": order_result.trend_alignment,
            "market_yes_at_open": order_result.market_yes_at_open,
            "market_yes_at_decision": order_result.market_yes_at_decision,
            "market_yes_at_close": order_result.market_yes_at_close,
            "contrarian_block_reason": order_result.contrarian_block_reason,
            "wallet_signal_source": order_result.wallet_signal_source,
            "wallet_lead_score": order_result.wallet_lead_score,
            "wallet_cluster": order_result.wallet_cluster,
            "window_start_ts": order_result.window_start_ts,
            "window_open_price": order_result.window_open_price,
            "window_open_source": order_result.window_open_source,
            "window_open_price_trusted": order_result.window_open_price_trusted,
            "actual_window_return": order_result.actual_window_return,
            "actual_move_regime": order_result.actual_move_regime,
            "actual_move_side": order_result.actual_move_side,
            "strategy_route": order_result.strategy_route,
            "cluster_id": order_result.cluster_id,
            "signal_epoch_id": order_result.signal_epoch_id,
            "book_age_ms": order_result.book_age_ms,
            "tick_size": order_result.tick_size,
            "expected_fill_price": order_result.expected_fill_price,
            "expected_cost": order_result.expected_cost,
            "markout_1s": order_result.markout_1s,
            "markout_5s": order_result.markout_5s,
            "markout_30s": order_result.markout_30s,
        }
    _write_jsonl(TRADES_JSONL, record)


def log_event(event_type: str, data: dict) -> None:
    """Log a risk or system event."""
    record = {
        "type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "codex_version": CODEX_VERSION,
        **data,
    }
    _write_jsonl(EVENTS_JSONL, record)


def log_settlement(trade: Trade) -> None:
    """Log trade settlement (win/loss resolution)."""
    log_event(
        "settlement",
        {
            "order_id": trade.order_id,
            "market_slug": trade.market_slug,
            "side": trade.side,
            "status": trade.status,
            "entry_price": trade.entry_price,
            "size": trade.size,
            "payout": trade.payout,
            "fees": trade.fees,
            "executor_type": trade.executor_type,
            "edge_gross": trade.edge_gross,
            "edge_net": trade.edge_net,
            "thesis_id": trade.thesis_id,
            "candle_regime": trade.candle_regime,
            "trend_alignment": trade.trend_alignment,
            "market_yes_at_close": trade.market_yes_at_close,
            "pnl": trade.payout - trade.size if trade.status == "won" else -trade.size,
        },
    )


def log_risk_block(signal_slug: str, reason: str) -> None:
    """Log a trade blocked by risk manager."""
    log_event(
        "risk_block",
        {
            "market_slug": signal_slug,
            "reason": reason,
        },
    )


def log_order_event(event_name: str, order_id: str, data: dict) -> None:
    """Log order lifecycle events separately from confirmed trade snapshots."""
    log_event(
        "order_event",
        {
            "event": event_name,
            "order_id": order_id,
            **data,
        },
    )


def log_signal_event(data: dict) -> None:
    """Log one analyzed signal decision for research and live monitoring."""
    log_event("signal_event", data)
