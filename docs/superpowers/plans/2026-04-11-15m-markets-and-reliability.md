# 15-Minute Markets, Logging Improvements & Real-Money Readiness

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 15-minute market support with separate timing config, improve trade logging with market type tracking and strategy change history, and add execution reliability guards for future real-money trading.

**Architecture:** Extend existing config/engine/market_fetcher to handle 15m markets with their own timing window (separate from 5m). Add `market_type` field to Trade for tracking. Add stale-data and latency guards in the analyzer. Strategy changes are tracked via a JSON changelog file.

**Tech Stack:** Python 3.14, pytest, csv, json

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `config.py` | Modify | Add 15m timing constants, `market_type` field on Trade, strategy changelog path |
| `market_fetcher.py` | Modify | Widen time window to accommodate 15m markets |
| `engine.py` | Modify | Remove 5m-only filter, process both intervals, warm 15m coins |
| `level_analyzer.py` | Modify | Add stale-data guard, latency buffer, time-based edge scaling |
| `logger.py` | Modify | Add `market_type` column to CSV |
| `strategy_changelog.py` | Create | Record strategy parameter changes with timestamps |
| `dashboard.py` | Modify | Show market type in tables |
| `tests/test_engine.py` | Modify | Update 15m filter test, add 15m trade test |
| `tests/test_level_analyzer.py` | Modify | Add stale-data and latency tests |
| `tests/test_market_fetcher.py` | Modify | Add 15m time window test |
| `tests/test_logger.py` | Modify | Add market_type CSV round-trip test |
| `tests/test_strategy_changelog.py` | Create | Test changelog recording |

---

### Task 1: Add `market_type` Field to Trade and CSV

**Files:**
- Modify: `config.py:122-135` (Trade dataclass)
- Modify: `logger.py:7-20` (CSV_FIELDS)
- Modify: `logger.py:30-49` (log_trade)
- Modify: `logger.py:52-73` (save_trades)
- Modify: `logger.py:76-103` (read_trades)
- Modify: `tests/test_logger.py`

- [ ] **Step 1: Write failing test for market_type in CSV round-trip**

Add to `tests/test_logger.py`:

```python
def test_market_type_field_round_trip(tmp_csv):
    """Trade with market_type persists through CSV write/read."""
    from logger import log_trade, read_trades
    from config import Trade
    from datetime import datetime, timezone

    trade = Trade(
        timestamp=datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc),
        market_slug="btc-updown-15m-123",
        question="BTC Up or Down?",
        strategy="updown",
        side="YES",
        entry_price=0.75,
        size=2.00,
        confidence=0.80,
        reason="test reason",
        market_type="15m",
    )
    log_trade(trade, path=tmp_csv)
    trades = read_trades(path=tmp_csv)
    assert len(trades) == 1
    assert trades[0].market_type == "15m"


def test_market_type_defaults_to_5m(tmp_csv):
    """Old CSV rows without market_type default to '5m'."""
    from logger import read_trades
    import csv

    # Write a row without the market_type column
    with open(tmp_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "market_slug", "question", "strategy", "side",
            "entry_price", "size", "confidence", "reason", "status", "payout", "end_date",
        ])
        writer.writerow([
            "2026-04-10T12:00:00+00:00", "btc-updown-5m-123", "BTC?", "updown", "YES",
            "0.75", "2.00", "0.80", "reason", "won", "2.67", "2026-04-10T12:05:00+00:00",
        ])

    trades = read_trades(path=tmp_csv)
    assert len(trades) == 1
    assert trades[0].market_type == "5m"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_logger.py::test_market_type_field_round_trip tests/test_logger.py::test_market_type_defaults_to_5m -v`
Expected: FAIL — `Trade.__init__() got an unexpected keyword argument 'market_type'`

- [ ] **Step 3: Add `market_type` field to Trade dataclass**

In `config.py`, add after the `end_date` field (line ~135):

```python
    market_type: str = "5m"    # "5m" or "15m"
```

- [ ] **Step 4: Add `market_type` to CSV_FIELDS and log/read functions**

