# Surviving short-horizon crypto prediction-market bots on Polymarket-style 5m and 15m direction contracts

## Scope and assumptions

This review treats “5m/15m crypto direction markets” as frequent, short-expiry binary contracts (e.g., “BTC Up or Down over the next 5 minutes”), traded on a central limit order book, with thin and discontinuous liquidity, and with maker/taker economics that materially change your breakeven. The Polymarket crypto directory explicitly segments markets by short horizons (5 Min, 15 Min, 1 Hour, etc.), and shows many “Up or Down” listings with narrow time windows—so the “short horizon, many expiries” premise is realistic. citeturn16view0

Key constraints (explicitly assumed in this review): (a) maker/taker fees exist and can change; (b) meaningful flow arrives in the last seconds before the window ends; (c) order books can be thin enough that a “marketable” order moves the price; (d) naive automation will overtrade and stack correlated exposures (e.g., BTC+ETH+SOL all “Up”); (e) no “social hype” alpha is assumed. citeturn28view1turn6view2

Also critical: on Polymarket-style architecture, order handling is hybrid: users place signed orders off-chain into an operator-run CLOB, and matched trades settle on-chain (so settlement, inventory, and “can I instantly flip?” are real constraints, not theoretical). Polymarket’s own docs describe off-chain matching with on-chain settlement, and independent audits describe a centralized operator receiving EIP-712 signed orders and deciding what gets matched and when it is submitted on-chain. citeturn28view1turn1view2turn15view1

## How these markets behave in production

### Prices, spreads, and what “the displayed price” really means

Polymarket-style markets present prices as probabilities (0–1), but the *displayed* price is not what you trade at: you pay the ask to buy and hit the bid to sell. Polymarket’s docs explicitly say the displayed price is the midpoint of the bid–ask spread, and if the spread is wider than $0.10, it may display the *last trade* instead—meaning the UI can show a number that is stale in precisely the “thin / stressed” conditions that matter most to a short-horizon bot. citeturn28view1

Spreads exist even if “blockchain gas is subsidized,” because spreads are fundamentally compensation for inventory and adverse selection, not merely “explicit fees.” Classic market microstructure surveys describe that inventory control implies a bid–ask spread even when physical trading costs are negligible, and spreads widen with risk/uncertainty and constraints on liquidity providers. That maps directly to short-horizon crypto direction books where informativeness and volatility spike near window end. citeturn24view0turn24view1

image_group{"layout":"carousel","aspect_ratio":"16:9","query":["limit order book bid ask spread diagram","order book depth chart example","binary option payoff diagram $0 to $1"],"num_per_query":1}

### Fee reality: breakeven is dominated by maker/taker economics

On current Polymarket documentation, taker fees are non-zero on fee-enabled markets, makers are *never* charged fees, and fees follow an explicit convex curve in price:  

**fee = C × feeRate × p × (1 − p)** (C = shares, p = price). citeturn6view2

Implications that matter for bot viability:

- Fees are **highest near 0.50** and **lower near the extremes** (0.05, 0.90, etc.) because they scale with \(p(1-p)\). citeturn6view2  
- Fee-enabled markets can be identified via a `feesEnabled` flag, and the docs explicitly warn API users to fetch fee rates dynamically and not hardcode them. In production, “fee regime drift” is not hypothetical; it is documented behavior. citeturn6view2turn1view1  
- Maker rebates exist and are funded by taker fees; rebate rates differ by category (e.g., crypto noted at 20% maker rebate in the fee table), and daily rebates are computed per-market—so you only compete with other makers within the same market for that rebate pool. citeturn6view2turn5view0  

For your three ideas, this means a brutal baseline: **if you are mostly a taker, your expected edge must clear (spread + taker fee + your latency slippage).** If you are a maker, your edge target is different: you are paid indirectly through spread capture plus potential rebates, but you accept adverse selection and inventory risk. citeturn6view2turn5view0turn28view1

### Latency is not just “network ping”: it includes throttling, maintenance, and on-chain finality

A short-horizon bot is exposed to several *platform-specific* latency traps:

- **Cloudflare throttling that queues requests rather than rejecting them** when you exceed rate limits; this is especially dangerous because a queued cancel or replace effectively becomes a stale action executed late. citeturn3view0  
- **Matching engine restarts**: the matching engine is documented to restart weekly (with typical ~90s downtime) and returns HTTP 425 (“Too Early”) during restarts. Any bot that assumes continuous availability without a kill-switch will eventually get stuck with unmanaged exposure or dead quotes. citeturn1view5  
- **Heartbeat-based order safety**: if a valid heartbeat isn’t received within 10 seconds (plus buffer), all open orders are canceled. That’s an operational cliff: transient networking issues can turn “maker strategy” into “suddenly no quotes,” often during volatility spikes. citeturn21view3  
- **Hybrid settlement**: trades transition through `MATCHED → MINED → CONFIRMED` (and can be `RETRYING`/`FAILED`), and the on-chain transaction hash only appears after mining. This means inventory and “re-enter immediately” assumptions can be wrong in fast windows. citeturn21view3turn15view1  

Also note that order matching uses **price-time priority** (best price first, then earlier orders first at the same price). In practice, that makes queue position a real asset; “same price but later” can be the difference between being filled and watching the window expire. citeturn29view0

### Resolution and capital lock-up are non-trivial even for 5m/15m markets

Even if a 5-minute event is “economically decided” at window end, final resolution is oracle-driven. Polymarket uses an optimistic oracle mechanism: proposals require a bond, there is a 2-hour challenge period, and disputes can escalate to longer UMA voting processes. This can turn short-horizon trading into **longer-horizon capital lock-up** if your strategy frequently holds through resolution rather than trading out. citeturn19view0turn19view1turn19view2turn19view3

(For completeness: the architecture connects conditional tokens (ERC-1155 style outcome shares), off-chain order matching, and on-chain settlement logs, which makes *executions* observable on-chain after the fact—but does not make *intent* (resting orders) observable in real time. citeturn13view1turn15view1)

## Evaluation of the three strategy ideas

### Copy-trading or shadowing a top trader or wallet

**Core thesis (plain English).** Identify a wallet with strong realised PnL and copy its trades, assuming its edge is stable and transferable. In short-horizon markets, the hope is that “informed” traders move first and you can ride the same direction. citeturn11view1turn11view0

**Why it might work specifically in prediction markets.** Prediction markets can concentrate “informed” activity into a few participants when most users are casual. Empirically, prediction market prices often map monotonically to beliefs and aggregate information reasonably well, so following a systematically well-informed participant could, in principle, inherit information advantage. citeturn14view3turn28view1

**Main failure modes (this is where it usually dies).**  
The dominant failures are structural:

1) **You cannot copy what you cannot see in time.** Orders are created and live off-chain in the operator-run CLOB, and only matched trades settle on-chain. That means you typically observe the leader’s execution only after it is already matched (and possibly after it is mined), which is fatal in 5m/15m windows. citeturn28view1turn15view1turn21view3turn13view1  
2) **The leader’s PnL driver may be non-copyable microstructure.** A top “trader” may actually be a liquidity provider monetising rebates/spread, queue position, and adverse selection management—things you will not replicate by “chasing their fills.” Maker rebates are explicitly part of the economics, and per-market competition means sophisticated makers can specialise. citeturn6view2turn5view0turn29view0  
3) **Selection bias and regime shift.** “Top wallet” lists are ex post; short-horizon PnL is extremely sensitive to realised volatility, fee regime, and latency rules, all of which can change. The docs explicitly caution that fee rates vary by market type and may change over time—exactly the kind of shift that breaks a copy strategy. citeturn6view2turn1view1  
4) **Correlated blowups by construction.** If the copied wallet is active across multiple correlated coins, you inherit its concentrated risk (and possibly at worse prices). BTC–ETH correlation and co-movement are state-dependent; a “diversified across coins” book can still blow up together. citeturn30search0  

**How latency affects it.** Copy-trading is *maximally delay-sensitive* because your signal is “they already traded.” Add (a) observation delay (indexing/on-chain mining), (b) your own order placement delay, and (c) price-time priority queue disadvantage, and your execution becomes an adverse selection magnet: you buy after the price has moved and sell after it has reverted. citeturn21view3turn15view1turn29view0turn3view0

