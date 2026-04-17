# Analysis Gate & Execution Safety Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unlock 35 high-edge blocked trades per session by removing the redundant `book_tradeable` gate from `early_follow`, while also patching three live-safety bugs: post-rounding size overflow, fake-loss timeout, and simulation/live shadow divergence.

**Architecture:** All changes are targeted single-file patches. No new modules. TDD throughout — write the failing test, run it, then implement the minimum code to pass.

**Tech Stack:** Python 3.12, pytest, config.py constants pattern (env-overridable floats).

---

## File Map

| File | What changes |
|---|---|
| `config.py` | Add `EARLY_MOMENTUM_NO_BOOK_EXTRA_EDGE`, `LIVE_MAX_SIZE_EXPANSION`; bump `STRATEGY_VERSION` to 14 |
| `level_analyzer.py` | Add constant to imports; remove `book_tradeable` from `early_follow`; add no-book edge surcharge |
| `order_executor.py` | Add `LIVE_MAX_SIZE_EXPANSION` to imports; add size-overflow rejection after 5-share expansion |
| `engine.py` | Remove 10-minute fake-loss block; remove simulation-mode exception from `_shadow_signal_allowed` |
| `tests/test_level_analyzer.py` | Add 2 tests for no-book early_follow path |
| `tests/test_live_executor.py` | Add 1 test for size-overflow rejection |
| `tests/test_engine.py` | Update fake-loss test; update shadow simulation test |

---

## Task 1: Config constants + STRATEGY_VERSION bump

**Files:**
- Modify: `config.py:159` (STRATEGY_VERSION)
- Modify: `config.py:236` (after EARLY_MOMENTUM_EXTRA_EDGE)
- Modify: `config.py:325` (after LIVE_MIN_BET area)

No test needed for constants — they are verified by the tests in later tasks.

- [ ] **Step 1: Bump STRATEGY_VERSION to 14**

In `config.py` line 159, change:
```python
STRATEGY_VERSION = 13
```
to:
```python
STRATEGY_VERSION = 14
```

- [ ] **Step 2: Add EARLY_MOMENTUM_NO_BOOK_EXTRA_EDGE**

In `config.py`, after line 236 (`EARLY_MOMENTUM_EXTRA_EDGE = ...`), insert:
```python
EARLY_MOMENTUM_NO_BOOK_EXTRA_EDGE = float(os.getenv("EARLY_MOMENTUM_NO_BOOK_EXTRA_EDGE", "0.05"))
```

- [ ] **Step 3: Add LIVE_MAX_SIZE_EXPANSION**

In `config.py`, after line 325 (`LIVE_MIN_BET = 1.00`), insert:
```python
LIVE_MAX_SIZE_EXPANSION = float(os.getenv("LIVE_MAX_SIZE_EXPANSION", "2.0"))
```

- [ ] **Step 4: Verify config loads without error**

Run:
```bash
python -c "from config import EARLY_MOMENTUM_NO_BOOK_EXTRA_EDGE, LIVE_MAX_SIZE_EXPANSION, STRATEGY_VERSION; print(EARLY_MOMENTUM_NO_BOOK_EXTRA_EDGE, LIVE_MAX_SIZE_EXPANSION, STRATEGY_VERSION)"
```
Expected output: `0.05 2.0 14`

- [ ] **Step 5: Commit**

```bash
git add config.py
git commit -m "feat: add no-book edge surcharge and size-expansion constants, bump strategy version to 14"
```

---

## Task 2: Analysis gate — write failing tests

**Files:**
- Modify: `tests/test_level_analyzer.py` (append 2 tests at end of file)

- [ ] **Step 1: Append tests to test_level_analyzer.py**

Add both tests at the end of `tests/test_level_analyzer.py`:

