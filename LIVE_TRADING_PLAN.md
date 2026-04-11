# Live Trading Transition Plan

## Status: WAITING FOR 2-DAY DATA (started 2026-04-11)

**Next step:** Re-analyze `trades.csv` after 2026-04-13 with ~700+ trades, then implement.

---

## Trade Analysis (370 trades, 2026-04-10 — 1 day)

### Overall
| Metric | Value |
|--------|-------|
| Total trades | 370 |
| Win rate | 76.6% |
| Net P&L | +$28.24 |
| ROI on risked | 3.9% |
| Total risked | $730.73 |
| Balance | $20.00 → $63.46 |
| Max drawdown | $29.73 (57.2%) |
| Max consecutive losses | 13 |

### By Coin
| Coin | Trades | WR | P&L | ROI |
|------|--------|----|-----|-----|
| XRP | 66 | 84.8% | +$29.70 | +21.2% |
| SOL | 62 | 79.0% | +$15.84 | +12.6% |
| BNB | 52 | 78.8% | +$8.86 | +8.6% |
| DOGE | 45 | 77.8% | +$6.44 | +6.9% |
| HYPE | 43 | 81.4% | +$0.14 | +0.2% |
| ETH | 50 | 72.0% | -$3.69 | -4.4% |
| **BTC** | **50** | **60.0%** | **-$13.83** | **-17.0%** |

### By Side
| Side | Trades | WR | P&L | ROI |
|------|--------|----|-----|-----|
| YES | 165 | 81.2% | +$50.69 | +16.0% |
| NO | 203 | 72.9% | -$7.23 | -1.8% |

### Biggest Losers (Coin x Side)
| Segment | Trades | WR | P&L |
|---------|--------|----|-----|
| BTC NO | 29 | 48.3% | -$18.42 |
| ETH NO | 27 | 66.7% | -$9.42 |
| HYPE NO | 24 | 75.0% | -$6.08 |
| BNB NO | 24 | 70.8% | -$2.10 |

### By Entry Price
| Price Range | Trades | WR | P&L | ROI |
|-------------|--------|----|-----|-----|
| 0.50-0.62 | 99 | 54.5% | +$2.31 | +1.4% |
| 0.62-0.75 | 78 | 82.1% | +$25.46 | +17.5% |
| 0.75-0.88 | 191 | 85.9% | +$15.69 | +3.9% |

### By Seconds to Close
| Window | Trades | WR | P&L | ROI |
|--------|--------|----|-----|-----|
| 5-20s | 14 | 85.7% | +$3.79 | +10.3% |
| 20-35s | 48 | 87.5% | +$15.39 | +12.4% |
| 35-50s | 65 | 87.7% | +$12.27 | +8.1% |
| 50-80s | 43 | 88.4% | +$3.74 | +5.2% |
| **80-120s** | **198** | **67.2%** | **+$8.27** | **+2.5%** |

### By Edge
| Edge | Trades | WR | P&L | ROI |
|------|--------|----|-----|-----|
| 5-7% | 324 | 74.4% | +$34.72 | +5.8% |
| 7-10% | 36 | 94.4% | +$8.25 | +7.8% |

---

## Key Findings

1. **BTC NO is a money pit** — 48.3% WR, -$18.42. Must blacklist.
2. **NO side overall is negative** — YES: +$50.69, NO: -$7.23. Require extra edge for NO trades.
3. **Entry price 0.50-0.62 has no edge** — 54.5% WR across 99 trades. Widen skip band.
4. **80-120s entries are weak** — 67.2% WR (half the dataset). The 20-50s sweet spot is 87%+ WR.
5. **Higher edge = dramatically better** — 7-10% edge: 94.4% WR vs 74.4% at 5-7%.
6. **57% max drawdown is unacceptable for real money** — need daily loss limits.

---

## Proposed Filter Changes (validate with 2-day data)

| Filter | Current | Proposed | Rationale |
|--------|---------|----------|-----------|
| BTC NO side | Allowed | Blacklisted | 48.3% WR, -$18.42 |
| Skip band | 0.38-0.62 | 0.35-0.65 | 0.50-0.62 entry = 54.5% WR |
| Entry window | 5-45s (but 80-120s leak in) | 15-50s strict | 80-120s = 67.2% WR |
| NO side edge premium | 0% | +3% extra edge required | NO side is -1.8% ROI |
| MIN_EDGE | 0.05 | 0.05 (half size) / 0.07 (full size) | 7%+ edge = 94.4% WR |
| BET_FRACTION | 0.15 | 0.05 (quarter-Kelly) | Reduce drawdown |
| MAX_BET | $50 | $10 (initial live) | Capital preservation |

**Expected impact:** WR from 76.6% → 82%+, ROI from 3.9% → 10%+, max drawdown < 25%.

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
| 1. Validation | Week 1-2 | $50 | $2.50 | Real WR > 75%, slippage < 2% |
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
1. [ ] Fund Polygon wallet with USDC.e ($50)
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

- **2026-04-11:** Plan written, paper trading continues
- **2026-04-13:** Re-analyze with 2-day dataset (~700+ trades)
- **2026-04-13-14:** Implement filter changes + new modules
- **2026-04-14-16:** Run 2-day simulation mode
- **2026-04-16:** Analyze simulation, decide go/no-go
- **2026-04-17+:** Go live with $50 if simulation passes
