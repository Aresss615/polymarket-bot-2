from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from config import Market, Signal, Trade, TRADE_SIZE, STARTING_BALANCE
from engine import Engine


def _make_market(slug="test-market"):
    return Market(
        condition_id=f"0x{slug}",
        question=f"Will {slug} happen?",
        slug=slug,
        outcomes=["Yes", "No"],
        outcome_prices=[0.65, 0.35],
        token_ids=[f"0x{slug}_yes", f"0x{slug}_no"],
        end_date=datetime(2026, 4, 10, 21, 0, tzinfo=timezone.utc),
        active=True,
    )


def _make_signal(market, strategy="level", side="YES", confidence=0.95):
    return Signal(
        market=market,
        strategy=strategy,
        side=side,
        confidence=confidence,
        reason="test reason",
    )


def test_engine_initial_state():
    engine = Engine()
    assert engine.balance == STARTING_BALANCE
    assert engine.trades == []
    assert engine.markets == []
    assert engine.traded_markets == set()
    assert engine.running is False


@patch("engine.log_trade")
def test_execute_paper_trade(mock_log):
    engine = Engine()
    market = _make_market()
    signal = _make_signal(market)

    trade = engine.execute_paper_trade(signal)

    assert trade.market_slug == "test-market"
    assert trade.side == "YES"
    assert trade.entry_price == 0.65  # YES price
    assert trade.size == TRADE_SIZE
    assert trade.strategy == "level"
    assert engine.balance == STARTING_BALANCE - TRADE_SIZE
    assert "test-market" in engine.traded_markets
    mock_log.assert_called_once()


@patch("engine.log_trade")
def test_execute_paper_trade_no_side(mock_log):
    engine = Engine()
    market = _make_market()
    signal = _make_signal(market, side="NO")

    trade = engine.execute_paper_trade(signal)
    assert trade.entry_price == 0.35  # NO price


@patch("engine.log_trade")
def test_duplicate_trade_prevention(mock_log):
    engine = Engine()
    market = _make_market("same-market")
    signal = _make_signal(market)

    engine.execute_paper_trade(signal)
    assert "same-market" in engine.traded_markets
    # Engine.tick() checks traded_markets before calling execute_paper_trade


@patch("engine.fetch_active_markets")
@patch("engine.find_level_markets")
@patch("engine.get_price")
@patch("engine.analyze_level_opportunity")
@patch("engine.log_trade")
def test_tick_executes_level_trade(mock_log, mock_analyze, mock_price, mock_find, mock_fetch):
    market = _make_market("btc-84k")
    signal = _make_signal(market)

    mock_fetch.return_value = [market]
    mock_find.return_value = [MagicMock(coin="BTC")]
    mock_price.return_value = 86000.0
    mock_analyze.return_value = signal

    engine = Engine()
    trades = engine.tick()

    assert len(trades) == 1
    assert trades[0].strategy == "level"
    assert trades[0].side == "YES"


@patch("engine.fetch_active_markets")
@patch("engine.find_level_markets")
@patch("engine.get_price")
@patch("engine.analyze_level_opportunity")
def test_tick_no_signal_no_trade(mock_analyze, mock_price, mock_find, mock_fetch):
    mock_fetch.return_value = [_make_market()]
    mock_find.return_value = [MagicMock(coin="BTC")]
    mock_price.return_value = 84500.0  # too close
    mock_analyze.return_value = None

    engine = Engine()
    trades = engine.tick()
    assert trades == []


@patch("engine.fetch_active_markets")
def test_tick_handles_fetch_error(mock_fetch):
    mock_fetch.side_effect = Exception("network error")
    engine = Engine()
    trades = engine.tick()
    assert trades == []


@patch("engine.log_trade")
def test_balance_decreases_per_trade(mock_log):
    engine = Engine()
    for i in range(3):
        market = _make_market(f"market-{i}")
        signal = _make_signal(market)
        engine.execute_paper_trade(signal)
    assert engine.balance == STARTING_BALANCE - (3 * TRADE_SIZE)


def test_stop():
    engine = Engine()
    engine.running = True
    engine.stop()
    assert engine.running is False
