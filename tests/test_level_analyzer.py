import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from config import Market, UpDownMarket
from level_analyzer import analyze_updown_market


@pytest.fixture(autouse=True)
def _mock_price_freshness():
    """Default: price data is fresh in tests."""
    with patch("level_analyzer.is_price_stale", return_value=False):
        yield


def _make_updown(coin="BTC", up_price=0.75, down_price=0.25, secs=30, up_idx=0):
    outcomes = ["Up", "Down"] if up_idx == 0 else ["Down", "Up"]
    prices = [up_price, down_price] if up_idx == 0 else [down_price, up_price]
    end_date = datetime.now(timezone.utc) + timedelta(seconds=secs)
    m = Market(
        condition_id="0x1",
        question=f"{coin}-USDT Up or Down?",
        slug=f"{coin.lower()}-updown-5m-123",
        outcomes=outcomes,
        outcome_prices=prices,
        token_ids=["0xa", "0xb"],
        end_date=end_date,
        active=True,
    )
    return UpDownMarket(market=m, coin=coin, interval_minutes=5, seconds_to_close=secs, up_outcome_index=up_idx)


@patch("level_analyzer.get_price_momentum", return_value=0.002)
def test_signal_yes_when_market_favors_up_with_confirmation(mock_mom):
    """UP at 0.82 with positive momentum -> YES (above 70-80% edge floor zone)."""
    udm = _make_updown(coin="SOL", up_price=0.82, down_price=0.18)
    signal, reason = analyze_updown_market(udm)
    assert signal is not None
    assert signal.side == "YES"
    assert signal.strategy == "updown"
    assert signal.confidence > 0


@patch("level_analyzer.get_price_momentum", return_value=-0.002)
def test_no_side_requires_extra_edge(mock_mom):
    """NO side requires 1% extra edge (reduced from 3%). Strong NO signals pass.

    UP at 0.18 with negative momentum -> strong DOWN signal -> buy NO.
    With reduced NO premium (1%), this trade should pass.
    """
    udm = _make_updown(coin="SOL", up_price=0.18, down_price=0.82)
    signal, reason = analyze_updown_market(udm)
    assert signal is not None
    assert signal.side == "NO"


@patch("level_analyzer.get_price_momentum", return_value=None)
def test_no_signal_at_50_50(mock_mom):
    """Market at 50/50 -> in skip band, no signal."""
    udm = _make_updown(up_price=0.50, down_price=0.50)
    signal, reason = analyze_updown_market(udm)
    assert signal is None
    assert "coin-flip" in reason


@patch("level_analyzer.get_price_momentum", return_value=None)
def test_no_signal_in_skip_band(mock_mom):
    """Market at 55/45 -> inside 38-62% skip band."""
    udm = _make_updown(up_price=0.55, down_price=0.45)
    signal, reason = analyze_updown_market(udm)
    assert signal is None
    assert "coin-flip" in reason


@patch("level_analyzer.get_price_momentum", return_value=None)
def test_no_signal_when_near_certain_high(mock_mom):
    """UP at 0.95 -> skip, no room for edge."""
    udm = _make_updown(up_price=0.95, down_price=0.05)
    signal, reason = analyze_updown_market(udm)
    assert signal is None
    assert "near-certain" in reason


@patch("level_analyzer.get_price_momentum", return_value=None)
def test_no_signal_when_near_certain_low(mock_mom):
    """UP at 0.05 -> skip, no room for edge."""
    udm = _make_updown(up_price=0.05, down_price=0.95)
    signal, reason = analyze_updown_market(udm)
    assert signal is None
    assert "near-certain" in reason


@patch("level_analyzer.get_price_momentum", return_value=-0.003)
def test_no_signal_when_price_contradicts(mock_mom):
    """UP at 0.75 but price falling -> skip (contradiction)."""
    udm = _make_updown(coin="SOL", up_price=0.75, down_price=0.25)
    signal, reason = analyze_updown_market(udm)
    assert signal is None
    assert "contradicts" in reason


@patch("level_analyzer.get_price_momentum", return_value=-0.002)
def test_inverted_up_index(mock_mom):
    """When UP is at index 1, prices are read correctly."""
    udm = _make_updown(coin="SOL", up_price=0.18, down_price=0.82, up_idx=1)
    signal, reason = analyze_updown_market(udm)
    assert signal is not None
    assert signal.side == "YES"


@patch("level_analyzer.get_price_momentum", return_value=0.002)
def test_signal_includes_reason(mock_mom):
    udm = _make_updown(coin="SOL", up_price=0.82, down_price=0.18)
    signal, reason = analyze_updown_market(udm)
    assert signal is not None
    assert "SOL" in signal.reason
    assert "UP" in signal.reason
    assert "30s" in signal.reason


