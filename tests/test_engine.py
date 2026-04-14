from collections import defaultdict
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from config import (
    MAX_BET,
    MIN_BET,
    STARTING_BALANCE,
    STRATEGY_VERSION,
    TICK_INTERVAL,
    Market,
    OpenOrder,
    OrderResult,
    Signal,
    Trade,
    UpDownMarket,
)
from engine import Engine
from order_executor import OrderExecutor


class StubExecutor(OrderExecutor):
    def __init__(self, *, place_results=None, reconcile_results=None):
        self.place_results = list(place_results or [])
        self.reconcile_results = defaultdict(list)
        self.place_calls = []

        for order_id, results in (reconcile_results or {}).items():
            if isinstance(results, list):
                self.reconcile_results[order_id].extend(results)
            else:
                self.reconcile_results[order_id].append(results)

    def place_order(self, signal: Signal, size: float, entry_price: float) -> OrderResult:
        self.place_calls.append(
            {
                "market_slug": signal.market.slug,
                "side": signal.side,
                "size": size,
                "entry_price": entry_price,
            }
        )
        return self.place_results.pop(0)

    def reconcile_order(self, open_order: OpenOrder) -> OrderResult | None:
        if self.reconcile_results[open_order.order_id]:
            return self.reconcile_results[open_order.order_id].pop(0)
        return None


@pytest.fixture(autouse=True)
def _clean_engine():
    """Keep engine tests isolated from disk and structured-log side effects."""
    from strategy_eval import Mode15mResult

    default_15m = Mode15mResult(
        enabled=True,
        tightened=False,
        confidence_boost=0.0,
        edge_boost=0.0,
        reason="test",
    )

    with (
        patch("engine.read_trades", return_value=[]),
        patch("engine.read_open_orders", return_value=[]),
        patch("engine.save_open_orders"),
        patch("engine.save_trades"),
        patch("engine.evaluate_15m_mode", return_value=default_15m),
        patch("engine.log_trade_jsonl"),
        patch("engine.log_settlement"),
        patch("engine.log_risk_block"),
        patch("engine.log_order_event"),
        patch("logger.log_trade"),
    ):
        yield


def _make_market(slug="btc-updown-5m-123", end_minutes=1):
    return Market(
        condition_id=f"0x{slug}",
        question="BTC Up or Down?",
        slug=slug,
        outcomes=["Up", "Down"],
        outcome_prices=[0.55, 0.45],
        token_ids=[f"0x{slug}_up", f"0x{slug}_down"],
        end_date=datetime.now(timezone.utc) + timedelta(minutes=end_minutes),
        active=True,
    )


def _make_signal(market=None, strategy="updown", side="YES", confidence=0.95):
    market = market or _make_market()
    return Signal(
        market=market,
        strategy=strategy,
        side=side,
        confidence=confidence,
        reason="test reason",
    )


def _make_result(**overrides):
    defaults = dict(
        filled=True,
        fill_price=0.55,
        fill_size=2.75,
        fees=0.0,
        slippage=0.0,
        latency_ms=0.0,
        order_id="order-123",
        status="filled",
        reason="",
        fill_shares=5.0,
        remaining_size=0.0,
        remaining_shares=0.0,
        reserved_size=0.0,
        requested_size=2.75,
        requested_shares=5.0,
        token_id="0xYES",
        needs_reconciliation=False,
        terminal=True,
        raw_status="filled",
        raw_response={},
    )
    defaults.update(overrides)
    return OrderResult(**defaults)


