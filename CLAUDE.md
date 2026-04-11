# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Polymarket paper trading bot. Monitors Polymarket prediction markets using two strategies:
- **Crypto UpDown markets**: Trades 5-minute crypto up/down binary markets (e.g., `btc-updown-5m-*`) by detecting market-implied direction and following the trend with a confidence boost
- **Resolution arbitrage**: Matches news headlines to markets via Groq LLM to find mispriced outcomes

All trades are paper-only, logged to CSV. Rich terminal dashboard for monitoring.

## Tech Stack

Python 3.14, synchronous with threading. Key dependencies: requests, groq, feedparser, rich, python-dotenv, pytest.

## Commands

```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run
python main.py

# Tests
python -m pytest                    # all tests
python -m pytest tests/test_foo.py  # single file
python -m pytest -k "test_name"     # single test
```

## Architecture

Synchronous engine loop with threading: engine runs in a background thread (10s tick, 5min news poll), Rich dashboard runs on the main thread.

**Data flow:** `market_fetcher.py` and `news_fetcher.py` produce `Market` and `Article` objects → strategies (`level_analyzer.py`, `arbitrage_analyzer.py`) produce `Signal` objects → `engine.py` converts signals to `Trade` objects → `logger.py` writes to CSV.

**Key modules:**
- `config.py` — All constants, API URLs, thresholds, and dataclass models (Market, UpDownMarket, Article, Signal, Trade)
- `price_feed.py` — OKX primary, Bybit fallback, CoinGecko fallback for crypto prices
- `market_fetcher.py` — Polymarket Gamma API with time-windowed fetching (markets closing within 5-45s), slug-based updown detection
- `news_fetcher.py` — Google News RSS via feedparser
- `arbitrage_analyzer.py` — Calls Groq LLM to match headlines to markets
- `level_analyzer.py` — Analyzes crypto updown markets using market-implied probability
- `engine.py` — Main loop orchestrating fetchers → analyzers → trade execution, with activity logging
- `dashboard.py` — Rich Live terminal UI with updown markets table, trades table, and activity log
- `main.py` — Entry point, starts engine thread, runs dashboard, handles Ctrl+C

## Environment Variables

Requires `.env` file (see `.env.example`):
- `GROQ_API_KEY` — for Groq LLM headline matching

## Known Issues

- OKX and Bybit APIs have SSL cert issues on Python 3.14/macOS — price_feed falls back to CoinGecko
- Crypto updown markets cycle every 5 minutes; the bot only targets the final 45 seconds of each cycle (5-45s window, trades placed with ≥15s remaining)