**How fees and slippage affect it.** This strategy tends to turn you into a taker, because you are reacting, not placing resting liquidity. Taker fees are explicit and convex in price, and you also pay the spread (or worse, you move the book in thin markets). Polymarket explicitly advises checking order book depth because large orders can move price significantly—copying a leader’s size is exactly how you self-impose price impact. citeturn6view2turn28view1

**Is it robust enough for automation?** As a live-trading bot: generally **no**. It is robust only as an *analytics* system, because the core dependency is an external actor whose edge may be primarily execution/queue/rebate based, and because your observation latency is structurally worse than theirs. citeturn15view1turn29view0turn6view2

**Works better in live trading, shadow mode, or research only?** Mostly **shadow mode / research only**. The realistic use is: treat top-wallet flows as a feature (who is active, what markets they touch, when they scale), not as a trade instruction. citeturn11view0turn11view1

**What data is required to test it properly.** At minimum:

- Wallet trade history with timestamps, side, size, price, and transaction hash (Data API supports trades for a user/markets, and also provides trader leaderboards). citeturn11view0turn11view1  
- Order book snapshots (best bid/ask and depth) at the time *you* would have acted, not when they acted (CLOB `/book` provides bids/asks by price/size). citeturn2view3turn28view1  
- A delay model: your detection lag + request/processing lag + any throttling/queuing (rate limit throttling is explicitly “delayed/queued”). citeturn3view0turn21view3  
- Fee regime for each market (`feesEnabled`, `feeRateBps`), because net PnL is dominated by this in short windows. citeturn6view2  

**What metrics you should track.** The metrics that matter are “copyability,” not raw wallet PnL:

- **Copy lag distribution** (p50/p90 between leader execution time and your actionable detection time). citeturn21view3turn3view0  
- **Slippage vs leader price** (your fill price minus their fill price, signed).  
- **Net edge per trade after costs** (spread + taker fee curve + price impact). citeturn6view2turn28view1  
- **Markout** (midprice after 5s/15s/60s) to quantify adverse selection (if your fills are consistently “picked off,” you’re dead). This is a standard LOB diagnostic in short-horizon execution research. citeturn0search2turn24view0  
- **Exposure overlap / correlation** across coins and windows (how often your copied trades stack in the same direction). citeturn30search0  

**Minimum sample size before trusting it.** You need *a lot* because per-trade edges after fees are small and trades are not independent (bursts, overlapping windows). Sample size requirements depend on desired confidence/power and effect size; under standard power analysis, required N scales like \(\sigma^2 / \Delta^2\), so tiny \(\Delta\) means huge N. citeturn25search1turn22search4  
Practical bar: **at least several thousand observed “copy opportunities” per wallet**, then compute an *effective* sample size discount for autocorrelation/clustering (the idea of effective sample size under dependence is standard; you should not treat clustered trades as independent observations). citeturn22search1

**What would make me reject it entirely.** I would hard-reject live automation if any of the following holds:

- Profitability disappears (or flips negative) when you impose a realistic delay distribution and enforce taker fees + spread. citeturn6view2turn3view0turn28view1  
- The wallet’s edge is dominated by maker-style economics (rebates/spread) or queue position patterns you cannot replicate by reacting. citeturn5view0turn29view0  
- The wallet’s strategy is highly regime-dependent (e.g., only works during specific volatility/fee periods) and you cannot define a stable regime filter ex ante. citeturn6view2turn1view1  

---

### Coin spread or relative-value strategy across coins or related markets

**Core thesis (plain English).** Trade mispricings between related contracts (e.g., BTC vs ETH “Up” probabilities, or the same coin across horizons) where the market’s implied probabilities become inconsistent, expecting convergence as liquidity providers and arbitrageurs restore parity. citeturn28view1

**Why it might work specifically in prediction markets.** There are explicit parity relationships *within* a market design: Polymarket’s own docs describe price discovery where “Yes at 0.60” and “No at 0.40” match because they sum to 1.00, effectively minting the complementary outcome tokens. That kind of structure (and discrete ticks) creates mechanical “should be true” relationships that can be violated transiently in thin books. citeturn28view1turn15view1  
Across *different* coins/markets, prediction markets may be less efficiently arbitraged than CEX spot because participants are fragmented, and market makers can be selective about which markets they quote, especially when rebates are calculated per market. citeturn5view0turn24view1