def _make_open_order(**overrides):
    defaults = dict(
        order_id="order-123",
        created_at=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
        market_slug="btc-updown-5m-123",
        question="BTC Up or Down?",
        condition_id="0xbtc-updown-5m-123",
        token_id="0xYES",
        strategy="updown",
        side="YES",
        confidence=0.95,
        reason="test reason",
        end_date=datetime(2026, 4, 10, 12, 5, tzinfo=timezone.utc),
        market_type="5m",
        strategy_version=STRATEGY_VERSION,
        executor_type="StubExecutor",
        limit_price=0.58,
        requested_size=2.90,
        requested_shares=5.0,
        reserved_size=2.90,
        confirmed_fill_size=0.0,
        confirmed_fill_shares=0.0,
        confirmed_fees=0.0,
        status="submitted",
        raw_status="live",
    )
    defaults.update(overrides)
    return OpenOrder(**defaults)


def _make_trade(**overrides):
    defaults = dict(
        timestamp=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
        market_slug="btc-updown-5m-123",
        question="BTC Up or Down?",
        strategy="updown",
        side="YES",
        entry_price=0.58,
        size=1.16,
        confidence=0.95,
        reason="test reason",
        end_date=datetime(2026, 4, 10, 12, 5, tzinfo=timezone.utc),
        market_type="5m",
        strategy_version=STRATEGY_VERSION,
        fill_price=0.58,
        order_id="order-123",
        executor_type="StubExecutor",
    )
    defaults.update(overrides)
    return Trade(**defaults)


def test_engine_initial_state():
    engine = Engine()
    assert engine.balance == STARTING_BALANCE
    assert engine.available_balance == STARTING_BALANCE
    assert engine.trades == []
    assert engine.open_orders == []
    assert engine.traded_markets == set()
    assert engine.running is False
    assert engine.wins == 0
    assert engine.losses == 0


def test_execute_trade_immediate_fill_books_confirmed_position_only():
    executor = StubExecutor(place_results=[_make_result(order_id="fill-1")])
    engine = Engine(executor=executor)

    trade = engine.execute_paper_trade(_make_signal())

    assert trade is not None
    assert trade.order_id == "fill-1"
    assert trade.executor_type == "StubExecutor"
    assert trade.market_slug == "btc-updown-5m-123"
    assert trade.side == "YES"
    assert trade.status == "pending"
    assert trade.size == pytest.approx(2.75)
    assert trade.entry_price == pytest.approx(0.55)
    assert engine.balance == pytest.approx(STARTING_BALANCE - 2.75)
    assert engine.available_balance == pytest.approx(STARTING_BALANCE - 2.75)
    assert engine.open_orders == []
    assert "btc-updown-5m-123" in engine.traded_markets


def test_live_submit_without_confirmed_fill_creates_open_order_only():
    executor = StubExecutor(
        place_results=[
            _make_result(
                filled=False,
                fill_size=0.0,
                fill_shares=0.0,
                fill_price=0.58,
                order_id="live-1",
                status="submitted",
                requested_size=2.90,
                requested_shares=5.0,
                reserved_size=2.90,
                remaining_size=2.90,
                remaining_shares=5.0,
                needs_reconciliation=True,
                terminal=False,
                raw_status="live",
            )
        ]
    )
    engine = Engine(executor=executor)

    trade = engine.execute_paper_trade(_make_signal())

    assert trade is None
    assert engine.trades == []
    assert len(engine.open_orders) == 1
    assert engine.open_orders[0].order_id == "live-1"
    assert engine.balance == STARTING_BALANCE
    assert engine.reserved_open_exposure == pytest.approx(2.90)
    assert engine.available_balance == pytest.approx(STARTING_BALANCE - 2.90)
    assert "btc-updown-5m-123" not in engine.traded_markets


