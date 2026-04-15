# CODEX.md

This file provides guidance to Codex when working with code in this repository.

## Project Overview

Polymarket trading bot with 3 execution modes:
- **paper**: instant fill, zero fees
- **simulation**: simulated fills with slippage, fees, partial fills, and rejections
- **live**: real CLOB order placement via `py-clob-client` with an explicit confirmation gate in `main.py`

The bot currently focuses on crypto up/down interval markets and keeps richer monitoring, logging, and replay support around every decision. The primary live path is deterministic and crypto-first, while shadow and research paths remain available for analytics and experimentation.

Trades are persisted to CSV and JSONL. Every candidate trade is gated by `RiskManager` before execution. A Rich dashboard and a lightweight web monitor expose balance, signals, open orders, and recent activity in real time.

## Tech Stack

- Python `>=3.12` from `pyproject.toml`
- Synchronous architecture with a background engine thread plus main-thread dashboard
- Main dependencies: `requests`, `groq`, `feedparser`, `rich`, `python-dotenv`, `py-clob-client`, `web3`
- Dev/test: `pytest`

## Commands

```powershell
# Setup (Windows PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Run (default = paper)
python main.py
$env:TRADING_MODE="simulation"; python main.py
$env:TRADING_MODE="live"; python main.py

# Tests
python -m pytest
python -m pytest tests/test_engine.py
python -m pytest -k test_name

# Analysis
python analyze_simulation.py
```

```bash
# Setup (macOS/Linux)
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run
python main.py
TRADING_MODE=simulation python main.py
TRADING_MODE=live python main.py
```

## Architecture

Engine loop runs in a background thread. Dashboard runs on the main thread. A local HTTP monitor also serves `ticker3.html` plus `/api/monitor`.

- Tick cadence: base `TICK_INTERVAL = 10s`, adaptively reduced to `5s` near expiry
- Order of operations in `Engine.tick()`: fetch markets -> detect up/down markets -> warm active coin prices -> analyze signals -> risk gate -> execute -> settle pending
- Web monitor: `monitor_server.py` serves `ticker3.html`, `ticker3.css`, `ticker3.js`, and `/api/monitor`

Data flow:
- `market_fetcher.py` produces `Market` and `UpDownMarket`
- `price_feed.py` + `state_cache.py` maintain reference price history and candle-style features
- `level_analyzer.py` produces `Signal` with regime, alignment, pricing, and confidence metadata
- `risk_manager.py` allows or blocks trade
- `order_executor.py` executes and returns `OrderResult`
- `engine.py` records `Trade`, reconciles open orders, and emits monitor snapshots
- `logger.py` writes CSV and `trade_logger.py` writes JSONL trade and event streams

## Key Modules

- `config.py`
  - Central config and dataclasses: `Market`, `UpDownMarket`, `Article`, `Signal`, `Trade`, `OrderResult`, `OpenOrder`, `RiskConfig`
  - `TRADING_MODE` controls mode selection
  - `CODEX_VERSION` is currently **1.3**
  - `STRATEGY_VERSION` is currently **13**

- `main.py`
  - Chooses executor from `TRADING_MODE`
  - Builds mode-specific `RiskConfig`
  - In live mode requires `POLYMARKET_PRIVATE_KEY` and explicit `yes` confirmation
  - Starts the Rich dashboard and web monitor

- `level_analyzer.py`
  - Core v13 deterministic up/down logic with actual-move-first routing
  - Uses trusted window-open anchors plus interval OHLC, interval return, late `60s` and `20s` returns, body ratio, wick imbalance
  - Routes setups into `strong`, `flat`, or `mid` actual-move regimes
  - Strong moves are follow-or-skip only; flat windows stay shadow-only and mid windows skip
  - Records `high_prob_shadow` for `0.78-0.90` strong-move setups instead of promoting them to live execution

- `state_cache.py`
  - Stores market-book state and reference price history
  - Computes rolling returns, z-scores, OHLC windows, and candle features

- `price_feed.py`
  - Price source chain: OKX -> Bybit -> CoinGecko
  - Batch CoinGecko fetch for active coins
  - Exposes enriched reference snapshots for analyzers and live-order drift checks

- `order_executor.py`
  - `PaperExecutor`: instant fills, no fees
  - `SimulationExecutor`: dynamic taker fees, adverse slippage, partial fills, simulated rejections
  - `LiveExecutor`: reconciliation-aware maker-style CLOB execution

- `risk_manager.py`
  - Guards every trade with daily loss, exposure, drawdown, cooldown, per-coin, and thesis limits
  - Simulation mode is intentionally very loose for research runs

- `engine.py`
  - Orchestrates the full loop
  - Restores history from CSV on startup
  - Reconciles open orders and settles resolved trades
  - Emits the monitor snapshot consumed by `ticker3.js`