**Main failure modes.** The failure modes are mostly operational and modelling:

1) **It’s not an arbitrage; it’s basis risk.** BTC–ETH correlation is state-dependent and can change under uncertainty. A “relative value” hedge constructed from historical correlation can fail precisely when you need it (high vol around window boundaries). citeturn30search0  
2) **Two-leg execution risk.** If you need both legs, you face partial fills, queue priority, and legging risk. In a price-time priority book, you can’t assume simultaneous fills at mid; you must model queue position and fill probability. citeturn29view0turn2view2  
3) **Costs stack.** If executed as taker on both legs, you pay two spreads and two taker fees; even “small mispricings” won’t clear that hurdle. citeturn6view2turn28view1  
4) **Overlapping windows create hidden concentration.** A bot can accidentally stack exposures across 5m and 15m products (and across coins) so that a single market move hits many legs at once. citeturn16view0turn30search0  
5) **Data alignment errors.** If your strategy depends on comparing prices across markets, clock skew and timestamp mismatch are fatal; Polymarket’s ecosystem includes server time tooling and explicit rate limits/throttling, so you must defensively engineer time alignment. citeturn3view0turn29view0  

**How latency affects it.** Relative value is typically **very delay-sensitive at entry** (you’re trying to capture a transient inconsistency) and **moderately delay-sensitive at exit** (you want convergence before expiry). Cloudflare throttling that queues requests is particularly dangerous because a queued cancel/replace can convert a “neutral spread” into unwanted directional inventory. citeturn3view0turn21view3

**How fees and slippage affect it.** This is a “small edge” strategy; therefore cost dominates. Your backtest must compute fills on the actual bid/ask ladder (from `/book`) and apply the convex fee curve per market, not a flat bps haircut. citeturn2view3turn6view2turn28view1  
If you can be maker on at least one leg (post-only / resting), the economics change materially because makers pay zero fees and may receive rebates. But you then substitute explicit fees for adverse selection and inventory risk. citeturn6view2turn5view0turn17view0

**Is it robust enough for automation?** **Potentially yes, but only with tight controls.** Among the three ideas, this is the one most naturally compatible with systematic risk limits (pairs exposure caps, legging rules, kill-switches). But it is operationally complex and easy to “accidentally become a market maker” without the infrastructure to manage inventory. citeturn24view0turn21view3turn15view1

**Works better in live trading, shadow mode, or research only?** Best sequence is **research → shadow mode → tiny live**, because almost all failure modes are microstructure/operational and will not show up in mid-price backtests. citeturn28view1turn3view0turn21view3

**What data is required to test it properly.**

- High-frequency (preferably streaming) order book and trade updates per market; Polymarket recommends WebSocket market channels for real-time order book/trade events rather than polling. citeturn1view6turn3view0  
- Historical price series at 1m granularity (or better) for each market to characterise convergence and microstructure volatility (CLOB `prices-history` supports `1m`). citeturn11view2  
- Fee rates per market/token (must query dynamically; markets can be fee-enabled or not). citeturn6view2  
- External “ground truth” reference data for the underlying coins (ideally the same source used in the market’s resolution rules), because your hedge ratios and convergence assumptions depend on how the event is defined. Resolution rules are explicitly market-specific, and Polymarket warns that the title is not enough; the rules govern edge cases. citeturn19view0  

**What metrics you should track.**

- **Realised PnL per spread event**, net of fees and crossing costs. citeturn6view2turn28view1  
- **Legging loss rate**: frequency and magnitude of times you got one leg but not the other. citeturn29view0turn2view2  
- **Inventory drift**: how often you unintentionally accumulate net directional exposure due to partial fills + expiry. citeturn24view0turn21view3  
- **Convergence time vs remaining time to expiry**: if convergence is slower than the window, you’re not running RV—you’re running directional risk with extra steps. citeturn16view0  
- **Tail co-movement / stress correlation** across coins (because correlated blowups are the main existential risk). citeturn30search0  

