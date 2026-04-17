from collections import defaultdict
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
import json
import time
from unittest.mock import MagicMock, call, patch

import pytest

import trade_logger
from config import (
    MAX_BET,
    MIN_BET,
    MAX_REFERENCE_AGE_SECONDS,
    MAX_REFERENCE_AGE_SECONDS_FALLBACK,
    NEWS_POLL_INTERVAL,
    RiskConfig,
    STARTING_BALANCE,
    STRATEGY_VERSION,
    TICK_INTERVAL,
    Market,
    OpenOrder,
    OrderResult,
    RedemptionResult,
    Signal,
    Trade,
    UpDownMarket,
)
from engine import Engine
from level_analyzer import UpdownAnalysis
from order_executor import OrderExecutor
from risk_manager import RiskManager


class StubExecutor(OrderExecutor):
    def __init__(
        self,
        *,
        place_results=None,
        reconcile_results=None,
        redeem_results=None,
        redemption_status_results=None,
        supports_redemption=False,
        wallet_type="safe",
        redemption_wallet_address="0xfeed000000000000000000000000000000000000",
    ):
        self.place_results = list(place_results or [])
        self.reconcile_results = defaultdict(list)
        self.redeem_results = list(redeem_results or [])
        self.redemption_status_results = defaultdict(list)
        self.supports_redemption_flag = supports_redemption
        self.wallet_type = wallet_type
        self.redemption_wallet_address = redemption_wallet_address
        self.place_calls = []
        self.redeem_calls = []
        self.redemption_status_calls = []

        for order_id, results in (reconcile_results or {}).items():
            if isinstance(results, list):
                self.reconcile_results[order_id].extend(results)
            else:
                self.reconcile_results[order_id].append(results)
        for transaction_id, results in (redemption_status_results or {}).items():
            if isinstance(results, list):
                self.redemption_status_results[transaction_id].extend(results)
            else:
                self.redemption_status_results[transaction_id].append(results)

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

    def supports_redemption(self) -> bool:
        return self.supports_redemption_flag

    def redeem_condition(self, condition_id: str) -> RedemptionResult:
        self.redeem_calls.append(condition_id)
        if self.redeem_results:
            return self.redeem_results.pop(0)
        return RedemptionResult(status="pending", success=True, terminal=False)

    def get_redemption_status(self, transaction_id: str) -> RedemptionResult:
        self.redemption_status_calls.append(transaction_id)
        if self.redemption_status_results[transaction_id]:
            return self.redemption_status_results[transaction_id].pop(0)
        return RedemptionResult(
            status="pending",
            success=True,
            transaction_id=transaction_id,
            terminal=False,
        )


class PendingExecutor:
    def __init__(self):
        self.submissions = []

    def submit(self, fn, *args, **kwargs):
        future = Future()
        self.submissions.append((fn, args, kwargs, future))
        return future

    def shutdown(self, **kwargs):
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
        patch("engine.log_redemption_event"),
        patch("engine.log_risk_block"),
        patch("engine.log_signal_event"),
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
        coin="BTC",
        cluster_id="crypto_beta",
        signal_epoch_id="epoch-1",
        expected_fill_price=0.57,
        expected_cost=0.02,
    )


