# Production-Ready Architecture for a Crypto Prediction-Market Bot

## System goals and threat model

You’re not trying to “be right” often; you’re trying to **compound positive expectancy under real execution**—latency, partial fills, stale books, fee drag, and outages. That framing matters more on prediction-market CLOBs (central limit order books) because your edge is often thin, and “taker convenience” can quietly eat it.

Two practical realities shape the design:

First, many crypto prediction-market venues operate like a CLOB: orders rest, match, and clear like an exchange. For example, entity["company","Polymarket","prediction market platform"] documents that all orders are expressed as limit orders, and “market orders” are effectively limit orders priced to execute immediately against resting liquidity.citeturn8view0turn8view2

Second, **latency is not optional risk**; it’s part of the strategy’s PnL distribution. Academic microstructure work defines latency as a multi-layer delay (market data → your processing/decision → order submission/processing), and shows it materially affects fill outcomes.citeturn3view0 A large live crypto execution experiment (Bybit/Binance) argues that discrepancies between expected vs realized fills are driven by latency and order book updates, and that taker orders can suffer adverse selection (profitable orders get worse-than-expected outcomes).citeturn18view0

Given your constraints, the bot must be built around:

- **Expected value (EV) as the primary objective**, measured net of fees + slippage + delay (not “win rate”).  
- **Correlation-aware portfolio construction** to avoid single-regime wipeouts—especially because crypto correlations can rise sharply in down markets, reducing diversification right when you need it.citeturn14view0  
- **Execution as a first-class system**, where you can bound slippage and control fill/kill behavior with order types and time-in-force rather than hoping the venue behaves.citeturn8view0turn9view1  
- **Promotion gates** that explicitly validate (a) edge, (b) execution realism, and (c) operational resilience before scaling live.

## Recommended system architecture

The architecture below is intentionally “solo-builder realistic”: a small number of services/processes, clean boundaries, and strict risk gates so your mistakes don’t scale.

### Core design choice: intent-driven trading with hard risk gates

Instead of “strategy places orders,” use **Trade Intents**:

1. Strategy outputs an *intent* (desired exposure change + max acceptable costs).  
2. A risk engine either approves (possibly resizing) or rejects.  
3. Execution converts approved intents into venue-specific orders and manages their lifecycle.

This mirrors institutional separation between decision/risk and execution/OMS/EMS concepts (even if you implement them in one repo).citeturn0search15turn0search23

### Minimum viable production topology

Run these as separate processes (Docker Compose is enough):

**Market Data Service**
- WebSocket ingestion (order book, trades, best bid/ask, venue status).
- Maintains an in-memory “latest book” + writes snapshots to Redis (fast) and Postgres (durable).
- Emits “market state ticks” to the strategy runner at a fixed cadence (e.g., 200–1000ms depending on horizon).

**Strategy Runner**
- Loads per-coin config.
- Produces Trade Intents (not orders).
- Records every decision (including “no-trade”) for shadow evaluation.

**Risk Engine (pre-trade + portfolio)**
- Stateless approval endpoint (in-process library is fine), but **stateful inputs**:
  - current positions + working orders
  - portfolio exposures + correlation groups
  - current latency/slippage telemetry
- Implements “deny by default” on missing/stale data.

**Execution Engine / OMS**
- Venue adapters (one per venue): signing/auth, order submit/cancel/replace, reconciliation.
- Order lifecycle state machine:
  - `created → sent → acked → resting|partial → filled|canceled|rejected|expired`
- Periodic reconciliation loop:
  - pull open orders + balances/positions from venue and reconcile local state (critical after disconnects).

**Observability + Control Plane**
- A small admin API (local web UI is optional) that can:
  - flip feature flags (taker allowed? new entries allowed? reduce-only mode?)
  - trigger kill switches
  - rotate configs + model versions safely
- Alerts on a handful of “stop the world” conditions (detailed later).

### Why this separation matters for delay and slippage

Latency is not just “network.” In the fill-ratio literature, latency includes your decision time and processing path, not only the exchange acknowledgment.citeturn3view0 So you want to measure and cap:
- **Decision latency** (market tick → intent)
- **Submission latency** (intent approved → order accepted)
- **Fill latency** (accepted → filled)

