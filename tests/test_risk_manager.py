from datetime import datetime, timedelta, timezone

from config import Market, OpenOrder, RiskConfig, Signal, Trade
from risk_manager import RiskManager


def _make_signal(
    slug="btc-updown-5m-1",
    coin="BTC",
    thesis_id="crypto-ref:BTC:5m:close",
    size_multiplier=1.0,
    cluster_id="",
    signal_epoch_id="",
    market_type="5m",
):
    market = Market(
        condition_id="0xtest",
        question="Test?",
        slug=slug,
        outcomes=["Up", "Down"],
        outcome_prices=[0.75, 0.25],
        token_ids=["0xup", "0xdown"],
        end_date=None,
        active=True,
    )
    return Signal(
        market=market,
        strategy="updown",
        side="YES",
        confidence=0.8,
        reason="test",
        market_type=market_type,
        coin=coin,
        thesis_id=thesis_id,
        size_multiplier=size_multiplier,
        cluster_id=cluster_id,
        signal_epoch_id=signal_epoch_id,
    )


def _make_trade(
    slug="btc-updown-5m-1",
    coin="BTC",
    size=5.0,
    status="pending",
    timestamp=None,
    thesis_id="crypto-ref:BTC:5m:close",
    cluster_id="",
    signal_epoch_id="",
    market_type="5m",
):
    return Trade(
        timestamp=timestamp or datetime.now(timezone.utc),
        market_slug=slug,
        question="Test?",
        strategy="updown",
        side="YES",
        entry_price=0.75,
        size=size,
        confidence=0.8,
        reason="test",
        status=status,
        thesis_id=thesis_id,
        reference_symbol=coin,
        cluster_id=cluster_id,
        signal_epoch_id=signal_epoch_id,
        market_type=market_type,
    )


def _make_open_order(
    slug="btc-updown-5m-1",
    size=4.0,
    thesis_id="crypto-ref:BTC:5m:close",
    coin="BTC",
    cluster_id="",
    signal_epoch_id="",
    market_type="5m",
):
    return OpenOrder(
        order_id="order-1",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        market_slug=slug,
        question="Test?",
        condition_id="0xtest",
        token_id="0xup",
        strategy="updown",
        side="YES",
        confidence=0.8,
        reason="test",
        end_date=None,
        market_type=market_type,
        strategy_version=11,
        executor_type="LiveExecutor",
        limit_price=0.75,
        requested_size=size,
        requested_shares=size / 0.75,
        reserved_size=size,
        thesis_id=thesis_id,
        coin=coin,
        cluster_id=cluster_id,
        signal_epoch_id=signal_epoch_id,
    )


def test_allows_trade_in_fresh_state():
    rm = RiskManager(RiskConfig())
    check = rm.check_trade_allowed(_make_signal(), size=1.0, pending_trades=[], account_equity=100.0)
    assert check.allowed is True


def test_recommended_position_size_uses_equity_and_size_multiplier():
    rm = RiskManager(RiskConfig())
    normal = rm.recommended_position_size(_make_signal(size_multiplier=1.0), account_equity=100.0)
    reduced = rm.recommended_position_size(_make_signal(size_multiplier=0.5), account_equity=100.0)
    assert normal == 2.0
    assert reduced == 1.0


def test_blocks_second_position_same_coin():
    rm = RiskManager(RiskConfig())
    pending = [_make_trade(size=2.0)]
    check = rm.check_trade_allowed(
        _make_signal(slug="btc-updown-5m-2"),
        size=1.0,
        pending_trades=pending,
        account_equity=100.0,
    )
    assert check.allowed is False
    assert "position cap" in check.reason


def test_blocks_thesis_position_cap():
    rm = RiskManager(RiskConfig(max_positions_per_thesis=2))
    pending = [
        _make_trade(size=2.0, thesis_id="t1"),
        _make_trade(size=2.0, thesis_id="t1", slug="eth-updown-5m-2"),
    ]
    check = rm.check_trade_allowed(
        _make_signal(slug="sol-updown-5m-3", coin="SOL", thesis_id="t1"),
        size=1.0,
        pending_trades=pending,
        account_equity=100.0,
    )
    assert check.allowed is False
    assert "thesis position cap" in check.reason


def test_blocks_thesis_exposure_cap():
    rm = RiskManager(RiskConfig(max_positions_per_coin=5, max_positions_per_thesis=5))
    pending = [_make_trade(size=5.0, thesis_id="t1", slug="eth-updown-5m-1", coin="ETH")]
    check = rm.check_trade_allowed(
        _make_signal(slug="sol-updown-5m-2", coin="SOL", thesis_id="t1"),
        size=2.0,
        pending_trades=pending,
        account_equity=100.0,
    )
    assert check.allowed is False
    assert "thesis exposure cap" in check.reason


def test_daily_loss_limit_uses_equity_percentage():
    rm = RiskManager(RiskConfig(daily_max_loss=999.0))
    rm.record_trade_result(_make_trade(size=6.0, status="lost"))
    check = rm.check_trade_allowed(_make_signal(), size=1.0, pending_trades=[], account_equity=100.0)
    assert check.allowed is False
    assert "daily loss" in check.reason


def test_per_coin_cooldown_after_three_losses():
    rm = RiskManager(RiskConfig(daily_max_loss=999.0, daily_realized_loss_limit_pct=0.50))
    for _ in range(3):
        rm.record_trade_result(_make_trade(size=1.0, status="lost"))

    check = rm.check_trade_allowed(_make_signal(), size=1.0, pending_trades=[], account_equity=100.0)
    assert check.allowed is False
    assert "cooldown" in check.reason


