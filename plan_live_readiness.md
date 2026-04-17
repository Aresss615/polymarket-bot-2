# Live Readiness Plan — Patch v14

> **Status:** Security review cleared. No high-confidence vulnerabilities. This plan covers everything that still needs to be validated before real-money deployment.
>
> **Bias of this document:** Assume the biggest danger is operational error, silent misconfiguration, and observability gaps — not a hostile attacker.

---

## 1. Executive Summary

Patch v14 passes its security review. The code is mechanically correct: size-expansion rejection is wired up (`order_executor.py:1121`), shadow signal filtering is enforced (`engine.py:107–110`), and the live execution path is unchanged from the prior baseline.

**The risk of losing money is not a code-quality problem. It is an operational problem.** The three most likely ways you lose money before a vulnerability ever matters:

1. **Misconfigured environment** — wrong `TRADING_MODE`, `LIVE_BALANCE` too high, relayer URL pointing somewhere unexpected, a strategy mode env var accidentally promoting 15m from shadow to live.
2. **Silent logic failures** — stale reference price bypasses the edge filter; an unresolved market settles your balance incorrectly; a redemption silently fails and you never collect a win.
3. **Insufficient observability** — you don't notice a pattern of bad fills, widening spreads, or a kill switch that fired and nobody saw.

This plan converts those concerns into pass/fail checks.

---

## 2. Security Assumptions and Trusted Boundaries

The security review relies on these assumptions. They must remain true in production — if any is violated, the risk posture changes.

| Assumption | What it means operationally |
|---|---|
| Env vars are a trusted boundary | `POLYMARKET_PRIVATE_KEY`, `POLYMARKET_RELAYER_URL`, and `POLYMARKET_RELAYER_API_KEY` must only be readable by the process owner. If these are in a shared `.env` checked into a repo, or readable by a CI system, the boundary is broken. |
| `STRATEGY_MODE_SHADOW` is never reachable from external input | The only shadow promotion path is explicit env var override (`UPDOWN_5M_STRATEGY_MODE`, `UPDOWN_15M_STRATEGY_MODE`). If a deployment script or CI ever writes these env vars automatically from untrusted input, this assumption breaks. |
| Private key is not logged or transmitted beyond CLOB | `LiveExecutor.__init__` stores the key as `self._signer_account = Account.from_key(private_key)` (line 350). The key string is also passed to `ClobClient(key=private_key)` (line 381). Any future change to logging that serialises the executor object risks leaking the key. |
| The relayer host is controlled | `POLYMARKET_RELAYER_URL` defaults to `"https://relayer-v2.polymarket.com"` (config.py:141–143). If someone changes this env var to a host they control, they receive the relayer API key and the signed redemption payload. This is a trusted-boundary assumption, not an exploitable vuln — but it is a hardening gap. |

---

## 3. Residual Risks Still Worth Hardening

These are not currently exploitable. They are live-trading hazards.

### 3.1 Accidental Wrong Relayer Host
`POLYMARKET_RELAYER_URL` can be set to any URL. There is no hostname whitelist. If you accidentally set it to a non-Polymarket host (e.g., a staging URL, a typo, a previous test environment), your relayer API key and signed redemption transactions go to the wrong endpoint.

**Current state:** No validation at startup.
**Hardening needed:** On startup in live mode, assert that `POLYMARKET_RELAYER_URL` matches a whitelist of known Polymarket relayer domains, or at minimum log the configured URL prominently so it can be visually verified.

### 3.2 Strategy Mode Drift Between Research, Shadow, and Live
The strategy modes (`UPDOWN_5M_STRATEGY_MODE`, `UPDOWN_15M_STRATEGY_MODE`, `BTC_NO_STRATEGY_MODE`, `ARBITRAGE_STRATEGY_MODE`) default correctly in code but can all be overridden via env vars. There is no startup assertion that verifies expected defaults in live mode. You could accidentally run live with 15m promoted to live, BTC NO promoted to live, or arbitrage enabled.

**Current state:** No startup validation of strategy mode configuration.
**Hardening needed:** In `main.py`, before constructing the engine in live mode, print and assert the active strategy mode configuration. Fail fast if any unexpected mode is active.

### 3.3 Secret Leakage Through Future Logging Changes
`_result_metadata_from_signal` (order_executor.py:132–182) serialises signal metadata into `OrderResult`. The `raw_response` field on `OrderResult` stores the full CLOB response dict. If someone adds a log line that serialises the full executor or result object, and the executor is ever passed context that includes the private key or API key, the key could appear in logs.

**Current state:** The key is not in any log today. But there is no enforcement preventing it.
**Hardening needed:** The private key should be zeroed or replaced after `ClobClient` and `Account` are initialised. At minimum, never log the `LiveExecutor` object directly.

### 3.4 Unsafe Retry and Duplicate Order Submission
`LiveExecutor.place_order` has a post-only retry path (lines 1140–1154): if the first GTC post-only order is rejected, it decrements the price by one tick and retries. This is correct. However, if the engine's `tick()` fires again before the retry resolves, `_try_execute` will see the market slug already in `active_order_markets` and skip. This is the intended deduplication path. 