And you want order types that let you choose how to trade off immediacy vs price protection. For instance, marketable limit orders (MLOs) provide immediate-or-cancel behavior with a price cap; if the cap can’t execute, the exchange cancels.citeturn21view0 That “cap” is your primary anti-slippage tool.

On prediction-market venues like Polymarket, post-only orders will be rejected rather than executed if they would cross the spread.citeturn8view0turn8view1 This is a powerful primitive for controlling fee role and adverse selection.

## Per-coin configuration design

A per-coin config should not just tune signals; it should define **a full micro-policy**: liquidity assumptions, order types, risk budget, re-entry policy, and which features are allowed in each stage (research/shadow/live).

Below is an opinionated schema (YAML/JSON). The point is not the syntax; it’s the separation of concerns.

```yaml
coin: "BTC"                       # logical coin family
venue:
  name: "polymarket_clob"         # or kalshi, binance, etc
  market_ids:                      # prediction-market contracts for this coin
    - "token_id_or_ticker"
  quote_ccy: "USDC"
  tick_size: 0.01                  # hard reject if incompatible

liquidity:
  max_spread_bps: 40               # if wider -> no new entries
  min_top_of_book_usd: 2000        # per side; below -> no new entries
  max_book_staleness_ms: 750       # stale feed -> pause coin

signal:
  horizon_s: 300                   # align with contract resolution / signal decay
  edge_min: 0.012                  # minimum p_model - p_market (or EV threshold)
  ev_min_usd_per_100: 0.30         # minimum EV per 100 shares/contracts after fees
  confidence_min: 0.55             # calibrated probability or model confidence
  model_version: "v2026-04-12"

execution:
  entry_style: "maker_first"       # maker_first | taker_allowed | taker_only
  order_type_entry: "post_only_gtc"
  order_type_exit: "fak_or_ioc"     # more aggressive exits if needed
  max_order_notional_usd: 250
  max_slippage_bps: 25             # compared to mid at decision time
  order_ttl_ms: 1500               # cancel/replace if not filled
  max_requotes_per_min: 12         # throttle

positioning:
  max_position_notional_usd: 1000
  max_gross_coin_notional_usd: 1500
  stop_policy:
    max_adverse_markout_bps: 80
    max_time_in_trade_s: 600

portfolio_tags:
  correlation_cluster: "majors"    # majors | alts | memes | stables
  beta_bucket: "high"              # for stress tests / caps

reentry:
  allow: true
  max_entries_per_horizon: 2
  min_edge_improvement: 0.006
  cooldown_s: 120
  require_new_signal_epoch: true

stage_controls:
  research:
    allow_orders: false
  shadow:
    allow_orders: false            # still no live orders
    record_virtual_fills: true
  live:
    allow_orders: true
    max_daily_loss_usd: 50
    max_daily_turnover_usd: 2000
```

### Order-type knobs your config must support

Your config should make it easy to switch between these behaviors per coin:

- **Post-only maker entries**: ensures you don’t “accidentally take” at entry. Polymarket and several exchanges document post-only behavior as “reject if it would immediately execute.”citeturn8view0turn9view0turn9view1turn9view3  
- **FAK/FOK/IOC exits** when risk requires immediacy. Polymarket explicitly distinguishes GTC/GTD (resting) vs FOK/FAK (market-like immediate execution against resting liquidity).citeturn8view0turn8view2  
- **Market-order slippage awareness**: Kraken’s trading rules explicitly warn that market orders can experience slippage depending on market conditions.citeturn9view1  
- **Fee-awareness per venue**: Polymarket states makers are never charged fees and defines taker fees via a function of price *p(1-p)*.citeturn8view3 Kalshi’s fee schedule similarly defines fees as a function of *P(1-P)* and distinguishes taker vs maker fee schedules.citeturn13view3  
These fee formulas make “more trades” a first-order cost, which heavily impacts whether re-entry is worth it.

## Portfolio risk controls and kill switches

This is where you prevent correlated wipeouts and “death by execution.” The safest approach is **layered controls**: order-level, position-level, portfolio-level, and operational controls.

