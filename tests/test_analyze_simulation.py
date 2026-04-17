from analyze_simulation import (
    build_signal_state,
    build_dumb_loss_audit,
    build_promotion_report,
    build_trade_state,
    summarize_actual_move,
    summarize_shadow_signals,
)


def test_promotion_report_blocks_when_samples_and_stress_are_insufficient():
    trades = [
        {
            "type": "trade",
            "timestamp": "2026-04-15T00:00:00+00:00",
            "market_slug": "btc-updown-5m-1",
            "question": "BTC?",
            "strategy": "updown",
            "strategy_mode": "live",
            "side": "YES",
            "entry_price": 0.60,
            "size": 10.0,
            "confidence": 0.9,
            "reason": "test",
            "status": "won",
            "payout": 15.0,
            "market_type": "5m",
            "fees": 0.1,
            "fill_price": 0.62,
            "order_id": "order-1",
            "executor_type": "SimulationExecutor",
            "cluster_id": "crypto_beta",
            "signal_epoch_id": "epoch-1",
            "expected_fill_price": 0.60,
            "spread": 0.04,
            "markout_5s": -0.02,
            "order": {
                "fill_price": 0.62,
                "fill_shares": 16.129,
                "latency_ms": 180.0,
                "spread": 0.04,
            },
        }
    ]
    events = [
        {
            "type": "signal_event",
            "strategy": "updown",
            "strategy_mode": "live",
            "coin": "BTC",
            "market_type": "5m",
            "decision_stage": "traded",
        }
    ]

    latest = build_trade_state(trades, events)
    report = build_promotion_report(trades, latest, events)

    assert report["fills_combined"] == 1
    assert report["fills_by_coin"]["BTC"] == 1
    assert report["promotion_blocked"] is True
    assert report["stressed_ev_per_trade"] is not None
    assert any("need 300 candidate fills" in reason for reason in report["promotion_blockers"])


def test_trade_state_uses_latest_snapshot_per_order():
    trades = [
        {
            "type": "trade",
            "timestamp": "2026-04-15T00:00:00+00:00",
            "market_slug": "btc-updown-5m-1",
            "side": "YES",
            "order_id": "order-1",
            "size": 1.0,
            "status": "pending",
        },
        {
            "type": "trade",
            "timestamp": "2026-04-15T00:00:05+00:00",
            "market_slug": "btc-updown-5m-1",
            "side": "YES",
            "order_id": "order-1",
            "size": 2.0,
            "status": "pending",
        },
    ]
    latest = build_trade_state(trades, [])

    assert len(latest) == 1
    assert latest[0]["size"] == 2.0


def test_actual_move_summary_and_dumb_loss_audit_track_contrarian_cases():
    latest_trades = [
        {
            "type": "trade",
            "timestamp": "2026-04-15T00:00:00+00:00",
            "market_slug": "btc-updown-5m-1",
            "strategy": "updown",
            "strategy_mode": "live",
            "market_type": "5m",
            "status": "lost",
            "side": "NO",
            "size": 5.0,
            "payout": 0.0,
            "actual_move_regime": "strong",
            "actual_move_side": "YES",
            "strategy_route": "trend_follow_candidate",
        },
        {
            "type": "trade",
            "timestamp": "2026-04-15T00:05:00+00:00",
            "market_slug": "sol-updown-5m-2",
            "strategy": "updown",
            "strategy_mode": "live",
            "market_type": "5m",
            "status": "won",
            "side": "YES",
            "size": 5.0,
            "payout": 8.0,
            "actual_move_regime": "strong",
            "actual_move_side": "YES",
            "strategy_route": "trend_follow_candidate",
        },
    ]
    events = [
        {
            "type": "signal_event",
            "actual_move_regime": "strong",
            "actual_move_side": "YES",
            "legacy_signal_side": "NO",
            "contrarian_block_reason": "blocked",
            "strategy_route": "high_prob_shadow",
            "entry_price": 0.81,
        }
    ]

    summary = summarize_actual_move(latest_trades, events)
    audit = build_dumb_loss_audit(latest_trades, events)

    assert summary["forbidden_blocked_contrarian_cases"] == 1
    assert summary["strong_up_legacy_no"] == 1
    assert summary["by_regime"]["strong"]["trades"] == 2
    assert summary["high_prob_shadow_bands"]["0.78-0.82"] == 1
    assert audit["trades_against_actual_move"] == 1
    assert audit["strong_move_disagreements"] == 1
    assert audit["legacy_contrarian_strong_move_examples"] == 1


def test_build_signal_state_prefers_latest_resolution_snapshot():
    events = [
        {
            "type": "signal_event",
            "timestamp": "2026-04-15T00:00:00+00:00",
            "signal_id": "sig-1",
            "signal_side": "YES",
            "strategy_mode": "shadow",
            "signal_status": "pending",
            "snapshot_event": "analysis",
        },
        {
            "type": "signal_event",
            "timestamp": "2026-04-15T00:06:00+00:00",
            "signal_id": "sig-1",
            "signal_side": "YES",
            "strategy_mode": "shadow",
            "signal_status": "won",
            "resolved_side": "YES",
            "snapshot_event": "resolution",
        },
    ]

    latest = build_signal_state(events)

    assert len(latest) == 1
    assert latest[0]["signal_status"] == "won"
    assert latest[0]["resolved_side"] == "YES"


def test_shadow_summary_uses_resolved_signal_snapshots():
    events = [
        {
            "type": "signal_event",
            "timestamp": "2026-04-15T00:00:00+00:00",
            "signal_id": "sig-1",
            "strategy_mode": "shadow",
            "signal_side": "YES",
            "decision_stage": "shadow_only",
            "strategy_route": "mid_follow_candidate",
            "signal_status": "pending",
        },
        {
            "type": "signal_event",
            "timestamp": "2026-04-15T00:06:00+00:00",
            "signal_id": "sig-1",
            "strategy_mode": "shadow",
            "signal_side": "YES",
            "decision_stage": "shadow_only",
            "strategy_route": "mid_follow_candidate",
            "signal_status": "won",
            "resolved_side": "YES",
        },
        {
            "type": "signal_event",
            "timestamp": "2026-04-15T00:01:00+00:00",
            "signal_id": "sig-2",
            "strategy_mode": "shadow",
            "signal_side": "NO",
            "decision_stage": "cycle_limit_skip",
            "strategy_route": "high_prob_shadow",
            "signal_status": "lost",
            "resolved_side": "YES",
        },
    ]

    summary = summarize_shadow_signals(events)

    assert summary["tracked"] == 2
    assert summary["settled"] == 2
    assert summary["wins"] == 1
    assert summary["losses"] == 1
    assert summary["by_route"]["mid_follow_candidate"]["signals"] == 1
