# FROM CLAUDE
# Polymarket-Bot-2 Refactor Roadmap (v9 -> v10)
**Core Objective:** Pivot from naive Taker/Arbitrage to Maker-First Execution to capture 0% crypto fees + volume-weighted rebates, mitigating adverse selection via CLOB microstructure analysis.

## Phase 1: Critical Bug Fixes & Security (Immediate)
*These must be resolved before deploying any new alpha logic.*

- [ ] **Fix "Phantom PnL" State Desync:** - Modify `LiveExecutor` to return a strict `OrderResult` object.
  - Update `portfolio.py` to ledger **only** the `matched_size` and exact execution prices from the API response. Deprecate "fire-and-forget" intent logging.
- [ ] **Enforce Maker-Only Execution:**
  - Hardcode `post_only=True` on all `LiveExecutor` limit orders.
  - Switch order types from FOK (Fill-Or-Kill) to GTC (Good-Till-Cancel) to prevent payload/signature rejections during fee rate volatility.
- [ ] **Implement Automated Settlement (`claim_winnings`):**
  - Build a background loop utilizing `py-clob-client`'s redeem function.
  - Sweep winning shares into USDCe to eliminate dead capital.
- [ ] **Enforce L2 Security Mandate:**
  - Purge Polygon L1 private keys from `.env` and configuration files.
  - Transition all execution logic to strictly use Polymarket Layer 2 proxy credentials (API Key, Secret, Passphrase).

## Phase 2: Hot-Path NLP Restructure
*The Groq LLM API (200-2000ms latency) is too slow for 5m/15m crypto markets. We are moving to a sub-15ms NLP cascade.*

- [ ] **Decouple Groq LLM:** Move Groq entirely off the hot path (relegate to background taxonomy, post-trade attribution, or complex market mapping).
- [ ] **Implement Zero-Allocation Pre-filter:** - Build an Aho-Corasick or Regex pre-filter to instantly drop irrelevant WebSocket headlines.
- [ ] **Integrate Fast Sentiment Scoring:**
  - **Tier 1 (CPU):** Implement VADER sentiment scoring (<0.1ms per headline).
  - **Tier 2 (GPU/ONNX - Optional):** Implement FinBERT / DistilBERT via ONNX Runtime (~3-15ms) for higher financial accuracy.
- [ ] **WebSocket Data Ingestion:**
  - Route execution triggers through `wss://news.treeofalpha.com/ws` or Polymarket RTDS for lowest-latency delivery.

## Phase 3: The Microstructure Cancel Engine (Core Edge)
*Surviving the 3.15% dynamic taker fee requires pulling resting quotes before informed flow sweeps the book.*

- [ ] **Upgrade `LevelAnalyzer` WebSocket:** - Subscribe to `wss://ws-subscriptions-clob.polymarket.com/ws/market` with `custom_feature_enabled: true` to receive `best_bid_ask` events.
- [ ] **Implement Micro-Price Estimator ($\mu_t$):**
  - Calculate: $\mu_t = \frac{Ask\_Price \cdot Bid\_Depth + Bid\_Price \cdot Ask\_Depth}{Ask\_Depth + Bid\_Depth}$
- [ ] **Implement Order Flow Imbalance (OBI):**
  - Calculate depth-weighted exponential OBI across a rolling tick window.
- [ ] **Wire the "Kill Switches" (Cancel Triggers):**
  - **Trigger 1:** Pull quote immediately if $|OBI| > 0.6$ against our resting side.
  - **Trigger 2:** Pull quote immediately if Micro-price ($\mu_t$) crosses through our resting quote.
  - **Trigger 3:** Pull all market quotes if a large taker sweep removes > 3 levels in < 500ms.
  - **Trigger 4:** Pull all market quotes if Volume-Synchronized Probability of Informed Trading ($VPIN$) > 0.7 within 60s of market resolution.

## Phase 4: Threading & Alternative Alpha (Next-Gen)
- [ ] **Python GIL Mitigation:**
  - Isolate WebSocket ingestion and OBI matrix math into separate sub-interpreters (PEP 684) or dedicated processes to prevent the synchronous main thread from bottlenecking.
- [ ] **Binance Momentum Signal (Lead-Lag Arb):**
  - Subscribe to Binance `aggTrade` WS for BTC/ETH.
  - Trigger: If underlying moves > 0.3% in 60s, pull Polymarket quotes or cross the spread if expected edge > dynamic taker fee.