### Portfolio risk controls to avoid correlated wipeouts

Crypto portfolios can become more correlated in bearish regimes, reducing diversification benefits; empirical work on major cryptocurrencies finds correlations increase significantly during bear periods.citeturn14view0 Macro spillover work from the entity["organization","International Monetary Fund","global financial institution"] also finds spillovers between crypto and equities tend to increase during volatile episodes.citeturn14view1

Given that, the bot should enforce **cluster-based caps** rather than “per-coin only” limits:

- **Cluster gross exposure cap**  
  Example: total notional in `alts` ≤ 1× total notional in `majors`.  
- **Directional beta cap**  
  If your signals often agree (e.g., long BTC, long ETH, long SOL), treat it as one bet with multiple legs.  
- **Stress regime de-risking**  
  When volatility proxy is high (or venue spreads widen), automatically reduce max position sizes and disallow taker entries. The live execution experiment on Bybit/Binance emphasizes that execution discrepancies correlate with volatility and liquidity.citeturn18view0  
- **Daily loss budget per cluster + portfolio**  
  If you hit it, you go reduce-only or flat—no debate.

### Pre-trade risk checks (non-negotiable)

Borrow the “fat-finger / price tolerance / position + working orders” discipline from automated trading best practices. The entity["organization","Futures Industry Association","futures industry trade group"] best-practices paper recommends localized pre-trade risk controls and lists examples like maximum order size (fat-finger) and maximum intraday position, explicitly noting that current positions plus working orders should be evaluated.citeturn2view0

Implement these as **hard rejects**:

- **Max order size** (coin-specific; reject if unset).citeturn2view0  
- **Max intraday position** including *working orders* (so you can’t exceed limits via pending fills).citeturn2view0  
- **Price tolerance bands** vs reference mid (reject absurd prices).citeturn2view0turn9view0  
- **Message throttles** (orders/cancels per second) to avoid self-inflicted outages.citeturn2view0  
- **Self-match prevention** if the venue supports it, because accidental self-trades/wash trades are operationally and financially toxic.citeturn2view0turn13view2  

### Kill switches

Kill switches are not a substitute for pre-trade controls; they are the “break glass” mechanism. FIA notes kill switches are one of many risk controls and typically invoked as a last resort when other actions have failed or aren’t feasible.citeturn2view0

I recommend three kill switch layers:

**Strategy Kill (per coin)**
- Triggered by: stale book, abnormal spread, repeated order rejections, abnormal slippage vs cap, or model confidence collapse.
- Action: cancel working orders for that coin; disable new intents; allow exits only.

**Portfolio Kill (global)**
- Triggered by: portfolio drawdown > threshold, cluster drawdown, unexpected inventory explosion, or systemic data-feed issues.
- Action: cancel all working orders; set system mode to reduce-only; optionally flatten in a controlled way.

**Operational Kill (hard stop)**
- Triggered by: inability to reconcile positions, missing heartbeat, signing/auth errors, or “unknown order state” beyond a timeout.
- Action: stop order routing entirely; alert; require manual restart.

Also note: regulators explicitly expect risk controls and ask about kill-switch style controls for highly automated access. entity["organization","FINRA","us self-regulator"]’s oversight materials reference the need for reasonably designed risk controls and mention kill switches in the context of monitoring/responding to aberrant algorithm behavior.citeturn11view0

## Promotion gates from research to shadow to live

Promotion gates should be **measurable and adversarial**: you must prove the strategy survives execution and doesn’t depend on overfit backtests.

### Research stage

Requirements:
- Offline backtest with conservative trading costs.
- Walk-forward evaluation with parameter stability checks.
- Explicit overfitting diagnostics.

A strong, cited warning here: Bailey et al. define and estimate the **probability of backtest overfitting (PBO)** and propose combinatorially symmetric cross-validation (CSCV) to quantify how likely an in-sample “best” strategy underperforms out of sample.citeturn10view0

Minimum gate to move to shadow:
- Positive EV net of estimated fees + slippage across multiple market regimes.
- Parameter sensitivity bounded (small parameter changes should not flip results).
- Measured PBO acceptably low (you pick the threshold, but the process must exist).citeturn10view0