def _make_udm(market=None, *, coin="BTC", interval_minutes=5, seconds_to_close=45, up_outcome_index=0):
    market = market or _make_market()
    return UpDownMarket(
        market=market,
        coin=coin,
        interval_minutes=interval_minutes,
        seconds_to_close=seconds_to_close,
        up_outcome_index=up_outcome_index,
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


def _make_redemption_result(**overrides):
    defaults = dict(
        status="pending",
        success=True,
        transaction_id="redeem-123",
        transaction_hash="0xhash",
        error="",
        terminal=False,
        retryable=False,
        raw_state="STATE_NEW",
        raw_response={},
    )
    defaults.update(overrides)
    return RedemptionResult(**defaults)


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


def test_live_engine_ignores_simulation_history():
    live_trade = _make_trade(
        executor_type="LiveExecutor",
        size=1.16,
        status="won",
        payout=2.0,
        order_id="live-order",
    )
    sim_trade = _make_trade(
        executor_type="SimulationExecutor",
        size=5.0,
        status="won",
        payout=6.0,
        order_id="sim-order",
        market_slug="eth-updown-5m-456",
    )
    live_open_order = _make_open_order(
        executor_type="LiveExecutor",
        order_id="live-open-order",
    )
    sim_open_order = _make_open_order(
        executor_type="SimulationExecutor",
        order_id="sim-open-order",
        market_slug="eth-updown-5m-456",
    )

    with (
        patch("engine.TRADING_MODE", "live"),
        patch("engine.read_trades", return_value=[live_trade, sim_trade]),
        patch("engine.read_open_orders", return_value=[live_open_order, sim_open_order]),
    ):
        engine = Engine(executor=StubExecutor())

    assert [trade.order_id for trade in engine.trades] == ["live-order"]
    assert [order.order_id for order in engine.open_orders] == ["live-open-order"]
    assert engine.balance == pytest.approx(STARTING_BALANCE - 1.16 + 2.0)


def test_simulation_engine_ignores_live_history():
    live_trade = _make_trade(
        executor_type="LiveExecutor",
        size=1.16,
        status="won",
        payout=2.0,
        order_id="live-order",
    )
    sim_trade = _make_trade(
        executor_type="SimulationExecutor",
        size=5.0,
        status="won",
        payout=6.0,
        order_id="sim-order",
        market_slug="eth-updown-5m-456",
    )

    with (
        patch("engine.TRADING_MODE", "simulation"),
        patch("engine.read_trades", return_value=[live_trade, sim_trade]),
        patch("engine.read_open_orders", return_value=[]),
    ):
        engine = Engine(executor=StubExecutor())

    assert [trade.order_id for trade in engine.trades] == ["sim-order"]
    assert engine.balance == pytest.approx(STARTING_BALANCE - 5.0 + 6.0)


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
    assert engine.open_orders[0].cluster_id == "crypto_beta"
    assert engine.open_orders[0].signal_epoch_id == "epoch-1"
    assert engine.open_orders[0].expected_fill_price == pytest.approx(0.57)
    assert engine.open_orders[0].expected_cost == pytest.approx(0.02)


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
    existing_trade = _make_trade(executor_type="LiveExecutor")
    existing_open_order = _make_open_order(
        executor_type="LiveExecutor",
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
        patch("engine.TRADING_MODE", "live"),
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

    trade, stage, reason = engine._try_execute(_make_signal())

    assert trade is None
    assert stage == "active_order_skip"
    assert "live" in reason
    assert executor.place_calls == []


def test_try_execute_surfaces_executor_rejection_reason():
    executor = StubExecutor(
        place_results=[
            _make_result(
                filled=False,
                fill_size=0.0,
                fill_shares=0.0,
                order_id="",
                status="rejected",
                reason="market moved above signal price (0.99>0.51)",
                requested_size=2.75,
                requested_shares=5.0,
                reserved_size=0.0,
                remaining_size=0.0,
                remaining_shares=0.0,
                needs_reconciliation=False,
                terminal=True,
                raw_status="rejected",
            )
        ]
    )
    engine = Engine(
        executor=executor,
        risk_manager=RiskManager(
            RiskConfig(
                max_open_exposure=100.0,
                max_open_exposure_pct=1.0,
                hard_position_cap_pct=1.0,
                max_thesis_exposure_pct=1.0,
                max_cluster_exposure_pct=1.0,
            )
        ),
    )

    trade, stage, reason = engine._try_execute(_make_signal())

    assert trade is None
    assert stage == "order_rejected"
    assert "market moved above signal price" in reason


def test_try_execute_prefers_signal_entry_price_override():
    executor = StubExecutor(place_results=[_make_result()])
    engine = Engine(
        executor=executor,
        risk_manager=RiskManager(
            RiskConfig(
                max_open_exposure=100.0,
                max_open_exposure_pct=1.0,
                hard_position_cap_pct=1.0,
                max_thesis_exposure_pct=1.0,
                max_cluster_exposure_pct=1.0,
            )
        ),
    )
    signal = _make_signal()
    signal.entry_price = 0.91

    trade, stage, reason = engine._try_execute(signal)

    assert trade is not None
    assert stage == "traded"
    assert "filled" in reason
    assert executor.place_calls[0]["entry_price"] == pytest.approx(0.91)


def test_try_execute_surfaces_reconciled_cancel_reason():
    executor = StubExecutor(
        place_results=[
            _make_result(
                filled=False,
                fill_size=0.0,
                fill_shares=0.0,
                fill_price=0.55,
                order_id="live-1",
                status="submitted",
                requested_size=2.75,
                requested_shares=5.0,
                reserved_size=2.75,
                remaining_size=2.75,
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
                    fill_price=0.55,
                    order_id="live-1",
                    status="cancelled",
                    reason="outbid_by_market>0.99",
                    cancel_reason="outbid_by_market>0.99",
                    requested_size=2.75,
                    requested_shares=5.0,
                    reserved_size=0.0,
                    remaining_size=0.0,
                    remaining_shares=0.0,
                    needs_reconciliation=False,
                    terminal=True,
                    raw_status="live",
                )
            ]
        },
    )
    engine = Engine(
        executor=executor,
        risk_manager=RiskManager(
            RiskConfig(
                max_open_exposure=100.0,
                max_open_exposure_pct=1.0,
                hard_position_cap_pct=1.0,
                max_thesis_exposure_pct=1.0,
                max_cluster_exposure_pct=1.0,
            )
        ),
    )

    trade, stage, reason = engine._try_execute(_make_signal())

    assert trade is None
    assert stage == "order_rejected"
    assert "outbid_by_market" in reason
    assert engine.open_orders == []


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
    ):
        trades = engine.tick()

    assert len(trades) == 1
    assert trades[0].order_id == "order-123"
    assert len(engine.trades) == 1
    assert len(engine.open_orders) == 1


