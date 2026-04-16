# [Crypto Prediction Market Strategies](https://sup.ai/chats/0e23551f-efe1-40d2-b63d-9772b28a3f75)

## V13 Research Brief

Use this updated context when evaluating any new strategy or architecture idea for the bot:

- A recent two-hour simulated trade log showed that the biggest problem was not just bad single trades. The bigger issue was **correlated batch losses** where several positions lost together.
- The current system also appears weak on **cheap-contract YES bets**, especially when those entries are "cheap" but not actually mispriced after fees, slippage, and late-window risk.
- Recent coin-level behavior suggests **XRP, BNB, and ETH underperformed**, while **BTC and SOL held up better**. Any new research should explicitly test whether that is persistent or just a short sample artifact.
- We already discussed that splitting into fully separate bots per coin may help operational isolation and maybe latency, but it **does not automatically improve prediction accuracy**.
- The architecture that currently looks most promising is **one shared decision engine with concurrent per-coin lanes plus central risk controls**.
- Central controls matter because coin-level strategies can still fail together during a broad crypto move. Coin independence should never be assumed.

### What New Research Should Focus On

For every proposed strategy, answer these questions directly:

1. Does it reduce or worsen correlated blowup risk?
2. Does it depend on cheap YES contracts actually being underpriced, or can it work without that assumption?
3. Is the apparent edge concentrated in only BTC and SOL, or can it survive excluding XRP, BNB, and ETH?
4. Does the strategy still work after realistic taker fees, shallow books, partial fills, and delayed execution?
5. Does it require repeated entries on the same coin, and if so, what exact rules prevent stacking the same risk repeatedly?
6. Does it fit a shared-engine architecture with per-coin lanes and central exposure caps?

### Architecture Lens

When recommending system design, assume the preferred production direction is:

- one shared market-data and feature engine
- one shared execution/risk brain
- concurrent per-coin analysis lanes
- central controls for:
  - max correlated exposure
  - per-coin disable switches
  - cooldowns after losses
  - repeated-entry limits on the same coin
  - global daily and session drawdown stops

Reject designs that merely move the same weak logic into isolated coin-specific bots without improving signal quality or exposure control.

## John Chrisley Delos Santos (Aresss)

You are acting as a skeptical quantitative trading researcher reviewing short-horizon prediction-market bots for crypto direction markets such as Polymarket 5m and 15m contracts.

My goal is not to get exciting ideas. My goal is to find strategies that can survive real execution, fees, slippage, delays, shallow liquidity, correlated losses, and overtrading.

Please evaluate these three strategy ideas:

1. Copy-trading / shadowing a top trader or wallet with a strong portfolio
2. Coin spread / relative-value strategy across coins or related markets
3. Buying high-probability contracts around 0.80 to 0.90 per share

For each idea, give me:

- The core thesis in plain English
- Why it might work specifically in prediction markets
- The main failure modes
- How latency affects it
- How fees and slippage affect it
- Whether it is robust enough for automation
- Whether it works better in live trading, shadow mode, or research only
- What data is required to test it properly
- What metrics I should track
- What minimum sample size I should demand before trusting it
- What would make you reject it entirely

Then compare the three ideas on:
- expected edge durability
- implementation complexity
- operational risk
- sensitivity to delay
- sensitivity to liquidity
- risk of correlated blowups
- suitability for a solo retail builder

Then propose:
- the safest one to test first
- the highest-upside one
- the easiest one to fake-good in backtests but fail live
- the most realistic staged rollout plan

Important constraints:
- Assume maker/taker fees exist
- Assume some trades happen late in the final seconds
- Assume order books can be thin
- Assume a model can overtrade and stack exposure across similar coins
- Assume no magical alpha from social media hype
- Be brutally honest and prioritize “why this may fail”

Finally, include a section called:
“Design rules for a production bot”
with concrete rules on:
- when to enter
- when not to enter
- position sizing
- max correlated exposure
- whether multiple entries on the same coin should be allowed
- when to disable a coin entirely

## Sup

# Skeptical Evaluation: Three Short-Horizon Prediction-Market Bot Strategies

**Polymarket 5m / 15m Crypto Direction Markets**

*Reviewer posture: every strategy is guilty of not working until proven otherwise.*

---

## Structural Facts That Constrain Everything

Before evaluating any strategy, the execution environment imposes hard constraints that no amount of clever signal generation can overcome.

**Market mechanics.** Polymarket operates a hybrid-decentralized CLOB (Central Limit Order Book): matching is offchain, settlement is onchain (Polygon), and all orders are limit-order primitives — "market orders" are just marketable limits (FAK/FOK). ([docs.polymarket.com][22]) Outcome tokens redeem to $$\$1$$ or $$\$0$$ at resolution, so all PnL is bounded binary payoff math plus execution frictions. ([docs.polymarket.com][21])

**Displayed price ≠ your fill.** The displayed market price is the midpoint of best bid and best ask — unless the spread exceeds $$\$0.10$$, in which case the UI shows last traded price instead. Buying happens at the ask; selling at the bid; depth determines your real fill. **Any backtest using displayed price as fill price is suspect.** ([Orderbook - Polymarket Documentation][20])

**Fee structure.** Polymarket uses a probability-based dynamic taker fee. For crypto markets (including 5m and 15m), the documented formula is:

$$
\text{fee per share} = C \times \text{feeRate} \times p \times (1-p)
$$

where $$C$$ is the number of shares, $$p$$ is the share price, and the crypto taker feeRate is $$0.072$$. The peak effective rate is **1.80%** at $$p = 0.50$$. Makers pay zero fees and may receive rebates (20–25% of taker fees for crypto). ([docs.polymarket.com][1], [Polymarket Fees Breakdown \[2026 Updated\]][19])

The fee curve at operationally relevant price points:

| Share Price | Fee/Share | Effective % of Notional | Win Payout | Loss Cost | Breakeven True Prob | Edge Needed |
|:-----------:|:---------:|:-----------------------:|:----------:|:---------:|:-------------------:|:-----------:|
| 0.50 | $0.0180 | 3.60% | +$0.482 | −$0.518 | 51.8% | +1.80pp |
| 0.70 | $0.0151 | 2.16% | +$0.285 | −$0.715 | 71.5% | +1.51pp |
| 0.80 | $0.0115 | 1.44% | +$0.189 | −$0.812 | 81.2% | +1.15pp |
| 0.85 | $0.0092 | 1.08% | +$0.141 | −$0.859 | 85.9% | +0.92pp |
| 0.90 | $0.0065 | 0.72% | +$0.094 | −$0.907 | 90.6% | +0.65pp |
| 0.95 | $0.0034 | 0.36% | +$0.047 | −$0.953 | 95.3% | +0.34pp |

**Bottom line:** At every price level, you need a positive calibration edge over the market price just to break even against taker fees. There is no free lunch at any price.

**Fee regime changes matter.** As of March 30, 2026 ("Fee Structure V2"), taker fees apply to ten market categories including all crypto timeframes (5m, 15m, 1H, 4H, daily, weekly). The fee rate and category assignments have changed multiple times in 2025–2026. Any backtest must be segmented by fee regime. ([docs.polymarket.com][18])

