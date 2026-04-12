from datetime import datetime, timezone

from config import Trade, STRATEGY_VERSION, MIN_PATCH_TRADES_FOR_EVAL
from strategy_eval import compute_patch_stats, evaluate_15m_mode, PatchStats, Mode15mResult


def _make_trade(
    status="won",
    size=2.0,
    payout=3.0,
    strategy_version=STRATEGY_VERSION,
    market_type="5m",
):
    return Trade(
        timestamp=datetime.now(timezone.utc),
        market_slug="test-slug",
        question="Test?",
        strategy="updown",
        side="YES",
        entry_price=0.65,
        size=size,
        confidence=0.80,
        reason="test",
        status=status,
        payout=payout,
        market_type=market_type,
        strategy_version=strategy_version,
    )


# --- compute_patch_stats ---


def test_patch_stats_filters_by_version():
    trades = [
        _make_trade(strategy_version=5),
        _make_trade(strategy_version=5),
        _make_trade(strategy_version=STRATEGY_VERSION),
    ]
    stats = compute_patch_stats(trades)
    assert stats.total_trades == 1
    assert stats.version == STRATEGY_VERSION


def test_patch_stats_filters_by_market_type():
    trades = [
        _make_trade(market_type="5m"),
        _make_trade(market_type="15m"),
        _make_trade(market_type="5m"),
    ]
    stats = compute_patch_stats(trades, market_type="15m")
    assert stats.total_trades == 1


def test_patch_stats_win_rate():
    trades = [
        _make_trade(status="won", size=2.0, payout=3.0),
        _make_trade(status="won", size=2.0, payout=3.0),
        _make_trade(status="lost", size=2.0, payout=0.0),
    ]
    stats = compute_patch_stats(trades)
    assert stats.win_rate == 2 / 3


def test_patch_stats_profit_factor():
    trades = [
        _make_trade(status="won", size=2.0, payout=4.0),  # profit = 2.0
        _make_trade(status="lost", size=2.0, payout=0.0),  # loss = 2.0
    ]
    stats = compute_patch_stats(trades)
    assert stats.profit_factor == 1.0  # 2.0 / 2.0


def test_patch_stats_ignores_pending():
    trades = [
        _make_trade(status="won", size=2.0, payout=3.0),
        _make_trade(status="pending", size=2.0, payout=0.0),
    ]
    stats = compute_patch_stats(trades)
    assert stats.settled_trades == 1
    assert stats.total_trades == 2


def test_patch_stats_empty():
    stats = compute_patch_stats([])
    assert stats.win_rate == 0.0
    assert stats.profit_factor == float("inf")
    assert stats.net_pnl == 0.0
    assert stats.avg_pnl == 0.0
    assert stats.expectancy == 0.0


def test_patch_stats_net_pnl():
    trades = [
        _make_trade(status="won", size=2.0, payout=5.0),  # profit +3
        _make_trade(status="lost", size=2.0, payout=0.0),  # loss -2
    ]
    stats = compute_patch_stats(trades)
    assert stats.net_pnl == 1.0  # 3.0 - 2.0


def test_patch_stats_expectancy():
    trades = [
        _make_trade(status="won", size=2.0, payout=4.0),  # profit = 2.0
        _make_trade(status="won", size=2.0, payout=4.0),  # profit = 2.0
        _make_trade(status="lost", size=2.0, payout=0.0),  # loss = 2.0
    ]
    stats = compute_patch_stats(trades)
    # WR = 2/3, avg_win = 2.0, avg_loss = 2.0
    # expectancy = (2/3 * 2.0) - (1/3 * 2.0) = 0.667
    assert abs(stats.expectancy - (2 / 3 * 2.0 - 1 / 3 * 2.0)) < 0.001


# --- evaluate_15m_mode ---


def test_15m_enabled_when_not_enough_data():
    # Fewer than MIN_PATCH_TRADES_FOR_EVAL settled 15m trades
    trades = [_make_trade(market_type="15m") for _ in range(5)]
    result = evaluate_15m_mode(trades)
    assert result.enabled is True
    assert result.tightened is False
    assert "collecting data" in result.reason


def test_15m_enabled_with_strong_performance():
    # Good win rate, positive PnL
    trades = []
    for _ in range(int(MIN_PATCH_TRADES_FOR_EVAL * 0.8)):
        trades.append(_make_trade(status="won", size=2.0, payout=3.5, market_type="15m"))
    for _ in range(int(MIN_PATCH_TRADES_FOR_EVAL * 0.2)):
        trades.append(_make_trade(status="lost", size=2.0, payout=0.0, market_type="15m"))
    result = evaluate_15m_mode(trades)
    assert result.enabled is True
    assert result.tightened is False


def test_15m_tightened_when_marginal():
    # WR ~60% with slightly negative overall PnL but above -$5
    # 12 wins at payout=3.5 (profit=1.5 each = $18), 8 losses at $2 each ($16)
    # net PnL = +$2, but WR 60% < 65% threshold → marginal, not strong
    n = MIN_PATCH_TRADES_FOR_EVAL
    trades = []
    wins = int(n * 0.60)
    losses = n - wins
    for _ in range(wins):
        trades.append(_make_trade(status="won", size=2.0, payout=3.5, market_type="15m"))
    for _ in range(losses):
        trades.append(_make_trade(status="lost", size=2.0, payout=0.0, market_type="15m"))
    result = evaluate_15m_mode(trades)
    assert result.enabled is True
    assert result.tightened is True
    assert result.confidence_boost > 0
    assert result.edge_boost > 0


def test_15m_disabled_when_poor():
    # WR ~30%, deeply negative
    n = MIN_PATCH_TRADES_FOR_EVAL
    trades = []
    wins = int(n * 0.3)
    losses = n - wins
    for _ in range(wins):
        trades.append(_make_trade(status="won", size=2.0, payout=3.0, market_type="15m"))
    for _ in range(losses):
        trades.append(_make_trade(status="lost", size=2.0, payout=0.0, market_type="15m"))
    result = evaluate_15m_mode(trades)
    assert result.enabled is False


def test_15m_ignores_old_versions():
    """Old version trades should not affect current version evaluation."""
    n = MIN_PATCH_TRADES_FOR_EVAL
    # Old version: terrible performance
    old_trades = [
        _make_trade(status="lost", size=2.0, payout=0.0, strategy_version=1, market_type="15m")
        for _ in range(n)
    ]
    # Current version: not enough data yet
    new_trades = [
        _make_trade(status="won", size=2.0, payout=3.5, market_type="15m")
        for _ in range(3)
    ]
    result = evaluate_15m_mode(old_trades + new_trades)
    # Should be enabled because current version only has 3 trades (collecting data)
    assert result.enabled is True
    assert "collecting data" in result.reason


def test_15m_only_evaluates_15m_trades():
    """5m trade performance should not affect 15m mode decision."""
    n = MIN_PATCH_TRADES_FOR_EVAL
    # Lots of bad 5m trades
    bad_5m = [
        _make_trade(status="lost", size=2.0, payout=0.0, market_type="5m")
        for _ in range(n)
    ]
    # Few good 15m trades
    good_15m = [
        _make_trade(status="won", size=2.0, payout=3.5, market_type="15m")
        for _ in range(3)
    ]
    result = evaluate_15m_mode(bad_5m + good_15m)
    assert result.enabled is True  # 15m has only 3 trades, still collecting
