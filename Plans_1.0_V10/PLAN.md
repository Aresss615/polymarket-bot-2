# Codex 1.1 / v11 Deterministic Engine Plan

## Status
- This file supersedes the old v10 two-day simulation research plan.
- The repo is no longer in the old "two strategies competing live" phase. The core v11 shift is already implemented in code:
  - live LLM/news trading is removed from the execution path
  - strategy modes now exist explicitly as `disabled`, `shadow`, or `live`
  - the crypto UpDown path uses a deterministic, fee-aware net-edge model
  - trade/order persistence now carries edge, reference, latency, spread, thesis, and cancel metadata
  - analytics and log readers are BOM-safe and replay-friendly again
  - risk controls now include equity-based sizing, correlation caps, and cooldown logic
- This means the next plan should not be "do another generic 48h sim and hope." It should be "finish the event-driven data plane, prove shadow EV, then promote deliberately."

## Summary
- Objective: maximize expected value and survivability, not promise profits.
- Product decisions stay locked:
  - `crypto-first`
  - `Python-first`
  - `reference-only expansion`
  - `LLM/news disabled for trading`
- The current repo is materially stronger than v10, but it is still not the finished version of the v11 vision.
- The best path now is to finish the execution/data integrity layer, not to add more prediction logic.

## What Is Already Done
- Runtime architecture:
  - `engine.py` only routes live execution through the deterministic crypto path
  - `arbitrage` and news remain research-only, not order-producing
  - `shadow` signals are analyzed and logged without touching capital
- Signal model:
  - deterministic net-edge scoring in `level_analyzer.py`
  - stale-reference rejection
  - 5m window tightened to the late trade window
  - 15m kept shadow-only by default
  - BTC toxic-flow logic added instead of the old crude blacklist-only behavior
- Persistence and analytics:
  - `Trade`, `OrderResult`, and `OpenOrder` now carry richer execution metadata
  - CSV and JSONL readers tolerate BOMs and malformed header rows
  - `analyze_simulation.py` can replay the current logs again
- Risk and execution:
  - maker-first live execution remains the default
  - cancel rules are stricter and more state-aware
  - risk sizing is now equity-aware and thesis-aware
  - same-coin and same-thesis concentration controls exist

## Highest-Priority Gaps
- The biggest remaining gap is the real-time data plane:
  - Polymarket Market WS is not yet the primary runtime source of book state
  - Polymarket User WS is not yet the primary truth source for fills and order transitions
  - RTDS is not yet the hot-path reference source for crypto and Chainlink updates
- The second biggest gap is replay integrity:
  - execution is improved, but the repo still needs a true stream-replay harness for restart parity using recorded WS/User events
- The third gap is promotion discipline:
  - the code can shadow and log, but the repo still needs a stronger promotion/reporting layer that explicitly answers "should this strategy graduate?"

## Revised Next Plan

### Phase 1: Finish the Real-Time Data Plane
- Wire Polymarket Market WS into `state_cache.py` for:
  - `book`
  - `best_bid_ask`
  - `price_change`
  - `market_resolved`
- Wire RTDS into `state_cache.py` / `price_feed.py` for:
  - `crypto_prices`
  - `crypto_prices_chainlink`
- Wire Polymarket User WS into execution state for:
  - order accepted
  - partial fill
  - full fill
  - cancel
  - reject
- Keep REST only as reconnect/reconciliation fallback, not primary truth.

### Phase 2: Make Execution Truly Event-Sourced
- Add explicit order/trade event application by `order_id`.
- Ensure only confirmed fill deltas can mutate:
  - position size
  - reserved exposure
  - fees
  - realized P&L state
- Add replay tests that prove:
  - no duplicate fills after restart
  - no phantom exposure
  - no silent close of unresolved positions

### Phase 3: Upgrade Promotion and Shadow Analytics
- Add a dedicated shadow-performance report for:
  - 5m deterministic crypto
  - 15m deterministic crypto
  - BTC NO specifically
  - thesis buckets
  - edge buckets
  - latency buckets