In `logger.py`, update `CSV_FIELDS` to include `"market_type"` after `"end_date"`:

```python
CSV_FIELDS = [
    "timestamp",
    "market_slug",
    "question",
    "strategy",
    "side",
    "entry_price",
    "size",
    "confidence",
    "reason",
    "status",
    "payout",
    "end_date",
    "market_type",
]
```

In `log_trade`, add `trade.market_type` to the row after `end_date`:

```python
                trade.end_date.isoformat() if trade.end_date else "",
                trade.market_type,
```

In `save_trades`, add the same:

```python
                    trade.end_date.isoformat() if trade.end_date else "",
                    trade.market_type,
```

In `read_trades`, add market_type parsing with backward compatibility:

```python
                    market_type=row.get("market_type", "5m"),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_logger.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full test suite to check nothing broke**

Run: `python -m pytest -v`
Expected: ALL PASS (existing tests should still work since `market_type` defaults to "5m")

- [ ] **Step 7: Commit**

```bash
git add config.py logger.py tests/test_logger.py
git commit -m "feat: add market_type field to Trade and CSV logging"
```

---

### Task 2: Add 15-Minute Timing Configuration

**Files:**
- Modify: `config.py:22-32` (timing constants)

- [ ] **Step 1: Update timing constants in config.py**

Replace the single timing window with per-interval configs. Change lines 22-32:

```python
# --- Crypto UpDown Settings ---
# 5-minute markets
MIN_SECONDS_TO_CLOSE_5M = 5       # Skip markets closing in <5s
MAX_SECONDS_TO_CLOSE_5M = 45      # Trade 5m markets closing within 45s
MIN_SECONDS_TO_TRADE_5M = 5       # Don't place trades with <5s remaining

# 15-minute markets — wider window since they're longer duration
MIN_SECONDS_TO_CLOSE_15M = 10     # Skip markets closing in <10s
MAX_SECONDS_TO_CLOSE_15M = 120    # Trade 15m markets closing within 2 minutes
MIN_SECONDS_TO_TRADE_15M = 10     # Higher cutoff — more time needed for execution

# Legacy aliases used by level_analyzer (interval-agnostic minimum)
MIN_SECONDS_TO_CLOSE = 5
MAX_SECONDS_TO_CLOSE = 120        # Widened to accommodate 15m window
MIN_SECONDS_TO_TRADE = 5          # Per-interval override happens in analyzer

CRYPTO_NEAR_CERTAIN_UPPER = 0.88
CRYPTO_NEAR_CERTAIN_LOWER = 0.12
CRYPTO_SKIP_BAND_LOW = 0.38
CRYPTO_SKIP_BAND_HIGH = 0.62
MIN_EDGE = 0.05
MIN_LIQUIDITY = 500
MAX_BETS_PER_CYCLE = 5
```

Remove `UPDOWN_INTERVAL_FILTER = 5` — we no longer filter out 15m.

- [ ] **Step 2: Run tests to check what breaks**

Run: `python -m pytest -v`
Expected: `test_tick_skips_15m_markets` will fail (it asserts 15m is skipped). Fix in Task 3.

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat: add separate timing config for 5m and 15m markets"
```

---

### Task 3: Update Market Fetcher for 15-Minute Window

**Files:**
- Modify: `market_fetcher.py:1-16` (imports)
- Modify: `market_fetcher.py:39-91` (fetch_active_markets)
- Modify: `market_fetcher.py:94-120` (find_updown_markets)
- Modify: `tests/test_market_fetcher.py`

- [ ] **Step 1: Write failing test for 15m market discovery in time window**

Add to `tests/test_market_fetcher.py`:

```python
def test_find_updown_markets_15m_in_window():
    """15m markets within 120s should be discovered."""
    now = datetime.now(timezone.utc)
    m = Market(
        condition_id="0x5",
        question="ETH Up or Down?",
        slug="eth-updown-15m-456",
        outcomes=["Up", "Down"],
        outcome_prices=[0.7, 0.3],
        token_ids=["0xa", "0xb"],
        end_date=now + timedelta(seconds=90),  # 90s out — within 15m window
        active=True,
    )
    results = find_updown_markets([m])
    assert len(results) == 1
    assert results[0].interval_minutes == 15
    assert results[0].coin == "ETH"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_market_fetcher.py::test_find_updown_markets_15m_in_window -v`