**The gap:** If the engine crashes between the first order submission and the open order being written to `open_orders.csv`, on restart the engine will not know the order is live, and may attempt to place a second order for the same market. The open order is only saved after `_normalize_submit_response` succeeds and `_create_open_order` is called (engine.py:1217–1220).

**Hardening needed:** On startup, reconcile all open orders immediately before accepting new signals. This is partially done (`_reconcile_open_orders()` is called in `__init__`), but verify that this path correctly prevents re-entry for a market that has a live unreconciled order.

### 3.5 Balance Reconciliation on Startup
`_load_history` (engine.py:210–248) reconstructs balance from trade history using `STARTING_BALANCE`. If CSV state is corrupted, out of date, or from a prior session with a different starting balance, the bot can trade with an incorrect view of available capital. There is no sanity check comparing computed balance to a live wallet balance read from the Polymarket API.

**Hardening needed:** In live mode, after loading history, compare the computed balance against the live wallet USDC balance fetched from the Polymarket API. Alert (or fail fast) if the discrepancy exceeds `LIVE_MIN_BET`.

### 3.6 Bad Redemption Handling
EOA wallets have auto-redeem disabled in v1 (order_executor.py:624–631). A winning trade with an EOA wallet will have `redemption_status = "disabled"` and the money stays in the contract. There is no alert, no dashboard indicator, and no recovery path documented.

**Hardening needed:** If `wallet_type == "eoa"`, live mode should display a persistent warning on the dashboard after any win. You must manually call `redeemPositions` on-chain or use the Polymarket UI.

### 3.7 Missing Liquidity in Execution Window
The current depth check is `depth_usd < max(MIN_ORDER_DEPTH_USD, size * 1.2)` where `MIN_ORDER_DEPTH_USD = 25.0` (order_executor.py:1061). The 5-second timing window for 5m markets is extremely tight. At near-expiry, books can go one-sided or completely illiquid. The current depth check only fires if `market_data_client` is set and a quote is available. If the quote fetch silently fails (the `except Exception: pass` at line 1071), the depth check is bypassed entirely.

**Hardening needed:** Stale or missing quote data should be treated as a rejection, not a silent pass.

### 3.8 Config Drift — `CLOB_API_URL` Is Not Used by LiveExecutor
`config.py` defines `CLOB_API_URL = "https://clob.polymarket.com"` (line 128). `LiveExecutor.__init__` hardcodes `ClobClient("https://clob.polymarket.com", ...)` (line 380) instead of reading from `CLOB_API_URL`. This is a silent drift: if you change `CLOB_API_URL` in config, the executor still hits the hardcoded URL.

**Hardening needed:** `LiveExecutor` should read `APP_CONFIG.market_data.clob_api_url` or `CLOB_API_URL` from config instead of hardcoding the URL.

### 3.9 Module-Level Mutation in main.py
`main.py` monkey-patches `config.MAX_BET` and `config.MIN_BET` after import (lines 107–108). Any code that reads these constants at import time rather than at call time will see the pre-patch values. This currently works because all sizing logic calls `risk_manager.recommended_position_size` at runtime. But it is fragile and will silently break if any new code caches these values at module load.

**Hardening needed:** Move the live bet-size overrides to `config.py` or apply them before any module imports that depend on these values.

---

## 4. Live Deployment Preconditions

These must be true before starting a live session. All are binary: yes or no.

- [ ] `POLYMARKET_PRIVATE_KEY` is set to a wallet with a known USDC balance.
- [ ] `LIVE_BALANCE` env var matches the actual USDC balance in the wallet (within $0.10).
- [ ] Wallet has approved the CLOB contract for USDC spending (run `scripts/setup_allowances.py`).
- [ ] `TRADING_MODE=live` is confirmed in the shell before launch.
- [ ] `UPDOWN_15M_STRATEGY_MODE` is confirmed as `shadow` (default). Do not promote to live before meeting the go-live gate in Section 10.
- [ ] `ARBITRAGE_STRATEGY_MODE` is confirmed as `disabled` (default).
- [ ] `BTC_NO_STRATEGY_MODE` is confirmed as `shadow` (default).
- [ ] `POLYMARKET_RELAYER_URL` is either unset (uses hardcoded default) or explicitly set to `https://relayer-v2.polymarket.com`.
- [ ] For safe/proxy wallets: `POLYMARKET_RELAYER_API_KEY` is set and tested by running a manual relayer nonce request against the production URL.
- [ ] For EOA wallets: you understand and accept that winning trades must be redeemed manually via the Polymarket UI or direct contract interaction. There is no auto-redeem in v1.
- [ ] At least 50 shadow-mode trades at matching parameters have been reviewed in `analyze_simulation.py`.
- [ ] The test suite passes: `python -m pytest` exits with zero failures.
- [ ] `events.jsonl` and `trades.jsonl` are either fresh (empty) or reviewed for orphaned open orders from a prior live session.

---

## 5. Required Code Safeguards to Verify

### `config.py`