**Minimum sample size before trusting it.** You should demand a sample over *multiple volatility / liquidity regimes* (quiet periods, high vol, thin books), because microstructure effects are regime-driven. As a practical bar: at least **100–300 distinct “spread divergence episodes” per pair** where you can measure entry → exit behaviour, and then discount for dependence (effective sample size) because episodes cluster in time. citeturn22search1turn25search1

**What would make me reject it entirely.**

- If profitability requires simultaneous mid-price fills (i.e., dies when you simulate bid/ask and queue priority). citeturn28view1turn29view0  
- If the strategy’s drawdowns are dominated by “one big day” where correlations snap or liquidity vanishes (correlated blowup), implying the hedge is illusory. citeturn30search0  
- If net PnL is negative after correctly stacking fees and spread on both legs. citeturn6view2turn28view1  

---

### Buying high-probability contracts around 0.80 to 0.90 per share

**Core thesis (plain English).** Focus on “likely” outcomes (priced 0.80–0.90) so you win often, trying to harvest small edge repeatedly (either by holding to settlement or selling later slightly higher). citeturn28view1turn16view0

**Why it might work specifically in prediction markets.** Two structural reasons are sometimes real:

1) **Fees are lower at extremes** because fee scales with \(p(1-p)\), so trading at 0.85–0.90 pays lower taker fees than trading around 0.50. The published crypto fee table (100 shares) shows fees around $0.92 at p=0.85 and $0.65 at p=0.90 (with higher fees at 0.50), consistent with the fee curve. citeturn6view2  
2) Prediction markets can embed risk preferences and position limits; “high win-rate” positions sometimes attract flow that is not purely expected-value optimal. Prediction market research indicates prices are often good but can be biased under some preference distributions; extreme-belief participants can disproportionately influence prices, pushing toward favorites/longshots depending on preferences. citeturn14view2turn14view3  

**Main failure modes (this strategy is a classic live-trading trap).**

1) **Small edge, large fragility.** At p=0.85, your max gross profit if you hold to $1 is $0.15 per share; a 1–2 cent worse fill or a single extra round trip can destroy expected value. In a book where you must buy the ask and sell the bid, the spread alone can be comparable to your “alpha.” citeturn28view1  
2) **Adverse selection concentrates at high-prob points.** When price is 0.85, you are often buying after a move; informed traders sell to you when the event is about to flip (or volatility mean-reverts in the last seconds). Market microstructure links spreads and liquidity provision to asymmetric information; in short windows, this is amplified. citeturn24view1turn29view0  
3) **Tail losses are correlated and lumpy.** If your bot repeatedly buys “high-prob Up” across coins during momentum, a single sharp reversal can hit all positions at once, especially given crypto co-movement. citeturn30search0turn16view0  
4) **Overtrading.** Because each trade “looks safe,” automation tends to stack exposure and churn inventory. Rate limits, queued requests, and heartbeat failures can then convert churn into unmanaged risk. citeturn3view0turn21view3  

**How latency affects it.** High-prob entries are **highly delay-sensitive** because probability can swing sharply near window end; you can easily end up consistently buying after the price has already adjusted. Also, price-time priority makes “trying to be maker at 0.84” a queue race; if you’re late, you don’t get filled, and if you cross the spread, you become taker and pay costs. citeturn29view0turn6view2turn28view1

**How fees and slippage affect it.** This strategy often “dies by arithmetic”:

- If you act as taker, taker fees apply and are non-trivial even at 0.85–0.90 (see fee curve/table), and fees must be fetched per market dynamically. citeturn6view2  
- Slippage is dominated by spread and depth; Polymarket explicitly warns that large orders may move price significantly and advises checking order book depth. citeturn28view1turn2view3  

A robust version typically *must* be maker-first (post-only/resting) so that you avoid paying taker fees; but then you inherit adverse selection (you get filled when the market is moving against you). citeturn6view2turn17view0turn24view1

**Is it robust enough for automation?** Only **with strict gating and an explicit “don’t trade” state.** The pure “buy 0.85–0.90 because it’s likely” heuristic is not robust; it needs a real signal about mispricing relative to the defined resolution rule, plus disciplined exposure throttles. citeturn19view0turn3view0turn21view3