Expected: FAIL — 90s exceeds `MAX_SECONDS_TO_CLOSE=30`

- [ ] **Step 3: Update market_fetcher to use per-interval time windows**

In `market_fetcher.py`, update imports:

```python
from config import (
    GAMMA_API_URL,
    CLOB_API_URL,
    Market,
    UpDownMarket,
    MIN_SECONDS_TO_CLOSE,
    MAX_SECONDS_TO_CLOSE,
    MIN_SECONDS_TO_CLOSE_5M,
    MAX_SECONDS_TO_CLOSE_5M,
    MIN_SECONDS_TO_CLOSE_15M,
    MAX_SECONDS_TO_CLOSE_15M,
    MIN_LIQUIDITY,
)
```

Update `find_updown_markets` to use per-interval bounds:

```python
def find_updown_markets(markets: list[Market]) -> list[UpDownMarket]:
    now = datetime.now(timezone.utc)
    results = []
    for m in markets:
        match = UPDOWN_SLUG_RE.match(m.slug)
        if not match:
            continue
        if not m.end_date:
            continue

        coin = match.group(1).upper()
        interval = int(match.group(2))
        secs = max(0, int((m.end_date - now).total_seconds()))

        # Per-interval time window
        if interval == 15:
            min_secs = MIN_SECONDS_TO_CLOSE_15M
            max_secs = MAX_SECONDS_TO_CLOSE_15M
        else:
            min_secs = MIN_SECONDS_TO_CLOSE_5M
            max_secs = MAX_SECONDS_TO_CLOSE_5M

        if secs < min_secs or secs > max_secs:
            continue

        results.append(
            UpDownMarket(
                market=m,
                coin=coin,
                interval_minutes=interval,
                seconds_to_close=secs,
                up_outcome_index=_up_outcome_index(m.outcomes),
            )
        )
    return results
```

Update `fetch_active_markets` to widen the time window to accommodate both intervals:

```python
    floor = now + timedelta(seconds=MIN_SECONDS_TO_CLOSE)
    cutoff = now + timedelta(seconds=MAX_SECONDS_TO_CLOSE)
```

- [ ] **Step 4: Run market fetcher tests**

Run: `python -m pytest tests/test_market_fetcher.py -v`
Expected: ALL PASS

- [ ] **Step 5: Update the old time window test**

The existing `test_find_updown_markets_respects_time_window` tests a 15m market at 200s. With the new 120s max for 15m, this should still be excluded. Verify:

Run: `python -m pytest tests/test_market_fetcher.py::test_find_updown_markets_respects_time_window -v`
Expected: PASS (200s > 120s max)

- [ ] **Step 6: Commit**

```bash
git add market_fetcher.py tests/test_market_fetcher.py
git commit -m "feat: per-interval time windows for 5m and 15m market discovery"
```

---

### Task 4: Update Engine to Process Both 5m and 15m Markets

**Files:**
- Modify: `engine.py:1-17` (imports)
- Modify: `engine.py:192-205` (check_updown_markets)
- Modify: `engine.py:218-307` (tick)
- Modify: `tests/test_engine.py:156-168` (update 15m skip test)

- [ ] **Step 1: Update the 15m skip test to expect 15m trades**

In `tests/test_engine.py`, replace `test_tick_skips_15m_markets`:

