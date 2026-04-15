You are a quantitative researcher reviewing a copy-trading bot for prediction markets.



I want to evaluate whether copying a top trader or wallet can be a real edge, or whether it is mostly a delayed, crowded, low-quality signal.



Please analyze this idea as if you are trying to disprove it.



Research questions:

- What makes a trader appear “top” but not actually copyable?

- How much does delay destroy the edge?

- How do partial fills, thin liquidity, and front-running risk affect copy-trading?

- How can I distinguish genuine skill from luck, concentration, or hidden information?

- What portfolio metrics matter most: ROI, Sharpe-like stability, drawdown, hit rate, average hold time, concentration, market selection, liquidity footprint?

- What are the red flags that a wallet should never be copied?

- Is copying entries, exits, sizing, or just market selection the better approach?

- Should I copy one wallet, a basket of wallets, or only use wallets as a feature in a broader model?

- How would I backtest this honestly without lookahead bias?

- What would a safe shadow-mode rollout look like?



Also answer this specifically:

If a copied trader enters the same coin more than once, when is that intelligent scaling and when is it just noisy re-entry?



Output:

1. Thesis

2. Edge case for why it could work

3. Strongest argument for why it will fail

4. Required data

5. Backtest design

6. Live risks

7. Recommendation: build / shadow only / avoid

Here is a skeptical, quantitative teardown of the copy-trading strategy for short-horizon prediction markets.

1. Thesis
Copy-trading top prediction market wallets is an illusion of alpha. It is a highly fragile, structurally flawed strategy where theoretical edge is rapidly destroyed by execution latency, extreme survivorship bias, and the harsh realities of thin liquidity. What appears to be a reproducible signal is almost always just an uncopyable execution advantage or a statistical anomaly.

2. Edge Case for Why It Could Work
Strict, tick-for-tick copy-trading of a single individual is doomed because even the best traders experience performance drift. However, there is a marginal edge if you abandon precise entry/exit copying and instead use wallet tracking purely as a market selection feature. By building "wallet baskets" categorized by specific topics, you can detect unusual volume and track where informed capital is flowing before mainstream news breaks, using this as an input for a broader, independent trading model.

3. Strongest Argument for Why It Will Fail
The execution reality gap will mathematically bleed the account dry. Polymarket leaderboards are highly misleading; a top-ranked wallet might owe its entire PnL to a single massive gamble or merely 8 lucky trades, offering zero reproducible statistical edge. Furthermore, when a genuine top trader executes a large order, they instantly consume the best available liquidity in the thin order book. The follower's bot, arriving milliseconds later, is forced to cross a widened spread, absorbing severe negative slippage. Over time, you are consistently buying at a premium and selling at a discount compared to the leader.

4. Required Data
To properly evaluate this, you cannot rely on basic PnL leaderboards. You require:

Deep Wallet Histories: To filter out infrastructure wallets and automated market makers, which frequently appear as top directional traders but are actually just capturing spreads.

Tick-Level Order Book Snapshots: To calculate the exact depth and bid-ask spread at the millisecond the leader's trade was broadcast.

Latency Metrics: The precise time delay between the leader's on-chain/API execution and your platform's replication speed.

5. Backtest Design
Standard backtests are fundamentally deceptive for this strategy because they assume perfect fills at the leader's execution price, ignoring the fact that the leader already consumed that liquidity. An honest backtest must:

Apply a strict negative slippage penalty to every simulated trade to reflect the delay.

Exclude any wallet that has fewer than 100 trades or a win rate below 40%, as these are red flags indicating survivorship bias rather than systemic skill.

Ignore the first 1-2 cents of the order book depth in the simulation to account for the leader's market impact.

6. Live Risks

Slippage and Spread Widening: During fast-moving events, latency guarantees you will suffer the worst possible fills, turning the leader's winning trade into your losing trade.

Margin and Scaling Failures: If the leader abruptly adds to a position, the follower may fail to copy the trade due to insufficient margin or contract size minimums, resulting in an unhedged or disproportionately sized portfolio.

