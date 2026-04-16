# Coin-Spread Strategies in Short-Horizon Crypto Prediction Markets

## Market structure realities that dominate “spread” feasibility

Short-horizon crypto direction markets (e.g., 5‑minute “Up/Down” windows) are binary outcome contracts: you are effectively trading a claim that pays **$1 if a specific sign condition on the reference price holds at the window end**, and **$0 otherwise**. On a representative 5‑minute Bitcoin Up/Down market page, the rules explicitly state: resolve “Up” if the **end-of-window Chainlink BTC/USD price is ≥ the start-of-window price**, else “Down,” and the **resolution source is the Chainlink data stream**, not “spot markets” generally. citeturn7view3

On entity["company","Polymarket","prediction market platform"], these outcomes are tokenized as ERC‑1155 “Yes/No” (or Up/Down) outcome tokens under the **Conditional Token Framework (CTF)** (an open standard developed by entity["organization","Gnosis","ctf standard developer"]). Each binary market has exactly two fully collateralized tokens; for every $1 of collateral, you can “split” into a Yes+No pair and later “merge” a full pair back into $1 collateral. This is important because it enforces strong *intra-market* parity constraints (Yes/No sums gravitate toward $1 in a frictionless world) but **does not** enforce *cross-coin* parity—your coin spreads rest on softer statistical relationships, not hard conversion arbitrage. citeturn7view2turn3search6turn3search10

The crypto markets you care about are run as a **central limit order book (CLOB)** with an offchain matching / onchain settlement lifecycle: orders are created offchain, matched by an operator, and settled atomically onchain (on entity["organization","Polygon","l2 blockchain network"]). This hybrid design gives you order-book style microstructure (spread, depth, queue position, stale quotes) but still leaves operational realities (matching, submission, finality) that matter at 5–15 minute horizons. citeturn8view1turn2search24

Two details matter more than almost any “alpha idea” for coin spreads:

Trading costs are not small at these horizons. Polymarket’s taker fees are **nonlinear in price** (symmetric around 0.5) with a published formula:  
**fee = C × feeRate × p × (1 − p)**, and for Crypto the parameter is **feeRate = 0.072** (makers pay zero fees). At p=0.50 and C=100 shares, the fee is $1.80. citeturn8view2  
If you measure that as a fraction of the **maximum payout notional** (100 shares → $100 max), that’s 1.8%. If you measure it as a fraction of the **cash you paid** (100 shares at $0.50 costs $50), it’s **3.6% of cash outlay**—which is the relevant denominator for a short-horizon strategy recycling capital. That’s before bid/ask spread and depth slippage. citeturn8view2turn5search1  
Also: the platform’s fee schedule has changed over time (e.g., public comms and changelog language around 1.56% peak for short-horizon crypto vs documentation showing 1.80% peak), which is precisely why you must design strategies that survive *parameter drift*. citeturn5search0turn5search1turn5search6

Latency and orderbook dynamics are *the strategy*. Market orders are implemented as “marketable” limit orders (FOK/FAK) whose price field is a **worst-price / slippage cap**, not a target. Polymarket provides a WebSocket market channel streaming level‑2 book updates and trade executions, plus an RTDS feed that streams crypto spot prices from entity["company","Binance","crypto exchange"] and entity["company","Chainlink","oracle network"] with millisecond timestamps. Any “spread” that relies on one coin’s book lagging another’s is, in practice, a latency game against other bots reading the same feeds. citeturn8view0turn7view1turn7view0

A microstructure-minded interpretation: in 5–15 minute crypto windows, “coin spread” strategies are competing to capture **micro-lags, stale quotes, segmentation, and inventory-driven mispricing**—while paying a fee curve that punishes overtrading unless you earn maker rebates / spreads.

## Taxonomy of plausible spread strategies in crypto prediction markets

A “coin spread” in this setting is not a classical spot pairs trade. You are trading **binary payoffs** whose prices are “implied probabilities,” which means many standard spread intuitions break: a 5‑cent mispricing is not “5 bps,” and hedging is discrete and path-dependent near expiry.

The strategies that are actually plausible cluster into five families.

### Cross-coin conditional-probability spreads (stat-arb on implied probabilities)

