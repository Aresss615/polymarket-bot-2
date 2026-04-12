#!/usr/bin/env python3
"""Post-simulation analysis script.

Reads trades.jsonl and events.jsonl to produce a comprehensive report
comparing paper vs simulation performance and providing go/no-go guidance.

Usage:
    python analyze_simulation.py
"""

import json
import re
import sys
from pathlib import Path

TRADES_JSONL = Path("trades.jsonl")
EVENTS_JSONL = Path("events.jsonl")

_COIN_RE = re.compile(r"^([a-z]+)-updown-", re.IGNORECASE)


def _extract_coin(slug: str) -> str:
    m = _COIN_RE.match(slug)
    return m.group(1).upper() if m else "OTHER"


def load_trades() -> list[dict]:
    if not TRADES_JSONL.exists():
        return []
    trades = []
    with open(TRADES_JSONL) as f:
        for line in f:
            line = line.strip()
            if line:
                trades.append(json.loads(line))
    return trades


def load_events() -> list[dict]:
    if not EVENTS_JSONL.exists():
        return []
    events = []
    with open(EVENTS_JSONL) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def analyze():
    trades = load_trades()
    events = load_events()

    if not trades:
        print("No trades found in trades.jsonl")
        print("Run the bot in simulation mode first:")
        print("  TRADING_MODE=simulation python main.py")
        return

    # Basic stats
    settled = [t for t in trades if t.get("status") in ("won", "lost")]
    wins = [t for t in settled if t["status"] == "won"]
    losses = [t for t in settled if t["status"] == "lost"]
    pending = [t for t in trades if t.get("status") == "pending"]

    total_risked = sum(t["size"] for t in settled)
    total_fees = sum(t.get("fees", 0) for t in trades)
    total_payout = sum(t.get("payout", 0) for t in wins)
    gross_pnl = total_payout - total_risked
    net_pnl = gross_pnl  # fees already included in fill price for simulation

    print("=" * 60)
    print("SIMULATION ANALYSIS REPORT")
    print("=" * 60)
    print()

    print(f"Total trades:     {len(trades)}")
    print(f"Settled:          {len(settled)} ({len(wins)}W / {len(losses)}L)")
    print(f"Pending:          {len(pending)}")
    print(f"Win rate:         {len(wins)/len(settled):.1%}" if settled else "Win rate: N/A")
    print()

    print("--- P&L ---")
    print(f"Total risked:     ${total_risked:.2f}")
    print(f"Total payout:     ${total_payout:.2f}")
    print(f"Gross P&L:        ${gross_pnl:+.2f}")
    print(f"Total fees:       ${total_fees:.2f}")
    print(f"Net P&L:          ${net_pnl:+.2f}")
    if total_risked > 0:
        print(f"ROI:              {net_pnl/total_risked:.1%}")
    print()

    # Execution quality
    sim_trades = [t for t in trades if t.get("executor_type") == "SimulationExecutor"]
    if sim_trades:
        orders = [t.get("order", {}) for t in sim_trades if t.get("order")]
        if orders:
            avg_slippage = sum(o.get("slippage", 0) for o in orders) / len(orders)
            avg_fees = sum(o.get("fees", 0) for o in orders) / len(orders)
            avg_latency = sum(o.get("latency_ms", 0) for o in orders) / len(orders)
            partials = sum(1 for o in orders if o.get("status") == "partial")
            rejections = sum(1 for o in orders if o.get("status") == "rejected")

            print("--- Execution Quality ---")
            print(f"Avg slippage:     {avg_slippage:.4f}")
            print(f"Avg fees/trade:   ${avg_fees:.4f}")
            print(f"Avg latency:      {avg_latency:.0f}ms")
            print(f"Partial fills:    {partials}/{len(orders)}")
            print(f"Rejections:       {rejections}/{len(orders)}")
            print()

    # Per-coin breakdown
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

    # Risk events
    risk_blocks = [e for e in events if e.get("type") == "risk_block"]
    if risk_blocks:
        print("--- Risk Events ---")
        reasons = {}
        for e in risk_blocks:
            reason = e.get("reason", "unknown")
            # Normalize reason to category
            if "daily loss" in reason:
                cat = "daily_loss_limit"
            elif "exposure cap" in reason:
                cat = "exposure_cap"
            elif "consecutive" in reason:
                cat = "consecutive_loss"
            elif "kill switch" in reason:
                cat = "kill_switch"
            elif "exposure" in reason:
                cat = "per_coin_exposure"
            else:
                cat = "other"
            reasons[cat] = reasons.get(cat, 0) + 1
        for cat, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {cat}: {count} blocks")
        print()

    # Go/No-Go recommendation
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
            print(f"CAUTION: Fees (${total_fees:.2f}) are >50% of gross P&L")
            print("Consider optimizing for lower-fee entry points")
        else:
            print(f"CAUTIOUS GO: WR={wr:.1%}, Net P&L=${net_pnl:+.2f}")
            print("Start with minimum size ($1-5) and monitor closely")
    print()


if __name__ == "__main__":
    analyze()
