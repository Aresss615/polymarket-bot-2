import time
from collections import deque
from datetime import datetime, timezone

from config import (
    Signal,
    Trade,
    STARTING_BALANCE,
    BET_FRACTION,
    MIN_BET,
    MAX_BET,
    NEWS_POLL_INTERVAL,
    TICK_INTERVAL,
)
from market_fetcher import fetch_active_markets, find_updown_markets, fetch_resolved_market
from news_fetcher import fetch_google_news
from level_analyzer import analyze_updown_market
from arbitrage_analyzer import analyze_headlines
from logger import log_trade, read_trades, save_trades


class Engine:
    def __init__(self):
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

    def bet_size(self) -> float:
        """Compute bet size: fraction of balance, clamped to [MIN_BET, MAX_BET]."""
        raw = self.balance * BET_FRACTION
        return max(MIN_BET, min(MAX_BET, raw))

    def execute_paper_trade(self, signal: Signal) -> Trade:
        price_idx = 0 if signal.side == "YES" else 1
        entry_price = (
            signal.market.outcome_prices[price_idx]
            if len(signal.market.outcome_prices) > price_idx
            else 0.5
        )

        size = self.bet_size()
        trade = Trade(
            timestamp=datetime.now(timezone.utc),
            market_slug=signal.market.slug,
            question=signal.market.question,
            strategy=signal.strategy,
            side=signal.side,
            entry_price=entry_price,
            size=size,
            confidence=signal.confidence,
            reason=signal.reason,
            end_date=signal.market.end_date,
        )
        self.trades.append(trade)
        self.traded_markets.add(signal.market.slug)
        self.balance -= size
        log_trade(trade)
        return trade

    def _try_execute(self, signal: Signal) -> Trade | None:
        if signal.market.slug in self.traded_markets:
            return None
        if self.balance < MIN_BET:
            return None
        return self.execute_paper_trade(signal)

    def settle_trades(self):
        """Settle pending trades whose markets have been resolved on Polymarket.

        Queries the Gamma API for each pending trade's market to check
        if it has been resolved (outcome prices are exactly 1/0).
        """
        now = datetime.now(timezone.utc)
        settled = False
        for trade in self.trades:
            if trade.status != "pending":
                continue
            if trade.end_date is not None:
                # Wait at least 30s past expiry before checking resolution
                if (now - trade.end_date).total_seconds() < 30:
                    continue

            resolved = fetch_resolved_market(trade.market_slug)
            if resolved is None:
                # Not yet resolved — check again next tick
                # Give up after 10 minutes past expiry (if expiry is known)
                if trade.end_date and (now - trade.end_date).total_seconds() > 600:
                    trade.status = "lost"
                    trade.payout = 0.0
                    self.losses += 1
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
                trade.payout = trade.size / trade.entry_price
                trade.status = "won"
                self.balance += trade.payout
                self.wins += 1
                self._log(f"WIN: {trade.market_slug} +${trade.payout - trade.size:.2f}")
            else:
                trade.payout = 0.0
                trade.status = "lost"
                self.losses += 1
                self._log(f"LOSS: {trade.market_slug} -${trade.size:.2f}")
            settled = True

        if settled:
            save_trades(self.trades)

    def check_updown_markets(self) -> list[Signal]:
        signals = []
        for udm in self.updown_markets_found:
            signal = analyze_updown_market(udm)
            if signal:
                signals.append(signal)
        return signals

    def check_arbitrage(self) -> list[Signal]:
        articles = fetch_google_news()
        self.articles_found = articles or []
        if not articles:
            return []
        return analyze_headlines(articles, self.markets)

    def tick(self) -> list[Trade]:
        now = time.time()
        new_trades = []
        self.tick_count += 1

        try:
            self.status = "Fetching markets"
            self.markets = fetch_active_markets()
            self._log(f"Fetched {len(self.markets)} markets (closing within 120s)")
        except Exception as e:
            self._log(f"Market fetch error: {e}")
            self.status = "Market fetch error"
            return new_trades

        # Settle expired trades
        self.settle_trades()

        # Check crypto updown markets every tick
        self.status = "Checking updown markets"
        try:
            self.updown_markets_found = find_updown_markets(self.markets)
            self._log(f"Found {len(self.updown_markets_found)} updown markets")
            signals = self.check_updown_markets()
            self._log(f"UpDown signals: {len(signals)}")
            for signal in signals:
                self._log(f"  Signal: {signal.side} on {signal.market.slug} ({signal.confidence:.0%})")
                trade = self._try_execute(signal)
                if trade:
                    self._log(f"  TRADE: {trade.side} {trade.market_slug} @ ${trade.entry_price:.2f}")
                    new_trades.append(trade)
        except Exception as e:
            self._log(f"UpDown check error: {e}")
            self.status = "UpDown check error"

        # Check news on interval
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

        self.status = "Idle"
        return new_trades

    def run(self, interval: float = TICK_INTERVAL):
        self.running = True
        while self.running:
            self.tick()
            time.sleep(interval)

    def stop(self):
        self.running = False