Malicious Traps: Attackers are aware of copy-bots and can execute bait-and-dump maneuvers, or even distribute malicious copy-trading repositories designed to steal private keys.

7. Recommendation: Avoid (with a caveat)
Avoid strict copy-trading entirely. It is a negative expected value trap. The only acceptable rollout is to use wallet tracking in shadow mode to generate signals for market selection, while executing your own independent pricing logic, sizing, and risk management parameters.

Intelligent Scaling vs. Noisy Re-entry
If a copied trader enters the same coin more than once, distinguishing between a sophisticated scale-in and dangerous noise requires tracking state and market context:

Intelligent Scaling: This occurs when the leader is systematically averaging into a position using predefined volume scaling and order deviation (e.g., adding to the position only when the price drops by a specific percentage to improve the average entry price). It is also intelligent if the secondary entry occurs when the bid-ask spread has demonstrably tightened, allowing the leader to absorb more size without excessive market impact.

Noisy Re-entry: This happens when a leader's algorithm produces "rapid-fire" updates or cancels/replaces orders at the exact same price level. If your bot lacks deterministic trade validation and state tracking, it will misinterpret these micro-adjustments as new directional signals, resulting in duplicate trades, severe overexposure, and wasted fees.

You are a skeptical market microstructure researcher.



I want to study a “coin spread” strategy for prediction markets. By coin spread, I mean exploiting relative mispricing across related crypto direction markets rather than predicting absolute direction perfectly.



Examples might include:

- BTC vs ETH direction disagreement

- SOL vs market basket divergence

- cross-coin relative momentum or mean reversion

- inconsistent pricing across similar short-horizon up/down contracts



Please explain what forms of relative-value or spread strategies are actually plausible in prediction markets.



I want:

- a taxonomy of spread strategies that could exist in short-duration crypto prediction markets

- which versions are most realistic for a retail bot

- which versions are fake-good in theory but impossible after fees and execution

- how to detect relative mispricing without overfitting

- how to hedge or partially hedge directional exposure

- how to measure correlation regime changes

- how to avoid blowing up from all “spread” trades failing together in a volatility event



Please include:

- concrete examples

- required data features

- entry and exit logic ideas

- failure modes

- latency sensitivity

- how to simulate live execution honestly

- whether multiple entries in one coin improve or worsen spread execution



At the end, rank the top 3 spread-style bot concepts from most promising to least promising for a small automated bot.

Here is a breakdown of spread and relative-value strategies in the context of short-horizon crypto prediction markets.

Taxonomy of Spread Strategies
In prediction markets, spread strategies typically fall into these categories:

Market Rebalancing Arbitrage (Intra-Market): Exploiting inefficiencies within a single market when the combined probability of exhaustive, mutually exclusive conditions strays from 1.00 (e.g., buying "Yes" and "No" for less than $1.00 total).

Combinatorial Arbitrage (Inter-Market): Trading mispricings across multiple related markets, such as overlapping price-range bands or correlated events.

Cross-Venue Arbitrage: Exploiting price discrepancies for the exact same event across different platforms (e.g., Polymarket vs. Kalshi).

Cross-Coin Relative Value (Pairs Trading): Exploiting divergences between highly correlated assets (e.g., BTC vs. ETH 5-minute directional contracts) under the assumption that their implied probabilities should move in tandem.

Volatility Arbitrage (Cross-Asset): Buying underpriced prediction market contracts during a volatility spike and simultaneously hedging the directional risk using centralized perpetual futures.

Realistic vs. Fake-Good Strategies
Fake-Good: Pure intra-market rebalancing and cross-venue arbitrage. While mathematical certainties in theory, these are impossible for retail bots to execute profitably. Spreads on these opportunities are generally tight (4 to 6 cents), and dynamic taker fees easily consume the margin. Furthermore, these are latency-dominated; HFT firms using WebSockets and Fill-or-Kill (FOK) orders will sweep the liquidity before your bot registers the signal.

