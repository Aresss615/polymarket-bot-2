# Research memo on buying 0.80–0.90 prediction-market contracts

## Context and headline conclusion

Buying “likely winners” (contracts priced ~0.80–0.90) can feel safer because the mark-to-market usually looks stable and your win rate will often be high. But that *safety feeling* is not the same thing as having positive expectancy (positive EV). A high-priced contract has a structurally lopsided payoff: you risk a large amount to win a small amount, so a single loss can erase many wins even before fees and slippage.

The brutally honest take is:

This approach can work **only** if you can (a) repeatedly identify **real** mispricings of several percentage points *after* costs, (b) trade in **high-liquidity** markets with tight spreads, and (c) execute mostly as a **maker** (or at least avoid paying full spread + full taker fees). The edge required is usually larger than people intuit, because “80–90% likely” leaves little room for costs and error.

Market-level evidence also says: prediction markets are often informative and become more accurate nearer expiry, so the “easy” edges tend to get competed away. citeturn4view2turn7view2turn7view3  
At the same time, there is credible evidence of a systematic favourite–longshot bias (low-price “lottery” contracts underperform; higher-price contracts can have slightly better returns), which is one of the *few* believable reasons a “likely winner” tilt might have a small tailwind. citeturn5view0turn7view0turn8view0turn4view0

The practical implication: if you trade this as a **taker** in mediocre liquidity, your expectancy is very likely negative. If you trade it as a **maker** with disciplined filters and conservative sizing, it might be viable—but the strategy becomes “microstructure + selection” more than “buy high-probability.”

## Mechanics of high-probability contracts

A standard winner-take-all prediction-market contract costs price **p** (between 0 and 1) and pays **1** if the event occurs and **0** otherwise. citeturn5view2turn8view0  
If your true probability estimate is **q**, then:

**Expected value (before costs) per contract = q − p.**  
This follows directly from the payoff definition (expected payout = q·1 + (1−q)·0 = q; you paid p). citeturn5view2turn8view0

### Why high-probability can look safe but have poor expectancy

For p in 0.80–0.90, your *maximum* profit is only 0.10–0.20, but your loss is 0.80–0.90. That means you need to be right *a lot*, and you need the market price to be meaningfully wrong in your favour.

A concrete example (ignoring fees):
- Buy at **p = 0.85**
- Win → profit **+0.15**
- Lose → profit **−0.85**
- EV = **q − 0.85**

If your “high-probability” intuition says q≈0.86, your EV is only +0.01 per contract **before** fees/spread/slippage. That’s a tiny edge in absolute terms, and it’s very easy for costs (or small misestimation) to turn +0.01 into negative.

### High hit rate vs positive EV

A high hit rate can still lose money if the payoff is asymmetric.

Example: suppose you win **90%** of the time but you are overpaying.
- Buy at p = 0.92
- True probability q = 0.90  
Then EV per contract = 0.90 − 0.92 = **−0.02** (you lose 2¢ per contract on average) even though you still win most of the time. citeturn8view0turn5view2

For high-priced contracts, the “wins feel frequent” effect can mask the fact you’re slowly bleeding expectancy.

### How often tail losses wipe out many small wins

For a long position at price p:
- Wins pay **(1 − p)**
- Losses cost **p**
- Wins needed to offset one loss (ignoring costs) = **p / (1 − p)**

So:
- At p = 0.80: 0.80 / 0.20 = **4** wins to cover one loss
- At p = 0.85: 0.85 / 0.15 ≈ **5.67** wins
- At p = 0.90: 0.90 / 0.10 = **9** wins

That’s the core “tail loss” dynamic: even if losses are rare, the accounting is brutal. This isn’t exotic tail risk—it is the *ordinary* downside of a binary bet with skewed payoffs. citeturn5view2turn8view0

Even with a genuinely strong q = 0.90 on p = 0.85 contracts, the probability of at least one loss over many trades becomes near-certain:
- Over 20 independent trades with 90% win chance: 1 − 0.9²⁰ ≈ **88%** chance you take at least one full loss.
That single loss can erase ~5–6 wins at p=0.85.

