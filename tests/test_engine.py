from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

import pytest

from config import Market, Signal, Trade, STARTING_BALANCE, BET_FRACTION, MIN_BET, MAX_BET, MAX_BETS_PER_CYCLE, TICK_INTERVAL, UpDownMarket, STRATEGY_VERSION
from engine import Engine


@pytest.fixture(autouse=True)
def _clean_engine():
    """Ensure Engine doesn't load real trades.csv or make network calls in tests."""
    from strategy_eval import Mode15mResult
    _default_15m = Mode15mResult(enabled=True, tightened=False, confidence_boost=0.0, edge_boost=0.0, reason="test")
    with patch("engine.read_trades", return_value=[]), \
         patch("engine.get_price", return_value=None), \
         patch("engine.evaluate_15m_mode", return_value=_default_15m), \
         patch("engine.log_trade_jsonl"), \
         patch("engine.log_settlement"), \
         patch("engine.log_risk_block"):
        yield


def _make_market(slug="btc-updown-5m-123", end_minutes=1):
    return Market(
        condition_id=f"0x{slug}",
        question="BTC Up or Down?",
        slug=slug,
        outcomes=["Up", "Down"],
        outcome_prices=[0.55, 0.45],
        token_ids=[f"0x{slug}_up", f"0x{slug}_down"],
        end_date=datetime.now(timezone.utc) + timedelta(minutes=end_minutes),
        active=True,
    )


def _make_signal(market, strategy="updown", side="YES", confidence=0.95):
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
    assert engine.wins == 0
    assert engine.losses == 0


@patch("engine.log_trade")
def test_execute_paper_trade(mock_log):
    engine = Engine()
    market = _make_market()
    signal = _make_signal(market, confidence=0.95)

    trade = engine.execute_paper_trade(signal)

    assert trade.market_slug == "btc-updown-5m-123"
    assert trade.side == "YES"
    assert trade.entry_price == 0.55
    assert trade.size >= MIN_BET
    assert trade.size <= MAX_BET
    assert trade.strategy == "updown"
    assert trade.status == "pending"
    assert trade.strategy_version == STRATEGY_VERSION
    assert engine.balance < STARTING_BALANCE
    assert "btc-updown-5m-123" in engine.traded_markets
    mock_log.assert_called_once()


@patch("engine.log_trade")
def test_execute_paper_trade_no_side(mock_log):
    engine = Engine()
    market = _make_market()
    signal = _make_signal(market, side="NO")

    trade = engine.execute_paper_trade(signal)
    assert trade.entry_price == 0.45


@patch("engine.log_trade")
def test_duplicate_trade_prevention(mock_log):
    engine = Engine()
    market = _make_market("same-market")
    signal = _make_signal(market)

    engine.execute_paper_trade(signal)
    assert "same-market" in engine.traded_markets


@patch("engine.fetch_active_markets")
@patch("engine.find_updown_markets")
@patch("engine.analyze_updown_market")
@patch("engine.log_trade")
def test_tick_executes_updown_trade(mock_log, mock_analyze, mock_find, mock_fetch):
    market = _make_market("btc-updown-5m-100")
    signal = _make_signal(market)

    mock_fetch.return_value = [market]
    udm_mock = MagicMock()
    udm_mock.interval_minutes = 5
    mock_find.return_value = [udm_mock]
    mock_analyze.return_value = (signal, "test reason")

    engine = Engine()
    trades = engine.tick()

    assert len(trades) == 1
    assert trades[0].strategy == "updown"
    assert trades[0].side == "YES"


@patch("engine.fetch_active_markets")
@patch("engine.find_updown_markets")
@patch("engine.analyze_updown_market")
def test_tick_no_signal_no_trade(mock_analyze, mock_find, mock_fetch):
    mock_fetch.return_value = [_make_market()]
    udm_mock = MagicMock()
    udm_mock.interval_minutes = 5
    mock_find.return_value = [udm_mock]
    mock_analyze.return_value = (None, "skip: test")

    engine = Engine()
    trades = engine.tick()
    assert trades == []


@patch("engine.fetch_active_markets")
@patch("engine.find_updown_markets")
@patch("engine.analyze_updown_market")
@patch("engine.log_trade")
def test_tick_respects_max_bets_per_cycle(mock_log, mock_analyze, mock_find, mock_fetch):
    """Only MAX_BETS_PER_CYCLE trades should be executed per tick."""
    markets = [_make_market(f"btc-updown-5m-{i}") for i in range(10)]
    signals = [(_make_signal(m), "test reason") for m in markets]

    mock_fetch.return_value = markets
    udm_mocks = []
    for _ in range(10):
        m = MagicMock()
        m.interval_minutes = 5
        udm_mocks.append(m)
    mock_find.return_value = udm_mocks
    mock_analyze.side_effect = signals

    engine = Engine()
    trades = engine.tick()

    assert len(trades) <= MAX_BETS_PER_CYCLE