**Core idea:** Use the more liquid coin’s Up probability as a sufficient statistic for the less liquid coin’s Up probability, given historically stable co-movement. Example: if BTC is 55% Up for the current 5‑minute window, and historically ETH’s Up probability conditional on BTC’s is higher than ETH is currently priced, buy ETH Up and hedge with BTC Down (or vice versa), targeting mean reversion of the pricing relationship.

Why this is plausible in prediction markets: prices are *explicit probabilities*, so you can model directly:  
P(ETH_up) ≈ P(BTC_up)·P(ETH_up | BTC_up) + (1 − P(BTC_up))·P(ETH_up | BTC_down)  
Then treat ETH’s market price as the market’s belief and trade deviations.

Why it can exist: **information arrives first where liquidity and attention are**, and in crypto that is typically BTC. In broader crypto literature, cross-cryptocurrency lead/lag and return predictability effects have been documented (though magnitudes and stability vary). citeturn4search14turn4search2

What makes it fragile: conditional probabilities are regime-dependent. Crypto co-movement and spillovers vary with volatility regimes and stress; many studies show correlations and connectedness measures are time-varying and often strengthen in common regimes or extremes. citeturn4search15turn4search23turn4search33  
In a volatility event, “spread” positions can fail together (both legs go the wrong way) because your hedge is not linear and can break exactly when you need it.

Retail realism: **researchable**, but hard to monetize as a taker after fees unless mispricings are large and frequent, or unless you can be maker on at least one leg.

### Lead–lag stale-quote sniping (cross-market micro-arbitrage)

**Core idea:** When BTC moves and its prediction market updates quickly, some smaller coin market’s orderbook can be momentarily stale. You take resting liquidity on the stale book (taker) or place/cancel aggressively (maker) to “pick off” mispriced quotes.

Why it might exist in these markets: CLOBs update discretely; some markets “still building their trading base” and can reflect only a small number of trades, which implies periods of slower price discovery. citeturn7view3  
This is the *most literal* coin-spread: “coin A’s book tells me coin B’s fair value right now.”

The problem: it is an arms race. Polymarket exposes near real-time orderbook and trade streams via WebSocket, and spot crypto prices via RTDS feeds; many bots will implement the same sniping logic. citeturn7view1turn7view0

Retail realism: possible only if (a) your latency is competitive *enough*, (b) you are disciplined about not paying fees/spread too often, and (c) the target markets are illiquid enough to lag—but illiquid enough also means **your fills will be partial and your slippage large** (the classic “it moved because it’s thin” trap).

### Basket / factor-residual spreads (synthetic hedge using multiple coin markets)

**Core idea:** Treat BTC as the common factor; trade an altcoin as “factor + residual.” If SOL’s implied Up is too high relative to what BTC and ETH imply (given historical beta), you short SOL Up (i.e., buy SOL Down) and hedge by buying BTC Up (and/or ETH Up) in proportion.

This is how quantitative stat-arb is usually built in equities (factor neutrality). The issue is the instrument: you are hedging **Bernoulli payoffs**, not linear returns. A “beta-neutral” notion exists only approximately, in expectation, and collapses near expiry because the payoff becomes almost deterministic given spot micro-moves.

Why it can exist: segmentation and shallow liquidity can cause one coin’s implied probability to overshoot, especially around coin-specific catalysts. More broadly, spillover literature indicates crypto markets have dynamic connectedness; a factor model is at least conceptually defensible. citeturn4search23turn4search26

Retail realism: viable mainly as a **risk-control overlay** rather than a primary alpha generator. If you can’t manage correlated blowups, this becomes “short volatility in disguise.”

### Calendar / horizon spreads (same coin, different windows)

**Core idea:** Trade inconsistency between (say) BTC 5‑minute Up and BTC 15‑minute Up that overlap in time, or between adjacent windows (e.g., next 5‑minute vs the following 5‑minute). In a diffusion-like world, these probabilities should be linked via volatility and drift assumptions; large gaps may be behavioral/flow-driven.

Why it can exist in prediction markets specifically: participants often treat each window as a separate “game,” and flow can be unbalanced across horizons; that can create persistent differences not fully arbitraged away because capital and attention are fragmented (a theme consistent with broader prediction-market fragmentation and law-of-one-price violations across venues/semantics). citeturn3search3turn3search5

Retail realism: **more realistic than cross-coin factor trades** because it eliminates cross-asset correlation uncertainty—but execution is still nontrivial, and overlapping-window mapping must be exact (no sloppy alignment).

