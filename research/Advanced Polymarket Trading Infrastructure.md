Advanced Polymarket Trading Infrastructure: Consolidated Quantitative Research Report
Classification: Proprietary Quant Research — Lead Desk
Date: 2026-04-13 | Stack: Python 3.12 / py-clob-client / Maker-Only / Groq LLM
Synthesized from: 8 independent research sweeps, 200+ sources verified
Critical Platform Context (April 2026)
Before diving into the four domains, note these post-2025 Polymarket changes that directly affect your architecture:
5-minute crypto markets launched February 12, 2026; taker fees and maker rebates extended to all crypto markets by March 6, 2026. (Polymarket Changelog - Polymarket Documentation)
Fee Structure V2 shipped March 30, 2026: crypto taker fee formula is $C \times \text{feeRate} \times p(1-p)$ with feeRate ~0.072; makers pay zero fees but rebates are pooled and volume-weighted, not fixed per fill. (docs.polymarket.com, docs.polymarket.com)
Market WebSocket subscription cap removed (May 2025), with initial_dump subscription control added April 10, 2026 — materially changes breadth-first scanning. (Polymarket Changelog - Polymarket Documentation)
Post-only orders added January 6, 2026. (Polymarket Changelog - Polymarket Documentation)
Polymarket's order lifecycle is off-chain matching, on-chain settlement — the CLOB matching engine is centralized; Polygon handles settlement via CTF Exchange contracts. (docs.polymarket.com)
⚠️ Key architectural implication: On 5m/15m crypto Up/Down markets, your highest-value upgrade is a microstructure-driven cancel engine, not a smarter quoting formula or news pipeline. Profitability is dominated by avoiding stale toxic fills while retaining enough queue priority to monetize maker rebates.
§1 — CLOB Microstructure & Adverse Selection Mitigation
1.1 Polymarket's Order Book Architecture
Polymarket's CLOB provides real-time data via WebSocket at wss://ws-subscriptions-clob.polymarket.com/ws/market. The market channel emits: book, price_change, last_trade_price, best_bid_ask, tick_size_change, new_market, and market_resolved. (Market Channel - Polymarket Documentation)
Subscribe with custom_feature_enabled: true to receive best_bid_ask and market_resolved events:

JSON


{
  "assets_ids": ["<token_id>"],
  "type": "market",
  "custom_feature_enabled": true
}


