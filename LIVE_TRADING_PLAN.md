# Live Trading Transition Plan

## Status: WAITING FOR 2-DAY DATA (started 2026-04-11)

**Next step:** Re-analyze `trades.csv` after 2026-04-13 with ~700+ trades, then implement.

---

## Trade Analysis (451 executed trades, 2026-04-10 to 2026-04-11)

### Overall
| Metric | Value |
|--------|-------|
| Total executed trades | 451 |
| Win rate | 78.5% |
| Net P&L | +$59.83 |
| ROI on risked | 4.9% |
| Total risked | $1,219.73 |
| Avg trade size | $2.70 |
| Avg profit/trade | $0.13 |

### By Coin
| Coin | Trades | WR | P&L | ROI |
|------|--------|----|-----|-----|
| BNB | 70 | 84% | +$29.78 | Best |
| XRP | 76 | 82% | +$12.53 | |
| HYPE | 51 | 82% | -$2.05 | High WR but slightly negative |
| SOL | 78 | 81% | +$18.47 | |
| DOGE | 60 | 78% | +$5.24 | |
| ETH | 60 | 75% | +$3.03 | Marginal |
| **BTC** | **56** | **64%** | **-$7.17** | **Worst — money loser** |

### By Side
| Side | Trades | WR | P&L |
|------|--------|----|-----|
| YES | 211 | 82% | Positive |
| NO | 240 | 75% | Weaker |

### By Market Type
| Type | Trades | WR | P&L |
|------|--------|----|-----|
| 5m | 433 | 79% | +$62.75 |
| 15m | 18 | 67% | -$2.92 |

### By Entry Price
| Price Range | Trades | WR | P&L |
|-------------|--------|----|-----|
| 0.50-0.60 | 90 | 58% | +$9.97 |
| 0.60-0.70 | 47 | 70% | +$7.66 |
| 0.70-0.80 | 103 | 82% | +$17.16 |
| 0.80-0.90 | 211 | 88% | +$25.04 |

### By Seconds to Close
| Window | Trades | WR | P&L | ROI |
|--------|--------|----|-----|-----|
| 0-15s | 12 | 83% | +$7.41 | Best ROI |
| 16-30s | 102 | 86% | +$18.30 | Sweet spot |
| 31-60s | 139 | 88% | +$25.85 | Sweet spot |
| 61-90s | 2 | 100% | +$0.53 | Too few |
| **91s+** | **196** | **67%** | **+$7.74** | **Weak** |

### Chronological Performance (strategy improving over time)
| Batch | WR | P&L | Period |
|-------|----|-----|--------|
| Trades 1-50 | 70% | +$0.32 | Early (no tuning) |
| Trades 101-150 | 76% | +$22.83 | |
| Trades 251-300 | 86% | +$4.19 | |
| Trades 301-350 | 96% | +$26.82 | Best batch |
| Trades 401-451 | 92% | +$26.56 | Recent |

---

## Key Findings

1. **BTC is a money loser** — 64% WR, -$7.17. BTC NO specifically is worst segment (~48% WR historically).
2. **NO side is weaker** — YES: 82% WR, NO: 75% WR. Require extra edge for NO trades.
3. **Entry price <0.60 has no real edge** — 58% WR across 90 trades. Already tightened skip band to 0.40-0.60.
4. **91s+ entries are weak** — 67% WR across 196 trades. Already tightened 5m window to 30s.
5. **Higher edge = dramatically better** — 7-10% edge historically shows 94%+ WR.
6. **15m markets underperform** — 67% WR vs 79% for 5m. Now supported but need separate tuning.
7. **Strategy is improving** — early batches 70% WR, recent batches 92-96% WR.
8. **Max drawdown still too high for real money** — need daily loss limits and smaller bet sizing.

---

## Already Applied (2026-04-11)

These filter changes were applied based on the 451-trade analysis:

| Filter | Old Value | New Value | Rationale |
|--------|-----------|-----------|-----------|
| MAX_SECONDS_TO_CLOSE_5M | 45s (leaked to 120s) | 30s strict | 91s+ = 67% WR |
| CRYPTO_SKIP_BAND | 0.38-0.62 | 0.40-0.60 | <0.60 entry = 58% WR |
| BTC COIN_MIN_EDGE | 0.07 | 0.10 | 64% WR, -$7.17 |
| 15m market support | Filtered out | Active (separate timing) | Expand opportunities |
| Stale data guard | None | Skip if price >30s old | Real-money readiness |
| Per-interval timing | Single window | 5m: 5-30s, 15m: 10-120s | Appropriate per type |

## Proposed Filter Changes (validate with 2-day data)

| Filter | Current | Proposed | Rationale |
|--------|---------|----------|-----------|
| BTC NO side | Allowed (high edge) | Blacklisted | Historically ~48% WR on NO side |
| NO side edge premium | 0% | +3% extra edge required | NO side is 75% WR vs 82% YES |
| MIN_EDGE | 0.05 | 0.05 (half size) / 0.07 (full size) | 7%+ edge = 94.4% WR |
| BET_FRACTION | 0.15 | 0.05 (quarter-Kelly) | Reduce drawdown for real money |
| MAX_BET | $50 | $10 (initial live) | Capital preservation |
| Tick rate in window | 5s adaptive | 2-3s when <30s to close | More entry opportunities in sweet spot |

**Expected impact:** WR from 78.5% → 85%+, ROI from 4.9% → 10%+, max drawdown < 25%.

