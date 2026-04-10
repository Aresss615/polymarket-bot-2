from datetime import datetime, timezone

from config import Market, UpDownMarket
from level_analyzer import analyze_updown_market


def _make_updown(coin="BTC", up_price=0.60, down_price=0.40, secs=45, up_idx=0):
    outcomes = ["Up", "Down"] if up_idx == 0 else ["Down", "Up"]
    prices = [up_price, down_price] if up_idx == 0 else [down_price, up_price]
    m = Market(
        condition_id="0x1",
        question=f"{coin}-USDT Up or Down?",
        slug=f"{coin.lower()}-updown-5m-123",
        outcomes=outcomes,
        outcome_prices=prices,
        token_ids=["0xa", "0xb"],
        end_date=datetime(2026, 4, 10, 21, 0, tzinfo=timezone.utc),
        active=True,
    )
    return UpDownMarket(market=m, coin=coin, interval_minutes=5, seconds_to_close=secs, up_outcome_index=up_idx)


def test_signal_yes_when_market_favors_up():
    """UP at 0.60 -> model boosts to 0.65, edge +5% -> YES."""
    udm = _make_updown(up_price=0.60, down_price=0.40)
    signal = analyze_updown_market(udm)
    assert signal is not None
    assert signal.side == "YES"
    assert signal.strategy == "updown"
    assert signal.confidence > 0


def test_signal_no_when_market_favors_down():
    """UP at 0.40 -> model pushes to 0.35, edge on YES is -5% -> NO."""
    udm = _make_updown(up_price=0.40, down_price=0.60)
    signal = analyze_updown_market(udm)
    assert signal is not None
    assert signal.side == "NO"


def test_no_signal_at_50_50():
    """Market at 50/50 -> no direction, no edge."""
    udm = _make_updown(up_price=0.50, down_price=0.50)
    signal = analyze_updown_market(udm)
    assert signal is None


def test_no_signal_when_near_certain_high():
    """UP at 0.95 -> skip, no room for edge."""
    udm = _make_updown(up_price=0.95, down_price=0.05)
    signal = analyze_updown_market(udm)
    assert signal is None


def test_no_signal_when_near_certain_low():
    """UP at 0.05 -> skip, no room for edge."""
    udm = _make_updown(up_price=0.05, down_price=0.95)
    signal = analyze_updown_market(udm)
    assert signal is None


def test_inverted_up_index():
    """When UP is at index 1, prices are read correctly."""
    # outcomes=["Down", "Up"], prices=[0.40, 0.60], up_idx=1
    # yes_price=0.40, implied_up=1-0.40=0.60 -> boost to 0.65
    # model_yes_prob=1-0.65=0.35, edge=0.35-0.40=-0.05 -> NO
    udm = _make_updown(up_price=0.60, down_price=0.40, up_idx=1)
    signal = analyze_updown_market(udm)
    assert signal is not None
    assert signal.side == "NO"


def test_signal_includes_reason():
    udm = _make_updown(up_price=0.60, down_price=0.40)
    signal = analyze_updown_market(udm)
    assert signal is not None
    assert "BTC" in signal.reason
    assert "UP" in signal.reason
    assert "45s" in signal.reason


def test_no_signal_insufficient_prices():
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
    udm = UpDownMarket(market=m, coin="BTC", interval_minutes=5, seconds_to_close=45, up_outcome_index=0)
    signal = analyze_updown_market(udm)
    assert signal is None