| Item | What to inspect | What could go wrong | Guardrail | Status |
|---|---|---|---|---|
| `TRADING_MODE` validation | `config.py:118` | Set to garbage string (e.g., `"Live"` with capital L) → silently treated as paper mode | No startup assertion that value is in `{"paper", "simulation", "live"}` | **Missing** |
| `LIVE_MAX_SIZE_EXPANSION` | `config.py:327` | Set to 10.0 via env var → 5-share minimum floor expands a $1 order to $10 | `order_executor.py:1121` checks against this; but the value itself is unconstrained | **Present but uncapped** — env var can set arbitrarily high value |
| Strategy mode env vars | `config.py:167–170` | `UPDOWN_15M_STRATEGY_MODE=live` or `ARBITRAGE_STRATEGY_MODE=live` set in `.env` accidentally | `normalize_strategy_mode()` defaults to disabled for unknown values, but valid values including `live` pass through | **Present normalization** but no startup assertion in live mode |
| `POLYMARKET_RELAYER_URL` | `config.py:140–143` | Typo or old staging URL | No hostname whitelist | **Missing** |
| `POLYMARKET_RELAYER_API_KEY` | `config.py:139` | Empty string → redemption silently disabled but no alert | `redemption_enabled = bool(self.relayer_api_key and self.relayer_type)` in executor; EOA will always have this False | **Present** — redemption gate checks this |

### `engine.py`

| Item | What to inspect | What could go wrong | Guardrail | Status |
|---|---|---|---|---|
| Shadow signal filter | `engine.py:107–110` `_shadow_signal_allowed()` | Shadow 15m signal executes as live | Returns `False` for any `strategy_mode == STRATEGY_MODE_SHADOW` unless `strategy_route == "high_prob_shadow"` | **Present** |
| Cross-mode history isolation | `engine.py:102–104` `_history_matches_current_mode()` | Paper/simulation trades contaminate live balance | Checks `executor_type` against `_EXECUTOR_TYPES_BY_MODE` per mode | **Present** |
| Cycle bet limit | `engine.py:1669` | Unlimited orders in one tick | `cycle_limit = MAX_BETS_PER_CYCLE = 5` in live mode | **Present** |
| Already-traded deduplication | `engine.py:1383–1386` | Same market traded twice | `executed_signal_keys` set checked before execution | **Present** |
| Active-order deduplication | `engine.py:1387–1390` | Second order for same market while first is live | `active_order_markets` set checked before execution | **Present** |
| Balance check before execution | `engine.py:1405–1408` | Trade when insufficient balance | `available_balance < size` → `balance_skip` | **Present** |
| Kill switch propagation | `engine.py:1409–1419` → `risk_manager.check_trade_allowed()` | Losses ignored after kill switch fires | Kill switch checked on every `_try_execute` call via `risk_manager` | **Present** |
| Exception swallowing in `tick()` | `engine.py:1693–1696` | Updown check exception silently suppresses all signals | `except Exception as e: self._log(...)` — broad catch continues tick | **Risk** — exceptions are logged but execution continues silently |

### `level_analyzer.py`

| Item | What to inspect | What could go wrong | Guardrail | Status |
|---|---|---|---|---|
| Reference price staleness | `_refresh_reference_snapshot()` (line 107–119) | Stale CEX price passed to edge calculation → trade on outdated momentum | `ensure_reference_recent()` returns `None` if price is stale; caller must handle `None` return | **Present** — need to verify callers handle `None` correctly |
| Shadow-only coin enforcement | `SHADOW_ONLY_COINS` set + `normalize_strategy_mode()` | Coin in shadow-only set executes live | `SHADOW_ONLY_COINS` env var applies per-coin shadow override | **Present** — verify `SHADOW_ONLY_COINS` is correctly applied in `analyze_updown_market_detail` |
| `LIVE_CONFIDENCE_CAP = 0.90` | `config.py:272` | Overconfident signal enters at max probability with no edge | Confidence is capped at 0.90 in live mode | **Present** |
| Edge calculation with fees | `_polymarket_taker_fee()` in level_analyzer (line 128) | Fee subtracted from wrong side | Fee deducted from gross edge to get net edge | **Present** — verify test coverage |
| No-book edge surcharge | `EARLY_MOMENTUM_NO_BOOK_EXTRA_EDGE = 0.05` (config.py:237) | Missing book bypassed as low-risk | Extra +5% edge required when book is unavailable | **Present** (v14 change) |

### `order_executor.py`

