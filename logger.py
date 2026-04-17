import csv
import io
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
    "edge_gross",
    "edge_net",
    "reference_symbol",
    "reference_price",
    "best_bid",
    "best_ask",
    "spread",
    "decision_latency_ms",
    "thesis_id",
    "cancel_reason",
    "strategy_mode",
    "model_up_probability",
    "selected_side_probability",
    "interval_open",
    "interval_high",
    "interval_low",
    "interval_close",
    "interval_return",
    "late_return_60s",
    "late_return_20s",
    "body_ratio",
    "wick_imbalance",
    "candle_regime",
    "trend_alignment",
    "market_yes_at_open",
    "market_yes_at_decision",
    "market_yes_at_close",
    "contrarian_block_reason",
    "wallet_signal_source",
    "wallet_lead_score",
    "wallet_cluster",
    "window_start_ts",
    "window_open_price",
    "window_open_source",
    "window_open_price_trusted",
    "window_open_anchor_age_seconds",
    "actual_window_return",
    "actual_move_regime",
    "actual_move_side",
    "strategy_route",
    "cluster_id",
    "signal_epoch_id",
    "book_age_ms",
    "tick_size",
    "expected_fill_price",
    "expected_cost",
    "markout_1s",
    "markout_5s",
    "markout_30s",
    "trade_id",
    "session_id",
    "bucket",
    "expected_value",
    "condition_id",
    "redemption_status",
    "redemption_tx_id",
    "redemption_tx_hash",
    "redemption_error",
    "redemption_updated_at",
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
    "edge_gross",
    "edge_net",
    "reference_symbol",
    "reference_price",
    "best_bid",
    "best_ask",
    "spread",
    "decision_latency_ms",
    "thesis_id",
    "cancel_reason",
    "strategy_mode",
    "coin",
    "model_up_probability",
    "selected_side_probability",
    "interval_open",
    "interval_high",
    "interval_low",
    "interval_close",
    "interval_return",
    "late_return_60s",
    "late_return_20s",
    "body_ratio",
    "wick_imbalance",
    "candle_regime",
    "trend_alignment",
    "market_yes_at_open",
    "market_yes_at_decision",
    "market_yes_at_close",
    "contrarian_block_reason",
    "wallet_signal_source",
    "wallet_lead_score",
    "wallet_cluster",
    "window_start_ts",
    "window_open_price",
    "window_open_source",
    "window_open_price_trusted",
    "window_open_anchor_age_seconds",
    "actual_window_return",
    "actual_move_regime",
    "actual_move_side",
    "strategy_route",
    "cluster_id",
    "signal_epoch_id",
    "book_age_ms",
    "tick_size",
    "expected_fill_price",
    "expected_cost",
    "markout_1s",
    "markout_5s",
    "markout_30s",
]


def _open_csv(path: Path, mode: str):
    return open(path, mode, encoding="utf-8-sig", newline="")


def _read_csv_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _csv_dict_reader(path: Path) -> csv.DictReader:
    return csv.DictReader(io.StringIO(_read_csv_text(path), newline=""))


def _iso_or_blank(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _float_or_blank(value: float | None, digits: int = 6) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_header_row(row: dict) -> bool:
    timestamp = (row.get("timestamp") or "").strip().lower()
    order_id = (row.get("order_id") or "").strip().lower()
    return timestamp in {"timestamp", "\ufefftimestamp"} or order_id == "order_id"


def init_csv(path: Path = TRADES_CSV) -> None:
    if not path.exists():
        with _open_csv(path, "w") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_FIELDS)


def init_open_orders_csv(path: Path = OPEN_ORDERS_CSV) -> None:
    if not path.exists():
        with _open_csv(path, "w") as f:
            writer = csv.writer(f)
            writer.writerow(OPEN_ORDER_FIELDS)