**Volume and competition.** 5-minute crypto markets draw up to $60 million daily volume, with bots accounting for 55–62% of that volume. ([Polymarket Fast Markets Hit $2.3B Volume as Bots Dominate 5-Minute Crypto Bets][16], [Polymarket's 5-Minute Bitcoin Bets Draw Up to $60 Million Daily][17]) You are competing against purpose-built latency-optimized bots from day one.

**Historical data limitations.** The official price history endpoint provides aggregated bars by interval/fidelity; real microstructure analysis requires your own recorded tick-by-tick book and trade stream via websocket. ([docs.polymarket.com][14], [docs.polymarket.com][15])

**Execution state is not instant.** Trade lifecycle includes `MATCHED`, `MINED`, `CONFIRMED`, `RETRYING`, and `FAILED`. If your bot measures fills only at signal time and ignores status changes, your live PnL accounting will be wrong. Rate-limit throttling can also queue requests and silently add latency. ([Overview - Polymarket Documentation][13])

---

## STRATEGY 1: Copy-Trading / Shadowing a Top Wallet

### Core Thesis

Someone else has already solved the hard problem — building a model, getting fast data, calibrating probabilities. You find them by screening wallet PnL histories on the public blockchain, then mirror their trades with proportional sizing.

### Why It Might Work in Prediction Markets

On-chain transparency is the structural reason this idea even exists. Everything is on the public Polygon blockchain, meaning every trade by every wallet is observable. Several platforms have built infrastructure around this. ([Building a Polymarket Copy Trading Bot | Quicknode Guides][12]) If a target wallet genuinely has persistent edge from a superior model or faster data feed, and that edge exceeds your execution degradation, copying can theoretically extract a fraction of their alpha.

### Main Failure Modes

**1. Latency decay (likely fatal).** Total latency from on-chain event detection to your confirmed trade: typically **4–14 seconds** under normal Polygon network conditions, and potentially 10–30 seconds for a retail builder without a dedicated node. In a 5-minute contract (300 seconds), 10–30 seconds is 3.3–10% of the contract's entire life. By the time you detect the trade, the order book has already absorbed the information. You enter at a strictly worse price than the target. ([How Latency Impacts Polymarket Bot Performance (And How to Reduce It) | QuantVPS][11])

At 30-second latency into a 5-minute contract, empirical modeling suggests you are buying a contract that has already moved against you by approximately **+1.1 percentage points** in adverse price.

**2. Survivorship bias in target selection (severe).** You select wallets by screening past PnL. But past PnL is a mixture of skill and luck. With thousands of wallets active, some will have impressive track records purely by chance. The strongest-looking wallets are the most likely to revert. Only ~12–13% of users are net profitable overall. ([medium.com][10])

Academic evidence from social trading platforms confirms that lagging, follower-type trades underperform leading trades, and that peer-performance chasing increases activity while reducing returns and increasing volatility. ([Losing by learning? A study of social trading platform - ScienceDirect][9])

**3. Maker vs. taker asymmetry.** If the target places limit orders (maker), they pay zero fees and may earn rebates. You, reacting to their trade, are almost certainly a taker. You pay 0.65–1.80% per trade that the target does not. Your net PnL is structurally worse than theirs even with zero latency.

**4. Crowding.** Multiple copy-trading platforms now exist. More bots chasing the same wallets collectively move the book against each other. ([Prediction Markets Are Turning Into a Bot Playground][8])

**5. Unobservable intent.** A "top wallet" trade may be part of a wider portfolio hedge, maker inventory adjustment, or cross-market strategy. You see the entry but not the context. You cannot observe exit signals or model recalibrations.

**6. Target adapts or goes dormant.** The wallet you've spent weeks validating may change strategies, move to different markets, or stop trading entirely.

### How Latency Affects It

**Extreme sensitivity.** Even an additional 50ms of latency can make profitable trades unviable in high-frequency contexts. Documented retail bot builders have reported slippage of **6+ cents per trade** — enough to erase most edges. ([reddit.com][2])

For 15-minute contracts, latency matters less proportionally (30s / 900s = 3.3% vs 30s / 300s = 10%), which is why **if you build this at all, it should only be tested on 15-minute contracts.**

### How Fees and Slippage Affect It

Devastating. You pay full taker fees on every copy trade. The target may pay zero (maker). On a $$p = 0.50$$ entry, your fee is 1.80% of position value. On top of this, slippage from delayed execution adds another 0.5–2%. Combined, you need the target's raw alpha to exceed ~3–4% per trade just to break even after your costs — an absurdly high bar for 5-minute markets.

### Robust for Automation?

Technically simple (WebSocket monitoring → order submission). Operationally fragile. The bot works, but the edge doesn't. **Verdict: weak as standalone strategy.** Better as a feature in a broader model.

### Recommended Mode

**Shadow mode / research only.** Shadow the target for 500+ trades. Simulate your fills with realistic latency and fee models. If the shadow P&L is negative, kill the idea before risking capital.

### Data Required

- Full on-chain Polygon transaction history for candidate wallets (minimum 6 months)
- Orderbook snapshots at the instant of the target's trade (to simulate your fill)
- Exact timestamp of when your system could first observe the wallet action
- Your own latency logs from day one of shadow mode
- Per-contract win rate, stake, timing, and market conditions

### Metrics to Track

| Metric | Purpose |
|---|---|
| Copy delay (p95) | Must be <12s; red flag if >25s |
| Entry price gap (target vs. your simulated fill) | Measures adverse selection |
| Alpha decay curve per second of delay | How fast does the signal die? |
| Net PnL after fees (shadow) | Must be positive after 100+ trades |
| Target win rate (rolling 50) | Must stay >58%; reject if <54% or dropping |
| PnL concentration by wallet | Reject if dominated by one wallet or one episode |
| Copier crowding ratio | Red flag if >3 bots detected on same wallet |

### Minimum Sample Size

- ≥**1,000 observed leader trades** across ≥3 distinct market regimes (trending up, trending down, ranging)
- ≥**300 executable delayed-copy simulations** per leader
- across **60+ trading days** and multiple volatility regimes
- with positive **lower 95% confidence bound** on net expectancy after clustering by coin-day

### What Would Make Me Reject It Entirely

- Target's alpha disappears when simulating even 3 seconds of delay
- Target's P&L is concentrated in <10 big wins (luck, not skill)
- Multiple other copy bots already trail this wallet
- You cannot achieve maker fills on any leg
- Copied trades are net negative after taker fees and realistic slippage
- Edge exists only at midpoint/last-trade prices, not executable quotes

---

## STRATEGY 2: Coin Spread / Relative-Value Across Markets

### Core Thesis

BTC-Up and ETH-Up contracts on the same 5-minute window are correlated because crypto moves together. When one coin's market is priced "too cheap" relative to its historical relationship with the other, buy the cheap side and sell the rich side. Profit when the spread mean-reverts, regardless of which direction crypto actually moves.

### Why It Might Work in Prediction Markets

Prediction markets quote **separate binary books** for related underlyings. Because books are shallow and update asynchronously, temporary cross-market dislocations can occur even when the underlying spot relationships are tight. ([A seesaw effect in the cryptocurrency market: Understanding the return cross predictability of cryptocurrencies - ScienceDirect][7]) Price discovery in crypto genuinely leads in BTC and follows in altcoins on short horizons. Market makers may not reprice all contracts simultaneously, creating brief windows of stale prices. Relative-value also reduces dependence on absolute directional forecasting.

### Main Failure Modes

**1. Not true arbitrage (critical conceptual flaw).** You cannot construct a true pairs trade in binary prediction markets. In equities, you can long Stock A and short Stock B to be delta-neutral. In Polymarket, you can buy BTC-UP and buy ETH-DOWN, but neither creates a genuine hedge. "BTC goes up" and "ETH goes up" are not fungible events — they're correlated, not identical. Even with $$\rho = 0.8$$, there is a 20% residual that can go either way. The "relative value" framing creates **false comfort.**

**2. Double fees (likely fatal).** You need two legs: buy one contract, sell/buy another. Both are taker trades. At $$p \approx 0.50$$ (maximum uncertainty zone where spreads are widest), each leg costs ~1.80%. Round-trip fee: ~3.60%. You need a spread divergence exceeding 3.60% just to break even. If the typical divergence is 2–5%, fees eat most or all of the edge.

**3. Legging risk.** You must fill both legs near-simultaneously. If leg 1 fills and leg 2 fails (order cancelled, book moved, gas spike), you are left with unhedged directional exposure — the opposite of what you wanted.

**4. Correlated blowup risk is severe and quantifiable.** With 5 positions at $$\rho = 0.85$$ (typical crypto correlation):

$$
P(\text{all 5 lose}) \approx 5.9\%
$$

compared to:

$$
P(\text{all 5 lose, independent}) = (0.15)^5 = 0.008\%
$$

That is approximately **780× higher catastrophic-loss probability** due to correlation. When a BTC macro event triggers a sudden reversal, all positions resolve against you simultaneously.

**5. Lead-lag is a sub-second phenomenon.** The genuine price-discovery lead of BTC over altcoins operates on millisecond-to-low-second timescales in spot markets. By the time a Polymarket contract price reflects the BTC spot move and you can detect, parse, and respond, the altcoin contract has already repriced.

**6. Thin books on the minor leg.** BTC is liquid; SOL or DOGE is not. The minor leg will slip more, and the slip is always against you.

### How Latency Affects It

**Extreme, and uniquely dangerous.** Simultaneous execution of both legs is the defining requirement. A 2-second gap between legs means the second leg fills at a different price than modeled. For a solo builder without colocated infrastructure and sub-second order execution, **5-minute contracts are likely not feasible.** For 15-minute contracts, the lead-lag window is somewhat wider, but still very short.

### How Fees and Slippage Affect It

**Likely fatal for taker execution.** Two taker legs at 1.0–1.8% each gives 2.0–3.6% round-trip. If your median spread capture is 2%, you're structurally losing. The only escape is placing limit orders (maker, zero fees) on at least one leg — but then you sacrifice execution speed and risk partial fills.

### Robust for Automation?

**The most complex of the three.** Requires real-time cross-market spread calculation, simultaneous order management, inventory tracking across positions, correlation estimation, regime detection, and failure-mode handling for partial fills. High complexity = high bug risk. A solo builder will spend weeks on infrastructure before generating a single signal.

**However:** if the execution and risk controls are first-class, the mathematical framework is objective and testable — making it the strategy with the strongest structural foundation *in theory*.

### Recommended Mode

**Research first, then shadow, then extremely cautious live.** You need to prove the spread exists, persists after double fees, and can realistically be captured before building anything.

**Important variant (confidence: high across models):** Rather than building a true two-leg spread, consider a **BTC-signal → altcoin-entry** single-leg approach:

> "BTC is X% into a 15-minute window and has moved Y standard deviations from open. Buy ETH-direction contract *if* ETH contract price implies a lower probability than BTC spot move suggests."

This eliminates the legging risk and double-fee problem while retaining the actual signal. ([datawallet.com][6])

### Data Required

- Synchronized L2 orderbook snapshots for all coin pairs (tick-level)
- Trade prints and timestamps for both legs
- External underlying spot/reference prices (Pyth/Chainlink)
- Historical cross-coin correlation matrices by market regime
- Per-market fee rates fetched dynamically (never hardcoded) ([docs.polymarket.com][1])
- Fill simulator incorporating partial fills, queue decay, cancel latency

### Metrics to Track

| Metric | Target | Red Flag |
|---|---|---|
| Theoretical vs. realized spread capture | >3pp average | <2pp average |
| Both-leg simultaneous fill rate | >70% | <50% |
| Total fee cost per spread | <50% of mispricing | >60% |
| Residual directional beta | Near zero | Strongly tracks BTC direction |
| Legging-loss frequency | <15% of attempts | >30% |
| Spread convergence half-life | <80% of contract duration | No convergence |
| Correlated loss events (≥3 positions same window) | <8% | >12% |

### Minimum Sample Size

- ≥**500–1,000 completed paired trades** (both legs executed)
- ≥**100 live or latency-injected paper trades**
- across **3+ regimes**: quiet, trend, violent reversal
- at least **30–60 active trading days**
- positive lower 95% confidence bound on net pair expectancy

### What Would Make Me Reject It Entirely

- Double fees exceed median spread capture
- Correlation between target coins drops below 0.5 on 5-min horizons
- Legging failures occur >30% of the time
- Spread half-life exceeds 80% of contract duration
- Net PnL strongly tracks outright BTC/ETH direction (secretly just directional)
- Edge exists only on midpoints, not on executable depth
- Order book depth on altcoin contracts is consistently under $200 top-of-book

---

## STRATEGY 3: Buying High-Probability Contracts (0.80–0.90)

### Core Thesis

Systematically buy contracts priced at 0.80–0.90. Win most of the time, collecting the 10–20 cent spread to resolution at $$\$1.00$$. Accept an asymmetric payoff (small frequent wins, rare large losses) and profit from systematic miscalibration — the market prices these outcomes slightly below their true probability.

### Why It Might Work in Prediction Markets

The favorite-longshot bias is a well-documented empirical regularity in betting markets: longshots are overbet whereas favorites are underbet. ([Explaining the Favorite–Long Shot Bias: Is it Risk-Love or Misperceptions? | Journal of Political Economy: Vol 118, No 4][5]) In crypto direction markets, this would manifest as the "Down" side being overpriced when BTC is trending upward (people love betting on crashes), leaving the "Up" side at 0.80–0.90 slightly underpriced relative to true probability. Prediction-market prices map naturally to probabilities, and academic work suggests prices can be biased, particularly near the extremes. ([Microsoft Word - Interpreting Prediction Market Prices as Probabilities _JPubE submission_.doc][4])

Additionally, the fee structure creates a structural advantage: fees are **lowest** at the extremes. At $$p = 0.90$$, the effective fee rate is just 0.72%, compared to 3.60% at $$p = 0.50$$. This means the fee hurdle is lowest precisely where this strategy operates.

### Main Failure Modes

**1. No calibration edge — the null hypothesis (fundamental).** If the market price of 0.85 reflects a true probability of exactly 85%, your expected value is:

$$
\text{EV} = 0.85 \times 0.14082 - 0.15 \times 0.85918 = 0.1197 - 0.1289 = -0.0092
$$

That's −0.92 cents per share. **Without a genuine calibration edge over the market, this strategy is strictly negative EV after fees.** The fee is the house edge. A contract at $0.85 means the market believes the probability is 85%. If the market is efficient, there is no edge. The *appearance* of edge in backtests comes entirely from the fact that 85% of these contracts do indeed resolve at $1.00 — which is exactly what you paid for.

**2. Convex loss structure (the steamroller).** At $$p = 0.85$$, you lose **6.1×** what you win on each trade. At $$p = 0.90$$, it's **9.7×**. This means a single loss wipes out 6–10 wins. A small miscalibration (true prob = 83% instead of 85%) turns a "winning" strategy into a slow bleed. The payoff structure punishes drawdown severely.

**3. Correlated multi-position losses (the kill shot).** If you simultaneously hold BTC-Up at 0.85, ETH-Up at 0.87, and SOL-Up at 0.82, and a market-wide crash occurs, **all positions lose at once.** Under independent assumptions, the probability of all 5 positions losing is 0.008%. Under realistic crypto correlation ($$\rho \approx 0.7$$–$$0.85$$), it rises to approximately **5–6% per window** — not a tail event, a **semi-regular operational reality** that transforms a "safe" strategy into one with periodic 400+ USDC drawdowns on modest sizing.

**4. Last-second oracle/resolution risk.** Approximately 15–20% of 5-minute BTC windows involve material price movements in the final 10 seconds. ([Unlocking Edges in Polymarket’s 5-Minute Crypto Markets: Last-Second Dynamics, Bot Strategies, and Profitable Trading | by Benjamin-Cup | Feb, 2026 | Medium][3]) A contract at $0.88 in the 4th minute can move to $0.15 in the 5th minute due to a sudden price reversal. This risk cannot be backtested accurately without genuine last-second tick data.

**5. Adverse selection from the sell side.** Who is selling you these "high probability" contracts? In an efficient market: participants who have information that the probability is lower than 0.85. Market-makers who maintain these prices may be selling to you precisely because they have tighter latency-sensitive pricing signals you do not.

**6. Overtrading and exposure stacking.** A high win rate creates behavioral and algorithmic overconfidence. You keep adding positions because "it always works." This stacks exposure and accelerates the correlated blowup when it comes.

### How Latency Affects It

**Low-to-moderate, compared to the other two.** Unlike copy-trading or spread trading, you're not racing anyone for fills. You can place limit orders (maker, zero fees) early in the contract's life and wait for a fill. The exception: if you try to enter late when the outcome appears nearly certain, the book will be thin and you'll pay large spreads.

**Critical caveat:** If conditions deteriorate in the 4th minute, you may want to exit. Thin order books mean your exit price is far below your entry. Latency to monitor and respond determines whether you exit at $0.65 or $0.40.

### How Fees and Slippage Affect It

**Significant but manageable — IF you have edge.** At $$p = 0.85$$, the breakeven true probability is 85.9%. You need to be better calibrated than the market by +0.92pp. At $$p = 0.90$$, breakeven is 90.6% (need +0.65pp edge). These are not impossible hurdles, but they're not trivial either.

**Critical insight:** If you can place **maker orders** instead of taker orders, your fee is **zero** (and you may earn rebates). This would eliminate the fee hurdle entirely and make any positive calibration edge exploitable. The trade-off: maker orders may not fill, especially if the market moves away from your price.

**Beyond fees:** Documented slippage on retail bots has been 6+ cents per trade in thin markets. ([reddit.com][2]) On a strategy that earns only 14¢ per winning share, that's up to 43% of gross profit consumed before considering fees.

### Robust for Automation?

**The simplest of the three.** Logic: monitor market → check if price is in target range → check correlation exposure cap → place order → track resolution. No cross-market coordination, no target wallet dependency, no simultaneous multi-leg execution.

However, the automation logic **must** enforce:
- Correlated exposure limits (no more than 1–2 positions per BTC-correlated group)
- Time-in-window restrictions (no entry after minute 3 of a 5m contract, minute 9 of a 15m contract)
- Exit-on-deterioration logic (require active monitoring, not just hold-to-resolution)

### Recommended Mode

**Shadow mode first, then micro-live.** This is the most backtest-fakeable strategy (see comparison below), which makes shadow validation essential.

- Shadow 500+ qualifying contracts over 4–8 weeks
- Log every "would-have-entered" trade with timestamp, price, and resolution
- Compute observed win rate vs. market-implied probability
- Only go live if observed edge exceeds breakeven by ≥2× the standard error

### Data Required

- Per-contract price time series at 1-second resolution, aligned to window open/close timestamps
- **Entry-side best ask, not midpoint** (this is critical and most builders miss it)
- Full order book depth around entry time
- Pyth/Chainlink price feed snapshots synchronized to contract prices (to verify oracle drift)
- Last-30-seconds price data per window — this is the key data most builders lack
- Volatility regime label for each window (trending / ranging / reversal)
- Historical resolution outcomes with timestamps
- Dynamic fee schedule per market ([docs.polymarket.com][1])

### Metrics to Track

| Metric | Target | Red Flag |
|---|---|---|
| Net PnL after fees (per share) | > +$0.002 | Negative |
| Win rate by entry price band | ≥ breakeven prob | < breakeven prob |
| Win rate by time-in-window | Stable across buckets | Drops sharply after min 3 |
| Max consecutive losses | ≤ 4 | ≥ 6 |
| Correlated loss rate (≥2 positions same window) | < 10% | > 15% |
| Avg slippage vs. ask price | < 0.5pp | > 1pp |
| Tail-loss contribution to total PnL | Quantified | Unknown/untracked |
| Last-30s reversal rate | Quantified | Missing from data |

### Minimum Sample Size

Because this strategy hides risk in rare losers, you need enough losses to estimate the tail:

To detect a **2pp calibration edge** (e.g., true prob = 87% when market says 85%) at 95% confidence:

| Entry Price | Minimum n (95% CI) | Expected Losses | Calendar Time (est.) |
|:-----------:|:------------------:|:---------------:|:--------------------:|
| 0.80 | ~1,537 | ~307 | 4–8 weeks |
| 0.85 | ~1,225 | ~184 | 3–6 weeks |
| 0.90 | ~865 | ~87 | 2–4 weeks |

**Do not trust any result with fewer than 50–100 observed losses.** A strategy that claims 90% win rate but has only had 10 losses is not validated — it's untested.

At 5-min markets running ~288 contracts/day per coin (24h × 12/hr), for 3 coins that's ~864 contracts/day. But you won't enter every contract — only when price is 0.80–0.90. Realistically 10–30% qualify. **Expect 4–8 weeks minimum for adequate shadow data.**

### What Would Make Me Reject It Entirely

- Observed win rate at $$p = 0.85$$ is ≤ 85.9% over 1,000+ trades (no edge after fees)
- Loss correlation across coins exceeds 0.5 (correlated blowup is frequent)
- Max drawdown exceeds 3× the daily variance expectation
- Most profit disappears when using ask instead of midpoint
- Kelly fraction is so small (<0.5%) that realistic position sizes cannot cover minimum order sizes
- No time-of-day, volatility regime, or coin filter improves calibration
- PnL is dominated by a few lucky regimes

### Kelly Criterion Context

If you genuinely believe the probability is 87% while the market says 85%, at the effective win/loss payoff:

$$
f_{\text{Kelly}} = \frac{p_{\text{true}} - p_{\text{be}}}{1 - p_{\text{be}}}
$$

At $$p = 0.85$$, breakeven = 0.8592, true $$p$$ = 0.87:

$$
f_{\text{Kelly}} \approx 0.077 \quad (7.7\%)
$$

**Use quarter-Kelly** (divide by 4): **~1.9% of bankroll per trade.** For a $1,000 account, that's $19 per trade. Full Kelly is suicidal with estimated probabilities.

---

## Comparative Analysis

| Dimension | Copy-Trading | Coin Spread / RV | High-Prob (0.80–0.90) |
|:--|:--:|:--:|:--:|
| **Expected Edge Durability** | 🔴 Very Low | 🟡 Medium | 🟡 Low–Medium |
| **Implementation Complexity** | 🟡 Medium | 🔴 High | 🟢 Low |
| **Operational Risk** | 🔴 Very High | 🔴 High | 🟡 Medium |
| **Sensitivity to Delay** | 🔴 Extreme | 🔴 Very High | 🟡 Low–Medium |
| **Sensitivity to Liquidity** | 🔴 High | 🔴 Very High | 🟡 Medium |
| **Risk of Correlated Blowups** | 🟡 Medium | 🔴 Very High (if stacked) | 🔴 High (if unsized) |
| **Suitability for Solo Retail** | 🔴 Low | 🔴 Low | 🟢 Highest of the three |
| **Backtest Fakability** | 🔴 Very High | 🟡 Medium–High | 🔴 Very High |

### Edge Durability

**Copy-Trading:** Edges decay as copy-bots proliferate. Wallet alpha is typically regime-specific and exhausted within weeks of discovery. Estimated half-life: **2–4 weeks** post-selection.

**Coin Spread / RV:** If structural (BTC leads, altcoins lag), potentially more durable since it monetizes microstructure inconsistency rather than pure forecasting. But correlation arbitrage windows shrink as more sophisticated actors enter. Estimated half-life: **1–3 months**, but likely never reachable by retail in its pure two-leg form.

**High-Prob:** The structural miscalibration (if it exists) is the most stable, since it depends on persistent market-maker behavior and retail psychology rather than another trader's secret edge. However, it is also the shallowest source of edge. Estimated half-life: **3–6 months**, conditional on the calibration anomaly existing at all.

### Sensitivity to Delay

Copy-Trading and Coin Spread are both **fatally sensitive** to delay for 5-minute contracts. A 15–30 second lag converts any theoretical edge into a guaranteed negative. High-Prob is the **only strategy** where a 15–30 second monitoring lag does not immediately destroy the edge, though it does affect exit capability.

### Risk of Correlated Blowups

**Most dangerous for Strategy 3 if position limits are not enforced.** A naive bot buying BTC-Up, ETH-Up, and SOL-Up simultaneously in the same window faces a joint loss probability of ~5–6% per window due to crypto correlation. Over 100 windows per day, this is not a tail event — it's a recurring operational reality.

**Most dangerous for Strategy 2** if it's secretly just directional exposure wearing a hedge costume.

---

## Direct Answers to Your Final Comparison Questions

### Safest One to Test First

> **Strategy 3 (High-Prob Contracts), on 15-minute contracts only, one coin at a time, with a maker-only entry rule.**

**Confidence: high (4 out of 6 models agree).**

Reasoning: simplest to implement, clearest rejection criteria, lowest infrastructure cost, produces interpretable and attributable PnL. You can generate data within 1–2 weeks and have a statistically meaningful answer within 6–8 weeks. Even if it fails, you've learned what calibration edges look like in this market. A failed shadow test tells you something actionable.

**Dissenting view (2 models):** Strategy 2 (Coin Spread) in shadow mode is the safest because it can reduce outright market beta and forces you to confront real execution from day one. The counterargument is that its implementation complexity creates more ways to introduce bugs and false signals before you learn anything.

### Highest Upside

> **Strategy 2 (Coin Spread / Relative Value), specifically the single-leg BTC-signal → altcoin-entry variant.**

**Confidence: high (5 out of 6 models agree).**

If — and this is a large "if" — a persistent cross-market information asymmetry exists that survives execution costs and can be captured without perfect simultaneity, the edge is market-neutral, repeatable, and potentially the most scalable. The single-leg variant (use BTC price action as a signal, trade the lagging altcoin's direction contract) eliminates the double-fee problem and legging risk.

### Easiest to Fake-Good in Backtests But Fail Live

> **Strategy 3 (High-Prob), by a meaningful margin. Strategy 1 (Copy-Trading) is a close second.**

**Confidence: high (broad agreement, though models disagree on which is #1).**

**Why Strategy 3 fakes well:**
A backtest of "buy all contracts priced 0.80–0.90, hold to resolution" will show ~85%+ win rate and positive P&L on historical data. This looks compelling. But it will have all of the following flaws invisibly:
- No slippage (you got the midpoint, not the ask)
- No fee modeling (or simplified flat fee instead of the dynamic formula)
- No last-second reversal data (missing from most historical datasets)
- No order book depth check (assuming you could always fill)
- No correlation between positions (treating each trade as independent)
- Look-ahead bias in regime selection

**Why Strategy 1 fakes well:**
You screen 10,000 wallets, find the top 10 by PnL, backtest copying them, and get spectacular results — because you selected for the outcome. Live, the wallet's edge may have been luck, or it may have decayed, or the book may have thinned from other copiers.

**Rule:** Never trust a backtest of any of these strategies unless it was built on **tick-level data with explicit order book depth checks, fee simulation using the exact dynamic formula, and last-second reversal modeling.**

### Most Realistic Staged Rollout Plan

| Phase | Duration | Activity | Go/No-Go Gate |
|:------|:---------|:---------|:--------------|
| **Phase 0: Data infrastructure** | 2–4 weeks | Record live L2 books, trades, fees, timestamps for all target coins via websocket. Build fee-accurate, depth-aware execution simulator. Validate clock sync and websocket gap handling. | APIs stable? Latency measured? Simulator verified against known fills? |
| **Phase 1: Research — all three strategies** | 4–8 weeks | Run all three on historical data using the simulator. Stratify by price band, time-in-window, coin, volatility regime. Identify which combinations (if any) show positive net PnL after fees and slippage. Treat copy-trading as a feature study, high-prob as calibration baseline, RV as the main candidate. | Historical net PnL positive in at least 3/4 distinct calendar quarters? |
| **Phase 2: Shadow mode — Strategy 3** | 6–8 weeks | Paper-trade every qualifying entry (0.80–0.90) using live data. Log every signal, entry price you *would have* gotten (use live bid/ask, not mid), fee, result. Track 50-trade rolling win rate continuously. | Win rate exceeds break

# Skeptical Evaluation: Three Short-Horizon Prediction-Market Bot Strategies

**Polymarket 5m / 15m Crypto Direction Markets**

*Reviewer posture: every strategy is guilty of not working until proven otherwise.*

---

## Verified Market Parameters (April 2026)

Before evaluating anything, the fee regime and microstructure constrain what is theoretically possible.

Polymarket operates a hybrid-decentralized CLOB (Central Limit Order Book): matching is offchain, settlement is onchain (Polygon), and all orders are signed limit-order primitives — "market orders" are just marketable limit behavior (FAK/FOK). ([Overview - Polymarket Documentation][13], [docs.polymarket.com][22])

**Displayed price is not your fill.** The UI shows the midpoint of best bid and best ask, unless the spread exceeds $$\$0.10$$, in which case it shows last traded price. Buying happens at the ask; selling at the bid; depth determines your real fill. Any backtest using displayed price as fill price is invalid. ([Orderbook - Polymarket Documentation][20])

Outcome tokens redeem to $$\$1$$ or $$\$0$$ at resolution — all PnL is bounded binary payoff math plus execution frictions. ([docs.polymarket.com][21])

**Fee structure:** Polymarket uses a probability-based dynamic taker fee. The documented formula is:

$$
\text{fee} = C \times \text{feeRate} \times p \times (1-p)
$$

where $$C$$ is share count, $$p$$ is share price, and feeRate for crypto markets is **0.072** (post Fee Structure V2, March 30, 2026). Peak effective taker fee is **1.80%** at $$p = 0.50$$. Makers pay **zero** fees and may receive rebates (20–25% of collected taker fees for crypto). ([docs.polymarket.com][18], [docs.polymarket.com][1], [Polymarket Fees Breakdown \[2026 Updated\]][19])

**Fee rates should never be hardcoded** — official docs explicitly state they can vary and must be fetched dynamically. ([docs.polymarket.com][1])

5-minute crypto markets launched February 12, 2026 with taker fees enabled, following the same fee curve as 15-minute markets. Starting March 6, 2026, taker fees extend to all crypto markets (1H, 4H, daily, weekly). ([docs.polymarket.com][18])

The computed fee table at relevant price points (post-V2):

| Share Price | Fee/Share | Effective % of Notional | Win Payout | Loss Cost | Break-Even True Prob | Edge Needed |
|:-----------:|:---------:|:-----------------------:|:----------:|:---------:|:--------------------:|:-----------:|
| $$0.50$$ | $$0.0180$$ | 3.60% | +$$0.4820$$ | −$$0.5180$$ | 51.8% | +1.80 pp |
| $$0.70$$ | $$0.0151$$ | 2.16% | +$$0.2849$$ | −$$0.7151$$ | 71.5% | +1.51 pp |
| $$0.80$$ | $$0.0115$$ | 1.44% | +$$0.1885$$ | −$$0.8115$$ | 81.2% | +1.15 pp |
| $$0.85$$ | $$0.0092$$ | 1.08% | +$$0.1408$$ | −$$0.8592$$ | 85.9% | +0.92 pp |
| $$0.90$$ | $$0.0065$$ | 0.72% | +$$0.0935$$ | −$$0.9065$$ | 90.6% | +0.65 pp |
| $$0.95$$ | $$0.0034$$ | 0.36% | +$$0.0466$$ | −$$0.9534$$ | 95.3% | +0.34 pp |

**Bottom line:** At every price level, you need a positive calibration edge over the market price just to break even against taker fees. There is no free lunch at any price.

**Additional structural facts:**
- 5-minute markets draw up to $60M daily volume; bots account for 55–62% of volume. ([Polymarket Fast Markets Hit $2.3B Volume as Bots Dominate 5-Minute Crypto Bets][16], [Polymarket's 5-Minute Bitcoin Bets Draw Up to $60 Million Daily][17])
- Polymarket introduced dynamic fees specifically to curb latency arbitrage. ([financemagnates.com][27])
- Gas fees on Polygon are typically under $$\$0.01$$ per transaction.
- Documented retail bot slippage can reach 6+ cents per trade in thin markets. ([reddit.com][2])
- GTD order expiration has a one-minute security threshold — you cannot rely on auto-expiry for last-second protection. ([Overview - Polymarket Documentation][13])
- Trade lifecycle includes `MATCHED`, `MINED`, `CONFIRMED`, `RETRYING`, and `FAILED` states. ([Overview - Polymarket Documentation][13])
- Historical price endpoints are aggregated by interval/fidelity; for 5m/15m markets, you need your own recorded tick-by-tick book/trade stream. ([docs.polymarket.com][14])

---

## STRATEGY 1: Copy-Trading / Shadowing a Top Wallet

### Core Thesis

Someone else has solved the hard problem — building a model, getting fast data, calibrating probabilities. You find them by screening wallet PnL histories on the public blockchain, then mirror their trades with proportional sizing.

### Why It Might Work in Prediction Markets

On-chain transparency is the structural reason this idea even exists. Every trade by every wallet is observable on Polygon. If a target wallet genuinely has persistent edge from a superior model or faster data feed, and that edge exceeds your execution degradation, copying can theoretically extract a fraction of their alpha.

Public market data, onchain data, and subgraphs make wallet behavior study possible — rarer in traditional venues. ([docs.polymarket.com][15])

### Main Failure Modes

**1. Latency Decay (likely fatal).** Total latency from on-chain event detection to your confirmed trade: typically 4–14 seconds under normal Polygon conditions; minimum realistic round-trip for retail infrastructure is 5–8 seconds, with 10–30 seconds being common. ([How Latency Impacts Polymarket Bot Performance (And How to Reduce It) | QuantVPS][11]) In a 5-minute contract (300 seconds), 10–30 seconds is 3–10% of the contract's entire life. By the time you detect the trade, the order book has already absorbed the information. You enter at a strictly worse price.

**2. Survivorship Bias in Target Selection (severe).** You select wallets by screening past PnL. But past PnL is a mixture of skill and luck. With thousands of active wallets, some will have impressive records purely by chance. The strongest-looking wallets are the most likely to revert. Academic evidence from social trading platforms finds that peer-performance chasing increases activity while reducing returns and increasing volatility. ([Losing by learning? A study of social trading platform - ScienceDirect][9])

**3. Maker vs. Taker Asymmetry.** If the target places limit orders (maker), they pay zero fees and earn rebates. You, reacting to their trade, are almost certainly a taker. You pay 0.65–1.80% per trade that the target does not. Your net PnL is structurally worse than theirs even with zero latency.

**4. Unobservable Intent.** A "top wallet" trade may be part of a wider portfolio hedge, maker inventory adjustment, or cross-market book management — not a standalone directional bet. You cannot see their full context.

**5. Crowding.** Multiple copy-trading platforms now exist. ([Building a Polymarket Copy Trading Bot | Quicknode Guides][12]) More bots chase the same edge → spreads tighten → latency becomes decisive → opportunity shrinks or disappears. When several copiers pile into the same wallet, they collectively move the book against each other.

**6. Target Adapts or Goes Dormant.** The wallet you've validated may change strategies, move to different markets, or stop trading entirely.

**7. Observation Delay.** Matching is offchain and settlement is onchain. If you infer leader behavior from onchain activity or indexed subgraphs, you are observing after the economically useful moment. ([docs.polymarket.com][22])

### How Latency Affects It

**Extreme sensitivity.** Even 50ms additional latency can make profitable trades unviable for high-frequency strategies. At 4–14 seconds of copy delay, you are not competing — you are picking up scraps. If the target's edge is 2% and the price moves 1.5% in the seconds after their trade, you capture 0.5% gross, minus your taker fee. That's negative. ([newyorkcityservers.com][25], [Running Polymarket Bots on a VPS: Why Low Latency Matters][26])

For 15-minute contracts, latency matters less proportionally (30s / 900s = 3.3% vs 30s / 300s = 10%), so **if you build this, it should only be tested on 15-minute contracts.**

### How Fees and Slippage Affect It

**Devastating.** You pay full taker fees on every copy trade. The target may pay zero (maker). Combined with slippage from delayed execution (documented at 6+ cents per trade for retail bots in thin markets), you need the target's raw alpha to exceed ~3–4% per trade just to break even. ([reddit.com][2])

### Robust for Automation?

**No, not as blind auto-copying.** Technically simple (WebSocket monitoring → order submission). Operationally fragile — the bot works, but the edge doesn't. At best, wallet activity is a **research feature** or a **shadow signal**, not a standalone execution strategy.

### Recommended Mode

**Shadow mode / research only.** Shadow the target for 500+ trades. Simulate fills with realistic latency and fee models. If shadow P&L is negative, kill the idea before risking capital.

### Data Required

- Full on-chain Polygon transaction history for candidate wallets (minimum 6 months)
- Polymarket CLOB order book snapshots at 1-second granularity for entry price reconstruction
- Underlying spot prices (Pyth/Chainlink) synchronized to block timestamps
- Your own detection latency logs from day 1 of shadow mode
- Per-contract win rate, stake, timing, and market conditions
- Exact timestamp of **when your system could first observe** the wallet action

### Metrics to Track

| Metric | Purpose |
|---|---|
| Target raw PnL | Does the target actually have alpha? |
| Your simulated PnL (with latency) | Does anything survive delay? |
| Entry price gap (target vs. your fill) | Measures adverse selection |
| Alpha decay curve per second of delay | How fast does the signal die? |
| Win rate, avg win/loss, Sharpe | Standard strategy quality |
| Target trade frequency | Is there enough volume to copy? |
| Copy slippage (bps vs. leader fill) | Execution quality |
| PnL concentration by wallet/episode | Skill vs. luck |

### Minimum Sample Size

At least **1,000 observed leader trades** across **60+ trading days** and multiple volatility regimes (trending up, trending down, ranging). At least **300 executable delayed-copy simulations per leader**. With positive lower 95% confidence bound on net expectancy after clustering by coin-day.

To detect a **3 pp edge** (true $$p = 0.53$$ vs null $$p = 0.50$$) at 80% power and 5% significance: **~1,716 trades.** At 20 live copy trades per day, this is **~86 trading days (~4 months).**

### What Would Make Me Reject It Entirely

- Target's alpha disappears when simulating even 3 seconds of delay
- Target's P&L is concentrated in <10 big wins (luck, not skill)
- Multiple other copy bots already trail this wallet
- You cannot achieve maker fills on any leg
- Target trades fewer than 20 times per week
- Edge exists only at midpoint or last-trade prices, not executable quotes
- Wallet activity cannot be observed early enough without privileged data
- Net expectancy ≤ 0 after conservative costs

---

## STRATEGY 2: Coin Spread / Relative-Value Across Markets

### Core Thesis

BTC-Up and ETH-Up contracts on the same 5-minute window are correlated because crypto moves together. When one coin's market is priced "too cheap" relative to its historical relationship with the other, buy the cheap side and sell the rich side. Profit when the spread mean-reverts, regardless of overall crypto direction.

### Why It Might Work in Prediction Markets

Prediction markets quote **separate binary books** for related underlyings. Because books are shallow and update asynchronously, temporary cross-market dislocations can occur even when spot relationships are tight. Academic work on cryptocurrencies documents intraday cross-predictability and lead-lag effects across coins. ([A seesaw effect in the cryptocurrency market: Understanding the return cross predictability of cryptocurrencies - ScienceDirect][7])

Additionally, different liquidity providers for different coins may not reprice all contracts simultaneously, creating brief windows of stale prices. Relative-value reduces dependence on absolute directional forecasting.

### Main Failure Modes

**1. Double Fees (likely fatal).** You need two legs: buy one contract, sell (or buy the opposite side of) another. Both are taker trades. At $$p \approx 0.50$$, each leg costs ~1.80%. Round-trip fee: ~3.60%. You need a spread divergence exceeding 3.60% just to break even. If the typical divergence is 2–5%, fees eat most or all of the edge.

**2. Legging Risk (severe).** You must fill both legs near-simultaneously. If leg 1 fills and leg 2 fails (order cancelled, book moved, gas spike), you are left with unhedged directional exposure — the opposite of what you wanted.

**3. Not True Arbitrage.** "BTC goes up" and "ETH goes up" are correlated, not identical events. Even with $$\rho = 0.8$$, there is a ~20% residual. In a 5-minute window, idiosyncratic coin-specific news can easily decorrelate them. Subtle rule/oracle/time differences between contracts add further basis risk.

**4. Thin Books on the Minor Leg.** BTC contracts are relatively liquid; SOL or DOGE is not. The minor leg will slip more, and the slip is always against you.

**5. Correlation Instability.** Crypto correlations are regime-dependent. They spike to ~0.95 during panic selloffs (destroying your hedge) and drop to ~0.3 during idiosyncratic moves (making the spread meaningless).

**6. Lead-Lag Is a Sub-Second Phenomenon.** The genuine price-discovery lead of BTC over altcoins operates on millisecond-to-low-second timescales. By the time a Polymarket contract reflects the BTC spot move and you can detect, parse, and respond, the altcoin market has already repriced.

**7. Hidden Beta Stacking.** You think you're market-neutral, but you're actually long crypto risk cluster. During a flash crash, all positions resolve against you simultaneously.

### Correlated Blowup Analysis

This risk deserves quantitative emphasis. With 5 positions at $$\rho = 0.85$$ (typical crypto correlation):

$$
P(\text{all 5 lose}) \approx 5.9\%
$$

compared to:

$$
P(\text{all 5 lose, independent}) = (0.15)^5 = 0.008\%
$$

That is approximately **780× higher catastrophic-loss probability** due to correlation. When BTC experiences a macro event — exchange hack, regulatory news, liquidation cascade — all positions resolve against you simultaneously. This is not diversification; it is concentrated exposure in a diversification costume.

### How Latency Affects It

**Extreme.** Simultaneous execution is the defining requirement. A 2-second gap between legs means the second leg fills at a different price than modeled. For a solo builder without colocated infrastructure and sub-second order execution, **this strategy is likely not feasible for 5-minute contracts.** For 15-minute contracts, the lead-lag window is somewhat wider but still very short.

### How Fees and Slippage Affect It

**Likely fatal for taker execution.** Two taker legs at 1.0–1.8% each gives 2.0–3.6% round-trip. If your median spread capture is 2%, you're structurally losing. The only escape is placing limit orders (maker, zero fees) on at least one leg — but then you sacrifice execution speed and risk partial fills.

### Robust for Automation?

**Highest complexity of the three.** Requires real-time cross-market spread calculation, simultaneous order management, inventory tracking, correlation estimation, regime detection, and failure-mode handling for partial fills. A solo builder will spend weeks on infrastructure before generating a single signal.

> **Confidence note:** Models disagree on whether this strategy is the safest to test first. Several models (GPT-5.3, GPT-5.4, Gemma, Mistral) favor Strategy 2 in shadow mode as safest because it reduces directional beta. Other models (Claude Opus, Claude Sonnet, Grok) favor Strategy 3 as safest because it's simpler. The disagreement is ~50/50 across models. My synthesis: Strategy 2 is theoretically safer *if you can solve execution*, but Strategy 3 is practically safer *because it's simpler to validate and reject*.

### Recommended Mode

**Research first, then shadow.** You need to prove the spread exists, persists after double fees, and can realistically be captured before building anything.

**Important reframing from GPT-5.4:** If you build this, consider building it as a **directional signal extraction tool** (not as a spread trade): "BTC has moved Y standard deviations from open → buy ETH-direction contract if ETH contract price implies a lower probability than BTC spot move suggests." This eliminates the two-leg execution problem while retaining the signal. ([docs.polymarket.com][22])

### Data Required

- Synchronized L2 order books for both legs at sub-second resolution
- Trade prints + timestamps for both legs
- External underlying spot/reference prices (Pyth, Chainlink)
- Contract rule metadata (end time, oracle, resolution logic)
- Fill simulator with partial fills, queue decay, cancel latency
- Historical cross-coin correlation matrices by market regime
- Dynamic fee rates per market

### Metrics to Track

| Metric | Purpose |
|---|---|
| Spread mean, σ, half-life | Is the spread real and does it revert? |
| Both-leg simultaneous fill rate | Can you actually execute? |
| Legging-loss frequency | Unmatched inventory risk |
| Net P&L after double fees | Does anything survive? |
| Residual directional beta | Are you secretly just long crypto? |
| Max unhedged exposure from partial fills | Worst-case directional risk |
| Correlation stability (rolling 1-week) | Does the model break during regime shifts? |
| Slippage vs. book-predicted fill per leg | Execution quality |

### Minimum Sample Size

At least **500–1,000 completed paired trades**, across at least 2–3 volatility regimes. Partial-fill trades must be included (they're part of reality). At least 200 observations per coin pair. At least **100 live or latency-injected paper trades**. At 10 complete spread trades per day: **~96 trading days minimum.**

### What Would Make Me Reject It Entirely

- Double fees exceed median spread capture
- Legging loss dominates gross convergence alpha
- Correlation between target coins drops below 0.5 on 5-min horizons
- Partial fills occur >30% of the time
- Spread half-life exceeds 80% of contract duration
- Results require constant retuning of pair relationships
- Residual directional beta is large (strategy is secretly just outright direction)
- Order book depth on altcoin contracts consistently under $$\$200$$ top-of-book
- Net edge vanishes after two-sided costs

---

## STRATEGY 3: Buying High-Probability Contracts (0.80–0.90)

### Core Thesis

Systematically buy contracts priced at 0.80–0.90. Win most of the time, collecting the 10–20 cent spread to resolution at $$\$1.00$$. Accept an asymmetric payoff (small frequent wins, rare large losses) and profit from any systematic underpricing of favorites.

### Why It Might Work in Prediction Markets

The well-documented favorite-longshot bias describes the empirical regularity that long shots are overbet while favorites are underbet. ([NBER WORKING PAPER SERIES EXPLAINING THE FAVORITE-LONGSHOT BIAS:][23], [Favourite-longshot bias - Wikipedia][24]) In crypto direction markets, this could manifest as the "Down" side being overpriced when BTC is trending upward, leaving the "Up" side slightly underpriced.

Prediction-market prices map naturally to probabilities, and academic work suggests prices often aggregate beliefs fairly well, but mispricing near the extremes can occur. ([Microsoft Word - Interpreting Prediction Market Prices as Probabilities _JPubE submission_.doc][4])

Additionally, the fee structure itself creates an asymmetry: fees are lowest at the extremes. At $$p = 0.90$$, the effective fee rate is just 0.72%, compared to 3.60% at $$p = 0.50$$. The fee hurdle is lowest precisely where this strategy operates.

### Main Failure Modes

**1. No Calibration Edge (the null hypothesis).** If the market price of 0.85 reflects a true probability of exactly 85%, your expected value is:

$$
\text{EV} = 0.85 \times 0.1408 - 0.15 \times 0.8592 = 0.1197 - 0.1289 = -0.0092
$$

That's −0.92 cents per share. **Without a genuine calibration edge over the market, this strategy is strictly negative EV after fees.** The fee is the house edge.

**2. Convex Loss Structure (the steamroller).** At $$p = 0.85$$: you lose **6.1×** what you win on each trade. At $$p = 0.90$$: **9.7×**. One loss wipes out 6–10 wins. A small miscalibration (true prob = 83% instead of 85%) turns a "winning" strategy into a slow bleed.

**3. Correlated Multi-Position Losses (the kill shot).** If you simultaneously hold BTC-Up at 0.85, ETH-Up at 0.87, and SOL-Up at 0.82, and a market-wide crash occurs, **all positions lose at once.** Under independent assumptions, the probability of all 5 positions losing is ~0.008%. Under realistic crypto correlation ($$\rho \approx 0.85$$), it approximates **~5.9%** — not a tail event but a semi-regular operational reality.

**4. Last-Second Oracle Risk.** ~15–20% of 5-minute windows involve significant price action in the final 10 seconds. A contract at 0.88 can move to 0.15 in seconds due to a sudden reversal. This risk cannot be backtested accurately without genuine last-second tick data.

**5. Adverse Selection from the Sell Side.** Who is selling you contracts at 0.85? In an efficient market: participants who have information that the probability is lower. Market makers maintaining these prices may be selling precisely because they have tighter latency-sensitive pricing signals.

**6. Overtrading.** A high win rate creates behavioral overconfidence. You keep adding positions because "it always works." This stacks exposure and accelerates the correlated blowup when it comes.

### How Latency Affects It

**Low-to-moderate sensitivity compared to the other two strategies.** You're not racing anyone for fills. You can place limit orders (maker, zero fees) early in the contract's life and wait for a fill. The exception: if you try to enter late when the outcome appears nearly certain, the book will be thin and you'll pay large spreads. If conditions deteriorate in the 4th minute, you may want to exit, but thin books mean your exit price is far below entry.

### How Fees and Slippage Affect It

**Significant but manageable — IF you have edge.** At $$p = 0.85$$, the breakeven true probability is 85.9%. You need to be better calibrated than the market by +0.92 pp. At $$p = 0.90$$, breakeven is 90.6% (need +0.65 pp edge). These are not impossible hurdles, but they're not trivial either.

**Critical insight:** If you can place **maker orders** instead of taker, your fee is **zero** (and you may earn rebates). This eliminates the fee hurdle entirely and makes any positive calibration edge exploitable. The trade-off: maker orders may not fill, especially if the market moves away from your price.

On a 5m or 15m horizon with tiny per-trade margins, slippage of even 1–2¢ on a 14¢ potential profit is 7–14% additional degradation.

### Robust for Automation?

**Simplest of the three.** Logic: monitor market → check if price is in target range → check correlation exposure cap → place order → track resolution. No cross-market coordination, no target wallet dependency, no simultaneous multi-leg execution.

However, the automation logic must enforce strict rules on correlated exposure limits, time-in-window restrictions, and exit-on-deterioration logic.

### Recommended Mode

**Shadow mode first, then micro-live.**
- Shadow 500+ qualifying contracts over 4–8 weeks
- Log every "would-have-entered" trade with timestamp, price, and resolution
- Compute observed win rate vs. market-implied probability
- Only go live if observed edge exceeds breakeven by ≥ 2× the standard error

### Data Required

- Per-contract price time series at 1-second resolution, aligned to window open/close
- Full order book depth (bid/ask/size) at entry time — **midpoint is not sufficient**
- Underlying reference-price path at sub-second resolution (Pyth/Chainlink)
- Time-to-expiry field for all open positions
- Last-30-seconds price data per window (this is the key data most builders lack)
- Volatility regime label for each window
- Historical resolution outcomes with timestamps
- Dynamic fee schedule per market ([docs.polymarket.com][1])

### Metrics to Track

| Metric | Purpose |
|---|---|
| Calibration: win rate vs. market price | Is there actually a favorite-longshot bias? |
| Net P&L per trade after fees | Edge after costs |
| Profit factor (gross wins / gross losses) | Must exceed 1.0 |
| Max consecutive losses | Tail risk indicator |
| Loss correlation across simultaneous positions | Correlated blowup risk |
| Max drawdown (realized and simulated) | Survival check |
| Quarter-Kelly bankroll fraction at risk | Sizing discipline |
| Avg slippage vs. midpoint | Execution quality |
| P&L attribution: last-30s reversals | Quantified tail risk contribution |
| Win rate by entry price band (0.80–0.85, 0.85–0.90) | Bucket-level calibration |
| Win rate by time-in-window | Does edge vary with timing? |

### Minimum Sample Size

To detect a **1.5 pp edge** (true $$p = 0.874$$ vs break-even $$p = 0.859$$) at 80% power: **~3,310 trades.** At 20 trades per day: **~166 trading days (~5.5 months).**

To detect a **2 pp edge** at 95% confidence:

| Entry Price | Min n (95% CI) | Expected Losses | Calendar Est. |
|:-----------:|:--------------:|:---------------:|:-------------:|
| 0.80 | ~1,537 | ~307 | 4–8 weeks |
| 0.85 | ~1,225 | ~184 | 3–6 weeks |
| 0.90 | ~865 | ~87 | 2–4 weeks |

**Do not trust any result with fewer than 50–100 observed losses.** A strategy claiming 90% win rate with only 10 losses is not validated — it's untested. Because per-trade edge is small and the payoff distribution is highly skewed, a massive sample is required to observe the true frequency of catastrophic tail events.

### What Would Make Me Reject It Entirely

- Observed win rate at $$p = 0.85$$ is ≤ 85.9% over 1,000+ trades (no edge after fees)
- Loss correlation across coins exceeds 0.5 (correlated blowup is likely)
- Max drawdown exceeds 3× the daily variance expectation
- Kelly fraction is so small (<0.5%) that realistic position sizes cannot cover minimum order sizes
- No time-of-day, volatility regime, or coin filter improves calibration
- Shadow P&L is negative after 200 trades even before fee simulation
- More than 2 instances of "late reversal" (contract at 0.85+ reverting below 0.50 in final 60 seconds) per 100 trades
- Most profit disappears when using ask price instead of midpoint
- Net calibration ≤ 0 in two independent out-of-sample periods

---

## Comparative Analysis

| Criterion | 1: Copy-Trade | 2: Coin Spread | 3: High-Prob |
|:--|:--:|:--:|:--:|
| **Expected Edge Durability** | 🔴 Low | 🟡 Low–Medium | 🟡 Low–Medium |
| **Implementation Complexity** | 🟡 Medium | 🔴 High | 🟢 Low |
| **Operational Risk** | 🔴 High | 🔴 High | 🟡 Medium |
| **Sensitivity to Delay** | 🔴 Extreme | 🔴 Very High | 🟢 Low–Medium |
| **Sensitivity to Liquidity** | 🔴 High | 🔴 Very High | 🟡 Medium |
| **Risk of Correlated Blowups** | 🟡 Medium | 🔴 Very High (if multi-leg) | 🔴 High (if stacked unsized) |
| **Suitability for Solo Retail** | 🔴 Low | 🔴 Low–Medium | 🟢 Medium |
| **Backtest Fakability** | 🔴 Very High | 🟡 Medium–High | 🔴 Very High |

### Expected Edge Durability

**Copy-Trading:** Edges decay as copy-bots proliferate. Wallet alpha is typically regime-specific and exhausted within weeks of discovery. Estimated half-life: 2–4 weeks post-selection.

**RV Spread:** If structural relationships persist, the underlying mispricing mechanism is more durable than behavioral copying. But double fees remain a permanent drag, and any persistent sub-second lead-lag opportunity will be competed away by colocated actors. Estimated half-life: 1–3 months, but possibly never reachable by retail.

**High-Prob:** The structural miscalibration (if it exists) depends on persistent market-maker behavior and retail psychology rather than another trader's secret edge. The shallowest source of edge but potentially the most stable. Estimated half-life: 3–6 months, conditional on the calibration anomaly existing at all.

### Implementation Complexity

- **Copy-Trading:** Requires Polygon node or high-frequency API, on-chain transaction parsing, CLOB order mapping, wallet watchlist. ~400–600 hours of engineering.
- **RV Spread:** Synchronized multi-market data feeds, implied fair value model, multi-leg execution, correlation regime detection. ~600–1,000 hours.
- **High-Prob:** CLOB price monitoring for one contract at a time, fee calculation, exposure limits. **~100–200 hours for a functional v1.**

### Sensitivity to Delay

Copy-Trading and RV Spread are both **fatally sensitive for 5-minute contracts.** A 15–30 second lag converts any theoretical edge into a guaranteed negative. High-Prob is the only strategy where a 15–30 second monitoring lag does not immediately destroy the edge.

### Risk of Correlated Blowups

The RV Spread strategy has the worst catastrophic downside if it encourages holding 3–5 correlated positions simultaneously. With $$\rho = 0.85$$, $$P(\text{all 5 lose}) \approx 5.9\%$$ per window — not a tail event, a **semi-regular operational reality.**

Strategy 3 has similar correlated blowup risk **if unsized** — but it is the easiest to cap with strict position limits.

---

## Proposals

### Safest One to Test First

**Strategy 3 (High-Prob Contracts), on 15-minute contracts only, one coin (BTC), with maker-only entry.**

> **Model disagreement note:** ~50% of models favor Strategy 2 (RV Spread) in shadow mode as "safest" because it reduces directional beta. The other ~50% favor Strategy 3 because it's simpler to implement, validate, and reject. My synthesis: Strategy 3 is the safer **practical** choice for a solo retail builder because it requires less infrastructure, produces interpretable/attributable P&L, and its failure modes are the most clearly identifiable. Strategy 2 is theoretically safer *if* you can solve execution, but that "if" is doing enormous load-bearing work.

**Why Strategy 3:**
- Simplest to implement correctly
- Clearest rejection criteria
- Lowest infrastructure cost
- Generates data within 1–2 weeks
- Produces a statistically meaningful answer within 6–8 weeks
- Even if it fails, you learn what calibration edges look like in this market
- A failed shadow test tells you something actionable

### Highest Upside

**Strategy 2 (Coin Spread / Relative Value)** — if and only if you solve execution and maintain true neutrality. Structural relationships may be more durable than pure directional or copy alpha.

**Important reframing:** Build it as a **BTC-signal-to-ETH-entry** single-leg directional trade, not a two-leg spread. This eliminates the "correlation spread" delusion while retaining the actual signal.

### Easiest to Fake-Good in Backtests But Fail Live

**Strategy 3 (High-Prob Contracts)**, by a large margin. Runner-up: **Strategy 1 (Copy-Trading)**.

**Why Strategy 3 fakes well:**
- Backtests show ~85%+ win rate and positive P&L on historical data
- No slippage modeled (you assume midpoint fills)
- No fee modeling or simplified flat fee
- No last-second reversal data (missing from most datasets)
- No order book depth check (assumed unlimited fills)
- No correlation between positions (each trade treated as independent)
- Look-ahead bias in regime selection

**Why Strategy 1 fakes well:**
- You screen 10,000 wallets, find the top 10 by PnL, backtest copying them — spectacular results because you selected for the outcome
- Historical leader fills are not your fills
- Cherry-picked wallets and periods

**Rule:** Never trust a backtest of Strategy 3 unless it was built on **tick-level data** with explicit order book depth checks, the **exact dynamic fee formula**, and last-second reversal modeling. Never trust a backtest of Strategy 1 unless the wallet selection was done **prospectively** (out-of-sample).

### Most Realistic Staged Rollout Plan

| Phase | Duration | Activity | Go/No-Go Gate |
|:------|:---------|:---------|:--------------|
| **Phase 0: Data & Infrastructure** | 2–4 weeks | Record live L2 books, trades, fees, timestamps for BTC/ETH/SOL 15m contracts. Build fee-accurate tick-level simulation engine. Validate clock sync and websocket gap handling. | Sufficient data volume? Clean data? APIs stable? Latency benchmarks acceptable? |
| **Phase 1: Research — Strategy 3** | 6–8 weeks | Run High-Prob strategy over historical data using simulation engine. Stratify by entry price band, time-in-window, coin, volatility regime. Investigate last-second reversal rate. | Historical net P&L positive after fees and slippage in ≥3 of 4 distinct calendar quarters? |
| **Phase 2: Shadow — Strategy 3** | 6–8 weeks | Paper-trade every qualifying entry (0.80–0.90), no real money. Use live bid/ask (not mid) for fill simulation. Track 50-trade rolling win rate. Track correlated loss events. | 200+ shadow trades with positive P&L after fees? Rolling-50 win rate above break-even in ≥8 of 10 windows? Loss correlation <0.4? |
| **Phase 3: Micro-Live — Strategy 3** | 4–8 weeks | Trade at 1/10 Kelly, max 1 position per coin, max 2 coins. $$\$5$$–$$\$10$$ per trade. BTC-15min only first. Maker orders only. | Net P&L positive after fees? Live P&L matches shadow within 20%? Max drawdown within tolerance? No systematic fill quality degradation? |
| **Phase 4: Scale — Strategy 3** | Ongoing | Increase to quarter-Kelly. Add coin/time filters. Expand to ETH. | Sustained Sharpe >0.5 over 200+ live trades? |
| **Phase 5: Explore — Strategy 2** | 8+ weeks | Only if Phase 4 profitable. Research spread persistence. Paper-trade BTC-signal variant as single-leg directional. | Spread > 2× double fees? Signal lead time >3s and measurable? |

**Strategy 1 is not recommended for any live phase.** The latency penalty in 5-minute markets makes it structurally nonviable for a solo retail builder without colocated infrastructure. Keep it as a **research feature** only — wallet activity as one input to a broader model.

---

## Design Rules for a Production Bot

These rules assume you are running **Strategy 3** (high-probability contracts) on Polymarket 15m crypto direction markets. They are designed to prevent the specific failure modes identified above. **Treat violations as system defects requiring immediate remediation, not judgment calls to override manually.**

---

### Rule 1: When to Enter

Enter a position **only if ALL of the following are true:**

1. **Price threshold:** Contract price is in $$[0.78, 0.92]$$. Below 0.78, the loss-to-win ratio may favor longshots. Above 0.92, the profit margin per win is too thin to absorb any miscalibration.

2. **Fee-adjusted EV positive:** Your model's estimated true probability exceeds the break-even probability (market price + fee drag) by at least **1.5 pp**. If you cannot estimate true probability independently, you should not be trading.

3. **Minimum remaining time:** Do not enter a 5-minute contract with <90 seconds remaining, or a 15-minute contract with <4 minutes remaining. Late entries face thin books, wide spreads, and oracle uncertainty.

4. **Order type preference:** Always attempt a **limit order (maker)** first. Only fall back to taker (market/FOK) if the maker order has been resting for ≥15 seconds without fill and the opportunity is still valid. Zero-fee maker fills dramatically improve expected value.

5. **Executable liquidity exists:** Top-of-book ask depth is at least **5×** your intended size within 2 pp of the current ask. ([Orderbook - Polymarket Documentation][20])

6. **Correlated exposure check:** You have **zero or one** other open position in the same BTC-correlated group (see Rule 4).

7. **No stale data:** Market websocket is healthy, no recent sequence gaps, clock skew below internal threshold.

---

### Rule 2: When NOT to Enter

**Never enter under any of the following conditions, regardless of signal strength:**

1. **Late in window:** Within the final 25% of the contract window (final 75s for 5-min; final 225s for 15-min). **Non-negotiable.** Last-second reversals are the single largest unmodeled risk.

2. **High-volatility filter:** Within 90 seconds of any external volatility shock (>0.5% BTC move in under 60 seconds on spot markets) or if the underlying coin has moved >1.5% in the last 5 minutes.

3. **Thin order book:** Top-of-book ask depth under $$\$100$$–$$\$150$$ for the target contract, or bid-ask spread exceeds 5 cents (or >1.5× its 1-hour rolling average).

4. **Daily/weekly loss limit hit.** See Rule 3.

5. **Max correlated exposure already reached.** See Rule 4.

6. **Back-to-back losses:** After 3 consecutive losing trades, pause for 2 full windows before the next entry.

7. **During open position:** Never enter a new position while a position in the same coin is already open.

8. **API/data latency degraded:** If your data feed has been delayed by >5 seconds in the last 60 seconds, skip the window entirely.

9. **Post-shock macro events:** Disable trading 5 minutes before and after major macro releases (FOMC, CPI, NFP) or scheduled network upgrades.

10. **Rapid price decay:** Do not enter if the contract price has dropped from 0.90→0.80 in under 10 seconds (indicates reversal, not consolidation).

---

### Rule 3: Position Sizing

Use **worst-case loss**, not expected win rate:

$$
\text{Position} = \min\left(\frac{1}{4} \times f_{\text{Kelly}} \times \text{Bankroll},\;\text{MaxPositionUSD}\right)
$$

Where:

$$
f_{\text{Kelly}} = \hat{p} - \frac{1 - \hat{p}}{b}, \quad b = \frac{\text{net win per share}}{\text{net loss per share}} = \frac{(1-p) - \text{fee}}{p + \text{fee}}
$$

- Use **quarter-Kelly** (divide Kelly fraction by 4). Full Kelly is suicidal with estimated probabilities.
- **Hard cap:** No single trade may exceed **0.25% of NAV** in worst-case loss, or an absolute dollar cap (start at $$\$10$$, graduate to $$\$25$$, then $$\$50$$ only after 200+ validated live trades).
- **Daily loss limit:** Stop all trading after losing **1.0% of NAV** in a single calendar day.
- **Weekly loss limit:** If week-to-date losses exceed **2.0% of NAV**, halt all trading and review.
- **Never use fixed dollar sizing** without a bankroll fraction cap. As bankroll shrinks, fixed sizing exponentially increases risk of ruin.

---

### Rule 4: Max Correlated Exposure

**At any point in time, total capital at risk across correlated assets must not exceed 1.5% of NAV.**

Define correlation groups based on BTC beta:
- **Group A (BTC-dominant, β > 0.80):** BTC, ETH, SOL, BNB, AVAX — these move together in crashes
- **Group B (lower beta):** Altcoins with partial BTC correlation
- **Group C (low beta):** Truly idiosyncratic (rare in Polymarket crypto)

**Hard rule:** Maximum **1–2 open positions in Group A at any time.** Period. The correlated blowup analysis shows holding 5 Group-A positions simultaneously raises $$P(\text{all lose})$$ to ~5.9% — unacceptable.

**Aggregate exposure of all correlated directional trades must not exceed 3% of total bankroll.**

**Cross-window exposure:** Positions in non-overlapping time windows (e.g., the 10:00 contract and the 10:15 contract) may be treated as independent, **unless** a macro event spans both windows.

If correlation spikes intraday, shrink caps automatically.

---

### Rule 5: Multiple Entries on the Same Coin

**Default: NO.** One open position per coin per contract period. No averaging down. No pyramiding.

- If BTC-Up at 0.85 has moved to 0.80, adding more does not "improve" your entry — it doubles your exposure to the same binary outcome.
- Across consecutive contracts: Allow re-entry on the same coin in the next contract period only if the previous contract resolved and the new contract independently meets all entry criteria.
- **Maximum 4 consecutive entries on the same coin in the same direction.** After 4 consecutive wins in one direction, require a skip of at least 1 contract.
- If you later relax this: allow at most **one add-on**, only if it improves average price, only if total coin exposure stays within original trade-risk cap, and only after a cooldown.

---

### Rule 6: When to Disable a Coin Entirely

**Automatic disable** if any of the following occur:

1. **Consecutive loss trigger:** 4–5 consecutive losses on that coin's contracts — disable for 24–48 hours and review.

2. **Calibration drift:** Rolling 20–100 trade win rate falls below the breakeven probability by more than 2 pp — disable until investigation is complete.

3. **Liquidity collapse:** Average bid-ask spread exceeds 8 cents over a 1-hour window, or top-of-book depth falls below $$\$100$$ for >30 minutes.

4. **Regime change:** Underlying coin's spot price shows a move >3% in any 5-minute window in the last 24 hours (volatility regime shift indicator). Disable for 12–24 hours.

5. **Realized slippage exceeds modeled slippage** by >50% over 10+ trades.

6. **Oracle/resolution anomaly:** Any contract on that coin resolved unexpectedly or was disputed.

7. **Platform issues:** Matching engine restart, API degradation, or order-status inconsistencies → disable all coins immediately until confirmed resolved. ([docs.polymarket.com][18])

**Re-enable criteria:** Coin can be re-enabled after 48 hours of observation **and** after confirming win rate returns to above break-even in shadow mode for 20+ windows. Requires explicit human review.

---

### Rule 7: Monitoring and Circuit Breakers

- **Data freshness:** If market price has not updated in 10+ seconds, assume data feed failure — do not trade.
- **Execution confirmation:** If order submitted and not confirmed within 8 seconds, treat as failed. Do not submit a second order without confirming the first is genuinely unconfirmed. ([Overview - Polymarket Documentation][13])
- **Position reconciliation:** End of every window, reconcile your position log against on-chain state. Any discrepancy of >$$\$5$$ halts trading until resolved manually.
- **Fee discrepancy alert:** If realized fees differ from modeled fees by >20% on average over 10 trades, halt and re-verify the fee formula implementation.
- **Request throttling detection:** Official docs note throttling delays requests rather than rejecting — deadly for short-horizon bots. Monitor and alert. ([Orderbook - Polymarket Documentation][20])

---

### Rule 8: Logging and Audit

Every single decision (enter, skip, exit, disable) must be logged with:
- Timestamp (ms precision)
- Contract ID, coin, direction, time window
- Market price at decision time
- Model's estimated true probability
- Orderbook top-of-book bid/ask/depth at decision time
- Fee calculated
- Position size and rationale
- Fill price and fill latency (if entered)
- Trade status lifecycle (MATCHED → CONFIRMED or FAILED)
- Resolution outcome (once known)
- All concurrent open positions (for correlation audit)

**Without this log, you cannot distinguish skill from luck, and you cannot debug failure modes.** This is not optional infrastructure — it is the strategy.

---

## Final Warning

The single most dangerous belief in short-horizon prediction market trading is:

> *"I win 85% of the time, therefore I have edge."*

An 85% win rate at $$p = 0.85$$ with zero calibration edge produces **negative expected value after fees.** The fee is the rake, and the rake always wins over a sufficient number of hands. The *only* way to profit is to be **provably better-calibrated** than the market price, after accounting for fees, slippage, latency, and correlated exposure.

If your shadow-mode data does not show this edge at statistical significance, the correct action is to not trade. The market is not obligated to give you an edge just because you built a bot.

> **In these markets, treat execution as the strategy.** Signal quality is secondary; cost, latency, and exposure discipline decide survival.

[1]: https://docs.polymarket.com/trading/fees
[2]: https://www.reddit.com/r/polymarket_bets/comments/1sf1t5j/built_a_profitable_polymarket_bot_but_slippage_is/
[3]: https://medium.com/@benjamin.bigdev/unlocking-edges-in-polymarkets-5-minute-crypto-markets-last-second-dynamics-bot-strategies-and-db8efcb5c196 "Unlocking Edges in Polymarket’s 5-Minute Crypto Markets: Last-Second Dynamics, Bot Strategies, and Profitable Trading | by Benjamin-Cup | Feb, 2026 | Medium"
[4]: https://users.nber.org/~jwolfers/papers/InterpretingPredictionMarketPrices.pdf "Microsoft Word - Interpreting Prediction Market Prices as Probabilities _JPubE submission_.doc"
[5]: https://www.journals.uchicago.edu/doi/abs/10.1086/655844 "Explaining the Favorite–Long Shot Bias: Is it Risk-Love or Misperceptions? | Journal of Political Economy: Vol 118, No 4"
[6]: https://www.datawallet.com/crypto/top-polymarket-trading-strategies
[7]: https://www.sciencedirect.com/science/article/abs/pii/S0927539823000956 "A seesaw effect in the cryptocurrency market: Understanding the return cross predictability of cryptocurrencies - ScienceDirect"
[8]: https://www.financemagnates.com/trending/prediction-markets-are-turning-into-a-bot-playground/ "Prediction Markets Are Turning Into a Bot Playground"
[9]: https://www.sciencedirect.com/science/article/pii/S1544612318302629 "Losing by learning? A study of social trading platform - ScienceDirect"
[10]: https://medium.com/@0xmega/how-to-find-the-best-polymarket-wallets-to-copy-trade-without-getting-rekt-26dd65123324
[11]: https://www.quantvps.com/blog/how-latency-impacts-polymarket-trading-performance "How Latency Impacts Polymarket Bot Performance (And How to Reduce It) | QuantVPS"
[12]: https://www.quicknode.com/guides/defi/polymarket-copy-trading-bot "Building a Polymarket Copy Trading Bot | Quicknode Guides"
[13]: https://docs.polymarket.com/developers/CLOB/orders/orders "Overview - Polymarket Documentation"
[14]: https://docs.polymarket.com/api-reference/markets/get-prices-history
[15]: https://docs.polymarket.com/market-data/websocket/market-channel
[16]: https://blockchain.news/news/polymarket-fast-markets-volume-bots-fees-analysis "Polymarket Fast Markets Hit $2.3B Volume as Bots Dominate 5-Minute Crypto Bets"
[17]: https://finance.yahoo.com/news/polymarkets-5-minute-bitcoin-bets-123329673.html "Polymarket's 5-Minute Bitcoin Bets Draw Up to $60 Million Daily"
[18]: https://docs.polymarket.com/changelog
[19]: https://www.tradetheoutcome.com/polymarket-fees/ "Polymarket Fees Breakdown [2026 Updated]"
[20]: https://docs.polymarket.com/trading/orderbook "Orderbook - Polymarket Documentation"
[21]: https://docs.polymarket.com/concepts/positions-tokens
[22]: https://docs.polymarket.com/trading/overview
[23]: https://www.nber.org/system/files/working_papers/w15923/w15923.pdf "NBER WORKING PAPER SERIES EXPLAINING THE FAVORITE-LONGSHOT BIAS:"
[24]: https://en.wikipedia.org/wiki/Favourite-longshot_bias "Favourite-longshot bias - Wikipedia"
[25]: https://newyorkcityservers.com/blog/polymarket-server-location-latency-guide
[26]: https://www.quantvps.com/blog/running-polymarket-bots-on-vps "Running Polymarket Bots on a VPS: Why Low Latency Matters"
[27]: https://www.financemagnates.com/cryptocurrency/polymarket-introduces-dynamic-fees-to-curb-latency-arbitrage-in-short-term-crypto-markets/
