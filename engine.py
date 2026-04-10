import time
from datetime import datetime, timezone

from config import (
    Signal,
    Trade,
    TRADE_SIZE,
    STARTING_BALANCE,
    NEWS_POLL_INTERVAL,
)
from market_fetcher import fetch_active_markets
from news_fetcher import fetch_google_news
from price_feed import get_price
from level_analyzer import find_level_markets, analyze_level_opportunity
from arbitrage_analyzer import analyze_headlines
from logger import log_trade


class Engine:
    def __init__(self):
        self.balance = STARTING_BALANCE
        self.trades: list[Trade] = []
        self.markets = []
        self.traded_markets: set[str] = set()
        self.last_news_poll: float = time.time()
        self.running = False
        self.status = "Initializing"

    def execute_paper_trade(self, signal: Signal) -> Trade:
        price_idx = 0 if signal.side == "YES" else 1
        entry_price = (
            signal.market.outcome_prices[price_idx]
            if len(signal.market.outcome_prices) > price_idx
            else 0.5
        )

        trade = Trade(
            timestamp=datetime.now(timezone.utc),
            market_slug=signal.market.slug,
            question=signal.market.question,
            strategy=signal.strategy,
            side=signal.side,
            entry_price=entry_price,
            size=TRADE_SIZE,
            confidence=signal.confidence,
            reason=signal.reason,
        )
        self.trades.append(trade)
        self.traded_markets.add(signal.market.slug)
        self.balance -= TRADE_SIZE
        log_trade(trade)
        return trade

    def _try_execute(self, signal: Signal) -> Trade | None:
        if signal.market.slug in self.traded_markets:
            return None
        if self.balance < TRADE_SIZE:
            return None
        return self.execute_paper_trade(signal)

    def check_level_markets(self) -> list[Signal]:
        level_markets = find_level_markets(self.markets)
        signals = []
        for lm in level_markets:
            price = get_price(lm.coin)
            if price is None:
                continue
            signal = analyze_level_opportunity(lm, price)
            if signal:
                signals.append(signal)
        return signals

    def check_arbitrage(self) -> list[Signal]:
        articles = fetch_google_news()
        if not articles:
            return []
        return analyze_headlines(articles, self.markets)

    def tick(self) -> list[Trade]:
        now = time.time()
        new_trades = []

        try:
            self.markets = fetch_active_markets()
        except Exception:
            return new_trades

        # Check level markets every tick
        self.status = "Checking level markets"
        try:
            for signal in self.check_level_markets():
                trade = self._try_execute(signal)
                if trade:
                    new_trades.append(trade)
        except Exception:
            self.status = "Level check error"

        # Check news on interval
        if now - self.last_news_poll >= NEWS_POLL_INTERVAL:
            self.last_news_poll = now
            self.status = "Checking news arbitrage"
            try:
                for signal in self.check_arbitrage():
                    trade = self._try_execute(signal)
                    if trade:
                        new_trades.append(trade)
            except Exception:
                self.status = "Arbitrage check error"

        self.status = "Idle"
        return new_trades

    def run(self, interval: float = 30.0):
        self.running = True
        while self.running:
            self.tick()
            time.sleep(interval)

    def stop(self):
        self.running = False
