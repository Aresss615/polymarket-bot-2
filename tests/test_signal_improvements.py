"""Tests for v8 signal improvements: BTC NO blacklist, NO premium, fee-aware edge."""

from unittest.mock import patch
from datetime import datetime, timezone, timedelta

from config import UpDownMarket, Market
from level_analyzer import analyze_updown_market


def _make_updown(coin="SOL", up_price=0.80, down_price=0.20, secs=20, interval=5):
    market = Market(
        condition_id="0xtest",
        question=f"{coin} Up or Down?",
        slug=f"{coin.lower()}-updown-{interval}m-123",
        outcomes=["Up", "Down"],
        outcome_prices=[up_price, down_price],
        token_ids=["0xup", "0xdown"],
        end_date=datetime.now(timezone.utc) + timedelta(seconds=secs),
        active=True,
    )
    return UpDownMarket(
        market=market, coin=coin, interval_minutes=interval,
        seconds_to_close=secs, up_outcome_index=0,
    )


@patch("level_analyzer.is_price_stale", return_value=False)
class TestBtcNoBlacklist:
    @patch("level_analyzer.get_price_momentum", return_value=-0.005)
    def test_btc_no_blocked(self, mock_mom, mock_stale):
        """BTC NO trades are blocked regardless of edge."""
        udm = _make_updown(coin="BTC", up_price=0.15, down_price=0.85)
        signal, reason = analyze_updown_market(udm)
        assert signal is None
        assert "BTC NO blacklisted" in reason

    @patch("level_analyzer.get_price_momentum", return_value=0.005)
    def test_btc_yes_still_allowed(self, mock_mom, mock_stale):
        """BTC YES trades are not affected by the blacklist."""
        udm = _make_updown(coin="BTC", up_price=0.87, down_price=0.13)
        signal, reason = analyze_updown_market(udm)
        # May or may not generate signal depending on edge, but should NOT be blacklisted
        if signal is None:
            assert "BTC NO blacklisted" not in reason

    @patch("level_analyzer.get_price_momentum", return_value=-0.005)
    def test_other_coin_no_not_blocked(self, mock_mom, mock_stale):
        """Non-BTC NO trades are not affected by the BTC blacklist."""
        udm = _make_updown(coin="XRP", up_price=0.13, down_price=0.87)
        signal, reason = analyze_updown_market(udm)
        if signal is None:
            assert "BTC NO blacklisted" not in reason


@patch("level_analyzer.is_price_stale", return_value=False)
class TestNoSideEdgePremium:
    @patch("level_analyzer.get_price_momentum", return_value=0.005)
    def test_yes_passes_at_lower_edge(self, mock_mom, mock_stale):
        """YES side should pass with standard min_edge (no premium)."""
        # SOL at 0.83 UP → YES side, entry at 0.83, strong signal
        udm = _make_updown(coin="SOL", up_price=0.83, down_price=0.17)
        signal, reason = analyze_updown_market(udm)
        assert signal is not None
        assert signal.side == "YES"

    @patch("level_analyzer.get_price_momentum", return_value=-0.005)
    def test_no_requires_more_edge(self, mock_mom, mock_stale):
        """NO side at same absolute edge as YES should be filtered due to +3% premium."""
        # SOL at 0.18 DOWN → NO side, entry at 0.82
        # This edge level would pass for YES but fails for NO
        udm = _make_updown(coin="SOL", up_price=0.18, down_price=0.82)
        signal, reason = analyze_updown_market(udm)
        assert signal is None
        assert "skip" in reason


@patch("level_analyzer.is_price_stale", return_value=False)
class TestFeeAwareEdge:
    @patch("level_analyzer.get_price_momentum", return_value=0.001)
    def test_near_50_filtered_by_fees(self, mock_mom, mock_stale):
        """Trades near 0.50 have highest fees (1.8%) and should be filtered more aggressively."""
        # Price at 0.62 (just above skip band), entry near 0.62
        # Fee at 0.62: 0.018 * (1 - 2*0.12) = 0.018 * 0.76 = 1.37%
        # This eats into edge significantly
        udm = _make_updown(coin="SOL", up_price=0.62, down_price=0.38)
        signal, reason = analyze_updown_market(udm)
        # With the fee deduction, this marginal signal should be filtered
        assert signal is None
        assert "fee" in reason or "skip" in reason

    @patch("level_analyzer.get_price_momentum", return_value=0.003)
    def test_extreme_price_low_fees_passes(self, mock_mom, mock_stale):
        """Trades at extreme prices have low fees and strong edge, should pass."""
        # SOL at 0.85 UP → YES side, very low fee (~0.5%)
        udm = _make_updown(coin="SOL", up_price=0.85, down_price=0.15)
        signal, reason = analyze_updown_market(udm)
        assert signal is not None
        assert signal.side == "YES"