```python
@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=0.004,
        zscore=2.0,
        interval_open=100.0,
        interval_high=100.4,
        interval_low=99.95,
        interval_close=100.4,
        interval_return=0.004,
        late_return_60s=0.001,
        late_return_20s=0.001,
        body_ratio=0.55,
        wick_imbalance=0.01,
    ),
)
def test_no_book_high_edge_emits_trend_follow_early(mock_snapshot):
    """No order-book data + strong confirmed move + high edge → early_follow fires."""
    udm = _make_updown(up_price=0.45, down_price=0.55, secs=25)
    with patch("level_analyzer.MARKET_CACHE.snapshot", return_value={}):
        analysis = analyze_updown_market_detail(udm)
    assert analysis.signal is not None
    assert analysis.strategy_route == "trend_follow_early"
    assert analysis.signal.size_multiplier == pytest.approx(0.75)


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=0.004,
        zscore=2.0,
        interval_open=100.0,
        interval_high=100.4,
        interval_low=99.95,
        interval_close=100.4,
        interval_return=0.004,
        late_return_60s=-0.001,
        late_return_20s=-0.001,
        body_ratio=0.55,
        wick_imbalance=0.01,
    ),
)
def test_no_book_late_misalign_skips(mock_snapshot):
    """No order-book + late returns disagree with actual move → skip, even without book gate."""
    udm = _make_updown(up_price=0.45, down_price=0.55, secs=25)
    with patch("level_analyzer.MARKET_CACHE.snapshot", return_value={}):
        analysis = analyze_updown_market_detail(udm)
    assert analysis.signal is None
    assert analysis.price_state == "strong_move_no_confirmation"
```

- [ ] **Step 2: Run the two new tests — expect FAIL**

Run:
```bash
python -m pytest tests/test_level_analyzer.py::test_no_book_high_edge_emits_trend_follow_early tests/test_level_analyzer.py::test_no_book_late_misalign_skips -v
```
Expected: `test_no_book_high_edge_emits_trend_follow_early` FAILS (signal is None because book_tradeable blocks early_follow). `test_no_book_late_misalign_skips` PASSES (already skips correctly).

---

## Task 3: Analysis gate — implement early_follow fix

**Files:**
- Modify: `level_analyzer.py:33` (imports)
- Modify: `level_analyzer.py:1508–1518` (early_follow condition)

- [ ] **Step 1: Add EARLY_MOMENTUM_NO_BOOK_EXTRA_EDGE to imports**

In `level_analyzer.py`, line 33 currently reads:
```python
    EARLY_MOMENTUM_EXTRA_EDGE,
```
Change it to:
```python
    EARLY_MOMENTUM_EXTRA_EDGE,
    EARLY_MOMENTUM_NO_BOOK_EXTRA_EDGE,
```

- [ ] **Step 2: Update early_follow condition**

In `level_analyzer.py`, lines 1508–1518 currently read:
```python
    early_follow = (
        not confirmed
        and _sign(actual_window_return) != 0
        and book_tradeable
        and body_ratio is not None
        and body_ratio >= EARLY_MOMENTUM_MIN_BODY_RATIO
        and entry_price <= EARLY_MOMENTUM_MAX_ENTRY_PRICE
        and (late_60_align or late_20_align)
        and edge_gross >= (expected_cost * 3.0)
        and edge_net >= (min_edge + EARLY_MOMENTUM_EXTRA_EDGE)
    )
```
Replace with:
```python
    early_follow = (
        not confirmed
        and _sign(actual_window_return) != 0
        and body_ratio is not None
        and body_ratio >= EARLY_MOMENTUM_MIN_BODY_RATIO
        and entry_price <= EARLY_MOMENTUM_MAX_ENTRY_PRICE
        and (late_60_align or late_20_align)
        and edge_gross >= (expected_cost * 3.0)
        and edge_net >= (
            min_edge
            + EARLY_MOMENTUM_EXTRA_EDGE
            + (0.0 if book_tradeable else EARLY_MOMENTUM_NO_BOOK_EXTRA_EDGE)
        )
    )
```

- [ ] **Step 3: Run new tests — expect both PASS**

Run:
```bash
python -m pytest tests/test_level_analyzer.py::test_no_book_high_edge_emits_trend_follow_early tests/test_level_analyzer.py::test_no_book_late_misalign_skips -v
```
Expected: both PASS.