@patch("engine.fetch_active_markets")
@patch("engine.find_updown_markets")
@patch("engine.analyze_updown_market")
@patch("engine.log_trade")
def test_tick_skips_15m_when_disabled(mock_log, mock_analyze, mock_find, mock_fetch):
    """15-minute markets are filtered out when evaluate_15m_mode returns disabled."""
    from strategy_eval import Mode15mResult
    disabled_15m = Mode15mResult(enabled=False, tightened=False, confidence_boost=0.0, edge_boost=0.0, reason="disabled")

    market = _make_market("eth-updown-15m-100")
    signal = _make_signal(market)

    mock_fetch.return_value = [market]
    udm_mock = MagicMock()
    udm_mock.interval_minutes = 15
    udm_mock.coin = "ETH"
    mock_find.return_value = [udm_mock]
    mock_analyze.return_value = (signal, "test reason")

    with patch("engine.evaluate_15m_mode", return_value=disabled_15m):
        engine = Engine()
        trades = engine.tick()

    assert len(trades) == 0
    mock_analyze.assert_not_called()


@patch("engine.log_trade")
def test_trade_market_type_from_signal(mock_log):
    """Trade should have market_type set based on the market slug."""
    engine = Engine()
    market_5m = _make_market("btc-updown-5m-123")
    signal_5m = _make_signal(market_5m)
    trade_5m = engine.execute_paper_trade(signal_5m)
    assert trade_5m.market_type == "5m"

    market_15m = _make_market("eth-updown-15m-456")
    signal_15m = _make_signal(market_15m)
    trade_15m = engine.execute_paper_trade(signal_15m)
    assert trade_15m.market_type == "15m"


@patch("engine.fetch_active_markets")
def test_tick_handles_fetch_error(mock_fetch):
    mock_fetch.side_effect = Exception("network error")
    engine = Engine()
    trades = engine.tick()
    assert trades == []


@patch("engine.log_trade")
def test_balance_decreases_per_trade(mock_log):
    engine = Engine()
    market = _make_market("btc-updown-5m-1")
    signal = _make_signal(market)
    trade = engine.execute_paper_trade(signal)
    assert engine.balance == STARTING_BALANCE - trade.size


def test_stop():
    engine = Engine()
    engine.running = True
    engine.stop()
    assert engine.running is False


# --- Settlement tests ---


@patch("engine.save_trades")
@patch("engine.fetch_resolved_market")
@patch("engine.log_trade")
def test_settle_winning_trade(mock_log, mock_resolve, mock_save):
    engine = Engine()
    market = _make_market("btc-win", end_minutes=-1)  # already expired
    signal = _make_signal(market, side="YES")
    trade = engine.execute_paper_trade(signal)

    # Polymarket resolved: Up won (price=1.0)
    mock_resolve.return_value = {"outcomes": ["Up", "Down"], "outcome_prices": [1.0, 0.0]}
    engine.settle_trades()

    assert trade.status == "won"
    assert trade.payout > trade.size  # profit
    assert engine.wins == 1
    assert engine.losses == 0
    assert engine.balance > STARTING_BALANCE - trade.size  # got payout


@patch("engine.save_trades")
@patch("engine.fetch_resolved_market")
@patch("engine.log_trade")
def test_settle_losing_trade(mock_log, mock_resolve, mock_save):
    engine = Engine()
    market = _make_market("btc-lose", end_minutes=-1)
    signal = _make_signal(market, side="YES")
    trade = engine.execute_paper_trade(signal)

    # Polymarket resolved: Down won (NO side)
    mock_resolve.return_value = {"outcomes": ["Up", "Down"], "outcome_prices": [0.0, 1.0]}
    engine.settle_trades()

    assert trade.status == "lost"
    assert trade.payout == 0.0
    assert engine.wins == 0
    assert engine.losses == 1


@patch("engine.save_trades")
@patch("engine.fetch_resolved_market")
@patch("engine.log_trade")
def test_win_rate(mock_log, mock_resolve, mock_save):
    engine = Engine()

    # Win one
    m1 = _make_market("btc-w", end_minutes=-1)
    engine.execute_paper_trade(_make_signal(m1, side="YES"))

    # Lose one
    m2 = _make_market("btc-l", end_minutes=-1)
    engine.execute_paper_trade(_make_signal(m2, side="YES"))

    # First call: Up won (YES wins), second call: Down won (YES loses)
    mock_resolve.side_effect = [
        {"outcomes": ["Up", "Down"], "outcome_prices": [1.0, 0.0]},
        {"outcomes": ["Up", "Down"], "outcome_prices": [0.0, 1.0]},
    ]
    engine.settle_trades()

    assert engine.wins == 1
    assert engine.losses == 1
    assert engine.win_rate == 0.5