def test_settlement_timeout_leaves_trade_pending():
    executor = StubExecutor(place_results=[_make_result(order_id="fill-1")])
    market = _make_market(end_minutes=-20)
    signal = _make_signal(market)

    with (
        patch("engine.fetch_resolved_market", return_value=None),
        patch("engine.log_settlement") as mock_settlement,
        patch("engine.log_trade_jsonl") as mock_trade_jsonl,
    ):
        engine = Engine(executor=executor)
        trade = engine.execute_paper_trade(signal)
        engine.settle_trades()

    assert trade is not None
    assert trade.status == "pending"
    assert engine.losses == 0
    mock_settlement.assert_not_called()
    settlement_calls = [c for c in mock_trade_jsonl.call_args_list if c.kwargs.get("snapshot_event") == "settlement"]
    assert settlement_calls == []


def test_tick_does_not_schedule_news_refresh_when_news_trading_disabled():
    engine = Engine(executor=StubExecutor())
    pending_executor = PendingExecutor()
    engine._background_executor = pending_executor
    market = _make_market()

    with (
        patch("engine.fetch_active_markets", return_value=[market]),
        patch("engine.find_updown_markets", return_value=[]),
        patch.object(engine, "_start_background_price_warm"),
    ):
        trades = engine.tick()

    assert trades == []
    assert pending_executor.submissions == []


def test_tick_marks_shadow_signal_without_execution():
    engine = Engine(executor=StubExecutor())
    market = _make_market()
    udm = UpDownMarket(
        market=market,
        coin="BTC",
        interval_minutes=5,
        seconds_to_close=20,
        up_outcome_index=0,
    )
    signal = _make_signal(market=market)
    signal.strategy_mode = "shadow"
    analysis = UpdownAnalysis(
        udm=udm,
        signal=signal,
        reason="shadow test",
        decision_stage="analysis_ready",
        seconds_to_close=20,
        implied_up_prob=0.75,
        model_up_prob=0.85,
        signal_side="YES",
        direction="BUY",
        confidence=0.7,
        entry_price=0.75,
        raw_edge=0.10,
        effective_edge=0.08,
        estimated_fee=0.01,
        min_edge=0.06,
        momentum=0.001,
        price_state="confirm",
        strategy_mode="shadow",
    )

    with (
        patch("engine.TRADING_MODE", "paper"),
        patch("engine.fetch_active_markets", return_value=[market]),
        patch("engine.find_updown_markets", return_value=[udm]),
        patch("engine.analyze_updown_market_detail", return_value=analysis),
        patch.object(engine, "_warm_active_coins"),
        patch.object(engine, "_start_background_price_warm"),
        patch.object(engine, "_try_execute", wraps=engine._try_execute) as mock_try_execute,
    ):
        trades = engine.tick()

    assert trades == []
    assert engine.monitor_signals[0]["decision_stage"] == "shadow_only"
    mock_try_execute.assert_called_once_with(signal)


