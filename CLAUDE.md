# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Polymarket trading bot with 3 execution modes:
- **paper**: instant fill, zero fees (default)
- **simulation**: simulated fills with slippage/fees/partial fills/rejections
- **live**: real CLOB order placement via `py-clob-client` (with confirmation gate in `main.py`)

The bot monitors Polymarket markets using two strategies:
- **Crypto UpDown markets**: 5m and 15m crypto up/down binaries, using market-implied direction + CEX momentum confirmation + fee-aware edge filtering
- **Resolution arbitrage**: maps Google News headlines to open markets with Groq, generating high-confidence factual resolution signals

Trades are persisted to CSV and JSONL. Every candidate trade is gated by `RiskManager` before execution. A Rich dashboard displays strategy, risk, and activity in real time.

## Tech Stack

- Python `>=3.12` (from `pyproject.toml`)
- Synchronous architecture with a background engine thread + main-thread dashboard
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

Engine loop runs in a background thread. Dashboard runs on the main thread.

- Tick cadence: base `TICK_INTERVAL = 10s`, adaptively reduced to `5s` near expiry
- News poll cadence: `NEWS_POLL_INTERVAL = 300s`
- Order of operations in `Engine.tick()`: fetch markets -> detect updown markets -> warm active coin prices -> analyze signals -> risk gate -> execute -> settle pending -> news arbitrage check

Data flow:
- `market_fetcher.py` + `news_fetcher.py` produce `Market` and `Article`
- `level_analyzer.py` / `arbitrage_analyzer.py` produce `Signal`
- `risk_manager.py` allows/blocks trade
- `order_executor.py` executes order and returns `OrderResult`
- `engine.py` records `Trade`
- `logger.py` writes CSV and `trade_logger.py` writes JSONL trade/events

## Key Modules

- `config.py`
	- Central config + dataclasses: `Market`, `UpDownMarket`, `Article`, `Signal`, `Trade`, `OrderResult`, `RiskConfig`
	- `TRADING_MODE` controls mode selection
	- `STRATEGY_VERSION` is currently **9**

- `main.py`
	- Chooses executor from `TRADING_MODE`
	- In live mode requires `POLYMARKET_PRIVATE_KEY` and explicit `yes` confirmation
	- Applies live bet-size overrides (`LIVE_MAX_BET`, `LIVE_MIN_BET`)

- `order_executor.py`
	- `PaperExecutor`: instant fills, no fees
	- `SimulationExecutor`: dynamic taker fees + adverse slippage + partial fills + simulated rejections
	- `LiveExecutor`: posts real CLOB orders, retries FOK full-fill failures with GTC fallback

- `risk_manager.py`
	- Guards every trade with: kill switch, daily loss limit, open exposure cap, consecutive-loss cooldown, per-coin exposure cap
	- Auto-activates kill switch if daily losses hit 2x daily limit

- `market_fetcher.py`
	- Fetches active Gamma markets in a configured end-date window
	- Extracts UpDown markets by slug regex: `{coin}-updown-{interval}m-{id}`
	- Applies per-interval close-time windows
	- Excludes esports-style markets by slug/question regex

- `level_analyzer.py`
	- Core updown decision logic using implied probability + momentum confirmation
	- Rejects stale price data
	- Fee-aware minimum edge filtering
	- BTC `NO` blacklist support
	- `NO` side minimum-edge premium is currently **+1%** (`NO_SIDE_EDGE_PREMIUM = 0.01`)

- `strategy_eval.py`
	- Patch-scoped analytics (version-filtered)
	- Computes win rate, profit factor, net/avg pnl, expectancy
	- Dynamically enables/tightens/disables 15m mode (`evaluate_15m_mode`)

- `engine.py`
	- Orchestrates full trading loop
	- Restores state from CSV on startup
	- Logs activity for dashboard
	- Settles resolved markets and updates risk state

- `price_feed.py`
	- Price source chain: OKX -> Bybit -> CoinGecko
	- Batch CoinGecko fetch for active coins
	- Keeps short in-memory price history for momentum and staleness checks

- `dashboard.py`
	- Real-time Rich UI: mode, balance, patch stats, 15m mode state, risk panel, per-coin stats, markets, trades, activity log

- `logger.py` + `trade_logger.py`
	- CSV trade ledger + JSONL structured events (`trades.jsonl`, `events.jsonl`)

- `analyze_simulation.py`
	- Post-run analysis for P&L, fees, execution quality, per-coin stats, risk-block categories, and go/no-go recommendation

## Strategy Versioning

Each trade stores `strategy_version`. Analytics are scoped to `STRATEGY_VERSION` only, preventing leakage from older parameter sets.

Current version: **v9**.

When strategy parameters change (timing windows, edge thresholds, confidence boosts, etc.), bump `STRATEGY_VERSION` so evaluation remains patch-pure.

## Current Timing and Risk Highlights

- 5m filter window: `MIN_SECONDS_TO_CLOSE_5M=5`, `MAX_SECONDS_TO_CLOSE_5M=35`
- 15m filter window: `MIN_SECONDS_TO_CLOSE_15M=10`, `MAX_SECONDS_TO_CLOSE_15M=20`
- 15m adaptive mode uses patch performance thresholds and can tighten (not just on/off)
- `MAX_BETS_PER_CYCLE = 5`
- Default start balance:
	- live: `LIVE_BALANCE` env var (default 5.0)
	- non-live: 11.0

## Environment Variables

From `.env.example`:
- `GROQ_API_KEY` - required for news arbitrage matching
- `TRADING_MODE` - `paper` (default), `simulation`, or `live`
- `POLYMARKET_PRIVATE_KEY` - required for live execution
- `POLYMARKET_FUNDER` - optional proxy/funder address for signature type 2
- `LIVE_BALANCE` - starting balance in live mode (default `5.0`)

## Known Issues and Operational Notes

- On macOS/Python 3.14, SSL verification can fail for some CEX endpoints; `price_feed.py` falls back to CoinGecko and disables TLS verification only on Darwin.
- Any `Engine` attribute rendered by dashboard must be initialized in `Engine.__init__`, because dashboard reads immediately.
- Engine tests intentionally mock version-eval and JSONL logging plumbing via the autouse fixture in `tests/test_engine.py`.
- Live trading path is implemented, but production safety still depends on wallet setup, API permissions, liquidity conditions, and careful manual rollout.

## Recent Fixes

- 2026-04-13: Added esports exclusion filter in `market_fetcher.py` (question/slug regex blocklist).
- 2026-04-13: Hardened `LiveExecutor` FOK->GTC fallback to catch Polymarket full-fill rejections surfaced under either `errorMsg`, `error`, or `PolyApiException`, and added a small-order guard so tiny signals do not get auto-oversized into a minimum lot.