Realistic for Retail: Cross-coin relative value (BTC vs. ETH) and volatility arbitrage. By trading statistical divergence (cointegration) over a 5-to-15-minute window rather than seeking risk-free instantaneous arbitrage, a retail bot avoids competing directly in the sub-millisecond latency war.

Detecting Mispricing Without Overfitting
To avoid overfitting, you must focus on cointegration rather than simple correlation. Correlation can break down rapidly during market crashes, whereas cointegration identifies a stable, long-term equilibrium relationship between two non-stationary asset prices. You can detect relative mispricing by calculating rolling Z-scores and applying spread-based Bollinger Bands to the differential between the two coins' implied probabilities.

Hedging Directional Exposure
To isolate the relative-value edge and hedge out the underlying crypto beta, you can use delta-hedging with perpetual futures. The theoretical delta of a European binary option with respect to the underlying spot price can be mathematically derived as Δ= 
σS 
t
​
  
T−t

​
 
e 
−r(T−t)
 N 
′
 (d 
2
​
 )
​
 . By computing this delta for a given prediction contract, your bot can take an offsetting linear position (shorting or longing) in a highly liquid perpetual futures market (like Binance) to neutralize directional risk.

Measuring Correlation Regime Changes
Cryptocurrency market dynamics are non-stationary. To measure regime changes, employ the Ljung-Box test to detect shifts in autocorrelation, which often accompany volatility clustering and regime shifts. Additionally, utilizing a rolling-window approach for your cointegration tests allows the system to continuously adapt to new correlation environments without relying on stale historical regimes.

Avoiding Correlated Blowups in Volatility
During a volatility event, historical correlations break, and all relative-value "spread" legs can move against you simultaneously. To survive:

Volatility Circuit Breakers: Program the bot to halt trading entirely if the underlying spot asset's standard deviation breaches a trailing historical threshold (e.g., the 95th percentile of the 24-hour rolling average).

Strict Value at Risk (VaR): Utilize VaR limits and correlation checks to cap maximum exposure across multiple running strategies, preventing overconcentration in one specific market direction.

Concrete Strategy Framework: The BTC/ETH Z-Score Spread
Data Requirements: Millisecond-synchronized WebSockets for Polymarket BTC and ETH order books, plus the Binance spot/perp feeds.

Entry Logic: Wait for the rolling Z-score of the BTC/ETH implied probability spread to exceed +2.0 or drop below -2.0. Ensure the bid-ask spread on both Polymarket order books is ≤ $0.03.

Exit Logic: Exit when the Z-score reverts to 0, or institute a hard time-based exit 60 seconds before contract resolution to avoid terminal oracle risk.

Failure Modes: The primary failure mode is a structural decoupling (e.g., a massive idiosyncratic news event targeting ETH) where the spread permanently diverges, resulting in sustained mark-to-market losses.

Latency Sensitivity: High, but manageable. While not requiring HFT speed, lagging by over a second means you cross widened spreads, absorbing slippage that destroys the mean-reversion profit.

Simulating Live Execution Honestly
A backtest is useless if it assumes independent price processes and perfect market order fills. To simulate accurately, you must model limit order book queue position, fill probabilities, and adverse selection. If your simulated limit order was filled exactly when the underlying spot price spiked, you must penalize the backtest by assuming an "adverse fill," meaning you caught the toxic flow of a faster informed trader right before a price drop.

Multiple Entries (Scaling)
Multiple entries on the same coin can improve execution if deployed systematically. Using dynamic volume scaling and order deviation (scaling in as the price drops) helps absorb liquidity smoothly and improves the average entry price. However, if the bot is merely executing noisy re-entries without widening the spread grid, it quickly leads to concentrated exposure and massive correlated losses.

Top 3 Bot Concepts Ranked (From Most to Least Promising)
Cross-Coin Relative Value (Cointegration): Most Promising. Trading the Z-score spread between BTC and ETH 15m directional markets. It relies on mean reversion and statistical relationships, removing the need for sub-millisecond execution and allowing a well-coded retail bot to compete effectively.