In real portfolios, losses also cluster because positions are often correlated (e.g., “macro surprises,” election shocks, regime breaks), making the wipeout pattern worse than the independent math suggests. citeturn8view1turn5view1

## Where edge gets crushed: fees, spreads, slippage, and time

### Fee schedules matter more than people think at 0.80–0.90

Both entity["company","Kalshi","prediction market dcm us"] and entity["company","Polymarket","crypto prediction market"] commonly implement fees that are (in various ways) proportional to **p(1−p)**, meaning fees are highest near 0.50 and lower near the extremes. citeturn2view0turn1view0turn1view2  
But “lower near extremes” is not the same as “small relative to your edge,” because your edge is also typically small near 0.80–0.90.

Kalshi’s published fee schedule describes:
- Taker trading fee: **fees = round up(0.07 × C × p × (1−p))**  
- Potential maker fee (in some markets): **fees = round up(0.0175 × C × p × (1−p))**  
and the PDF table indicates that at p=0.85 the fee is about **$0.90 per 100 contracts** (≈0.9¢/contract), and at p=0.90 about **$0.63 per 100** (≈0.63¢/contract). citeturn2view0

Polymarket’s documentation similarly states:
- **fee = C × feeRate × p × (1 − p)**  
with category-specific taker fee rates and fee tables. For example, in the “Finance / Politics / Mentions / Tech” table, the taker fee is listed as about **$0.38 per 100 shares at p=0.85** and **$0.27 per 100 at p=0.90**; other categories (e.g., crypto) can be meaningfully higher. citeturn1view0  
Polymarket US’s fee schedule presents a similar p(1−p) approach and shows maker rebates as a fraction of taker fees. citeturn1view2

### The real enemy is “all-in cost”: fee + spread + slippage

The practical break-even rule is:

**Net EV = (q − p) − cost**, so **q must exceed p by at least your all-in cost**. citeturn8view0turn5view2

Where “cost” should include:
- Explicit fees (platform fee schedules) citeturn2view0turn1view0turn1view2
- The bid–ask spread you cross as a taker (an immediate transaction cost) citeturn6search9
- Slippage (execution worse than expected, especially in thin books or volatile moments) citeturn6search33

Because the tick size is often 1¢ and contracts only trade between 0 and 1, even a 1–2¢ spread is a large fraction of your *maximum profit* when buying 0.85–0.90. That’s a structural reason this approach fails if you can’t trade tightly.

### Threshold rules for acceptable fees/slippage

Let:
- p = entry price
- c = all-in cost per contract (in “probability points,” i.e., dollars per $1 payout unit)
- You hold to resolution (no exit trade), so only entry costs apply

Then your minimum required true probability is:

**q_min = p + c**

A practical way to estimate **c** for a taker entry is:

**c ≈ fee_per_contract + (half-spread) + expected slippage**

Worked examples (illustrative, using published fee tables):
- If you buy p=0.85 and your effective cost is ~0.01 (fee) + 0.01 (spread impact) = 0.02, then you need q ≳ **0.87** to break even. Kalshi’s taker fees at p=0.85 are about 0.9¢ per contract at 100-lot scale, so “~1¢ fee” is not a wild estimate; spread/slippage can easily add another cent in average conditions. citeturn2view0
- On Polymarket categories where taker fees at p=0.85 are ~0.38¢ per contract (per the 100-share table), you *might* have fee closer to 0.004, but spread/slippage can dominate anyway. citeturn1view0

A tougher but safer rule (because q is estimated with error) is to require a cushion:

**q_min = p + c + m**, where **m** is an uncertainty margin (often 0.01–0.03 in practice unless you have a very strong model and stable market conditions).

### Contract timing and late price movement change the economics

Two timing realities matter:

Markets tend to become more accurate near expiry/closing, which reduces mispricing opportunity as resolution approaches. A large Kalshi dataset finds accuracy improves as markets approach closing. citeturn4view0turn7view1turn7view0  
Separately, research on prediction markets finds they are often reasonably calibrated at shorter horizons, but can show biases and calibration issues when time-to-expiration is longer. citeturn8view0