| Item | What to inspect | What could go wrong | Guardrail | Status |
|---|---|---|---|---|
| Size expansion rejection | Lines 1121–1129 | 5-share minimum floor multiplies a small order by 10x | `actual_size > size * LIVE_MAX_SIZE_EXPANSION` → rejection | **Present** |
| Min shares floor | Line 1119 `min_shares = 5.0` | Hardcoded, not from config | If tick_size changes or market changes min lot, floor is wrong | **Hardcoded — not config-driven** |
| Quote staleness rejection | Lines 1049–1059 | Stale execution quote passes entry check | `quote_age > APP_CONFIG.execution.quote_staleness_seconds` (5.0s) → rejection | **Present but has silent bypass** (exception at 1071 swallowed) |
| Depth check bypass | Lines 1060–1071 | `except Exception: pass` skips depth check | No depth fallback — depth check skipped on any exception | **Present but has silent bypass** |
| CLOB URL hardcode | Line 380 `"https://clob.polymarket.com"` | Config `CLOB_API_URL` change has no effect | URL not read from `APP_CONFIG.market_data.clob_api_url` | **Bug** — config and executor out of sync |
| Post-only retry price | Lines 1140–1154 | Retry at lower price with no size re-validation | Retry does not re-check size expansion after price change | **Unclear** — `actual_size = round(shares * limit_price, 2)` recomputed at 1155, but expansion check is not re-run |
| Feed health stale cancel | `_cancel_quote_reason()` line 1244 | Active order not cancelled when feed goes stale | Returns `"feed_health_stale"` if reference age > `FEED_HEARTBEAT_STALE_SECONDS = 3.0` | **Present** |

---

## 6. Runtime Kill Switches and Safety Limits

These are the hard rules. All are currently implemented but their configured values need verification before live deployment.

### Maximum Order Size
**Rule:** No single order may exceed `LIVE_MAX_BET = $5.00`.
**Enforcement:** `risk_manager.recommended_position_size()` caps at `hard_position_cap_pct` of equity, and `main.py` sets `MAX_BET = LIVE_MAX_BET` after import.
**Verify:** Run `python -c "import config; print(config.MAX_BET)"` in live env after `main.py` initialises. Should print `5.0`.
**Gap:** The monkey-patch in `main.py` happens after import. If `MAX_BET` is read at module load time anywhere, the cap is wrong.

### Maximum Exposure Per Market
**Rule:** Only one open position per market slug.
**Enforcement:** `executed_signal_keys` + `active_order_markets` gates in `_try_execute`.
**Verify:** Confirmed present.

### Maximum Exposure Per Coin
**Rule:** `MAX_EXPOSURE_PER_COIN = $10.00`; in live mode overridden to `min(10.0, LIVE_MAX_OPEN_EXPOSURE) = $6.00`.
**Enforcement:** `risk_manager.check_trade_allowed()` checks per-coin exposure across pending trades and open orders.
**Verify:** Confirm `RiskConfig.max_exposure_per_coin = 6.0` in the live `build_risk_config("live")` path in `main.py`.

### Maximum Total Open Exposure
**Rule:** `LIVE_MAX_OPEN_EXPOSURE = $6.00`.
**Enforcement:** `risk_manager.check_trade_allowed()` checks total open exposure.
**Verify:** With a $5 starting balance, a single $5 bet fills the entire exposure budget.

### Maximum Concurrent Orders
**Rule:** `MAX_BETS_PER_CYCLE = 5` per 10-second tick.
**Enforcement:** `cycle_limit` in `engine.tick()` line 1669.
**Note:** With `LIVE_MAX_OPEN_EXPOSURE = $6.00` and `LIVE_MIN_BET = $1.00`, you can have at most 6 simultaneous positions. The `MAX_BETS_PER_CYCLE` limit is advisory; the exposure cap is the binding constraint.

### Maximum Daily Loss
**Rule:** `LIVE_DAILY_MAX_LOSS = $6.00`. Kill switch auto-activates at `2x = $12.00` of daily losses (i.e., if balance goes negative).
**Enforcement:** `risk_manager.py:137–138` and `405–408`.
**Gap:** The kill switch does NOT persist across process restarts. If the process is killed and restarted, the daily loss counter resets. It is reconstructed from trade history in `bootstrap_from_history()`, but only for trades loaded in `_load_history()`. Verify that `bootstrap_from_history` correctly reloads and accumulates today's losses from the CSV.

### Stale Data Shutdown
**Rule:** Reference price older than `MAX_REFERENCE_AGE_SECONDS_REALTIME = 2.0s` (realtime mode) or `MAX_REFERENCE_AGE_SECONDS_FALLBACK = 8.0s` (fallback mode) should block new signals.
**Enforcement:** `level_analyzer._refresh_reference_snapshot()` returns `None` for stale prices; `FEED_HEARTBEAT_STALE_SECONDS = 3.0` triggers order cancellation.
**Gap:** There is no global "pause all trading" trigger if the entire reference feed goes down. Individual signal analyses will block, but the tick loop continues running. Stale data is handled per-signal, not at the session level.

### Relayer/API Failure Shutdown
**Rule:** Repeated redemption failures should not silently accumulate.
**Enforcement:** `_REDEMPTION_RETRY_COOLDOWN_SECONDS = 60.0` prevents tight retry loops. After 3+ failures on the same condition, the status stays `failed` until manually inspected.
**Gap:** There is no aggregate failure counter that triggers a kill switch after N consecutive redemption failures.

### Spread/Liquidity Guard
**Rule:** `MID_FOLLOW_MAX_SPREAD = 3%` (configurable), `LIVE_MAKER_MAX_SPREAD = 4%`. Orders are rejected or cancelled when spread exceeds these limits.
**Enforcement:** `_cancel_quote_reason()` checks spread at line 1225. `level_analyzer` checks spread before generating a signal.