def test_retry_watch_allows_exactly_one_second_chance_retry_per_market_window():
    engine = Engine(executor=StubExecutor())
    market = _make_market()
    udm = _make_udm(market=market)
    retry_signal = _make_signal(market=market)
    retry_signal.strategy_route = "second_chance_retry"
    retry_signal.entry_price = 0.82

    calls = {"count": 0}

    def _analyze(_udm, extra_min_edge=0.0, retry_context=None):
        del extra_min_edge
        calls["count"] += 1
        if calls["count"] == 1:
            assert retry_context is None
            return UpdownAnalysis(
                udm=_udm,
                signal=None,
                reason="too late",
                decision_stage="analysis_skip",
                seconds_to_close=45,
                signal_side="YES",
                direction="BUY",
                entry_price=0.90,
                price_state="too_late_high_prob",
                strategy_mode="shadow",
                actual_move_regime="strong",
                actual_move_side="YES",
                strategy_route="too_late_or_overpriced",
                tick_size=0.01,
            )
        if calls["count"] == 2:
            assert retry_context is not None
            assert retry_context["entry_price"] == pytest.approx(0.90)
            return UpdownAnalysis(
                udm=_udm,
                signal=retry_signal,
                reason="retry ready",
                decision_stage="analysis_ready",
                seconds_to_close=40,
                signal_side="YES",
                direction="BUY",
                confidence=0.8,
                entry_price=0.82,
                price_state="second_chance_retry",
                strategy_mode="live",
                actual_move_regime="strong",
                actual_move_side="YES",
                strategy_route="second_chance_retry",
                tick_size=0.01,
            )
        assert retry_context is None
        return UpdownAnalysis(
            udm=_udm,
            signal=None,
            reason="used already",
            decision_stage="analysis_skip",
            seconds_to_close=35,
            signal_side="YES",
            direction="BUY",
            entry_price=0.81,
            price_state="mid_regime_no_trade",
            strategy_mode="live",
            actual_move_regime="strong",
            actual_move_side="YES",
            strategy_route="mid_skip",
            tick_size=0.01,
        )

    engine.updown_markets_found = [udm]

    with (
        patch("engine.TRADING_MODE", "live"),
        patch("engine.analyze_updown_market_detail", side_effect=_analyze),
    ):
        first = engine.check_updown_markets()
        second = engine.check_updown_markets()
        third = engine.check_updown_markets()

    assert first[0].signal is None
    assert second[0].signal is retry_signal
    assert second[0].strategy_route == "second_chance_retry"
    assert third[0].signal is None
    assert market.slug not in engine._retry_watches


def test_retry_watch_expires_after_12_seconds():
    engine = Engine(executor=StubExecutor())
    market = _make_market()
    udm = _make_udm(market=market)
    engine._retry_watches[market.slug] = {
        "market_slug": market.slug,
        "actual_move_side": "YES",
        "entry_price": 0.90,
        "tick_size": 0.01,
        "observed_at": 100.0,
    }

    with patch("engine.time.time", return_value=111.9):
        engine._prune_retry_watches([udm])
        assert market.slug in engine._retry_watches

    with patch("engine.time.time", return_value=112.01):
        engine._prune_retry_watches([udm])

    assert market.slug not in engine._retry_watches


@pytest.mark.parametrize(
    ("result", "expected_stage"),
    [
        (_make_result(order_id="fill-1"), "traded"),
        (
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
            ),
            "order_live",
        ),
    ],
)
def test_retry_watch_clears_on_fill_or_live_order(result, expected_stage):
    executor = StubExecutor(place_results=[result])
    engine = Engine(
        executor=executor,
        risk_manager=RiskManager(
            RiskConfig(
                max_open_exposure=100.0,
                max_open_exposure_pct=1.0,
                hard_position_cap_pct=1.0,
                max_thesis_exposure_pct=1.0,
                max_cluster_exposure_pct=1.0,
            )
        ),
    )
    signal = _make_signal()
    signal.strategy_mode = "live"
    signal.strategy_route = "second_chance_retry"
    signal.requested_size_override = 2.0
    engine._retry_watches[signal.market.slug] = {
        "market_slug": signal.market.slug,
        "actual_move_side": signal.side,
        "entry_price": 0.90,
        "tick_size": 0.01,
        "observed_at": time.time(),
    }

    with patch("engine.TRADING_MODE", "live"):
        trade, stage, _ = engine._try_execute(signal)

    assert stage == expected_stage
    assert signal.market.slug not in engine._retry_watches
    if expected_stage == "traded":
        assert trade is not None