def _trade_to_row(trade: Trade) -> list[str]:
    return [
        trade.timestamp.isoformat(),
        trade.market_slug,
        trade.question,
        trade.strategy,
        trade.side,
        f"{trade.entry_price:.4f}",
        f"{trade.size:.2f}",
        f"{trade.confidence:.4f}",
        trade.reason,
        trade.status,
        f"{trade.payout:.2f}",
        _iso_or_blank(trade.end_date),
        trade.market_type,
        str(trade.strategy_version),
        f"{trade.fees:.4f}",
        _float_or_blank(trade.fill_price, digits=4),
        trade.order_id,
        trade.executor_type,
        f"{trade.edge_gross:.6f}",
        f"{trade.edge_net:.6f}",
        trade.reference_symbol,
        _float_or_blank(trade.reference_price),
        _float_or_blank(trade.best_bid),
        _float_or_blank(trade.best_ask),
        _float_or_blank(trade.spread),
        f"{trade.decision_latency_ms:.3f}",
        trade.thesis_id,
        trade.cancel_reason,
        trade.strategy_mode,
        _float_or_blank(trade.model_up_probability),
        _float_or_blank(trade.selected_side_probability),
        _float_or_blank(trade.interval_open),
        _float_or_blank(trade.interval_high),
        _float_or_blank(trade.interval_low),
        _float_or_blank(trade.interval_close),
        _float_or_blank(trade.interval_return),
        _float_or_blank(trade.late_return_60s),
        _float_or_blank(trade.late_return_20s),
        _float_or_blank(trade.body_ratio),
        _float_or_blank(trade.wick_imbalance),
        trade.candle_regime,
        trade.trend_alignment,
        _float_or_blank(trade.market_yes_at_open),
        _float_or_blank(trade.market_yes_at_decision),
        _float_or_blank(trade.market_yes_at_close),
        trade.contrarian_block_reason,
        trade.wallet_signal_source,
        _float_or_blank(trade.wallet_lead_score),
        trade.wallet_cluster,
        _float_or_blank(trade.window_start_ts, digits=3),
        _float_or_blank(trade.window_open_price),
        trade.window_open_source,
        str(trade.window_open_price_trusted),
        _float_or_blank(trade.window_open_anchor_age_seconds),
        _float_or_blank(trade.actual_window_return),
        trade.actual_move_regime,
        trade.actual_move_side,
        trade.strategy_route,
        trade.cluster_id,
        trade.signal_epoch_id,
        _float_or_blank(trade.book_age_ms, digits=3),
        _float_or_blank(trade.tick_size),
        _float_or_blank(trade.expected_fill_price),
        _float_or_blank(trade.expected_cost),
        _float_or_blank(trade.markout_1s),
        _float_or_blank(trade.markout_5s),
        _float_or_blank(trade.markout_30s),
        trade.trade_id,
        trade.session_id,
        trade.bucket,
        _float_or_blank(trade.expected_value),
        trade.condition_id,
        trade.redemption_status,
        trade.redemption_tx_id,
        trade.redemption_tx_hash,
        trade.redemption_error,
        _iso_or_blank(trade.redemption_updated_at),
    ]


def log_trade(trade: Trade, path: Path = TRADES_CSV) -> None:
    init_csv(path)
    with _open_csv(path, "a") as f:
        writer = csv.writer(f)
        writer.writerow(_trade_to_row(trade))


def save_trades(trades: list[Trade], path: Path = TRADES_CSV) -> None:
    """Rewrite the entire CSV with current trade state."""
    with _open_csv(path, "w") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_FIELDS)
        for trade in trades:
            writer.writerow(_trade_to_row(trade))