@patch("level_analyzer.get_price_momentum", return_value=None)
def test_no_signal_insufficient_prices(mock_mom):
    """Market with only one price -> skip."""
    m = Market(
        condition_id="0x2",
        question="BTC Up or Down?",
        slug="btc-updown-5m-456",
        outcomes=["Up"],
        outcome_prices=[0.60],
        token_ids=["0xa"],
        end_date=datetime(2026, 4, 10, 21, 0, tzinfo=timezone.utc),
        active=True,
    )
    udm = UpDownMarket(market=m, coin="BTC", interval_minutes=5, seconds_to_close=30, up_outcome_index=0)
    signal, reason = analyze_updown_market(udm)
    assert signal is None


@patch("level_analyzer.get_price_momentum", return_value=None)
def test_strong_signal_no_momentum_still_trades(mock_mom):
    """Very strong signal (83%) without price data still trades.
    strength=0.33, boost=0.02+0.33*0.15=0.070, entry=0.83 (above 0.80 floor)."""
    udm = _make_updown(coin="SOL", up_price=0.83, down_price=0.17)
    signal, reason = analyze_updown_market(udm)
    assert signal is not None
    assert signal.side == "YES"


@patch("level_analyzer.get_price_momentum", return_value=0.001)
def test_moderate_signal_with_momentum_trades(mock_mom):
    """Strong signal (83%) with price confirmation -> trade (entry 0.83, enough edge after fees)."""
    udm = _make_updown(coin="SOL", up_price=0.83, down_price=0.17)
    signal, reason = analyze_updown_market(udm)
    assert signal is not None
    assert signal.side == "YES"


@patch("level_analyzer.get_price_momentum", return_value=None)
def test_moderate_signal_no_momentum_skips(mock_mom):
    """Moderate signal (68%) without price confirmation -> too weak."""
    udm = _make_updown(coin="SOL", up_price=0.68, down_price=0.32)
    signal, reason = analyze_updown_market(udm)
    # 68% is outside skip band, but strength=0.18 < 0.20, no momentum
    assert signal is None
    assert "weak signal" in reason


@patch("level_analyzer.get_price_momentum", return_value=0.002)
def test_btc_requires_higher_edge(mock_mom):
    """BTC at 0.75 with momentum -> edge ~5.8% < BTC min 8% -> skip."""
    udm = _make_updown(coin="BTC", up_price=0.75, down_price=0.25)
    signal, reason = analyze_updown_market(udm)
    assert signal is None
    assert "edge" in reason


@patch("level_analyzer.get_price_momentum", return_value=-0.005)
def test_btc_no_blacklisted(mock_mom):
    """BTC NO trades are blocked entirely (historical ~48% WR)."""
    udm = _make_updown(coin="BTC", up_price=0.15, down_price=0.85)
    signal, reason = analyze_updown_market(udm)
    assert signal is None
    assert "blacklisted" in reason.lower()


@patch("level_analyzer.get_price_momentum", return_value=0.002)
def test_btc_rejected_high_min_edge(mock_mom):
    """BTC requires 10% edge (59% historical WR) — boost formula can't reach it."""
    udm = _make_updown(coin="BTC", up_price=0.86, down_price=0.14)
    signal, reason = analyze_updown_market(udm)
    assert signal is None


@patch("level_analyzer.get_price_momentum", return_value=0.002)
def test_70_80_zone_requires_higher_edge(mock_mom):
    """Entry price 0.75 requires 7% edge (price-dependent floor), not just 5%."""
    # SOL at 0.75 with momentum: strength=0.25, boost=0.0675, edge=6.75% < 7%
    udm = _make_updown(coin="SOL", up_price=0.75, down_price=0.25)
    signal, reason = analyze_updown_market(udm)
    assert signal is None  # rejected by 70-80% edge floor
    assert "edge" in reason


@patch("level_analyzer.is_price_stale", return_value=True)
@patch("level_analyzer.get_price_momentum", return_value=0.002)
def test_skip_when_price_data_stale(mock_mom, mock_stale):
    """If price data is stale (>30s old), skip the trade."""
    udm = _make_updown(coin="SOL", up_price=0.82, down_price=0.18)
    signal, reason = analyze_updown_market(udm)
    assert signal is None
    assert "stale" in reason.lower()


@patch("level_analyzer.get_price_momentum", return_value=0.002)
def test_15m_uses_higher_min_seconds(mock_mom):
    """15m markets use MIN_SECONDS_TO_TRADE_15M (10s), not 5s."""
    # Create a 15m market with only 8 seconds remaining
    udm = _make_updown(coin="SOL", up_price=0.82, down_price=0.18, secs=8)
    from config import UpDownMarket
    udm_15m = UpDownMarket(
        market=udm.market,
        coin="SOL",
        interval_minutes=15,
        seconds_to_close=8,
        up_outcome_index=0,
    )
    udm_15m.market.slug = "sol-updown-15m-123"
    signal, reason = analyze_updown_market(udm_15m)
    assert signal is None
    assert "left" in reason  # "8s left < 10s min"
