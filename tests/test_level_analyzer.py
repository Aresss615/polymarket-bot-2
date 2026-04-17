from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from config import STRATEGY_MODE_LIVE, STRATEGY_MODE_SHADOW, Market, UpDownMarket
from level_analyzer import analyze_updown_market, analyze_updown_market_detail


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


def _make_updown(coin="SOL", up_price=0.78, down_price=0.22, secs=20, interval=5, up_idx=0):
    outcomes = ["Up", "Down"] if up_idx == 0 else ["Down", "Up"]
    prices = [up_price, down_price] if up_idx == 0 else [down_price, up_price]
    token_ids = ["0xup", "0xdown"] if up_idx == 0 else ["0xdown", "0xup"]
    market = Market(
        condition_id="0x1",
        question=f"{coin} Up or Down?",
        slug=f"{coin.lower()}-updown-{interval}m-123",
        outcomes=outcomes,
        outcome_prices=prices,
        token_ids=token_ids,
        end_date=datetime.now(timezone.utc) + timedelta(seconds=secs),
        active=True,
    )
    return UpDownMarket(
        market=market,
        coin=coin,
        interval_minutes=interval,
        seconds_to_close=secs,
        up_outcome_index=up_idx,
    )


def _snapshot(
    *,
    price=100.0,
    age=0.2,
    ret=0.0012,
    zscore=0.4,
    chainlink_price=None,
    chainlink_age=None,
    interval_open=None,
    interval_high=None,
    interval_low=None,
    interval_close=None,
    interval_return=None,
    late_return_60s=None,
    late_return_20s=None,
    body_ratio=None,
    wick_imbalance=None,
    window_open_price=None,
    window_open_source="test_anchor",
    window_open_price_trusted=None,
    window_open_anchor_age_seconds=None,
):
    effective_price = interval_close if interval_close is not None else price
    derived_interval_return = interval_return if interval_return is not None else ret
    derived_window_open = window_open_price
    if derived_window_open is None:
        if interval_open is not None:
            derived_window_open = interval_open
        elif effective_price is not None and derived_interval_return is not None:
            derived_window_open = effective_price / (1.0 + derived_interval_return)
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
        "wick_imbalance": wick_imbalance,
        "window_open_price": derived_window_open,
        "window_open_source": window_open_source,
        "window_open_price_trusted": (
            derived_window_open is not None
            if window_open_price_trusted is None
            else window_open_price_trusted
        ),
        "window_open_anchor_age_seconds": window_open_anchor_age_seconds,
        "source": "test",
    }


@patch("level_analyzer.get_reference_snapshot", return_value=_snapshot(ret=0.0036, zscore=1.0))
def test_live_signal_emits_positive_net_edge(mock_snapshot):
    udm = _make_updown(up_price=0.70, down_price=0.30)
    analysis = analyze_updown_market_detail(udm)
    assert analysis.signal is not None
    assert analysis.signal.side == "YES"
    assert analysis.signal.strategy_mode == STRATEGY_MODE_LIVE
    assert analysis.effective_edge is not None and analysis.effective_edge > 0
    assert analysis.reference_age_seconds is not None and analysis.reference_age_seconds < 1


@patch("level_analyzer.get_reference_snapshot", return_value=_snapshot(ret=0.00005, zscore=0.0))
def test_neutral_setup_requires_higher_net_edge(mock_snapshot):
    udm = _make_updown(up_price=0.58, down_price=0.42)
    signal, reason = analyze_updown_market(udm)
    assert signal is None
    assert "flat window shadow only" in reason


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(chainlink_price=100.0, chainlink_age=0.3, ret=0.0060, zscore=1.2),
)
def test_shadow_record_includes_pending_signal_status(mock_snapshot):
    udm = _make_updown(interval=15, secs=240, up_price=0.60, down_price=0.40)
    analysis = analyze_updown_market_detail(udm)

    row = analysis.to_record()

    assert row["signal_id"]
    assert row["snapshot_event"] == "analysis"
    assert row["signal_status"] == "pending"
    assert row["resolved_side"] == ""