def test_global_cooldown_after_five_losses():
    rm = RiskManager(RiskConfig(daily_max_loss=999.0, daily_realized_loss_limit_pct=0.50))
    for i in range(5):
        rm.record_trade_result(_make_trade(size=1.0, status="lost", slug=f"coin{i}-updown-5m-1"))

    check = rm.check_trade_allowed(
        _make_signal(slug="eth-updown-5m-1", coin="ETH"),
        size=1.0,
        pending_trades=[],
        account_equity=100.0,
    )
    assert check.allowed is False
    assert "global cooldown" in check.reason


def test_drawdown_kill_switch_blocks_trade():
    rm = RiskManager(RiskConfig(daily_max_loss=999.0))
    rm.observe_account_equity(100.0)
    check = rm.check_trade_allowed(_make_signal(), size=1.0, pending_trades=[], account_equity=89.0)
    assert check.allowed is False
    assert "kill switch" in check.reason


def test_bootstrap_from_history_restores_today_losses():
    now = datetime.now(timezone.utc)
    trades = [
        _make_trade(size=2.0, status="won", timestamp=now - timedelta(hours=2)),
        _make_trade(size=3.0, status="lost", timestamp=now - timedelta(hours=1)),
        _make_trade(size=4.0, status="lost", timestamp=now),
    ]
    rm = RiskManager(RiskConfig(daily_max_loss=999.0))

    rm.bootstrap_from_history(trades, account_equity=100.0)

    assert rm.daily_pnl == -7.0
    assert rm.peak_equity == 100.0


def test_open_orders_count_toward_exposure_and_coin_caps():
    rm = RiskManager(RiskConfig(max_positions_per_coin=5))
    open_orders = [_make_open_order(size=14.0)]
    check = rm.check_trade_allowed(
        _make_signal(slug="btc-updown-5m-2"),
        size=2.0,
        pending_trades=[],
        open_orders=open_orders,
        account_equity=100.0,
    )
    assert check.allowed is False
    assert "exposure cap" in check.reason or "BTC exposure" in check.reason


def test_cluster_position_cap_blocks_third_live_candidate():
    rm = RiskManager(RiskConfig(max_positions_per_coin=5, max_positions_per_cluster=2))
    pending = [
        _make_trade(slug="btc-updown-5m-1", coin="BTC", size=1.0, cluster_id="crypto_beta"),
        _make_trade(slug="sol-updown-5m-1", coin="SOL", size=1.0, cluster_id="crypto_beta"),
    ]

    check = rm.check_trade_allowed(
        _make_signal(slug="btc-updown-5m-2", coin="BTC", cluster_id="crypto_beta"),
        size=1.0,
        pending_trades=pending,
        account_equity=100.0,
    )

    assert check.allowed is False
    assert "cluster position cap" in check.reason


def test_non_candidate_coin_is_blocked_from_live_candidate_path():
    rm = RiskManager(RiskConfig())

    check = rm.check_trade_allowed(
        _make_signal(slug="ada-updown-5m-1", coin="ADA"),
        size=1.0,
        pending_trades=[],
        account_equity=100.0,
    )

    assert check.allowed is False
    assert "shadow-only" in check.reason


def test_live_candidate_no_reentry_blocks_same_side_window():
    rm = RiskManager(RiskConfig(max_positions_per_coin=5))
    pending = [
        _make_trade(
            slug="btc-updown-5m-1",
            coin="BTC",
            size=1.0,
            signal_epoch_id="epoch-1",
            market_type="5m",
        )
    ]

    check = rm.check_trade_allowed(
        _make_signal(
            slug="btc-updown-5m-2",
            coin="BTC",
            signal_epoch_id="epoch-2",
            market_type="5m",
        ),
        size=1.0,
        pending_trades=pending,
        account_equity=100.0,
    )

    assert check.allowed is False
    assert "no re-entry" in check.reason


def test_execution_quality_breach_moves_cluster_to_reduce_only():
    rm = RiskManager(RiskConfig(max_positions_per_coin=5))

    for _ in range(3):
        rm.record_execution_quality(
            coin="BTC",
            cluster_id="crypto_beta",
            slippage=0.03,
            expected_cost=0.01,
        )

    check = rm.check_trade_allowed(
        _make_signal(slug="btc-updown-5m-9", coin="BTC", cluster_id="crypto_beta"),
        size=1.0,
        pending_trades=[],
        account_equity=100.0,
    )

    assert check.allowed is False
    assert "reduce-only" in check.reason


def test_kill_switch_persisted_and_restored(tmp_path):
    state_file = tmp_path / "ks.json"
    rm = RiskManager(kill_switch_path=state_file)
    assert not rm.kill_switch_active

    rm.activate_kill_switch("test reason")
    assert state_file.exists()

    rm2 = RiskManager(kill_switch_path=state_file)
    assert rm2.kill_switch_active
    assert "test reason" in rm2._kill_switch_reason


def test_kill_switch_cleared_on_deactivate(tmp_path):
    state_file = tmp_path / "ks.json"
    rm = RiskManager(kill_switch_path=state_file)
    rm.activate_kill_switch("test")

    rm.deactivate_kill_switch()
    assert not rm.kill_switch_active

    rm2 = RiskManager(kill_switch_path=state_file)
    assert not rm2.kill_switch_active


def test_kill_switch_no_persistence_when_path_is_none():
    rm = RiskManager(kill_switch_path=None)
    rm.activate_kill_switch("test")
    assert rm.kill_switch_active