Delta-Hedged Volatility Arbitrage: Moderate Promise. Buying heavily discounted prediction contracts during irrational panic dips and instantly hedging the directional risk via Binance perpetual futures. The structural edge is real, but managing the cross-venue API risk and precise delta math requires high technical competence.

Combinatorial / Cross-Venue Arbitrage: Least Promising. Attempting to guarantee profit by balancing probabilities between Polymarket and Kalshi. This is entirely dominated by institutional HFTs, heavily penalized by taker fees, and fraught with "broken leg" execution risk.

You are reviewing a high-probability prediction-market strategy that buys contracts priced around 0.80 to 0.90.



The basic idea is to buy “likely winners” rather than cheap lottery-style contracts.



I want a brutally honest research memo on whether this can work after fees, slippage, occasional tail losses, and market efficiency.



Please address:

- Why high-probability contracts can look safe but still have poor expectancy

- The difference between high hit rate and positive EV

- How often tail losses wipe out many small wins

- Whether this works better with maker fills than taker fills

- What kinds of mispricings near 0.80 to 0.90 are actually believable

- Whether this approach is more robust than buying cheap 0.02 to 0.15 contracts

- How contract resolution timing and late price movement affect it

- When to prefer buying 0.80 to 0.90 vs selling the opposite side

- How to size risk when a single loss can erase many wins



Please produce:

- expectancy math examples

- threshold rules for acceptable fees/slippage

- examples of good vs bad entries

- filters to reduce false safety

- whether repeated entries in the same coin are ever justified

- a recommended shadow test plan

Here is the brutally honest research memo evaluating the high-probability (0.80 to 0.90) contract strategy in short-horizon prediction markets.

MEMO: The Quantitative Reality of High-Probability Prediction Market Strategies
Thesis
Systematically buying prediction market contracts priced between $0.80 and $0.90 is the crypto equivalent of selling out-of-the-money options: it is a "picking up pennies in front of a steamroller" strategy. While it boasts a high raw hit rate and produces a deceptively smooth, upward-sloping backtest equity curve, it suffers from extreme negative asymmetry. The theoretical edge is routinely obliterated by adverse selection, where you only get filled when the market has already moved against you, guaranteeing that periodic tail losses will wipe out weeks of accumulated micro-profits.

High Hit Rate vs. Positive Expected Value (EV)
A high hit rate is a psychological comfort metric, not a mathematical edge. EV is the only metric that dictates survival.

If you systematically buy contracts at $0.85, you are risking $0.85 to make $0.15.

To merely break even before fees, you must win exactly 85% of the time: (0.85 * $0.15) - (0.15 * $0.85) = $0.00.

If your system only wins 82% of the time, your EV is negative: (0.82 * $0.15) - (0.18 * $0.85) = -$0.03 per trade.

A single tail loss (losing the full $0.85) requires roughly six consecutive winning trades just to recover the principal. In short-horizon crypto markets subject to sudden spot volatility, achieving an 86%+ win rate after execution friction is extraordinarily difficult.

The "Fake Safety" of Maker vs. Taker Fills
You have two choices for execution, and both introduce fatal flaws at the $0.80-$0.90 price band:

Maker Fills (Resting Limit Orders): You post a bid at $0.85 to avoid taker fees and capture the spread. This introduces catastrophic adverse selection. In an efficient market driven by APIs, your $0.85 bid will sit unfilled while the true probability is 90%. The exact millisecond the underlying spot asset (e.g., Bitcoin) drops violently, HFT algorithms will instantly dump their now-toxic contracts onto your resting bid. You effectively provide free insurance to faster players. You only get filled when your $0.85 contract is suddenly worth $0.60.

Taker Fills (Market/Aggressive Orders): You cross the spread to guarantee entry. Here, you avoid adverse selection but absorb slippage and fees. Polymarket's taker fee scales based on price uncertainty using a dynamic formula. While fees at $0.90 are mathematically lower than at $0.50, any combined slippage and fee drag of just $0.02 to $0.03 compresses your max profit from $0.15 down to $0.12, meaning your required breakeven win rate jumps from 85% to 88%.