@patch("level_analyzer.get_reference_snapshot", return_value=_snapshot(age=9.5))
def test_stale_reference_skips(mock_snapshot):
    udm = _make_updown()
    signal, reason = analyze_updown_market(udm)
    assert signal is None
    assert "stale" in reason.lower()


@patch("level_analyzer.ensure_reference_recent", return_value=True)
@patch(
    "level_analyzer.get_reference_snapshot",
    side_effect=[_snapshot(age=9.5), _snapshot(ret=0.0036, zscore=1.0)],
)
def test_stale_reference_refreshes_before_skip(mock_snapshot, mock_refresh):
    udm = _make_updown()
    analysis = analyze_updown_market_detail(udm)
    assert analysis.signal is not None
    assert analysis.price_state != "stale"
    assert mock_snapshot.call_count == 2
    assert mock_refresh.called


@patch("level_analyzer.get_reference_snapshot", return_value=_snapshot())
def test_invalid_prices_skip(mock_snapshot):
    market = Market(
        condition_id="0x2",
        question="SOL Up or Down?",
        slug="sol-updown-5m-456",
        outcomes=["Up"],
        outcome_prices=[0.8],
        token_ids=["0xup"],
        end_date=datetime.now(timezone.utc) + timedelta(seconds=20),
        active=True,
    )
    udm = UpDownMarket(market=market, coin="SOL", interval_minutes=5, seconds_to_close=20, up_outcome_index=0)
    signal, reason = analyze_updown_market(udm)
    assert signal is None
    assert "<2 outcome prices" in reason


@patch("level_analyzer.get_reference_snapshot", return_value=_snapshot(chainlink_price=None, chainlink_age=None))
def test_15m_requires_chainlink(mock_snapshot):
    udm = _make_updown(interval=15, secs=240)
    signal, reason = analyze_updown_market(udm)
    assert signal is None
    assert "Chainlink" in reason


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(chainlink_price=100.0, chainlink_age=0.3, ret=0.0060, zscore=1.2),
)
def test_15m_signal_is_shadow_only_by_default(mock_snapshot):
    udm = _make_updown(interval=15, secs=240, up_price=0.60, down_price=0.40)
    analysis = analyze_updown_market_detail(udm)
    assert analysis.signal is not None
    assert analysis.signal.strategy_mode == STRATEGY_MODE_SHADOW
    assert analysis.strategy_mode == STRATEGY_MODE_SHADOW


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=-0.0040,
        zscore=1.3,
        interval_open=100.0,
        interval_high=100.0,
        interval_low=99.5,
        interval_close=99.6,
        interval_return=-0.0040,
        late_return_60s=-0.0015,
        late_return_20s=-0.0008,
        body_ratio=0.80,
    ),
)
def test_btc_toxic_flow_blocks_no_signal(mock_snapshot):
    udm = _make_updown(coin="BTC", up_price=0.85, down_price=0.15)
    signal, reason = analyze_updown_market(udm)
    assert signal is None
    assert "toxic flow" in reason.lower()


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
        body_ratio=0.80,
    ),
)
def test_btc_no_weak_toxic_flow_reduces_size_and_stays_shadow(mock_snapshot):
    udm = _make_updown(coin="BTC", up_price=0.85, down_price=0.15)
    analysis = analyze_updown_market_detail(udm)
    assert analysis.signal is not None
    assert analysis.signal.side == "NO"
    assert analysis.signal.strategy_mode == STRATEGY_MODE_SHADOW
    assert analysis.signal.size_multiplier == 0.625


@patch("level_analyzer.get_reference_snapshot", return_value=_snapshot(ret=0.0038, zscore=0.8))
def test_inverted_up_index_is_supported(mock_snapshot):
    udm = _make_updown(up_price=0.18, down_price=0.82, up_idx=1)
    analysis = analyze_updown_market_detail(udm)
    assert analysis.signal is not None
    assert analysis.signal.side == "YES"
    assert analysis.direction == "SELL"