### Shadow stage

Shadow means: run the full stack against live data, **produce intents**, run risk checks, run the execution simulator, but do not place real orders.

Two important shadow mechanics:

- **Virtual order book execution**: simulate fills using top-of-book + queue assumptions, plus a latency model (see “Shadow-mode evaluation framework” below).
- **Exact same throttles and risk gates as live**: otherwise your shadow is lying.

If you use venues that offer a safe test environment, use it for integration hardening. entity["company","Kalshi","us prediction market exchange"] explicitly mentions a demo environment for testing integrations.citeturn13view0

Shadow-to-live promotion gates (opinionated but practical):
- ≥ 2–4 weeks of shadow data (or enough trades to cover your typical frequency).
- Shadow PnL **net of simulated fees/slippage** is positive and stable across weeks.
- Median and tail slippage are within configured caps.
- No “unknown state” incidents in reconciliation for at least 7 consecutive days.
- Correlation exposure limits were respected in all stress episodes.

### Live stage

Live is not “on/off.” It’s staged:

- **Live-1 (micro-notional)**: cap notional per coin and per day; prove fills and reconciliation match shadow assumptions.
- **Live-2 (small scaling)**: increase notional only if slippage and fee-role distribution stay within expected bounds.
- **Live-3 (controlled scaling)**: only after you have evidence that the execution disadvantage in taker flow is controlled (see next section).citeturn18view0turn21view0

## Shadow-mode evaluation framework

A production-grade shadow framework answers one question:  
**“If I flip the switch, what changes—edge, costs, or both?”**

### Track execution disadvantage explicitly

You need metrics that compare:
- **Expected fill** at decision time (based on visible book)
- **Realized fill** under your execution model (shadow)
- **Realized fill** in live trading (once live)

This is not academic nitpicking: the crypto live experiment on Bybit/Binance reports systematic disadvantage for taker orders and notes market orders can worsen fill prices while marketable limit orders can fail-to-fill immediately.citeturn18view0

### Shadow fill model components

Use a deliberately simple, conservative model:

- **Latency model**: sample a distribution of end-to-end latency that includes your processing path (consistent with the multi-layer latency definition).citeturn3view0  
- **Fill model by order type**:
  - Post-only: either rests or rejects (no “instant take”).citeturn8view0turn9view0  
  - MLO/IOC/FAK: executes up to price cap; cancels remainder.citeturn8view0turn21view0  
- **Fee model**: compute per-trade fees using venue formulae; on Polymarket, taker fees depend on *p(1-p)* and makers pay no fees.citeturn8view3 On Kalshi, fee schedules similarly define *P(1-P)*-based fees and separate maker fee schedules.citeturn13view3

### Shadow evaluation metrics (EV-first)

Per coin and portfolio-wide:

- **Expectancy / EV per trade**, net of fees and modeled slippage (your main KPI).
- **EV per unit of turnover** (controls overtrading).
- **Drawdown and tail loss (CVaR proxy)** in simulated PnL.
- **Fill ratio / miss ratio** by order type (maker vs taker vs MLO).
- **Markout curves** (PnL after 1s/5s/30s/5m) to detect adverse selection.
- **Fee-role distribution** (how often you end up taker) because makers vs takers can have structurally different returns; an academic study of Kalshi highlights that takers accept worse prices and pay fees, resulting in worse returns for takers in their model/data.citeturn12view0turn13view3

Promotion gate rule I recommend:
- Don’t move live unless the strategy remains positive EV under **two stress multipliers**:
  1) latency × 2,  
  2) spread/slippage × 1.5.  
If it only works in perfect execution, it’s not production-ready.

## Minimum logging fields and observability

If you only log “orders and fills,” you will not be able to diagnose EV decay versus execution decay.

Also, formal market-access regimes emphasize documenting and preserving risk controls and supervisory procedures; Rule 15c3-5 text explicitly requires establishing, documenting, and maintaining risk management controls, plus preservation as books/records for covered entities.citeturn11view2turn11view1 (Even if you’re not a broker-dealer, this is the right operational mindset.)

### Event types you must persist

