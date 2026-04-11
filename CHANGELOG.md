# Config Changelog

Track all configuration changes with rationale and data backing.

## 2026-04-11 — BTC edge threshold raised to 15%

**Change:** `COIN_MIN_EDGE["BTC"]` 0.10 → 0.15

**Rationale:** 368-trade analysis shows BTC is the worst performer:
- 60% WR (vs 76.6% overall), +18.4% ROI (vs 44.3% overall)
- BTC NO side: 29 trades, 48.3% WR, -$3.97 P&L — actively losing money
- BTC YES side: 21 trades, 76.2% WR, +$14.42 — fine but small
- Most efficiently priced asset on Polymarket, needs larger edge to overcome

**Expected impact:** Fewer BTC trades, cutting the losing NO-side entries. Should improve overall ROI by ~5 points with minimal P&L loss (~$10 on $230 total).

## 2026-04-11 — Updated COIN_MIN_EDGE comments with latest stats

**Change:** Refreshed inline comments with data from 368-trade sample.

**Asset rankings (for reference):**
| Asset | Trades | WR    | P&L     | ROI    |
|-------|--------|-------|---------|--------|
| XRP   | 66     | 84.8% | +$68.29 | +67.3% |
| SOL   | 62     | 79.0% | +$50.62 | +55.4% |
| BNB   | 52     | 78.8% | +$36.46 | +48.3% |
| DOGE  | 45     | 77.8% | +$31.02 | +45.3% |
| ETH   | 50     | 72.0% | +$22.57 | +39.1% |
| HYPE  | 43     | 81.4% | +$18.79 | +27.1% |
| BTC   | 50     | 60.0% | +$10.45 | +18.4% |
