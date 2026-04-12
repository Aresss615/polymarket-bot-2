# Next-Day Analysis: v8 Validation (2026-04-13)

## What Changed in v8 (2026-04-12)

The following were **already implemented** in v8 and need validation with fresh data:

| Change | Config | What it does |
|--------|--------|-------------|
| BTC NO blacklist | `BTC_NO_BLACKLISTED = True` | Blocks all BTC NO trades |
| NO side edge premium | `NO_SIDE_EDGE_PREMIUM = 0.03` | +3% min_edge for all NO trades |
| Fee-aware edge | Uses `MAX_TAKER_FEE_RATE = 0.018` | Subtracts estimated taker fee from edge before min_edge check |
| Risk manager | `DAILY_MAX_LOSS = 10.0`, `MAX_OPEN_EXPOSURE = 25.0` | Gates every trade through risk checks |
| Execution abstraction | `TRADING_MODE` env var | Paper/Simulation/Live executor selection |
| STRATEGY_VERSION | 7 → 8 | Clean analytics break, old trades ignored in patch stats |
| Bet sizing | `BET_FRACTION = 0.08`, `MAX_BET = 10.0` | Already reduced from v6 |

## Gaps Still Open — Validate With v8 Data

### 1. v8 Signal Volume and Quality
- The fee-aware edge + NO premium will reject more trades than v7
- **Check**: how many signals per hour in v8 vs v7? Is the bot still finding enough trades?
- **Check**: is v8 WR actually higher than v7's 78.5%? (should be, fewer marginal trades)
- **Risk**: if signal count drops too far, the bot may miss profitable opportunities
- **Action if signal count < 50% of v7**: consider reducing `NO_SIDE_EDGE_PREMIUM` from 0.03 to 0.02

### 2. Fee-Aware Edge Accuracy
- The fee model uses `fee_rate = 0.018 * (1 - 2*|price - 0.50|)` which is an approximation
- Polymarket's actual fee schedule may differ slightly
- **Check**: compare fee deductions in `trades.jsonl` against actual Polymarket fee documentation
- **Check**: are any trades being rejected where the estimated fee was wrong by >0.5%?

### 3. NO Side — Is 3% Premium Too Aggressive?
- The +3% NO premium combined with fee deduction makes most NO trades very hard to enter
- Model probability floor at 0.05 caps NO side edge at extreme prices
- **Check**: how many NO trades did v8 execute vs v7?
- **Check**: of the v7 NO trades that would now be rejected by v8 filters, what was their WR?
- **Action if profitable NO trades are being filtered**: reduce to `NO_SIDE_EDGE_PREMIUM = 0.02`

### 4. Near-Certain Upper Threshold (0.88)
- Still at 0.88 — the $20.39 BNB loss at 0.86 entry shows risk
- At 0.86 entry you need 86% WR to break even, margin is razor thin
- **Check**: what is v8 WR at 0.83-0.88 entry vs 0.75-0.83?
- **Action if 0.83-0.88 WR <80%**: lower `CRYPTO_NEAR_CERTAIN_UPPER` to 0.85 or add 9% edge floor for 0.80-0.88

### 5. High Entry Edge Floor Gap
- 0.70-0.80 entries require 7% min edge (price-dependent floor)
- 0.80-0.88 entries use default (5% or coin override) — no extra floor
- **Check**: is there a WR cliff between 0.80-0.88 entries vs 0.75-0.80?
- **Action if cliff exists**: add `if 0.80 <= entry_price <= 0.88: min_edge = max(min_edge, 0.09)`

### 6. 15m Market Performance Under v8
- v7 data: 67% WR on 18 trades (too few)
- v8 tightened 15m with fee-aware edge + adaptive mode
- **Check**: does v8 produce enough 15m trades to evaluate? (need 20+ settled for `evaluate_15m_mode`)
- **Check**: if 15m WR >75% on 20+ trades, keep; if <65%, disable in v9

### 7. Risk Manager Impact
- New in v8: daily loss limit, exposure cap, consecutive loss cooldown
- **Check**: how many trades did the risk manager block? Which checks triggered?
- **Check**: review `events.jsonl` for risk_block events
- **Action if too many blocks**: tune `DAILY_MAX_LOSS` or `MAX_OPEN_EXPOSURE` upward
- **Action if zero blocks**: the limits may be too loose for live — tighten before real money

### 8. Simulation Mode Validation
- Run `TRADING_MODE=simulation` for at least 4 hours before live
- **Check**: compare paper WR vs simulation WR — the gap is how much fees/slippage cost
- **Check**: run `python analyze_simulation.py` for the full report
- **Gate**: simulation WR must be >70% and net P&L positive over 50+ trades

### 9. Per-Coin-Per-Side Performance Matrix
- BTC NO is blacklisted, but other weak segments may exist
- **Check**: build full coin x side x market_type matrix for v8 trades
- Flag any segment with <65% WR over 20+ trades
- **Action**: add to `COIN_MIN_EDGE` overrides or blacklist specific segments