### Duplicate Order Prevention
**Rule:** One order per market slug per session.
**Enforcement:** `executed_signal_keys` (persisted via CSV re-load on startup) and `active_order_markets` (runtime set).
**Gap:** `executed_signal_keys` is populated from `traded_markets` on history load, not from `open_orders`. If an order is live but unfilled and the process restarts, the market slug is NOT in `executed_signal_keys` (only in `active_order_markets` after order reconciliation). However, the `active_order_markets` check is populated from `self.open_orders` which IS loaded from CSV on restart. Reconcile these paths carefully.

### Cooldown After Abnormal Behavior
**Rule:** Per-coin cooldown of 30 minutes after 3 consecutive losses (`PER_COIN_LOSS_STREAK = 3`). Global cooldown of 60 minutes after 5 consecutive losses (`GLOBAL_LOSS_STREAK = 5`).
**Enforcement:** `risk_manager.py` cooldown logic.
**Verify:** These are the default `RiskConfig` values. Confirm that `build_risk_config("live")` in `main.py` does not override these to weaker values. Looking at `main.py:40–59`: `build_risk_config` for live mode only overrides `daily_max_loss`, `max_open_exposure`, `max_exposure_per_coin`, and percentage caps. The per-coin/global loss streak and cooldown defaults come from `RiskConfig()` base — confirm they are the strict values, not `SIMULATION_*` values.

---

## 7. Secret Handling and Environment Validation

### Current State
- `POLYMARKET_PRIVATE_KEY` is read at runtime in `main.py:93` via `os.getenv()`.
- It is passed to `LiveExecutor(private_key=pk)` and then to `Account.from_key(private_key)` and `ClobClient(key=private_key)`.
- The key string is not explicitly zeroed after use.
- `POLYMARKET_RELAYER_API_KEY` is read at module import time in `config.py:139`.

### Required Checks Before Live

1. **`.env` file permissions:** Confirm `.env` is readable only by your user (`chmod 600 .env` on Linux/macOS). On Windows, verify the file is not in a shared or synced directory (Dropbox, OneDrive).

2. **`.env` is in `.gitignore`:** Confirm `git check-ignore .env` reports `.env` is ignored. The security review confirmed this but verify it for your working copy.

3. **`POLYMARKET_PRIVATE_KEY` never appears in logs:** Run `grep -r "POLYMARKET_PRIVATE_KEY" events.jsonl trades.jsonl` — should return no matches. Verify that `log_order_event`, `log_trade_jsonl`, and `log_signal_event` do not serialise the env var or any key material.

4. **`POLYMARKET_RELAYER_API_KEY` in headers:** The `_relayer_headers()` method sends this key in an HTTP header. Confirm this only goes to `self.relayer_url`. If you enable HTTPS termination via a proxy, confirm TLS is not terminated in a way that exposes headers.

5. **Startup env var audit (required manual step):**
   ```bash
   # Run this before starting live mode
   python -c "
   import os
   from dotenv import load_dotenv
   load_dotenv()
   import config
   print('TRADING_MODE:', config.TRADING_MODE)
   print('5M mode:', config.UPDOWN_5M_STRATEGY_MODE)
   print('15M mode:', config.UPDOWN_15M_STRATEGY_MODE)
   print('BTC_NO mode:', config.BTC_NO_STRATEGY_MODE)
   print('ARB mode:', config.ARBITRAGE_STRATEGY_MODE)
   print('RELAYER_URL:', config.POLYMARKET_RELAYER_URL)
   print('LIVE_BALANCE:', config.LIVE_STARTING_BALANCE)
   print('LIVE_MAX_BET:', config.LIVE_MAX_BET)
   print('LIVE_DAILY_MAX_LOSS:', config.LIVE_DAILY_MAX_LOSS)
   print('FUNDER:', config.POLYMARKET_FUNDER)
   print('WALLET_TYPE:', config.POLYMARKET_WALLET_TYPE)
   print('KEY_SET:', bool(os.getenv('POLYMARKET_PRIVATE_KEY')))
   "
   ```
   All values must match your intended configuration before proceeding.

---

## 8. Order Execution and Relayer Safety Checks

### CLOB Order Submission Flow
1. Signal is generated in `level_analyzer.analyze_updown_market_detail()`.
2. Signal passes `_try_execute()` gates (mode, dedup, balance, risk).
3. `execute_paper_trade()` calls `self.executor.place_order(signal, size, entry_price)`.
4. `LiveExecutor.place_order()` performs pre-checks: token_id present, quote age, depth, market drift.
5. `_maker_limit_price()` computes a post-only limit price one tick inside the bid.
6. `_submit_limit_order()` posts a GTC + post-only order via `py-clob-client`.
7. If post-only rejected, retry at one tick lower.
8. `_normalize_submit_response()` creates an `OrderResult` with `needs_reconciliation=True`.
9. Engine creates an `OpenOrder` and persists to `open_orders.csv`.
10. `_reconcile_open_orders()` is called every tick to check fill status.