Buying $0.80 vs. Selling the Opposite Side at $0.20
Due to Polymarket's symmetric fee structure, buying a "YES" contract at $0.80 and selling a "NO" contract at $0.20 yield identical mathematical expected values and incur the exact same fee volume.

However, behavioral market microstructure dictates you should sell the opposite side. Retail prediction markets suffer from a documented "favorite-longshot bias". Retail traders irrationally love buying cheap lottery tickets ($0.05 to $0.15). By acting as a market maker selling "NO" contracts at $0.15 to retail gamblers, you can passively harvest this irrational premium, rather than aggressively buying "YES".

Believable Mispricings vs. Toxic Illusions
Not all $0.85 contracts are created equal.

Believable Mispricing: The underlying asset has crossed the strike threshold with strong momentum, but the order book hasn't fully updated from $0.80 to $0.95 because retail participants are hesitating or hedging.

Toxic Illusion: The contract is priced at $0.85 with 45 seconds left, but the underlying spot asset is hovering dangerously close to the strike price. The $0.85 price isn't an "edge"; it represents the market correctly pricing the volatility risk of a last-second oracle flip.

Resolution Timing and Late Price Movements
In 5-minute and 15-minute markets, time decay is non-linear. Entering a high-probability trade in the final 30 seconds is pure latency arbitrage. If a trade fills at $0.85 in the final seconds, it usually means the Chainlink oracle is registering a price that invalidates your position, and faster bots are using you as exit liquidity before the UI resolves.

Is This Better Than Buying Cheap Contracts (0.02 - 0.15)?
Buying cheap contracts suffers from the long-shot bias (you overpay for tail events) and bleeds your account slowly through a 90% loss rate and higher relative fees. Buying high-probability contracts (0.80 - 0.90) bleeds your account violently through sudden, clustered tail losses. Neither is robust on its own. The high-probability strategy is simply much easier to "fake-good" in backtests because historical simulators fail to model the toxic nature of the fills.

Design Rules for High-Probability Execution
Threshold Rules for Fees and Slippage
Spread Maximum: Never execute if the bid-ask spread exceeds $0.02. Wide spreads mean institutional liquidity is absent and slippage will eat your edge.

Friction Ceiling: The combined cost of the taker fee plus expected slippage must never exceed 15% of the expected gross profit.

Examples of Good vs. Bad Entries
Good Entry (Taker Snipe): A 5-minute BTC UP market. BTC spot price surges 0.20% above the strike with 60 seconds left. The Polymarket order book is lagging at $0.82. You aggressively take the offer at $0.82 to capture the latency lag.

Bad Entry (Toxic Maker): Resting a passive bid at $0.85 for 3 minutes. The spot price suddenly drops toward the strike, and your bid is instantly filled.

Filters to Reduce False Safety
Spot Momentum Agreement: Never buy a high-probability "UP" contract if the 1-minute trend of the underlying spot asset is negative.

Volatility Circuit Breaker: If the 5-minute rolling standard deviation of the underlying asset spikes above the 90th percentile, halt trading. Do not try to collect pennies during a macro news event.

Are Repeated Entries (Scaling) Justified?
Never. Averaging down on a binary option is algorithmic suicide. If you bought at $0.85 and the price drops to $0.60, your fundamental thesis that the event had an 85% probability is demonstrably wrong. You must accept the loss. Adding to the position drastically increases correlated exposure to a failing trade within a strictly time-bound window.

Risk Sizing
Because one loss erases six wins, position sizing must be heavily suppressed. Use a fractional Kelly criterion (e.g., 0.1x Kelly) and implement a hard absolute cap: no single trade should exceed 1% of your total trading capital.

Recommended Shadow Test Plan
Do not backtest this with standard OHLCV data; it will lie to you.

Run in Shadow Mode: Stream live order book data via WebSockets.

Log Intentions: When your logic dictates a buy at $0.85, log the timestamp to the millisecond.

Calculate the Toxicity: Look at the price of the underlying spot asset (e.g., Binance BTC/USDT) exactly 5 seconds after your intended fill.