- `logger.py` + `trade_logger.py`
  - CSV trade ledger and open-order persistence
  - JSONL trade and event streams with v12 audit fields such as candle regime and trend alignment

- `analyze_simulation.py`
  - Post-run analysis for P&L, fees, execution quality, per-coin stats, trade alignment, and price buckets

- `ticker3.html` / `ticker3.js` / `ticker3.css`
  - Mode-neutral web monitor UI
  - Shows signal board, recent trades, open orders, account pulse, and reference chart stage

## Strategy Versioning

Each trade stores `strategy_version`. Analytics are scoped to `STRATEGY_VERSION` only, preventing leakage from older parameter sets.

Current release: **Codex 1.3**.  
Current patch version: **v13**.

When strategy parameters change, bump `STRATEGY_VERSION` so evaluation remains patch-pure.

## Current Timing And Risk Highlights

- 5m trade window: `MIN_SECONDS_TO_TRADE_5M=8`, `MAX_SECONDS_TO_CLOSE_5M=30`
- 15m trade window: `MIN_SECONDS_TO_TRADE_15M=25`, `MAX_SECONDS_TO_CLOSE_15M=480`
- Default strategy modes:
  - 5m up/down: `live`
  - 15m up/down: `shadow`
  - BTC `NO`: `shadow`
  - arbitrage: `disabled`
- `MAX_BETS_PER_CYCLE = 5` in normal operation
- Simulation override: `SIMULATION_MAX_BETS_PER_CYCLE = 1_000_000`

Simulation defaults are intentionally research-friendly:
- `SIMULATION_STARTING_BALANCE = 10000.0`
- exposure/loss/cooldown caps are effectively near-unbounded
- shadow-only signals are allowed to execute in simulation for data collection

## Actual-Move V13 Highlights

- Trusted exact window-open price is required for candidate/live routing
- Strong actual-move thresholds:
  - 5m actual return: `>= 0.30%`
  - 15m actual return: `>= 0.50%`
- Flat actual-move thresholds:
  - 5m actual return: `<= 0.08%`
  - 15m actual return: `<= 0.12%`
- Strong-move confirmation requires aligned `60s` and `20s` returns, `body_ratio >= 0.60`, fresh book age, and tight spread
- Strong actual move may only follow the move direction or skip; opposite-side candidate trades are blocked by design
- `0.78-0.90` strong-move entries are tracked as `high_prob_shadow`
- Missing trusted window-open anchor causes `missing_exact_open` skip
- Confidence caps:
  - strong-trend setups cap at `0.90`
  - mixed or uncertain setups cap at `0.75`
- Sizing:
  - strong follow-trend: `1.25x`
  - mixed: `0.5x`
  - uncertain: `1.0x`
  - strong-trend contrarian: blocked
- Extreme selected-side prices (`>= 0.97` or `<= 0.03`) are shadow-only, not skipped

## Environment Variables

From `.env.example` and current config:
- `TRADING_MODE` - `paper` (default), `simulation`, or `live`
- `SIMULATION_STARTING_BALANCE` - simulation bankroll, default `10000.0`
- `LIVE_BALANCE` - starting balance in live mode, default `5.0`
- `POLYMARKET_PRIVATE_KEY` - required for live execution
- `POLYMARKET_FUNDER` - optional proxy/funder address for signature type 2
- `GROQ_API_KEY` - retained for research tooling
- `UPDOWN_5M_STRATEGY_MODE`, `UPDOWN_15M_STRATEGY_MODE`, `BTC_NO_STRATEGY_MODE`
- `MONITOR_HOST`, `MONITOR_PORT` - web monitor bind settings

## Known Issues And Operational Notes

- `CLAUDE.md` exists as a sibling guidance file, but some of its values are stale relative to current v12 code
- Any `Engine` attribute consumed by dashboard or monitor must be initialized in `Engine.__init__`
- Tests patch out a lot of persistence and logging side effects in `tests/test_engine.py`
- On macOS/Python 3.14, SSL verification can fail for some exchange endpoints; `price_feed.py` falls back accordingly
- Live trading is implemented, but operational safety still depends on wallet setup, API permissions, liquidity, and careful rollout

## Recent Fixes

- 2026-04-15: Added v12 candle-aware deterministic crypto engine with regime classification, side-aware reasons, and stronger trade audit fields
- 2026-04-15: Extended CSV and JSONL trade persistence with regime and candle-alignment metadata
- 2026-04-15: Relaxed simulation research mode so exposure, daily loss, and shadow-only gates no longer choke high-volume sim runs
- 2026-04-15: Updated `ticker3` web monitor copy and badges to be mode-neutral and simulation-friendly
- 2026-04-15: Added v13 actual-move-first routing with trusted window-open anchors, follow-or-skip strong-move logic, and dumb-loss audit reporting
