from datetime import datetime, timezone

from config import Market, Signal, Trade, RiskConfig
from risk_manager import RiskManager


def _make_signal(slug="btc-updown-5m-1"):
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
    return Signal(market=market, strategy="updown", side="YES", confidence=0.8, reason="test")


def _make_trade(slug="btc-updown-5m-1", size=5.0, status="pending"):
    return Trade(
        timestamp=datetime.now(timezone.utc),
        market_slug=slug,
        question="Test?",
        strategy="updown",
        side="YES",
        entry_price=0.75,
        size=size,
        confidence=0.8,
        reason="test",
        status=status,
    )


class TestRiskManagerAllowsTrades:
    def test_allows_trade_fresh_state(self):
        rm = RiskManager(RiskConfig())
        check = rm.check_trade_allowed(_make_signal(), size=5.0, pending_trades=[])
        assert check.allowed is True

    def test_allows_multiple_small_trades(self):
        rm = RiskManager(RiskConfig(max_open_exposure=50.0, max_exposure_per_coin=50.0))
        pending = [_make_trade(size=5.0) for _ in range(3)]
        check = rm.check_trade_allowed(_make_signal(), size=5.0, pending_trades=pending)
        assert check.allowed is True


class TestDailyLossLimit:
    def test_blocks_on_daily_loss_limit(self):
        rm = RiskManager(RiskConfig(daily_max_loss=10.0))
        # Record losses exceeding limit
        for _ in range(3):
            trade = _make_trade(size=4.0, status="lost")
            rm.record_trade_result(trade)

        check = rm.check_trade_allowed(_make_signal(), size=5.0, pending_trades=[])
        assert check.allowed is False
        assert "daily loss" in check.reason

    def test_allows_after_daily_reset(self):
        rm = RiskManager(RiskConfig(daily_max_loss=5.0))
        trade = _make_trade(size=6.0, status="lost")
        rm.record_trade_result(trade)

        # Blocked
        check = rm.check_trade_allowed(_make_signal(), size=1.0, pending_trades=[])
        assert check.allowed is False

        # Manually reset (simulates new day)
        rm._daily_losses = 0.0
        check = rm.check_trade_allowed(_make_signal(), size=1.0, pending_trades=[])
        assert check.allowed is True


class TestExposureCap:
    def test_blocks_on_exposure_cap(self):
        rm = RiskManager(RiskConfig(max_open_exposure=20.0))
        pending = [_make_trade(size=8.0) for _ in range(2)]  # 16 existing
        check = rm.check_trade_allowed(_make_signal(), size=5.0, pending_trades=pending)
        assert check.allowed is False
        assert "exposure cap" in check.reason

    def test_allows_under_exposure_cap(self):
        rm = RiskManager(RiskConfig(max_open_exposure=20.0))
        pending = [_make_trade(size=5.0)]  # 5 existing
        check = rm.check_trade_allowed(_make_signal(), size=5.0, pending_trades=pending)
        assert check.allowed is True


class TestConsecutiveLossCooldown:
    def test_blocks_after_consecutive_losses(self):
        rm = RiskManager(RiskConfig(max_consecutive_losses=3, daily_max_loss=999.0))
        for _ in range(3):
            rm.record_trade_result(_make_trade(status="lost"))

        check = rm.check_trade_allowed(_make_signal(), size=1.0, pending_trades=[])
        assert check.allowed is False
        assert "consecutive loss" in check.reason

    def test_win_resets_consecutive_losses(self):
        rm = RiskManager(RiskConfig(max_consecutive_losses=3, daily_max_loss=999.0))
        for _ in range(2):
            rm.record_trade_result(_make_trade(status="lost"))
        rm.record_trade_result(_make_trade(status="won"))

        assert rm.consecutive_losses == 0
        check = rm.check_trade_allowed(_make_signal(), size=1.0, pending_trades=[])
        assert check.allowed is True


class TestKillSwitch:
    def test_kill_switch_blocks_everything(self):
        rm = RiskManager(RiskConfig())
        rm.activate_kill_switch("manual test")

        check = rm.check_trade_allowed(_make_signal(), size=1.0, pending_trades=[])
        assert check.allowed is False
        assert "kill switch" in check.reason

    def test_deactivate_kill_switch(self):
        rm = RiskManager(RiskConfig())
        rm.activate_kill_switch("test")
        rm.deactivate_kill_switch()

        check = rm.check_trade_allowed(_make_signal(), size=1.0, pending_trades=[])
        assert check.allowed is True

    def test_auto_kill_switch_at_2x_daily_loss(self):
        rm = RiskManager(RiskConfig(daily_max_loss=5.0))
        for _ in range(3):
            rm.record_trade_result(_make_trade(size=4.0, status="lost"))

        assert rm.kill_switch_active is True


class TestPerCoinExposure:
    def test_blocks_per_coin_exposure(self):
        rm = RiskManager(RiskConfig(max_exposure_per_coin=8.0, max_open_exposure=100.0))
        pending = [_make_trade(slug="btc-updown-5m-1", size=5.0)]
        check = rm.check_trade_allowed(
            _make_signal(slug="btc-updown-5m-2"), size=4.0, pending_trades=pending
        )
        assert check.allowed is False
        assert "BTC exposure" in check.reason

    def test_allows_different_coin(self):
        rm = RiskManager(RiskConfig(max_exposure_per_coin=8.0, max_open_exposure=100.0))
        pending = [_make_trade(slug="btc-updown-5m-1", size=7.0)]
        check = rm.check_trade_allowed(
            _make_signal(slug="eth-updown-5m-1"), size=5.0, pending_trades=pending
        )
        assert check.allowed is True
