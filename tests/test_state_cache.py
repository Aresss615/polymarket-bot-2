from datetime import datetime, timedelta, timezone

import pytest

from state_cache import MarketStateCache, ReferenceStateCache


def test_candle_features_compute_ohlc_returns_and_wicks():
    cache = ReferenceStateCache()
    base = datetime(2026, 4, 15, 0, 0, tzinfo=timezone.utc)
    points = [
        (0, 100.0),
        (60, 102.0),
        (120, 99.0),
        (240, 100.0),
        (280, 100.5),
        (300, 101.0),
    ]

    for offset_seconds, price in points:
        cache.update("BTC", price, timestamp=base + timedelta(seconds=offset_seconds))

    features = cache.candle_features("BTC", window_seconds=300)

    assert features["interval_open"] == 100.0
    assert features["interval_high"] == 102.0
    assert features["interval_low"] == 99.0
    assert features["interval_close"] == 101.0
    assert features["interval_return"] == pytest.approx(0.01)
    assert features["late_return_60s"] == pytest.approx(0.01)
    assert features["late_return_20s"] == pytest.approx((101.0 - 100.5) / 100.5)
    assert features["body_ratio"] == pytest.approx(1.0 / 3.0)
    assert features["wick_imbalance"] == pytest.approx(0.0)


def test_market_cache_snapshot_includes_tick_size_and_book_age():
    cache = MarketStateCache()
    base = datetime.now(timezone.utc) - timedelta(milliseconds=500)

    cache.update_from_book(
        "token-1",
        bids=[{"price": 0.47, "size": 120}, {"price": 0.46, "size": 50}],
        asks=[{"price": 0.49, "size": 100}, {"price": 0.50, "size": 40}],
        market_slug="btc-updown-5m-1",
        timestamp=base,
        tick_size=0.01,
    )

    snapshot = cache.snapshot("token-1")

    assert snapshot["best_bid"] == pytest.approx(0.47)
    assert snapshot["best_ask"] == pytest.approx(0.49)
    assert snapshot["spread"] == pytest.approx(0.02)
    assert snapshot["tick_size"] == pytest.approx(0.01)
    assert snapshot["book_age_ms"] is not None
    assert snapshot["book_age_ms"] >= 400


def test_market_cache_tick_size_change_updates_existing_state():
    cache = MarketStateCache()
    cache.update_best_bid_ask("token-2", best_bid=0.40, best_ask=0.41, tick_size=0.01)

    cache.update_tick_size("token-2", tick_size=0.005)
    snapshot = cache.snapshot("token-2")

    assert snapshot["tick_size"] == pytest.approx(0.005)


def test_market_cache_partial_quote_update_preserves_existing_other_side():
    cache = MarketStateCache()
    cache.update_best_bid_ask("token-3", best_bid=0.40, best_ask=0.41, tick_size=0.01)

    cache.update_best_bid_ask("token-3", best_bid=None, best_ask=0.42)
    snapshot = cache.snapshot("token-3")

    assert snapshot["best_bid"] == pytest.approx(0.40)
    assert snapshot["best_ask"] == pytest.approx(0.42)
    assert snapshot["spread"] == pytest.approx(0.02)


def test_reference_cache_window_anchor_marks_trusted_within_tolerance():
    cache = ReferenceStateCache()
    base = datetime(2026, 4, 15, 0, 0, tzinfo=timezone.utc)

    cache.update("BTC", 100.0, timestamp=base + timedelta(seconds=1))
    cache.update("BTC", 101.0, timestamp=base + timedelta(seconds=10))

    anchor = cache.window_anchor(
        "BTC",
        target_timestamp=base.timestamp(),
        tolerance_seconds=2.0,
    )

    assert anchor["trusted"] is True
    assert anchor["price"] == pytest.approx(100.0)
