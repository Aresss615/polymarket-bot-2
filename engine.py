import time
from collections import deque
from datetime import datetime, timezone

from config import (
    BET_FRACTION,
    MAX_BET,
    MAX_BETS_PER_CYCLE,
    MIN_BET,
    NEWS_POLL_INTERVAL,
    OpenOrder,
    RiskConfig,
    STARTING_BALANCE,
    STRATEGY_VERSION,
    SUPPORTED_COINS,
    TICK_INTERVAL,
    Signal,
    Trade,
)
from strategy_eval import evaluate_15m_mode
from market_fetcher import fetch_active_markets, fetch_resolved_market, find_updown_markets
from news_fetcher import fetch_google_news
from level_analyzer import analyze_updown_market
from arbitrage_analyzer import analyze_headlines
from logger import read_open_orders, read_trades, save_open_orders, save_trades
from price_feed import get_prices_batch
from order_executor import OrderExecutor, PaperExecutor
from risk_manager import RiskManager
from trade_logger import log_order_event, log_risk_block, log_settlement, log_trade_jsonl


class Engine:
    def __init__(self, executor: OrderExecutor | None = None, risk_manager: RiskManager | None = None):
        self.executor = executor or PaperExecutor()
        self.risk_manager = risk_manager or RiskManager(RiskConfig())
        self.trades: list[Trade] = []
        self.open_orders: list[OpenOrder] = []
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
        self.risk_manager.observe_account_equity(self.account_equity)
        if self.open_orders:
            self._reconcile_open_orders()

    def _load_history(self):
        """Restore confirmed positions and any persisted open live orders."""
        self.balance = STARTING_BALANCE
        self.trades = read_trades()
        self.open_orders = read_open_orders()

        for trade in self.trades:
            self.traded_markets.add(trade.market_slug)
            self.balance -= trade.size
            if trade.status == "won":
                self.balance += trade.payout
                self.wins += 1
            elif trade.status == "lost":
                self.losses += 1

        if self.trades:
            self._log(
                f"Loaded {len(self.trades)} trades ({self.wins}W/{self.losses}L), balance ${self.balance:.2f}"
            )
        if self.open_orders:
            self._log(
                f"Restored {len(self.open_orders)} open orders, ${self.reserved_open_exposure:.2f} reserved"
            )

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

    @property
    def pending_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.status == "pending"]

    @property
    def reserved_open_exposure(self) -> float:
        return sum(order.reserved_size for order in self.open_orders)

    @property
    def available_balance(self) -> float:
        return max(0.0, self.balance - self.reserved_open_exposure)

    @property
    def account_equity(self) -> float:
        return self.balance + sum(trade.size for trade in self.pending_trades) + self.reserved_open_exposure

    @property
    def active_order_markets(self) -> set[str]:
        return {order.market_slug for order in self.open_orders}

    def bet_size(self, confidence: float, entry_price: float) -> float:
        """Size based on payout asymmetry, not just confidence."""
        wins_to_recover = entry_price / (1.0 - entry_price)
        risk_scale = min(1.5, 3.0 / wins_to_recover)
        conf_scale = 0.6 + confidence * 0.8  # range [0.6, 1.4]
        fraction = BET_FRACTION * risk_scale * conf_scale
        raw = self.available_balance * fraction
        return max(MIN_BET, min(MAX_BET, raw))

    @staticmethod
    def _market_type_from_slug(slug: str) -> str:
        return "15m" if "-15m-" in slug else "5m"

    @staticmethod
    def _entry_price_for_signal(signal: Signal) -> float:
        price_idx = 0 if signal.side == "YES" else 1
        return (
            signal.market.outcome_prices[price_idx]
            if len(signal.market.outcome_prices) > price_idx
            else 0.5
        )

    def _find_trade_by_order_id(self, order_id: str) -> Trade | None:
        if not order_id:
            return None
        return next((trade for trade in self.trades if trade.order_id == order_id), None)

    def _record_trade_fill(
        self,
        *,
        market_slug: str,
        question: str,
        strategy: str,
        side: str,
        confidence: float,
        reason: str,
        end_date,
        market_type: str,
        executor_type: str,
        order_id: str,
        result,
    ) -> Trade | None:
        fill_shares = result.fill_shares
        if fill_shares <= 0 and result.fill_price > 0:
            fill_shares = result.fill_size / result.fill_price
        if result.fill_size <= 0 or fill_shares <= 0:
            return None

        trade = self._find_trade_by_order_id(order_id)
        is_new = trade is None
        if trade is None:
            trade = Trade(
                timestamp=datetime.now(timezone.utc),
                market_slug=market_slug,
                question=question,
                strategy=strategy,
                side=side,
                entry_price=result.fill_price,
                size=result.fill_size,
                confidence=confidence,
                reason=reason,
                end_date=end_date,
                market_type=market_type,
                strategy_version=STRATEGY_VERSION,
                fees=result.fees,
                fill_price=result.fill_price,
                order_id=order_id,
                executor_type=executor_type,
            )
            self.trades.append(trade)
            self.traded_markets.add(market_slug)
        else:
            existing_shares = trade.size / trade.entry_price if trade.entry_price > 0 else 0.0
            total_cost = trade.size + result.fill_size
            total_shares = existing_shares + fill_shares
            avg_price = total_cost / total_shares if total_shares > 0 else result.fill_price
            trade.size = total_cost
            trade.entry_price = avg_price
            trade.fill_price = avg_price
            trade.fees += result.fees
            trade.executor_type = trade.executor_type or executor_type

        self.balance -= result.fill_size
        if is_new:
            from logger import log_trade

            log_trade(trade)
        else:
            save_trades(self.trades)
        log_trade_jsonl(trade, result, executor_type=executor_type, snapshot_event="fill")
        return trade

    def _create_open_order(self, signal: Signal, result) -> OpenOrder:
        now = datetime.now(timezone.utc)
        return OpenOrder(
            order_id=result.order_id,
            created_at=now,
            updated_at=now,
            market_slug=signal.market.slug,
            question=signal.market.question,
            condition_id=signal.market.condition_id,
            token_id=result.token_id,
            strategy=signal.strategy,
            side=signal.side,
            confidence=signal.confidence,
            reason=signal.reason,
            end_date=signal.market.end_date,
            market_type=self._market_type_from_slug(signal.market.slug),
            strategy_version=STRATEGY_VERSION,
            executor_type=type(self.executor).__name__,
            limit_price=result.fill_price,
            requested_size=result.requested_size or result.reserved_size,
            requested_shares=result.requested_shares,
            reserved_size=result.remaining_size or result.reserved_size,
            status=result.status,
            raw_status=result.raw_status or result.status,
        )

    def execute_paper_trade(self, signal: Signal) -> Trade | None:
        """Execute a trade through the configured executor.

        Named execute_paper_trade for backwards compatibility, but routes
        through self.executor (Paper, Simulation, or Live).
        """
        entry_price = self._entry_price_for_signal(signal)
        size = self.bet_size(signal.confidence, entry_price)
        result = self.executor.place_order(signal, size, entry_price)

        if result.fill_size > 0:
            trade = self._record_trade_fill(
                market_slug=signal.market.slug,
                question=signal.market.question,
                strategy=signal.strategy,
                side=signal.side,
                confidence=signal.confidence,
                reason=signal.reason,
                end_date=signal.market.end_date,
                market_type=self._market_type_from_slug(signal.market.slug),
                executor_type=type(self.executor).__name__,
                order_id=result.order_id,
                result=result,
            )
        else:
            trade = None

        if result.needs_reconciliation:
            open_order = self._create_open_order(signal, result)
            self.open_orders = [o for o in self.open_orders if o.order_id != open_order.order_id]
            self.open_orders.append(open_order)
            save_open_orders(self.open_orders)
            log_order_event(
                "submit",
                open_order.order_id,
                {
                    "market_slug": open_order.market_slug,
                    "side": open_order.side,
                    "status": open_order.status,
                    "raw_status": open_order.raw_status,
                    "requested_size": open_order.requested_size,
                    "reserved_size": open_order.reserved_size,
                },
            )
            reconciled = self._reconcile_open_orders(order_ids={open_order.order_id})
            return reconciled[-1] if reconciled else trade

        if not result.filled:
            self._log(f"  Order rejected: {result.reason}")
            log_order_event(
                "reject",
                result.order_id,
                {
                    "market_slug": signal.market.slug,
                    "side": signal.side,
                    "status": result.status,
                    "reason": result.reason,
                },
            )
            return None

        return trade

    def _reconcile_open_orders(
        self,
        *,
        order_ids: set[str] | None = None,
        max_orders: int | None = None,
    ) -> list[Trade]:
        if not self.open_orders:
            return []

        reconciled_trades: list[Trade] = []
        changed = False
        count = 0

        for open_order in list(self.open_orders):
            if order_ids is not None and open_order.order_id not in order_ids:
                continue
            if max_orders is not None and count >= max_orders:
                break
            count += 1

            result = self.executor.reconcile_order(open_order)
            if result is None:
                continue

            previous_status = open_order.status
            previous_raw_status = open_order.raw_status
            previous_reserved = open_order.reserved_size

            trade = None
            if result.fill_size > 0:
                trade = self._record_trade_fill(
                    market_slug=open_order.market_slug,
                    question=open_order.question,
                    strategy=open_order.strategy,
                    side=open_order.side,
                    confidence=open_order.confidence,
                    reason=open_order.reason,
                    end_date=open_order.end_date,
                    market_type=open_order.market_type,
                    executor_type=open_order.executor_type,
                    order_id=open_order.order_id,
                    result=result,
                )
                if trade:
                    reconciled_trades.append(trade)

            open_order.confirmed_fill_size += result.fill_size
            open_order.confirmed_fill_shares += result.fill_shares
            open_order.confirmed_fees += result.fees
            open_order.reserved_size = result.remaining_size
            open_order.status = result.status
            open_order.raw_status = result.raw_status or result.status
            open_order.updated_at = datetime.now(timezone.utc)

            material_change = (
                result.fill_size > 0
                or result.terminal
                or previous_status != open_order.status
                or previous_raw_status != open_order.raw_status
                or abs(previous_reserved - open_order.reserved_size) > 1e-9
            )
            if material_change:
                changed = True
                log_order_event(
                    "reconcile",
                    open_order.order_id,
                    {
                        "market_slug": open_order.market_slug,
                        "side": open_order.side,
                        "status": open_order.status,
                        "raw_status": open_order.raw_status,
                        "fill_size": result.fill_size,
                        "fill_shares": result.fill_shares,
                        "remaining_size": open_order.reserved_size,
                        "terminal": result.terminal,
                    },
                )

            if result.terminal or result.remaining_size <= 1e-9:
                self.open_orders.remove(open_order)
                changed = True

        if changed:
            save_open_orders(self.open_orders)

        return reconciled_trades

    def _try_execute(self, signal: Signal) -> Trade | None:
        if signal.market.slug in self.traded_markets:
            self._log(f"  Skip (already traded): {signal.market.slug}")
            return None
        if signal.market.slug in self.active_order_markets:
            self._log(f"  Skip (order already live): {signal.market.slug}")
            return None
        if self.available_balance < MIN_BET:
            self._log(f"  Skip (available ${self.available_balance:.2f} < min ${MIN_BET})")
            return None

        size = self.bet_size(signal.confidence, self._entry_price_for_signal(signal))
        risk_check = self.risk_manager.check_trade_allowed(
            signal,
            size,
            self.pending_trades,
            open_orders=self.open_orders,
            account_equity=self.account_equity,
        )
        if not risk_check.allowed:
            self._log(f"  Risk blocked: {risk_check.reason}")
            log_risk_block(signal.market.slug, risk_check.reason)
            return None

        return self.execute_paper_trade(signal)

    def settle_trades(self, max_checks: int = 3):
        """Settle pending trades whose markets have been resolved on Polymarket."""
        now = datetime.now(timezone.utc)
        settled = False
        api_calls = 0

        for trade in self.trades:
            if trade.status != "pending":
                continue
            if trade.end_date is not None and (now - trade.end_date).total_seconds() < 10:
                continue

            if api_calls >= max_checks:
                break
            api_calls += 1

            resolved = fetch_resolved_market(trade.market_slug)
            if resolved is None:
                if trade.end_date and (now - trade.end_date).total_seconds() > 600:
                    trade.status = "lost"
                    trade.payout = 0.0
                    self.losses += 1
                    self.risk_manager.record_trade_result(trade)
                    self._log(f"LOSS (unresolved after 10m): {trade.market_slug}")
                    log_settlement(trade)
                    log_trade_jsonl(trade, executor_type=trade.executor_type or type(self.executor).__name__, snapshot_event="settlement")
                    settled = True
                continue

            outcomes = resolved["outcomes"]
            prices = resolved["outcome_prices"]
            winning_idx = prices.index(1.0)
            winning_outcome = outcomes[winning_idx].strip().upper()

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
            log_trade_jsonl(
                trade,
                executor_type=trade.executor_type or type(self.executor).__name__,
                snapshot_event="settlement",
            )
            settled = True

        if settled:
            save_trades(self.trades)

    def check_updown_markets(self) -> list[Signal]:
        signals = []
        mode = getattr(self, "mode_15m", None)
        extra_edge = mode.edge_boost if mode and mode.tightened else 0.0
        extra_conf = mode.confidence_boost if mode and mode.tightened else 0.0
        for udm in self.updown_markets_found:
            edge_boost = extra_edge if udm.interval_minutes == 15 else 0.0
            conf_boost = extra_conf if udm.interval_minutes == 15 else 0.0
            signal, reason = analyze_updown_market(udm, extra_min_edge=edge_boost)
            if signal:
                if conf_boost > 0 and signal.confidence < conf_boost:
                    self._log(
                        f"  {udm.coin} skip: confidence {signal.confidence:.0%} < tightened min {conf_boost:.0%}"
                    )
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
        self.risk_manager.on_cycle_start()

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

        reconciled = self._reconcile_open_orders()
        if reconciled:
            new_trades.extend(reconciled)
            self._log(f"Reconciled {len(reconciled)} confirmed fill(s)")

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
            self._log(
                f"Found {len(udm_5m)} 5m + {len(udm_15m)} 15m updown markets | {mode_15m.reason}"
            )

            active_coins = {udm.coin for udm in self.updown_markets_found}
            if active_coins:
                t0 = time.time()
                self._warm_active_coins(active_coins)
                warm_ms = (time.time() - t0) * 1000
                if warm_ms > 2000:
                    self._log(
                        f"  Price warming slow: {warm_ms:.0f}ms for {len(active_coins)} coins"
                    )

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
                    self._log(
                        f"  TRADE: {trade.side} {trade.market_slug} @ ${trade.entry_price:.2f}, ${trade.size:.2f}"
                    )
                    new_trades.append(trade)
                if trade or signal.market.slug in self.active_order_markets:
                    cycle_bets += 1
        except Exception as e:
            self._log(f"UpDown check error: {e}")
            self.status = "UpDown check error"

        self.settle_trades()

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
            return 5.0
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