- Market snapshots (best bid/ask, spread, top depth, staleness)
- Strategy decisions (including no-trade)
- Risk decisions (approved/rejected, resized)
- Order lifecycle events
- Fills and fees
- Position and PnL snapshots (per coin and portfolio)
- Health/heartbeat + reconciliation reports

### Minimum fields (log as structured JSON)

At minimum, log these for every *decision* and every *order lifecycle change*:

- `timestamp_exchange` (when venue says event happened, if available)
- `timestamp_local_ingest`, `timestamp_decision`, `timestamp_order_sent`, `timestamp_ack`, `timestamp_fill`
- `venue`, `instrument_id` (token_id/ticker), `coin`
- `stage` (research/shadow/live), `config_version`, `model_version`
- `signal`:
  - `p_model`, `p_market` (or implied), `edge`, `ev_estimate_usd`
  - `confidence`, `horizon_s`
- `risk`:
  - `position_before`, `position_after`
  - `gross_exposure`, `cluster_exposure`, `available_risk_budget`
  - `reason_code` if rejected/resized
- `order`:
  - `client_order_id`, `exchange_order_id`
  - `side`, `type`, `time_in_force`, `post_only`, `reduce_only`
  - `price`, `size`, `notional`
  - `slippage_cap_bps`, `ttl_ms`
- `execution_outcome`:
  - `status` (resting/partial/filled/canceled/rejected)
  - `fill_price_vwap`, `fill_size`, `fees_paid`
  - `realized_slippage_bps` (vs mid at decision)
- `self_trade_prevention` settings/flags where supported (Kalshi exposes this in its order schema).citeturn13view2  
- `error`:
  - `exception_type`, `exception_message_hash`, `retry_count`

Finally, instrument **message rate** and throttle events; message throttles are a recognized control to prevent excessive messaging that can disrupt systems.citeturn2view0

## Repeated Entries in the Same Coin

You asked for hard guidance here. The clean way to think about this is:  
**A “re-entry” is acceptable only if it increases expected value faster than it increases costs and tail risk.**

### When repeated entries are rational

Repeated entries can be rational in three main cases:

**Execution slicing is not re-entry**  
If you intended a $1,000 position and you split it into 4 child orders to reduce slippage or to stay maker, that’s one entry implemented safely, not four entries.

**Edge improved (not just price moved)**  
You add only when the **incremental edge** improves meaningfully after costs. In prediction markets, fees are often nonlinear in price (e.g., *p(1-p)*), so you must recompute EV at the new price, not reuse the old EV.citeturn8view3turn13view3  
If the market reprices against you but your model probability stays the same (or increases), EV can improve—*that* can justify adding.

**Independent signal epochs**  
If your strategy is multi-horizon (e.g., a 5-minute contract plus a separate 1-hour thesis), you can allow a second entry if:
- it is tagged to a distinct signal,
- it has its own stop/time limit,
- and it fits within the same per-coin and cluster risk budgets.

A useful analogy from Kelly’s original work: maximizing expected value of capital by betting too aggressively can still lead to eventual ruin; controlling bet fraction is crucial.citeturn22view0 Your re-entry rule is basically “dynamic bet sizing,” so it must be subordinated to risk budget, not emotion.

### When repeated entries are disguised overtrading

Re-entries are usually disguised overtrading when:

- **Edge is flat but you keep trading** (you’re paying spread/fees multiple times for the same view).
- **You’re reacting to noise** (micro price wiggles) without a model change.
- **Your additional entries are mostly taker** because you’re “chasing fills.”  
  This is particularly dangerous if taker flow is structurally disadvantaged. A Kalshi-focused academic analysis describes takers as accepting worse prices and paying fees, yielding worse returns for takers.citeturn12view0turn13view3  
- **You’re averaging down without a defined invalidation** (classic path to tail losses).

### Hard rules that should govern re-entry

These are the rules I’d actually implement:

**Rule: Re-entry requires a new “signal epoch” AND improved EV**  
- Define `signal_epoch_id` (e.g., model timestamp bucket, bar close time, or contract window).  
- No second entry unless:
  - `signal_epoch_id` changed **or** `edge` improved by at least `min_edge_improvement`.
  - and `ev_incremental` (recomputed at current price and fee schedule) is positive.