### Relayer Redemption Flow
1. After market settlement, `settle_trades()` marks won trades with `redemption_status = "pending"`.
2. `_process_redemptions()` is called every tick.
3. For safe/proxy wallets: fetches nonce from relayer, signs redemption calldata, posts to `/submit`.
4. Polls `/transaction` on subsequent ticks until `STATE_EXECUTED` or `STATE_FAILED`.
5. On failure: retries after `_REDEMPTION_RETRY_COOLDOWN_SECONDS = 60s`.
6. For EOA wallets: sets status to `"disabled"` — no auto-redeem.

### Safety Checks to Verify Before First Live Order

- [ ] Run `scripts/setup_allowances.py` and confirm the USDC allowance is set.
- [ ] Confirm `LIVE_MAKER_POST_ONLY = True` (config.py:332). Post-only orders are maker orders — you pay no taker fee and you control your fill price.
- [ ] Confirm `LIVE_MAKER_MAX_AGE_SECONDS = 1.0` for 5m orders. Orders older than 1 second are cancelled by `_cancel_quote_reason()`. This is intentionally tight — live updown markets require fresh execution.
- [ ] For safe/proxy redemption: test the relayer nonce endpoint manually before running live:
  ```bash
  curl "https://relayer-v2.polymarket.com/nonce?address=YOUR_SIGNER_ADDRESS&type=SAFE"
  ```
  Expect a JSON response with a `nonce` field. If this fails, auto-redeem will silently fail for every win.
- [ ] Confirm that `MIN_ORDER_DEPTH_USD = 25.0` and `QUOTE_STALENESS_SECONDS = 5.0` are appropriate for the markets you're trading.

---

## 9. Logging and Auditability Requirements

For every trade, you must be able to reconstruct the following from `events.jsonl` and `trades.jsonl`:

### Why a Trade Was Allowed
Each `signal_event` entry should contain:
- `decision_stage` (must be `"traded"` for executed trades)
- `strategy_mode` (must be `"live"` for real orders)
- `strategy_route` (the specific route: `actual_move`, `mid_follow`, `early_follow`, etc.)
- `confidence`, `edge_gross`, `edge_net`
- `min_edge` (what the minimum edge requirement was at decision time)
- `reason` (the specific pass reason)

**Verify:** After any live trade, open `events.jsonl` and grep for the market slug. Confirm the `signal_event` with `decision_stage=analysis_ready` or the pre-execution state is present.

### What Prices / Edge / Liquidity Were Seen
Each `signal_event` must contain:
- `entry_price`, `best_bid`, `best_ask`, `spread`
- `reference_price`, `reference_age_seconds`
- `book_age_ms`
- `interval_return`, `late_return_60s`, `late_return_20s` (the momentum inputs)

**Verify:** Confirmed — `UpdownAnalysis.to_record()` includes all of these.

### What Config Was Active
- `strategy_version` is written to every `Trade` record (config.py `STRATEGY_VERSION = 14`).
- `trading_mode` is written to each `signal_event` via `engine._emit_signal_events()`.
- **Gap:** There is no startup config snapshot written to `events.jsonl`. If you restart with changed env vars and don't document it, you cannot reconstruct which config was active for a given trade window.
- **Required:** Write a `session_start` event to `events.jsonl` on startup that includes all key config values.

### Order Submission, Fill, Retry, Rejection, Cancellation
- `log_order_event("submit", ...)` — called when open order is created.
- `log_order_event("reject", ...)` — called when executor rejects.
- `log_order_event("cancel", ...)` — called when open order is cancelled.
- `log_order_event("reconcile", ...)` — called on every fill reconciliation.
- **Verify:** All four call sites are present in `engine.py`. Confirm they write to `events.jsonl` and are not silently swallowed.

### Whether Redemption Happened
- `log_redemption_event("submit", ...)` — redemption attempt.
- `log_redemption_event("poll", ...)` — status polling.
- `log_redemption_event("disabled", ...)` — EOA wallet case.
- **Verify:** Confirmed present in `engine._process_redemptions()`.

### Whether Live Mode Was Definitely Intended
- `TRADING_MODE` is logged in `signal_event` entries.
- `executor_type = "LiveExecutor"` is written to every `Trade` record.
- **Required:** The `session_start` event (see config snapshot gap above) should include `trading_mode` and `executor_type`.

---

## 10. Shadow-to-Live Promotion Checklist

Do not promote any strategy to live without meeting ALL of the following gates. These are measurable, not advisory.

### 5m Strategy (currently LIVE — verify it meets gates)

| Gate | Threshold | How to Measure |
|---|---|---|
| Minimum sample size | ≥ 50 settled trades at `strategy_version=14` | `analyze_simulation.py` — filter `strategy_version == 14` |
| Win rate | ≥ 52% | `analyze_simulation.py` win rate output |
| Profit factor | ≥ 1.1 | `analyze_simulation.py` profit factor output |
| Average net PnL per trade | > 0.0 (positive) | `analyze_simulation.py` average PnL output |
| Max drawdown in sample | ≤ 25% of starting balance | Manual calculation from trade history |
| Fill rate (live fills / live attempts) | ≥ 85% | Count `executor_type=LiveExecutor` trades with `status=won/lost` vs. total submitted |
| Avg slippage vs expected | ≤ 1.5% | `markout_1s` field — compare to `expected_fill_price` |