def test_live_partial_fill_books_only_matched_size_and_keeps_order_open():
    executor = StubExecutor(
        place_results=[
            _make_result(
                filled=False,
                fill_size=0.0,
                fill_shares=0.0,
                fill_price=0.58,
                order_id="live-1",
                status="submitted",
                requested_size=2.90,
                requested_shares=5.0,
                reserved_size=2.90,
                remaining_size=2.90,
                remaining_shares=5.0,
                needs_reconciliation=True,
                terminal=False,
                raw_status="live",
            )
        ],
        reconcile_results={
            "live-1": [
                _make_result(
                    fill_price=0.58,
                    fill_size=1.16,
                    fill_shares=2.0,
                    order_id="live-1",
                    status="partial",
                    requested_size=2.90,
                    requested_shares=5.0,
                    reserved_size=1.74,
                    remaining_size=1.74,
                    remaining_shares=3.0,
                    needs_reconciliation=True,
                    terminal=False,
                    raw_status="live",
                )
            ]
        },
    )
    engine = Engine(executor=executor)

    trade = engine.execute_paper_trade(_make_signal())

    assert trade is not None
    assert trade.order_id == "live-1"
    assert trade.size == pytest.approx(1.16)
    assert trade.entry_price == pytest.approx(0.58)
    assert len(engine.trades) == 1
    assert len(engine.open_orders) == 1
    assert engine.open_orders[0].order_id == "live-1"
    assert engine.open_orders[0].confirmed_fill_size == pytest.approx(1.16)
    assert engine.open_orders[0].reserved_size == pytest.approx(1.74)
    assert engine.balance == pytest.approx(STARTING_BALANCE - 1.16)
    assert engine.available_balance == pytest.approx(STARTING_BALANCE - 1.16 - 1.74)
    assert "btc-updown-5m-123" in engine.traded_markets


def test_reconciliation_can_add_later_fills_to_existing_trade():
    executor = StubExecutor(
        place_results=[
            _make_result(
                filled=False,
                fill_size=0.0,
                fill_shares=0.0,
                fill_price=0.58,
                order_id="live-1",
                status="submitted",
                requested_size=2.90,
                requested_shares=5.0,
                reserved_size=2.90,
                remaining_size=2.90,
                remaining_shares=5.0,
                needs_reconciliation=True,
                terminal=False,
                raw_status="live",
            )
        ],
        reconcile_results={
            "live-1": [
                _make_result(
                    fill_price=0.58,
                    fill_size=1.16,
                    fill_shares=2.0,
                    order_id="live-1",
                    status="partial",
                    requested_size=2.90,
                    requested_shares=5.0,
                    reserved_size=1.74,
                    remaining_size=1.74,
                    remaining_shares=3.0,
                    needs_reconciliation=True,
                    terminal=False,
                    raw_status="live",
                ),
                _make_result(
                    fill_price=0.58,
                    fill_size=1.74,
                    fill_shares=3.0,
                    order_id="live-1",
                    status="filled",
                    requested_size=2.90,
                    requested_shares=5.0,
                    reserved_size=0.0,
                    remaining_size=0.0,
                    remaining_shares=0.0,
                    needs_reconciliation=False,
                    terminal=True,
                    raw_status="filled",
                ),
            ]
        },
    )
    engine = Engine(executor=executor)
    first_trade = engine.execute_paper_trade(_make_signal())

    reconciled = engine._reconcile_open_orders()

    assert first_trade is not None
    assert reconciled == [first_trade]
    assert len(engine.trades) == 1
    assert engine.trades[0].order_id == "live-1"
    assert engine.trades[0].size == pytest.approx(2.90)
    assert engine.trades[0].entry_price == pytest.approx(0.58)
    assert engine.balance == pytest.approx(STARTING_BALANCE - 2.90)
    assert engine.open_orders == []


def test_rejected_order_creates_no_trade_and_no_exposure():
    executor = StubExecutor(
        place_results=[
            _make_result(
                filled=False,
                fill_size=0.0,
                fill_shares=0.0,
                status="rejected",
                reason="insufficient balance",
                order_id="",
                requested_size=2.90,
                requested_shares=5.0,
                needs_reconciliation=False,
                terminal=True,
            )
        ]
    )
    engine = Engine(executor=executor)

    trade = engine.execute_paper_trade(_make_signal())

    assert trade is None
    assert engine.trades == []
    assert engine.open_orders == []
    assert engine.balance == STARTING_BALANCE
    assert engine.available_balance == STARTING_BALANCE
    assert engine.traded_markets == set()