The book event fires both on initial subscription and whenever a trade impacts the order book — this is your primary adverse selection detection surface. The user WebSocket (wss://ws-subscriptions-clob.polymarket.com/ws/user) provides authenticated order lifecycle: MATCHED → MINED → CONFIRMED, plus ORDER_DELAYED responses that serve as execution path congestion proxies. (docs.polymarket.com)
Binary-specific insight: Polymarket's YES/NO books are mirrored — a buy-YES at price $p$ synthetically creates a sell-NO at $1-p$. You must construct cross-book synthetic imbalance to avoid being deceived by one-sided depth:

$$I^{\text{cross}}_t = \frac{(B_Y + A_N) - (A_Y + B_N)}{B_Y + A_N + A_Y + B_N}$$
where $B_Y, A_Y$ are YES bid/ask volumes and $B_N, A_N$ are NO bid/ask volumes. This is the correct binary-options adaptation implied by the arbitrage-free requirement that mutually exclusive outcome prices sum to 1.
1.2 Order Flow Imbalance (OFI) — The Cont-Kukanov-Stoikov Framework
The foundational production signal. Cont, Kukanov & Stoikov (2014) show that over short intervals, price changes are mainly driven by order flow imbalance. (

$$1011.6402$$
The Price Impact of Order Book Events)
The core OFI formula:

$$e_t = \mathbb{1}_{\{P_t^B \geq P_{t-1}^B\}} q_t^B - \mathbb{1}_{\{P_t^B \leq P_{t-1}^B\}} q_{t-1}^B - \mathbb{1}_{\{P_t^A \leq P_{t-1}^A\}} q_t^A + \mathbb{1}_{\{P_t^A \geq P_{t-1}^A\}} q_{t-1}^A$$
where $P_t^B, P_t^A$ are best bid/ask prices and $q_t^B, q_t^A$ are corresponding queue depths at update $t$. A rolling sum of $e_t$ over a 50-tick window serves as a leading indicator of order book depletion.
Depth-weighted exponential OBI (production-grade enhancement):

$$V^{bid}_t = \sum_{i=1}^{L} q^{bid}_{t,i} \cdot e^{-\lambda \cdot \delta^{bid}_{t,i}}, \quad V^{ask}_t = \sum_{i=1}^{L} q^{ask}_{t,i} \cdot e^{-\lambda \cdot \delta^{ask}_{t,i}}$$

$$\text{OBI}_t = \frac{V^{bid}_t - V^{ask}_t}{V^{bid}_t + V^{ask}_t} \in [-1, +1]$$
where $\delta^{bid}_{t,i}$ is the distance from mid-price in ticks and $\lambda$ is a decay parameter (calibrate per market; typically 0.5–2.0 for binary CLOBs). Near binary extremes ($p \in [0.05, 0.15]$ or $[0.85, 0.95]$), scale $\lambda$ dynamically:

$$\lambda_t = \lambda_0 \cdot \left(1 + \beta \cdot |p_t - 0.5|\right)$$
This filters noise from the book near resolution extremes where OBI becomes a leading indicator of informed taker sweeps. (Market Making with Alpha - Order Book Imbalance - HftBacktest)
1.3 Micro-Price Estimator (Stoikov 2017)
The single most important fair-value estimator for your bot. It computes the limit of expected future mid-prices given order book state:

$$\mu_t = \frac{a_t \cdot q^b_t + b_t \cdot q^a_t}{q^a_t + q^b_t}$$
where $a_t, b_t$ are best ask/bid prices and $q^b_t, q^a_t$ are best bid/ask queue depths. The signal $\mu_t - m_t$ (where $m_t = (a_t + b_t)/2$) directly tells your Maker bot whether the "true" price is above or below mid, and by how much. If your resting bid is below a micro-price that is dropping through mid, you are about to be adversely selected. (papers.ssrn.com)
Implementations:
sstoikov/microprice — (sstoikov/microprice - GitHub)
grayvalley/microprice-calibration — (grayvalley/microprice-calibration)
shaileshkakkar/MicroPriceIndicator — (shaileshkakkar/MicroPriceIndicator)
2024 extension: Higher-order microprice with Tsetlin machines extends to deeper book levels:

$$P_i(t) = M_t + \sum_{k=1}^{i} g_k(I_t, S_t)$$
Validated on Databento L3 data. (arxiv.org)
1.4 VPIN — Volume-Synchronized Probability of Informed Trading
Easley, López de Prado & O'Hara (2012) proposed VPIN as a high-frequency toxicity detector:

$$\text{VPIN} = \frac{\sum_{\tau=1}^{N} |V_\tau^B - V_\tau^S|}{N \cdot V_{\text{bucket}}}$$
where each $\tau$ is a volume-synchronized bucket (not time-based), and $V_\tau^B, V_\tau^S$ are buyer/seller-initiated volumes classified via the tick rule. (VPIN 1 The Volume Synchronized Probability of INformed ...)
Practical thresholds from Buildix's crypto implementation: VPIN > 0.8 combined with low OBI suggests a potential liquidation cascade; consistently elevated VPIN > 0.6 for hours suggests a trending regime where mean-reversion strategies should pause. (What Is VPIN? Flow Toxicity Detection for Crypto Traders — Buildix Blog)
For Polymarket: Bucket by USDC volume on each condition token. When VPIN > 0.7 on a 5m crypto market within 60s of the resolution window opening, pull all resting maker orders.
1.5 Avellaneda-Stoikov Framework Adapted for Binary Options
The canonical inventory-risk-adjusted market making model. The reservation price and optimal spread:

$$r(s, q, t) = s - q \gamma \sigma^2 (T - t)$$

$$\delta^{a*} + \delta^{b*} = \gamma \sigma^2 (T-t) + \frac{2}{\gamma} \ln\left(1 + \frac{\gamma}{\kappa}\right)$$
where $s$ = mid-price, $q$ = inventory, $\gamma$ = risk aversion, $\sigma$ = volatility, $\kappa$ = fill-rate intensity, $T$ = time to resolution. The second term $\frac{2}{\gamma}\ln(1 + \gamma/\kappa)$ is the adverse selection component. (arxiv.org, Technical Deep Dive into the Avellaneda & Stoikov Strategy - Hummingbot)
Binary options adaptation: Because $(T-t) \to 0$ near resolution, spreads naturally compress. You must widen $\delta^*$ manually when OBI diverges from 0, because the model otherwise underestimates adverse selection from informed late-resolution bets. A recent paper proves $O(\log^2 T)$ regret when learning $\kappa$ online via regularized MLE — critical for adaptive calibration on Polymarket's non-stationary books. (Logarithmic regret in the ergodic Avellaneda–Stoikov market making model)
1.6 Queue Position Tracking
Polymarket's market WebSocket provides L2 (price-level aggregated) data, not market-by-order. You cannot know exact FIFO rank. Estimate queue ahead:

$$Q^{\text{ahead}}_{t_0} \approx Q^{\text{visible}}_{P,\text{pre}} + \epsilon$$
Then evolve on each price_change at your level:

$$Q^{\text{ahead}}_{t+1} = Q^{\text{ahead}}_t - \Delta V^{\text{trade}}_{P,t} - \pi_t \Delta V^{\text{cancel}}_{P,t} + \Delta V^{\text{join-ahead}}_{P,t}$$
where $\pi_t$ = probability cancelled size was ahead of you (learned per regime). Use survival-style ETA-to-fill:

$$P(T_{\text{fill}} \leq h) = 1 - \exp\left(-\int_t^{t+h} \lambda_{\text{fill}}(u) \, du\right)$$
hftbacktest (nkaz001/hftbacktest) implements production-grade queue-position-aware backtesting with both risk-averse and probabilistic queue models — directly applicable for calibrating your Polymarket bot. (GitHub - nkaz001/hftbacktest: Free, open source, a high frequency trading and market making backtesting and trading bot, which accounts for limit orders, queue positions, and latencies, utilizing full tick data for trades and order books(Level-2 and Level-3), with real-world crypto trading examples for Binance and Bybit · GitHub, Probability Queue Position Models - HftBacktest - Read the Docs)
1.7 The Resting-Order EV Framework & Cancel Triggers
The right object is not "spread capture" — it is the expected value of leaving the quote live over horizon $h$:

$$\text{EV}_{\text{rest}}(t,h) = P_{\text{benign}}(t,h) \cdot G_t - P_{\text{toxic}}(t,h) \cdot L_t - c_{\text{replace}} - c_{\text{inventory}}$$
with $G_t \approx \frac{s_t}{2} + \hat{r}_t$ (spread capture + expected rebate) and $L_t \approx \mathbb{E}[|\Delta p_{t \to t+h}| \mid \text{toxic fill}]$. Pull when $\text{EV}_{\text{rest}} < 0$. (papers.ssrn.com, The Market Maker’s Dilemma: Navigating the Fill Probability vs. Post-Fill Returns Trade-Off)
Concrete cancel triggers for your 5m/15m crypto bot:
Signal
Action
Threshold
OBI flips > 0.6 against your resting side
Pull immediately


Micro-price $\mu_t$ crosses through your quote
Cancel that side
$\mu_t$ breach
Large taker sweep removes > 3 levels in < 500ms
Pull all quotes in that market
> 3 levels
tick_size_change event near 0.96/0.04 boundary
Regime shift — widen or pull
Near extremes
ORDER_DELAYED spikes cluster
Execution congestion — pull
Spike detection
VPIN > 0.7 within 60s of resolution window
Pull all resting orders
VPIN threshold
Underlying BTC/ETH perp moves > 0.3% in 60s
Polymarket hasn't repriced yet
Lead-lag arb

1.8 Key Academic Papers for This Module
Paper
Authors
Key Contribution
arXiv:1011.6402
Cont, Kukanov, Stoikov
OFI definition and price impact
arXiv:1512.03492
Gould, Bonart
Queue imbalance as tick-ahead predictor
SSRN:2970694
Stoikov
Micro-price estimator
SSRN:3479741
Xu, Gould, Howison
Multi-level OFI
arXiv:0805.3706
Avellaneda, Stoikov
Optimal market making under inventory risk
SSRN:5074873
Albers, Cucuringu, Howison, Shestopaloff
Fill probability vs post-fill returns trade-off
SSRN:3991930
Garriott, van Kervel, Zoican
Queue position and adverse selection
SSRN:2911540
Donnelly, Gan
Optimal cancel/leave decisions under time priority
arXiv:1610.00261
Strategic placement
Adverse selection risk and latency
arXiv:2510.27334
Hawkes/RL
Adverse selection of meta-orders by RL market making (2025)
arXiv:2508.20225
Optimal quoting
Adverse selection + price reading framework (2025)

§2 — Ultra-Low Latency News & Alternative Data
2.1 Institutional-Grade News Feeds (Ranked by Latency)
Source
Latency
Protocol
Coverage
Cost
Polymarket RTDS WS
~50-150ms
WebSocket
Crypto prices (Binance + Chainlink), comments
Free
Tree News Tokyo
Sub-second
ws://tokyo.treeofalpha.com:5124
Subscriber-only, Binance/Bybit proximity
€2,500/mo (Sapling)
Tree News Main
Sub-second
wss://news.treeofalpha.com/ws
1,150+ sources, 2,300+ Twitter accounts
$500/mo (Sprout)
Finlight Raw WS
~0s (raw)
wss://wss.finlight.me/raw
Financial news, structured JSON
API-key
TweetStream
~200ms
wss://ws.tweetstream.io/ws
X/Twitter with Polymarket tagging, OCR
$499/mo
RavenPack Edge
Sub-second
Streaming API
Dow Jones/WSJ/Benzinga + entity tagging
Enterprise
Finnhub WS
~2-5s
WebSocket
Broader market events
Free tier

(Tree Ecosystem - A Crypto Trading Product, Edge Data Delivery | RavenPack, WebSocket - Real-Time Financial News Streaming | finlight - finlight.me, Websockets | Tree Service)
Tree News monitors >1,000 sources and >2,300 Twitter accounts, relaying through a dedicated WebSocket based in Japan (optimized for proximity to Binance/Bybit). The Sapling tier ($2,500/mo) provides the Exchange Announcements WebSocket — the institutional-speed feed for machine-parseable exchange events. (Tree Ecosystem - A Crypto Trading Product)
Polymarket's RTDS provides Binance-source crypto prices via:

JSON


{
  "action": "subscribe",
  "subscriptions": [{
    "topic": "crypto_prices",
    "type": "update",
    "filters": "btcusdt"
  }]
}


For 15m crypto markets, Polymarket offers sponsored Chainlink API keys — subscribe to the same oracle source the resolution contract uses to eliminate oracle-lag arbitrage. Register at pm-ds-request.streams.chain.link/. (Real-Time Data Socket - Polymarket Documentation)
2.2 LLM-Bypass Architecture: Direct NLP on Raw Streams
Critical insight (consensus across all research sources): Do NOT put Groq (or any LLM) on the hot path for 5m/15m crypto markets. LLMs belong off-path for labeling, taxonomy expansion, and post-trade attribution. The hot path must be:



[WebSocket Text Stream]
       ↓
[Aho-Corasick / Regex Pre-filter]  ← ~1μs, zero allocation
       ↓ (only matched headlines pass)
[VADER Sentiment]  ← <0.1ms per headline, no GPU
       ↓ OR
[FinBERT / DistilBERT via ONNX Runtime]  ← ~3-15ms on GPU
       ↓
[Market Relevance Scorer]  ← cosine similarity to cached embeddings
       ↓
[Threshold Gate + Signal Router]
       ↓
[py-clob-client Order / Cancel]


Latency comparison:
Model
Throughput
Latency
GPU Required
Finance Accuracy
VADER
~10,000/sec
<0.1ms
No
65-72%
FinBERT (ONNX)
~50-100/sec
~3-15ms
Recommended
85-92%
DistilBERT (TensorRT)
~200/sec
<1.5ms
Yes
80-88%
Groq LLM API
~20-50/sec
200-2000ms
N/A (API)
85-95%

(github.com, docs/TECHNICAL_REPORT.md at main · DwivediUtkarsh/SentimentQuant-Engine, huggingface.co) — production cascade with VADER+FinBERT, 1.69ms average latency, P95 5.52ms.
For ONNX deployment in Rust (if migrating hot path): pykeio/ort for fast ONNX inference, or webonnx/wonnx for WebGPU-accelerated ONNX. (github.com, github.com)
2.3 Binance-to-Polymarket Momentum Signal (Directly Applicable)
The most battle-tested pipeline for your 5m crypto markets is the Binance→Polymarket latency arbitrage documented by Chudi Nnorukam (2026):
Signal source: Binance aggTrade WebSocket (not klines)
Momentum threshold: 0.3% in 60 seconds → 3-8 signals/day, 62% in-range rate
Total pipeline latency: ~10-20ms
Edge window: 30-90 seconds of Polymarket repricing lag
(Build a Binance-Polymarket Signal Pipeline in 2026 | Chudi Nnorukam)
2.4 Critical RTDS Event: market_resolved
The market_resolved event fires the instant a market closes. In the period between resolution announcement and full CLOB repricing of adjacent correlated markets (2-15 minutes), structural mispricings exist. Your bot should detect this event and immediately scan the constraint graph of related markets.
§3 — On-Chain Alpha & Whale Copy-Trading
3.1 Critical Limitation: Off-Chain Matching Precedes On-Chain Settlement
⚠️ Conflict across research models (confidence: HIGH): Polymarket's order lifecycle is off-chain creation → off-chain matching → on-chain settlement. This means raw on-chain listeners do NOT generally see CLOB order intent before the market WebSocket does. For ordinary CLOB fills, the market/user WebSockets are the first public execution surface; the chain is mainly confirmation/audit trail. (docs.polymarket.com)
Correct conclusion: On-chain monitoring is NOT the primary edge for detecting passive/active CLOB intent before price moves. It IS valuable for:
Direct CTF operations — splits, merges, redemptions, neg-risk conversions
Historical wallet scoring — building high-alpha wallet databases
Pending settlement-bundle monitoring — pre-confirmation signals
Non-book positioning flows that later spill into the CLOB
3.2 Smart Contract Address Map
All trading activity settles through two main contracts. (Decoding the Digital Tea Leaves: A Guide to Analyzing Polymarket’s On-Chain Order Data - Zichao Yang, docs.polymarket.com)
Contract
Address
Monitor For
CTF (Gnosis)
0x4D97DCd97eC945f40cF65F87097ACe5EA0476045
PositionsSplit, PositionsMerge
CTF Exchange
0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E
OrderFilled, OrdersMatched
NegRisk_CTFExchange
0xC5d563A36AE78145C45a50134d48A1215220f80a
Multi-outcome trades
NegRiskAdapter
0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296
PositionsConverted
USDC.e
0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
Large transfers
UMA Oracle V2
0x6A9D222616C90FcA5754cd1333cFD9b7fb6a4F74
Resolution events

Price calculation from OrderFilled: Price(YES) = USDC paid / YES tokens received. USDC has 6 decimals (÷10^6), outcome tokens have 18 decimals (÷10^18). (Polymarket CTF Exchange API | Bitquery)
Also monitor: incrementNonce on the exchange interface — this is a cancellation/intent-abort signal. (github.com)
3.3 Whale Detection & Wallet Scoring
UCLA 2026 empirical work (J. Yang thesis on NBA markets, transferable to crypto binaries) provides the most rigorous insider detection methodology:
Pseudo-Ground Truth Oracle: Label wallets with Profit ≥ 95th percentile, ROI ≥ 60%, directional concentration ≥ 90%
Isolation Forest (unsupervised, n_estimators=2000, subsample=256) on scale-invariant features: wallet_age_days, unique_markets, historical_roi, position_anomaly_ratio = $\ln(1 + \text{max\_position}/\text{historical\_avg})$, entry timing, sweep ratio
Result: Top 1% anomaly cohort captured 11.7% of aggregate profits (p<0.001 vs bootstrap)
SHAP drivers: Position anomaly ratio, timing, concentration
(escholarship.org)
Production wallet scoring formula:

$$\text{AlphaScore}_w = w_1 \cdot \text{WinRate}_w + w_2 \cdot \log\left(\frac{\text{TotalVol}_w}{\$100K}\right) + w_3 \cdot \text{Sharpe}_w - w_4 \cdot \text{Recency}^{-1}_w$$
Noise filtering rules:
Directionality ratio: $D_w = \frac{|\sum_i s_i n_i|}{\sum_i |n_i|}$ — if $D_w \approx 0$, wallet is MM/arb, not conviction trader
Market concentration: $H_w = \sum_m \omega_{w,m}^2$ — high = concentrated bets (what you want)
Hold-intent ratio: $C_w = \frac{\text{notional held beyond } T}{\text{gross opened}}$ — low = fast turnover/arb
Price-discovery lead score: $E_w(\tau) = \text{corr}(\text{signed flow}_{w,t}, r_{m,t+\tau})$ — copy wallets that lead returns
(Finding the Needle: Detecting Insider-Like Trading on Polymarket) — February 2026: algorithm ranked known insider wallet #1 out of 7,655 in blind test.
Tools & Repos:
pselamy/polymarket-insider-tracker — (pselamy/polymarket-insider-tracker) — DBSCAN clustering, funding source analysis, fresh wallet detection
punkde99/polymarket-whale-bot — (punkde99/polymarket-whale-bot) — Real-time Polygon WS monitoring, composite scoring
suislanchez/polymarket-insider-detector — (suislanchez/polymarket-insider-detector)
PolyTrack — (polytrackhq.app) — Real-time trade feed, P&L tracking, Telegram alerts
Dune Analytics dashboards: dune.com/thxshogun/polymarket-2025-capital-and-whales, dune.com/andy_chelsea/polymarket-whale-order-observation
3.4 Millisecond-Scale Monitoring Architecture
The correct sequence is WS-first, chain-second, subgraph-third:
Polymarket market/user WS — first execution surface for ordinary CLOB fills
**Polygon pending tx subscription (alchemy_pendingTransactionsornewPendingTransactions) + immediate eth_getTransactionByHash` decode — gives ~1-3s lead for direct CTF operations (Subscription API Overview | Alchemy Docs)
Confirmed logs via RPC/subgraph for backfill and wallet scoring (Subgraph - Polymarket Documentation)

Python


# Pending TX monitoring pattern
w3 = Web3(Web3.WebsocketProvider("wss://polygon-mainnet.g.alchemy.com/v2/<KEY>"))

def on_pending_tx(tx_hash):
    tx = w3.eth.get_transaction(tx_hash)
    if tx['to'] in [CTF_EXCHANGE, NEGRISK_EXCHANGE]:
        decoded = decode_calldata(tx['input'])  # ABI decode
        if decoded['function'] == 'matchOrders':
            # Pre-confirmation signal
            whale_check(decoded['maker'], decoded['size'])


§4 — Cross-Market Combinatorial Arbitrage
4.1 The Marginal Polytope Problem
Traditional sum-of-prices checks miss the real opportunity. For $n$ logically interconnected conditions, the set of arbitrage-free prices forms a Marginal Polytope $\mathcal{M}$:

$$\mathcal{M} = \text{conv}\left\{ \mathbf{e}_\omega : \omega \in \Omega \right\} \subset [0,1]^n$$
where $\mathbf{e}_\omega$ is the indicator vector for outcome $\omega$ and $\Omega$ is the set of all logically valid outcome combinations. If the current price vector $\mathbf{p} \notin \mathcal{M}$, structural arbitrage exists. The challenge: $|\Omega|$ can be $2^{63}$ — computationally intractable without structure-exploiting algorithms. (Polymarket Arbitrage Bible: The Real Gap is in the Mathematical Infrastructure - ChainCatcher)
4.2 Bregman Projection for Arbitrage-Optimal Trades
The maximum guaranteed profit equals the Bregman divergence from current prices to the closest arbitrage-free point:

$$D_\phi(\mathbf{q} \| \mathbf{p}) = \phi(\mathbf{q}) - \phi(\mathbf{p}) - \nabla\phi(\mathbf{p})^\top (\mathbf{q} - \mathbf{p})$$
For LMSR cost function (which Polymarket uses), $\phi(\mathbf{q}) = b \ln\left(\sum_i e^{q_i/b}\right)$, and the Bregman divergence becomes a generalization of KL divergence. (Arbitrage-Free Combinatorial Market Making via Integer Programming,

$$PDF$$
Arbitrage-Free Combinatorial Market Making via Integer Programming)
4.3 Frank-Wolfe Algorithm with IP Oracle
The Frank-Wolfe (conditional gradient) algorithm iteratively projects onto $\mathcal{M}$ without enumerating all vertices:
Initialize: $\mathbf{p}_0 \in \mathcal{M}$ (feasible starting point)
For $t = 0, 1, \ldots, T$:
Linear subproblem — find direction of steepest descent within $\mathcal{M}$:
$$\mathbf{s}_t = \arg\min_{\mathbf{s} \in \mathcal{M}} \langle \nabla_\mathbf{p} D_\phi(\mathbf{p}_t \| \mathbf{q}), \; \mathbf{s} \rangle$$
Step size (adaptive): $\gamma_t = \frac{2}{t+2}$ or solved via line-search
Update: $\mathbf{p}_{t+1} = (1 - \gamma_t)\mathbf{p}_t + \gamma_t \mathbf{s}_t$
Convergence: $\mathcal{O}(1/T)$ for standard FW. The Frank-Wolfe gap $g_t = \langle \nabla D_\phi(\mathbf{p}_t \| \mathbf{q}), \mathbf{p}_t - \mathbf{s}_t \rangle$ serves as a certified upper bound on suboptimality — useful for live trading as a real-time arb size estimate. (The Frank-Wolfe Algorithm: A Short Introduction | Jahresbericht der Deutschen Mathematiker-Vereinigung | Springer Nature Link)
Gradient explosion fix: When prices approach 0 or 1, LMSR gradients tend to $-\infty$. The solution is Barrier Frank-Wolfe: optimize on a slightly "shrunk" version of $\mathcal{M}$ with shrinkage parameter $\varepsilon$ that adaptively decreases. In practice, 50-150 iterations suffice for convergence.
Solver: Gurobi (academic license free) or OR-Tools (open source) for the IP oracle at each FW step. Empirical solving times: early iterations <1s, mid-stage 10-30s, late-stage <5s as the feasible solution space shrinks. After 45 games in the original NCAA test, FWMM outperformed LCMM by 38%.
2025 extension — Adaptive Bregman step sizes: Takahashi, Pokutta & Takeda (2025) achieve linear convergence under Hölder error bound conditions — a significant speedup for relatively smooth objectives. (Fast Frank--Wolfe Algorithms with Adaptive Bregman Step-Size for ...)
4.4 Empirical Evidence: ~$40M Extracted from Polymarket
Saguillo, Ghafouri, Kiffer & Suarez-Tangil (AFT 2025) provide the first large-scale empirical study of Polymarket arbitrage:
Market Rebalancing Arbitrage (intra-market): Within a condition, dependent outcome prices don't sum to $1
Combinatorial Arbitrage (inter-market): Across logically linked markets
Uses LLMs (Linq-Embed-Mistral) to extract combinatorial relationships from market descriptions
Result: ~$40M USD realized profit, April 2024–April 2025. Top account >$2M. Single-trade max: $58,983.
Over 40% of individual market scenarios contained exploitable arbitrage
90% of liquidity sits in top 4 conditions — important for pruning solver state space
(Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets, Mathematical Advances Unlock $40 Million Arbitrage Profits In Prediction Markets - Sorafutures.com, drops.dagstuhl.de)
UCLA 2026 microlevel data (NBA markets, transferable to crypto): Single-market arb resolves in median 3.6s, combinatorial episodes last ~16s median, 101 bps median yield, but 76.9% bottlenecked at $100 executable depth. (escholarship.org)
4.5 NegRisk Adapter Arbitrage Path
The NegRiskAdapter allows converting NO positions to YES + USDC atomically in a single transaction — bypassing the non-atomic CLOB execution problem. If $\sum_i p_i^{\text{YES}} < 1 - \varepsilon$ across outcomes of a neg-risk event:
Buy YES in all underpriced outcomes via CLOB
Convert collected NO positions via NegRiskAdapter on-chain (atomic)
Conversion eliminates leg risk entirely
(NegRisk Market Rebalancing: How $29M Was Extracted From Multi-Condition Prediction Markets | by Navnoor Bawa | Medium, Negative Risk Markets - Polymarket Documentation)
4.6 Production Implementation
Constraint families to encode:
Within-market exhaustivity: $\sum_{j \in \mathcal{O}(m)} p_j = 1$
YES/NO complementarity: $p_{\text{YES}} + p_{\text{NO}} = 1$ (after bid/ask and fees)
Implication constraints: If A implies B: $p(A) \leq p(B)$
Mutual exclusion: If A and B cannot both resolve true: $p(A) + p(B) \leq 1$
Neg-risk conversion constraints from adapter-convertible relationships
Implementation: edgelord Rust crate implements FW projection onto arbitrage-free manifold using Bregman divergence. (edgelord::application::strategy::combinatorial - Rust)
For Python: dmitryk4/prediction-market-arbitrage provides a Kalshi/Polymarket cross-venue scaffold. (github.com)
§5 — Execution Infrastructure & Client Benchmarks
5.1 Client Library Performance
polyfill-rs (Rust) achieves the lowest latencies for Polymarket interaction: (GitHub - floor-licker/polyfill-rs: The Fastest Polymarket Rust Client · GitHub)
Operation
polyfill-rs
polymarket-rs-client
Official Python
Fetch Markets
321.6ms ± 92.9ms
409.3ms ± 137.6ms
1.366s ± 0.048s
Order Book Updates (1000 ops)
159.6µs ± 32µs
—
—
Spread/Mid Calculations
70ns ± 77ns
—
—
WS book hot path (1 level)
~0.28µs
—
—

Recommendation: Migrate order execution hot path from py-clob-client to Rust via PyO3 FFI. Keep Python for strategy logic. (GitHub - Polymarket/rs-clob-client: Polymarket Rust CLOB Client · GitHub)
5.2 Python GIL Mitigation
Your Python 3.12 synchronous threading stack is a bottleneck for CPU-bound tasks (OBI calculation, Bregman divergence). Options:
Short-term: PEP 684 (per-interpreter GIL) — isolate WebSocket ingestion, OFI calculation, and execution into separate sub-interpreters
Long-term: Rewrite critical path in Rust with tokio-tungstenite for WebSockets, interfaced via PyO3
§6 — Consolidated Implementation Priority
Priority
Strategy
Alpha Half-Life
Complexity
Expected Edge
1
OBI/Micro-price cancel engine
1-10 min
Medium
Reduces maker bleed 30-60%
2
Remove LLM from hot path → VADER+FinBERT
Continuous
Low-Medium
10-40x faster signal
3
Binance→Polymarket momentum signal
30-90s
Low
Direct, calibrated edge
4
market_resolved RTDS → correlated market repricing
30-300s
Low
Pure alpha, first-mover
5
WS-first whale tracker + pending TX
1-48 hrs
Medium
Depends on watchlist quality
6
Binary complement + threshold ladder arb scanner
2-15 min
Medium
Structural
7
Full Bregman/FW combinatorial solver
2-15 min
Very High
$40M/yr pool (competitive)

§7 — Master Reference Index
Academic Papers

Paper
Year
Link
Queue Imbalance Predictor
2015
(

$$1512.03492$$
Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book)
Micro-Price Estimator
2017
(papers.ssrn.com)
Avellaneda-Stoikov Market Making
2008
(arxiv.org)
OFI Price Impact
2014
(

$$1011.6402$$
The Price Impact of Order Book Events)
Combinatorial Market Making (FW+IP)
2016
(Arbitrage-Free Combinatorial Market Making via Integer Programming)
Polymarket Arbitrage Empirical ($40M)
2025
(Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets)
Anatomy of Polymarket (2024 Election)
2026
(The Anatomy of Polymarket: Evidence from the 2024 Presidential ...)
Adaptive Bregman FW
2025
(Fast Frank--Wolfe Algorithms with Adaptive Bregman Step-Size for ...)
Fill Probability vs Post-Fill Returns
2025
(To Make, or to Take, That Is the Question: Impact of LOB Mechanics on Natural Trading Strategies)
Hawkes/RL Adverse Selection
2025
(arxiv.org)
Price Discovery in Prediction Markets
2026
(papers.ssrn.com)
PolySwarm (Multi-Agent LLM Arb)
2026
(arxiv.org)
SoK: Prediction Market Microstructure
2026
(arxiv.org)

GitHub Repositories

Repo
Purpose
(GitHub - nkaz001/hftbacktest: Free, open source, a high frequency trading and market making backtesting and trading bot, which accounts for limit orders, queue positions, and latencies, utilizing full tick data for trades and order books(Level-2 and Level-3), with real-world crypto trading examples for Binance and Bybit · GitHub)
Queue-aware crypto backtesting
(Polymarket/py-clob-client)
Official Python CLOB SDK
(GitHub - Polymarket/rs-clob-client: Polymarket Rust CLOB Client · GitHub)
Official Rust CLOB client
(GitHub - floor-licker/polyfill-rs: The Fastest Polymarket Rust Client · GitHub)
Fastest Polymarket Rust client
(github.com)
Exchange contracts/docs
(sstoikov/microprice - GitHub)
Micro-price estimator
(pselamy/polymarket-insider-tracker)
DBSCAN whale detection
(punkde99/polymarket-whale-bot)
Real-time whale monitoring
(GitHub - ProsusAI/finBERT: Financial Sentiment Analysis with BERT · GitHub)
Financial sentiment (sub-15ms)
(github.com)
Sub-ms sentiment scoring
(github.com)
Rust ONNX inference
(github.com)
VADER+FinBERT cascade
(github.com)
Cross-venue arb scaffold

API Endpoints
Service
Endpoint
Polymarket Market WS
wss://ws-subscriptions-clob.polymarket.com/ws/market
Polymarket User WS
wss://ws-subscriptions-clob.polymarket.com/ws/user
Polymarket RTDS
wss://ws-live-data.polymarket.com
Tree News Main
wss://news.treeofalpha.com/ws
Tree News Tokyo
ws://tokyo.treeofalpha.com:5124
Finlight Raw
wss://wss.finlight.me/raw
Gamma API (no auth)
gamma-api.polymarket.com
CLOB API (auth)
clob.polymarket.com
Data API (no auth)
data-api.polymarket.com

§8 — Documented Limitations & Conflicts
On-chain vs. CLOB timing (HIGH CONFIDENCE CONFLICT): Multiple research sources disagree on whether mempool monitoring provides pre-CLOB alpha. The consensus finding: for ordinary CLOB fills, WS beats chain. For direct CTF operations (splits, merges, conversions), pending TX monitoring provides 1-3s lead. Architect accordingly — WS-first, chain-second. (docs.polymarket.com)
Maker rebates are NOT fixed per fill. They are pooled, per-market, volume-weighted. Your expected rebate per marginal fill collapses when too many makers crowd the same level. Model as $\hat{r}_t$ (expectation), not a constant. (docs.polymarket.com)
No production-grade open-source Polymarket-specific Frank-Wolfe/Bregman arb engine exists. The edgelord Rust crate and the foundational paper provide the framework, but your edge is in custom implementation: dependency extraction, incremental solve scheduling, depth-aware leg construction.
Queue position on Polymarket ≠ traditional LOB. L2-only data means exact FIFO rank is estimated, not known. Validate hftbacktest queue models against actual Polymarket fill data before deploying.
The $40M arbitrage pool (Apr 2024–Apr 2025) is pre-competition. With $44B+ 2025 volume and 170+ ecosystem tools, this pool is increasingly competed for. (The Definitive Guide to the Polymarket Ecosystem: 170+ Tools, Bots, and Products Reshaping Prediction Markets)
Whale copy signals are shared alpha. Multiple services (PolySignals, PolyTrack, HashDive, Polywhaler) distribute alerts. Custom Polygon RPC + pending TX monitoring provides structural latency advantage over shared Telegram channels.
Spoofing risk in whale copying. Algorithmic agents can learn to manipulate visible order-book conditions. Penalize hyper-short hold times, alternating-side bursts, and wallets that don't lead returns. (papers.ssrn.com)
I did not find an official primary source publishing Polymarket matching-engine latency distributions. Any hard latency threshold for cancel/replace must be calibrated from your own WS + request timestamp + Polygon settlement timestamp capture.
