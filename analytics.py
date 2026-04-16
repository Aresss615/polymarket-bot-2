from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from config import LEDGER_JSONL, Trade, TRADES_CSV
from ledger import load_trade_state
from logger import read_trades


def _trade_from_payload(payload: dict) -> Trade:
    end_date = payload.get("end_date")
    return Trade(
        timestamp=datetime.fromisoformat(payload["timestamp"]),
        market_slug=payload["market_slug"],
        question=payload["question"],
        strategy=payload["strategy"],
        side=payload["side"],
        entry_price=float(payload["entry_price"]),
        size=float(payload["size"]),
        confidence=float(payload["confidence"]),
        reason=payload["reason"],
        status=payload.get("status", "pending"),
        payout=float(payload.get("payout", 0) or 0),
        end_date=datetime.fromisoformat(end_date) if end_date else None,
        market_type=payload.get("market_type", "5m"),
        strategy_version=int(payload.get("strategy_version", 0) or 0),
        fees=float(payload.get("fees", 0) or 0),
        fill_price=float(payload["fill_price"]) if payload.get("fill_price") else None,
        trade_id=payload.get("trade_id", ""),
        session_id=payload.get("session_id", ""),
        bucket=payload.get("bucket", "uncategorized"),
        expected_value=float(payload.get("expected_value", 0) or 0),
    )


def load_trades_from_ledger(path: Path = LEDGER_JSONL) -> list[Trade]:
    state = load_trade_state(path)
    trades = [_trade_from_payload(payload) for payload in state.values()]
    trades.sort(key=lambda t: t.timestamp)
    return trades


def settled_trades(trades: list[Trade]) -> list[Trade]:
    return [t for t in trades if t.status in {"won", "lost"}]


def compute_summary(trades: list[Trade]) -> dict:
    settled = settled_trades(trades)
    wins = [t for t in settled if t.status == "won"]
    losses = [t for t in settled if t.status == "lost"]
    pnl = sum(t.payout - t.size for t in settled)
    return {
        "total_trades": len(trades),
        "settled_trades": len(settled),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(settled) if settled else 0.0,
        "net_pnl": pnl,
    }


def summarize_by_bucket(trades: list[Trade]) -> dict[str, dict]:
    grouped: dict[str, list[Trade]] = defaultdict(list)
    for trade in settled_trades(trades):
        grouped[trade.bucket or "uncategorized"].append(trade)

    summary = {}
    for bucket, bucket_trades in grouped.items():
        wins = sum(1 for t in bucket_trades if t.status == "won")
        pnl = sum(t.payout - t.size for t in bucket_trades)
        summary[bucket] = {
            "trades": len(bucket_trades),
            "win_rate": wins / len(bucket_trades) if bucket_trades else 0.0,
            "net_pnl": pnl,
        }
    return dict(sorted(summary.items()))


def compare_csv_and_ledger(
    csv_path: Path = TRADES_CSV,
    ledger_path: Path = LEDGER_JSONL,
) -> dict:
    csv_trades = read_trades(csv_path)
    ledger_trades = load_trades_from_ledger(ledger_path)
    csv_summary = compute_summary(csv_trades)
    ledger_summary = compute_summary(ledger_trades)
    return {
        "csv": csv_summary,
        "ledger": ledger_summary,
        "counts_match": csv_summary["settled_trades"] == ledger_summary["settled_trades"],
        "pnl_match": round(csv_summary["net_pnl"], 6) == round(ledger_summary["net_pnl"], 6),
    }


def session_summary_payload(trades: list[Trade]) -> dict:
    return {
        "overall": compute_summary(trades),
        "by_bucket": summarize_by_bucket(trades),
    }