- [ ] **Step 4: Run full level_analyzer test suite — expect no regressions**

Run:
```bash
python -m pytest tests/test_level_analyzer.py -v
```
Expected: all previously passing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add level_analyzer.py tests/test_level_analyzer.py
git commit -m "fix: remove book_tradeable gate from early_follow; add no-book edge surcharge"
```

---

## Task 4: Size overflow — write failing test

**Files:**
- Modify: `tests/test_live_executor.py` (append 1 test)

- [ ] **Step 1: Append test to test_live_executor.py**

```python
@patch("py_clob_client.client.ClobClient", autospec=True)
def test_live_executor_size_expansion_rejected(MockClient):
    """5-share minimum expanding a $2 order to $4.45 (>2x limit) must be rejected."""
    executor, instance = _make_executor(MockClient)
    instance.get_order_book.return_value = {
        "bids": [{"price": "0.88", "size": "25"}],
        "asks": [{"price": "0.91", "size": "25"}],
        "tick_size": "0.01",
    }

    # size=2.0, entry_price=0.90 → limit_price≈0.89, estimated_shares≈2.25
    # 5-share floor → shares=5.0, actual_size≈4.45
    # 4.45 > 2.0 * 2.0 (LIVE_MAX_SIZE_EXPANSION) → rejected
    result = executor.place_order(_make_signal(side="YES"), size=2.0, entry_price=0.90)

    assert result.filled is False
    assert "size expansion" in result.reason
    assert instance.create_order.call_count == 0
```

- [ ] **Step 2: Run the test — expect FAIL**

Run:
```bash
python -m pytest tests/test_live_executor.py::test_live_executor_size_expansion_rejected -v
```
Expected: FAIL — order is submitted (no rejection guard yet), so `instance.create_order.call_count > 0`.

---

## Task 5: Size overflow — implement rejection check

**Files:**
- Modify: `order_executor.py:25–49` (imports)
- Modify: `order_executor.py:1119` (after actual_size computation)

- [ ] **Step 1: Add LIVE_MAX_SIZE_EXPANSION to imports**

In `order_executor.py`, the `from config import` block ends around line 49. Add `LIVE_MAX_SIZE_EXPANSION,` after `LIVE_MAKER_REFERENCE_REVERSAL,` (line 36):
```python
    LIVE_MAKER_REFERENCE_REVERSAL,
    LIVE_MAX_SIZE_EXPANSION,
    MAX_TAKER_FEE_RATE,
```

- [ ] **Step 2: Add overflow check after line 1119**

In `order_executor.py`, lines 1117–1119 currently read:
```python
        min_shares = 5.0
        shares = max(round(size / limit_price, 2), min_shares)
        actual_size = round(shares * limit_price, 2)
```
Add the overflow check immediately after (before `t0 = time.time()`):
```python
        min_shares = 5.0
        shares = max(round(size / limit_price, 2), min_shares)
        actual_size = round(shares * limit_price, 2)
        if actual_size > size * LIVE_MAX_SIZE_EXPANSION:
            return self._make_rejection(
                entry_price=limit_price,
                latency_ms=0.0,
                reason=f"size expansion {actual_size:.2f} > limit {size * LIVE_MAX_SIZE_EXPANSION:.2f} (min_shares floor)",
                requested_size=size,
                requested_shares=shares,
                token_id=token_id,
                metadata=metadata,
            )
```

- [ ] **Step 3: Run size overflow test — expect PASS**

Run:
```bash
python -m pytest tests/test_live_executor.py::test_live_executor_size_expansion_rejected -v
```
Expected: PASS.

- [ ] **Step 4: Run full live executor test suite — expect no regressions**

Run:
```bash
python -m pytest tests/test_live_executor.py -v
```
Expected: all previously passing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add order_executor.py tests/test_live_executor.py
git commit -m "fix: reject live orders where 5-share minimum expands notional beyond 2x approved size"
```

---

## Task 6: Fake-loss timeout — update test + implement fix

**Files:**
- Modify: `tests/test_engine.py:917–942`
- Modify: `engine.py:1454–1462`

