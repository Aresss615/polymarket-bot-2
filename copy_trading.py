from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from threading import Event, Lock, Thread
import time

import requests

from analytics import session_summary_payload
from config import APP_CONFIG, Market, RunSession, Signal, Trade, STRATEGY_MODE_LIVE, STRATEGY_VERSION
from logger import log_trade, save_trades
from market_data import ClobMarketDataClient, MarketMetadataCache
from order_executor import OrderExecutor, PaperExecutor
from risk_manager import RiskManager, RiskConfig
from trade_logger import log_risk_block, log_session_summary, log_trade_jsonl


def _normalize_trade_timestamp(raw) -> datetime:
    ts = float(raw or 0)
    if ts > 1e12:
        ts /= 1000.0
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _safe_float(raw, default: float = 0.0) -> float:
    try:
        if raw in (None, ""):
            return default
        return float(raw)
    except (TypeError, ValueError):
        return default


def _copy_key(activity: dict) -> str:
    return ":".join(
        [
            str(activity.get("transactionHash", "")),
            str(activity.get("outcome", "")),
            str(activity.get("price", "")),
            str(activity.get("size", "")),
            str(activity.get("timestamp", "")),
        ]
    )


def _trade_side_from_outcome(activity: dict, market: Market) -> str:
    outcome = str(activity.get("outcome", "")).strip().upper()
    if outcome in {"YES", "UP"}:
        return "YES"
    if outcome in {"NO", "DOWN"}:
        return "NO"
    if market.outcomes:
        first = str(market.outcomes[0]).strip().upper()
        return "YES" if first == outcome else "NO"
    return "YES"


def _signal_side_from_activity(activity: dict, market: Market) -> str:
    base_side = _trade_side_from_outcome(activity, market)
    activity_side = str(activity.get("side", "")).strip().upper()
    if activity_side == "SELL":
        return "NO" if base_side == "YES" else "YES"
    return base_side


def _market_price_for_side(market: Market, side: str, fallback: float = 0.0) -> float:
    price_idx = 0 if side == "YES" else 1
    if len(market.outcome_prices) > price_idx:
        return _safe_float(market.outcome_prices[price_idx], fallback)
    return fallback


def _token_id_for_side(market: Market, side: str, activity: dict) -> str:
    raw_asset = str(activity.get("asset", "")).strip()
    if raw_asset:
        return raw_asset
    token_idx = 0 if side == "YES" else 1
    if len(market.token_ids) > token_idx:
        return str(market.token_ids[token_idx])
    return ""


def _compute_copy_order_shares(target_shares: float) -> tuple[float, str]:
    if target_shares <= 0:
        return 0.0, "target trade size missing or invalid"

    scaled = target_shares * (APP_CONFIG.copy_trading.size_percent / 100.0)
    scaled = max(APP_CONFIG.copy_trading.min_copy_size, scaled)
    scaled = min(APP_CONFIG.copy_trading.max_copy_size, scaled)
    scaled = round(scaled, 6)
    if scaled <= 0:
        return 0.0, "computed copy size is zero after percent/min/max"
    return scaled, ""


@dataclass(frozen=True)
class CopyTradeCandidate:
    key: str
    timestamp: datetime
    market: Market
    side: str
    target_wallet: str
    target_transaction_hash: str
    target_trade_shares: float
    target_trade_price: float
    copy_shares: float
    copy_notional: float
    token_id: str = ""
    activity_side: str = ""
    outcome: str = ""
    title: str = ""

    def to_signal(self) -> Signal:
        return Signal(
            market=self.market,
            strategy="copy_trade",
            side=self.side,
            confidence=0.92,
            reason=(
                f"Copy-trading {self.target_wallet}: {self.side} {self.market.slug} "
                f"from {self.target_transaction_hash or 'activity'}"
            ),
            strategy_mode=STRATEGY_MODE_LIVE,
            market_type="copy",
            coin="",
            wallet_signal_source=self.target_wallet,
            wallet_lead_score=self.target_trade_shares,
            wallet_cluster=self.target_wallet[-8:] if self.target_wallet else "",
            cluster_id="wallet_copy",
            signal_epoch_id=self.key,
            requested_size_override=self.copy_notional,
            bucket="wallet_copy",
            expected_value=0.0,
        )