def test_simulation_executes_shadow_signal():
    executor = StubExecutor(place_results=[_make_result(order_id="sim-shadow-1")])
    signal = _make_signal()
    signal.strategy_mode = "shadow"

    with patch("engine.TRADING_MODE", "simulation"):
        engine = Engine(
            executor=executor,
            risk_manager=RiskManager(
                RiskConfig(
                    max_open_exposure=100.0,
                    max_open_exposure_pct=1.0,
                    hard_position_cap_pct=1.0,
                    max_thesis_exposure_pct=1.0,
                    max_cluster_exposure_pct=1.0,
                )
            ),
        )
        trade, stage, reason = engine._try_execute(signal)

    assert trade is not None
    assert trade.order_id == "sim-shadow-1"
    assert stage == "traded"
    assert "filled" in reason


def test_live_executes_high_prob_shadow_signal():
    executor = StubExecutor(place_results=[_make_result(order_id="live-shadow-1")])
    signal = _make_signal()
    signal.strategy_mode = "shadow"
    signal.strategy_route = "high_prob_shadow"

    with patch("engine.TRADING_MODE", "live"):
        engine = Engine(
            executor=executor,
            risk_manager=RiskManager(
                RiskConfig(
                    max_open_exposure=100.0,
                    max_open_exposure_pct=1.0,
                    hard_position_cap_pct=1.0,
                    max_thesis_exposure_pct=1.0,
                    max_cluster_exposure_pct=1.0,
                )
            ),
        )
        trade, stage, reason = engine._try_execute(signal)

    assert trade is not None
    assert trade.order_id == "live-shadow-1"
    assert stage == "traded"
    assert "filled" in reason


def test_live_blocks_non_promoted_shadow_signal():
    executor = StubExecutor(place_results=[_make_result(order_id="live-shadow-1")])
    signal = _make_signal()
    signal.strategy_mode = "shadow"
    signal.strategy_route = "shadow_probe"

    with patch("engine.TRADING_MODE", "live"):
        engine = Engine(executor=executor)
        trade, stage, reason = engine._try_execute(signal)

    assert trade is None
    assert stage == "shadow_only"
    assert reason == "shadow-only strategy"
    assert executor.place_calls == []


def test_settle_shadow_signals_logs_resolution_snapshot(tmp_path):
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        (
            '{"type":"signal_event","timestamp":"2026-04-15T00:00:00+00:00",'
            '"signal_id":"btc-shadow-1","snapshot_event":"analysis","signal_status":"pending",'
            '"strategy":"updown","strategy_mode":"shadow","signal_side":"YES","decision_stage":"shadow_only",'
            '"market_slug":"btc-updown-5m-1776263700","market_type":"5m","interval_minutes":5,'
            '"strategy_route":"mid_follow_candidate","window_start_ts":1776263700.0}\n'
        ),
        encoding="utf-8",
    )
    engine = Engine(executor=StubExecutor())

    with (
        patch("engine.EVENTS_JSONL", events_path),
        patch.object(trade_logger, "EVENTS_JSONL", events_path),
        patch(
            "engine.fetch_resolved_market",
            return_value={"outcomes": ["Yes", "No"], "outcome_prices": [1.0, 0.0]},
        ),
        patch("engine.log_signal_event", side_effect=trade_logger.log_signal_event),
    ):
        engine.settle_shadow_signals(max_checks=1)

    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 2
    resolution = rows[-1]
    assert resolution["type"] == "signal_event"
    assert resolution["snapshot_event"] == "resolution"
    assert resolution["signal_status"] == "won"
    assert resolution["resolved_side"] == "YES"
    assert resolution["market_yes_at_close"] == 1.0


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


def test_engine_stop_shuts_down_runtime_services():
    engine = Engine()

    with patch.object(engine, "stop_runtime_services") as mock_stop_runtime:
        engine.stop()

    mock_stop_runtime.assert_called_once()