Your “return” is also constrained by how long capital is locked. Buying 0.90 for months is an unattractive use of capital unless the edge is unusually large or you can recycle the bankroll frequently. The general forecasting literature notes prediction markets can function well, but that does not imply mispricings are large enough to support profitable trading once frictions are included. citeturn8view1turn4view2

A practical timing filter many traders miss:
- Evaluate an *implied yield*: **max profit / capital at risk / time**.  
For long yes at price p held to resolution, max profit fraction on stake is **(1−p)/p**. If p=0.90, that’s 0.10/0.90 ≈ 11.1% *before costs*, but only if it resolves quickly; over long horizons, that yield compresses sharply.

## Maker vs taker execution: when it helps and when it hurts

### Maker fills are usually structurally better—but you inherit different risks

The maker/taker distinction is central because takers pay for immediacy (fees + crossing spread), while makers often get better prices but risk non-execution and being “picked off” by better-informed flow.

Kalshi’s own framing (as quoted in academic work) describes: makers post offers; takers accept the most generous offer. citeturn7view0turn4view1  
Polymarket’s fee structures and Polymarket US’s schedule explicitly include maker rebates/benefits relative to taker fees. citeturn1view0turn1view2turn0search32

Empirically, the Kalshi microstructure paper finds:
- Favourite–longshot bias exists for both makers and takers, but is **more pronounced for prices accepted by takers**, and the model argues takers have more extreme beliefs and tolerate worse prices/fees, producing worse returns for takers. citeturn7view0turn7view1turn4view0

So, if your strategy is “buy 0.80–0.90 as a taker,” you’re choosing the costliest path in the very regime where edges are smallest.

### Why maker trading is not a free lunch

Maker trading introduces two hard problems:

Fill risk: you might not get filled, so your “paper edge” isn’t monetised.

Adverse selection: you get filled disproportionately when the value moved against you (someone with new info happily takes your stale quote). The microstructure literature cited in the Kalshi paper explicitly models how quote-driven markets produce spreads and how selection into maker/taker roles relates to information and beliefs. citeturn7view0turn7view1turn4view0

A practical implication for 0.80–0.90:
- Maker trading improves expectancy **if** you have (i) latency/attention to cancel quickly when info shifts and (ii) a strong filter for when spreads compensate you enough for the information risk.

## What mispricings at 0.80–0.90 are actually believable

“Believable” here means: consistent with known biases/microstructure, repeatable, and large enough to survive costs.

### Believable sources of mispricing near 0.80–0.90

Favourite–longshot bias / probability misperception: In gambling markets, longshots tend to be overbet and favourites underbet; one explanation is misperception/overweighting of small probabilities (Prospect Theory-type mechanisms). citeturn5view0turn8view0  
In Kalshi data, high-price contracts win slightly more often than their prices imply and can yield small positive returns, while cheap contracts perform very poorly. citeturn4view0turn7view0turn7view1  
If this bias persists, it provides a plausible “wind at your back” for avoiding longshots and leaning into favourites—but note the reported edge is described as *small*, and (importantly) taker execution is worse. citeturn7view0turn4view0

Contract clarity vs popularity tension: Prediction-market design work notes that contracts must be well specified, but popularity/liquidity may favour less precise questions; ambiguity can materially affect outcomes. citeturn8view1  
In the 0.80–0.90 range, “looks obvious” can be undermined by *settlement semantics*—you don’t lose because the world surprised you, you lose because the contract resolves in a way you didn’t model.

Thin markets / limits to information aggregation: When markets are thin, incentives to discover and trade on private information are weaker, which can allow mispricing to persist—but thinness also increases spreads/slippage and exposure to manipulation/noise. citeturn8view1turn5view1  
entity["people","Justin Wolfers","economist"] and entity["people","Eric Zitzewitz","economist"] also note that interpretation of prices can be less reliable near extremes (close to 0 or 1) under conditions like dispersed beliefs, constrained volume, or unusual risk acceptance—exactly the environment where you might see 0.90 prices that still aren’t “certain.” citeturn5view1

