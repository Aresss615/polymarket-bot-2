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
        '[{"type":"crypto_prices","symbol":"BTC","price":101234.5,"timestamp":1700000000}]'
    )

    market = plane.market_cache.snapshot("token-1")
    assert market["best_bid"] == 0.45
    assert market["best_ask"] == 0.47
    assert market["tick_size"] == 0.01
    assert plane.reference_cache.price("BTC") == 101234.5


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
            {"topic": "crypto_prices", "type": "update", "filters": "btcusdt"},
            {"topic": "crypto_prices", "type": "update", "filters": "solusdt"},
        ],
    }