def read_trades(path: Path = TRADES_CSV) -> list[Trade]:
    if not path.exists():
        return []

    trades = []
    reader = _csv_dict_reader(path)
    for row in reader:
        if not row or _is_header_row(row) or not row.get("market_slug"):
            continue
        timestamp = _safe_datetime(row.get("timestamp"))
        if timestamp is None:
            continue
        trades.append(
            Trade(
                timestamp=timestamp,
                market_slug=row["market_slug"],
                question=row.get("question", ""),
                strategy=row.get("strategy", ""),
                side=row.get("side", ""),
                entry_price=_safe_float(row.get("entry_price")),
                size=_safe_float(row.get("size")),
                confidence=_safe_float(row.get("confidence")),
                reason=row.get("reason", ""),
                condition_id=row.get("condition_id", ""),
                status=row.get("status", "pending"),
                payout=_safe_float(row.get("payout")),
                end_date=_safe_datetime(row.get("end_date")),
                market_type=row.get("market_type", "5m") or "5m",
                strategy_version=int(_safe_float(row.get("strategy_version"), 0.0)),
                fees=_safe_float(row.get("fees")),
                fill_price=(
                    _safe_float(row.get("fill_price"))
                    if row.get("fill_price") not in (None, "")
                    else None
                ),
                order_id=row.get("order_id", ""),
                executor_type=row.get("executor_type", ""),
                edge_gross=_safe_float(row.get("edge_gross")),
                edge_net=_safe_float(row.get("edge_net")),
                reference_symbol=row.get("reference_symbol", ""),
                reference_price=(
                    _safe_float(row.get("reference_price"))
                    if row.get("reference_price") not in (None, "")
                    else None
                ),
                best_bid=(
                    _safe_float(row.get("best_bid"))
                    if row.get("best_bid") not in (None, "")
                    else None
                ),
                best_ask=(
                    _safe_float(row.get("best_ask"))
                    if row.get("best_ask") not in (None, "")
                    else None
                ),
                spread=(
                    _safe_float(row.get("spread"))
                    if row.get("spread") not in (None, "")
                    else None
                ),
                decision_latency_ms=_safe_float(row.get("decision_latency_ms")),
                thesis_id=row.get("thesis_id", ""),
                cancel_reason=row.get("cancel_reason", ""),
                strategy_mode=row.get("strategy_mode", "live") or "live",
                model_up_probability=(
                    _safe_float(row.get("model_up_probability"))
                    if row.get("model_up_probability") not in (None, "")
                    else None
                ),
                selected_side_probability=(
                    _safe_float(row.get("selected_side_probability"))
                    if row.get("selected_side_probability") not in (None, "")
                    else None
                ),
                interval_open=(
                    _safe_float(row.get("interval_open"))
                    if row.get("interval_open") not in (None, "")
                    else None
                ),
                interval_high=(
                    _safe_float(row.get("interval_high"))
                    if row.get("interval_high") not in (None, "")
                    else None
                ),
                interval_low=(
                    _safe_float(row.get("interval_low"))
                    if row.get("interval_low") not in (None, "")
                    else None
                ),
                interval_close=(
                    _safe_float(row.get("interval_close"))
                    if row.get("interval_close") not in (None, "")
                    else None
                ),
                interval_return=(
                    _safe_float(row.get("interval_return"))
                    if row.get("interval_return") not in (None, "")
                    else None
                ),
                late_return_60s=(
                    _safe_float(row.get("late_return_60s"))
                    if row.get("late_return_60s") not in (None, "")
                    else None
                ),
                late_return_20s=(
                    _safe_float(row.get("late_return_20s"))
                    if row.get("late_return_20s") not in (None, "")
                    else None
                ),
                body_ratio=(
                    _safe_float(row.get("body_ratio"))
                    if row.get("body_ratio") not in (None, "")
                    else None
                ),
                wick_imbalance=(
                    _safe_float(row.get("wick_imbalance"))
                    if row.get("wick_imbalance") not in (None, "")
                    else None
                ),
                candle_regime=row.get("candle_regime", ""),
                trend_alignment=row.get("trend_alignment", ""),
                market_yes_at_open=(
                    _safe_float(row.get("market_yes_at_open"))
                    if row.get("market_yes_at_open") not in (None, "")
                    else None
                ),
                market_yes_at_decision=(
                    _safe_float(row.get("market_yes_at_decision"))
                    if row.get("market_yes_at_decision") not in (None, "")
                    else None
                ),
                market_yes_at_close=(
                    _safe_float(row.get("market_yes_at_close"))
                    if row.get("market_yes_at_close") not in (None, "")
                    else None
                ),
                contrarian_block_reason=row.get("contrarian_block_reason", ""),
                wallet_signal_source=row.get("wallet_signal_source", ""),
                wallet_lead_score=(
                    _safe_float(row.get("wallet_lead_score"))
                    if row.get("wallet_lead_score") not in (None, "")
                    else None
                ),
                wallet_cluster=row.get("wallet_cluster", ""),
                window_start_ts=(
                    _safe_float(row.get("window_start_ts"))
                    if row.get("window_start_ts") not in (None, "")
                    else None
                ),
                window_open_price=(
                    _safe_float(row.get("window_open_price"))
                    if row.get("window_open_price") not in (None, "")
                    else None
                ),
                window_open_source=row.get("window_open_source", ""),
                window_open_price_trusted=str(row.get("window_open_price_trusted", "")).strip().lower() == "true",
                window_open_anchor_age_seconds=(
                    _safe_float(row.get("window_open_anchor_age_seconds"))
                    if row.get("window_open_anchor_age_seconds") not in (None, "")
                    else None
                ),
                actual_window_return=(
                    _safe_float(row.get("actual_window_return"))
                    if row.get("actual_window_return") not in (None, "")
                    else None
                ),
                actual_move_regime=row.get("actual_move_regime", ""),
                actual_move_side=row.get("actual_move_side", ""),
                strategy_route=row.get("strategy_route", ""),
                cluster_id=row.get("cluster_id", ""),
                signal_epoch_id=row.get("signal_epoch_id", ""),
                book_age_ms=(
                    _safe_float(row.get("book_age_ms"))
                    if row.get("book_age_ms") not in (None, "")
                    else None
                ),
                tick_size=(
                    _safe_float(row.get("tick_size"))
                    if row.get("tick_size") not in (None, "")
                    else None
                ),
                expected_fill_price=(
                    _safe_float(row.get("expected_fill_price"))
                    if row.get("expected_fill_price") not in (None, "")
                    else None
                ),
                expected_cost=(
                    _safe_float(row.get("expected_cost"))
                    if row.get("expected_cost") not in (None, "")
                    else None
                ),
                trade_id=row.get("trade_id", ""),
                session_id=row.get("session_id", ""),
                bucket=row.get("bucket", "uncategorized"),
                expected_value=_safe_float(row.get("expected_value"), 0.0),
                markout_1s=(
                    _safe_float(row.get("markout_1s"))
                    if row.get("markout_1s") not in (None, "")
                    else None
                ),
                markout_5s=(
                    _safe_float(row.get("markout_5s"))
                    if row.get("markout_5s") not in (None, "")
                    else None
                ),
                markout_30s=(
                    _safe_float(row.get("markout_30s"))
                    if row.get("markout_30s") not in (None, "")
                    else None
                ),
                redemption_status=row.get("redemption_status", ""),
                redemption_tx_id=row.get("redemption_tx_id", ""),
                redemption_tx_hash=row.get("redemption_tx_hash", ""),
                redemption_error=row.get("redemption_error", ""),
                redemption_updated_at=_safe_datetime(row.get("redemption_updated_at")),
            )
        )
    return trades


