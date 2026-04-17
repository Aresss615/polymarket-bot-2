import sys
import threading
import time
from collections import Counter, deque
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
import json

import requests

from copy_trading import CopyTradingService
from config import (
    APP_CONFIG,
    ARBITRAGE_STRATEGY_MODE,
    BTC_NO_STRATEGY_MODE,
    CODEX_VERSION,
    ENABLE_REALTIME_DATA_PLANE,
    EVENTS_JSONL,
    LIVE_DAILY_MAX_LOSS,
    LIVE_MAX_BET,
    LIVE_MAX_OPEN_EXPOSURE,
    LIVE_MIN_BET,
    LIVE_STARTING_BALANCE,
    MAX_BET,
    MAX_BETS_PER_CYCLE,
    MIN_BET,
    Market,
    OpenOrder,
    POLYMARKET_RELAYER_URL,
    POLYMARKET_WALLET_TYPE,
    REALTIME_DISCOVERY_REFRESH_SECONDS,
    RiskConfig,
    STARTING_BALANCE,
    STRATEGY_MODE_DISABLED,
    STRATEGY_MODE_SHADOW,
    STRATEGY_VERSION,
    STRUCTURAL_ARB_STRATEGY_MODE,
    SUPPORTED_COINS,
    SIMULATION_MAX_BETS_PER_CYCLE,
    TICK_INTERVAL,
    TRADING_MODE,
    Signal,
    UPDOWN_5M_STRATEGY_MODE,
    UPDOWN_15M_STRATEGY_MODE,
    market_side_price,
    market_side_token_id,
    SECOND_CHANCE_WINDOW_SECONDS,
    Trade,
    UpDownMarket,
)
from strategy_eval import evaluate_15m_mode
from market_fetcher import fetch_active_markets, fetch_resolved_market, find_updown_markets
from level_analyzer import UpdownAnalysis, analyze_updown_market_detail
from logger import read_open_orders, read_trades, save_open_orders, save_trades
from price_feed import (
    active_reference_max_age_seconds,
    ensure_reference_recent,
    get_prices_batch,
    get_reference_snapshot,
    reference_feed_mode,
    reference_feed_status,
)
from order_executor import OrderExecutor, PaperExecutor
from risk_manager import RiskManager
from trade_logger import (
    log_event,
    log_order_event,
    log_redemption_event,
    log_risk_block,
    log_settlement,
    log_signal_event,
    log_trade_jsonl,
)
from runtime_data import RUNTIME_DATA_PLANE

MONITOR_SIGNAL_LIMIT = 40
MONITOR_ACTIONABLE_STAGES = {
    "traded",
    "order_live",
    "risk_blocked",
    "cycle_limit_skip",
    "already_traded_skip",
    "active_order_skip",
    "balance_skip",
    "order_rejected",
    "tightened_skip",
    "shadow_only",
}
SIGNAL_STAGE_RANK = {
    "traded": 0,
    "order_live": 1,
    "risk_blocked": 2,
    "shadow_only": 3,
    "cycle_limit_skip": 3,
    "tightened_skip": 4,
    "already_traded_skip": 5,
    "active_order_skip": 6,
    "balance_skip": 7,
    "order_rejected": 8,
    "analysis_skip": 9,
    "analysis_ready": 10,
}

_EXECUTOR_TYPES_BY_MODE = {
    "paper": {"", "PaperExecutor"},
    "simulation": {"SimulationExecutor"},
    "live": {"LiveExecutor"},
}
_REDEMPTION_RETRY_COOLDOWN_SECONDS = 60.0
_REDEMPTION_FINAL_STATUSES = {"confirmed", "external", "unsupported", "disabled"}
_SHADOW_SETTLEMENT_SKIP_STAGES = {"traded", "order_live", "already_traded_skip", "active_order_skip"}
_TERMINAL_SIGNAL_STATUSES = {"won", "lost"}
_SIGNAL_EVENT_RESERVED_FIELDS = {"type", "timestamp", "codex_version"}


def _history_matches_current_mode(executor_type: str) -> bool:
    allowed = _EXECUTOR_TYPES_BY_MODE.get(TRADING_MODE, {""})
    return (executor_type or "").strip() in allowed


def _shadow_signal_allowed(signal: Signal) -> bool:
    if signal.strategy_mode != STRATEGY_MODE_SHADOW:
        return True
    return (signal.strategy_route or "") == "high_prob_shadow"


def _winning_side_from_resolution(resolved: dict) -> str | None:
    outcomes = list(resolved.get("outcomes") or [])
    prices = list(resolved.get("outcome_prices") or [])
    if not outcomes or not prices:
        return None

    try:
        winning_idx = prices.index(1.0)
    except ValueError:
        return None

    winning_outcome = str(outcomes[winning_idx]).strip().upper()
    if winning_outcome in ("UP", "YES"):
        return "YES"
    if winning_outcome in ("DOWN", "NO"):
        return "NO"
    return "YES" if winning_idx == 0 else "NO"