### 10. Risk-Adjusted Metrics
- Raw WR and P&L don't capture risk-adjusted performance
- **Check**: compute from v8 daily returns:
  - Sharpe ratio (target >1.0 for live consideration)
  - Max drawdown % (target <25%)
  - Consecutive loss streaks (longest streak, how many >3)
  - Daily P&L variance
- These are in `analyze_simulation.py` output when running simulation mode

## Analysis Queries for v8 Data

```python
from logger import read_trades
from config import STRATEGY_VERSION

all_trades = read_trades()

# Only v8 trades
v8 = [t for t in all_trades if t.strategy_version == 8]
v8_settled = [t for t in v8 if t.status in ('won', 'lost')]
v8_wins = [t for t in v8_settled if t.status == 'won']

print(f"v8 trades: {len(v8)} total, {len(v8_settled)} settled")
print(f"v8 WR: {len(v8_wins)/len(v8_settled):.1%}" if v8_settled else "no settled trades")
print(f"v8 P&L: ${sum(t.payout - t.size for t in v8_settled):.2f}")

# 1. Signal volume: trades per hour
from datetime import datetime, timezone
if len(v8) >= 2:
    span_hours = (v8[-1].timestamp - v8[0].timestamp).total_seconds() / 3600
    print(f"v8 trades/hour: {len(v8)/span_hours:.1f}" if span_hours > 0 else "")

# 2. YES vs NO breakdown
for side in ['YES', 'NO']:
    subset = [t for t in v8_settled if t.side == side]
    wins = sum(1 for t in subset if t.status == 'won')
    print(f"  {side}: {len(subset)} trades, {wins/len(subset):.0%} WR" if subset else f"  {side}: 0 trades")

# 3. Per-coin-per-side matrix
import re
_COIN_RE = re.compile(r'^([a-z]+)-updown-', re.IGNORECASE)
coins = sorted({_COIN_RE.match(t.market_slug).group(1).upper() for t in v8_settled if _COIN_RE.match(t.market_slug)})
for coin in coins:
    for side in ['YES', 'NO']:
        subset = [t for t in v8_settled if _COIN_RE.match(t.market_slug) and _COIN_RE.match(t.market_slug).group(1).upper() == coin and t.side == side]
        if len(subset) >= 5:
            wins = sum(1 for t in subset if t.status == 'won')
            pnl = sum(t.payout - t.size for t in subset)
            flag = " *** WEAK" if wins/len(subset) < 0.65 else ""
            print(f"  {coin} {side}: {len(subset)} trades, {wins/len(subset):.0%} WR, ${pnl:+.2f}{flag}")

# 4. Entry price buckets
for lo, hi in [(0.60, 0.70), (0.70, 0.80), (0.80, 0.85), (0.85, 0.88)]:
    subset = [t for t in v8_settled if lo <= t.entry_price < hi]
    if subset:
        wins = sum(1 for t in subset if t.status == 'won')
        pnl = sum(t.payout - t.size for t in subset)
        print(f"  Entry {lo:.2f}-{hi:.2f}: {len(subset)} trades, {wins/len(subset):.0%} WR, ${pnl:+.2f}")

# 5. Fee impact (v8 trades with fees > 0)
fee_trades = [t for t in v8 if t.fees > 0]
if fee_trades:
    avg_fee = sum(t.fees for t in fee_trades) / len(fee_trades)
    print(f"  Avg fee: ${avg_fee:.4f} over {len(fee_trades)} trades")

# 6. 5m vs 15m
for mt in ['5m', '15m']:
    subset = [t for t in v8_settled if t.market_type == mt]
    if subset:
        wins = sum(1 for t in subset if t.status == 'won')
        pnl = sum(t.payout - t.size for t in subset)
        print(f"  {mt}: {len(subset)} trades, {wins/len(subset):.0%} WR, ${pnl:+.2f}")
```

## Go-Live Decision Matrix (updated for v8)

| Finding | Action |
|---------|--------|
| v8 WR >80% on 100+ trades | Strong signal — proceed to simulation mode |
| v8 WR 70-80% on 100+ trades | Acceptable — proceed to simulation cautiously |
| v8 WR <70% | Do NOT go live — investigate which filter is too loose |
| v8 signal volume <50% of v7 | Filters too aggressive — relax NO premium or fee threshold |
| NO side still <70% WR after premium | Increase `NO_SIDE_EDGE_PREMIUM` to 0.04 or blacklist more segments |
| 0.83-0.88 entry WR <80% | Add edge floor for 0.80-0.88 range |
| 15m WR <65% on 20+ trades | Disable 15m in v9 |
| Risk manager blocked >20% of signals | Limits too tight — tune upward |
| Risk manager blocked 0% | Limits too loose — tighten before live |
| Simulation WR >70%, net P&L positive on 50+ trades | Ready for Stage 1 live ($20, $1-5 bets) |
| Sharpe <1.0 on daily returns | Not ready — need better risk-adjusted returns |
| Max drawdown >25% | Reduce bet sizing further before live |
