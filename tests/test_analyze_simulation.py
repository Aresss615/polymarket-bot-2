from analyze_simulation import build_trade_state


def test_build_trade_state_applies_settlement_to_latest_confirmed_snapshot():
    trades = [
        {
            "type": "trade",
            "snapshot_event": "fill",
            "timestamp": "2026-04-10T12:00:00+00:00",
            "market_slug": "btc-updown-5m-123",
            "strategy": "updown",
            "side": "YES",
            "entry_price": 0.58,
            "size": 1.16,
            "confidence": 0.95,
            "reason": "test",
            "status": "pending",
            "payout": 0.0,
            "fees": 0.01,
            "fill_price": 0.58,
            "order_id": "order-123",
            "executor_type": "LiveExecutor",
        },
        {
            "type": "trade",
            "snapshot_event": "fill",
            "timestamp": "2026-04-10T12:01:00+00:00",
            "market_slug": "btc-updown-5m-123",
            "strategy": "updown",
            "side": "YES",
            "entry_price": 0.58,
            "size": 2.90,
            "confidence": 0.95,
            "reason": "test",
            "status": "pending",
            "payout": 0.0,
            "fees": 0.03,
            "fill_price": 0.58,
            "order_id": "order-123",
            "executor_type": "LiveExecutor",
        },
    ]
    events = [
        {
            "type": "settlement",
            "timestamp": "2026-04-10T12:06:00+00:00",
            "order_id": "order-123",
            "market_slug": "btc-updown-5m-123",
            "side": "YES",
            "status": "won",
            "payout": 4.97,
            "fees": 0.03,
        }
    ]

    latest = build_trade_state(trades, events)

    assert len(latest) == 1
    assert latest[0]["order_id"] == "order-123"
    assert latest[0]["size"] == 2.90
    assert latest[0]["status"] == "won"
    assert latest[0]["payout"] == 4.97


def test_build_trade_state_matches_legacy_trade_without_order_id():
    trades = [
        {
            "type": "trade",
            "snapshot_event": "fill",
            "timestamp": "2026-04-10T12:00:00+00:00",
            "market_slug": "eth-updown-5m-456",
            "strategy": "updown",
            "side": "NO",
            "entry_price": 0.44,
            "size": 3.00,
            "confidence": 0.90,
            "reason": "legacy",
            "status": "pending",
            "payout": 0.0,
            "fees": 0.0,
            "fill_price": 0.44,
            "executor_type": "PaperExecutor",
        }
    ]
    events = [
        {
            "type": "settlement",
            "timestamp": "2026-04-10T12:05:00+00:00",
            "market_slug": "eth-updown-5m-456",
            "side": "NO",
            "status": "lost",
            "payout": 0.0,
            "fees": 0.0,
        }
    ]

    latest = build_trade_state(trades, events)

    assert len(latest) == 1
    assert latest[0]["market_slug"] == "eth-updown-5m-456"
    assert latest[0]["status"] == "lost"