**Rule: Re-entry can never increase cluster exposure beyond budget**  
If BTC+ETH+SOL longs are already near your `majors` cluster cap, adding BTC is not “diversifying”; it’s doubling down into the same factor. Crypto correlations can rise in down markets, so cluster budgets are your anti-wipeout mechanism.citeturn14view0

**Rule: Re-entry is forbidden under degraded execution conditions**
Disable re-entry if any of these are true:
- spread > `max_spread_bps`
- staleness > `max_book_staleness_ms`
- recent realized slippage > cap
- latency p95 above threshold  
These conditions correlate with worse execution outcomes in live trading conditions.citeturn18view0turn3view0

**Rule: Re-entry must not cross your own resting liquidity**
Use self-match prevention features where supported, and in your own OMS ensure you don’t send marketable orders that would hit your own resting order. Self-match prevention is explicitly discussed as a control in automated trading risk practices.citeturn2view0turn13view2

### Max number of entries per coin per interval

My recommendation (opinionated, tuned for solo reliability):

- **Max 2 entries per coin per signal horizon** (the horizon should match your signal decay or contract window).  
- **Max 3 entries per coin per hour** even if horizons overlap.  
- **Max 6 entries per coin per day** unless you are market-making (different strategy class).

Rationale: prediction-market fee functions and maker/taker microstructure mean churn is expensive, and your operational error rate rises with order count.citeturn8view3turn13view3turn2view0

### How to measure whether re-entry improves expectancy or just increases variance

Treat re-entry as a feature flag and run an ablation test in shadow:

- **Baseline**: allow only first entry per epoch; execute virtual fills; compute EV distribution.
- **Variant**: enable re-entry; keep everything else constant.

Then measure:

- **Incremental EV**:  
  \[
  \Delta EV = EV_{\text{with re-entry}} - EV_{\text{baseline}}
  \]
- **Incremental variance / drawdown**: does tail loss worsen?
- **Incremental fee + slippage load**: re-entry should not “buy” EV by paying more costs than it creates.
- **Marginal markout of add-on trades**: compute markouts separately for “first entry” vs “add-on entry.” If add-ons have negative average markout or worse adverse selection, kill the feature.
- **Turnover-adjusted EV**: EV per $1,000 traded (or per 100 contracts). Re-entry that increases EV but destroys EV-per-turnover is often just variance inflation.

If re-entry is “good,” you should see:
- positive marginal EV on add-ons,
- stable or improved EV-per-turnover,
- and no disproportionate increase in drawdown tails.

## What to disable first if performance degrades

Performance usually degrades from one of three causes: **edge decay**, **execution decay**, or **risk regime shift**. Your shutdown sequence should assume “execution and regime” first, because those can turn a good model into a loser fastest.

Here’s the order I recommend:

**Disable taker / marketable entries first (go maker-only)**  
Post-only orders are specifically designed to prevent immediate execution; venues document that they reject rather than cross the spread, helping you avoid unintended taker fees and adverse selection.citeturn8view0turn9view0turn9view1turn9view3  
If performance improves after maker-only, your problem was execution/fees, not signal.

**Disable repeated entries (single-entry mode)**  
Re-entry amplifies churn and correlation exposure. If disabling re-entry stabilizes results, you were likely overtrading or paying too much microstructure tax.citeturn8view3turn13view3

**Raise EV/edge thresholds and reduce universe to highest liquidity coins**  
Wide spreads and low depth are where slippage dominates. Market orders can slip in volatile/illiquid conditions, and execution discrepancies correlate with volatility and liquidity.citeturn9view1turn18view0

**Reduce portfolio correlation risk (cluster caps down)**
If the whole tape is moving together, you want smaller cluster exposure because diversification weakens in bear markets.citeturn14view0

**Go “reduce-only” globally**
Allow only exits and risk reduction. This is safer than a full stop because it lets you unwind.

**Trigger the portfolio kill switch**
If reconciliation is unreliable, data is stale, or losses exceed budget, kill routing and require manual intervention. FIA frames kill switches as last-resort tools within a broader suite of controls.citeturn2view0turn11view0