- [ ] **Step 1: Update the fake-loss test to assert pending behavior**

In `tests/test_engine.py`, `test_settlement_timeout_logs_structured_event` (lines 917–942) currently asserts `trade.status == "lost"`. Replace the entire test body with:

```python
def test_settlement_timeout_leaves_trade_pending():
    executor = StubExecutor(place_results=[_make_result(order_id="fill-1")])
    market = _make_market(end_minutes=-20)
    signal = _make_signal(market)

    with (
        patch("engine.fetch_resolved_market", return_value=None),
        patch("engine.log_settlement") as mock_settlement,
        patch("engine.log_trade_jsonl") as mock_trade_jsonl,
    ):
        engine = Engine(executor=executor)
        trade = engine.execute_paper_trade(signal)
        engine.settle_trades()

    assert trade is not None
    assert trade.status == "pending"
    assert engine.losses == 0
    mock_settlement.assert_not_called()
    mock_trade_jsonl.assert_not_called()
```

Note: the old name was `test_settlement_timeout_logs_structured_event` — rename it to `test_settlement_timeout_leaves_trade_pending`.

- [ ] **Step 2: Run the updated test — expect FAIL**

Run:
```bash
python -m pytest tests/test_engine.py::test_settlement_timeout_leaves_trade_pending -v
```
Expected: FAIL — `trade.status` is still `"lost"` because the timeout block hasn't been removed yet.

- [ ] **Step 3: Remove the fake-loss block from engine.py**

In `engine.py`, lines 1452–1463 currently read:
```python
            resolved = fetch_resolved_market(trade.market_slug)
            if resolved is None:
                if trade.end_date and (now - trade.end_date).total_seconds() > 600:
                    trade.status = "lost"
                    trade.payout = 0.0
                    self.losses += 1
                    self.risk_manager.record_trade_result(trade)
                    self._log(f"LOSS (unresolved after 10m): {trade.market_slug}")
                    log_settlement(trade)
                    log_trade_jsonl(trade, executor_type=trade.executor_type or type(self.executor).__name__, snapshot_event="settlement")
                    settled = True
                continue
```
Replace with:
```python
            resolved = fetch_resolved_market(trade.market_slug)
            if resolved is None:
                if trade.end_date and (now - trade.end_date).total_seconds() > 600:
                    self._log(f"PENDING (still unresolved after 10m): {trade.market_slug}")
                continue
```

- [ ] **Step 4: Run the updated test — expect PASS**

Run:
```bash
python -m pytest tests/test_engine.py::test_settlement_timeout_leaves_trade_pending -v
```
Expected: PASS.

- [ ] **Step 5: Run full engine test suite — expect no regressions**

Run:
```bash
python -m pytest tests/test_engine.py -v
```
Expected: all previously passing tests pass. The old `test_settlement_timeout_logs_structured_event` no longer exists (renamed), so no conflict.

- [ ] **Step 6: Commit**

```bash
git add engine.py tests/test_engine.py
git commit -m "fix: unresolved trades stay pending instead of force-booking as lost after 10m"
```

---

## Task 7: Shadow/live alignment — update test + implement fix

**Files:**
- Modify: `tests/test_engine.py` (update `test_simulation_executes_shadow_signal`)
- Modify: `engine.py:107–112` (`_shadow_signal_allowed`)

- [ ] **Step 1: Update test_simulation_executes_shadow_signal**

In `tests/test_engine.py`, `test_simulation_executes_shadow_signal` (lines 1179–1202) currently asserts `trade is not None`. After Fix 4, simulation also blocks non-promoted shadow signals. Replace the full test:

```python
def test_simulation_blocks_non_promoted_shadow_signal():
    """After shadow/live alignment: shadow signals without high_prob_shadow route
    are blocked in simulation mode the same as in live mode."""
    executor = StubExecutor(place_results=[_make_result(order_id="sim-shadow-1")])
    signal = _make_signal()
    signal.strategy_mode = "shadow"
    # strategy_route defaults to "" — not "high_prob_shadow"

    with patch("engine.TRADING_MODE", "simulation"):
        eng = Engine(executor=executor)
        trade, stage, reason = eng._try_execute(signal)

    assert trade is None
    assert stage == "shadow_only"
    assert reason == "shadow-only strategy"
    assert executor.place_calls == []
```