### Intra-market parity / conversion arbitrage (not cross-coin, but crucial baseline)

Not a coin spread, but you should treat it as the “control strategy” and operational check: because you can split/merge Yes+No pairs into $1 collateral, extreme violations of Yes+No parity (after costs) create near-arbitrage situations. These are likely rare and highly competed, but they anchor expectations about how much “free money” you should see from mispricing in the system. citeturn7view2turn3search6turn3search10

## What’s realistic for a retail bot vs fake-good after fees and execution

High-frequency relative-value strategies are notoriously sensitive to transaction costs and execution speed. Classic evidence from high-frequency equity pairs trading shows excess returns are “extremely sensitive” to transaction costs and speed of execution; even moderate costs can cut profits dramatically. citeturn2search3turn2search7  
That lesson ported to prediction markets is even harsher because (a) **fees are percentage-like and nonlinear**, (b) spreads can be wide in thin books, and (c) the payoff is binary so you can’t “partially delta-hedge” continuously.

With Polymarket’s crypto taker fee curve, “small” edges are often not edges. For a taker strategy, you must overcome:

The taker fee, which depends on p and peaks near p=0.5 (Crypto uses feeRate 0.072). citeturn8view2  
The bid/ask spread (your immediate loss when crossing). Level‑2 book snapshots and best bid/ask updates can be streamed, but thin books mean the effective spread at your size can be much wider than top-of-book. citeturn7view1turn0search5  
Slippage and partial fills (especially if you use FAK or marketable limits). Polymarket’s market order mechanics explicitly cap worst price but do not guarantee full execution (FAK fills what it can and cancels the rest). citeturn8view0

So which families are “realistic”?

Most realistic (retail): maker-biased, rebate-aware relative value. Makers pay no fees and maker rebates exist explicitly to incentivize deeper liquidity; the program pays daily USDC rebates funded by taker fees. citeturn8view2turn6view0  
A retail bot that quotes intelligently (two-sided, inventory-skewed, and cancels staleness fast) can turn “spread strategy” into “capturing micro-spread + rebates while using cross-coin signals to reduce adverse selection.”

Plausible but latency-sensitive: lead–lag sniping when mispricings are large. If your target market is sufficiently illiquid or slow-moving, the mispricing can be big enough to clear fees+spread. But this is the one most likely to be crowded and to degrade fast.

Most fake-good: cross-coin conditional-probability spreads with aggressive rebalancing. They backtest beautifully if you assume midprice fills, ignore queue position, and treat fees as flat bps. In reality: you’ll overtrade, pay the nonlinear fee curve repeatedly, and get the worst fills when everyone rushes to update in the last seconds of the window.

A practical “skeptical filter”: if your model’s average per-trade expected advantage is not comfortably larger than **(half-spread + fees + expected slippage)**, the backtest is noise. This is exactly the transaction-cost fragility seen in pairs trading research. citeturn2search3turn2search7

## Detecting relative mispricing without overfitting and constructing partial hedges

A robust spread bot needs two models, not one:

A mispricing detector: “Is coin A rich/cheap relative to coin B right now?”  
A regime/risk model: “Is the relationship stable enough right now to risk capital?”

### Data features you actually need (minimum viable)

From Polymarket market data:

Level‑2 orderbook snapshots/deltas and trade prints from the Market WebSocket channel. citeturn7view1turn2search9  
Best bid/ask (to estimate immediate crossing cost) and tick-size changes (tick size can change when prices reach extremes, e.g., >0.96 or <0.04). citeturn9search19turn8view0  
Fee rate / whether fees are enabled for the specific token (don’t hardcode; docs explicitly warn fee rates vary by market type and may change). citeturn8view2turn1view0

From external/reference price streams:

A spot price feed aligned to what matters for resolution. For the BTC 5‑minute market, resolution uses the Chainlink BTC/USD data stream; RTDS can stream Chainlink and Binance prices with timestamps. citeturn7view3turn7view0

From your own execution logs:

Order submit timestamps, acknowledgements, fills (including partials), cancels, and end-to-end latency distribution.

### Mispricing detection that resists overfitting

A strong baseline approach is deliberately boring:

Define a small set of “anchor markets” (e.g., BTC and ETH) with better liquidity and faster price discovery.

Estimate a rolling, shrinkage-based relationship between implied probabilities:

p_alt(t) ≈ α + β · p_BTC(t) + γ · p_ETH(t) + controls(t)

Controls that are hard to fake:

time-to-expiry (seconds remaining in window), because the payoff becomes more deterministic near expiry.  
realized spot volatility over the last N seconds (from RTDS), because co-movement and reversal odds change with volatility. citeturn7view0turn4search6  
orderbook “staleness” measures (time since last trade or last best bid/ask update), because stale books are where mispricing lives. citeturn7view1turn2search9

Then compute a z‑score or standardized residual:

resid(t) = p_alt_market(t) − p_alt_model(t)

Only act when |resid| exceeds a threshold that is explicitly greater than an execution cost buffer.

This is pairs-trading logic adapted to implied probabilities. The academic pairs-trading literature emphasizes the importance of accounting for transaction costs and execution frictions; high-frequency variants are particularly cost-sensitive. citeturn2search3turn2search7turn2search28

### Hedging / partial hedging approaches that are feasible

Because payoffs are binary, your hedge is never perfect. What you can realistically do is:

Expected-value neutrality: choose sizes so that under your model, the spread’s expected payoff is near zero when there is no mispricing, so you are mostly betting on mispricing correction. This reduces uncontrolled directional exposure, but only “in expectation.”

Factor hedge: if you’re trading SOL residual, you can hedge with BTC/ETH legs sized to reduce covariance with the common factor—but note this is regime-dependent and can fail in stress.

Operationally, the only hedges that are easy to execute are “take the opposite outcome in the hedge coin.” That is mechanically simple, but it still leaves you exposed to joint tail events where both coins move together (correlation spikes) and the hedge leg doesn’t offset enough.

Because crypto connectedness and spillovers vary by regime (including stronger correlations under common volatility regimes and tail connectedness), you must treat “market-neutral” as a goal, not a guarantee. citeturn4search15turn4search23turn4search33

### Correlation regime monitoring that works in practice

For a production bot, avoid fragile high-parameter correlation models if you can’t maintain them. Use layered, interpretable monitors:

EWMA correlation of spot returns (from RTDS) over multiple half-lives (e.g., 30s, 2m, 10m).

A simple “stress score” such as:
absolute BTC move over last 60s, realized volatility percentile, and orderbook spread widening.

A regime switcher: if stress score is high, assume correlations rise and spread trades become more correlated (diversification fails), consistent with empirical findings that connectedness/spillovers are state-dependent and often larger in extremes. citeturn4search33turn4search23

If you want a more formal method, DCC-GARCH models are commonly used for time-varying correlation, including in crypto contexts. citeturn4search1turn4search28  
But the key is not sophistication; it’s whether it **prevents you from placing correlated bets during regime breaks**.

## Failure modes and why “spread” trades blow up together

A spread strategy fails more often from *structure* than from “being wrong.”

Execution failure modes:

Thin books: top-of-book looks attractive, but your size clears depth and you suffer nonlinear slippage; Polymarket docs explicitly warn large orders can move price significantly and you should check depth. citeturn0search5turn7view1  
Partial fills: if you execute leg A but only partially execute leg B (or vice versa), you are left with naked directional exposure into expiry. FAK orders explicitly allow partial fills and cancel the remainder. citeturn8view0  
Tick-size changes near extremes can break your quoting logic or cause rejected orders if you’re not fetching updated tick sizes; Polymarket’s Market Channel explicitly emits tick_size_change events when prices go beyond thresholds. citeturn9search19turn7view1  
Fee mis-estimation: fee schedules can change and are per-market; documentation explicitly advises against hardcoding fee rates and notes fee-enabled markets are identifiable via flags/endpoints. citeturn8view2turn1view0

Economic failure modes:

Fees + spreads eat “small mispricing.” With the fee curve peaking near p=0.5, spread strategies that continuously rebalance around mid-probabilities are structurally disadvantaged as takers. citeturn8view2turn5search1  
Crowding: if the edge is “coin A updates faster than coin B,” other bots will also exploit it; your fills deteriorate and adverse selection increases.

Model failure modes:

Regime shifts: in high volatility, correlations and spillovers can increase (or connectedness patterns change), making multiple spreads fail in the same direction. citeturn4search15turn4search23turn4search33  
Hidden optionality: many spread strategies are implicitly **short tail risk**. You earn small, frequent wins when relationships mean-revert and lose big when everything moves together quickly.