- [ ] **Whale Shadowing (Off-Path):**
  - Create `WhaleShadow` module connected to Alchemy `pendingTransactions` (Polygon mempool).
  - Monitor `CTF_EXCHANGE` and `NEGRISK_EXCHANGE` for direct operations (splits/merges) from highly-scored wallets.



# FROM CHATGPT
Your Gemini + research synthesis is actually **very strong structurally**—it’s basically already an institutional HFT spec. The main issue is not quality, but **it’s slightly “over-academic + under-implementation constrained.”**

Right now it mixes:

* real production fixes (PnL desync, settlement, post-only execution)
* high-frequency microstructure theory (OBI, VPIN, microprice)
* infra rewrites (LLM removal, threading, WS architecture)
* optional alpha research (Binance lead-lag, whale shadowing)

What it needs to become production-grade is:

* strict prioritization (what breaks PnL vs what improves edge)
* explicit interfaces (what files/functions change)
* deterministic execution rules (no ambiguity like “optional GPU”)
* safety + failure modes (what happens if WS dies, fills partial, etc.)
* testability hooks (so you don’t break live bot again)

---

# ✅ PRODUCTION-GRADE REWRITE: `refactor_spec.md (v10)`

---

# Polymarket-Bot v10 — Production Refactor Specification

**Objective:** Stabilize execution correctness, eliminate PnL drift, enforce maker-first execution, and introduce microstructure-driven cancel logic without compromising system determinism.

**Constraint:** Do NOT modify market data ingestion architecture outside WebSocket handlers. Do NOT introduce blocking LLM calls in execution path. All changes must be backward-compatible with current engine loop.

---

# 1. CRITICAL SYSTEM FIXES (BLOCKING RELEASE)

## 1.1 Eliminate Phantom PnL (State Desynchronization Fix)

### Problem

Current system logs *intent* instead of *execution truth*, causing:

* inflated PnL
* incorrect risk exposure
* invalid trade history reconstruction

### Required Changes

#### `config.py`

Update:

```python
@dataclass
class OrderResult:
    order_id: str
    status: str  # FILLED / PARTIAL / FAILED

    filled_size: float
    fill_price: float
    fees_paid: float

    avg_execution_price: float
    raw_response: dict
```

---

#### `LiveExecutor.execute()`

MANDATORY RULES:

* NEVER return signal.requested_size
* ONLY return API-confirmed fills
* If fill == 0 → return FAILED state

```python
response = clob.create_order(...)

return OrderResult(
    order_id=response["order_id"],
    status=response["status"],
    filled_size=response["filled_size"],
    fill_price=response["avg_price"],
    fees_paid=response["fees"],
    avg_execution_price=response["avg_price"],
    raw_response=response
)
```

---

#### `engine.py`

Replace:

```python
Trade(size=signal.size, price=signal.price)
```

WITH:

```python
Trade(
    size=order_result.filled_size,
    price=order_result.avg_execution_price
)
```

---

### Acceptance Criteria

* CSV ledger matches exchange fills exactly
* Backtest replay matches live ledger within ±0.1% deviation
* No “ghost positions” possible

---

## 1.2 Maker-Only Execution Enforcement

### Rule

All orders must be:

* `post_only = True`
* `order_type = LIMIT_GTC`
* NO FOK ORDERS ALLOWED

---

### `LiveExecutor`

```python
order = {
    "side": signal.side,
    "price": signal.price,
    "size": signal.size,
    "post_only": True,
    "time_in_force": "GTC"
}
```

---

### Failure Handling

If post-only rejects:

* retry once with improved price (inside spread)
* then cancel permanently
* DO NOT fallback to taker execution

---

### Acceptance Criteria

* taker fee exposure = 0%
* no FOK rejection errors in logs

---

## 1.3 Automated Settlement Engine (On-Chain Sweep)

### Add Module

```
/execution/settlement.py
```

### Function

```python
def claim_winnings(condition_id: str) -> str:
    tx = clob.redeem_positions(condition_id)
    return tx.hash
```

---

### Engine Hook

Inside `engine.tick()`:

```python
if trade.status == "WON" and config.live_mode:
    tx_hash = executor.claim_winnings(trade.condition_id)
    logger.info(f"Settlement TX: {tx_hash}")
```

---

### Acceptance Criteria

* No unresolved winning positions older than T+1 block
* USDCe fully realized on-chain

---

## 1.4 Security Hardening