### 15m Strategy (currently SHADOW — gates before live promotion)

| Gate | Threshold | How to Measure |
|---|---|---|
| Minimum shadow sample size | ≥ 200 resolved shadow signals | Count `signal_event` with `strategy_mode=shadow`, `signal_status in {won, lost}` |
| Shadow win rate | ≥ 58% (higher bar because smaller sample | Shadow signal events |
| Shadow profit factor | ≥ 1.2 | Shadow signal event P&L reconstruction |
| No anomalous routes | No route with < 45% win rate and > 10 samples | Per-route breakdown |
| Code review of `WINDOWS_15M` timing windows | Manual inspection | Verify 25–70s and 180–480s windows have separate confirmation |

### BTC NO Strategy (currently SHADOW)

| Gate | Threshold |
|---|---|
| ≥ `BTC_NO_MIN_SHADOW_SAMPLES = 200` shadow samples | Required by config |
| Win rate ≥ 55% in shadow | Must beat random |
| No correlation with 5m BTC YES losses | Cross-analysis required |

### DO NOT promote any strategy to live if:
- The last 10 live trades show a loss rate > 70%.
- The kill switch has fired in the current session.
- Any reference feed coin has been stale for > 10 minutes in the current session.
- `analyze_simulation.py` shows a "no-go" recommendation for the current patch.

---

## 11. Manual Pre-Flight Checklist

Run this before every live session start.

```
PRE-FLIGHT CHECKLIST — Polymarket Bot v14 Live Mode
Date: ____________________
Starting balance: $____________________

ENVIRONMENT
[ ] TRADING_MODE=live confirmed in shell
[ ] LIVE_BALANCE matches actual wallet USDC balance (within $0.10)
[ ] POLYMARKET_PRIVATE_KEY is set (not empty)
[ ] POLYMARKET_RELAYER_URL is "https://relayer-v2.polymarket.com" or unset
[ ] UPDOWN_15M_STRATEGY_MODE=shadow confirmed
[ ] ARBITRAGE_STRATEGY_MODE=disabled confirmed
[ ] BTC_NO_STRATEGY_MODE=shadow confirmed
[ ] Strategy mode audit script run (Section 7) — all values match intent

WALLET
[ ] Wallet USDC balance confirmed on Polymarket dashboard
[ ] USDC allowance confirmed (scripts/setup_allowances.py run recently)
[ ] For safe/proxy: relayer nonce endpoint confirmed reachable
[ ] For EOA: acknowledged that winning trades require manual redemption

DATA
[ ] events.jsonl opened and inspected for anomalies from prior session
[ ] trades.jsonl opened — all open trades from prior session are settled or reconciled
[ ] open_orders.csv is empty OR all persisted orders are known and expected

CODE
[ ] python -m pytest exits 0
[ ] git status is clean (no uncommitted config changes)
[ ] STRATEGY_VERSION=14 confirmed in config.py

LIMITS
[ ] LIVE_MAX_BET=$5.00 confirmed
[ ] LIVE_DAILY_MAX_LOSS=$6.00 confirmed
[ ] LIVE_MAX_OPEN_EXPOSURE=$6.00 confirmed
[ ] MAX_BETS_PER_CYCLE=5 confirmed

GO / NO-GO DECISION
[ ] Analysis of last 50+ trades shows positive expectancy
[ ] No kill switch events in last session
[ ] Bot operator will monitor dashboard for first 30 minutes
```

---

## 12. Post-Deployment Monitoring Plan

### First 30 Minutes (Hands-on)
- Watch the Rich dashboard continuously.
- Verify the first signal fires with `strategy_mode=live` and `decision_stage=traded`.
- Confirm the `order_live` or `traded` stage appears in the monitor within the first tick.
- Open `events.jsonl` and verify `log_order_event("submit", ...)` was written.
- Check `open_orders.csv` — the open order should appear and then disappear within 1–2 ticks as it reconciles.

### Every 30 Minutes (Active Session)
- Check `total_pnl` on dashboard. If negative beyond `LIVE_DAILY_MAX_LOSS / 2 = $3.00`, review manually.
- Check kill switch status on dashboard (`risk_manager.kill_switch_active`).
- Check reference feed health — all tracked coins should show reference age < 3s.
- Confirm no `redemption_status=failed` entries accumulating in `events.jsonl`.

### After Every Settled Trade
- Run `python analyze_simulation.py` (or a mode-filtered version) to check rolling stats at `strategy_version=14`.
- If fill rate drops below 85%, review `order_rejected` entries in `events.jsonl` to identify the rejection reason.
- If slippage (from `markout_1s` vs `expected_fill_price`) exceeds 1.5% consistently, investigate book conditions.

### Daily
- Confirm all winning trades have a `redemption_status` that is not `failed`.
- For EOA wallets: manually check Polymarket UI for redeemable positions.
- Review the daily loss tally against `LIVE_DAILY_MAX_LOSS = $6.00`.
- Back up `trades.jsonl`, `events.jsonl`, and `trades.csv`.

### Automated Alerts (Not Yet Implemented — Required Before Scale-Up)
The following are not currently implemented and should be added before increasing position sizes:

- Alert when kill switch activates.
- Alert when `redemption_status=failed` count > 2 for a given condition.
- Alert when reference feed is stale for > 30 consecutive seconds.
- Alert when fill rate for the session drops below 80%.

---

## 13. Rollback Plan

### Immediate Halt (Kill Switch)
```python
# From Python REPL or a script:
engine.risk_manager.activate_kill_switch("manual: operator halt")
```
This blocks all new order submission. Existing open orders are NOT cancelled — they remain live on Polymarket until they fill or expire.

To also cancel all open orders:
```python
for order in engine.open_orders:
    engine.executor.cancel_order(order.order_id)
```

### Process Kill
- `Ctrl+C` in the dashboard terminal triggers the `shutdown()` handler, which calls `engine.stop()`.
- `engine.stop()` calls `stop_runtime_services()` and shuts down the background executor.
- Open orders on Polymarket are NOT cancelled on process exit — they remain live.
- **Required manual step:** If you kill the process, log into the Polymarket UI and cancel any open orders manually, or run the cancel loop above before exiting.

### Switching to Paper Mode
1. Stop the live process.
2. Change `TRADING_MODE=paper` in `.env`.
3. Restart.
4. `_load_history()` will ignore all `LiveExecutor` trades because `_history_matches_current_mode` filters by executor type.
5. The paper session starts fresh.

### Recovery After Unexpected Restart
1. Confirm `open_orders.csv` has the correct state.
2. On startup, `_reconcile_open_orders()` is called automatically to catch any fills during downtime.
3. Confirm `events.jsonl` shows `order_reconcile` events for any orders that were live.
4. If `open_orders.csv` is missing or corrupted, query the Polymarket UI for open orders directly.

---

## 14. Highest-Priority Improvements

Ranked by impact on live safety, independent of the security review.

### Priority 1: Startup Config Validation in Live Mode (High Impact, Low Effort)
Add an assertion block in `main.py` before `LiveExecutor` is instantiated that:
- Asserts `TRADING_MODE == "live"` (not truthy, literal equality).
- Prints the full effective configuration (strategy modes, limits, relayer URL).
- Asserts `POLYMARKET_RELAYER_URL` contains `polymarket.com` if relayer redemption is enabled.
- Asserts `UPDOWN_15M_STRATEGY_MODE != "live"` and `ARBITRAGE_STRATEGY_MODE != "live"`.

This is 15 lines of code that prevents the most common class of operational errors.

### Priority 2: Session Start Event in events.jsonl (High Impact, Low Effort)
Write a `session_start` event at bot startup that captures:
- `trading_mode`, `strategy_version`, all strategy modes, all risk limits, relayer URL (not key), wallet type.
- This makes post-hoc audit possible and immediately reveals config drift between sessions.

### Priority 3: Fix CLOB URL Drift in LiveExecutor (Medium Impact, Trivial Effort)
Replace `"https://clob.polymarket.com"` hardcode in `order_executor.py:380` with `APP_CONFIG.market_data.clob_api_url`. Currently harmless, but a future config change would silently have no effect.

### Priority 4: Depth Check Silent Bypass Fix (Medium Impact, Low Effort)
In `LiveExecutor.place_order()`, the `except Exception: pass` at line 1071 silently skips both quote staleness and depth checks. This should either re-raise or explicitly reject the order with reason `"market_data_unavailable"`. Silent bypass means you trade with no liquidity validation when the market data client is flaky.

### Priority 5: Kill Switch Persistence Across Restarts (Medium Impact, Medium Effort)
The kill switch resets on process restart. `bootstrap_from_history()` partially reconstructs state, but the kill switch itself is not persisted. Add a `kill_switch_state.json` or JSONL record that persists the kill switch state and is loaded on startup. This prevents accidentally resuming after a loss limit breach.

### Priority 6: Min Shares Config-Driven (Low Impact, Low Effort)
Replace `min_shares = 5.0` hardcode in `order_executor.py:1119` with a config constant. As markets change their minimum lot sizes, this needs to be adjustable without a code change.

### Priority 7: Live Balance Reconciliation Against Wallet (High Impact, Medium Effort)
After loading trade history, call the Polymarket positions API to get the actual USDC balance in the wallet and compare it to the computed balance. A discrepancy above `LIVE_MIN_BET = $1.00` should trigger a warning (or halt). This is the only way to catch balance drift from manually placed orders, cancelled orders with unreleased funds, or CSV corruption.

### Priority 8: Duplicate Order Prevention After Crash Recovery (Medium Impact, Medium Effort)
On startup, query the Polymarket CLOB for any open orders associated with the wallet and add them to `executed_signal_keys` before processing any new signals. Currently, if the bot crashes after submitting an order but before writing to `open_orders.csv`, the market slug is not protected and a second order may be placed on the next startup.

---

*Plan written 2026-04-17. Re-verify all code references before each live session — file contents change, this document does not auto-update.*