def _open_order_to_row(order: OpenOrder) -> list[str]:
    return [
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
        str(order.strategy_version),
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
        f"{order.edge_gross:.6f}",
        f"{order.edge_net:.6f}",
        order.reference_symbol,
        _float_or_blank(order.reference_price),
        _float_or_blank(order.best_bid),
        _float_or_blank(order.best_ask),
        _float_or_blank(order.spread),
        f"{order.decision_latency_ms:.3f}",
        order.thesis_id,
        order.cancel_reason,
        order.strategy_mode,
        order.coin,
        _float_or_blank(order.model_up_probability),
        _float_or_blank(order.selected_side_probability),
        _float_or_blank(order.interval_open),
        _float_or_blank(order.interval_high),
        _float_or_blank(order.interval_low),
        _float_or_blank(order.interval_close),
        _float_or_blank(order.interval_return),
        _float_or_blank(order.late_return_60s),
        _float_or_blank(order.late_return_20s),
        _float_or_blank(order.body_ratio),
        _float_or_blank(order.wick_imbalance),
        order.candle_regime,
        order.trend_alignment,
        _float_or_blank(order.market_yes_at_open),
        _float_or_blank(order.market_yes_at_decision),
        _float_or_blank(order.market_yes_at_close),
        order.contrarian_block_reason,
        order.wallet_signal_source,
        _float_or_blank(order.wallet_lead_score),
        order.wallet_cluster,
        _float_or_blank(order.window_start_ts, digits=3),
        _float_or_blank(order.window_open_price),
        order.window_open_source,
        str(order.window_open_price_trusted),
        _float_or_blank(order.window_open_anchor_age_seconds),
        _float_or_blank(order.actual_window_return),
        order.actual_move_regime,
        order.actual_move_side,
        order.strategy_route,
        order.cluster_id,
        order.signal_epoch_id,
        _float_or_blank(order.book_age_ms, digits=3),
        _float_or_blank(order.tick_size),
        _float_or_blank(order.expected_fill_price),
        _float_or_blank(order.expected_cost),
        _float_or_blank(order.markout_1s),
        _float_or_blank(order.markout_5s),
        _float_or_blank(order.markout_30s),
    ]


