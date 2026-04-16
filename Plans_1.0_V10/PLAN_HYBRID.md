# Hybrid High-Activity Bot Upgrade

**Summary**
- The current repo is skipping by design, not because tests are failing: `events.jsonl` shows 2,256 signal events and all 2,256 ended as `analysis_skip`.
- The biggest blockers are feed quality and gating strictness: 1,429 skips were `reference data stale`, 340 were `15m requires fresh Chainlink reference`, 185 were `missing trusted exact window open`, 156 were `flat window shadow only`, and 120 were `mid regime no trade`.
- On `2026-04-15 16:59:44+00:00`, the feed was fresh (`reference_age_seconds=0.0`) and the bot still skipped BTC/SOL/BNB/DOGE/ETH/XRP because the current 5m logic only trades “strong” moves; the skipped “mid” moves were typically about `0.12%` to `0.20%`, while the current 5m strong threshold is `0.30%`.
- The TypeScript repo is the real reference for copy-trading behavior. The Rust toolkit is useful for copy-trading safety ideas, but its arbitrage/direction/orderbook bots are mostly stubs, so we should port copy-trading flow and risk concepts, not pretend those unfinished strategies are production code.

**Implementation Changes**
- Make feed startup explicit instead of silent: on boot, log `sys.executable`, whether `websocket-client` imported successfully, whether RTDS workers started, and whether the bot is in `realtime` or `poll-fallback` mode.
- Replace the current silent RTDS failure path with resilient fallback behavior: if RTDS is unavailable or stale, keep warming active coins via REST polling and treat reference data as usable up to `8s` old in fallback mode instead of hard-failing at `2s`.
- Keep the strict `2s` freshness rule only when RTDS is healthy; expose both thresholds in config so we can tune without code edits.
- Change window-open handling so the analyzer no longer hard-skips every market without a perfect anchor: keep `2s` as “trusted exact open”, allow a degraded nearest-anchor fallback up to `8s`, and only force shadow/skip when no usable anchor exists at all.
- Retune 5m price-action logic for a high-activity profile: lower `ACTUAL_MOVE_STRONG_RETURN_5M` from `0.30%` to `0.16%`, keep flat handling around `0.08%`, and add a new `mid_follow_candidate` route for `0.12%` to `0.16%` moves that have strong body, aligned late momentum or aligned orderbook pressure, fresh book, and positive net edge.
- Keep the existing “flat window shadow only” behavior for genuinely flat/noisy candles; do not open the door to flat/no-body trades.
- Stop hard-coding live 5m trading to only BTC/SOL. Replace `CANDIDATE_COINS`/`SHADOW_ONLY_COINS` with env-driven allowlists, and default the live 5m set to `BTC,ETH,SOL,XRP,DOGE,BNB,HYPE`.
- Keep 15m shadow-only in this pass. We will fix its feed path and diagnostics, but not promote it live yet.
- Use the existing market-cache microstructure data as a real confirmation layer: `mid_follow_candidate` must pass book-age, spread, and OBI alignment checks before it can trade.
- Port the TypeScript repo’s copy-trading flow into Python as a first-class strategy lane: Data API `/activity` polling, zero-point seeding, dedupe by tx/outcome/price/size/timestamp, single-wallet config, global “any market” scope, and configurable size percent/min/max.
- Do not port the TS order-posting code directly. Reuse the current Python executor and risk manager so copy trades and momentum trades share the same sizing, logging, and live/sim execution path.
- Refactor execution entry into a serialized `Engine.process_signal(...)` path so the new copy-trading worker can submit signals immediately without waiting for the 10s engine tick.
- Add a copy-trading safety layer inspired by the Rust toolkit: optional minimum target-trade size, repeated large-trade detection, depth-beyond-order check, and temporary reduce-only cooldown on toxic burst activity.
- Extend monitor/status output with feed health per coin, current feed mode, last RTDS heartbeat, last copy-trade event, and per-route counts so “why did it skip?” is visible without digging through JSONL.

**Config and Interfaces**
- Add env/config for feed behavior: `RTDS_STRICT_MODE`, `MAX_REFERENCE_AGE_SECONDS_REALTIME`, `MAX_REFERENCE_AGE_SECONDS_FALLBACK`, `WINDOW_OPEN_TRUST_TOLERANCE_SECONDS`, `WINDOW_OPEN_DEGRADED_TOLERANCE_SECONDS`.
- Add env/config for aggressive 5m trading: `LIVE_CANDIDATE_COINS`, `ACTUAL_MOVE_STRONG_RETURN_5M`, `MID_FOLLOW_MIN_RETURN_5M`, `MID_FOLLOW_MIN_BODY_RATIO`, `MID_FOLLOW_MAX_SPREAD`, `MID_FOLLOW_MAX_BOOK_AGE_MS`.
- Add env/config for copy trading: `ENABLE_COPY_TRADING`, `COPY_TARGET_WALLET`, `COPY_POLL_INTERVAL_MS`, `COPY_ACTIVITY_LIMIT`, `COPY_SIZE_PERCENT`, `COPY_MIN_SIZE`, `COPY_MAX_SIZE`, `COPY_MIN_TARGET_SHARES`, `COPY_LARGE_TRADE_SHARES`, `COPY_CONSECUTIVE_TRIGGER`, `COPY_MIN_DEPTH_USD`, `COPY_TRIP_SECONDS`.
- Add a `CopyTradingService`/`CopyTradeCandidate` layer rather than folding copy logic into `copy_main.py` only; `copy_main.py` can remain as a focused runner, but the main engine should also be able to start the same service when `ENABLE_COPY_TRADING=1`.
- Add `Engine.process_signal(signal, source=...)` and route both up/down analysis and copy-trading signals through it so execution, risk checks, logging, and open-order handling stay consistent.

**Test Plan**
- Add feed tests proving RTDS import failure does not silently disable trading and that fallback polling keeps references fresh enough to analyze.
- Add analyzer tests for the new `mid_follow_candidate` route: `0.12%` to `0.20%` aligned moves should trade when edge/book conditions pass, while flat/noisy moves should still skip.
- Add config/risk tests proving env-driven live coin allowlists replace the current BTC/SOL hard-code and that 15m remains shadow-only.
- Add copy-trading tests for zero-point seeding, dedupe, single-wallet config, percent/min/max sizing, invalid trade skip paths, and immediate engine submission through `process_signal`.
- Add safety tests for large-trade burst detection, depth guard, and temporary reduce-only cooldown.
- Run the existing analyzer, engine, copy-trading, risk, and execution preflight test suites after the change and add one integration test covering both a momentum signal and a copied trade in the same session.

**Assumptions**
- Target architecture is the aggressive hybrid path: fix feed resilience, make 5m momentum materially less conservative, and add a single-wallet copy-trading lane.
- Single-wallet copy trading will use the existing `COPY_TARGET_WALLET` style configuration; wallet discovery/ranking is out of scope for this pass.
- Default execution remains `simulation` until you explicitly switch to live.
- We will port working behavior from the reference repos, not their UI/frontend, and we will not spend time copying unfinished Rust strategy stubs that do not contain real trading logic.
