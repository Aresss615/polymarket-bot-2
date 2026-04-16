"""Focused regression tests for the v11 deterministic signal rules."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from config import STRATEGY_MODE_SHADOW, Market, UpDownMarket
from level_analyzer import analyze_updown_market_detail


@pytest.fixture(autouse=True)
def _mock_book_snapshot():
    with patch(
        "level_analyzer.MARKET_CACHE.snapshot",
        return_value={
            "best_bid": 0.69,
            "best_ask": 0.70,
            "spread": 0.01,
            "book_age_ms": 250.0,
            "tick_size": 0.01,
        },
    ):
        yield


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
        market=market,
        coin=coin,
        interval_minutes=interval,
        seconds_to_close=secs,
        up_outcome_index=0,
    )


def _snapshot(
    *,
    ret,
    zscore,
    age=0.2,
    price=100.0,
    interval_open=None,
    interval_high=None,
    interval_low=None,
    interval_close=None,
    interval_return=None,
    late_return_60s=None,
    late_return_20s=None,
    body_ratio=None,
    chainlink_price=100.0,
    chainlink_age=0.2,
):
    effective_price = interval_close if interval_close is not None else price
    derived_interval_return = interval_return if interval_return is not None else ret
    derived_window_open = interval_open if interval_open is not None else effective_price / (1.0 + derived_interval_return)
    return {
        "coin": "SOL",
        "price": effective_price,
        "active_reference_price": effective_price,
        "chainlink_price": chainlink_price,
        "age_seconds": age,
        "active_reference_age_seconds": age,
        "chainlink_age_seconds": chainlink_age,
        "return_lookback": ret,
        "zscore": zscore,
        "interval_open": interval_open,
        "interval_high": interval_high,
        "interval_low": interval_low,
        "interval_close": interval_close,
        "interval_return": interval_return,
        "late_return_60s": late_return_60s if late_return_60s is not None else derived_interval_return,
        "late_return_20s": late_return_20s if late_return_20s is not None else derived_interval_return,
        "body_ratio": body_ratio if body_ratio is not None else 1.0,
        "window_open_price": derived_window_open,
        "window_open_source": "test_anchor",
        "window_open_price_trusted": True,
        "source": "test",
    }


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=-0.0040,
        zscore=1.2,
        interval_open=100.0,
        interval_high=100.0,
        interval_low=99.5,
        interval_close=99.6,
        interval_return=-0.0040,
        late_return_60s=-0.0015,
        late_return_20s=-0.0008,
        body_ratio=0.8,
    ),
)
def test_btc_no_strong_toxic_flow_is_blocked(mock_snapshot):
    analysis = analyze_updown_market_detail(_make_updown(coin="BTC", up_price=0.85, down_price=0.15))
    assert analysis.signal is None
    assert "toxic flow" in analysis.reason.lower()


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=-0.0040,
        zscore=0.7,
        interval_open=100.0,
        interval_high=100.0,
        interval_low=99.5,
        interval_close=99.6,
        interval_return=-0.0040,
        late_return_60s=-0.0015,
        late_return_20s=-0.0008,
        body_ratio=0.8,
    ),
)
def test_btc_no_weak_toxic_flow_is_shadow_and_half_size(mock_snapshot):
    analysis = analyze_updown_market_detail(_make_updown(coin="BTC", up_price=0.85, down_price=0.15))
    assert analysis.signal is not None
    assert analysis.signal.side == "NO"
    assert analysis.signal.strategy_mode == STRATEGY_MODE_SHADOW
    assert analysis.signal.size_multiplier == 0.625


@patch("level_analyzer.get_reference_snapshot", return_value=_snapshot(ret=0.00005, zscore=0.0))
def test_price_neutral_setup_requires_higher_threshold(mock_snapshot):
    analysis = analyze_updown_market_detail(_make_updown(up_price=0.58, down_price=0.42))
    assert analysis.signal is None
    assert analysis.strategy_route == "range_or_flat"


@patch("level_analyzer.get_reference_snapshot", return_value=_snapshot(ret=0.0060, zscore=1.2))
def test_15m_candidate_stays_shadow_even_when_passing(mock_snapshot):
    analysis = analyze_updown_market_detail(_make_updown(interval=15, secs=240, up_price=0.60, down_price=0.40))
    assert analysis.signal is not None
    assert analysis.signal.strategy_mode == STRATEGY_MODE_SHADOW


@patch("level_analyzer.get_reference_snapshot", return_value=_snapshot(ret=0.0036, zscore=1.0))
def test_fee_aware_edge_can_still_pass_for_strong_setups(mock_snapshot):
    analysis = analyze_updown_market_detail(_make_updown(up_price=0.70, down_price=0.30))
    assert analysis.signal is not None
    assert analysis.effective_edge is not None
    assert analysis.effective_edge > analysis.estimated_fee