Note: rename from `test_simulation_executes_shadow_signal` to `test_simulation_blocks_non_promoted_shadow_signal`.

- [ ] **Step 2: Run the updated test — expect FAIL**

Run:
```bash
python -m pytest tests/test_engine.py::test_simulation_blocks_non_promoted_shadow_signal -v
```
Expected: FAIL — simulation currently allows the shadow signal through.

- [ ] **Step 3: Implement shadow/live alignment in engine.py**

In `engine.py`, lines 107–112 currently read:
```python
def _shadow_signal_allowed(signal: Signal) -> bool:
    if signal.strategy_mode != STRATEGY_MODE_SHADOW:
        return True
    if TRADING_MODE == "simulation":
        return True
    return TRADING_MODE == "live" and (signal.strategy_route or "") == "high_prob_shadow"
```
Replace with:
```python
def _shadow_signal_allowed(signal: Signal) -> bool:
    if signal.strategy_mode != STRATEGY_MODE_SHADOW:
        return True
    return (signal.strategy_route or "") == "high_prob_shadow"
```

- [ ] **Step 4: Run the updated test — expect PASS**

Run:
```bash
python -m pytest tests/test_engine.py::test_simulation_blocks_non_promoted_shadow_signal -v
```
Expected: PASS.

- [ ] **Step 5: Verify high_prob_shadow still executes in both modes**

Run:
```bash
python -m pytest tests/test_engine.py::test_live_executes_high_prob_shadow_signal tests/test_engine.py::test_live_blocks_non_promoted_shadow_signal -v
```
Expected: both PASS — `high_prob_shadow` still executes, non-promoted still blocks.

- [ ] **Step 6: Run full engine test suite — expect no regressions**

Run:
```bash
python -m pytest tests/test_engine.py -v
```
Expected: all tests pass (the old `test_simulation_executes_shadow_signal` no longer exists — renamed).

- [ ] **Step 7: Commit**

```bash
git add engine.py tests/test_engine.py
git commit -m "fix: align shadow signal filtering in simulation to match live mode rules"
```

---

## Task 8: Full suite verification

- [ ] **Step 1: Run the complete test suite**

Run:
```bash
python -m pytest -v
```
Expected: all tests pass. Note the count — it should be ≥ the pre-patch count (244) plus the 4 new tests added (2 level_analyzer, 1 live_executor, renamed tests in engine).

- [ ] **Step 2: Verify config values load correctly**

Run:
```bash
python -c "
from config import (
    EARLY_MOMENTUM_NO_BOOK_EXTRA_EDGE,
    LIVE_MAX_SIZE_EXPANSION,
    STRATEGY_VERSION,
)
assert EARLY_MOMENTUM_NO_BOOK_EXTRA_EDGE == 0.05, EARLY_MOMENTUM_NO_BOOK_EXTRA_EDGE
assert LIVE_MAX_SIZE_EXPANSION == 2.0, LIVE_MAX_SIZE_EXPANSION
assert STRATEGY_VERSION == 14, STRATEGY_VERSION
print('All config assertions pass')
"
```
Expected: `All config assertions pass`

- [ ] **Step 3: Commit final state**

```bash
git add -p  # review any remaining unstaged changes
git commit -m "chore: full suite verification pass for patch v14"
```
(Skip this commit if Step 1 produced no unstaged changes.)

---

## Verification Checklist (post-implementation)

After running in simulation for one session (minimum 20 market windows):

1. Check `events.jsonl` for `strategy_route="trend_follow_early"` entries with `book_age_ms=null` — these are the newly unblocked trades.
2. Check that `LOSS (unresolved after 10m)` no longer appears in logs.
3. Check that shadow fill counts in simulation drop to near zero (shadow signals no longer auto-execute).
4. Run `python -m pytest` — zero failures.