class CopyRiskGuard:
    def __init__(
        self,
        *,
        min_target_shares: float,
        large_trade_shares: float,
        consecutive_trigger: int,
        min_depth_usd: float,
        trip_seconds: int,
        sequence_window_seconds: int = 30,
    ):
        self.min_target_shares = max(min_target_shares, 0.0)
        self.large_trade_shares = max(large_trade_shares, 0.0)
        self.consecutive_trigger = max(int(consecutive_trigger), 1)
        self.min_depth_usd = max(min_depth_usd, 0.0)
        self.trip_seconds = max(int(trip_seconds), 0)
        self.sequence_window_seconds = max(int(sequence_window_seconds), 1)
        self._large_trade_sequences: dict[str, deque[float]] = {}
        self._tripped_until: dict[str, float] = {}

    def evaluate(self, candidate: CopyTradeCandidate, book_snapshot) -> tuple[bool, str]:
        token_key = candidate.token_id or candidate.market.slug
        now = time.time()

        if candidate.target_trade_shares < self.min_target_shares:
            return (
                False,
                f"target trade {candidate.target_trade_shares:.2f} < min {self.min_target_shares:.2f} shares",
            )

        tripped_until = self._tripped_until.get(token_key)
        if tripped_until is not None and now < tripped_until:
            remaining = max(int(tripped_until - now), 1)
            return False, f"copy guard tripped ({remaining}s remaining)"

        if self.large_trade_shares <= 0 or candidate.target_trade_shares < self.large_trade_shares:
            return True, "ok"

        bucket = self._large_trade_sequences.setdefault(token_key, deque())
        cutoff = now - self.sequence_window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        bucket.append(now)

        if len(bucket) < self.consecutive_trigger:
            return True, f"large-trade sequence {len(bucket)}/{self.consecutive_trigger}"

        if book_snapshot is None:
            self._tripped_until[token_key] = now + self.trip_seconds
            return False, "book unavailable for copy depth check"

        depth_beyond = self._depth_beyond_order(book_snapshot, candidate.copy_notional)
        if depth_beyond < self.min_depth_usd:
            self._tripped_until[token_key] = now + self.trip_seconds
            return False, f"copy trap: depth beyond ${depth_beyond:.2f} < ${self.min_depth_usd:.2f}"
        return True, f"depth beyond ok ${depth_beyond:.2f}"

    @staticmethod
    def _depth_beyond_order(book_snapshot, copy_notional: float) -> float:
        ask_levels = getattr(book_snapshot, "asks", []) or []
        visible_notional = sum(level.price * level.size for level in ask_levels[:10])
        return max(visible_notional - copy_notional, 0.0)