This “correlated blowup” risk is not hypothetical; it is consistent with broad evidence on time-varying spillovers and tail connectedness in crypto and broader markets. citeturn4search23turn4search33

## Honest execution simulation for backtests and live-like evaluation

If you want to avoid building something that is “fake-good,” you need an execution simulator that respects Polymarket’s actual mechanics.

### Market data reconstruction requirements

Use the Market WebSocket channel (level‑2 data) for each token you trade; it provides snapshots and updates, including bids/asks arrays and timestamps. citeturn7view1turn2search9  
Use RTDS for spot price features; messages include timestamps indicating when the message was sent and when the price was recorded. citeturn7view0

You cannot rely on periodic midprice polling; the entire edge (if any) is in micro-timing.

### Taker simulation rules (for sniping / aggressive spreads)

At decision time t, sample the orderbook state that would have been available given your measured data latency.

When you “send” a marketable limit order, execute against the book with a worst-price cap (as in Polymarket’s market order interface). If depth is insufficient, simulate partial fill (FAK) or no fill (FOK). citeturn8view0

Charge taker fees using the published fee formula and crypto feeRate; fees depend on price p and shares C. citeturn8view2

Add a cancellation/replace penalty: if your strategy implies rapid order churn, model the realistic ratio of submits to fills; over-churn is often where backtests cheat.

### Maker simulation rules (if you want anything durable)

Queue priority approximation: you need either full orderbook event history (including order adds/cancels) or a conservative fill model (e.g., assume you are last in queue at your price level unless you have evidence otherwise). Polymarket’s market maker docs stress that quoting and cancellation discipline matters; they recommend WebSocket for real-time feeds and batching orders to reduce latency. citeturn1view2turn7view1turn9search0

Heartbeat / kill-switch realism: Polymarket’s order system includes a heartbeat mechanism; if a valid heartbeat is not received within ~10 seconds (with buffer), open orders can be cancelled. A bot that can’t maintain session liveness will not behave like your backtest. citeturn9search1turn9search5

Rebates: maker rebates exist and are funded by taker fees, paid daily, and proportional to a “fee-equivalent” formula. If you’re evaluating maker-based spreads, include rebates in PnL—but treat them as **unstable policy risk** (rebate % is discretionary and can change). citeturn6view0turn8view2

### Multiple entries in one coin: help or harm for spread execution?

For taker-style spreads: multiple entries usually **worsen** results. Each additional entry is another round-trip through bid/ask and another fee payment (and another chance for partial fill asymmetry). Given the convexity of costs (fees + slippage), scaling in can turn a marginal edge into negative expectancy.

For maker-style quoting: multiple orders at multiple levels can **improve** execution quality by increasing the probability you capture spread without crossing. Polymarket explicitly supports posting multiple orders (up to 15 per request) and recommends batch posting for tighter multi-level spreads. citeturn1view2turn9search0  
But it increases adverse selection risk if you don’t cancel fast—especially close to expiry when the contract becomes almost deterministic based on the reference price path. In other words: multi-level entries help *only if* you have strong quote-staleness controls and strict inventory limits.

## Ranking the top spread-style bot concepts for a small automated bot

Most promising: maker-biased cross-coin “relative value market making”
You quote both sides on a small set of coin markets (e.g., BTC/ETH/SOL) with inventory skew and a cross-coin fair value model. You aim to earn spread + maker rebates while using the cross-coin model mainly to avoid being picked off when one coin has moved and your quotes are stale. This aligns with the platform’s incentive design: makers pay no fees and there is a maker rebates program funded by taker fees. citeturn8view2turn6view0turn1view2  
It’s still hard—market making is adverse-selection management—but it’s one of the few ways to not donate the fee curve to the house.

Middle: selective lead–lag sniping with strict “mispricing must clear costs” gating
Only trade when the inferred mispricing (from RTDS + anchor coin) exceeds a conservative threshold: fee + half-spread + depth slippage + a latency buffer. Use FOK more than FAK to reduce leg-asymmetry risk. This can be profitable in niches but is crowded and degrades quickly because the same data is public and low-latency accessible. citeturn7view0turn8view0turn7view1