---

## Implementation Plan

### New Modules
| Module | Purpose | Est. Lines |
|--------|---------|-----------|
| `order_executor.py` | PaperExecutor, SimulationExecutor, LiveExecutor abstraction | ~150 |
| `risk_manager.py` | Daily loss limit, exposure cap, consecutive loss pause | ~80 |
| `trade_logger.py` | JSONL detailed logging (fills, slippage, latency) | ~60 |
| `analyze_simulation.py` | Post-simulation analysis + recommendations | ~150 |

### Modified Files
| File | Changes |
|------|---------|
| `config.py` | Add TRADING_MODE, risk constants, OrderResult dataclass |
| `engine.py` | Replace execute_paper_trade → execute_trade, integrate risk manager + executor |
| `main.py` | Mode selection, live confirmation prompt |
| `dashboard.py` | Mode indicator, risk status in header |
| `.env.example` | Add POLYMARKET_PRIVATE_KEY, TRADING_MODE |
| `pyproject.toml` | Add py-clob-client, web3 deps |

### Execution Architecture
```
Signal → RiskManager.check_trade_allowed()
       → OrderExecutor.place_order()
           ├─ PaperExecutor:      instant fill at displayed price
           ├─ SimulationExecutor: paper fill + real order book validation
           └─ LiveExecutor:       CLOB market order via py-clob-client
       → Trade logged to CSV + JSONL
       → RiskManager.record_trade()
```

### Adaptive Tick Rate
```
Outside 30s window: 10s ticks (nothing actionable)
Inside 30s window:  2-3s ticks (sweet spot, maximize entry opportunities)
```

**Rationale:** At 10s ticks, a 30s window gives only ~3 looks at a market. At 2-3s ticks, you get 10-15 looks, catching more favorable price movements during the high-WR sweet spot.

**Rate limit considerations:**
- CoinGecko free tier: 10-30 calls/min — at 2s ticks this burns through fast. Either fix OKX/Bybit SSL, get a CoinGecko key, or batch-warm once at window entry and only refresh Gamma prices on subsequent ticks.
- Polymarket Gamma API: check rate limit headers before implementing.
- Mitigation: warm prices once at 30s mark, then only poll Gamma market prices at 2-3s intervals (skip CEX calls since momentum is already established from the initial warm).

### Risk Controls (for real money)
```python
DAILY_MAX_LOSS = 10.0         # stop if daily losses > $10
MAX_OPEN_EXPOSURE = 25.0      # max $ at risk across pending trades
MAX_CONSECUTIVE_LOSSES = 5    # pause 1 cycle after 5 losses in a row
MAX_BET = 10.0                # cap per trade
SLIPPAGE_BUFFER = 0.02        # add 2% to MIN_EDGE for live orders
```

### Scaling Plan
| Stage | Timeline | Bankroll | Bet Size | Gate |
|-------|----------|----------|----------|------|
| 1. Validation | Week 1-2 | $20 | $1.00 | Real WR > 75%, slippage < 2% |
| 2. Confidence | Week 3-4 | $100 | $5.00 | Sharpe > 1.0 on daily returns |
| 3. Scale | Month 2+ | $200-500 | $10-20 | 500+ real trades profitable |
| 4. Steady state | Month 3+ | $500-1000 | $25-50 | Consistent monthly profit |

---

## Polymarket CLOB API Research

### Authentication
- Two-tier: EIP-712 signing (L1) + HMAC (L2)
- SDK: `py-clob-client` handles all signing
- EOA wallet (type 0) with token allowances on 3 exchange contracts
- **Must complete one trade on polymarket.com UI before API works**

### Order Mechanics
- All orders are limit orders internally (market orders = aggressive limits)
- Prices must match tick size (0.01 for most markets)
- Dynamic taker fees: up to 1.8% at $0.50, lower at extremes
- Makers pay zero fees + receive 20-25% rebate
- Heartbeat every 5s required for open orders (not relevant for market orders)

### Common Pitfalls
1. Wrong tick size → silent rejection
2. Forgetting token allowances (EOA)
3. Proxy wallet not deployed (need 1 UI trade first)
4. Failed requests count against rate limits
5. Balance stacking: orders must sum to <= balance per market

### Go-Live Checklist
1. [ ] Fund Polygon wallet with USDC.e ($20)
2. [ ] Log into polymarket.com with same wallet
3. [ ] Complete one manual trade on UI
4. [ ] Set token allowances (SDK helper)
5. [ ] Run 2-day simulation mode
6. [ ] Analyze simulation results
7. [ ] Set TRADING_MODE=live, MAX_BET=5.0
8. [ ] Monitor first 2 hours continuously
9. [ ] After 24h: analyze live trades
10. [ ] If metrics hold: increase MAX_BET=10.0

---

## Timeline

- **2026-04-11:** Plan written, 15m support + reliability guards + data-driven tuning applied
- **2026-04-12:** Paper trading continues with new filters (collecting 2-day data)
- **2026-04-13:** Re-analyze with 2-day dataset (~700+ trades), validate proposed filters
- **2026-04-13-14:** Implement remaining filters (BTC NO blacklist, NO edge premium, tick rate) + new modules (order_executor, risk_manager)
- **2026-04-14-16:** Run 2-day simulation mode
- **2026-04-16:** Analyze simulation, decide go/no-go
- **2026-04-17+:** Go live with $50 if simulation passes