**Works better in live trading, shadow mode, or research only?** Best used as **research + shadow**, then extremely small live with maker-only entries (if at all). The backtest/live gap is enormous because fills at high-prob points are dominated by queue and last-second price jumps. citeturn29view0turn28view1

**What data is required to test it properly.**

- Full bid/ask ladder snapshots (or deltas via WebSocket) to simulate realistic fills and price impact. citeturn1view6turn2view3  
- Accurate fee rates per market and enforcement of `feesEnabled` to avoid mixing regimes. citeturn6view2  
- External reference price/time series matching the market’s resolution specification (because “Up” is defined against a specific source/timestamp ruleset). citeturn19view0  
- A latency model (including throttling queues and on-chain settlement delays), because high-prob strategies die when acted on late. citeturn3view0turn21view3  

**What metrics you should track.**

- **Net profit per trade** after all explicit fees and spread. citeturn6view2turn28view1  
- **Win rate vs expected** (calibration): whether realised outcomes match your implied probabilities (not because price is truth, but because it diagnoses systematic bias). citeturn28view1turn14view3  
- **Tail loss contribution** (% of total drawdown from worst 1% of trades), because that’s what kills “high win-rate” strategies. citeturn30search0  
- **Turnover / trade frequency** and **exposure stacking** (how many simultaneous “Up” positions across correlated coins/windows). citeturn16view0turn30search0  

**Minimum sample size before trusting it.** Because per-trade edge is small, N must be large. Under standard sample size logic, detecting a small mean edge requires N that grows with \(\sigma^2/\Delta^2\); if your net edge is a few basis points per trade after costs, you can easily need **thousands to tens of thousands** of trades. citeturn25search1turn22search4  
And because trades cluster (overlapping windows, trend bursts), you must discount to an effective sample size rather than raw N. citeturn22search1

**What would make me reject it entirely.**

- If edge vanishes when you simulate fills on the *ask* (not midpoint) and include the correct taker fee curve. citeturn28view1turn6view2  
- If PnL is dominated by a small number of lucky streaks and the strategy has large negative skew (typical for “high probability” harvesting). citeturn30search0  
- If profitability requires trading in the last seconds where you cannot reliably control fills/cancels due to queue priority and throttling/heartbeat risks. citeturn29view0turn3view0turn21view3  

## Cross-strategy comparison and staged rollout

### Head-to-head comparison

| Dimension | Copy-trading top wallet | Coin spread / relative value | Buy 0.80–0.90 “likely” |
|---|---|---|---|
| Expected edge durability | **Low**: depends on external actor + non-copyable execution edge citeturn15view1turn29view0 | **Medium**: structural frictions can persist, but costs/competition compress it citeturn24view1turn5view0 | **Low–Medium**: relies on small edge; costs + adverse selection usually dominate citeturn6view2turn24view1 |
| Implementation complexity | Medium (data + lag model) but hard to do “for real” in 5m/15m citeturn11view0turn21view3 | **High**: multi-market data, hedging, leg execution logic, inventory controls citeturn1view6turn29view0turn21view3 | Medium: simple logic, but robust gating is complex citeturn3view0turn21view3 |
| Operational risk | Medium–High: chasing fills + outages = uncontrolled entries citeturn3view0turn17view0turn21view3 | **High**: two-leg risk + partial fills + correlation shocks citeturn30search0turn2view2 | **High**: overtrading + correlated tails + last-second hazards citeturn30search0turn29view0 |
| Sensitivity to delay | **Extreme**: your signal is “already happened” citeturn15view1turn21view3 | High: divergence windows can be brief; legging risk grows with delay citeturn3view0turn29view0 | High: high-prob points move quickly near expiry citeturn29view0turn16view0 |
| Sensitivity to liquidity | High: copying size moves books, widens slippage citeturn28view1 | **Very high**: you need depth on both legs and predictable fills citeturn2view3turn28view1 | High: thin books turn “safe” into “pay the spread + impact” citeturn28view1turn2view3 |
| Risk of correlated blowups | High: you inherit leader’s clustering across markets citeturn30search0turn11view0 | Medium–High: hedges fail under regime shift citeturn30search0 | **High**: easiest to stack “Up” exposure everywhere citeturn30search0turn16view0 |
| Suitability for solo retail builder | Good for analytics; poor for real-money execution citeturn15view1turn29view0 | Possible but demanding (infra + discipline) citeturn3view0turn21view3 | Easy to build; hardest to make truly robust citeturn6view2turn29view0 |