def save_open_orders(open_orders: list[OpenOrder], path: Path = OPEN_ORDERS_CSV) -> None:
    """Rewrite persisted live order state."""
    with _open_csv(path, "w") as f:
        writer = csv.writer(f)
        writer.writerow(OPEN_ORDER_FIELDS)
        for order in open_orders:
            writer.writerow(_open_order_to_row(order))


def read_open_orders(path: Path = OPEN_ORDERS_CSV) -> list[OpenOrder]:
    if not path.exists():
        return []

    open_orders = []
    reader = _csv_dict_reader(path)
    for row in reader:
        if not row or _is_header_row(row) or not row.get("order_id"):
            continue
        created_at = _safe_datetime(row.get("created_at"))
        updated_at = _safe_datetime(row.get("updated_at"))
        if created_at is None or updated_at is None:
            continue
        open_orders.append(
            OpenOrder(
                order_id=row["order_id"],
                created_at=created_at,
                updated_at=updated_at,
                market_slug=row.get("market_slug", ""),
                question=row.get("question", ""),
                condition_id=row.get("condition_id", ""),
                token_id=row.get("token_id", ""),
                strategy=row.get("strategy", ""),
                side=row.get("side", ""),
                confidence=_safe_float(row.get("confidence")),
                reason=row.get("reason", ""),
                end_date=_safe_datetime(row.get("end_date")),
                market_type=row.get("market_type", "5m") or "5m",
                strategy_version=int(_safe_float(row.get("strategy_version"), 0.0)),
                executor_type=row.get("executor_type", ""),
                limit_price=_safe_float(row.get("limit_price")),
                requested_size=_safe_float(row.get("requested_size")),
                requested_shares=_safe_float(row.get("requested_shares")),
                reserved_size=_safe_float(row.get("reserved_size")),
                confirmed_fill_size=_safe_float(row.get("confirmed_fill_size")),
                confirmed_fill_shares=_safe_float(row.get("confirmed_fill_shares")),
                confirmed_fees=_safe_float(row.get("confirmed_fees")),
                status=row.get("status", "submitted"),
                raw_status=row.get("raw_status", ""),
                edge_gross=_safe_float(row.get("edge_gross")),
                edge_net=_safe_float(row.get("edge_net")),
                reference_symbol=row.get("reference_symbol", ""),
                reference_price=(
                    _safe_float(row.get("reference_price"))
                    if row.get("reference_price") not in (None, "")
                    else None
                ),
                best_bid=(
                    _safe_float(row.get("best_bid"))
                    if row.get("best_bid") not in (None, "")
                    else None
                ),
                best_ask=(
                    _safe_float(row.get("best_ask"))
                    if row.get("best_ask") not in (None, "")
                    else None
                ),
                spread=(
                    _safe_float(row.get("spread"))
                    if row.get("spread") not in (None, "")
                    else None
                ),
                decision_latency_ms=_safe_float(row.get("decision_latency_ms")),
                thesis_id=row.get("thesis_id", ""),
                cancel_reason=row.get("cancel_reason", ""),
                strategy_mode=row.get("strategy_mode", "live") or "live",
                coin=row.get("coin", ""),
                model_up_probability=(
                    _safe_float(row.get("model_up_probability"))
                    if row.get("model_up_probability") not in (None, "")
                    else None
                ),
                selected_side_probability=(
                    _safe_float(row.get("selected_side_probability"))
                    if row.get("selected_side_probability") not in (None, "")
                    else None
                ),
                interval_open=(
                    _safe_float(row.get("interval_open"))
                    if row.get("interval_open") not in (None, "")
                    else None
                ),
                interval_high=(
                    _safe_float(row.get("interval_high"))
                    if row.get("interval_high") not in (None, "")
                    else None
                ),
                interval_low=(
                    _safe_float(row.get("interval_low"))
                    if row.get("interval_low") not in (None, "")
                    else None
                ),
                interval_close=(
                    _safe_float(row.get("interval_close"))
                    if row.get("interval_close") not in (None, "")
                    else None
                ),
                interval_return=(
                    _safe_float(row.get("interval_return"))
                    if row.get("interval_return") not in (None, "")
                    else None
                ),
                late_return_60s=(
                    _safe_float(row.get("late_return_60s"))
                    if row.get("late_return_60s") not in (None, "")
                    else None
                ),
                late_return_20s=(
                    _safe_float(row.get("late_return_20s"))
                    if row.get("late_return_20s") not in (None, "")
                    else None
                ),
                body_ratio=(
                    _safe_float(row.get("body_ratio"))
                    if row.get("body_ratio") not in (None, "")
                    else None
                ),
                wick_imbalance=(
                    _safe_float(row.get("wick_imbalance"))
                    if row.get("wick_imbalance") not in (None, "")
                    else None
                ),
                candle_regime=row.get("candle_regime", ""),
                trend_alignment=row.get("trend_alignment", ""),
                market_yes_at_open=(
                    _safe_float(row.get("market_yes_at_open"))
                    if row.get("market_yes_at_open") not in (None, "")
                    else None
                ),
                market_yes_at_decision=(
                    _safe_float(row.get("market_yes_at_decision"))
                    if row.get("market_yes_at_decision") not in (None, "")
                    else None
                ),
                market_yes_at_close=(
                    _safe_float(row.get("market_yes_at_close"))
                    if row.get("market_yes_at_close") not in (None, "")
                    else None
                ),
                contrarian_block_reason=row.get("contrarian_block_reason", ""),
                wallet_signal_source=row.get("wallet_signal_source", ""),
                wallet_lead_score=(
                    _safe_float(row.get("wallet_lead_score"))
                    if row.get("wallet_lead_score") not in (None, "")
                    else None
                ),
                wallet_cluster=row.get("wallet_cluster", ""),
                window_start_ts=(
                    _safe_float(row.get("window_start_ts"))
                    if row.get("window_start_ts") not in (None, "")
                    else None
                ),
                window_open_price=(
                    _safe_float(row.get("window_open_price"))
                    if row.get("window_open_price") not in (None, "")
                    else None
                ),
                window_open_source=row.get("window_open_source", ""),
                window_open_price_trusted=str(row.get("window_open_price_trusted", "")).strip().lower() == "true",
                window_open_anchor_age_seconds=(
                    _safe_float(row.get("window_open_anchor_age_seconds"))
                    if row.get("window_open_anchor_age_seconds") not in (None, "")
                    else None
                ),
                actual_window_return=(
                    _safe_float(row.get("actual_window_return"))
                    if row.get("actual_window_return") not in (None, "")
                    else None
                ),
                actual_move_regime=row.get("actual_move_regime", ""),
                actual_move_side=row.get("actual_move_side", ""),
                strategy_route=row.get("strategy_route", ""),
                cluster_id=row.get("cluster_id", ""),
                signal_epoch_id=row.get("signal_epoch_id", ""),
                book_age_ms=(
                    _safe_float(row.get("book_age_ms"))
                    if row.get("book_age_ms") not in (None, "")
                    else None
                ),
                tick_size=(
                    _safe_float(row.get("tick_size"))
                    if row.get("tick_size") not in (None, "")
                    else None
                ),
                expected_fill_price=(
                    _safe_float(row.get("expected_fill_price"))
                    if row.get("expected_fill_price") not in (None, "")
                    else None
                ),
                expected_cost=(
                    _safe_float(row.get("expected_cost"))
                    if row.get("expected_cost") not in (None, "")
                    else None
                ),
                markout_1s=(
                    _safe_float(row.get("markout_1s"))
                    if row.get("markout_1s") not in (None, "")
                    else None
                ),
                markout_5s=(
                    _safe_float(row.get("markout_5s"))
                    if row.get("markout_5s") not in (None, "")
                    else None
                ),
                markout_30s=(
                    _safe_float(row.get("markout_30s"))
                    if row.get("markout_30s") not in (None, "")
                    else None
                ),
            )
        )
    return open_orders