Evaluate: If the spot price moved adversely in those 5 seconds, mark the trade as a "toxic fill" and assume a total loss. Only calculate your EV on the remaining, non-toxic fills, minus a blanket $0.02 slippage penalty. If the EV is still positive, you may advance to fractional live execution.

Based on the strategy analysis above, design a practical architecture for a production-ready crypto prediction-market bot.



My constraints:

- I care about expected value, not just win rate

- I want to avoid correlated wipeouts

- I need to control delay and slippage

- I may trade multiple coins

- I may allow more than one entry in the same coin, but only if justified

- I want clear promotion gates from research to shadow to live



Please produce:

- recommended system architecture

- per-coin config design

- portfolio risk controls

- rules for multiple entries in the same coin

- kill switches

- minimum logging fields

- shadow-mode evaluation framework

- what to disable first if performance degrades



Be opinionated. Prefer a design that is realistic for a solo builder and robust under imperfect execution.

Add a section called “Repeated Entries in the Same Coin.”

Explain:

- when repeated entries are rational

- when they are just disguised overtrading

- what hard rules should govern re-entry

- what max number of entries per coin per interval you recommend

- how to measure whether re-entry improves expectancy or just increases variance

Here is a brutally honest, production-focused architecture designed specifically for a solo quantitative builder targeting short-horizon prediction markets.

This design assumes you do not have the millions of dollars required for FPGA hardware or co-located servers, but you still need an institutional-grade logical framework to survive the latency and slippage traps of 5-minute and 15-minute contracts.

Recommended System Architecture
For a solo builder, using Python for a 5-minute execution bot is a death sentence; the interpreter overhead and garbage collection pauses will routinely result in execution delays of 5 to 8 seconds, ensuring you absorb maximum slippage.

The Tech Stack & Execution Loop:

Language: Go or Rust. Go is highly recommended for a solo builder due to its lightweight Goroutines, which easily handle concurrent WebSocket streams with sub-100ms reaction times.

Data Ingestion Layer: You must establish raw WebSocket connections to both the prediction market (e.g., Polymarket) and the underlying spot venue (e.g., Binance). REST API polling is too slow and will result in trading on stale data.

Execution Layer: Use strictly Fill-or-Kill (FOK) order types. If your required size cannot be filled instantly at your exact price, the order must be canceled automatically to prevent your bot from posting resting liquidity that faster HFTs will use as an exit trap.

Hosting: Deploy on a high-performance VPS located as close to the exchange servers as possible to reduce network transit time.

Per-Coin Config Design
Every coin (BTC, ETH, SOL) requires a strictly independent JSON/YAML configuration file. Hardcoding global variables will cause blowups when altcoins experience idiosyncratic volatility.

target_asset: "BTC"

market_duration: "5m"

max_acceptable_spread: $0.03 (Never cross a spread wider than 3 cents).

min_liquidity_multiplier: 10.0 (The resting liquidity at your price level must be at least 10x your order size).

volatility_halt_percentile: 0.95 (Halt trading if the 5-minute standard deviation of the spot asset breaches its 95th percentile).

max_slippage_cents: $0.02

execution_window_seconds:  (Only fire orders between T-30s and T-10s before market closure).

Portfolio Risk Controls
Fractional Kelly Sizing: Base your size on your edge, heavily penalized. Use a fractional Kelly formula: Edge=Confidence−Price. Kelly= 
(1−Price)
Edge
​
 . Size=Budget×min(Kelly,0.25).

Liquidity-Capped Absolute Max: Regardless of Kelly output, cap every individual trade at 1% to 5% of the available order book liquidity to prevent self-induced slippage.

Correlated Exposure Ceiling (VaR): If you are running multiple markets (e.g., BTC 5m, ETH 15m, SOL 15m), calculate the net directional beta. Your total correlated exposure to a "Crypto UP" outcome must never exceed a hard-coded percentage (e.g., 10%) of your total portfolio at any given millisecond.