### Safest one to test first

**Copy-trading, but only in shadow mode (no execution).** It’s the safest way to learn the platform’s true latency/cost structure without paying tuition. You can use the public leaderboard endpoints to pick candidate wallets/markets and the Data API to reconstruct trades, then simulate what *you* would have gotten with realistic delay, spread, and the fee curve. citeturn11view1turn11view0turn6view2turn28view1

### Highest-upside one (if you can execute well)

**Coin spread / relative value**, *if* you implement it as a disciplined, inventory-aware strategy that is very selective about liquidity and avoids taker-taker legging. It is the only one of the three that naturally aligns with “don’t bet the farm on one direction,” provided you cap correlated inventory and refuse to trade when depth is insufficient. citeturn2view3turn30search0turn24view0

### Easiest one to fake-good in backtests but fail live

**Buying 0.80–0.90** is the easiest to make look good if you (incorrectly) assume midpoint fills, constant liquidity, and ignore queue priority and last-second jumps. It will also look artificially stable if you ignore exposure stacking and tail dependence across coins/windows. citeturn28view1turn29view0turn30search0

(Copy-trading is also easy to fake-good if your backtest “fills you at the leader’s price,” but the 0.80–0.90 idea is uniquely seductive because the win-rate hides the fragility until a tail event hits.) citeturn15view1turn28view1turn30search0

### Most realistic staged rollout plan

**Stage: data + simulator (non-negotiable).** Build a replayable feed from WebSocket order book/trades and store snapshots; poll only as backup because rate limits throttle by queuing. Record server time offsets and your own end-to-end latencies. citeturn1view6turn3view0turn29view0  

**Stage: shadow mode for all three ideas in parallel.**  
- Copy-trading: compute “copyable PnL after delay/cost.” citeturn11view0turn6view2turn28view1  
- Relative value: compute divergence frequency, required spread to cover costs, and legging loss rate. citeturn2view3turn6view2turn29view0  
- High-prob buying: compute fill realism and markout at multiple horizons. citeturn29view0turn24view1  

**Stage: tiny live, maker-only, single coin, single window length.** Start with a single liquid coin and enforce post-only orders so you never unintentionally cross and become taker. Validate heartbeat stability and failure handling (engine restarts, cancel-only mode). citeturn17view0turn21view3turn1view5  

**Stage: add complexity only after passing hard gates.** Expand to more coins/horizons only if: (a) your realised slippage matches simulation bands, (b) you survive operational incidents (425 restarts, throttling), and (c) you have a demonstrated edge after costs using realistic fills. citeturn1view5turn3view0turn6view2  

## Design rules for a production bot

These are concrete production rules aimed at survival under fees, slippage, delay, thin books, and correlated exposure. Where rules reference platform behaviour, they align with documented Polymarket mechanics (fees, rate limits, restarts, heartbeat, error modes). citeturn6view2turn3view0turn1view5turn21view3turn17view0

### When to enter

Enter only if all gates are true:

1) **Market integrity gate:** Market has explicit resolution rules you have parsed; never trade a market where “Up/Down” definition or reference source is ambiguous, because the rules—not the title—determine resolution. citeturn19view0  
2) **Fee gate:** Market is `feesEnabled`-known and you have fetched the live `feeRateBps`; do not trade if fee rate cannot be fetched or is stale. citeturn6view2  
3) **Liquidity gate:**  
   - Spread ≤ 2 ticks *or* you can place a post-only order inside the spread without crossing.  
   - Depth at best bid/ask is large enough that your intended size is ≤ 10–20% of visible size at that level (otherwise you are the market). citeturn2view3turn28view1turn17view0  
4) **Latency gate:** Your current p95 order placement + cancel latency is below a threshold you set per window (e.g., for 5m markets, if you cannot reliably cancel/replace within sub-second timescales, you must trade smaller or not at all). This must include the possibility of queued requests under throttling. citeturn3view0turn21view3

### When not to enter

Hard “no trade” conditions:

- **Blackout near expiry:** No new entries in the final portion of the window (e.g., last 10–20 seconds for 5m, last 30–60 seconds for 15m), because last-second flow + price-time priority + queued cancels create unrecoverable adverse selection. citeturn29view0turn3view0  
- **Wide-spread / stale-display regime:** If displayed price is likely last-trade because spread > $0.10, do not trade unless you explicitly model and accept that the shown price is stale and you are trading the live book. citeturn28view1  
- **Operational degradation:** If you observe 425 restart windows, “trading disabled,” or “cancel-only” states, stop entering immediately and focus only on flattening exposure if needed. citeturn1view5turn17view0  
- **Heartbeat risk:** If heartbeat loop is not stable (packet loss, missed intervals), do not run maker exposure; your orders will be canceled automatically, and you will lose control of quoting. citeturn21view3  

### Position sizing

A survivable sizing model for short-horizon markets prioritises *loss containment* over theoretical Kelly:

- **Per-position risk cap:** Size so that the worst-case plausible move (including a gap + spread widening) costs no more than X% of equity (commonly 0.10–0.25% per position for short-horizon automated systems). This matters because correlated tails dominate. citeturn30search0turn24view1  
- **Liquidity-scaled sizing:** Max shares per order = min( your risk cap size, 10–20% of top-of-book visible size). This directly implements the “don’t be the market” rule. citeturn2view3turn28view1  
- **Maker-first bias:** If your model requires taker entries, halve size (or more), because taker pays the fee curve and spread; your breakeven margin shrinks sharply. citeturn6view2turn28view1  

### Max correlated exposure

Define correlation groups and enforce **hard** caps:

- **Group caps:** e.g., (BTC-related majors), (ETH ecosystem / L1s), (memecoins). Set max net directional exposure per group (e.g., ≤ 1.5× a single-position cap). The motive is that crypto co-movement is state-dependent; “many small positions” is not diversification when correlation spikes. citeturn30search0  
- **Window overlap cap:** Do not hold overlapping exposures in both 5m and 15m windows on the same coin in the same direction unless you explicitly treat it as a single combined position with one risk budget. citeturn16view0  

### Multiple entries on the same coin

Default rule for survival: **only one live position per coin per direction per window.**

- If you allow multiple entries, require a **cooldown** (e.g., 1–2 minutes for 5m markets, 3–5 minutes for 15m markets) and require improved price (average-in only if you reduce your average entry cost and remain within the same risk budget).  
- Never “chase” fills by crossing; if you must become taker to re-enter, you are likely converting a small-edge idea into fee + slippage burn. citeturn6view2turn28view1turn17view0  

### When to disable a coin entirely

Disable trading (for a cooling period) if any trigger fires:

1) **Liquidity collapse:** spread widens beyond N ticks for M consecutive seconds, or top-of-book size falls below your minimum tradable size. citeturn2view3turn28view1  
2) **Repeated adverse selection:** persistent negative markout (e.g., median 10–30s markout < −1 tick) that indicates you’re being picked off. citeturn24view1turn0search2  
3) **Operational instability:** repeated 429 throttles (queued requests), 425 restarts without proper recovery, or heartbeat instability leading to forced cancellations. citeturn3view0turn1view5turn21view3  
4) **Rules ambiguity / resolution risk:** any unclear resolution source or contradictory rule clarification—because resolution is oracle-based and disputes can extend timelines; do not take “definition risk” for 5-minute profits. citeturn19view0turn19view1turn19view3  

---

**Bottom line as a skeptical execution-focused reviewer:**  
- Live copy-trading of a “top wallet” in 5m/15m direction markets is usually **not copyable alpha**; it’s mostly a delayed, worse-priced shadow of someone else’s non-public order flow and queue position. citeturn15view1turn29view0turn21view3  
- Relative value is the only idea of the three that can plausibly be engineered into a controlled-risk system, but it is also the most operationally complex and the most sensitive to liquidity and legging. citeturn2view3turn30search0turn3view0  
- Buying 0.80–0.90 “likely” outcomes is the easiest to build and the easiest to fool yourself with; it requires unusually strong discipline to avoid turning fees + slippage + correlated tails into a slow bleed punctuated by catastrophic drawdowns. citeturn6view2turn28view1turn30search0