Least promising: “textbook” cross-coin conditional-probability pairs trading as a taker
It is highly likely to be fake-good in backtests unless you simulate queue position and fees perfectly. High-frequency pairs trading evidence shows extreme sensitivity to costs and execution speed, and your costs here (taker fee curve + wide/inconsistent spreads in thin books) are large relative to realistic mispricings. citeturn2search3turn2search7turn8view2  
This can still be valuable in research as a signal generator (market selection, inventory skew), but as a standalone taker strategy it’s the first one I’d try to disprove.

## Design rules for a production bot

These rules assume: thin books exist, fees exist, late-second trading happens, and correlated exposure can stack across coins.

Entry rules

Enter only when the *cost-clearing* mispricing is large. Define:  
edge_est = |p_market − p_model|  
cost_buffer = taker_fee(p_market) + half_spread + expected_slippage(size) + latency_margin  
Trade only if edge_est ≥ k × cost_buffer, with k≥2 for taker strategies. Fees are price-dependent, so this gating must be dynamic. citeturn8view2turn8view0turn0search5

Prefer maker entries when possible. If your logic does not require immediate fill, post-only maker orders (so you never accidentally pay taker fees). Polymarket’s API supports post-only behaviour (reject if it would cross). citeturn8view0turn8view1

Avoid entering in the final seconds unless you have a measured, reliable latency budget. Near expiry, probabilities can shift sharply, and any stale quote risk is magnified. citeturn7view3turn8view1

When not to enter

Do not trade if you cannot complete both legs within a bounded time window. For two-leg spreads, require either:
atomic execution logic (if supported) or  
a strict “leg A fill must confirm before leg B” protocol (accepting missed trades over partial hedges)

Do not trade markets with stale or sparse updates beyond a staleness threshold unless your entire strategy is explicitly “stale quote picking” and you have latency advantage. Use Market WebSocket arrival times to measure staleness. citeturn7view1turn2search9

Do not trade if tick size has changed and your pricing logic hasn’t refreshed tick size; tick changes can happen near extreme prices. citeturn9search19turn9search2

Position sizing rules

Size by worst-case execution asymmetry, not by model confidence. For spread trades, the dominant tail risk is “one leg fills, the other doesn’t.” Your max size should be the size you can tolerate holding unhedged into resolution.

Cap turnover explicitly. If you can’t write down a maximum trades-per-hour per coin, you will overtrade into the fee curve.

Adjust size down as p approaches 0.5 (unless you are maker). The taker fee curve is maximal near p=0.5, so “small, frequent” mid-probability trades are structurally disadvantaged. citeturn8view2

Max correlated exposure rules

Define a correlation cluster: {BTC, ETH, SOL, XRP} are typically highly connected in short-horizon stress. Treat them as one cluster for exposure limits even if your positions are “spread” positions. Spillovers and tail connectedness in crypto are time-varying and can intensify in extremes. citeturn4search23turn4search33turn4search15

Set a cluster cap in “at-risk payout notional,” not in dollars spent. Because payoffs are $1 per share, payout notional is the natural risk unit.

Multiple entries on the same coin

Allow multiple entries only for maker-style layered quoting, and only if:
you batch orders (to reduce latency) and  
you have automated “cancel stale quotes” triggers and a kill switch. Polymarket supports posting multiple orders (max 15 per request) and cancel-all endpoints; operationally, you should be able to yank quotes immediately. citeturn9search0turn9search29turn9search3

For taker execution, treat multiple entries as a red flag: unless you are executing a single order sliced for stealth, repeated entries usually indicate signal noise and fee leakage.

When to disable a coin entirely

Disable a coin (temporarily) if any of these occur:

Execution-quality break: fill asymmetry rate (one leg filled without the other) exceeds a threshold over a rolling window.

Liquidity break: median top-of-book depth falls below what you need for minimum size with tolerable slippage.

Microstructure break: tick size changes frequently or your orders are repeatedly rejected due to tick/precision mismatches (this indicates your market-parameter caching is unsafe). citeturn9search19turn9search23turn9search2

Operational break: heartbeat failures or connectivity issues. If heartbeats aren’t maintained, open orders can be cancelled automatically; treat this as an immediate “go flat” condition. citeturn9search1turn9search5

Regime break: market stress score exceeds threshold (volatility spike, spreads widen, correlations jump). In this regime, assume spread trades become more correlated and stop adding risk. citeturn4search33turn4search23