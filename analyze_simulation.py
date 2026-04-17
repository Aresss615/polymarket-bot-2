#!/usr/bin/env python3
"""Post-run analysis script.

Reads ``trades.jsonl`` and ``events.jsonl`` to produce a comprehensive report
using confirmed trade snapshots plus settlement events.
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from config import CANDIDATE_COINS

TRADES_JSONL = Path("trades.jsonl")
EVENTS_JSONL = Path("events.jsonl")

_COIN_RE = re.compile(r"^([a-z]+)-updown-", re.IGNORECASE)


def _extract_coin(slug: str) -> str:
    m = _COIN_RE.match(slug)
    return m.group(1).upper() if m else "OTHER"


def _price_bucket(price: float | None) -> str:
    if price is None:
        return "unknown"
    if price < 0.10:
        return "<0.10"
    if price < 0.25:
        return "0.10-0.24"
    if price < 0.50:
        return "0.25-0.49"
    if price < 0.75:
        return "0.50-0.74"
    if price < 0.90:
        return "0.75-0.89"
    return ">=0.90"


def _spread_bucket(spread: float | None) -> str:
    if spread is None:
        return "unknown"
    if spread < 0.01:
        return "<0.01"
    if spread < 0.02:
        return "0.01-0.019"
    if spread < 0.05:
        return "0.02-0.049"
    return ">=0.05"


def _latency_bucket(latency_ms: float | None) -> str:
    if latency_ms is None:
        return "unknown"
    if latency_ms < 100:
        return "<100ms"
    if latency_ms < 250:
        return "100-249ms"
    if latency_ms < 500:
        return "250-499ms"
    return ">=500ms"


def _high_prob_band(price: float | None) -> str:
    if price is None:
        return "unknown"
    if price <= 0.82:
        return "0.78-0.82"
    if price <= 0.86:
        return "0.82-0.86"
    return "0.86-0.90"


def _iter_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []

    rows: list[dict] = []
    with open(path, encoding="utf-8-sig") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("{") is False:
                # Skip malformed header rows or accidental CSV fragments.
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def load_trades() -> list[dict]:
    return [row for row in _iter_jsonl(TRADES_JSONL) if row.get("type") == "trade"]


def load_events() -> list[dict]:
    return _iter_jsonl(EVENTS_JSONL)


def _trade_key(trade: dict) -> tuple[str, str]:
    order_id = trade.get("order_id")
    if order_id:
        return ("order", order_id)
    return ("legacy", f"{trade['timestamp']}|{trade['market_slug']}|{trade['side']}")


def build_trade_state(trades: list[dict], events: list[dict]) -> list[dict]:
    """Reconstruct latest known trade state from snapshots and settlements."""
    trades_sorted = sorted(trades, key=lambda row: row["timestamp"])
    settlements = sorted(
        [event for event in events if event.get("type") == "settlement"],
        key=lambda row: row["timestamp"],
    )

    latest_by_key: dict[tuple[str, str], dict] = {}
    legacy_by_market: defaultdict[tuple[str, str], list[tuple[tuple[str, str], dict]]] = defaultdict(list)

    for trade in trades_sorted:
        key = _trade_key(trade)
        existing = latest_by_key.get(key)
        if existing is None or trade["timestamp"] >= existing["timestamp"]:
            latest_by_key[key] = dict(trade)

    for key, trade in latest_by_key.items():
        if key[0] == "legacy":
            legacy_by_market[(trade["market_slug"], trade["side"])].append((key, trade))

    for bucket in legacy_by_market.values():
        bucket.sort(key=lambda item: item[1]["timestamp"])

    used_legacy_keys: set[tuple[str, str]] = set()

    for settlement in settlements:
        order_id = settlement.get("order_id")
        target = None
        if order_id:
            target = latest_by_key.get(("order", order_id))

        if target is None:
            candidates = legacy_by_market.get((settlement["market_slug"], settlement["side"]), [])
            for key, trade in candidates:
                if key in used_legacy_keys:
                    continue
                if trade["timestamp"] <= settlement["timestamp"]:
                    target = trade
                    used_legacy_keys.add(key)
                    break

        if target is None:
            continue

        target["status"] = settlement["status"]
        target["payout"] = settlement["payout"]
        target["fees"] = settlement.get("fees", target.get("fees", 0.0))

    return sorted(latest_by_key.values(), key=lambda row: row["timestamp"])


def _signal_key(event: dict) -> tuple[str, str]:
    signal_id = event.get("signal_id")
    if signal_id:
        return ("signal", str(signal_id))
    return (
        "legacy_signal",
        "|".join(
            [
                str(event.get("timestamp") or ""),
                str(event.get("market_slug") or ""),
                str(event.get("strategy_mode") or ""),
                str(event.get("signal_side") or ""),
                str(event.get("strategy_route") or ""),
            ]
        ),
    )


def build_signal_state(events: list[dict]) -> list[dict]:
    signal_events = sorted(
        [event for event in events if event.get("type") == "signal_event"],
        key=lambda row: str(row.get("timestamp") or ""),
    )
    latest_by_key: dict[tuple[str, str], dict] = {}
    for event in signal_events:
        key = _signal_key(event)
        existing = latest_by_key.get(key)
        event_ts = str(event.get("timestamp") or "")
        existing_ts = str(existing.get("timestamp") or "") if existing is not None else ""
        if existing is None or event_ts >= existing_ts:
            latest_by_key[key] = dict(event)
    return sorted(latest_by_key.values(), key=lambda row: str(row.get("timestamp") or ""))


def _trade_pnl(trade: dict) -> float | None:
    status = trade.get("status")
    if status == "won":
        return float(trade.get("payout", 0.0)) - float(trade.get("size", 0.0))
    if status == "lost":
        return -float(trade.get("size", 0.0))
    return None


def _fill_shares(trade: dict) -> float:
    order = trade.get("order") or {}
    fill_shares = order.get("fill_shares")
    if fill_shares not in (None, ""):
        return float(fill_shares)
    fill_price = order.get("fill_price", trade.get("fill_price", trade.get("entry_price", 0.0)))
    if fill_price:
        return float(trade.get("size", 0.0)) / float(fill_price)
    return 0.0


def _execution_delta_cost(trade: dict) -> float:
    order = trade.get("order") or {}
    fill_price = order.get("fill_price", trade.get("fill_price", trade.get("entry_price", 0.0))) or 0.0
    expected_fill_price = trade.get("expected_fill_price", order.get("expected_fill_price", fill_price)) or fill_price
    return max(float(fill_price) - float(expected_fill_price), 0.0) * _fill_shares(trade)


def _spread_cost(trade: dict) -> float:
    order = trade.get("order") or {}
    spread = order.get("spread", trade.get("spread")) or 0.0
    return max(float(spread), 0.0) * _fill_shares(trade)


def _candidate_trade(trade: dict) -> bool:
    coin = _extract_coin(trade.get("market_slug", ""))
    return (
        trade.get("strategy") == "updown"
        and trade.get("strategy_mode") == "live"
        and trade.get("market_type") == "5m"
        and coin in CANDIDATE_COINS
    )


def _performance_breakdown(rows: list[dict], field: str) -> dict[str, dict[str, float | int | None]]:
    settled = [row for row in rows if row.get("status") in {"won", "lost"}]
    buckets = sorted({str(row.get(field) or "unknown") for row in settled})
    summary: dict[str, dict[str, float | int | None]] = {}
    for bucket in buckets:
        bucket_rows = [row for row in settled if str(row.get(field) or "unknown") == bucket]
        pnl_values = [_trade_pnl(row) for row in bucket_rows]
        pnl = sum(value for value in pnl_values if value is not None)
        wins = sum(1 for row in bucket_rows if row.get("status") == "won")
        summary[bucket] = {
            "trades": len(bucket_rows),
            "win_rate": (wins / len(bucket_rows)) if bucket_rows else None,
            "pnl": pnl,
        }
    return summary


def summarize_actual_move(latest_trades: list[dict], events: list[dict]) -> dict:
    signal_events = build_signal_state(events)
    contrarian_events = [event for event in signal_events if event.get("contrarian_block_reason")]
    strong_up_legacy_no = sum(
        1
        for event in signal_events
        if event.get("actual_move_regime") == "strong"
        and event.get("actual_move_side") == "YES"
        and event.get("legacy_signal_side") == "NO"
    )
    strong_down_legacy_yes = sum(
        1
        for event in signal_events
        if event.get("actual_move_regime") == "strong"
        and event.get("actual_move_side") == "NO"
        and event.get("legacy_signal_side") == "YES"
    )
    high_prob_shadow_events = [
        event for event in signal_events if event.get("strategy_route") == "high_prob_shadow"
    ]
    high_prob_bands = Counter(
        _high_prob_band(float(event["entry_price"])) for event in high_prob_shadow_events if event.get("entry_price") not in (None, "")
    )
    return {
        "by_regime": _performance_breakdown(latest_trades, "actual_move_regime"),
        "by_route": _performance_breakdown(latest_trades, "strategy_route"),
        "forbidden_blocked_contrarian_cases": len(contrarian_events),
        "strong_up_legacy_no": strong_up_legacy_no,
        "strong_down_legacy_yes": strong_down_legacy_yes,
        "high_prob_shadow_bands": dict(high_prob_bands),
    }


def build_dumb_loss_audit(latest_trades: list[dict], events: list[dict]) -> dict:
    settled = [trade for trade in latest_trades if trade.get("status") in {"won", "lost"}]
    disagreement_trades = [
        trade
        for trade in settled
        if trade.get("actual_move_side") in {"YES", "NO"}
        and trade.get("side") in {"YES", "NO"}
        and trade.get("actual_move_side") != trade.get("side")
    ]
    strong_disagreements = [
        trade for trade in disagreement_trades if trade.get("actual_move_regime") == "strong"
    ]
    signal_events = build_signal_state(events)
    legacy_contrarian_examples = [
        event
        for event in signal_events
        if event.get("actual_move_regime") == "strong"
        and event.get("contrarian_block_reason")
    ]
    return {
        "trades_against_actual_move": len(disagreement_trades),
        "trades_against_actual_move_pnl": sum(_trade_pnl(trade) or 0.0 for trade in disagreement_trades),
        "strong_move_disagreements": len(strong_disagreements),
        "strong_move_disagreement_pnl": sum(_trade_pnl(trade) or 0.0 for trade in strong_disagreements),
        "legacy_contrarian_strong_move_examples": len(legacy_contrarian_examples),
    }


def summarize_shadow_signals(events: list[dict]) -> dict:
    signal_rows = build_signal_state(events)
    tracked_shadow = [
        row
        for row in signal_rows
        if row.get("strategy_mode") == "shadow"
        and row.get("signal_side") in {"YES", "NO"}
        and row.get("decision_stage") not in {"traded", "order_live", "already_traded_skip", "active_order_skip"}
    ]
    settled_shadow = [row for row in tracked_shadow if row.get("signal_status") in {"won", "lost"}]
    wins = sum(1 for row in settled_shadow if row.get("signal_status") == "won")

    by_route: dict[str, dict[str, float | int | None]] = {}
    for route in sorted({str(row.get("strategy_route") or "unclassified") for row in settled_shadow}):
        route_rows = [row for row in settled_shadow if str(row.get("strategy_route") or "unclassified") == route]
        route_wins = sum(1 for row in route_rows if row.get("signal_status") == "won")
        by_route[route] = {
            "signals": len(route_rows),
            "win_rate": (route_wins / len(route_rows)) if route_rows else None,
        }

    return {
        "tracked": len(tracked_shadow),
        "settled": len(settled_shadow),
        "wins": wins,
        "losses": len(settled_shadow) - wins,
        "win_rate": (wins / len(settled_shadow)) if settled_shadow else None,
        "by_route": by_route,
    }


def count_replay_drift(trade_snapshots: list[dict], latest_trades: list[dict], events: list[dict]) -> int:
    drift = 0
    snapshots_by_key: defaultdict[tuple[str, str], list[dict]] = defaultdict(list)
    for trade in trade_snapshots:
        snapshots_by_key[_trade_key(trade)].append(trade)

    for snapshots in snapshots_by_key.values():
        previous_size = 0.0
        for row in sorted(snapshots, key=lambda item: item["timestamp"]):
            size = float(row.get("size", 0.0))
            if size + 1e-9 < previous_size:
                drift += 1
                break
            previous_size = size

    latest_order_ids = {trade.get("order_id") for trade in latest_trades if trade.get("order_id")}
    for event in events:
        if event.get("type") != "settlement":
            continue
        order_id = event.get("order_id")
        if order_id and order_id not in latest_order_ids:
            drift += 1
    return drift


def build_promotion_report(
    trade_snapshots: list[dict],
    latest_trades: list[dict],
    events: list[dict],
    *,
    latency_multiplier: float = 2.0,
    spread_slippage_multiplier: float = 1.5,
) -> dict:
    candidate_trades = [trade for trade in latest_trades if _candidate_trade(trade)]
    candidate_settled = [trade for trade in candidate_trades if trade.get("status") in {"won", "lost"}]
    pnl_series = [_trade_pnl(trade) for trade in candidate_settled]
    pnl_series = [pnl for pnl in pnl_series if pnl is not None]

    stressed_pnls: list[float] = []
    for trade in candidate_settled:
        pnl = _trade_pnl(trade)
        if pnl is None:
            continue
        extra_latency = _execution_delta_cost(trade) * max(latency_multiplier - 1.0, 0.0)
        extra_spread = _spread_cost(trade) * max(spread_slippage_multiplier - 1.0, 0.0)
        stressed_pnls.append(pnl - extra_latency - extra_spread)

    candidate_signals = [
        event
        for event in events
        if event.get("type") == "signal_event"
        and event.get("strategy") == "updown"
        and event.get("strategy_mode") == "live"
        and event.get("market_type") == "5m"
        and event.get("coin") in CANDIDATE_COINS
    ]
    attempt_events = [
        event
        for event in candidate_signals
        if event.get("decision_stage") in {"traded", "order_live", "order_rejected"}
    ]
    fill_ratio = len(candidate_trades) / len(attempt_events) if attempt_events else None
    miss_ratio = (
        sum(1 for event in attempt_events if event.get("decision_stage") == "order_rejected") / len(attempt_events)
        if attempt_events
        else None
    )

    fills_by_coin = Counter(_extract_coin(trade.get("market_slug", "")) for trade in candidate_trades)
    latency_buckets = Counter()
    spread_buckets = Counter()
    price_buckets = Counter()
    cluster_epoch_counts = Counter()

    for trade in candidate_trades:
        order = trade.get("order") or {}
        latency = order.get("latency_ms", trade.get("decision_latency_ms"))
        latency_buckets[_latency_bucket(float(latency) if latency not in (None, "") else None)] += 1
        spread = order.get("spread", trade.get("spread"))
        spread_buckets[_spread_bucket(float(spread) if spread not in (None, "") else None)] += 1
        entry_price = trade.get("entry_price")
        price_buckets[_price_bucket(float(entry_price) if entry_price not in (None, "") else None)] += 1
        cluster_id = trade.get("cluster_id")
        signal_epoch_id = trade.get("signal_epoch_id")
        if cluster_id and signal_epoch_id:
            cluster_epoch_counts[(cluster_id, signal_epoch_id)] += 1

    cluster_stacking_incidents = sum(
        count - 1
        for count in cluster_epoch_counts.values()
        if count > 1
    )
    forbidden_contrarian_candidate_trades = sum(
        1
        for trade in candidate_trades
        if trade.get("actual_move_regime") == "strong"
        and trade.get("actual_move_side") in {"YES", "NO"}
        and trade.get("side") in {"YES", "NO"}
        and trade.get("actual_move_side") != trade.get("side")
    )
    replay_drift_incidents = count_replay_drift(trade_snapshots, latest_trades, events)
    markouts = {
        "1s": [float(trade["markout_1s"]) for trade in candidate_trades if trade.get("markout_1s") not in (None, "")],
        "5s": [float(trade["markout_5s"]) for trade in candidate_trades if trade.get("markout_5s") not in (None, "")],
        "30s": [float(trade["markout_30s"]) for trade in candidate_trades if trade.get("markout_30s") not in (None, "")],
    }

    promotion_blockers: list[str] = []
    stressed_ev_per_trade = sum(stressed_pnls) / len(stressed_pnls) if stressed_pnls else None
    if len(candidate_trades) < 300:
        promotion_blockers.append(f"need 300 candidate fills, have {len(candidate_trades)}")
    for coin in sorted(CANDIDATE_COINS):
        if fills_by_coin.get(coin, 0) < 100:
            promotion_blockers.append(f"{coin} needs 100 fills, has {fills_by_coin.get(coin, 0)}")
    if replay_drift_incidents > 0:
        promotion_blockers.append(f"replay drift incidents: {replay_drift_incidents}")
    if forbidden_contrarian_candidate_trades > 0:
        promotion_blockers.append(
            f"strong-move contrarian candidate trades: {forbidden_contrarian_candidate_trades}"
        )
    if stressed_ev_per_trade is None or stressed_ev_per_trade <= 0:
        promotion_blockers.append("stressed EV per trade is non-positive")
    if fill_ratio is not None and fill_ratio < 0.80:
        promotion_blockers.append(f"fill ratio degraded to {fill_ratio:.1%}")

    turnover = sum(float(trade.get("size", 0.0)) for trade in candidate_settled)
    realized_pnl = sum(pnl_series)
    return {
        "fills_combined": len(candidate_trades),
        "fills_by_coin": dict(fills_by_coin),
        "settled_fills": len(candidate_settled),
        "ev_per_trade": (realized_pnl / len(candidate_settled)) if candidate_settled else None,
        "ev_per_turnover": (realized_pnl / turnover) if turnover > 0 else None,
        "stressed_ev_per_trade": stressed_ev_per_trade,
        "fill_ratio": fill_ratio,
        "miss_ratio": miss_ratio,
        "markout_curves": {
            bucket: (sum(values) / len(values) if values else None)
            for bucket, values in markouts.items()
        },
        "latency_buckets": dict(latency_buckets),
        "spread_buckets": dict(spread_buckets),
        "price_buckets": dict(price_buckets),
        "forbidden_contrarian_candidate_trades": forbidden_contrarian_candidate_trades,
        "cluster_stacking_incidents": cluster_stacking_incidents,
        "replay_drift_incidents": replay_drift_incidents,
        "promotion_blocked": bool(promotion_blockers),
        "promotion_blockers": promotion_blockers,
        "stress_assumptions": {
            "latency_multiplier": latency_multiplier,
            "spread_slippage_multiplier": spread_slippage_multiplier,
        },
    }


def analyze():
    trades = load_trades()
    events = load_events()

    if not trades:
        print("No trades found in trades.jsonl")
        print("Run the bot first to generate confirmed trade snapshots.")
        return

    latest_trades = build_trade_state(trades, events)
    promotion = build_promotion_report(trades, latest_trades, events)
    actual_move_summary = summarize_actual_move(latest_trades, events)
    shadow_summary = summarize_shadow_signals(events)
    dumb_loss_audit = build_dumb_loss_audit(latest_trades, events)
    settled = [t for t in latest_trades if t.get("status") in ("won", "lost")]
    wins = [t for t in settled if t["status"] == "won"]
    losses = [t for t in settled if t["status"] == "lost"]
    pending = [t for t in latest_trades if t.get("status") == "pending"]

    total_risked = sum(t["size"] for t in settled)
    total_fees = sum(t.get("fees", 0) for t in latest_trades)
    total_payout = sum(t.get("payout", 0) for t in wins)
    net_pnl = total_payout - total_risked

    print("=" * 60)
    print("SIMULATION ANALYSIS REPORT")
    print("=" * 60)
    print()

    print(f"Trade snapshots:   {len(trades)}")
    print(f"Latest trades:     {len(latest_trades)}")
    print(f"Settled:           {len(settled)} ({len(wins)}W / {len(losses)}L)")
    print(f"Pending:           {len(pending)}")
    print(f"Win rate:          {len(wins)/len(settled):.1%}" if settled else "Win rate: N/A")
    print()

    print("--- P&L ---")
    print(f"Total risked:      ${total_risked:.2f}")
    print(f"Total payout:      ${total_payout:.2f}")
    print(f"Total fees:        ${total_fees:.2f}")
    print(f"Net P&L:           ${net_pnl:+.2f}")
    if total_risked > 0:
        print(f"ROI:               {net_pnl/total_risked:.1%}")
    print()

    sim_trades = [t for t in latest_trades if t.get("executor_type") == "SimulationExecutor"]
    if sim_trades:
        orders = [t.get("order", {}) for t in sim_trades if t.get("order")]
        if orders:
            avg_slippage = sum(o.get("slippage", 0) for o in orders) / len(orders)
            avg_fees = sum(o.get("fees", 0) for o in orders) / len(orders)
            avg_latency = sum(o.get("latency_ms", 0) for o in orders) / len(orders)
            partials = sum(1 for o in orders if o.get("status") == "partial")
            rejections = sum(1 for o in orders if o.get("status") == "rejected")

            print("--- Execution Quality ---")
            print(f"Avg slippage:      {avg_slippage:.4f}")
            print(f"Avg fees/trade:    ${avg_fees:.4f}")
            print(f"Avg latency:       {avg_latency:.0f}ms")
            print(f"Partial fills:     {partials}/{len(orders)}")
            print(f"Rejections:        {rejections}/{len(orders)}")
            print()

    coins = sorted(set(_extract_coin(t["market_slug"]) for t in settled))
    if coins:
        print("--- Per-Coin Performance ---")
        print(f"{'Coin':<6} {'Trades':>6} {'WR':>6} {'P&L':>10} {'Fees':>8}")
        print("-" * 40)
        for coin in coins:
            ct = [t for t in settled if _extract_coin(t["market_slug"]) == coin]
            cw = sum(1 for t in ct if t["status"] == "won")
            cpnl = sum(t.get("payout", 0) - t["size"] for t in ct)
            cfees = sum(t.get("fees", 0) for t in ct)
            print(f"{coin:<6} {len(ct):>6} {cw/len(ct):>5.0%} {cpnl:>+9.2f} {cfees:>7.2f}")
        print()

    alignment_trades = [t for t in settled if t.get("trend_alignment")]
    if alignment_trades:
        print("--- Trade Alignment ---")
        print(f"{'Alignment':<22} {'Trades':>6} {'WR':>6} {'P&L':>10}")
        print("-" * 50)
        for alignment in sorted(set(t.get("trend_alignment") for t in alignment_trades)):
            rows = [t for t in alignment_trades if t.get("trend_alignment") == alignment]
            wins_for_alignment = sum(1 for t in rows if t["status"] == "won")
            pnl = sum(t.get("payout", 0.0) - t["size"] for t in rows)
            print(f"{alignment:<22} {len(rows):>6} {wins_for_alignment/len(rows):>5.0%} {pnl:>+9.2f}")
        print()

    if settled:
        print("--- Price Buckets ---")
        print(f"{'Bucket':<10} {'Trades':>6} {'WR':>6} {'P&L':>10}")
        print("-" * 38)
        buckets = sorted({_price_bucket(t.get("entry_price")) for t in settled})
        for bucket in buckets:
            rows = [t for t in settled if _price_bucket(t.get("entry_price")) == bucket]
            wins_for_bucket = sum(1 for t in rows if t["status"] == "won")
            pnl = sum(t.get("payout", 0.0) - t["size"] for t in rows)
            print(f"{bucket:<10} {len(rows):>6} {wins_for_bucket/len(rows):>5.0%} {pnl:>+9.2f}")
        print()

    if actual_move_summary["by_regime"]:
        print("--- Actual Move ---")
        print(f"{'Regime':<18} {'Trades':>6} {'WR':>6} {'P&L':>10}")
        print("-" * 44)
        for regime, stats in actual_move_summary["by_regime"].items():
            win_rate = stats["win_rate"]
            print(
                f"{regime:<18} {stats['trades']:>6} "
                f"{(win_rate if win_rate is not None else 0.0):>5.0%} {stats['pnl']:>+9.2f}"
            )
        print(f"Blocked contrarian: {actual_move_summary['forbidden_blocked_contrarian_cases']}")
        print(f"Strong up -> legacy NO: {actual_move_summary['strong_up_legacy_no']}")
        print(f"Strong down -> legacy YES: {actual_move_summary['strong_down_legacy_yes']}")
        if actual_move_summary["high_prob_shadow_bands"]:
            print("High-prob shadow bands:")
            for band, count in sorted(actual_move_summary["high_prob_shadow_bands"].items()):
                print(f"  {band}: {count}")
        print()

    if actual_move_summary["by_route"]:
        print("--- Strategy Routes ---")
        print(f"{'Route':<24} {'Trades':>6} {'WR':>6} {'P&L':>10}")
        print("-" * 50)
        for route, stats in actual_move_summary["by_route"].items():
            win_rate = stats["win_rate"]
            print(
                f"{route:<24} {stats['trades']:>6} "
                f"{(win_rate if win_rate is not None else 0.0):>5.0%} {stats['pnl']:>+9.2f}"
            )
        print()

    if shadow_summary["tracked"]:
        print("--- Shadow Decisions ---")
        print(f"Tracked:           {shadow_summary['tracked']}")
        print(f"Settled:           {shadow_summary['settled']}")
        print(f"Wins/Losses:       {shadow_summary['wins']}W / {shadow_summary['losses']}L")
        if shadow_summary["win_rate"] is not None:
            print(f"Win rate:          {shadow_summary['win_rate']:.1%}")
        else:
            print("Win rate:          N/A")
        for route, stats in shadow_summary["by_route"].items():
            win_rate = stats["win_rate"]
            print(
                f"  {route}: {stats['signals']} signals"
                f"{f', {win_rate:.1%} WR' if win_rate is not None else ''}"
            )
        print()

    print("--- Dumb Loss Audit ---")
    print(f"Trades vs actual move:     {dumb_loss_audit['trades_against_actual_move']}")
    print(f"P&L vs actual move:        {dumb_loss_audit['trades_against_actual_move_pnl']:+.2f}")
    print(f"Strong-move disagreements: {dumb_loss_audit['strong_move_disagreements']}")
    print(f"Strong-move disagreement P&L: {dumb_loss_audit['strong_move_disagreement_pnl']:+.2f}")
    print(f"Legacy contrarian strong examples: {dumb_loss_audit['legacy_contrarian_strong_move_examples']}")
    print()

    risk_blocks = [e for e in events if e.get("type") == "risk_block"]
    if risk_blocks:
        print("--- Risk Events ---")
        reasons = {}
        for e in risk_blocks:
            reason = e.get("reason", "unknown")
            if "daily loss" in reason:
                cat = "daily_loss_limit"
            elif "exposure cap" in reason:
                cat = "exposure_cap"
            elif "cooldown" in reason:
                cat = "cooldown"
            elif "kill switch" in reason:
                cat = "kill_switch"
            elif "thesis" in reason:
                cat = "thesis_limit"
            elif "BTC" in reason:
                cat = "coin_limit"
            else:
                cat = "other"
            reasons[cat] = reasons.get(cat, 0) + 1
        for cat, count in sorted(reasons.items(), key=lambda item: -item[1]):
            print(f"  {cat}: {count} blocks")
        print()

    print("--- Candidate Promotion Report ---")
    print(f"Candidate fills:   {promotion['fills_combined']}")
    print(f"Settled fills:     {promotion['settled_fills']}")
    if promotion["ev_per_trade"] is not None:
        print(f"EV / trade:        ${promotion['ev_per_trade']:+.4f}")
    else:
        print("EV / trade:        N/A")
    if promotion["ev_per_turnover"] is not None:
        print(f"EV / turnover:     {promotion['ev_per_turnover']:+.2%}")
    else:
        print("EV / turnover:     N/A")
    if promotion["stressed_ev_per_trade"] is not None:
        print(f"Stress EV / trade: ${promotion['stressed_ev_per_trade']:+.4f}")
    else:
        print("Stress EV / trade: N/A")
    if promotion["fill_ratio"] is not None:
        print(f"Fill ratio:        {promotion['fill_ratio']:.1%}")
    else:
        print("Fill ratio:        N/A")
    if promotion["miss_ratio"] is not None:
        print(f"Miss ratio:        {promotion['miss_ratio']:.1%}")
    else:
        print("Miss ratio:        N/A")
    print(f"Replay drift:      {promotion['replay_drift_incidents']}")
    print(f"Forbidden contra:  {promotion['forbidden_contrarian_candidate_trades']}")
    print(f"Cluster stacking:  {promotion['cluster_stacking_incidents']}")
    for bucket, value in promotion["markout_curves"].items():
        if value is None:
            print(f"Avg markout {bucket}:  N/A")
        else:
            print(f"Avg markout {bucket}:  {value:+.4f}")
    if promotion["promotion_blocked"]:
        print("Promotion gate:    BLOCKED")
        for blocker in promotion["promotion_blockers"]:
            print(f"  - {blocker}")
    else:
        print("Promotion gate:    PASS")
    print()

    print("--- RECOMMENDATION ---")
    if not settled:
        print("KEEP SIMULATING: Not enough settled trades for evaluation")
    elif len(settled) < 50:
        print(f"KEEP SIMULATING: Only {len(settled)} settled trades (need 50+)")
    else:
        wr = len(wins) / len(settled)
        if wr < 0.70:
            print(f"DO NOT GO LIVE: Win rate {wr:.1%} below 70% threshold")
        elif net_pnl < 0:
            print(f"DO NOT GO LIVE: Net P&L is negative (${net_pnl:+.2f})")
        elif total_fees > abs(net_pnl) * 0.5:
            print(f"CAUTION: Fees (${total_fees:.2f}) are >50% of net P&L")
            print("Consider optimizing for lower-fee entry points")
        else:
            print(f"CAUTIOUS GO: WR={wr:.1%}, Net P&L=${net_pnl:+.2f}")
            print("Keep promotion gates tied to latency and shadow sample counts.")
    print()


if __name__ == "__main__":
    analyze()