@patch("engine.fetch_resolved_market")
@patch("engine.log_trade")
def test_no_settle_before_expiry(mock_log, mock_resolve):
    engine = Engine()
    market = _make_market("btc-future", end_minutes=5)  # expires in 5 min
    signal = _make_signal(market, side="YES")
    trade = engine.execute_paper_trade(signal)

    # Should not even call the API
    engine.settle_trades()

    assert trade.status == "pending"  # not settled yet
    assert engine.wins == 0
    mock_resolve.assert_not_called()


@patch("engine.save_trades")
@patch("engine.fetch_resolved_market")
@patch("engine.log_trade")
def test_payout_calculation(mock_log, mock_resolve, mock_save):
    engine = Engine()
    market = _make_market("btc-pay", end_minutes=-1)
    market.outcome_prices = [0.60, 0.40]
    signal = _make_signal(market, side="YES")
    trade = engine.execute_paper_trade(signal)

    mock_resolve.return_value = {"outcomes": ["Up", "Down"], "outcome_prices": [1.0, 0.0]}
    engine.settle_trades()

    # Bought at 0.60, won -> payout = size / 0.60
    assert trade.status == "won"
    assert abs(trade.payout - (trade.size / 0.60)) < 0.01


@patch("engine.fetch_resolved_market")
@patch("engine.log_trade")
def test_settle_not_resolved_yet(mock_log, mock_resolve):
    engine = Engine()
    market = _make_market("btc-pending", end_minutes=-1)
    signal = _make_signal(market, side="YES")
    trade = engine.execute_paper_trade(signal)

    # Market not yet resolved
    mock_resolve.return_value = None
    engine.settle_trades()

    assert trade.status == "pending"
    assert engine.wins == 0
    assert engine.losses == 0


@patch("engine.save_trades")
@patch("engine.fetch_resolved_market")
@patch("engine.log_trade")
def test_settle_trade_without_end_date_uses_market_resolution(mock_log, mock_resolve, mock_save):
    engine = Engine()
    market = _make_market("btc-no-enddate", end_minutes=-1)
    signal = _make_signal(market, side="YES")
    trade = engine.execute_paper_trade(signal)
    trade.end_date = None  # simulate legacy row loaded from old CSV format

    mock_resolve.return_value = {"outcomes": ["Up", "Down"], "outcome_prices": [1.0, 0.0]}
    engine.settle_trades()

    assert trade.status == "won"
    assert engine.wins == 1
    assert engine.losses == 0


# --- Bet sizing tests ---


def test_bet_size_scales_with_confidence():
    engine = Engine()
    low_conf = engine.bet_size(confidence=0.2, entry_price=0.70)
    high_conf = engine.bet_size(confidence=0.9, entry_price=0.70)
    assert high_conf > low_conf


def test_bet_size_scales_inversely_with_entry_price():
    """High entry prices should produce smaller bets (worse payout ratio)."""
    engine = Engine()
    engine.balance = 70.0
    low_entry = engine.bet_size(confidence=0.3, entry_price=0.60)
    high_entry = engine.bet_size(confidence=0.3, entry_price=0.85)
    assert low_entry > high_entry


def test_bet_size_respects_min():
    engine = Engine()
    engine.balance = 5.0  # small balance
    assert engine.bet_size(confidence=0.3, entry_price=0.70) >= MIN_BET


def test_bet_size_respects_max():
    engine = Engine()
    engine.balance = 1000.0
    assert engine.bet_size(confidence=1.0, entry_price=0.50) <= MAX_BET


@patch("engine.log_trade")
def test_bet_size_compounds_on_wins(mock_log):
    engine = Engine()
    initial_size = engine.bet_size(confidence=0.3, entry_price=0.70)

    # Simulate a win that increases balance
    engine.balance = 30.0
    bigger_size = engine.bet_size(confidence=0.3, entry_price=0.70)
    assert bigger_size > initial_size


@patch("engine.log_trade")
def test_bet_size_shrinks_on_losses(mock_log):
    engine = Engine()
    initial_size = engine.bet_size(confidence=0.3, entry_price=0.70)

    # Simulate losses that decreased balance
    engine.balance = 10.0
    smaller_size = engine.bet_size(confidence=0.3, entry_price=0.70)
    assert smaller_size < initial_size


# --- Adaptive tick interval tests ---


def test_adaptive_interval_fast_near_expiry():
    engine = Engine()
    m = _make_market()
    udm = UpDownMarket(market=m, coin="BTC", interval_minutes=5, seconds_to_close=20, up_outcome_index=0)
    engine.updown_markets_found = [udm]
    assert engine._adaptive_interval() == 5.0


def test_adaptive_interval_normal_when_far():
    engine = Engine()
    m = _make_market()
    udm = UpDownMarket(market=m, coin="BTC", interval_minutes=5, seconds_to_close=40, up_outcome_index=0)
    engine.updown_markets_found = [udm]
    assert engine._adaptive_interval() == TICK_INTERVAL


def test_adaptive_interval_normal_when_empty():
    engine = Engine()
    engine.updown_markets_found = []
    assert engine._adaptive_interval() == TICK_INTERVAL