- Add explicit promotion gates in code or docs, not just in conversation:
  - 5m goes live only after `200` shadow opportunities with positive net shadow P&L
  - BTC NO stays shadow until its own positive sample clears independently
  - 15m stays shadow until its own bar clears independently

### Phase 4: Add Structural Arb in Shadow Only
- Build bounded, fee-aware shadow modules for:
  - YES/NO parity checks
  - neg-risk basket checks
- Do not add broad combinatorial optimization yet.
- Only graduate structural arb if executable depth is clearly large enough relative to planned size.

### Phase 5: Add Read-Only External Validation
- Add read-only Kalshi market data connectors.
- Use them for:
  - market sanity checks
  - monitoring
  - shadow comparison
- Do not add multi-venue execution in this phase.

## Suggestions

### Suggestion 1: Freeze Strategy Logic Before Adding New Alpha
- Do not widen the signal logic again right now.
- The current mistake to avoid is layering more prediction ideas on top of a half-finished execution/data stack.
- The next edge will come more from better state, faster invalidation, and cleaner replay than from fancier directional logic.

### Suggestion 2: Treat Shadow as the Main Product For Now
- The most valuable next dataset is not "another mixed sim."
- It is a clean shadow log driven by RTDS + Market WS + User WS, with deterministic gating and accurate latency/reconciliation metrics.
- That dataset should answer whether the current filters survive live-like conditions.

### Suggestion 3: Track Detect-to-Decision and Decision-to-Order Separately
- Right now latency is being logged, but the next iteration should separate:
  - data arrival to signal detection
  - signal detection to decision
  - decision to submit
  - submit to exchange acknowledgement
- This matters because a strategy can look correct while still dying from late action.

### Suggestion 4: Add a Daily "Do Not Promote" Report
- Every day, produce a compact report with:
  - shadow P&L
  - p95 latency
  - feed-staleness rate
  - cancel-rate by reason
  - worst thesis clusters
  - worst coin-side buckets
- If any of those break the gates, promotion should be blocked automatically.

### Suggestion 5: Keep News Disabled Until the Core Engine Is Proven
- The repo evidence and external research still point the same way:
  - LLM/news is fine for labeling and offline study
  - it is not trustworthy as the fast capital-allocation brain for this system
- The fastest way to regress again would be to re-open that live path prematurely.

## Concrete Next Implementation Order
1. Add Market WS + RTDS ingestion into `state_cache.py`.
2. Add User WS event handling and idempotent order application into `engine.py` / execution state.
3. Add recorded-stream replay tests and restart parity tests.
4. Add shadow promotion reporting by edge, coin, thesis, and latency.
5. Add shadow-only structural arb scans.
6. Add read-only Kalshi validation feeds.

## Test Plan
- Unit tests:
  - WS event application is idempotent by `order_id`
  - RTDS updates refresh reference state correctly
  - stale heartbeat blocks quoting/cancels quotes
  - shadow/live/disabled modes behave exactly as intended
  - thesis and coin caps block correlated buildup
- Integration tests:
  - replay recorded Market WS + User WS streams through restart boundaries
  - simulate partial fills, cancels, delayed settlements, reconnects, and stale references
  - verify ledger parity after replay
- Acceptance gates:
  - no duplicate fill booking after restart
  - no exposure drift after replay
  - `p95 detect-to-order < 800ms` on the 5m path
  - positive net shadow P&L after fees for 5m before promotion
  - 15m and BTC NO must each clear their own shadow bar separately

## Assumptions
- Profit is never guaranteed.
- The deliverable is a higher-EV, lower-blowup, more measurable system.
- Live trading remains Polymarket-only for now.
- The best current move is depth and integrity, not breadth.
- The repo should be judged by promotion gates and replay integrity, not by isolated screenshot wins or one-off anecdotal trades.