@patch(
    "level_analyzer.get_reference_snapshot",
        return_value=_snapshot(
            ret=0.0040,
            zscore=0.0,
            interval_open=100.0,
            interval_high=100.4,
            interval_low=99.9,
            interval_close=100.4,
            interval_return=0.0040,
            late_return_60s=0.0010,
            late_return_20s=0.0004,
            body_ratio=0.75,
            wick_imbalance=0.05,
        ),
)
def test_strong_move_95c_skips_as_too_late_or_overpriced(mock_snapshot):
    udm = _make_updown(up_price=0.95, down_price=0.05)
    with patch(
        "level_analyzer.MARKET_CACHE.snapshot",
        return_value={
            "best_bid": 0.94,
            "best_ask": 0.95,
            "spread": 0.01,
            "midpoint": 0.945,
            "book_age_ms": 250.0,
            "tick_size": 0.01,
        },
    ):
        analysis = analyze_updown_market_detail(udm)
    assert analysis.signal is None
    assert analysis.actual_move_regime == "strong"
    assert analysis.strategy_route == "too_late_or_overpriced"
    assert "too late or overpriced" in analysis.reason


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=0.0030,
        zscore=0.2,
        interval_open=100.0,
        interval_high=100.4,
        interval_low=99.95,
        interval_close=100.4,
        interval_return=0.0040,
        late_return_60s=0.0012,
        late_return_20s=0.0005,
        body_ratio=0.80,
        wick_imbalance=0.02,
    ),
)
def test_strong_follow_trend_boosts_size_without_excess_confidence(mock_snapshot):
    udm = _make_updown(up_price=0.70, down_price=0.30)
    analysis = analyze_updown_market_detail(udm)
    assert analysis.signal is not None
    assert analysis.actual_move_regime == "strong"
    assert analysis.strategy_route == "trend_follow_candidate"
    assert analysis.signal.size_multiplier == 1.25
    assert analysis.signal.confidence <= 0.90


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=-0.0015,
        zscore=-0.1,
        interval_open=100.0,
        interval_high=100.1,
        interval_low=99.7,
        interval_close=99.85,
        interval_return=-0.0015,
        late_return_60s=-0.0006,
        late_return_20s=0.0002,
        body_ratio=0.30,
        wick_imbalance=-0.15,
    ),
)
def test_mixed_regime_caps_confidence_and_uses_side_aware_reason(mock_snapshot):
    udm = _make_updown(up_price=0.75, down_price=0.25)
    analysis = analyze_updown_market_detail(udm)
    assert analysis.signal is None
    assert analysis.actual_move_regime == "mid"
    assert analysis.strategy_route == "mid_skip"
    assert "mid regime no trade" in analysis.reason


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=-0.0030,
        zscore=-0.3,
        interval_open=100.0,
        interval_high=100.0,
        interval_low=99.4,
        interval_close=99.5,
        interval_return=-0.0050,
        late_return_60s=-0.0015,
        late_return_20s=-0.0007,
        body_ratio=0.75,
        wick_imbalance=-0.05,
    ),
)
def test_extreme_price_setup_is_shadow_only_not_skipped(mock_snapshot):
    udm = _make_updown(up_price=0.99, down_price=0.01)
    with patch(
        "level_analyzer.MARKET_CACHE.snapshot",
        return_value={
            "best_bid": 0.01,
            "best_ask": 0.02,
            "spread": 0.01,
            "midpoint": 0.015,
            "book_age_ms": 250.0,
            "tick_size": 0.01,
        },
    ):
        analysis = analyze_updown_market_detail(udm)
    assert analysis.signal is not None
    assert analysis.signal.side == "NO"
    assert analysis.signal.strategy_mode == STRATEGY_MODE_SHADOW


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(window_open_price=None, window_open_price_trusted=False),
)
def test_missing_exact_open_causes_skip(mock_snapshot):
    udm = _make_updown(up_price=0.70, down_price=0.30)
    analysis = analyze_updown_market_detail(udm)
    assert analysis.signal is None
    assert analysis.strategy_route == "missing_exact_open"
    assert "trusted exact window open" in analysis.reason


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=0.0040,
        interval_open=100.0,
        interval_high=100.5,
        interval_low=99.95,
        interval_close=100.4,
        interval_return=0.0040,
        late_return_60s=0.0012,
        late_return_20s=0.0006,
        body_ratio=0.80,
    ),
)
def test_79c_strong_move_goes_to_high_prob_shadow(mock_snapshot):
    udm = _make_updown(up_price=0.79, down_price=0.21)
    with patch(
        "level_analyzer.MARKET_CACHE.snapshot",
        return_value={
            "best_bid": 0.79,
            "best_ask": 0.80,
            "spread": 0.01,
            "midpoint": 0.795,
            "book_age_ms": 250.0,
            "tick_size": 0.01,
        },
    ):
        analysis = analyze_updown_market_detail(udm)
    assert analysis.signal is not None
    assert analysis.signal.strategy_mode == STRATEGY_MODE_SHADOW
    assert analysis.strategy_route == "high_prob_shadow"


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=-0.0026,
        zscore=-0.3,
        interval_open=100.0,
        interval_high=100.0,
        interval_low=99.6,
        interval_close=99.74,
        interval_return=-0.0026,
        late_return_60s=-0.0011,
        late_return_20s=-0.0005,
        body_ratio=0.78,
        wick_imbalance=-0.06,
    ),
)
def test_strong_move_can_use_opposite_token_quote_when_selected_book_is_sparse(mock_snapshot):
    udm = _make_updown(up_price=0.28, down_price=0.72)

    def _book_snapshot(token_id):
        if token_id == "0xdown":
            return {
                "best_bid": None,
                "best_ask": None,
                "spread": None,
                "book_age_ms": 250.0,
                "tick_size": 0.01,
            }
        return {
            "best_bid": 0.28,
            "best_ask": 0.29,
            "spread": 0.01,
            "book_age_ms": 250.0,
            "tick_size": 0.01,
            "top_obi": 0.25,
            "top3_obi": 0.22,
        }

    with patch("level_analyzer.MARKET_CACHE.snapshot", side_effect=_book_snapshot):
        analysis = analyze_updown_market_detail(udm)

    assert analysis.signal is not None
    assert analysis.signal.side == "NO"
    assert analysis.best_bid == pytest.approx(0.71)
    assert analysis.best_ask == pytest.approx(0.72)


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=0.0040,
        zscore=0.8,
        interval_open=100.0,
        interval_high=100.5,
        interval_low=99.95,
        interval_close=100.4,
        interval_return=0.0040,
        late_return_60s=0.0012,
        late_return_20s=0.0006,
        body_ratio=0.80,
    ),
)
def test_stale_gamma_price_uses_trusted_book_midpoint_and_skips_too_late(mock_snapshot):
    udm = _make_updown(up_price=0.49, down_price=0.51)

    def _book_snapshot(_token_id):
        return {
            "best_bid": 0.99,
            "best_ask": 1.00,
            "spread": 0.01,
            "midpoint": 0.995,
            "book_age_ms": 250.0,
            "tick_size": 0.01,
            "top_obi": 0.25,
            "top3_obi": 0.22,
        }

    with patch("level_analyzer.MARKET_CACHE.snapshot", side_effect=_book_snapshot):
        analysis = analyze_updown_market_detail(udm)

    assert analysis.signal is None
    assert analysis.entry_price == pytest.approx(0.995)
    assert analysis.strategy_route == "too_late_or_overpriced"
    assert "too late or overpriced" in analysis.reason


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=0.0040,
        zscore=0.8,
        interval_open=100.0,
        interval_high=100.5,
        interval_low=99.95,
        interval_close=100.4,
        interval_return=0.0040,
        late_return_60s=0.0012,
        late_return_20s=0.0006,
        body_ratio=0.80,
    ),
)
def test_opposite_token_quote_replaces_broken_wide_selected_book(mock_snapshot):
    udm = _make_updown(up_price=0.49, down_price=0.51)

    def _book_snapshot(token_id):
        if token_id == "0xup":
            return {
                "best_bid": 0.01,
                "best_ask": 0.99,
                "spread": 0.98,
                "midpoint": 0.50,
                "book_age_ms": 250.0,
                "tick_size": 0.01,
            }
        return {
            "best_bid": 0.00,
            "best_ask": 0.01,
            "spread": 0.01,
            "midpoint": 0.005,
            "book_age_ms": 250.0,
            "tick_size": 0.01,
            "top_obi": -0.30,
            "top3_obi": -0.25,
        }

    with patch("level_analyzer.MARKET_CACHE.snapshot", side_effect=_book_snapshot):
        analysis = analyze_updown_market_detail(udm)

    assert analysis.best_bid == pytest.approx(0.99)
    assert analysis.best_ask == pytest.approx(1.0)
    assert analysis.entry_price == pytest.approx(0.995)


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=0.0040,
        zscore=0.8,
        interval_open=100.0,
        interval_high=100.5,
        interval_low=99.95,
        interval_close=100.4,
        interval_return=0.0040,
        late_return_60s=0.0012,
        late_return_20s=0.0006,
        body_ratio=0.80,
    ),
)
def test_reversed_outcome_index_uses_selected_token_book_for_expected_fill_price(mock_snapshot):
    udm = _make_updown(up_price=0.44, down_price=0.56, up_idx=1)

    def _book_snapshot(token_id):
        if token_id == "0xup":
            return {
                "best_bid": 0.43,
                "best_ask": 0.44,
                "spread": 0.01,
                "midpoint": 0.435,
                "book_age_ms": 250.0,
                "tick_size": 0.01,
            }
        return {
            "best_bid": 0.56,
            "best_ask": 0.57,
            "spread": 0.01,
            "midpoint": 0.565,
            "book_age_ms": 250.0,
            "tick_size": 0.01,
        }

    with patch("level_analyzer.MARKET_CACHE.snapshot", side_effect=_book_snapshot):
        analysis = analyze_updown_market_detail(udm)

    assert analysis.signal is not None
    assert analysis.signal.side == "YES"
    assert analysis.best_bid == pytest.approx(0.43)
    assert analysis.best_ask == pytest.approx(0.44)
    assert analysis.signal.expected_fill_price == pytest.approx(0.44)


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=0.0040,
        zscore=0.2,
        interval_open=100.0,
        interval_high=100.4,
        interval_low=99.95,
        interval_close=100.4,
        interval_return=0.0040,
        late_return_60s=0.0010,
        late_return_20s=-0.0002,
        body_ratio=0.55,
        wick_imbalance=0.01,
    ),
)
def test_strong_move_cheap_entry_emits_trend_follow_early(mock_snapshot):
    udm = _make_updown(up_price=0.50, down_price=0.50)

    with patch(
        "level_analyzer.MARKET_CACHE.snapshot",
        return_value={
            "best_bid": 0.50,
            "best_ask": 0.51,
            "spread": 0.01,
            "midpoint": 0.505,
            "book_age_ms": 250.0,
            "tick_size": 0.01,
        },
    ):
        analysis = analyze_updown_market_detail(udm)

    assert analysis.signal is not None
    assert analysis.strategy_route == "trend_follow_early"
    assert analysis.signal.size_multiplier == pytest.approx(0.75)
    assert analysis.signal.strategy_mode == STRATEGY_MODE_LIVE


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=0.0014,
        zscore=0.1,
        interval_open=100.0,
        interval_high=100.16,
        interval_low=99.98,
        interval_close=100.14,
        interval_return=0.0014,
        late_return_60s=0.0007,
        late_return_20s=-0.0001,
        body_ratio=0.60,
        wick_imbalance=0.02,
    ),
)
def test_mid_regime_cheap_entry_emits_mid_follow_early(mock_snapshot):
    udm = _make_updown(up_price=0.41, down_price=0.59)

    with patch(
        "level_analyzer.MARKET_CACHE.snapshot",
        return_value={
            "best_bid": 0.40,
            "best_ask": 0.42,
            "spread": 0.02,
            "midpoint": 0.41,
            "book_age_ms": 250.0,
            "tick_size": 0.01,
            "top_obi": 0.20,
            "top3_obi": 0.18,
        },
    ):
        analysis = analyze_updown_market_detail(udm)

    assert analysis.signal is not None
    assert analysis.actual_move_regime == "mid"
    assert analysis.strategy_route == "mid_follow_early"
    assert analysis.signal.size_multiplier == pytest.approx(0.75)


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        price=100.0,
        ret=-0.0030,
        zscore=-0.3,
        interval_open=100.3,
        interval_high=100.3,
        interval_low=99.8,
        interval_close=100.0,
        interval_return=-0.0030,
        late_return_60s=-0.0015,
        late_return_20s=-0.0008,
        body_ratio=0.80,
        window_open_price=99.5,
    ),
)
def test_contrarian_block_skip_logs_actual_move_side(mock_snapshot):
    udm = _make_updown(up_price=0.70, down_price=0.30)

    with patch(
        "level_analyzer.MARKET_CACHE.snapshot",
        return_value={
            "best_bid": 0.69,
            "best_ask": 0.70,
            "spread": 0.01,
            "midpoint": 0.695,
            "book_age_ms": 250.0,
            "tick_size": 0.01,
        },
    ):
        analysis = analyze_updown_market_detail(udm)

    assert analysis.signal is None
    assert analysis.price_state == "contrarian_block_actual_move"
    assert analysis.signal_side == "YES"
    assert analysis.actual_move_side == "YES"
    assert analysis.legacy_signal_side == "NO"


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=0.0040,
        zscore=0.8,
        interval_open=100.0,
        interval_high=100.5,
        interval_low=99.95,
        interval_close=100.4,
        interval_return=0.0040,
        late_return_60s=0.0012,
        late_return_20s=0.0006,
        body_ratio=0.80,
        window_open_price_trusted=False,
        window_open_anchor_age_seconds=15.0,
    ),
)
def test_degraded_open_within_15_seconds_is_allowed(mock_snapshot):
    udm = _make_updown(up_price=0.70, down_price=0.30)
    analysis = analyze_updown_market_detail(udm)

    assert analysis.strategy_route != "missing_exact_open"
    assert analysis.window_open_anchor_age_seconds == pytest.approx(15.0)


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=0.0040,
        zscore=0.8,
        interval_open=100.0,
        interval_high=100.5,
        interval_low=99.95,
        interval_close=100.4,
        interval_return=0.0040,
        late_return_60s=0.0012,
        late_return_20s=0.0006,
        body_ratio=0.80,
        window_open_price_trusted=False,
        window_open_anchor_age_seconds=15.1,
    ),
)
def test_degraded_open_over_15_seconds_skips(mock_snapshot):
    udm = _make_updown(up_price=0.70, down_price=0.30)
    analysis = analyze_updown_market_detail(udm)

    assert analysis.signal is None
    assert analysis.strategy_route == "missing_exact_open"


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=0.004,
        zscore=2.0,
        interval_open=100.0,
        interval_high=100.4,
        interval_low=99.95,
        interval_close=100.4,
        interval_return=0.004,
        late_return_60s=0.001,
        late_return_20s=0.001,
        body_ratio=0.55,
        wick_imbalance=0.01,
    ),
)
def test_no_book_high_edge_emits_trend_follow_early(mock_snapshot):
    """No order-book data + strong confirmed move + high edge → early_follow fires."""
    udm = _make_updown(up_price=0.45, down_price=0.55, secs=25)
    with patch("level_analyzer.MARKET_CACHE.snapshot", return_value={}):
        analysis = analyze_updown_market_detail(udm)
    assert analysis.signal is not None
    assert analysis.strategy_route == "trend_follow_early"
    assert analysis.signal.size_multiplier == pytest.approx(0.75)


@patch(
    "level_analyzer.get_reference_snapshot",
    return_value=_snapshot(
        ret=0.004,
        zscore=2.0,
        interval_open=100.0,
        interval_high=100.4,
        interval_low=99.95,
        interval_close=100.4,
        interval_return=0.004,
        late_return_60s=-0.001,
        late_return_20s=-0.001,
        body_ratio=0.55,
        wick_imbalance=0.01,
    ),
)
def test_no_book_late_misalign_skips(mock_snapshot):
    """No order-book + late returns disagree with actual move → skip, even without book gate."""
    udm = _make_updown(up_price=0.45, down_price=0.55, secs=25)
    with patch("level_analyzer.MARKET_CACHE.snapshot", return_value={}):
        analysis = analyze_updown_market_detail(udm)
    assert analysis.signal is None
    assert analysis.price_state == "strong_move_no_confirmation"