Repeated Entries in the Same Coin
Scaling into positions is a double-edged sword. Done correctly, it minimizes market impact; done poorly, it is just emotional averaging down.

When it is Rational: Repeated entries are rational only as a phased execution mechanism (scaling in) designed to absorb liquidity smoothly in thin books. It is only justified if the underlying spot momentum continues to validate the initial signal AND the bid-ask spread has demonstrably tightened since your first fill.

When it is Disguised Overtrading: It is noisy re-entry when your bot fires rapid, duplicate orders at the exact same price level because of micro-fluctuations in the data feed, or when it averages down into a losing position out of a mathematical "need" to improve the breakeven price.

Hard Rules for Re-entry:

Strict Anti-Martingale: Never average down on a binary option. If the contract price drops after your first entry, your probability thesis is wrong. Cut the trade or let it ride, but do not add capital.

Fractional Starts: Your first entry must never exceed 25% of your total intended position size.

Max Number of Entries: A maximum of 3 entries per coin per interval.

Measuring Expectancy vs. Variance: To prove re-entry works, track the expectancy of your trades: Expectancy=(WinRate×AverageWin)−(LossRate×AverageLoss). Group your trades into "Single Entry" vs. "Scaled Entries." If the scaled entries increase your total profit but lower your per-dollar expectancy or radically increase your equity curve drawdown variance, the scaling is inefficient and must be disabled.

Kill Switches
The 3-Strike Toxicity Rule: If you suffer negative execution slippage exceeding your threshold on 3 consecutive trades, instantly blacklist that market. You are being front-run by a faster player.

Oracle Desynchronization: If the prediction market API lags the Binance WebSocket feed by more than 1 second, halt all trading. You are trading blind against HFTs.

Global Drawdown Switch: If the portfolio drops by 5% in a single 24-hour rolling period, lock the system and alert the admin.

Minimum Logging Fields
A database log is your only defense against the "fake-good" backtest. Every execution attempt must record:

signal_timestamp_ms: When your logic fired.

exchange_receipt_ms: When the exchange confirmed the order (measures latency).

bid_ask_spread: The spread width at signal_timestamp_ms.

expected_fill_price: The assumed price based on the mid-market.

actual_fill_price: What you actually paid (calculates slippage drag).

post_fill_5s_spot_price: The price of the underlying asset (e.g., BTC on Binance) exactly 5 seconds after your fill. If this moved violently against you, you just logged an "adverse selection" event.

Shadow-Mode Evaluation & Promotion Gates
To transition safely from theory to live capital, adhere strictly to this 4-step framework:

Data Validation (Research Mode): Run the bot without API execution keys. Ensure your WebSockets remain stable for 72 hours without memory leaks.

Recorded Shadow Mode (2 to 6 weeks): Log every intended trade to a database using the actual best-ask price at the exact millisecond of the signal. Apply a hard $0.02 slippage penalty and deduct dynamic taker fees. If the Expectancy remains positive, proceed.

Canary Live Testing (10 to 20 days): Execute live trades using strictly 1-contract position sizes (e.g., risking $0.85 per trade). Validate that your FOK orders execute correctly and that your actual_fill_price matches your shadow-mode expectations.

Phased Capital Scaling: If canary metrics pass, increase position sizing to 25% of the Kelly output.

What to Disable First if Performance Degrades
If your live equity curve begins to bleed, do not tweak indicators—cut exposure structurally in this exact order:

Disable "Maker" (Limit) Orders First: If you are bleeding, you are likely suffering from adverse selection (toxic fills). Stop providing passive liquidity immediately.

Disable Repeated Entries (Scaling): Revert to single-bullet execution to instantly cut your maximum directional risk exposure by 75%.

Disable Altcoins (SOL/ETH): Altcoin prediction markets suffer from severe liquidity droughts. Disable them and retreat to the BTC 5-minute market, which has the deepest order books and lowest relative spreads.

Halt 5-Minute Markets: If you are still losing, your latency budget is fundamentally broken. Halt 5-minute operations entirely and move to 15-minute or 1-hour markets where the speed of execution is slightly less punitive.