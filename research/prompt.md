Act as the Lead Systems Architect and Quant Developer for my repository, Polymarket-Bot-2.

Your job is to inspect the repo, synthesize the research docs, AND analyze real trading behavior to produce a production-ready v10 upgrade plan that is actually implementable in this codebase.

Do not give generic advice. Do not invent a new architecture from scratch. Work inside the existing repo and improve it surgically.

-----------------------------------
STEP 1 — CONTEXT INGESTION
-----------------------------------

Read and internalize these files first:

- CLAUDE.md
- refactor_spec.md
- LIVE_TRADING_PLAN.md
- CHANGELOG.md
- Files in the research folder
- Paper trading logs (IMPORTANT — 5 days of v9 execution data)

Treat:
- PDFs → theoretical research
- .md files → system design + constraints + suggestion from other ai models
- paper trading logs → ground truth behavior

DO NOT summarize them. Instead extract:
- actual performance patterns
- hidden weaknesses
- mismatches between theory and execution
- where the bot is leaking money or taking unnecessary risk

-----------------------------------
STEP 2 — OBJECTIVE
-----------------------------------

Design a production-grade v10 upgrade plan that:

- Improves expected value (EV), not just win rate
- Reduces drawdown and variance
- Fixes real-world execution issues
- Aligns signals with actual fill behavior
- Preserves system simplicity where possible

You must base decisions on BOTH:
- research findings
- actual paper trading results

If they conflict → trust the trading data more.

-----------------------------------
STEP 3 — REQUIRED ANALYSIS (CRITICAL)
-----------------------------------

Before proposing changes, explicitly analyze the 5-day paper trading data:

1. Identify strongest conditions:
   - best entry timing windows
   - best edge ranges
   - best market types

2. Identify weakest conditions:
   - losing trades (BTC NO-side, low price entries, etc.)
   - poor-performing timeframes (especially 15m)
   - overtrading or bad fills

3. Detect structural issues:
   - false edge (signals that look good but lose money)
   - execution lag problems
   - fill assumptions vs reality

4. Output:
   - What is ACTUALLY working
   - What must be removed or restricted
   - What should be scaled up

-----------------------------------
STEP 4 — CORE SYSTEM UPGRADES
-----------------------------------

Your plan MUST include implementation-level details for:

1. Execution Integrity
   - Eliminate phantom PnL
   - Only update state from confirmed fills
   - Handle partial fills, cancellations, rejections
   - Ensure portfolio always matches real state

2. Maker-Only Execution Layer
   - Use post_only + GTC where viable
   - Avoid taker fees
   - Add cancel/requote protection
   - Prevent adverse selection

3. Microstructure Cancel Engine
   - Lightweight system using:
     - order book imbalance
     - spread widening
     - microprice movement
   - Must run fast in a live loop
   - Avoid unnecessary complexity

4. BTC NO-Side Optimization
   - Replace static blacklist
   - Add momentum-based filter (CEX-based)
   - Dynamically skip or reduce size
   - Integrate into existing signal flow

5. 15-Minute Market Adaptation
   - Add time-decay confidence scaling
   - Reduce early and late exposure
   - Increase edge requirements
   - Align with observed performance from logs

6. Hot-Path Optimization
   - Remove blocking LLM calls
   - Replace with fast deterministic logic
   - Keep sentiment lightweight and async

7. Threading & Performance
   - Separate ingestion, signal, execution loops
   - Avoid blocking calls
   - Improve reaction time (<1s target)

8. Risk Management (STRICT)
   - Daily loss halt
   - Max drawdown kill switch
   - Consecutive loss pause
   - Max bet size
   - Max exposure
   - MUST run before every trade

-----------------------------------
STEP 5 — CONSTRAINTS
-----------------------------------

- Do NOT redesign the entire repo
- Do NOT overengineer
- Prefer simple, robust solutions
- Every suggestion must map to real code changes
- If a research idea is not practical → discard it
- If something is unclear → make a reasonable assumption and proceed

-----------------------------------
STEP 6 — OUTPUT FORMAT
-----------------------------------

1. Architecture Review
   - current weaknesses (based on logs + repo)
   - strongest edges to preserve
   - highest-impact fixes
   - what NOT to change yet

2. Paper Trading Insights (MANDATORY)
   - key performance patterns
   - biggest leaks
   - actionable conclusions

3. Phased Roadmap
   - Phase 1: Execution integrity + state sync
   - Phase 2: Signal improvements (BTC + 15m)
   - Phase 3: Execution + cancel engine
   - Phase 4: Performance/threading
   - Phase 5: Risk system

Explain why this order is correct.

-----------------------------------
STEP 7 — PHASE 1 IMPLEMENTATION
-----------------------------------

Only implement Phase 1 in code.

Provide:
- file-by-file changes
- exact Python functions/classes
- integration points
- minimal but production-ready code

Focus ONLY on:
- confirmed fills
- partial fill handling
- state reconciliation
- eliminating phantom PnL

-----------------------------------
STEP 8 — STOP RULE
-----------------------------------

After Phase 1:

STOP.

Ask for approval before continuing.

-----------------------------------
FINAL INSTRUCTION
-----------------------------------

Build a system that:
- survives live trading
- avoids hidden execution risks
- improves real profitability

Do NOT optimize for theory.
Optimize for what actually works in live conditions.