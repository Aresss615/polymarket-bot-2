import pytest

from runtime_data import RuntimeDataPlane


def test_market_and_rtds_messages_accept_list_payloads():
    plane = RuntimeDataPlane()

    plane.set_market_tokens({"token-1"})
    plane.set_reference_symbols({"BTC"})
    plane.apply_market_message([
        {
            "event_type": "best_bid_ask",
            "asset_id": "token-1",
            "market_slug": "btc-updown-5m-1",
            "best_bid": 0.45,
            "best_ask": 0.47,
            "tick_size": 0.01,
            "timestamp": 1_700_000_000,
        }
    ])
    plane.apply_rtds_message(
        '[{"topic":"crypto_prices","type":"update","timestamp":1700000000123,"payload":{"symbol":"btcusdt","value":101234.5,"timestamp":1700000000000}}]'
    )

    market = plane.market_cache.snapshot("token-1")
    assert market["best_bid"] == 0.45
    assert market["best_ask"] == 0.47
    assert market["tick_size"] == 0.01
    assert plane.reference_cache.price("BTC") == 101234.5


def test_price_change_array_updates_partial_quotes_without_erasing_known_side():
    plane = RuntimeDataPlane()

    plane.apply_market_message(
        {
            "event_type": "best_bid_ask",
            "asset_id": "token-1",
            "market_slug": "btc-updown-5m-1",
            "best_bid": 0.45,
            "best_ask": 0.47,
            "tick_size": 0.01,
            "timestamp": 1_700_000_000,
        }
    )
    plane.apply_market_message(
        {
            "event_type": "price_change",
            "timestamp": 1_700_000_001,
            "price_changes": [
                {
                    "asset_id": "token-1",
                    "side": "SELL",
                    "price": 0.46,
                    "best_ask": 0.46,
                }
            ],
        }
    )

    market = plane.market_cache.snapshot("token-1")
    assert market["best_bid"] == 0.45
    assert market["best_ask"] == 0.46
    assert market["spread"] == pytest.approx(0.01)


def test_rtds_chainlink_snapshot_populates_history_and_latest_price():
    plane = RuntimeDataPlane()

    plane.apply_rtds_message(
        {
            "topic": "crypto_prices_chainlink",
            "type": "subscribe",
            "timestamp": 1_700_000_003_000,
            "payload": {
                "symbol": "btc/usd",
                "data": [
                    {"timestamp": 1_700_000_000_000, "value": 101000.0},
                    {"timestamp": 1_700_000_001_000, "value": 101100.0},
                    {"timestamp": 1_700_000_002_000, "value": 101234.5},
                ],
            },
        }
    )

    assert plane.reference_cache.price("BTC", prefer_chainlink=True) == 101234.5
    assert plane.reference_cache.age_seconds("BTC", prefer_chainlink=True) is not None


def test_user_order_store_uses_cumulative_fill_state():
    plane = RuntimeDataPlane()

    plane.apply_user_message(
        {
            "order_id": "order-1",
            "status": "MATCHED",
            "fill_size": 1.25,
            "fill_shares": 2.5,
            "fees": 0.02,
            "remaining_size": 0.75,
            "remaining_shares": 1.5,
            "asset_id": "token-1",
            "market_slug": "btc-updown-5m-1",
            "timestamp": 1_700_000_000,
        }
    )
    plane.apply_user_message(
        {
            "order_id": "order-1",
            "status": "CONFIRMED",
            "fill_size": 2.0,
            "fill_shares": 4.0,
            "fees": 0.03,
            "remaining_size": 0.0,
            "remaining_shares": 0.0,
            "asset_id": "token-1",
            "market_slug": "btc-updown-5m-1",
            "timestamp": 1_700_000_001,
        }
    )

    snapshot = plane.order_store.snapshot("order-1")

    assert snapshot is not None
    assert snapshot.status == "confirmed"
    assert snapshot.fill_size == 2.0
    assert snapshot.fill_shares == 4.0
    assert snapshot.remaining_size == 0.0
    assert snapshot.terminal is True


def test_subscription_payloads_follow_active_runtime_universe():
    plane = RuntimeDataPlane()
    plane.set_market_tokens({"token-b", "token-a"})
    plane.set_reference_symbols({"SOL", "BTC"})

    market_sub = plane._market_subscriptions()
    rtds_sub = plane._rtds_subscriptions()

    assert market_sub == {
        "assets_ids": ["token-a", "token-b"],
        "type": "market",
        "custom_feature_enabled": True,
    }
    assert rtds_sub == {
        "action": "subscribe",
        "subscriptions": [
            {"topic": "crypto_prices", "type": "update"},
            {"topic": "crypto_prices_chainlink", "type": "*", "filters": '{"symbol": "btc/usd"}'},
            {"topic": "crypto_prices_chainlink", "type": "*", "filters": '{"symbol": "sol/usd"}'},
        ],
    }