### Good vs bad entries (concrete examples)

Good entry archetype (believable edge survives costs):
- High liquidity (1–2¢ spread), meaningful depth, no obvious info cliff imminent. citeturn6search9turn6search33  
- Contract terms are crisp and operationally checkable (you can point to a single authoritative data source). citeturn8view1  
- You have an independent probability estimate q that differs from price by **≥ (all-in cost + margin)**, not just a vibe. citeturn8view0turn5view2  
- You can enter passively (maker) or at least avoid crossing a wide spread; maker/taker evidence suggests taker prices/returns are worse. citeturn7view0turn1view2turn2view0

Bad entry archetype (false safety):
- Wide spread / thin book: you pay 2–5¢ in spread impact on a trade whose max profit is 10–15¢, destroying expectancy. citeturn6search9turn6search33  
- Ambiguous settlement (“what exactly counts?”), where disputes or technicalities are plausible. citeturn8view1  
- Long-dated “almost sure” outcomes where you are tying up capital for a small capped payoff while information can drift against you over time. citeturn8view0turn4view0  
- You are forced to be a taker repeatedly (immediate execution mindset), effectively donating spread + taker fees in a low-edge regime. citeturn7view0turn1view0turn2view0

### Is this more robust than buying 0.02–0.15 contracts?

The best evidence-based argument *for* your approach is that longshot-style contracts can be systematically overpriced and perform badly. The Kalshi work reports that contracts priced below 10¢ lose *very* heavily on average, while higher-price contracts can have small positive returns. citeturn7view0turn4view0  
This is aligned with the broader favourite–longshot bias literature in betting markets. citeturn5view0turn8view0

But “more robust than longshots” does **not** automatically mean “profitable after costs.” Some forecasting literature explicitly cautions that observed mispricings in some contexts are not large enough to support profitable trading strategies once frictions are considered. citeturn8view1  
So the honest comparative answer is:

If you are trading casually (taker, non-systematic entry), favourites are likely *less bad* than longshots.  
If you are seeking repeatable positive EV after costs, both regimes are hard—favourites demand small, precise edges and excellent execution; longshots demand rare-event modelling skill and tolerance for long losing streaks.

## Positioning choices, sizing, repeated entries, and a shadow test plan

### When to prefer buying 0.80–0.90 vs selling the opposite side

In a frictionless market, “buy yes at p” and “sell no at (1−p)” create the same payoff profile (profit if yes, loss if no). In practice, you choose the expression that minimises frictions:

Prefer the route that:
- Lets you be a maker more often (or receive maker rebates where applicable). citeturn1view2turn1view0turn2view0  
- Has tighter liquidity on that side of the book (sometimes yes-side and no-side books are not symmetric in depth). citeturn7view1turn6search9  
- Minimises explicit fees under the platform rules (fee schedules can differ by role and market). citeturn2view0turn1view0turn1view2

A common mistake is to ignore the “embedded spread”: if the best yes ask is 0.86 but the best no ask is 0.16 (implying 1.02 total), the market is charging you for immediacy. The Kalshi microstructure discussion explicitly notes that the sum of best taker prices can exceed 1 because of spreads. citeturn4view1turn7view0

### How to size risk when one loss erases many wins

Because losses are large relative to wins at high p, sizing has to be conservative unless your edge is both large and reliable.

Two practical sizing frames:

Loss-budget sizing (simple, robust):
- Decide a max bankroll drawdown you will accept from a single upset (e.g., 0.5%–2%).
- If you buy at p, your worst-case loss is essentially the stake you paid. So stake fraction f should be ≤ that loss budget.
- At p=0.85, if you stake 1% of bankroll, you win only ~0.176% on a win but lose 1% on a loss—consistent with the “5.67 wins per loss” math.

Fractional Kelly (only if you have a calibrated q and independence assumptions):
- A Kelly-style fraction exists for skewed bets, but it is extremely sensitive to q estimation error; if your “q” is off by even 1–2 percentage points in this regime, Kelly sizing becomes over-aggressive.
- Given published evidence that markets are often accurate and improve near closing, any persistent edge is likely small, so full-Kelly behaviour is generally inappropriate. citeturn7view2turn4view0turn8view1

