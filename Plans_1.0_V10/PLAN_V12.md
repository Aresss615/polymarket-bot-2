# v12 Plan: Candle-Aware Crypto Engine + Wallet-Intelligence Shadow Research

## Summary
- Primary live path stays deterministic and crypto-first. We will stop letting the bot take contrarian mispricing trades against an obviously strong 5m/15m candle.
- Copy trading is included only as a shadow research module, not a live executor. The official Polymarket data shows top-wallet performance is heterogeneous and raw leaderboard PnL is not pure trading alpha because activity can include `MAKER_REBATE` and `REFERRAL_REWARD`.
- Research findings to lock into the plan:
  - Your current bot only uses a short reference return and z-score, so it can disagree with the full interval candle you see on the chart.
  - Top crypto wallets are not all doing the same thing. In the official crypto leaderboard sample, several top wallets are BTC-heavy up/down traders, while others are range/level basket traders.
  - Top-wallet activity often includes late, high-probability entries and large size. That is not directly copyable for a small bankroll at the same price.
- Evidence base:
  - Official RTDS crypto feeds: https://docs.polymarket.com/market-data/websocket/rtds
  - Official fees + maker rebates: https://docs.polymarket.com/trading/fees
  - Official leaderboard UI: https://polymarket.com/leaderboard/overall/today/profit
  - Official public data endpoints used for research:
    - `https://data-api.polymarket.com/v1/leaderboard?category=CRYPTO&timePeriod=ALL&orderBy=PNL&limit=10`
    - `https://data-api.polymarket.com/activity?user=<wallet>&limit=25`
    - `https://data-api.polymarket.com/closed-positions?user=<wallet>&limit=20`

## Key Changes
- Add a forensic trade-alignment layer so every trade can answer:
  - what the reference candle did over the full contract interval
  - what the last 60s and last 20s did
  - what Polymarket YES/NO prices did between contract open, decision time, and settlement
  - whether the trade was `follow_trend`, `contrarian`, `uncertain_mispricing`, or `late_reversal`
- Extend the reference state and trade analysis data model with:
  - `interval_open`, `interval_high`, `interval_low`, `interval_close`
  - `interval_return`, `late_return_60s`, `late_return_20s`
  - `body_ratio`, `wick_imbalance`, `candle_regime`, `trend_alignment`
  - `market_yes_at_open`, `market_yes_at_decision`, `market_yes_at_close`
  - `selected_side_probability`, `contrarian_block_reason`
  - `wallet_signal_source`, `wallet_lead_score`, `wallet_cluster`
- Replace the current “mispricing everywhere” rule in `level_analyzer.py` with a regime gate:
  - `trend_strong` if all are true:
    - 5m `abs(interval_return) >= 0.25%`
    - 15m `abs(interval_return) >= 0.45%`
    - `abs(late_return_60s) >= 0.08%` for 5m or `>= 0.12%` for 15m
    - `abs(late_return_20s) >= 0.03%` for 5m or `>= 0.05%` for 15m
    - interval, 60s, and 20s return signs all match
    - `body_ratio >= 0.60`
  - `trend_mixed` if interval and late returns disagree or `body_ratio < 0.40`
  - `uncertain` otherwise, and always if interval move is under `0.15%` for 5m or `0.25%` for 15m
- Trading policy by regime:
  - `trend_strong`: only allow the follow-trend side; block contrarian trades entirely
  - `trend_mixed` or `uncertain`: allow mispricing trades if existing edge rules still pass
  - `near_certain` (`entry_price >= 0.97` or `<= 0.03`): track in shadow only for now, do not live-trade as a primary strategy
- Keep BTC toxic-flow logic, but generalize the anti-countertrend rule to every coin in `trend_strong`.
- Make the explanation text side-aware:
  - always show model `UP` probability, selected side probability, market selected-side price, and the reason the selected side was considered underpriced
  - remove the misleading pattern where a `NO` trade reads like it “bought the 92% side”
- Recalibrate confidence:
  - cap live confidence to `0.90`
  - cap `trend_mixed` and `uncertain` setups to `0.75`
  - stop using the current saturating pattern that pins many trades at `0.99`
- Make sizing regime-aware:
  - `trend_strong` follow-trend: `1.25x` base size
  - `uncertain` mispricing: `1.0x`
  - `trend_mixed`: `0.5x`
  - `contrarian` in `trend_strong`: `0x`
  - price bucket cap: if `entry_price < 0.10` or `> 0.90`, live size max is `0.5x`
- Add a wallet-intelligence shadow module:
  - build a daily crypto wallet universe from top 20 all-time and top 20 monthly leaderboard wallets
  - fetch public activity and closed-position samples, then classify wallets as `updown_directional`, `range_basket`, `late_certainty`, or `rebate_heavy`
  - exclude wallets from copy scoring if non-trade activity is too high, supported-crypto share is too low, or most fills are only at extreme prices
  - compute `lead_score`, `fillability_score`, `consistency_score`, and `spoof_penalty`
  - publish a shadow-copy blotter with 1-tick and 2-tick worse-fill assumptions
- Add a smarter layer, but shadow-only:
  - train an offline ranker/calibrator on deterministic features plus wallet-flow features
  - output `model_ev_shadow` and `model_veto_shadow`
  - do not let ML decide live trades until it proves uplift against the deterministic baseline

## Interfaces And Analytics
- Extend `price_feed.py` / `state_cache.py` so the reference cache can return interval OHLC-style features, not just one lookback return.
- Extend `UpdownAnalysis`, `Trade`, and JSONL event payloads with the regime and candle-alignment fields above so every trade is auditable.
- Extend `analyze_simulation.py` or add a dedicated trade-alignment report to produce:
  - PnL by `follow_trend`, `contrarian`, `uncertain_mispricing`, `late_reversal`
  - PnL by price bucket
  - PnL by coin and by 5m vs 15m
  - shadow wallet-copy markouts and slippage-adjusted PnL

## Test Plan
- Unit tests:
  - candle feature calculation from reference history
  - regime classification at each threshold boundary
  - strong-trend contrarian blocking
  - side-aware reason text for YES and NO trades
  - confidence capping and regime-based sizing
  - wallet scoring filters for rebate-heavy and extreme-price-only wallets
- Integration and replay tests:
  - replay the most recent settled trades and verify each gets a correct regime label and alignment explanation
  - compare baseline strategy vs candle-aware regime strategy on historical paper/simulation trades
  - compare deterministic baseline vs shadow wallet-copy vs deterministic-plus-shadow-model
- Acceptance criteria:
  - every recent trade can be explained by candle regime and selected-side logic
  - live candidates contain zero strong-trend contrarian trades
  - shadow wallet report identifies wallet cluster, lead score, and worse-fill PnL
  - ML remains shadow-only unless it beats the deterministic baseline over at least 1000 shadow opportunities

## Assumptions And Defaults
- Locked choices from this planning turn:
  - main path: safer hybrid
  - copy mode: shadow only
- 5m remains the primary live market family. 15m remains shadow-first until separately validated under the new regime logic.
- Small-bankroll priority is EV and survivability, not chasing 99-cent “sure winners” that are hard to copy and produce weak risk-adjusted returns.
- Public wallet activity is assumed good enough for research and shadow scoring, but not fast enough to justify automatic live copy execution.
- No LLM is put on the hot path for crypto trading. LLMs may remain research-only for labeling, reporting, and clustering.
