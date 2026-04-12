import time
from collections import deque
from datetime import datetime, timezone

from config import (
    Signal,
    Trade,
    RiskConfig,
    STARTING_BALANCE,
    BET_FRACTION,
    MIN_BET,
    MAX_BET,
    NEWS_POLL_INTERVAL,
    TICK_INTERVAL,
    MAX_BETS_PER_CYCLE,
    SUPPORTED_COINS,
    STRATEGY_VERSION,
)
from strategy_eval import evaluate_15m_mode
from market_fetcher import fetch_active_markets, find_updown_markets, fetch_resolved_market
from news_fetcher import fetch_google_news
from level_analyzer import analyze_updown_market
from arbitrage_analyzer import analyze_headlines
from logger import log_trade, read_trades, save_trades
from price_feed import get_price, get_prices_batch
from order_executor import OrderExecutor, PaperExecutor
from risk_manager import RiskManager
from trade_logger import log_trade_jsonl, log_settlement, log_risk_block


class Engine:
    def __init__(self, executor: OrderExecutor | None = None, risk_manager: RiskManager | None = None):
        self.executor = executor or PaperExecutor()
        self.risk_manager = risk_manager or RiskManager(RiskConfig())
        self.trades: list[Trade] = []
        self.traded_markets: set[str] = set()
        self.last_news_poll: float = time.time()
        self.running = False
        self.status = "Initializing"
        self.activity_log: deque[str] = deque(maxlen=30)
        self.markets = []
        self.updown_markets_found: list = []
        self.articles_found: list = []
        self.tick_count = 0
        self.wins = 0
        self.losses = 0
        self.mode_15m = evaluate_15m_mode([])  # default until first tick
        self._load_history()

    def _load_history(self):
        """Restore state from trades CSV."""
        self.balance = STARTING_BALANCE
        past_trades = read_trades()
        if not past_trades:
            return

        self.trades = past_trades
        for t in self.trades:
            self.traded_markets.add(t.market_slug)
            self.balance -= t.size
            if t.status == "won":
                self.balance += t.payout
                self.wins += 1
            elif t.status == "lost":
                self.losses += 1
        self._log(f"Loaded {len(self.trades)} trades ({self.wins}W/{self.losses}L), balance ${self.balance:.2f}")

    def _log(self, msg: str):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.activity_log.append(f"[{ts}] {msg}")

    @property
    def settled_count(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        if self.settled_count == 0:
            return 0.0
        return self.wins / self.settled_count

    @property
    def total_pnl(self) -> float:
        return sum(t.payout - t.size for t in self.trades if t.status != "pending")

    def bet_size(self, confidence: float, entry_price: float) -> float:
        """Size based on payout asymmetry, not just confidence.

        At high entry prices (0.85), one loss wipes ~6 wins because
        win profit is only 17.6% of the bet while a loss is 100%.
        This scales risk inversely with how many wins it takes to
        recover a single loss at a given entry price.
        """
        # Wins needed to recover one loss: entry / (1 - entry)
        # e.g., 0.85 → 5.67, 0.75 → 3.0, 0.65 → 1.86, 0.55 → 1.22
        wins_to_recover = entry_price / (1.0 - entry_price)

        # Bet less when recovery is harder. At 3 wins to recover → scale=1.0
        risk_scale = min(1.5, 3.0 / wins_to_recover)

        # Mild linear confidence scaling (NOT exponential)
        conf_scale = 0.6 + confidence * 0.8  # range [0.6, 1.4]

        fraction = BET_FRACTION * risk_scale * conf_scale
        raw = self.balance * fraction
        return max(MIN_BET, min(MAX_BET, raw))

    @property
    def pending_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.status == "pending"]

    def execute_paper_trade(self, signal: Signal) -> Trade:
        """Execute a trade through the configured executor.

        Named execute_paper_trade for backwards compatibility, but routes
        through self.executor (Paper, Simulation, or Live).
        """
        price_idx = 0 if signal.side == "YES" else 1
        entry_price = (
            signal.market.outcome_prices[price_idx]
            if len(signal.market.outcome_prices) > price_idx
            else 0.5
        )

        size = self.bet_size(signal.confidence, entry_price)

        # Route through executor
        result = self.executor.place_order(signal, size, entry_price)

        if not result.filled:
            self._log(f"  Order rejected: {result.reason}")
            return None

        # Detect market type from slug
        market_type = "15m" if "-15m-" in signal.market.slug else "5m"
        trade = Trade(
            timestamp=datetime.now(timezone.utc),
            market_slug=signal.market.slug,
            question=signal.market.question,
            strategy=signal.strategy,
            side=signal.side,
            entry_price=result.fill_price,
            size=result.fill_size,
            confidence=signal.confidence,
            reason=signal.reason,
            end_date=signal.market.end_date,
            market_type=market_type,
            strategy_version=STRATEGY_VERSION,
            fees=result.fees,
            fill_price=result.fill_price,
        )
        self.trades.append(trade)
        self.traded_markets.add(signal.market.slug)
        self.balance -= result.fill_size
        log_trade(trade)
        log_trade_jsonl(trade, result, executor_type=type(self.executor).__name__)
        return trade

    def _try_execute(self, signal: Signal) -> Trade | None:
        if signal.market.slug in self.traded_markets:
            self._log(f"  Skip (already traded): {signal.market.slug}")
            return None
        if self.balance < MIN_BET:
            self._log(f"  Skip (balance ${self.balance:.2f} < min ${MIN_BET})")
            return None

        # Risk manager gate
        size = self.bet_size(signal.confidence, signal.market.outcome_prices[0] if signal.side == "YES" else signal.market.outcome_prices[1] if len(signal.market.outcome_prices) > 1 else 0.5)
        risk_check = self.risk_manager.check_trade_allowed(signal, size, self.pending_trades)
        if not risk_check.allowed:
            self._log(f"  Risk blocked: {risk_check.reason}")
            log_risk_block(signal.market.slug, risk_check.reason)
            return None

        return self.execute_paper_trade(signal)

    def settle_trades(self, max_checks: int = 3):
        """Settle pending trades whose markets have been resolved on Polymarket.

        Queries the Gamma API for each pending trade's market to check
        if it has been resolved (outcome prices are exactly 1/0).
        Caps API calls per tick to avoid blocking the trading loop.
        """
        now = datetime.now(timezone.utc)
        settled = False
        api_calls = 0
        for trade in self.trades:
            if trade.status != "pending":
                continue
            if trade.end_date is not None:
                # Wait at least 10s past expiry for Gamma to index
                # Chainlink settles in ~1-5s, Gamma indexes in ~5-15s
                if (now - trade.end_date).total_seconds() < 10:
                    continue

            if api_calls >= max_checks:
                break  # remaining pending trades checked next tick
            api_calls += 1

            resolved = fetch_resolved_market(trade.market_slug)
            if resolved is None:
                # Not yet resolved — check again next tick
                # Give up after 10 minutes past expiry (if expiry is known)
                if trade.end_date and (now - trade.end_date).total_seconds() > 600:
                    trade.status = "lost"
                    trade.payout = 0.0
                    self.losses += 1
                    self.risk_manager.record_trade_result(trade)
                    self._log(f"LOSS (unresolved after 10m): {trade.market_slug}")
                    settled = True
                continue

            outcomes = resolved["outcomes"]
            prices = resolved["outcome_prices"]

            # Find which outcome won (price == 1.0)
            winning_idx = prices.index(1.0)
            winning_outcome = outcomes[winning_idx].strip().upper()

            # Map outcome labels to YES/NO for updown markets
            # "Up" = YES (first outcome), "Down" = NO (second outcome)
            if winning_outcome in ("UP", "YES"):
                winning_side = "YES"
            elif winning_outcome in ("DOWN", "NO"):
                winning_side = "NO"
            else:
                winning_side = "YES" if winning_idx == 0 else "NO"

            if trade.side == winning_side:
                trade.payout = (trade.size / trade.entry_price) - trade.fees
                trade.status = "won"
                self.balance += trade.payout
                self.wins += 1
                self._log(f"WIN: {trade.market_slug} +${trade.payout - trade.size:.2f}")
            else:
                trade.payout = 0.0
                trade.status = "lost"
                self.losses += 1
                self._log(f"LOSS: {trade.market_slug} -${trade.size:.2f}")
            self.risk_manager.record_trade_result(trade)
            log_settlement(trade)
            settled = True

        if settled:
            save_trades(self.trades)

    def check_updown_markets(self) -> list[Signal]:
        signals = []
        mode = getattr(self, "mode_15m", None)
        extra_edge = mode.edge_boost if mode and mode.tightened else 0.0
        extra_conf = mode.confidence_boost if mode and mode.tightened else 0.0
        for udm in self.updown_markets_found:
            # Apply adaptive tightening for 15m markets
            edge_boost = extra_edge if udm.interval_minutes == 15 else 0.0
            conf_boost = extra_conf if udm.interval_minutes == 15 else 0.0
            signal, reason = analyze_updown_market(udm, extra_min_edge=edge_boost)
            if signal:
                # Require higher confidence when tightened
                if conf_boost > 0 and signal.confidence < conf_boost:
                    self._log(f"  {udm.coin} skip: confidence {signal.confidence:.0%} < tightened min {conf_boost:.0%}")
                    continue
                signals.append(signal)
            else:
                self._log(f"  {reason}")
        signals.sort(key=lambda s: s.confidence, reverse=True)
        return signals

    def check_arbitrage(self) -> list[Signal]:
        articles = fetch_google_news()
        self.articles_found = articles or []
        if not articles:
            return []
        return analyze_headlines(articles, self.markets)

    def _warm_active_coins(self, coins: set[str]):
        """Warm price cache for active coins using a single batch API call."""
        get_prices_batch(coins)

    def tick(self) -> list[Trade]:
        tick_start = time.time()
        new_trades = []
        self.tick_count += 1

        # === CRITICAL PATH: fetch → warm active coins → analyze → trade ===
        # Market fetch first — this is the time-sensitive operation
        t0 = time.time()
        try:
            self.status = "Fetching markets"
            self.markets = fetch_active_markets()
            fetch_ms = (time.time() - t0) * 1000
            self._log(f"Fetched {len(self.markets)} markets ({fetch_ms:.0f}ms)")
        except Exception as e:
            self._log(f"Market fetch error: {e}")
            self.status = "Market fetch error"
            return new_trades

        # Find updown markets and warm prices ONLY for coins that need analysis
        self.status = "Checking updown markets"
        try:
            all_updown = find_updown_markets(self.markets)
            mode_15m = evaluate_15m_mode(self.trades)
            if not mode_15m.enabled:
                all_updown = [u for u in all_updown if u.interval_minutes != 15]
            self.mode_15m = mode_15m
            self.updown_markets_found = all_updown
            udm_5m = [u for u in self.updown_markets_found if u.interval_minutes == 5]
            udm_15m = [u for u in self.updown_markets_found if u.interval_minutes == 15]
            self._log(f"Found {len(udm_5m)} 5m + {len(udm_15m)} 15m updown markets | {mode_15m.reason}")

            # Warm prices for all active updown markets (both 5m and 15m)
            active_coins = {udm.coin for udm in self.updown_markets_found}
            if active_coins:
                t0 = time.time()
                self._warm_active_coins(active_coins)
                warm_ms = (time.time() - t0) * 1000
                if warm_ms > 2000:
                    self._log(f"  Price warming slow: {warm_ms:.0f}ms for {len(active_coins)} coins")

            signals = self.check_updown_markets()
            self._log(f"UpDown signals: {len(signals)}")
            cycle_bets = 0
            for signal in signals:
                self._log(f"  Signal: {signal.side} on {signal.market.slug} ({signal.confidence:.0%})")
                if cycle_bets >= MAX_BETS_PER_CYCLE:
                    self._log(f"  Skipped (max {MAX_BETS_PER_CYCLE} bets/cycle)")
                    break
                trade = self._try_execute(signal)
                if trade:
                    self._log(f"  TRADE: {trade.side} {trade.market_slug} @ ${trade.entry_price:.2f}, ${trade.size:.2f}")
                    new_trades.append(trade)
                    cycle_bets += 1
        except Exception as e:
            self._log(f"UpDown check error: {e}")
            self.status = "UpDown check error"

        # === NON-CRITICAL PATH: settle, news, background warming ===

        # Settle expired trades (cap per tick to avoid blocking)
        self.settle_trades()

        # Check news on interval
        now = time.time()
        secs_until_news = max(0, NEWS_POLL_INTERVAL - (now - self.last_news_poll))
        if secs_until_news == 0:
            self.last_news_poll = now
            self.status = "Checking news arbitrage"
            try:
                signals = self.check_arbitrage()
                self._log(f"Fetched {len(self.articles_found)} articles, {len(signals)} arb signals")
                for signal in signals:
                    self._log(f"  Arb signal: {signal.side} on {signal.market.slug}")
                    trade = self._try_execute(signal)
                    if trade:
                        self._log(f"  TRADE: {trade.side} {trade.market_slug}")
                        new_trades.append(trade)
            except Exception as e:
                self._log(f"Arbitrage error: {e}")
                self.status = "Arbitrage check error"
        else:
            self._log(f"Next news poll in {secs_until_news:.0f}s")

        # Background: warm remaining coins for momentum history (single batch call)
        try:
            remaining = set(SUPPORTED_COINS.keys()) - {udm.coin for udm in self.updown_markets_found}
            if remaining:
                get_prices_batch(remaining)
        except Exception:
            pass

        tick_ms = (time.time() - tick_start) * 1000
        if tick_ms > 5000:
            self._log(f"SLOW TICK: {tick_ms:.0f}ms")
        self.status = "Idle"
        return new_trades

    def _adaptive_interval(self) -> float:
        """Shorter tick interval when markets are approaching expiry."""
        if any(udm.seconds_to_close <= 30 for udm in self.updown_markets_found):
            return 5.0  # poll faster near expiry
        return TICK_INTERVAL

    def run(self, interval: float = TICK_INTERVAL):
        self.running = True
        while self.running:
            t0 = time.time()
            self.tick()
            elapsed = time.time() - t0
            sleep_time = max(0, self._adaptive_interval() - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def stop(self):
        self.running = False