def test_zero_fill_cancel_releases_reserved_exposure():
    executor = StubExecutor(
        place_results=[
            _make_result(
                filled=False,
                fill_size=0.0,
                fill_shares=0.0,
                fill_price=0.58,
                order_id="live-1",
                status="submitted",
                requested_size=2.90,
                requested_shares=5.0,
                reserved_size=2.90,
                remaining_size=2.90,
                remaining_shares=5.0,
                needs_reconciliation=True,
                terminal=False,
                raw_status="live",
            )
        ],
        reconcile_results={
            "live-1": [
                _make_result(
                    filled=False,
                    fill_size=0.0,
                    fill_shares=0.0,
                    fill_price=0.58,
                    order_id="live-1",
                    status="cancelled",
                    requested_size=2.90,
                    requested_shares=5.0,
                    reserved_size=0.0,
                    remaining_size=0.0,
                    remaining_shares=0.0,
                    needs_reconciliation=False,
                    terminal=True,
                    raw_status="cancelled",
                )
            ]
        },
    )
    engine = Engine(executor=executor)

    trade = engine.execute_paper_trade(_make_signal())

    assert trade is None
    assert engine.trades == []
    assert engine.open_orders == []
    assert engine.reserved_open_exposure == 0.0
    assert engine.available_balance == STARTING_BALANCE
    assert engine.active_order_markets == set()
    assert "btc-updown-5m-123" not in engine.traded_markets


def test_reconciliation_logs_explicit_cancel_event():
    executor = StubExecutor(
        place_results=[
            _make_result(
                filled=False,
                fill_size=0.0,
                fill_shares=0.0,
                fill_price=0.58,
                order_id="live-1",
                status="submitted",
                requested_size=2.90,
                requested_shares=5.0,
                reserved_size=2.90,
                remaining_size=2.90,
                remaining_shares=5.0,
                needs_reconciliation=True,
                terminal=False,
                raw_status="live",
            )
        ],
        reconcile_results={
            "live-1": [
                _make_result(
                    filled=False,
                    fill_size=0.0,
                    fill_shares=0.0,
                    fill_price=0.58,
                    order_id="live-1",
                    status="cancelled",
                    reason="maker_quote_age>1.5s",
                    requested_size=2.90,
                    requested_shares=5.0,
                    reserved_size=0.0,
                    remaining_size=0.0,
                    remaining_shares=0.0,
                    needs_reconciliation=False,
                    terminal=True,
                    raw_status="cancelled",
                )
            ]
        },
    )
    with patch("engine.log_order_event") as mock_order_event:
        engine = Engine(executor=executor)
        trade = engine.execute_paper_trade(_make_signal())

    assert trade is None
    assert engine.open_orders == []
    cancel_calls = [
        call for call in mock_order_event.call_args_list
        if call.args and call.args[0] == "cancel"
    ]
    assert cancel_calls, "expected a cancel lifecycle event"


def test_restart_reconciliation_does_not_double_book_existing_fill():
    existing_trade = _make_trade()
    existing_open_order = _make_open_order(
        reserved_size=1.74,
        confirmed_fill_size=1.16,
        confirmed_fill_shares=2.0,
        status="partial",
    )
    executor = StubExecutor(
        reconcile_results={
            "order-123": [
                _make_result(
                    filled=False,
                    fill_size=0.0,
                    fill_shares=0.0,
                    fill_price=0.58,
                    order_id="order-123",
                    status="filled",
                    requested_size=2.90,
                    requested_shares=5.0,
                    reserved_size=0.0,
                    remaining_size=0.0,
                    remaining_shares=0.0,
                    needs_reconciliation=False,
                    terminal=True,
                    raw_status="filled",
                )
            ]
        }
    )

    with (
        patch("engine.read_trades", return_value=[existing_trade]),
        patch("engine.read_open_orders", return_value=[existing_open_order]),
    ):
        engine = Engine(executor=executor)

    assert len(engine.trades) == 1
    assert engine.trades[0].order_id == "order-123"
    assert engine.trades[0].size == pytest.approx(1.16)
    assert engine.balance == pytest.approx(STARTING_BALANCE - 1.16)
    assert engine.open_orders == []