```python
@patch("engine.fetch_active_markets")
@patch("engine.find_updown_markets")
@patch("engine.analyze_updown_market")
@patch("engine.log_trade")
def test_tick_executes_15m_trade(mock_log, mock_analyze, mock_find, mock_fetch):
    """15-minute interval markets should now be traded."""
    market = _make_market("eth-updown-15m-100")
    signal = _make_signal(market)

    mock_fetch.return_value = [market]
    udm_mock = MagicMock()
    udm_mock.interval_minutes = 15
    udm_mock.coin = "ETH"
    mock_find.return_value = [udm_mock]
    mock_analyze.return_value = (signal, "test reason")

    engine = Engine()
    trades = engine.tick()

    assert len(trades) == 1
    assert trades[0].strategy == "updown"
    mock_analyze.assert_called_once()
```

- [ ] **Step 2: Write test for market_type being set on trade**

Add to `tests/test_engine.py`:

```python
@patch("engine.log_trade")
def test_trade_market_type_from_signal(mock_log):
    """Trade should have market_type set based on the market slug."""
    engine = Engine()
    market_5m = _make_market("btc-updown-5m-123")
    signal_5m = _make_signal(market_5m)
    trade_5m = engine.execute_paper_trade(signal_5m)
    assert trade_5m.market_type == "5m"

    market_15m = _make_market("eth-updown-15m-456")
    signal_15m = _make_signal(market_15m)
    trade_15m = engine.execute_paper_trade(signal_15m)
    assert trade_15m.market_type == "15m"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_engine.py::test_tick_executes_15m_trade tests/test_engine.py::test_trade_market_type_from_signal -v`
Expected: FAIL

- [ ] **Step 4: Update engine to process both intervals and set market_type**

In `engine.py`, remove the `UPDOWN_INTERVAL_FILTER` import and update `check_updown_markets`:

```python
    def check_updown_markets(self) -> list[Signal]:
        signals = []
        for udm in self.updown_markets_found:
            signal, reason = analyze_updown_market(udm)
            if signal:
                signals.append(signal)
            else:
                self._log(f"  {reason}")
        signals.sort(key=lambda s: s.confidence, reverse=True)
        return signals
```

Update `execute_paper_trade` to detect and set `market_type` from the slug:

```python
    def execute_paper_trade(self, signal: Signal) -> Trade:
        price_idx = 0 if signal.side == "YES" else 1
        entry_price = (
            signal.market.outcome_prices[price_idx]
            if len(signal.market.outcome_prices) > price_idx
            else 0.5
        )

        # Detect market type from slug
        market_type = "15m" if "-15m-" in signal.market.slug else "5m"

        size = self.bet_size(signal.confidence)
        trade = Trade(
            timestamp=datetime.now(timezone.utc),
            market_slug=signal.market.slug,
            question=signal.market.question,
            strategy=signal.strategy,
            side=signal.side,
            entry_price=entry_price,
            size=size,
            confidence=signal.confidence,
            reason=signal.reason,
            end_date=signal.market.end_date,
            market_type=market_type,
        )
        self.trades.append(trade)
        self.traded_markets.add(signal.market.slug)
        self.balance -= size
        log_trade(trade)
        return trade
```

Update the tick method's logging to show both intervals:

```python
            self.updown_markets_found = find_updown_markets(self.markets)
            udm_5m = [u for u in self.updown_markets_found if u.interval_minutes == 5]
            udm_15m = [u for u in self.updown_markets_found if u.interval_minutes == 15]
            self._log(f"Found {len(udm_5m)} 5m + {len(udm_15m)} 15m updown markets")

            # Warm prices for all active updown markets
            active_coins = {udm.coin for udm in self.updown_markets_found}
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_engine.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add engine.py tests/test_engine.py
git commit -m "feat: engine processes both 5m and 15m updown markets"
```

---

### Task 5: Add Execution Reliability Guards to Level Analyzer

**Files:**
- Modify: `level_analyzer.py:1-28` (imports)
- Modify: `level_analyzer.py:33-161` (analyze_updown_market)
- Modify: `tests/test_level_analyzer.py`

- [ ] **Step 1: Write failing tests for stale data guard and latency buffer**

Add to `tests/test_level_analyzer.py`:

```python
@patch("level_analyzer.is_price_stale", return_value=True)
@patch("level_analyzer.get_price_momentum", return_value=0.002)
def test_skip_when_price_data_stale(mock_mom, mock_stale):
    """If price data is stale (>30s old), skip the trade."""
    udm = _make_updown(coin="SOL", up_price=0.82, down_price=0.18)
    signal, reason = analyze_updown_market(udm)
    assert signal is None
    assert "stale" in reason.lower()


@patch("level_analyzer.get_price_momentum", return_value=0.002)
def test_15m_uses_higher_min_seconds(mock_mom):
    """15m markets use MIN_SECONDS_TO_TRADE_15M (10s), not 5s."""
    udm = _make_updown(coin="SOL", up_price=0.82, down_price=0.18, secs=8)
    udm_15m = UpDownMarket(
        market=udm.market,
        coin="SOL",
        interval_minutes=15,
        seconds_to_close=8,
        up_outcome_index=0,
    )
    # Override the slug for 15m
    udm_15m.market.slug = "sol-updown-15m-123"
    signal, reason = analyze_updown_market(udm_15m)
    assert signal is None
    assert "left" in reason  # "8s left < 10s min"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_level_analyzer.py::test_skip_when_price_data_stale tests/test_level_analyzer.py::test_15m_uses_higher_min_seconds -v`
Expected: FAIL

- [ ] **Step 3: Add stale-data guard and per-interval timing to analyzer**

In `level_analyzer.py`, update imports:

```python
from config import (
    Signal,
    UpDownMarket,
    CRYPTO_NEAR_CERTAIN_UPPER,
    CRYPTO_NEAR_CERTAIN_LOWER,
    CRYPTO_SKIP_BAND_LOW,
    CRYPTO_SKIP_BAND_HIGH,
    MIN_EDGE,
    MIN_SECONDS_TO_TRADE_5M,
    MIN_SECONDS_TO_TRADE_15M,
    COIN_MIN_EDGE,
)
from price_feed import get_price, get_price_momentum, is_price_stale
```

At the start of `analyze_updown_market`, after the price count check, add stale-data guard:

```python
    # Stale data guard — don't trade on outdated price info
    if is_price_stale(coin, max_age=30.0):
        return None, f"{coin} skip: price data stale (>30s old)"
```

Replace the `MIN_SECONDS_TO_TRADE` check with per-interval logic:

```python
    # Per-interval minimum time to trade
    min_seconds = MIN_SECONDS_TO_TRADE_15M if udm.interval_minutes == 15 else MIN_SECONDS_TO_TRADE_5M

    if actual_seconds < min_seconds:
        return None, f"{coin} skip: {actual_seconds:.0f}s left < {min_seconds}s min"
```

- [ ] **Step 4: Run analyzer tests**

Run: `python -m pytest tests/test_level_analyzer.py -v`
Expected: ALL PASS (existing tests mock `get_price_momentum` which calls `is_price_stale` internally — but we need to also mock `is_price_stale` at the analyzer level now)

If existing tests break because `is_price_stale` returns True in test env (no price history), add a default mock. Update the helper:

```python
def _make_updown(coin="BTC", up_price=0.75, down_price=0.25, secs=30, up_idx=0):
    ...  # same as before
```

And add a conftest or autouse fixture:

```python
@pytest.fixture(autouse=True)
def _mock_price_freshness():
    """Default: price data is fresh in tests."""
    with patch("level_analyzer.is_price_stale", return_value=False):
        yield
```

Add this at the top of `tests/test_level_analyzer.py`.

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add level_analyzer.py tests/test_level_analyzer.py
git commit -m "feat: add stale-data guard and per-interval timing to analyzer"
```

---

### Task 6: Strategy Changelog Tracking

**Files:**
- Create: `strategy_changelog.py`
- Create: `tests/test_strategy_changelog.py`
- Modify: `config.py` (add STRATEGY_CHANGELOG_PATH)

- [ ] **Step 1: Write failing test for changelog recording**

Create `tests/test_strategy_changelog.py`:

```python
import json
from datetime import datetime, timezone
from strategy_changelog import record_change, read_changelog