def test_monitor_snapshot_summarizes_signal_board():
    engine = Engine()
    engine.monitor_updated_at = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    engine.monitor_signals = [
        {
            "market_type": "5m",
            "direction": "BUY",
            "signal_side": "YES",
            "decision_stage": "traded",
            "confidence": 0.72,
        },
        {
            "market_type": "15m",
            "direction": "SELL",
            "signal_side": "NO",
            "decision_stage": "risk_blocked",
            "confidence": 0.51,
        },
        {
            "market_type": "5m",
            "direction": "",
            "signal_side": "",
            "decision_stage": "analysis_skip",
            "confidence": 0.0,
        },
    ]

    snapshot = engine.get_monitor_snapshot()

    assert snapshot["signal_summary"]["5m"]["BUY"]["count"] == 1
    assert snapshot["signal_summary"]["5m"]["BUY"]["actionable"] == 1
    assert snapshot["signal_summary"]["15m"]["SELL"]["count"] == 1
    assert snapshot["signal_summary"]["15m"]["SELL"]["actionable"] == 1
    assert snapshot["monitor_updated_at"] == "2026-04-10T12:00:00+00:00"


def test_warm_active_coins_falls_back_to_direct_refresh_for_stale_symbols():
    engine = Engine()

    with (
        patch.object(engine.runtime_data_plane.reference_cache, "price", return_value=None),
        patch.object(engine.runtime_data_plane.reference_cache, "age_seconds", return_value=None),
        patch("engine.get_prices_batch", return_value={}) as mock_batch,
        patch("engine.ensure_reference_recent", return_value=True) as mock_ensure,
    ):
        engine._warm_active_coins({"BTC", "ETH"})

    mock_batch.assert_called_once()
    assert mock_batch.call_args.args[0] == {"BTC", "ETH"}
    mock_ensure.assert_has_calls(
        [
            call("BTC", max_age=MAX_REFERENCE_AGE_SECONDS_FALLBACK),
            call("ETH", max_age=MAX_REFERENCE_AGE_SECONDS_FALLBACK),
        ],
        any_order=True,
    )


def test_tick_updates_monitor_state_and_emits_signal_event():
    engine = Engine(executor=StubExecutor())
    market = _make_market(end_minutes=1)
    udm = UpDownMarket(
        market=market,
        coin="BTC",
        interval_minutes=5,
        seconds_to_close=20,
        up_outcome_index=0,
    )
    signal = _make_signal(market=market)
    analysis = UpdownAnalysis(
        udm=udm,
        signal=signal,
        reason="BTC implied UP at 82%, edge +7.0%, 20s to close",
        decision_stage="analysis_ready",
        seconds_to_close=20,
        implied_up_prob=0.82,
        model_up_prob=0.89,
        signal_side="YES",
        direction="BUY",
        confidence=0.67,
        entry_price=0.82,
        raw_edge=0.07,
        effective_edge=0.06,
        estimated_fee=0.01,
        min_edge=0.05,
        momentum=0.002,
        price_state="confirm",
    )

    with (
        patch("engine.fetch_active_markets", return_value=[market]),
        patch("engine.find_updown_markets", return_value=[udm]),
        patch("engine.analyze_updown_market_detail", return_value=analysis),
        patch.object(engine, "_warm_active_coins"),
        patch.object(engine, "_start_background_price_warm"),
        patch.object(engine, "_try_execute", return_value=(None, "risk_blocked", "test block")),
        patch("engine.log_signal_event") as mock_signal_event,
    ):
        trades = engine.tick()

    assert trades == []
    assert engine.monitor_signals[0]["market_slug"] == market.slug
    assert engine.monitor_signals[0]["decision_stage"] == "risk_blocked"
    assert "test block" in engine.monitor_signals[0]["reason"]
    mock_signal_event.assert_called_once()


