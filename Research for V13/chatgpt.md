# V13 Deep Research Prompt for ChatGPT

Act as a skeptical quantitative trading researcher and systems designer reviewing short-horizon crypto prediction-market bots for Polymarket-like 5m and 15m contracts.

The objective is not to generate exciting alpha stories. The objective is to find strategies and architecture choices that might survive real execution after fees, slippage, delays, thin books, correlated losses, and repeated-entry mistakes.

Current project conclusions you must incorporate:

- A recent two-hour simulated trade log suggested the core issue was **correlated batch losses**.
- Another issue was weak performance from **cheap-contract YES bets**, especially when those trades looked cheap but may not have been truly +EV after execution costs and late-window risk.
- In that same sample, **XRP, BNB, and ETH looked weak**, while **BTC and SOL held up better**.
- We already discussed that separate bots per coin may help operational isolation or reduce some latency bottlenecks, but they likely **do not improve prediction accuracy on their own**.
- The architecture that currently seems most rational is **one shared engine with concurrent per-coin lanes plus central risk controls**.

Evaluate these three new strategy directions:

1. Copy-trading top wallets
2. Coin-spread / relative-value trading
3. Buying 0.80 to 0.90 contracts

For each one, provide:

- core thesis
- why it might work here
- key failure modes
- latency sensitivity
- fee and slippage sensitivity
- how correlation can break it
- how repeated entries in the same coin can break it
- whether it belongs in live trading, paper trading, or research only
- the fairest backtest design
- the minimum credible sample size
- the rejection criteria

Then compare the three on:

- edge durability
- implementation complexity
- operational risk
- backtest fragility
- sensitivity to latency
- sensitivity to liquidity
- sensitivity to correlation
- fit for a solo retail builder

Then give me a direct recommendation on architecture:

- Should I run separate bots per coin?
- Should I run one shared engine with concurrent per-coin lanes?
- Should I require a portfolio-level central risk manager no matter what?

Be explicit about the difference between:

- improving latency or software isolation
- improving actual predictive accuracy

I want you to argue whether separate bots mostly solve engineering problems rather than alpha problems.

I also want a concrete section on `Rules For Repeated Entries In The Same Coin`.

That section should cover:

- whether averaging down should be forbidden
- whether pyramiding should be forbidden
- whether the bot can re-enter the same coin in the next contract window
- max number of consecutive entries in the same direction
- when a loss streak should force a cooldown
- when a coin should be disabled entirely

Important constraints:

- Assume maker/taker fees exist
- Assume delayed fills and shallow liquidity are real
- Assume some opportunities vanish in seconds
- Assume broad crypto moves can make several coins fail together
- Assume honest backtests must use executable quotes, not midpoint fantasies
- Be brutally honest and focus on failure first

End with a `Most Realistic V13 Rollout Plan` that explains:

- what to test first
- what to test only in shadow mode
- whether BTC/SOL should be prioritized over XRP/BNB/ETH
- what evidence would justify re-enabling weak coins
- what evidence would justify abandoning cheap YES trades entirely