class CopyTradingService:
    def __init__(
        self,
        target_wallet: str,
        *,
        metadata_cache: MarketMetadataCache | None = None,
        market_data_client: ClobMarketDataClient | None = None,
    ):
        self.target_wallet = target_wallet.strip()
        self.metadata_cache = metadata_cache or MarketMetadataCache()
        self.market_data_client = market_data_client or ClobMarketDataClient()
        self.processed_keys: set[str] = set()
        self.baseline_seeded = False
        self.running = False
        self._events: deque[dict] = deque(maxlen=APP_CONFIG.copy_trading.activity_limit)
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._risk_guard = CopyRiskGuard(
            min_target_shares=APP_CONFIG.copy_trading.min_target_shares,
            large_trade_shares=APP_CONFIG.copy_trading.large_trade_shares,
            consecutive_trigger=APP_CONFIG.copy_trading.consecutive_trigger,
            min_depth_usd=APP_CONFIG.copy_trading.min_depth_usd,
            trip_seconds=APP_CONFIG.copy_trading.trip_seconds,
        )
        self._last_poll_at: float | None = None

    def _push_event(self, kind: str, *, message: str, candidate: CopyTradeCandidate | None = None, decision_stage: str = "") -> None:
        event = {
            "at": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "message": message,
            "decision_stage": decision_stage,
        }
        if candidate is not None:
            event.update(
                {
                    "market_slug": candidate.market.slug,
                    "side": candidate.side,
                    "copy_notional": round(candidate.copy_notional, 6),
                    "copy_shares": round(candidate.copy_shares, 6),
                    "target_trade_shares": round(candidate.target_trade_shares, 6),
                    "target_trade_price": round(candidate.target_trade_price, 6),
                    "target_transaction_hash": candidate.target_transaction_hash,
                }
            )
        with self._lock:
            self._events.appendleft(event)

    def recent_events(self) -> list[dict]:
        with self._lock:
            return list(self._events)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "enabled": True,
                "running": self.running,
                "target_wallet": self.target_wallet,
                "baseline_seeded": self.baseline_seeded,
                "processed_keys": len(self.processed_keys),
                "last_poll_at": self._last_poll_at,
                "recent_events": list(self._events),
            }

    def _fetch_recent_trades(self) -> list[dict]:
        resp = requests.get(
            f"{APP_CONFIG.copy_trading.data_api_url}/activity",
            params={
                "user": self.target_wallet,
                "type": "TRADE",
                "limit": APP_CONFIG.copy_trading.trade_limit,
                "sortDirection": "DESC",
            },
            timeout=10,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not isinstance(rows, list):
            return []
        rows.sort(key=lambda row: float(row.get("timestamp", 0) or 0))
        return rows

    def _candidate_from_activity(self, activity: dict) -> tuple[CopyTradeCandidate | None, str]:
        slug = str(activity.get("slug", "")).strip()
        if not slug:
            return None, "activity missing slug"

        market = self.metadata_cache.resolve(slug)
        if market is None:
            return None, f"unresolved market: {slug}"

        signal_side = _signal_side_from_activity(activity, market)
        price_fallback = _safe_float(activity.get("price"), 0.0)
        signal_price = _market_price_for_side(market, signal_side, fallback=price_fallback)
        if signal_price <= 0:
            return None, f"invalid signal price for {slug}"

        target_trade_shares = _safe_float(activity.get("size"), 0.0)
        copy_shares, skip_reason = _compute_copy_order_shares(target_trade_shares)
        if skip_reason:
            return None, skip_reason

        copy_notional = round(copy_shares * signal_price, 6)
        if copy_notional <= 0:
            return None, "computed copy notional is zero"

        candidate = CopyTradeCandidate(
            key=_copy_key(activity),
            timestamp=_normalize_trade_timestamp(activity.get("timestamp")),
            market=market,
            side=signal_side,
            target_wallet=self.target_wallet,
            target_transaction_hash=str(activity.get("transactionHash", "")),
            target_trade_shares=target_trade_shares,
            target_trade_price=price_fallback,
            copy_shares=copy_shares,
            copy_notional=copy_notional,
            token_id=_token_id_for_side(market, signal_side, activity),
            activity_side=str(activity.get("side", "")).strip().upper(),
            outcome=str(activity.get("outcome", "")),
            title=str(activity.get("title", "")),
        )
        return candidate, ""

    def poll_once(self, signal_handler=None) -> list:
        rows = self._fetch_recent_trades()
        self._last_poll_at = time.time()
        if not self.baseline_seeded:
            for row in rows:
                self.processed_keys.add(_copy_key(row))
            self.baseline_seeded = True
            self._push_event(
                "baseline",
                message=f"Seeded copy baseline with {len(rows)} trades for {self.target_wallet}",
            )
            return []

        results = []
        for row in rows:
            key = _copy_key(row)
            if key in self.processed_keys:
                continue
            self.processed_keys.add(key)

            candidate, reason = self._candidate_from_activity(row)
            if candidate is None:
                self._push_event("skipped", message=reason or "candidate build failed")
                continue

            book_snapshot = None
            if candidate.token_id:
                book_snapshot = self.market_data_client.get_book_snapshot(candidate.token_id)
            allowed, guard_reason = self._risk_guard.evaluate(candidate, book_snapshot)
            if not allowed:
                self._push_event("skipped", message=guard_reason, candidate=candidate, decision_stage="copy_guard_skip")
                continue

            if signal_handler is None:
                results.append(candidate)
                self._push_event("candidate", message=guard_reason, candidate=candidate, decision_stage="candidate_ready")
                continue

            try:
                trade, decision_stage, decision_reason = signal_handler(
                    candidate.to_signal(),
                    source="copy_trading",
                )
            except Exception as exc:  # pragma: no cover - defensive service logging
                self._push_event("error", message=str(exc), candidate=candidate, decision_stage="handler_error")
                continue

            if trade is not None:
                results.append(trade)
            event_kind = "applied" if decision_stage in {"traded", "order_live"} else "skipped"
            self._push_event(
                event_kind,
                message=decision_reason or guard_reason,
                candidate=candidate,
                decision_stage=decision_stage,
            )
        return results

    def run(self, signal_handler, poll_interval_ms: int | None = None) -> None:
        poll_interval = max((poll_interval_ms or APP_CONFIG.copy_trading.poll_interval_ms) / 1000.0, 0.2)
        self.running = True
        self._stop_event.clear()
        try:
            while not self._stop_event.is_set():
                self.poll_once(signal_handler)
                self._stop_event.wait(poll_interval)
        finally:
            self.running = False

    def start(self, signal_handler, poll_interval_ms: int | None = None) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = Thread(
            target=self.run,
            args=(signal_handler, poll_interval_ms),
            daemon=True,
            name="copy-trading-service",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        self.running = False


class CopyTradingBot:
    def __init__(
        self,
        target_wallet: str,
        executor: OrderExecutor | None = None,
        risk_manager: RiskManager | None = None,
        metadata_cache: MarketMetadataCache | None = None,
        market_data_client: ClobMarketDataClient | None = None,
    ):
        self.target_wallet = target_wallet
        self.executor = executor or PaperExecutor()
        self.risk_manager = risk_manager or RiskManager(RiskConfig())
        self.metadata_cache = metadata_cache or MarketMetadataCache()
        self.market_data_client = market_data_client or ClobMarketDataClient()
        self.trades: list[Trade] = []
        self.running = False
        self.activity_log: deque[str] = deque(maxlen=50)
        self.session = RunSession(
            session_id=f"copy-{int(time.time())}",
            started_at=datetime.now(timezone.utc),
            mode="copy-trading",
            strategies={"copy_trading": True},
        )
        self.service = CopyTradingService(
            target_wallet=target_wallet,
            metadata_cache=self.metadata_cache,
            market_data_client=self.market_data_client,
        )

    @property
    def processed_keys(self) -> set[str]:
        return self.service.processed_keys

    @property
    def baseline_seeded(self) -> bool:
        return self.service.baseline_seeded

    def _log(self, message: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.activity_log.append(f"[{ts}] {message}")

    def _process_signal(self, signal: Signal, *, source: str = "copy_trading") -> tuple[Trade | None, str, str]:
        del source
        entry_price = _market_price_for_side(signal.market, signal.side, fallback=0.0)
        size = signal.requested_size_override or 0.0
        risk_check = self.risk_manager.check_trade_allowed(
            signal,
            size,
            [trade for trade in self.trades if trade.status == "pending"],
        )
        if not risk_check.allowed:
            self._log(f"Risk blocked {signal.market.slug}: {risk_check.reason}")
            log_risk_block(signal.market.slug, risk_check.reason, session_id=self.session.session_id)
            return None, "risk_blocked", risk_check.reason

        result = self.executor.place_order(signal, size, entry_price)
        if not result.filled:
            self._log(f"Order rejected {signal.market.slug}: {result.reason}")
            return None, "order_rejected", result.reason

        trade = Trade(
            timestamp=datetime.now(timezone.utc),
            market_slug=signal.market.slug,
            question=signal.market.question,
            strategy="copy_trade",
            side=signal.side,
            entry_price=result.fill_price,
            size=result.fill_size,
            confidence=signal.confidence,
            reason=signal.reason,
            status="pending",
            payout=0.0,
            end_date=signal.market.end_date,
            market_type="copy",
            strategy_version=STRATEGY_VERSION,
            fees=result.fees,
            fill_price=result.fill_price,
            trade_id=result.order_id or signal.signal_epoch_id,
            session_id=self.session.session_id,
            bucket="wallet_copy",
            order_id=result.order_id,
            executor_type=type(self.executor).__name__,
            wallet_signal_source=signal.wallet_signal_source,
            wallet_lead_score=signal.wallet_lead_score,
            wallet_cluster=signal.wallet_cluster,
            cluster_id=signal.cluster_id,
            signal_epoch_id=signal.signal_epoch_id,
        )
        self.trades.append(trade)
        log_trade(trade)
        log_trade_jsonl(trade, result, executor_type=type(self.executor).__name__)
        self._log(f"Copied {signal.side} {signal.market.slug} size ${trade.size:.2f}")
        save_trades(self.trades)
        return trade, "traded", f"filled @ ${trade.entry_price:.2f}"

    def poll_once(self) -> list[Trade]:
        opened = self.service.poll_once(self._process_signal)
        for event in self.service.recent_events()[:3]:
            message = event.get("message")
            market_slug = event.get("market_slug")
            decision_stage = event.get("decision_stage")
            if message:
                prefix = f"{market_slug} " if market_slug else ""
                suffix = f" [{decision_stage}]" if decision_stage else ""
                self._log(f"{prefix}{message}{suffix}".strip())
        return [trade for trade in opened if isinstance(trade, Trade)]

    def finalize_session(self) -> dict:
        summary = session_summary_payload(self.trades)
        log_session_summary(self.session, summary)
        return summary

    def run(self, poll_interval_ms: int | None = None):
        self.running = True
        try:
            self.service.run(self._process_signal, poll_interval_ms=poll_interval_ms)
        finally:
            self.running = False
            self.finalize_session()

    def stop(self):
        self.running = False
        self.service.stop()