def test_try_execute_skips_market_with_active_open_order():
    executor = StubExecutor()
    engine = Engine(executor=executor)
    engine.open_orders.append(_make_open_order())

    trade = engine._try_execute(_make_signal())

    assert trade is None
    assert executor.place_calls == []


def test_tick_reconciles_open_orders_before_new_signals():
    market = _make_market()
    signal = _make_signal(market)
    open_order = _make_open_order()
    executor = StubExecutor(
        reconcile_results={
            "order-123": [
                _make_result(
                    fill_price=0.58,
                    fill_size=1.16,
                    fill_shares=2.0,
                    order_id="order-123",
                    status="partial",
                    requested_size=2.90,
                    requested_shares=5.0,
                    reserved_size=1.74,
                    remaining_size=1.74,
                    remaining_shares=3.0,
                    needs_reconciliation=True,
                    terminal=False,
                    raw_status="live",
                )
            ]
        }
    )
    engine = Engine(executor=executor)
    engine.open_orders.append(open_order)

    with (
        patch("engine.fetch_active_markets", return_value=[market]),
        patch("engine.find_updown_markets", return_value=[]),
        patch("engine.fetch_google_news", return_value=[]),
    ):
        trades = engine.tick()

    assert len(trades) == 1
    assert trades[0].order_id == "order-123"
    assert len(engine.trades) == 1
    assert len(engine.open_orders) == 1


def test_settlement_timeout_logs_structured_event():
    executor = StubExecutor(place_results=[_make_result(order_id="fill-1")])
    market = _make_market(end_minutes=-20)
    signal = _make_signal(market)

    with (
        patch("engine.fetch_resolved_market", return_value=None),
        patch("engine.log_settlement") as mock_settlement,
        patch("engine.log_trade_jsonl") as mock_trade_jsonl,
        patch("engine.save_trades") as mock_save,
    ):
        engine = Engine(executor=executor)
        trade = engine.execute_paper_trade(signal)
        engine.settle_trades()

    assert trade is not None
    assert trade.status == "lost"
    assert trade.payout == 0.0
    assert engine.losses == 1
    mock_settlement.assert_called_once_with(trade)
    mock_trade_jsonl.assert_any_call(
        trade,
        executor_type="StubExecutor",
        snapshot_event="settlement",
    )
    mock_save.assert_called_once()


def test_bet_size_scales_with_confidence():
    engine = Engine()
    low_conf = engine.bet_size(confidence=0.2, entry_price=0.70)
    high_conf = engine.bet_size(confidence=0.9, entry_price=0.70)
    assert high_conf > low_conf


def test_bet_size_respects_min_and_max():
    engine = Engine()
    engine.balance = 2.0
    assert engine.bet_size(confidence=0.1, entry_price=0.90) >= MIN_BET

    engine.balance = 1000.0
    assert engine.bet_size(confidence=1.0, entry_price=0.50) <= MAX_BET


def test_adaptive_interval_fast_near_expiry():
    engine = Engine()
    market = _make_market()
    engine.updown_markets_found = [
        UpDownMarket(
            market=market,
            coin="BTC",
            interval_minutes=5,
            seconds_to_close=20,
            up_outcome_index=0,
        )
    ]
    assert engine._adaptive_interval() == 5.0


def test_adaptive_interval_normal_when_far():
    engine = Engine()
    market = _make_market()
    engine.updown_markets_found = [
        UpDownMarket(
            market=market,
            coin="BTC",
            interval_minutes=5,
            seconds_to_close=40,
            up_outcome_index=0,
        )
    ]
    assert engine._adaptive_interval() == TICK_INTERVAL