### Filters to reduce “false safety” (operational checklist)

Contract-quality filters:
- Clear settlement source and unambiguous wording; avoid “interpretation risk.” citeturn8view1  
- Avoid contracts where extreme prices may be less informative due to dispersed beliefs/low volume. citeturn5view1

Market-quality filters:
- Require tight spreads relative to max profit (e.g., spread ≤ 10% of (1−p), and ideally much less). Spread is a direct cost of immediacy. citeturn6search9  
- Minimum depth at your intended size to control slippage. citeturn6search33  
- Avoid trading immediately before known info events unless you are the one bringing the information (reduces adverse selection as a maker). citeturn7view1turn7view0

Edge-validation filters:
- Require an independently computed q (model, reference forecast aggregation, or mechanical rule) and log it before entry; don’t allow “it feels like 90%.” citeturn8view0turn5view2  
- Apply a margin-of-safety: only trade when (q − p) exceeds all-in costs by a buffer.

Portfolio filters:
- Cap exposure to correlated themes (e.g., multiple bets that all lose if one macro shock happens). Thin markets + correlated tails are a known failure mode for prediction markets. citeturn8view1turn5view1

### Are repeated entries in the same contract ever justified?

Sometimes, but they should be treated as **one aggregated bet** with a single risk cap.

Repeated entries are most defensible when:
- New information arrives that you can explain and quantify, and your fair value q updates upward meaningfully while price lags. citeturn4view0turn7view2  
- Liquidity conditions improve (spread tightens) so your all-in cost drops, raising EV.

Repeated entries are usually unjustified when they are:
- “Averaging up” just because price is moving in your direction (often means the market is incorporating information you did not originate).
- Concentration creep driven by high win rate and emotional comfort.

The maker/taker evidence is relevant here: if your new fills are occurring because you’re being hit as a maker in a fast-moving market, repeated entries can be systematically worse than your initial entry (adverse selection). citeturn7view0turn7view1

### Recommended shadow test plan

A shadow test should answer one question: **Does your realised edge survive the exact way you actually trade (costs, fills, timing, and correlation)?**

Design:
- Define your universe: only contracts in 0.80–0.90 (and a matched sample in 0.02–0.15 for comparison).
- For each candidate trade, log *before* entry:
  - Timestamp, market, side, p, spread, visible depth at best prices
  - Your q and how derived (even if simple)
  - Planned execution: maker limit price vs taker price
  - Expected fees using the published fee schedule for that platform/market type citeturn1view0turn2view0turn1view2
  - Time to expiry and whether you intend to hold to resolution

Execution realism:
- Simulate both:
  - Taker version (assume you cross the spread now)
  - Maker version (assume you post at your limit; count fill only if price trades through your order; otherwise “no trade”)
- This distinguishes “paper EV” from “fillable EV,” which is where many strategies die. citeturn7view1turn7view0

Evaluation metrics (must be net of frictions):
- Net P&L per contract and per dollar at risk
- Hit rate vs EV (show both; don’t let hit rate seduce you)
- Drawdown statistics and “wins-to-recover-loss” realised frequency for your p band
- Sensitivity to spread regime (tight vs average vs wide)
- Correlation clustering: how often multiple positions lose on the same day/week

Go/no-go criteria (practical thresholds):
- You should only go live if the maker-mode shadow portfolio shows:
  - Positive net expectancy with a statistically meaningful sample size (at least 100+ fills, ideally more), and
  - Drawdowns that match your psychological and bankroll constraints.
- If only the taker-mode is positive in the shadow test, treat that as a red flag: it often indicates backtest artefacts or unrealistic assumptions about slippage/fees. citeturn6search33turn6search9

Finally, run an “edge stress test”:
- Subtract an extra 1–2¢ per contract as an error bar (for unseen slippage, bad settlement surprises, and model overconfidence). If the strategy flips negative under that small stress, it was never robust in the first place—especially in the 0.80–0.90 regime where true edges are typically thin. citeturn5view1turn8view1turn4view0