def test_record_and_read_change(tmp_path):
    log_path = tmp_path / "changelog.json"
    record_change(
        what="Increased BTC min edge from 0.07 to 0.10",
        old_value="0.07",
        new_value="0.10",
        last_trade_slug="btc-updown-5m-123",
        path=log_path,
    )

    entries = read_changelog(path=log_path)
    assert len(entries) == 1
    assert entries[0]["what"] == "Increased BTC min edge from 0.07 to 0.10"
    assert entries[0]["old_value"] == "0.07"
    assert entries[0]["new_value"] == "0.10"
    assert entries[0]["last_trade_slug"] == "btc-updown-5m-123"
    assert "timestamp" in entries[0]


def test_multiple_changes_append(tmp_path):
    log_path = tmp_path / "changelog.json"
    record_change("change 1", "a", "b", "slug-1", path=log_path)
    record_change("change 2", "c", "d", "slug-2", path=log_path)

    entries = read_changelog(path=log_path)
    assert len(entries) == 2


def test_read_empty_changelog(tmp_path):
    log_path = tmp_path / "nonexistent.json"
    entries = read_changelog(path=log_path)
    assert entries == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_strategy_changelog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'strategy_changelog'`

- [ ] **Step 3: Implement strategy_changelog.py**

Create `strategy_changelog.py`:

```python
"""Track strategy parameter changes over time."""

import json
from datetime import datetime, timezone
from pathlib import Path

CHANGELOG_PATH = Path("strategy_changelog.json")


def record_change(
    what: str,
    old_value: str,
    new_value: str,
    last_trade_slug: str,
    path: Path = CHANGELOG_PATH,
) -> None:
    """Append a strategy change entry to the changelog."""
    entries = read_changelog(path)
    entries.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "what": what,
        "old_value": old_value,
        "new_value": new_value,
        "last_trade_slug": last_trade_slug,
    })
    with open(path, "w") as f:
        json.dump(entries, f, indent=2)


def read_changelog(path: Path = CHANGELOG_PATH) -> list[dict]:
    """Read all changelog entries."""
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_strategy_changelog.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add strategy_changelog.py tests/test_strategy_changelog.py
git commit -m "feat: add strategy changelog for tracking parameter changes"
```

---

### Task 7: Update Dashboard for Market Type Display

**Files:**
- Modify: `dashboard.py:56-89` (trades table)

- [ ] **Step 1: Add market type column to trades table**

In `dashboard.py`, add a "Type" column to the trades table after the "Market" column:

```python
    trades_table.add_column("Type", width=4)
```

And in the row rendering loop, add:

```python
        market_type = getattr(t, 'market_type', '5m')
```

Add `market_type` to the `add_row` call after the market slug.

The full trades table section becomes:

```python
    trades_table = Table(title="Trades", expand=True)
    trades_table.add_column("Time", width=8)
    trades_table.add_column("Market", max_width=28, no_wrap=True)
    trades_table.add_column("Type", width=4)
    trades_table.add_column("Side", width=4)
    trades_table.add_column("Entry", justify="right", width=6)
    trades_table.add_column("Size", justify="right", width=6)
    trades_table.add_column("Result", width=8)
    trades_table.add_column("P/L", justify="right", width=8)
    trades_table.add_column("Reason", max_width=32, no_wrap=True)

    for t in engine.trades[-15:]:
        side_style = "green" if t.side == "YES" else "red"
        market_type = getattr(t, 'market_type', '5m')

        if t.status == "won":
            result_text = Text("WIN", style="bold green")
            pl = t.payout - t.size
            pl_text = Text(f"+${pl:.2f}", style="green")
        elif t.status == "lost":
            result_text = Text("LOSS", style="bold red")
            pl_text = Text(f"-${t.size:.2f}", style="red")
        else:
            result_text = Text("...", style="dim")
            pl_text = Text("—", style="dim")

        trades_table.add_row(
            t.timestamp.strftime("%H:%M:%S"),
            t.market_slug[:28],
            market_type,
            Text(t.side, style=side_style),
            f"${t.entry_price:.2f}",
            f"${t.size:.2f}",
            result_text,
            pl_text,
            t.reason[:32],
        )

    if not engine.trades:
        trades_table.add_row("—", "No trades yet", "—", "—", "—", "—", "—", "—", "Waiting...")
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add dashboard.py
git commit -m "feat: show market type (5m/15m) in dashboard trades table"
```

---

### Task 8: Clean Up Config Imports and Remove UPDOWN_INTERVAL_FILTER

**Files:**
- Modify: `config.py` (remove UPDOWN_INTERVAL_FILTER)
- Modify: `engine.py` (remove UPDOWN_INTERVAL_FILTER import)

- [ ] **Step 1: Remove UPDOWN_INTERVAL_FILTER from config.py**

Delete line:
```python
UPDOWN_INTERVAL_FILTER = 5     # Only trade 5-minute intervals (skip 15m)
```

- [ ] **Step 2: Remove UPDOWN_INTERVAL_FILTER import from engine.py**

Remove `UPDOWN_INTERVAL_FILTER` from the import list in `engine.py`.

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add config.py engine.py
git commit -m "refactor: remove UPDOWN_INTERVAL_FILTER, both intervals now active"
```