def test_live_settlement_marks_winning_trade_redemption_pending():
    executor = StubExecutor()
    trade = _make_trade(
        status="pending",
        condition_id="0xcondition",
        end_date=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    engine = Engine(executor=executor)
    engine.trades = [trade]

    with (
        patch("engine.TRADING_MODE", "live"),
        patch(
            "engine.fetch_resolved_market",
            return_value={"outcomes": ["Yes", "No"], "outcome_prices": [1.0, 0.0]},
        ),
    ):
        engine.settle_trades()

    assert trade.status == "won"
    assert trade.redemption_status == "pending"
    assert trade.redemption_tx_id == ""
    assert trade.redemption_updated_at is not None


def test_process_redemptions_shares_single_tx_per_condition():
    executor = StubExecutor(
        supports_redemption=True,
        redeem_results=[_make_redemption_result()],
    )
    trades = [
        _make_trade(
            market_slug="btc-updown-5m-1",
            order_id="order-1",
            status="won",
            condition_id="0xcondition",
            redemption_status="pending",
        ),
        _make_trade(
            market_slug="btc-updown-5m-2",
            order_id="order-2",
            status="won",
            condition_id="0xcondition",
            redemption_status="pending",
        ),
    ]
    engine = Engine(executor=executor)
    engine.trades = trades

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = [{"redeemable": True, "negativeRisk": False}]

    with (
        patch("engine.TRADING_MODE", "live"),
        patch("engine.requests.get", return_value=response),
    ):
        engine._process_redemptions()

    assert executor.redeem_calls == ["0xcondition"]
    assert all(trade.redemption_tx_id == "redeem-123" for trade in trades)
    assert all(trade.redemption_status == "pending" for trade in trades)


def test_process_redemptions_polls_pending_tx_without_resubmit():
    executor = StubExecutor(
        supports_redemption=True,
        redemption_status_results={
            "redeem-123": _make_redemption_result(
                transaction_id="redeem-123",
                transaction_hash="0xhash",
                raw_state="STATE_NEW",
            )
        },
    )
    trade = _make_trade(
        status="won",
        condition_id="0xcondition",
        redemption_status="pending",
        redemption_tx_id="redeem-123",
    )
    engine = Engine(executor=executor)
    engine.trades = [trade]

    with patch("engine.TRADING_MODE", "live"):
        engine._process_redemptions()

    assert executor.redemption_status_calls == ["redeem-123"]
    assert executor.redeem_calls == []
    assert trade.redemption_status == "pending"


def test_process_redemptions_retries_after_failed_cooldown():
    executor = StubExecutor(
        supports_redemption=True,
        redeem_results=[_make_redemption_result()],
    )
    trade = _make_trade(
        status="won",
        condition_id="0xcondition",
        redemption_status="failed",
        redemption_updated_at=datetime.now(timezone.utc) - timedelta(seconds=61),
    )
    engine = Engine(executor=executor)
    engine.trades = [trade]

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = [{"redeemable": True, "negativeRisk": False}]

    with (
        patch("engine.TRADING_MODE", "live"),
        patch("engine.requests.get", return_value=response),
    ):
        engine._process_redemptions()

    assert executor.redeem_calls == ["0xcondition"]
    assert trade.redemption_tx_id == "redeem-123"
    assert trade.redemption_status == "pending"


def test_process_redemptions_marks_external_when_not_redeemable():
    executor = StubExecutor(supports_redemption=True)
    trade = _make_trade(
        status="won",
        condition_id="0xcondition",
        redemption_status="pending",
    )
    engine = Engine(executor=executor)
    engine.trades = [trade]

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = []

    with (
        patch("engine.TRADING_MODE", "live"),
        patch("engine.requests.get", return_value=response),
    ):
        engine._process_redemptions()

    assert executor.redeem_calls == []
    assert trade.redemption_status == "external"


def test_process_redemptions_runs_catch_up_on_startup():
    executor = StubExecutor(
        supports_redemption=True,
        redeem_results=[_make_redemption_result()],
    )
    trade = _make_trade(
        status="won",
        condition_id="0xcondition",
        redemption_status="pending",
        executor_type="LiveExecutor",
    )

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = [{"redeemable": True, "negativeRisk": False}]

    with (
        patch("engine.TRADING_MODE", "live"),
        patch("engine.read_trades", return_value=[trade]),
        patch("engine.requests.get", return_value=response),
    ):
        engine = Engine(executor=executor)

    assert executor.redeem_calls == ["0xcondition"]
    assert engine.trades[0].redemption_tx_id == "redeem-123"


@pytest.mark.parametrize("mode", ["paper", "simulation"])
def test_process_redemptions_skips_non_live_modes(mode):
    executor = StubExecutor(
        supports_redemption=True,
        redeem_results=[_make_redemption_result()],
    )
    trade = _make_trade(
        status="won",
        condition_id="0xcondition",
        redemption_status="pending",
    )
    engine = Engine(executor=executor)
    engine.trades = [trade]

    with patch("engine.TRADING_MODE", mode):
        engine._process_redemptions()

    assert executor.redeem_calls == []
    assert trade.redemption_tx_id == ""