* Remove all private keys from logs
* Ensure only API-based auth is used
* Block accidental env dumps in debug mode

---

# 2. MICROSTRUCTURE CANCEL ENGINE (CORE EDGE SYSTEM)

## 2.1 Market Data Upgrade

Subscribe:

```
wss://ws-subscriptions-clob.polymarket.com/ws/market
```

Enable:

```json
custom_feature_enabled: true
```

Required streams:

* best_bid_ask
* book
* price_change
* market_resolved

---

## 2.2 Micro-Price Model

```python
def micro_price(bid, ask, bid_size, ask_size):
    return (ask * bid_size + bid * ask_size) / (bid_size + ask_size)
```

---

## 2.3 Order Flow Imbalance (OBI)

Compute rolling 50-tick exponential decay:

```python
OBI = (bid_pressure - ask_pressure) / (bid_pressure + ask_pressure)
```

---

## 2.4 Cancel Engine (MANDATORY LOGIC)

### HARD RULES (no overrides)

| Condition                               | Action            |                        |                    |
| --------------------------------------- | ----------------- | ---------------------- | ------------------ |
|                                         | OBI               | > 0.6 against position | CANCEL IMMEDIATELY |
| microprice crosses quote                | CANCEL            |                        |                    |
| >3 level sweep in <500ms                | CANCEL ALL ORDERS |                        |                    |
| VPIN > 0.7 (60s window near resolution) | FLUSH BOOK        |                        |                    |
| ORDER_DELAYED spike                     | REDUCE EXPOSURE   |                        |                    |

---

### Execution Rule Priority

1. Risk kill-switches (highest)
2. Microprice protection
3. Inventory control
4. Signal updates

---

## 2.5 Expected Value Rule (Resting Orders)

```python
EV_rest = P_benign * spread_gain - P_toxic * adverse_move - cost
```

If EV_rest < 0:
→ cancel immediately

---

# 3. HOT PATH ARCHITECTURE (NO LLM IN EXECUTION)

## 3.1 Forbidden

* NO Groq API in trading loop
* NO LLM inference in signal path

---

## 3.2 Allowed Pipeline

```
WS Stream
 → Aho-Corasick Filter
 → VADER Sentiment
 → (optional) FinBERT ONNX async
 → Signal Score
 → Execution Engine
```

---

## 3.3 Latency Targets

| Component          | Max Latency |
| ------------------ | ----------- |
| Filter             | <1 µs       |
| VADER              | <0.1 ms     |
| FinBERT            | <15 ms      |
| Execution decision | <1 ms       |

---

# 4. ALPHA MODULES (NON-BLOCKING)

## 4.1 Binance Lead-Lag Signal

Trigger:

```
BTC/ETH move > 0.3% in 60s
```

Action:

* widen quotes OR pull inventory
* optionally cross spread if edge > fee

---

## 4.2 Whale Shadowing (ASYNC ONLY)

Inputs:

* Polygon pending tx
* CTF_EXCHANGE activity
* wallet scoring DB

Rules:

* NEVER block execution loop
* only adjust signal bias

---

# 5. THREADING & PERFORMANCE

## 5.1 Architecture Requirement

Split into 3 isolated loops:

```
[WS Ingest Thread]
[Signal Engine Thread]
[Execution Thread]
```

No shared blocking state without locks or queues.

---

## 5.2 GIL Mitigation Rule

* OBI calculation → separate process OR PEP 684 sub-interpreter
* Execution must remain single-thread deterministic

---

# 6. SYSTEM ACCEPTANCE TESTS

Must pass before deployment:

### Execution correctness

* [ ] fill price == ledger price
* [ ] no phantom PnL drift
* [ ] no duplicated trades

### Risk engine

* [ ] all kill-switches tested with simulated WS bursts
* [ ] cancel latency < 50ms reaction

### Settlement

* [ ] winning trades always trigger redeem flow
* [ ] tx hashes logged

### Execution mode

* [ ] 100% post-only orders
* [ ] 0 FOK usage

---

# 7. DESIGN PHILOSOPHY (IMPORTANT)

This system is NOT:

* a research simulator
* a sentiment bot
* a trading assistant

It is:

> A deterministic, event-driven market making + microstructure risk engine.

Every component must:

* be observable
* be replayable
* fail safely
* never hallucinate state

---

If you want next step, I can:

* turn this into **actual patch diff for your repo**
* or generate **Claude Code auto-refactor prompt**
* or design **v10 architecture diagram (execution-grade)**