---

### Task 9: Apply Data-Driven Tuning from Trade Analysis

**Files:**
- Modify: `config.py` (update BTC edge, tighten timing)

Based on the trade data analysis:
- **BTC** has 64% WR and is losing money → raise min edge further
- **91s+ entries** have 67% WR vs 88% WR at 31-60s → tighten 5m max window
- **Entry prices <0.60** have 58% WR → raise skip band

- [ ] **Step 1: Apply tuning changes**

In `config.py`, update:

```python
# Tightened based on trade data analysis (2026-04-11):
# - 91s+ entries: 67% WR → reduce max window for 5m
# - <0.60 entry: 58% WR → widen skip band
MAX_SECONDS_TO_CLOSE_5M = 30      # Was 45; 31-60s is 88% WR, but 91s+ drops to 67%
CRYPTO_SKIP_BAND_LOW = 0.40       # Was 0.38; tighten to avoid low-WR entries
CRYPTO_SKIP_BAND_HIGH = 0.60      # Was 0.62; symmetric

COIN_MIN_EDGE = {
    "BTC": 0.10,   # Was 0.07; 64% WR, -$7.17 — worst performer, needs big edge
    "ETH": 0.06,   # 75% WR, +$3.03 — marginal
    "DOGE": 0.06,  # 78% WR, +$5.24
    "HYPE": 0.06,  # 82% WR, -$2.05 — high WR but slightly negative, keep tight
}
```

- [ ] **Step 2: Record these changes in the strategy changelog**

This is a manual step — run once to seed the changelog:

```python
python3 -c "
from strategy_changelog import record_change
record_change('Tightened MAX_SECONDS_TO_CLOSE_5M from 45 to 30', '45', '30', 'btc-updown-5m-1775917200')
record_change('Raised BTC COIN_MIN_EDGE from 0.07 to 0.10', '0.07', '0.10', 'btc-updown-5m-1775917200')
record_change('Widened CRYPTO_SKIP_BAND to 0.40-0.60', '0.38-0.62', '0.40-0.60', 'btc-updown-5m-1775917200')
"
```

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest -v`
Expected: ALL PASS (some existing tests may need minor adjustments if they relied on specific skip band values — check and fix)

- [ ] **Step 4: Commit**

```bash
git add config.py strategy_changelog.json
git commit -m "feat: data-driven strategy tuning based on 451-trade analysis"
```

---

### Task 10: Final Integration Test — Run the Bot

- [ ] **Step 1: Run the full test suite one final time**

Run: `python -m pytest -v`
Expected: ALL PASS

- [ ] **Step 2: Verify the bot starts and runs**

Run: `python main.py` — observe the dashboard shows both 5m and 15m markets, the "Type" column appears in trades, and trading proceeds normally. Ctrl+C to stop after verifying.

- [ ] **Step 3: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore: final cleanup for 15m support and reliability improvements"
```
