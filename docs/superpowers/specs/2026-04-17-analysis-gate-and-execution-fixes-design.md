# Design: Analysis Gate & Execution Safety Fixes (Patch v14)

**Date:** 2026-04-17  
**Status:** Approved  
**Author:** Claude Code (brainstorming session)  
**Scope:** Fix all CODE_REVIEW.md high/critical issues that are implementable without an async or wallet-API redesign. Verify in simulation before enabling live.

---

## Context

Forensic analysis of `events.jsonl` (2026-04-16T21:30Z → 2026-04-17T01:14Z — 3.75h window) found:

- **0 live fills, 0 simulation fills** in the entire window despite active market coverage.
- **91.9% of analysis ticks** have no order-book data (`best_bid=null`). Both the `confirmed` and `early_follow` paths in `_analyze_actual_move_first()` require `book_tradeable=True`, so they always fail.
- **35 no-book blocked windows**: 100% positive edge, mean edge **32.3%**, would-have-won **37/37 = 100%** across unique market windows.
- **59 with-book sign-mismatch blocks**: entry prices 0.985–0.995, negative effective edge — correctly blocked, do not touch.
- **84 contrarian blocks**: mean edge 0.6%, 73% negative — correctly blocked, do not touch.
- Shadow signals win 23/24 settled but are `too_late_or_overpriced` with negative edge at 0.985–0.995 — these are directional confirmation signals, not real trades.

CODE_REVIEW.md adds three additional bugs that affect live safety even before the analysis gate is fixed: a post-rounding size overflow in `LiveExecutor`, a fake-loss timeout in `settle_trades()`, and a simulation/live shadow divergence that inflates simulation win rates.

---

## Goals

1. Unblock profitable trades that are rejected purely due to missing book data.
2. Prevent live order size from silently exceeding risk-approved notional.
3. Prevent unresolved markets from being recorded as losses.
4. Make simulation shadow behavior match live shadow behavior so metrics are trustworthy.
5. Cover all changes with tests. Bump `STRATEGY_VERSION` so analytics don't mix pre/post data.

---

## Out of Scope

These issues require architectural changes beyond this patch:

- **Wallet reconciliation** — needs Polymarket CLOB API queries for live balance/positions.
- **Tick latency / async warming** — requires async refactor of `engine.py` + `price_feed.py`.
- **Taker fallback** — requires execution strategy redesign.
- **Skip-signal retrospective labeling** — medium complexity, not blocking simulation.
- **Dead code removal** in `level_analyzer.py` — cosmetic, can wait.

---

## Fix 1: Analysis Gate — `early_follow` No-Book Path

**Files:** `config.py`, `level_analyzer.py`  
**Lines:** `config.py:236`, `level_analyzer.py:1508–1518`, `level_analyzer.py` imports  

### Problem

`early_follow` at `level_analyzer.py:1511` requires `book_tradeable=True`. Because 91.9% of ticks have no book data, this path is dead. No trades emit.

The 35 no-book blocked windows all pass the other `early_follow` conditions (direction sign agreement, body ratio, entry price ≤ 0.60, high edge) — the book requirement alone is the blocker.

### Change

**`config.py`** — add one env-overridable constant after `EARLY_MOMENTUM_EXTRA_EDGE`:

```python
EARLY_MOMENTUM_NO_BOOK_EXTRA_EDGE = float(os.getenv("EARLY_MOMENTUM_NO_BOOK_EXTRA_EDGE", "0.05"))
```

**`level_analyzer.py`** — add to `from config import` block: `EARLY_MOMENTUM_NO_BOOK_EXTRA_EDGE`

**`level_analyzer.py:1508–1518`** — remove `and book_tradeable`, add no-book surcharge:

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

### Invariants

- `confirmed` path is unchanged — still requires `book_tradeable`.
- When `early_follow` fires without book data: `trend_alignment="follow_trend_early"`, `strategy_route="trend_follow_early"`, `size_multiplier=min(..., 0.75)`, `price_state="strong_actual_move_early"`. All existing downstream handling applies.
- Entry price uses existing fallback (`up_price` or `down_price`) when book is absent — no new pricing logic needed.
- `EARLY_MOMENTUM_MAX_ENTRY_PRICE=0.60` cap still applies — no high-priced contracts taken without book.
- Total no-book edge floor: `min_edge + 0.01 + 0.05 = min_edge + 0.06`.

---

## Fix 2: Post-Rounding Size Overflow

**File:** `order_executor.py`, `config.py`  
**Lines:** `order_executor.py:1117–1119`

### Problem

```python
min_shares = 5.0
shares = max(round(size / limit_price, 2), min_shares)
actual_size = round(shares * limit_price, 2)
```

If risk approves `$1.00` and `limit_price=0.90`, `size/limit_price = 1.11 shares`, rounded up to `5.0 shares`, `actual_size = $4.50`. The order is submitted 4.5× the approved notional with no second risk check.

### Change

**`config.py`** — add:

```python
LIVE_MAX_SIZE_EXPANSION = float(os.getenv("LIVE_MAX_SIZE_EXPANSION", "2.0"))
```

**`order_executor.py`** — add `LIVE_MAX_SIZE_EXPANSION` to the `from config import` block (line 25).

**`order_executor.py`** — after `actual_size` is computed (line 1119), before `_submit_limit_order`, using the existing `_make_rejection` helper:

```python
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

### Invariants

- `LIVE_MAX_SIZE_EXPANSION=2.0` means up to 2× expansion is acceptable (handles rounding noise).
- A 4.5× expansion is rejected cleanly before any API call.
- The rejection is logged as `status="rejected"` and surfaces in analytics.
- `LIVE_MAX_SIZE_EXPANSION` is env-overridable if the user wants to tighten or relax.

---

## Fix 3: Remove Fake-Loss Timeout

**File:** `engine.py`  
**Lines:** `engine.py:1454–1462`

### Problem

```python
if trade.end_date and (now - trade.end_date).total_seconds() > 600:
    trade.status = "lost"
    trade.payout = 0.0
    self.losses += 1
    self.risk_manager.record_trade_result(trade)
    self._log(f"LOSS (unresolved after 10m): {trade.market_slug}")
    log_settlement(trade)
    log_trade_jsonl(...)
    settled = True
```

A slow resolution API response causes the engine to permanently record a loss, trip risk limits, and distort bankroll.

### Change

Replace the entire `if trade.end_date and ... > 600` block with a log-and-continue:

```python
if trade.end_date and (now - trade.end_date).total_seconds() > 600:
    self._log(f"PENDING (still unresolved after 10m): {trade.market_slug}")
continue
```

The trade stays `pending` indefinitely until `fetch_resolved_market` returns a real result.

### Invariants

- No fake losses, no fake risk-limit trips.
- Trade stays in `self.trades` and is retried every `settle_trades()` call until resolved.
- A genuine loss still records correctly when `winning_side != trade.side` from a real resolution.
- `tests/test_engine.py:917–933` currently asserts the fake-loss behavior — that test must be updated to assert the trade stays `pending`.

---

## Fix 4: Shadow/Live Alignment

**File:** `engine.py`  
**Lines:** `engine.py:107–112`

### Problem

```python
def _shadow_signal_allowed(signal: Signal) -> bool:
    if signal.strategy_mode != STRATEGY_MODE_SHADOW:
        return True
    if TRADING_MODE == "simulation":
        return True   # ← all shadow signals execute in simulation
    return TRADING_MODE == "live" and (signal.strategy_route or "") == "high_prob_shadow"
```

In simulation, every shadow signal executes. In live, only `strategy_route == "high_prob_shadow"` executes (a route that is never assigned, so shadow signals never trade in live). Simulation win metrics are contaminated with trades that can never happen in live.

### Change

Apply the same route restriction in both modes:

```python
def _shadow_signal_allowed(signal: Signal) -> bool:
    if signal.strategy_mode != STRATEGY_MODE_SHADOW:
        return True
    return (signal.strategy_route or "") == "high_prob_shadow"
```

### Invariants

- Live signals (`strategy_mode="live"`) are unaffected — they always pass this check.
- Shadow signals only execute if explicitly routed as `high_prob_shadow` (reserved for future high-confidence shadow opportunities).
- Simulation now shows the same shadow fill rate as live: zero, until a `high_prob_shadow` route is produced.
- The existing `test_engine.py` tests that mock `_shadow_signal_allowed` are unaffected.

---

## Fix 5: Strategy Version Bump

**File:** `config.py:159`

```python
STRATEGY_VERSION = 14
```

Ensures analytics, `strategy_eval.py`, and `analyze_simulation.py` scope to the new parameter set and don't mix pre-patch and post-patch data.

---

## Tests

### `tests/test_level_analyzer.py` — 2 new cases

**Case A — No-book, high edge → `trend_follow_early`**

Patch `MARKET_CACHE.snapshot` to return `{}` (empty dict — `_book_is_tradeable` reads `.get("best_bid")` which returns `None` from an empty dict, correctly setting `book_tradeable=False`). Use a reference snapshot where `actual_window_return` is strong, `late_return_60s` agrees, `body_ratio >= 0.50`, `entry_price <= 0.60`, and `edge_net >= min_edge + 0.06`. Assert `analysis.strategy_route == "trend_follow_early"` and `analysis.signal is not None`.

**Case B — No-book, insufficient edge → skip**

Same setup but `edge_net < min_edge + 0.06` (below the no-book floor). Assert `analysis.signal is None` and `analysis.price_state == "strong_move_no_confirmation"`.

### `tests/test_engine.py` — update fake-loss test

Lines 917–933 currently assert `trade.status == "lost"` after 10 minutes of non-resolution. Update to assert `trade.status == "pending"` and that `self.losses` is not incremented.

### `tests/test_execution_preflight.py` or `tests/test_live_executor.py` — 1 new case

Mock `size=1.0`, `limit_price=0.20` (which would expand to 5 shares × 0.20 = $1.00 actual — within 2× limit). Assert passes.

Mock `size=1.0`, `limit_price=0.90` (which would expand to 5 shares × 0.90 = $4.50 — exceeds 2× limit). Assert `OrderResult.status == "rejected"`.

---

## Verification Plan

After implementation, run in simulation for one market session (minimum 20 market windows) and confirm:

1. `strategy_route="trend_follow_early"` events appear in `events.jsonl` with `book_age_ms=null`.
2. No `strategy_route="too_late_or_overpriced"` shadow fills (shadow signals no longer execute in simulation).
3. No `LOSS (unresolved after 10m)` log lines.
4. `python -m pytest` passes with 0 failures.