class Engine:
    def __init__(self, executor: OrderExecutor | None = None, risk_manager: RiskManager | None = None):
        self.executor = executor or PaperExecutor()
        self.risk_manager = risk_manager or RiskManager(RiskConfig())
        self.runtime_data_plane = RUNTIME_DATA_PLANE
        self._runtime_started = False
        self._startup_logged = False
        self._execution_lock = threading.RLock()
        self.trades: list[Trade] = []
        self.open_orders: list[OpenOrder] = []
        self.traded_markets: set[str] = set()
        self.executed_signal_keys: set[str] = set()
        self._clob_open_token_ids: set[str] = set()
        self.running = False
        self.status = "Initializing"
        self.activity_log: deque[str] = deque(maxlen=30)
        self.markets = []
        self.updown_markets_found: list = []
        self.articles_found: list = []
        self._cache_warm_future: Future | None = None
        self._background_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="engine-bg")
        self.tick_count = 0
        self.wins = 0
        self.losses = 0
        self.mode_15m = evaluate_15m_mode([])  # default until first tick
        self.monitor_signals: list[dict] = []
        self.monitor_updated_at: datetime | None = None
        self._last_market_refresh_at: float | None = None
        self._order_token_ids: dict[str, str] = {}
        self._retry_watches: dict[str, dict] = {}
        self._last_execution_reason: str = ""
        self._redemption_disabled_logged = False
        self.copy_trading_service: CopyTradingService | None = None
        if APP_CONFIG.copy_trading.enabled and APP_CONFIG.copy_trading.target_wallet:
            self.copy_trading_service = CopyTradingService(APP_CONFIG.copy_trading.target_wallet)
        self._load_history()
        self._reconcile_wallet_balance()
        self._seed_clob_open_token_ids()
        self.risk_manager.bootstrap_from_history(self.trades, account_equity=self.account_equity)
        if self.open_orders:
            self._reconcile_open_orders()
        self._process_redemptions(startup=True)

    def start_runtime_services(self) -> None:
        if not self._startup_logged:
            self._log(f"Python executable: {sys.executable}")
            diagnostics = self.runtime_data_plane.diagnostics()
            self._log(
                "websocket-client available: "
                f"{diagnostics['websocket_client_available']}"
            )
            log_event("session_start", {
                "trading_mode": TRADING_MODE,
                "executor_type": type(self.executor).__name__,
                "strategy_version": STRATEGY_VERSION,
                "codex_version": CODEX_VERSION,
                "updown_5m_mode": UPDOWN_5M_STRATEGY_MODE,
                "updown_15m_mode": UPDOWN_15M_STRATEGY_MODE,
                "btc_no_mode": BTC_NO_STRATEGY_MODE,
                "arbitrage_mode": ARBITRAGE_STRATEGY_MODE,
                "structural_arb_mode": STRUCTURAL_ARB_STRATEGY_MODE,
                "live_max_bet": LIVE_MAX_BET,
                "live_min_bet": LIVE_MIN_BET,
                "live_daily_max_loss": LIVE_DAILY_MAX_LOSS,
                "live_max_open_exposure": LIVE_MAX_OPEN_EXPOSURE,
                "live_starting_balance": LIVE_STARTING_BALANCE,
                "relayer_url": POLYMARKET_RELAYER_URL,
                "wallet_type": POLYMARKET_WALLET_TYPE,
            })
            self._startup_logged = True
        if ENABLE_REALTIME_DATA_PLANE and not self._runtime_started:
            self.runtime_data_plane.start()
            self._runtime_started = True
            diagnostics = self.runtime_data_plane.diagnostics()
            workers = diagnostics["workers"]
            self._log(
                "Runtime workers started: "
                f"market={workers['market']} rtds={workers['rtds']} user={workers['user']}"
            )
        self._log(
            f"Reference feed mode: {reference_feed_mode()} "
            f"(max age {active_reference_max_age_seconds():.1f}s)"
        )
        if self.copy_trading_service is not None and not self.copy_trading_service.running:
            self.copy_trading_service.start(
                self.process_signal,
                poll_interval_ms=APP_CONFIG.copy_trading.poll_interval_ms,
            )
            self._log(
                f"Copy-trading service started for {APP_CONFIG.copy_trading.target_wallet}"
            )

    def stop_runtime_services(self) -> None:
        if self.copy_trading_service is not None:
            self.copy_trading_service.stop()
        if self._runtime_started:
            self.runtime_data_plane.stop()
            self._runtime_started = False

    def _load_history(self):
        """Restore confirmed positions and any persisted open live orders."""
        self.balance = STARTING_BALANCE
        all_trades = read_trades()
        all_open_orders = read_open_orders()
        self.trades = [
            trade for trade in all_trades if _history_matches_current_mode(trade.executor_type)
        ]
        self.open_orders = [
            order for order in all_open_orders if _history_matches_current_mode(order.executor_type)
        ]
        self._order_token_ids = {
            order.order_id: order.token_id
            for order in self.open_orders
            if order.order_id and order.token_id
        }

        for trade in self.trades:
            self._remember_trade_key(trade)
            self.balance -= trade.size
            if trade.status == "won":
                self.balance += trade.payout
                self.wins += 1
            elif trade.status == "lost":
                self.losses += 1

        if self.trades:
            self._log(
                f"Loaded {len(self.trades)} trades ({self.wins}W/{self.losses}L), balance ${self.balance:.2f}"
            )
        skipped_trades = len(all_trades) - len(self.trades)
        skipped_orders = len(all_open_orders) - len(self.open_orders)
        if skipped_trades or skipped_orders:
            self._log(
                f"Ignored {skipped_trades} trades and {skipped_orders} open orders from other modes"
            )
        if self.open_orders:
            self._log(
                f"Restored {len(self.open_orders)} open orders, ${self.reserved_open_exposure:.2f} reserved"
            )

    def _seed_clob_open_token_ids(self) -> None:
        if TRADING_MODE != "live":
            return
        clob_token_ids = self.executor.get_clob_open_token_ids()
        local_token_ids = {order.token_id for order in self.open_orders if order.token_id}
        untracked = clob_token_ids - local_token_ids
        if untracked:
            self._clob_open_token_ids = untracked
            self._log(
                f"Seeded {len(untracked)} CLOB open token_id(s) not in open_orders.csv "
                f"(crash-recovery guard)"
            )

    def _reconcile_wallet_balance(self) -> None:
        if TRADING_MODE != "live":
            return
        wallet_balance = self.executor.get_wallet_balance()
        if wallet_balance is None:
            return
        discrepancy = abs(wallet_balance - self.balance)
        if discrepancy > LIVE_MIN_BET:
            self._log(
                f"WARNING: computed balance ${self.balance:.2f} differs from "
                f"wallet balance ${wallet_balance:.2f} by ${discrepancy:.2f} "
                f"(threshold ${LIVE_MIN_BET:.2f}) — check for manually placed "
                f"orders or CSV drift"
            )

    def _log(self, msg: str):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.activity_log.append(f"[{ts}] {msg}")

    def _signal_key(self, signal: Signal) -> str:
        if signal.strategy == "copy_trade":
            return signal.signal_epoch_id or f"copy:{signal.market.slug}:{signal.side}:{signal.reason}"
        return signal.market.slug

    def _remember_trade_key(self, trade: Trade) -> None:
        if trade.strategy == "copy_trade" and trade.signal_epoch_id:
            self.executed_signal_keys.add(trade.signal_epoch_id)
            return
        self.traded_markets.add(trade.market_slug)
        self.executed_signal_keys.add(trade.market_slug)

    def _clear_retry_watch(self, market_slug: str) -> None:
        if market_slug:
            self._retry_watches.pop(market_slug, None)

    def _prune_retry_watches(self, active_markets: list[UpDownMarket] | None = None) -> None:
        if not self._retry_watches:
            return
        now = time.time()
        active_slugs = {udm.market.slug for udm in (active_markets or [])}
        for market_slug, watch in list(self._retry_watches.items()):
            observed_at = float(watch.get("observed_at") or 0.0)
            if observed_at <= 0 or (now - observed_at) > SECOND_CHANCE_WINDOW_SECONDS:
                self._retry_watches.pop(market_slug, None)
                continue
            if active_slugs and market_slug not in active_slugs:
                self._retry_watches.pop(market_slug, None)
                continue
            if market_slug in self.traded_markets or market_slug in self.active_order_markets:
                self._retry_watches.pop(market_slug, None)

    def _update_retry_watch(self, analysis: UpdownAnalysis) -> None:
        market_slug = analysis.udm.market.slug
        if not market_slug:
            return
        if TRADING_MODE != "live":
            self._clear_retry_watch(market_slug)
            return
        if market_slug in self.traded_markets or market_slug in self.active_order_markets:
            self._clear_retry_watch(market_slug)
            return
        if analysis.signal and analysis.strategy_route == "second_chance_retry":
            self._clear_retry_watch(market_slug)
            return

        existing = self._retry_watches.get(market_slug)
        actual_move_side = analysis.actual_move_side or ""
        if existing and actual_move_side and existing.get("actual_move_side") != actual_move_side:
            self._clear_retry_watch(market_slug)
            existing = None

        if (
            analysis.signal is None
            and analysis.strategy_route == "too_late_or_overpriced"
            and actual_move_side in {"YES", "NO"}
            and analysis.entry_price not in (None, 0.0)
            and analysis.tick_size not in (None, 0.0)
        ):
            self._retry_watches[market_slug] = {
                "market_slug": market_slug,
                "actual_move_side": actual_move_side,
                "entry_price": float(analysis.entry_price),
                "tick_size": float(analysis.tick_size),
                "observed_at": time.time(),
            }

    def _redemption_wallet_address(self) -> str:
        return str(
            getattr(self.executor, "redemption_wallet_address", "")
            or getattr(self.executor, "funder", "")
            or ""
        )

    @staticmethod
    def _condition_redemption_updated_at(trades: list[Trade]) -> datetime | None:
        timestamps = [trade.redemption_updated_at for trade in trades if trade.redemption_updated_at]
        return max(timestamps) if timestamps else None

    @staticmethod
    def _condition_redemption_tx_id(trades: list[Trade]) -> str:
        for trade in trades:
            if trade.redemption_tx_id:
                return trade.redemption_tx_id
        return ""

    @staticmethod
    def _update_redemption_state(
        trades: list[Trade],
        *,
        status: str | None = None,
        tx_id: str | None = None,
        tx_hash: str | None = None,
        error: str | None = None,
        updated_at: datetime | None = None,
    ) -> bool:
        changed = False
        for trade in trades:
            if status is not None and trade.redemption_status != status:
                trade.redemption_status = status
                changed = True
            if tx_id is not None and trade.redemption_tx_id != tx_id:
                trade.redemption_tx_id = tx_id
                changed = True
            if tx_hash is not None and trade.redemption_tx_hash != tx_hash:
                trade.redemption_tx_hash = tx_hash
                changed = True
            if error is not None and trade.redemption_error != error:
                trade.redemption_error = error
                changed = True
            if updated_at is not None and trade.redemption_updated_at != updated_at:
                trade.redemption_updated_at = updated_at
                changed = True
        return changed

    def _fetch_redeemable_positions(self, condition_id: str) -> list[dict] | None:
        wallet_address = self._redemption_wallet_address()
        if not wallet_address:
            return None
        response = requests.get(
            f"{APP_CONFIG.market_data.data_api_url}/positions",
            params={
                "user": wallet_address,
                "market": condition_id,
                "redeemable": "true",
                "sizeThreshold": "0",
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []

    def _process_redemptions(self, *, startup: bool = False) -> None:
        if TRADING_MODE != "live":
            return

        winning_trades = [
            trade
            for trade in self.trades
            if trade.status == "won"
            and trade.condition_id
            and trade.redemption_status not in _REDEMPTION_FINAL_STATUSES
        ]
        if not winning_trades:
            return

        wallet_type = getattr(self.executor, "wallet_type", "")
        if wallet_type == "eoa":
            changed = self._update_redemption_state(
                winning_trades,
                status="disabled",
                error="auto-redeem is disabled for eoa wallets in v1",
                updated_at=datetime.now(timezone.utc),
            )
            if changed:
                save_trades(self.trades)
                log_redemption_event(
                    "disabled",
                    "",
                    {
                        "trade_count": len(winning_trades),
                        "wallet_type": wallet_type,
                    },
                )
            if not self._redemption_disabled_logged:
                self._log("Auto-redeem disabled in v1 for eoa wallets")
                self._redemption_disabled_logged = True
            return

        if not self.executor.supports_redemption():
            if not self._redemption_disabled_logged:
                self._log("Auto-redeem unavailable: relayer-backed live redemption is not configured")
                self._redemption_disabled_logged = True
            return

        changed = False
        now = datetime.now(timezone.utc)
        trades_by_condition: dict[str, list[Trade]] = {}
        for trade in winning_trades:
            trades_by_condition.setdefault(trade.condition_id, []).append(trade)

        for condition_id, trades in trades_by_condition.items():
            active_tx_id = ""
            if any(
                trade.redemption_status == "pending" and trade.redemption_tx_id
                for trade in trades
            ):
                active_tx_id = self._condition_redemption_tx_id(trades)

            if active_tx_id:
                result = self.executor.get_redemption_status(active_tx_id)
                changed |= self._update_redemption_state(
                    trades,
                    status=result.status,
                    tx_id=result.transaction_id or active_tx_id,
                    tx_hash=result.transaction_hash,
                    error=result.error,
                    updated_at=now,
                )
                log_redemption_event(
                    "poll",
                    condition_id,
                    {
                        "transaction_id": result.transaction_id or active_tx_id,
                        "transaction_hash": result.transaction_hash,
                        "status": result.status,
                        "raw_state": result.raw_state,
                        "error": result.error,
                        "startup": startup,
                    },
                )
                if result.status == "pending":
                    continue
                if result.status in _REDEMPTION_FINAL_STATUSES or result.status == "confirmed":
                    continue

            latest_update = self._condition_redemption_updated_at(trades)
            if latest_update is not None and any(
                trade.redemption_status == "failed" for trade in trades
            ):
                if (now - latest_update).total_seconds() < _REDEMPTION_RETRY_COOLDOWN_SECONDS:
                    continue

            try:
                redeemable_positions = self._fetch_redeemable_positions(condition_id)
            except Exception as exc:
                changed |= self._update_redemption_state(
                    trades,
                    status="failed",
                    error=str(exc),
                    updated_at=now,
                )
                log_redemption_event(
                    "positions_error",
                    condition_id,
                    {
                        "error": str(exc),
                        "startup": startup,
                    },
                )
                continue

            if redeemable_positions is None:
                continue

            if any(bool(position.get("negativeRisk")) for position in redeemable_positions):
                changed |= self._update_redemption_state(
                    trades,
                    status="unsupported",
                    error="negative-risk redemption is unsupported in v1",
                    updated_at=now,
                )
                log_redemption_event(
                    "unsupported",
                    condition_id,
                    {
                        "reason": "negative-risk redemption is unsupported in v1",
                        "startup": startup,
                    },
                )
                continue

            if not redeemable_positions:
                changed |= self._update_redemption_state(
                    trades,
                    status="external",
                    error="wallet no longer reports a redeemable position for this condition",
                    updated_at=now,
                )
                log_redemption_event(
                    "external",
                    condition_id,
                    {
                        "trade_count": len(trades),
                        "startup": startup,
                    },
                )
                continue

            result = self.executor.redeem_condition(condition_id)
            changed |= self._update_redemption_state(
                trades,
                status=result.status,
                tx_id=result.transaction_id,
                tx_hash=result.transaction_hash,
                error=result.error,
                updated_at=now,
            )
            log_redemption_event(
                "submit",
                condition_id,
                {
                    "transaction_id": result.transaction_id,
                    "transaction_hash": result.transaction_hash,
                    "status": result.status,
                    "raw_state": result.raw_state,
                    "error": result.error,
                    "startup": startup,
                },
            )
            if result.status == "pending":
                self._log(
                    f"Redemption submitted for {condition_id} ({result.transaction_id or 'pending'})"
                )
            elif result.status == "confirmed":
                self._log(f"Redemption confirmed for {condition_id}")
            elif result.status == "failed":
                self._log(f"Redemption failed for {condition_id}: {result.error or 'unknown error'}")

        if changed:
            save_trades(self.trades)

    def _set_monitor_signals(self, analyses: list[UpdownAnalysis]) -> None:
        records = [analysis.to_record() for analysis in analyses]
        records.sort(
            key=lambda row: (
                SIGNAL_STAGE_RANK.get(row["decision_stage"], 99),
                -row.get("confidence", 0.0),
                row.get("seconds_to_close", 9999),
                row.get("coin", ""),
            )
        )
        self.monitor_signals = records[:MONITOR_SIGNAL_LIMIT]
        self.monitor_updated_at = datetime.now(timezone.utc)

    def _emit_signal_events(self, analyses: list[UpdownAnalysis]) -> None:
        for analysis in analyses:
            payload = {
                **analysis.to_record(),
                "tick_count": self.tick_count,
                "trading_mode": TRADING_MODE,
                "strategy_version": STRATEGY_VERSION,
            }
            log_signal_event(payload)

    def _load_latest_signal_snapshots(self) -> dict[str, dict]:
        if not EVENTS_JSONL.exists():
            return {}

        latest_by_id: dict[str, dict] = {}
        with open(EVENTS_JSONL, encoding="utf-8-sig") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("type") != "signal_event":
                    continue
                signal_id = str(row.get("signal_id") or "").strip()
                if not signal_id:
                    continue
                timestamp = str(row.get("timestamp") or "")
                if not timestamp:
                    continue
                existing = latest_by_id.get(signal_id)
                if existing is None or timestamp >= str(existing.get("timestamp") or ""):
                    latest_by_id[signal_id] = row
        return latest_by_id

    def _shadow_signal_end_ts(self, signal_row: dict) -> float | None:
        window_start_ts = signal_row.get("window_start_ts")
        if window_start_ts in (None, ""):
            market_slug = str(signal_row.get("market_slug") or "")
            try:
                window_start_ts = float(market_slug.rsplit("-", 1)[1])
            except (IndexError, TypeError, ValueError):
                return None
        interval_minutes = signal_row.get("interval_minutes")
        if interval_minutes in (None, ""):
            return None
        try:
            return float(window_start_ts) + (float(interval_minutes) * 60.0)
        except (TypeError, ValueError):
            return None

    def settle_shadow_signals(self, max_checks: int = 10) -> None:
        now = datetime.now(timezone.utc).timestamp()
        api_calls = 0

        latest_signals = self._load_latest_signal_snapshots()
        for signal_row in sorted(latest_signals.values(), key=lambda row: str(row.get("timestamp") or "")):
            if api_calls >= max_checks:
                break
            if signal_row.get("strategy_mode") != STRATEGY_MODE_SHADOW:
                continue
            if signal_row.get("signal_side") not in {"YES", "NO"}:
                continue
            if signal_row.get("decision_stage") in _SHADOW_SETTLEMENT_SKIP_STAGES:
                continue
            if signal_row.get("signal_status") in _TERMINAL_SIGNAL_STATUSES:
                continue

            end_ts = self._shadow_signal_end_ts(signal_row)
            if end_ts is None or now < end_ts + 10.0:
                continue

            market_slug = str(signal_row.get("market_slug") or "")
            if not market_slug:
                continue

            api_calls += 1
            resolved = fetch_resolved_market(market_slug)
            if resolved is None:
                continue

            winning_side = _winning_side_from_resolution(resolved)
            if winning_side not in {"YES", "NO"}:
                continue

            payload = {
                key: value
                for key, value in signal_row.items()
                if key not in _SIGNAL_EVENT_RESERVED_FIELDS
            }
            payload["snapshot_event"] = "resolution"
            payload["signal_status"] = "won" if signal_row.get("signal_side") == winning_side else "lost"
            payload["resolved_side"] = winning_side
            payload["market_yes_at_close"] = 1.0 if winning_side == "YES" else 0.0
            log_signal_event(payload)

    def _monitor_summary(self) -> dict:
        summary = {
            "5m": {"BUY": {"count": 0, "actionable": 0, "best_confidence": 0.0}, "SELL": {"count": 0, "actionable": 0, "best_confidence": 0.0}},
            "15m": {"BUY": {"count": 0, "actionable": 0, "best_confidence": 0.0}, "SELL": {"count": 0, "actionable": 0, "best_confidence": 0.0}},
        }
        for row in self.monitor_signals:
            market_type = row.get("market_type")
            direction = row.get("direction")
            if market_type not in summary or direction not in summary[market_type]:
                continue
            if not row.get("signal_side"):
                continue
            cell = summary[market_type][direction]
            cell["count"] += 1
            if row.get("decision_stage") in MONITOR_ACTIONABLE_STAGES:
                cell["actionable"] += 1
            cell["best_confidence"] = max(cell["best_confidence"], row.get("confidence", 0.0))
        return summary

    def _signal_route_summary(self) -> dict[str, int]:
        routes = Counter()
        for row in self.monitor_signals:
            routes[row.get("strategy_route") or "unclassified"] += 1
        return dict(routes)

    def _reference_feed_snapshot(self) -> dict:
        coins = sorted(
            {
                *(udm.coin for udm in self.updown_markets_found if getattr(udm, "coin", "")),
                *APP_CONFIG.strategies.updown.live_candidate_coins,
            }
        )
        max_age = active_reference_max_age_seconds()
        per_coin = []
        for coin in coins:
            snapshot = get_reference_snapshot(coin)
            age = snapshot.get("active_reference_age_seconds")
            per_coin.append(
                {
                    "coin": coin,
                    "reference_age_seconds": age,
                    "max_age_seconds": max_age,
                    "stale": age is None or age > max_age,
                    "source": snapshot.get("source"),
                    "active_reference_price": snapshot.get("active_reference_price"),
                }
            )
        return {
            **reference_feed_status(),
            "per_coin": per_coin,
        }

    def get_monitor_snapshot(self) -> dict:
        recent_trades = []
        for trade in reversed(self.trades[-12:]):
            if trade.status == "won":
                pnl = trade.payout - trade.size
            elif trade.status == "lost":
                pnl = -trade.size
            else:
                pnl = None
            recent_trades.append(
                {
                    "timestamp": trade.timestamp.isoformat(),
                    "market_slug": trade.market_slug,
                    "question": trade.question,
                    "strategy": trade.strategy,
                    "side": trade.side,
                    "entry_price": round(trade.entry_price, 4),
                    "size": round(trade.size, 4),
                    "confidence": round(trade.confidence, 4),
                    "status": trade.status,
                    "payout": round(trade.payout, 4),
                    "pnl": round(pnl, 4) if pnl is not None else None,
                    "market_type": trade.market_type,
                    "reason": trade.reason,
                }
            )

        open_orders = []
        for order in self.open_orders[-10:]:
            open_orders.append(
                {
                    "order_id": order.order_id,
                    "market_slug": order.market_slug,
                    "question": order.question,
                    "side": order.side,
                    "status": order.status,
                    "raw_status": order.raw_status,
                    "market_type": order.market_type,
                    "reserved_size": round(order.reserved_size, 4),
                    "requested_size": round(order.requested_size, 4),
                    "updated_at": order.updated_at.isoformat(),
                }
            )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "monitor_updated_at": self.monitor_updated_at.isoformat() if self.monitor_updated_at else None,
            "trading_mode": TRADING_MODE,
            "status": self.status,
            "tick_count": self.tick_count,
            "balance": round(self.balance, 4),
            "available_balance": round(self.available_balance, 4),
            "reserved_open_exposure": round(self.reserved_open_exposure, 4),
            "account_equity": round(self.account_equity, 4),
            "wins": self.wins,
            "losses": self.losses,
            "settled_count": self.settled_count,
            "win_rate": round(self.win_rate, 4),
            "total_pnl": round(self.total_pnl, 4),
            "pending_trades": len(self.pending_trades),
            "open_orders_count": len(self.open_orders),
            "mode_15m": {
                "enabled": self.mode_15m.enabled,
                "tightened": self.mode_15m.tightened,
                "confidence_boost": round(self.mode_15m.confidence_boost, 4),
                "edge_boost": round(self.mode_15m.edge_boost, 4),
                "reason": self.mode_15m.reason,
            },
            "signal_summary": self._monitor_summary(),
            "signal_routes": self._signal_route_summary(),
            "signal_board": list(self.monitor_signals),
            "reference_feed": self._reference_feed_snapshot(),
            "copy_trading": (
                self.copy_trading_service.snapshot()
                if self.copy_trading_service is not None
                else {"enabled": False, "running": False, "target_wallet": "", "recent_events": []}
            ),
            "recent_trades": recent_trades,
            "open_orders": open_orders,
            "recent_activity": list(self.activity_log)[-12:],
        }

    @property
    def settled_count(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        if self.settled_count == 0:
            return 0.0
        return self.wins / self.settled_count

    @property
    def total_pnl(self) -> float:
        return sum(t.payout - t.size for t in self.trades if t.status != "pending")

    @property
    def pending_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.status == "pending"]

    @property
    def reserved_open_exposure(self) -> float:
        return sum(order.reserved_size for order in self.open_orders)

    @property
    def available_balance(self) -> float:
        return max(0.0, self.balance - self.reserved_open_exposure)

    @property
    def account_equity(self) -> float:
        return self.balance + sum(trade.size for trade in self.pending_trades) + self.reserved_open_exposure

    @property
    def active_order_markets(self) -> set[str]:
        return {order.market_slug for order in self.open_orders}

    def _refresh_markets(self, *, force: bool = False) -> None:
        now = time.time()
        refresh_due = (
            force
            or not self.markets
            or self._last_market_refresh_at is None
            or (now - self._last_market_refresh_at) >= REALTIME_DISCOVERY_REFRESH_SECONDS
        )
        if not refresh_due:
            return

        t0 = time.time()
        self.markets = fetch_active_markets()
        self._last_market_refresh_at = now
        fetch_ms = (time.time() - t0) * 1000
        self._log(f"Fetched {len(self.markets)} markets ({fetch_ms:.0f}ms)")

    def _update_runtime_subscriptions(self) -> None:
        if not ENABLE_REALTIME_DATA_PLANE:
            return
        market_tokens = {
            token_id
            for market in self.markets
            for token_id in getattr(market, "token_ids", [])
            if token_id
        }
        active_coins = {
            getattr(udm, "coin", "")
            for udm in self.updown_markets_found
            if getattr(udm, "coin", "")
        }
        self.runtime_data_plane.set_market_tokens(market_tokens)
        self.runtime_data_plane.set_reference_symbols(active_coins)

    def bet_size(self, confidence: float, entry_price: float) -> float:
        """Backward-compatible sizing helper used by tests and monitors."""
        del entry_price
        synthetic_signal = Signal(
            market=Market(
                condition_id="synthetic",
                question="synthetic",
                slug="synthetic-updown-5m-0",
                outcomes=["Up", "Down"],
                outcome_prices=[0.5, 0.5],
                token_ids=["synthetic-yes", "synthetic-no"],
                end_date=None,
                active=True,
            ),
            strategy="updown",
            side="YES",
            confidence=confidence,
            reason="synthetic",
        )
        base = self.risk_manager.recommended_position_size(synthetic_signal, self.account_equity)
        conf_scale = 0.5 + max(0.0, min(confidence, 1.0))
        return max(MIN_BET, min(MAX_BET, base * conf_scale))

    @staticmethod
    def _market_type_from_slug(slug: str) -> str:
        return "15m" if "-15m-" in slug else "5m"

    @staticmethod
    def _entry_price_for_signal(signal: Signal) -> float:
        if signal.entry_price not in (None, 0.0):
            return float(signal.entry_price)
        selected_price = market_side_price(signal.market, signal.side)
        return float(selected_price) if selected_price not in (None, 0.0) else 0.5

    def _position_size_for_signal(self, signal: Signal) -> float:
        if signal.requested_size_override not in (None, 0.0):
            return float(signal.requested_size_override)
        return self.risk_manager.recommended_position_size(signal, self.account_equity)

    def _find_trade_by_order_id(self, order_id: str) -> Trade | None:
        if not order_id:
            return None
        return next((trade for trade in self.trades if trade.order_id == order_id), None)

    def _record_trade_fill(
        self,
        *,
        market_slug: str,
        question: str,
        condition_id: str,
        strategy: str,
        side: str,
        confidence: float,
        reason: str,
        end_date,
        market_type: str,
        executor_type: str,
        order_id: str,
        result,
    ) -> Trade | None:
        fill_shares = result.fill_shares
        if fill_shares <= 0 and result.fill_price > 0:
            fill_shares = result.fill_size / result.fill_price
        if result.fill_size <= 0 or fill_shares <= 0:
            return None
        if order_id and result.token_id:
            self._order_token_ids[order_id] = result.token_id

        trade = self._find_trade_by_order_id(order_id)
        is_new = trade is None
        if trade is None:
            trade = Trade(
                timestamp=datetime.now(timezone.utc),
                market_slug=market_slug,
                question=question,
                condition_id=condition_id,
                strategy=strategy,
                side=side,
                entry_price=result.fill_price,
                size=result.fill_size,
                confidence=confidence,
                reason=reason,
                end_date=end_date,
                market_type=market_type,
                strategy_version=STRATEGY_VERSION,
                fees=result.fees,
                fill_price=result.fill_price,
                order_id=order_id,
                executor_type=executor_type,
                edge_gross=result.edge_gross,
                edge_net=result.edge_net,
                reference_symbol=result.reference_symbol,
                reference_price=result.reference_price,
                best_bid=result.best_bid,
                best_ask=result.best_ask,
                spread=result.spread,
                decision_latency_ms=result.decision_latency_ms or result.latency_ms,
                thesis_id=result.thesis_id,
                cancel_reason=result.cancel_reason,
                strategy_mode=result.strategy_mode,
                model_up_probability=result.model_up_probability,
                selected_side_probability=result.selected_side_probability,
                interval_open=result.interval_open,
                interval_high=result.interval_high,
                interval_low=result.interval_low,
                interval_close=result.interval_close,
                interval_return=result.interval_return,
                late_return_60s=result.late_return_60s,
                late_return_20s=result.late_return_20s,
                body_ratio=result.body_ratio,
                wick_imbalance=result.wick_imbalance,
                candle_regime=result.candle_regime,
                trend_alignment=result.trend_alignment,
                market_yes_at_open=result.market_yes_at_open,
                market_yes_at_decision=result.market_yes_at_decision,
                market_yes_at_close=result.market_yes_at_close,
                contrarian_block_reason=result.contrarian_block_reason,
                wallet_signal_source=result.wallet_signal_source,
                wallet_lead_score=result.wallet_lead_score,
                wallet_cluster=result.wallet_cluster,
                window_start_ts=result.window_start_ts,
                window_open_price=result.window_open_price,
                window_open_source=result.window_open_source,
                window_open_price_trusted=result.window_open_price_trusted,
                window_open_anchor_age_seconds=result.window_open_anchor_age_seconds,
                actual_window_return=result.actual_window_return,
                actual_move_regime=result.actual_move_regime,
                actual_move_side=result.actual_move_side,
                strategy_route=result.strategy_route,
                cluster_id=result.cluster_id,
                signal_epoch_id=result.signal_epoch_id,
                book_age_ms=result.book_age_ms,
                tick_size=result.tick_size,
                expected_fill_price=result.expected_fill_price,
                expected_cost=result.expected_cost,
                markout_1s=result.markout_1s,
                markout_5s=result.markout_5s,
                markout_30s=result.markout_30s,
            )
            self.trades.append(trade)
            self._remember_trade_key(trade)
        else:
            existing_shares = trade.size / trade.entry_price if trade.entry_price > 0 else 0.0
            total_cost = trade.size + result.fill_size
            total_shares = existing_shares + fill_shares
            avg_price = total_cost / total_shares if total_shares > 0 else result.fill_price
            trade.size = total_cost
            trade.entry_price = avg_price
            trade.fill_price = avg_price
            if condition_id and not trade.condition_id:
                trade.condition_id = condition_id
            trade.fees += result.fees
            trade.executor_type = trade.executor_type or executor_type
            trade.edge_gross = result.edge_gross or trade.edge_gross
            trade.edge_net = result.edge_net or trade.edge_net
            trade.reference_symbol = result.reference_symbol or trade.reference_symbol
            trade.reference_price = result.reference_price or trade.reference_price
            trade.best_bid = result.best_bid if result.best_bid is not None else trade.best_bid
            trade.best_ask = result.best_ask if result.best_ask is not None else trade.best_ask
            trade.spread = result.spread if result.spread is not None else trade.spread
            trade.decision_latency_ms = max(trade.decision_latency_ms, result.decision_latency_ms or result.latency_ms)
            trade.thesis_id = result.thesis_id or trade.thesis_id
            trade.cancel_reason = result.cancel_reason or trade.cancel_reason
            trade.strategy_mode = result.strategy_mode or trade.strategy_mode
            trade.model_up_probability = result.model_up_probability if result.model_up_probability is not None else trade.model_up_probability
            trade.selected_side_probability = result.selected_side_probability if result.selected_side_probability is not None else trade.selected_side_probability
            trade.interval_open = result.interval_open if result.interval_open is not None else trade.interval_open
            trade.interval_high = result.interval_high if result.interval_high is not None else trade.interval_high
            trade.interval_low = result.interval_low if result.interval_low is not None else trade.interval_low
            trade.interval_close = result.interval_close if result.interval_close is not None else trade.interval_close
            trade.interval_return = result.interval_return if result.interval_return is not None else trade.interval_return
            trade.late_return_60s = result.late_return_60s if result.late_return_60s is not None else trade.late_return_60s
            trade.late_return_20s = result.late_return_20s if result.late_return_20s is not None else trade.late_return_20s
            trade.body_ratio = result.body_ratio if result.body_ratio is not None else trade.body_ratio
            trade.wick_imbalance = result.wick_imbalance if result.wick_imbalance is not None else trade.wick_imbalance
            trade.candle_regime = result.candle_regime or trade.candle_regime
            trade.trend_alignment = result.trend_alignment or trade.trend_alignment
            trade.market_yes_at_open = result.market_yes_at_open if result.market_yes_at_open is not None else trade.market_yes_at_open
            trade.market_yes_at_decision = result.market_yes_at_decision if result.market_yes_at_decision is not None else trade.market_yes_at_decision
            trade.market_yes_at_close = result.market_yes_at_close if result.market_yes_at_close is not None else trade.market_yes_at_close
            trade.contrarian_block_reason = result.contrarian_block_reason or trade.contrarian_block_reason
            trade.wallet_signal_source = result.wallet_signal_source or trade.wallet_signal_source
            trade.wallet_lead_score = result.wallet_lead_score if result.wallet_lead_score is not None else trade.wallet_lead_score
            trade.wallet_cluster = result.wallet_cluster or trade.wallet_cluster
            trade.window_start_ts = result.window_start_ts if result.window_start_ts is not None else trade.window_start_ts
            trade.window_open_price = result.window_open_price if result.window_open_price is not None else trade.window_open_price
            trade.window_open_source = result.window_open_source or trade.window_open_source
            trade.window_open_price_trusted = result.window_open_price_trusted or trade.window_open_price_trusted
            trade.window_open_anchor_age_seconds = (
                result.window_open_anchor_age_seconds
                if result.window_open_anchor_age_seconds is not None
                else trade.window_open_anchor_age_seconds
            )
            trade.actual_window_return = result.actual_window_return if result.actual_window_return is not None else trade.actual_window_return
            trade.actual_move_regime = result.actual_move_regime or trade.actual_move_regime
            trade.actual_move_side = result.actual_move_side or trade.actual_move_side
            trade.strategy_route = result.strategy_route or trade.strategy_route
            trade.cluster_id = result.cluster_id or trade.cluster_id
            trade.signal_epoch_id = result.signal_epoch_id or trade.signal_epoch_id
            trade.book_age_ms = result.book_age_ms if result.book_age_ms is not None else trade.book_age_ms
            trade.tick_size = result.tick_size if result.tick_size is not None else trade.tick_size
            trade.expected_fill_price = result.expected_fill_price if result.expected_fill_price is not None else trade.expected_fill_price
            trade.expected_cost = result.expected_cost if result.expected_cost is not None else trade.expected_cost
            trade.markout_1s = result.markout_1s if result.markout_1s is not None else trade.markout_1s
            trade.markout_5s = result.markout_5s if result.markout_5s is not None else trade.markout_5s
            trade.markout_30s = result.markout_30s if result.markout_30s is not None else trade.markout_30s

        self.balance -= result.fill_size
        if is_new:
            from logger import log_trade

            log_trade(trade)
        else:
            save_trades(self.trades)
        log_trade_jsonl(trade, result, executor_type=executor_type, snapshot_event="fill")
        return trade

    def _create_open_order(self, signal: Signal, result) -> OpenOrder:
        now = datetime.now(timezone.utc)
        token_id = result.token_id or market_side_token_id(signal.market, signal.side)
        if result.order_id and token_id:
            self._order_token_ids[result.order_id] = token_id
        return OpenOrder(
            order_id=result.order_id,
            created_at=now,
            updated_at=now,
            market_slug=signal.market.slug,
            question=signal.market.question,
            condition_id=signal.market.condition_id,
            token_id=token_id,
            strategy=signal.strategy,
            side=signal.side,
            confidence=signal.confidence,
            reason=signal.reason,
            end_date=signal.market.end_date,
            market_type=self._market_type_from_slug(signal.market.slug),
            strategy_version=STRATEGY_VERSION,
            executor_type=type(self.executor).__name__,
            limit_price=result.fill_price,
            requested_size=result.requested_size or result.reserved_size,
            requested_shares=result.requested_shares,
            reserved_size=result.remaining_size or result.reserved_size,
            status=result.status,
            raw_status=result.raw_status or result.status,
            edge_gross=signal.edge_gross,
            edge_net=signal.edge_net,
            reference_symbol=signal.reference_symbol,
            reference_price=signal.reference_price,
            best_bid=result.best_bid if result.best_bid is not None else signal.best_bid,
            best_ask=result.best_ask if result.best_ask is not None else signal.best_ask,
            spread=result.spread if result.spread is not None else signal.spread,
            decision_latency_ms=signal.decision_latency_ms,
            thesis_id=signal.thesis_id,
            cancel_reason=result.cancel_reason,
            strategy_mode=signal.strategy_mode,
            coin=signal.coin,
            model_up_probability=signal.model_up_probability,
            selected_side_probability=signal.selected_side_probability,
            interval_open=signal.interval_open,
            interval_high=signal.interval_high,
            interval_low=signal.interval_low,
            interval_close=signal.interval_close,
            interval_return=signal.interval_return,
            late_return_60s=signal.late_return_60s,
            late_return_20s=signal.late_return_20s,
            body_ratio=signal.body_ratio,
            wick_imbalance=signal.wick_imbalance,
            candle_regime=signal.candle_regime,
            trend_alignment=signal.trend_alignment,
            market_yes_at_open=signal.market_yes_at_open,
            market_yes_at_decision=signal.market_yes_at_decision,
            market_yes_at_close=signal.market_yes_at_close,
            contrarian_block_reason=signal.contrarian_block_reason,
            wallet_signal_source=signal.wallet_signal_source,
            wallet_lead_score=signal.wallet_lead_score,
            wallet_cluster=signal.wallet_cluster,
            window_start_ts=signal.window_start_ts,
            window_open_price=signal.window_open_price,
            window_open_source=signal.window_open_source,
            window_open_price_trusted=signal.window_open_price_trusted,
            window_open_anchor_age_seconds=signal.window_open_anchor_age_seconds,
            actual_window_return=signal.actual_window_return,
            actual_move_regime=signal.actual_move_regime,
            actual_move_side=signal.actual_move_side,
            strategy_route=signal.strategy_route,
            cluster_id=signal.cluster_id,
            signal_epoch_id=signal.signal_epoch_id,
            book_age_ms=result.book_age_ms if result.book_age_ms is not None else signal.book_age_ms,
            tick_size=result.tick_size if result.tick_size is not None else signal.tick_size,
            expected_fill_price=(
                result.expected_fill_price
                if result.expected_fill_price is not None
                else signal.expected_fill_price
            ),
            expected_cost=result.expected_cost if result.expected_cost is not None else signal.expected_cost,
            markout_1s=result.markout_1s if result.markout_1s is not None else signal.markout_1s,
            markout_5s=result.markout_5s if result.markout_5s is not None else signal.markout_5s,
            markout_30s=result.markout_30s if result.markout_30s is not None else signal.markout_30s,
        )

    def execute_paper_trade(self, signal: Signal) -> Trade | None:
        """Execute a trade through the configured executor.

        Named execute_paper_trade for backwards compatibility, but routes
        through self.executor (Paper, Simulation, or Live).
        """
        self._last_execution_reason = ""
        entry_price = self._entry_price_for_signal(signal)
        size = self._position_size_for_signal(signal)
        result = self.executor.place_order(signal, size, entry_price)
        self.risk_manager.record_execution_quality(
            coin=signal.coin,
            cluster_id=signal.cluster_id,
            slippage=result.slippage,
            expected_cost=signal.expected_cost,
        )

        if result.fill_size > 0:
            trade = self._record_trade_fill(
                market_slug=signal.market.slug,
                question=signal.market.question,
                condition_id=signal.market.condition_id,
                strategy=signal.strategy,
                side=signal.side,
                confidence=signal.confidence,
                reason=signal.reason,
                end_date=signal.market.end_date,
                market_type=self._market_type_from_slug(signal.market.slug),
                executor_type=type(self.executor).__name__,
                order_id=result.order_id,
                result=result,
            )
        else:
            trade = None

        if result.needs_reconciliation:
            open_order = self._create_open_order(signal, result)
            self.open_orders = [o for o in self.open_orders if o.order_id != open_order.order_id]
            self.open_orders.append(open_order)
            save_open_orders(self.open_orders)
            log_order_event(
                "submit",
                open_order.order_id,
                {
                    "market_slug": open_order.market_slug,
                    "side": open_order.side,
                    "status": open_order.status,
                    "raw_status": open_order.raw_status,
                    "requested_size": open_order.requested_size,
                    "reserved_size": open_order.reserved_size,
                },
            )
            reconciled = self._reconcile_open_orders(order_ids={open_order.order_id})
            if reconciled:
                return reconciled[-1]
            if trade is None and open_order.status in {"cancelled", "rejected"}:
                self._last_execution_reason = (
                    open_order.cancel_reason
                    or open_order.status
                )
            return trade

        if not result.filled:
            self._last_execution_reason = result.reason or result.status
            self._log(f"  Order rejected: {result.reason}")
            log_order_event(
                "reject",
                result.order_id,
                {
                    "market_slug": signal.market.slug,
                    "side": signal.side,
                    "status": result.status,
                    "reason": result.reason,
                },
            )
            return None

        return trade

    def _reconcile_open_orders(
        self,
        *,
        order_ids: set[str] | None = None,
        max_orders: int | None = None,
    ) -> list[Trade]:
        with self._execution_lock:
            if not self.open_orders:
                return []

            reconciled_trades: list[Trade] = []
            changed = False
            count = 0

            for open_order in list(self.open_orders):
                if order_ids is not None and open_order.order_id not in order_ids:
                    continue
                if max_orders is not None and count >= max_orders:
                    break
                count += 1

                result = self.executor.reconcile_order(open_order)
                if result is None:
                    continue
                self.risk_manager.record_execution_quality(
                    coin=open_order.coin,
                    cluster_id=open_order.cluster_id,
                    slippage=result.slippage,
                    expected_cost=open_order.expected_cost,
                    feed_stale="stale" in (result.reason or "").lower(),
                    liquidity_collapse="liquidity" in (result.reason or "").lower(),
                )

                previous_status = open_order.status
                previous_raw_status = open_order.raw_status
                previous_reserved = open_order.reserved_size

                trade = None
                if result.fill_size > 0:
                    trade = self._record_trade_fill(
                        market_slug=open_order.market_slug,
                        question=open_order.question,
                        condition_id=open_order.condition_id,
                        strategy=open_order.strategy,
                        side=open_order.side,
                        confidence=open_order.confidence,
                        reason=open_order.reason,
                        end_date=open_order.end_date,
                        market_type=open_order.market_type,
                        executor_type=open_order.executor_type,
                        order_id=open_order.order_id,
                        result=result,
                    )
                    if trade:
                        reconciled_trades.append(trade)

                open_order.confirmed_fill_size += result.fill_size
                open_order.confirmed_fill_shares += result.fill_shares
                open_order.confirmed_fees += result.fees
                open_order.reserved_size = result.remaining_size
                open_order.status = result.status
                open_order.raw_status = result.raw_status or result.status
                open_order.cancel_reason = result.cancel_reason or open_order.cancel_reason
                open_order.updated_at = datetime.now(timezone.utc)

                material_change = (
                    result.fill_size > 0
                    or result.terminal
                    or previous_status != open_order.status
                    or previous_raw_status != open_order.raw_status
                    or abs(previous_reserved - open_order.reserved_size) > 1e-9
                )
                if material_change:
                    changed = True
                    if result.status == "cancelled":
                        log_order_event(
                            "cancel",
                            open_order.order_id,
                            {
                                "market_slug": open_order.market_slug,
                                "side": open_order.side,
                                "status": open_order.status,
                                "reason": result.reason,
                            },
                        )
                    log_order_event(
                        "reconcile",
                        open_order.order_id,
                        {
                            "market_slug": open_order.market_slug,
                            "side": open_order.side,
                            "status": open_order.status,
                            "raw_status": open_order.raw_status,
                            "fill_size": result.fill_size,
                            "fill_shares": result.fill_shares,
                            "remaining_size": open_order.reserved_size,
                            "terminal": result.terminal,
                            "reason": result.reason,
                        },
                    )

                if result.terminal or result.remaining_size <= 1e-9:
                    self.open_orders.remove(open_order)
                    changed = True

            if changed:
                save_open_orders(self.open_orders)

            return reconciled_trades

    def process_signal(self, signal: Signal, *, source: str = "updown") -> tuple[Trade | None, str, str]:
        with self._execution_lock:
            if source != "updown":
                self._log(
                    f"  External signal ({source}): {signal.side} on {signal.market.slug}"
                )
            return self._try_execute(signal)

    def _try_execute(self, signal: Signal) -> tuple[Trade | None, str, str]:
        signal_key = self._signal_key(signal)
        if signal.strategy_mode == STRATEGY_MODE_DISABLED:
            return None, "analysis_skip", "strategy disabled"
        if not _shadow_signal_allowed(signal):
            return None, "shadow_only", "shadow-only strategy"
        if signal_key and signal_key in self.executed_signal_keys:
            self._log(f"  Skip (already traded): {signal_key}")
            self._clear_retry_watch(signal.market.slug)
            return None, "already_traded_skip", "already traded"
        if signal.market.slug in self.active_order_markets:
            self._log(f"  Skip (order already live): {signal.market.slug}")
            self._clear_retry_watch(signal.market.slug)
            return None, "active_order_skip", "order already live"
        signal_token_id = market_side_token_id(signal.market, signal.side)
        if signal_token_id and signal_token_id in self._clob_open_token_ids:
            self._log(f"  Skip (CLOB open order for token {signal_token_id[:10]}... not in CSV — crash guard)")
            return None, "active_order_skip", "clob open order (crash recovery guard)"
        entry_price = self._entry_price_for_signal(signal)
        if signal.strategy == "arbitrage" and not APP_CONFIG.strategies.news.enabled:
            self._log("  Skip (news arbitrage disabled)")
            return None, "analysis_skip", "news arbitrage disabled"
        if signal.strategy == "updown":
            min_entry = APP_CONFIG.strategies.updown.min_entry_price
            max_entry = APP_CONFIG.strategies.updown.max_entry_price
            if entry_price < min_entry:
                self._log(f"  Skip (entry {entry_price:.2f} < min {min_entry:.2f})")
                return None, "analysis_skip", f"entry {entry_price:.2f} < min {min_entry:.2f}"
            if entry_price > max_entry:
                self._log(f"  Skip (entry {entry_price:.2f} > max {max_entry:.2f})")
                return None, "analysis_skip", f"entry {entry_price:.2f} > max {max_entry:.2f}"
        size = self._position_size_for_signal(signal)
        if self.available_balance < size:
            self._log(f"  Skip (available ${self.available_balance:.2f} < target ${size:.2f})")
            return None, "balance_skip", f"available ${self.available_balance:.2f} < target ${size:.2f}"
        risk_check = self.risk_manager.check_trade_allowed(
            signal,
            size,
            self.pending_trades,
            open_orders=self.open_orders,
            account_equity=self.account_equity,
        )
        if not risk_check.allowed:
            self._log(f"  Risk blocked: {risk_check.reason}")
            log_risk_block(signal.market.slug, risk_check.reason)
            return None, "risk_blocked", risk_check.reason

        trade = self.execute_paper_trade(signal)
        if trade:
            self._clear_retry_watch(signal.market.slug)
            return trade, "traded", f"filled @ ${trade.entry_price:.2f}"
        if signal.market.slug in self.active_order_markets:
            self._clear_retry_watch(signal.market.slug)
            return None, "order_live", "submitted and awaiting reconciliation"
        return (
            None,
            "order_rejected",
            self._last_execution_reason or "executor rejected or produced no fill",
        )

    def settle_trades(self, max_checks: int = 3):
        """Settle pending trades whose markets have been resolved on Polymarket."""
        now = datetime.now(timezone.utc)
        settled = False
        api_calls = 0

        for trade in self.trades:
            if trade.status != "pending":
                continue
            if trade.end_date is not None and (now - trade.end_date).total_seconds() < 10:
                continue

            if api_calls >= max_checks:
                break
            api_calls += 1

            resolved = fetch_resolved_market(trade.market_slug)
            if resolved is None:
                if trade.end_date and (now - trade.end_date).total_seconds() > 600:
                    self._log(f"PENDING (still unresolved after 10m): {trade.market_slug}")
                continue

            winning_side = _winning_side_from_resolution(resolved)
            if winning_side not in {"YES", "NO"}:
                continue

            if trade.side == winning_side:
                trade.payout = (trade.size / trade.entry_price) - trade.fees
                trade.status = "won"
                if TRADING_MODE == "live" and trade.condition_id:
                    trade.redemption_status = "pending"
                    trade.redemption_tx_id = ""
                    trade.redemption_tx_hash = ""
                    trade.redemption_error = ""
                    trade.redemption_updated_at = now
                self.balance += trade.payout
                self.wins += 1
                self._log(f"WIN: {trade.market_slug} +${trade.payout - trade.size:.2f}")
            else:
                trade.payout = 0.0
                trade.status = "lost"
                self.losses += 1
                self._log(f"LOSS: {trade.market_slug} -${trade.size:.2f}")

            trade.market_yes_at_close = 1.0 if winning_side == "YES" else 0.0

            self.risk_manager.record_trade_result(trade)
            log_settlement(trade)
            log_trade_jsonl(
                trade,
                executor_type=trade.executor_type or type(self.executor).__name__,
                snapshot_event="settlement",
            )
            settled = True

        if settled:
            save_trades(self.trades)

    def check_updown_markets(self) -> list[UpdownAnalysis]:
        analyses = []
        mode = getattr(self, "mode_15m", None)
        extra_edge = mode.edge_boost if mode and mode.tightened else 0.0
        extra_conf = mode.confidence_boost if mode and mode.tightened else 0.0
        self._prune_retry_watches(self.updown_markets_found)
        for udm in self.updown_markets_found:
            edge_boost = extra_edge if udm.interval_minutes == 15 else 0.0
            conf_boost = extra_conf if udm.interval_minutes == 15 else 0.0
            retry_context = self._retry_watches.get(udm.market.slug)
            analysis = analyze_updown_market_detail(
                udm,
                extra_min_edge=edge_boost,
                retry_context=retry_context,
            )
            self._update_retry_watch(analysis)
            if analysis.signal and conf_boost > 0 and analysis.confidence < conf_boost:
                analysis.reason = (
                    f"{udm.coin} skip: confidence {analysis.confidence:.0%} "
                    f"< tightened min {conf_boost:.0%}"
                )
                analysis.decision_stage = "tightened_skip"
                analysis.signal = None
            if analysis.signal is None:
                self._log(f"  {analysis.reason}")
            analyses.append(analysis)
        analyses.sort(key=lambda item: (0 if item.signal else 1, -item.confidence, item.seconds_to_close))
        return analyses

    def check_arbitrage(self) -> list[Signal]:
        """Offline research hook retained for compatibility; never executes live."""
        return []

    def _start_background_price_warm(self, coins: set[str]):
        if not coins:
            return
        if self._cache_warm_future and not self._cache_warm_future.done():
            return
        self._cache_warm_future = self._background_executor.submit(self._warm_active_coins, set(coins))

    def _consume_background_price_warm(self):
        if not self._cache_warm_future or not self._cache_warm_future.done():
            return
        try:
            self._cache_warm_future.result()
        except Exception:
            pass
        finally:
            self._cache_warm_future = None

    def _warm_active_coins(self, coins: set[str]):
        """Warm price cache for active coins using a single batch API call."""
        if not coins:
            return
        reference_max_age = active_reference_max_age_seconds()
        if ENABLE_REALTIME_DATA_PLANE:
            stale_or_missing = False
            for coin in coins:
                if self.runtime_data_plane.reference_cache.price(coin) is None:
                    stale_or_missing = True
                    break
                age = self.runtime_data_plane.reference_cache.age_seconds(coin)
                if age is None or age > reference_max_age:
                    stale_or_missing = True
                    break
            if not stale_or_missing:
                return
        get_prices_batch(coins)
        for coin in coins:
            ensure_reference_recent(coin, max_age=reference_max_age)

    def _markout_midpoint(self, order_id: str) -> float | None:
        token_id = self._order_token_ids.get(order_id)
        if not token_id:
            return None
        snapshot = self.runtime_data_plane.market_cache.snapshot(token_id)
        if not snapshot:
            return None
        midpoint = snapshot.get("midpoint")
        if midpoint is not None:
            return float(midpoint)
        best_bid = snapshot.get("best_bid")
        best_ask = snapshot.get("best_ask")
        if best_bid is not None and best_ask is not None:
            return (float(best_bid) + float(best_ask)) / 2.0
        return None

    def _update_trade_markouts(self) -> None:
        if not self.trades:
            return

        now = datetime.now(timezone.utc)
        changed = False
        for trade in self.trades:
            if trade.status != "pending" or not trade.order_id:
                continue
            midpoint = self._markout_midpoint(trade.order_id)
            if midpoint is None:
                continue
            baseline = (
                trade.expected_fill_price
                if trade.expected_fill_price is not None
                else trade.fill_price
                if trade.fill_price is not None
                else trade.entry_price
            )
            if baseline <= 0:
                continue
            elapsed = (now - trade.timestamp).total_seconds()
            markout = midpoint - baseline
            if trade.markout_1s is None and elapsed >= 1.0:
                trade.markout_1s = markout
                changed = True
            if trade.markout_5s is None and elapsed >= 5.0:
                trade.markout_5s = markout
                self.risk_manager.record_execution_quality(
                    coin=(trade.reference_symbol or "").upper(),
                    cluster_id=trade.cluster_id,
                    markout_5s=markout,
                    expected_cost=trade.expected_cost,
                )
                changed = True
            if trade.markout_30s is None and elapsed >= 30.0:
                trade.markout_30s = markout
                changed = True

        if changed:
            save_trades(self.trades)

    def tick(self) -> list[Trade]:
        tick_start = time.time()
        new_trades = []
        updown_analyses: list[UpdownAnalysis] = []
        self.tick_count += 1
        self.risk_manager.on_cycle_start()
        self._consume_background_price_warm()

        try:
            self.status = "Fetching markets"
            self._refresh_markets()
        except Exception as e:
            self._log(f"Market fetch error: {e}")
            self.status = "Market fetch error"
            return new_trades

        reconciled = self._reconcile_open_orders()
        if reconciled:
            new_trades.extend(reconciled)
            self._log(f"Reconciled {len(reconciled)} confirmed fill(s)")

        self.status = "Checking updown markets"
        try:
            all_updown = find_updown_markets(self.markets)
            mode_15m = evaluate_15m_mode(self.trades)
            self.mode_15m = mode_15m
            self.updown_markets_found = all_updown
            self._update_runtime_subscriptions()
            udm_5m = [u for u in self.updown_markets_found if u.interval_minutes == 5]
            udm_15m = [u for u in self.updown_markets_found if u.interval_minutes == 15]
            self._log(
                f"Found {len(udm_5m)} 5m + {len(udm_15m)} 15m updown markets | {mode_15m.reason}"
            )

            active_coins = {udm.coin for udm in self.updown_markets_found}
            if active_coins:
                t0 = time.time()
                self._warm_active_coins(active_coins)
                warm_ms = (time.time() - t0) * 1000
                if warm_ms > 2000:
                    self._log(
                        f"  Price warming slow: {warm_ms:.0f}ms for {len(active_coins)} coins"
                    )

            updown_analyses = self.check_updown_markets()
            signal_analyses = [analysis for analysis in updown_analyses if analysis.signal]
            self._log(f"UpDown signals: {len(signal_analyses)}")
            cycle_bets = 0
            cycle_limit = SIMULATION_MAX_BETS_PER_CYCLE if TRADING_MODE == "simulation" else MAX_BETS_PER_CYCLE
            for analysis in signal_analyses:
                signal = analysis.signal
                if signal is None:
                    continue
                self._log(
                    f"  Signal: {signal.side} on {signal.market.slug} "
                    f"({signal.confidence:.0%}, mode={signal.strategy_mode})"
                )
                if cycle_bets >= cycle_limit:
                    self._log(f"  Skipped (max {cycle_limit} bets/cycle)")
                    analysis.decision_stage = "cycle_limit_skip"
                    analysis.reason = f"{analysis.reason} | max {cycle_limit} bets/cycle reached"
                    continue
                trade, decision_stage, decision_reason = self._try_execute(signal)
                analysis.decision_stage = decision_stage
                if decision_stage != "traded":
                    analysis.reason = f"{analysis.reason} | {decision_reason}"
                if trade:
                    self._log(
                        f"  TRADE: {trade.side} {trade.market_slug} @ ${trade.entry_price:.2f}, ${trade.size:.2f}"
                    )
                    new_trades.append(trade)
                if decision_stage in {"traded", "order_live"}:
                    cycle_bets += 1
        except Exception as e:
            self._log(f"UpDown check error: {e}")
            self.status = "UpDown check error"
        finally:
            self._set_monitor_signals(updown_analyses)
            self._emit_signal_events(updown_analyses)

        self._update_trade_markouts()
        self.settle_trades()
        self.settle_shadow_signals()
        self._process_redemptions()
        self._log("LLM/news trading disabled; arbitrage remains research-only")

        remaining = set(SUPPORTED_COINS.keys()) - {udm.coin for udm in self.updown_markets_found}
        self._start_background_price_warm(remaining)

        tick_ms = (time.time() - tick_start) * 1000
        if tick_ms > 5000:
            self._log(f"SLOW TICK: {tick_ms:.0f}ms")
        self.status = "Idle"
        return new_trades

    def _adaptive_interval(self) -> float:
        """Shorter tick interval when markets are approaching expiry."""
        if any(udm.seconds_to_close <= 30 for udm in self.updown_markets_found):
            return 5.0
        return TICK_INTERVAL

    def run(self, interval: float = TICK_INTERVAL):
        self.start_runtime_services()
        self.running = True
        while self.running:
            t0 = time.time()
            self.tick()
            elapsed = time.time() - t0
            sleep_time = max(0, self._adaptive_interval() - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def stop(self):
        self.running = False
        self.stop_runtime_services()
        self._background_executor.shutdown(wait=False, cancel_futures=True)
