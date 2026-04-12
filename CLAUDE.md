# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Polymarket trading bot with three execution modes: paper, simulation, and live (stub). Monitors Polymarket prediction markets using two strategies:
- **Crypto UpDown markets**: Trades 5-minute and 15-minute crypto up/down binary markets by detecting market-implied direction, confirming with CEX price momentum, and applying fee-aware edge calculation
- **Resolution arbitrage**: Matches news headlines to markets via Groq LLM to find mispriced outcomes

Trades are logged to CSV + JSONL. Risk manager gates every trade. Rich terminal dashboard with risk panel for monitoring.

## Tech Stack

Python 3.14, synchronous with threading. Key dependencies: requests, groq, feedparser, rich, python-dotenv, pytest.

## Commands

```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run (default: paper mode)
python main.py                          # paper mode (instant fills, no fees)
TRADING_MODE=simulation python main.py  # simulation mode (realistic fills)
TRADING_MODE=live python main.py        # live mode (not yet implemented)

# Tests
python -m pytest                    # all tests (venv must be active)
python -m pytest tests/test_foo.py  # single file
python -m pytest -k "test_name"     # single test

# Analysis
python analyze_simulation.py        # post-simulation analysis report
```

## Architecture

Synchronous engine loop with threading: engine runs in a background thread (10s tick, 5min news poll), Rich dashboard runs on the main thread.

**Data flow:** `market_fetcher.py` and `news_fetcher.py` produce `Market` and `Article` objects → strategies (`level_analyzer.py`, `arbitrage_analyzer.py`) produce `Signal` objects → `risk_manager.py` gates the trade → `order_executor.py` fills the order → `engine.py` records `Trade` objects → `logger.py` writes to CSV, `trade_logger.py` writes to JSONL.

**Key modules:**
- `config.py` — All constants, API URLs, thresholds, and dataclass models (Market, UpDownMarket, Article, Signal, Trade, OrderResult, RiskConfig). TRADING_MODE env var controls execution mode.
- `order_executor.py` — Execution abstraction: PaperExecutor (instant fills), SimulationExecutor (fees/slippage/partial fills), LiveExecutor (stub)
- `risk_manager.py` — Trade gating: daily loss limit, open exposure cap, consecutive loss cooldown, per-coin exposure limit, global kill switch
- `price_feed.py` — OKX primary, Bybit fallback, CoinGecko fallback for crypto prices
- `market_fetcher.py` — Polymarket Gamma API with time-windowed fetching, slug-based updown detection
- `news_fetcher.py` — Google News RSS via feedparser
- `arbitrage_analyzer.py` — Calls Groq LLM to match headlines to markets
- `level_analyzer.py` — Analyzes crypto updown markets using market-implied probability. Includes BTC NO blacklist, NO side edge premium (+3%), and fee-aware edge calculation
- `strategy_eval.py` — Patch-scoped analytics evaluator; filters trades by STRATEGY_VERSION, computes win rate/profit factor/expectancy, drives adaptive 15m mode toggle
- `engine.py` — Main loop orchestrating fetchers → risk check → executor → trade logging, with activity logging. Accepts injected executor and risk_manager.
- `dashboard.py` — Rich Live terminal UI. Shows: mode indicator, header stats, strategy panel, risk panel (daily P&L, exposure, loss streak, kill switch), per-coin table, updown markets, trades, activity log
- `trade_logger.py` — JSONL structured logging for trades and risk events (alongside CSV)
- `analyze_simulation.py` — Standalone post-simulation analysis script
- `main.py` — Entry point: selects executor based on TRADING_MODE, creates risk manager, starts engine thread, runs dashboard

## Strategy Versioning

Every trade is stamped with `STRATEGY_VERSION` from `config.py` (currently v8). Bump this integer whenever you change strategy parameters (thresholds, edge values, timing windows, etc.). All analytics in `strategy_eval.py` are scoped to the current version only — old trades are ignored. This prevents historical leakage from earlier strategy versions dragging down current performance metrics.

v8 changes: BTC NO blacklist, NO side edge premium (+3%), fee-aware edge calculation, execution/risk abstraction.

15-minute market mode is no longer a static flag. `evaluate_15m_mode()` dynamically enables/tightens/disables based on current-patch 15m trade performance. When marginal, it tightens entry requirements (extra edge + confidence) instead of hard-disabling.

## Environment Variables

Requires `.env` file (see `.env.example`):
- `GROQ_API_KEY` — for Groq LLM headline matching
- `TRADING_MODE` — "paper" (default), "simulation", or "live"

## Known Issues

- OKX and Bybit APIs have SSL cert issues on Python 3.14/macOS — price_feed falls back to CoinGecko
- Crypto updown markets cycle every 5 minutes; the bot only targets the final 30 seconds of each 5m cycle and final 60s of each 15m cycle
- Any engine attribute read by `dashboard.py` must be initialized in `Engine.__init__` — the dashboard starts reading before the first tick runs
- Engine tests require `evaluate_15m_mode` and JSONL logging functions to be mocked (see `_clean_engine` fixture in `test_engine.py`)
- UpDown market slug format: `{coin}-updown-{interval}m-{id}` (e.g., `btc-updown-5m-12345`). Parsed by regex in `market_fetcher.py`, `dashboard.py`, and `risk_manager.py`
- LiveExecutor is a stub — requires py-clob-client integration, wallet setup, and at least one manual trade on polymarket.com UI
