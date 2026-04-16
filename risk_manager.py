"""Risk management for trade gating."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config import (
    CANDIDATE_COINS,
    CLUSTER_SLIPPAGE_BREACH_LIMIT,
    COIN_MARKOUT_BREACH_LIMIT,
    FEED_HEARTBEAT_STALE_SECONDS,
    LIVE_MAKER_MAX_SPREAD,
    MAX_BET,
    MIN_BET,
    OpenOrder,
    RiskConfig,
    SHADOW_ONLY_COINS,
    Signal,
    STRATEGY_MODE_LIVE,
    Trade,
)


@dataclass
class RiskCheck:
    """Result of a risk check."""

    allowed: bool
    reason: str


_COIN_RE = re.compile(r"^([a-z]+)-updown-", re.IGNORECASE)


def _extract_coin(slug: str) -> str | None:
    m = _COIN_RE.match(slug)
    return m.group(1).upper() if m else None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RiskManager:
    def __init__(self, config: RiskConfig | None = None):
        self.config = config or RiskConfig()
        self._daily_losses: float = 0.0
        self._daily_start: datetime = _utc_now()
        self._kill_switch: bool = False
        self._kill_switch_reason: str = ""
        self._peak_equity: float = 0.0
        self._global_consecutive_losses: int = 0
        self._global_cooldown_until: datetime | None = None
        self._coin_consecutive_losses: dict[str, int] = {}
        self._coin_cooldown_until: dict[str, datetime] = {}
        self._coin_markout_breaches: dict[str, int] = {}
        self._cluster_slippage_breaches: dict[str, int] = {}
        self._coin_reduce_only: set[str] = set()
        self._cluster_reduce_only: set[str] = set()

    @staticmethod
    def _trade_timestamp(trade: Trade) -> datetime:
        ts = trade.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)

    @classmethod
    def _trade_date(cls, trade: Trade):
        return cls._trade_timestamp(trade).date()

    def _maybe_reset_daily(self):
        now = _utc_now()
        if now.date() != self._daily_start.date():
            self._daily_losses = 0.0
            self._daily_start = now

    def on_cycle_start(self):
        """Compatibility hook; time-based cooldowns do not need per-cycle decay."""
        self._maybe_reset_daily()

    def _observe_account_equity(self, account_equity: float | None):
        if account_equity is None or account_equity <= 0:
            return
        if account_equity > self._peak_equity:
            self._peak_equity = account_equity

    def observe_account_equity(self, account_equity: float | None):
        self._observe_account_equity(account_equity)

    def recommended_position_size(self, signal: Signal, account_equity: float | None) -> float:
        if account_equity is None or account_equity <= 0:
            raw = MAX_BET
        else:
            raw = account_equity * self.config.target_position_pct * max(signal.size_multiplier, 0.1)
            raw = min(raw, account_equity * self.config.hard_position_cap_pct)
        return max(MIN_BET, min(MAX_BET, raw))

    def _current_coin_cooldown(self, coin: str | None) -> datetime | None:
        if not coin:
            return None
        return self._coin_cooldown_until.get(coin)

    def bootstrap_from_history(
        self,
        trades: list[Trade],
        account_equity: float | None = None,
    ) -> None:
        """Restore daily risk state from persisted trade history."""
        self._maybe_reset_daily()
        self._observe_account_equity(account_equity)

        today = _utc_now().date()
        settled_today = [
            trade
            for trade in trades
            if trade.status in ("won", "lost") and self._trade_date(trade) == today
        ]
        settled_today.sort(key=self._trade_timestamp)

        self._daily_losses = sum(trade.size for trade in settled_today if trade.status == "lost")

        self._global_consecutive_losses = 0
        self._coin_consecutive_losses = {}
        self._global_cooldown_until = None
        self._coin_cooldown_until = {}

        for trade in settled_today:
            self._restore_trade_result(trade)

        limit = None
        if account_equity and account_equity > 0:
            limit = account_equity * self.config.daily_realized_loss_limit_pct
        elif self.config.daily_max_loss > 0:
            limit = self.config.daily_max_loss

        if limit is not None and self._daily_losses >= limit * 2:
            self.activate_kill_switch(f"auto: daily losses ${self._daily_losses:.2f} >= 2x limit")

    def _restore_trade_result(self, trade: Trade):
        coin = _extract_coin(trade.market_slug)
        ts = self._trade_timestamp(trade)
        if trade.status == "lost":
            self._global_consecutive_losses += 1
            if coin:
                self._coin_consecutive_losses[coin] = self._coin_consecutive_losses.get(coin, 0) + 1
                if self._coin_consecutive_losses[coin] >= self.config.per_coin_loss_streak:
                    self._coin_cooldown_until[coin] = ts + timedelta(minutes=self.config.per_coin_cooldown_minutes)
            if self._global_consecutive_losses >= self.config.global_loss_streak:
                self._global_cooldown_until = ts + timedelta(minutes=self.config.global_cooldown_minutes)
        elif trade.status == "won":
            self._global_consecutive_losses = 0
            if coin:
                self._coin_consecutive_losses[coin] = 0

    @staticmethod
    def _open_order_exposure(open_orders: list[OpenOrder] | None) -> float:
        return sum(order.reserved_size for order in (open_orders or []))

    @staticmethod
    def _active_positions_for_coin(
        coin: str,
        pending_trades: list[Trade],
        open_orders: list[OpenOrder] | None,
    ) -> int:
        active = 0
        active += sum(1 for trade in pending_trades if _extract_coin(trade.market_slug) == coin)
        active += sum(1 for order in (open_orders or []) if _extract_coin(order.market_slug) == coin)
        return active

    @staticmethod
    def _active_positions_for_cluster(
        cluster_id: str,
        pending_trades: list[Trade],
        open_orders: list[OpenOrder] | None,
    ) -> tuple[int, float]:
        if not cluster_id:
            return 0, 0.0
        trades = [trade for trade in pending_trades if trade.cluster_id == cluster_id]
        orders = [order for order in (open_orders or []) if order.cluster_id == cluster_id]
        exposure = sum(trade.size for trade in trades) + sum(order.reserved_size for order in orders)
        return len(trades) + len(orders), exposure

    @staticmethod
    def _active_same_side_window_positions(
        signal: Signal,
        pending_trades: list[Trade],
        open_orders: list[OpenOrder] | None,
    ) -> int:
        active = 0
        active += sum(
            1
            for trade in pending_trades
            if _extract_coin(trade.market_slug) == signal.coin
            and trade.side == signal.side
            and trade.market_type == signal.market_type
        )
        active += sum(
            1
            for order in (open_orders or [])
            if _extract_coin(order.market_slug) == signal.coin
            and order.side == signal.side
            and order.market_type == signal.market_type
        )
        return active

    @staticmethod
    def _active_epoch_positions(
        signal_epoch_id: str,
        pending_trades: list[Trade],
        open_orders: list[OpenOrder] | None,
    ) -> int:
        if not signal_epoch_id:
            return 0
        active = 0
        active += sum(1 for trade in pending_trades if trade.signal_epoch_id == signal_epoch_id)
        active += sum(1 for order in (open_orders or []) if order.signal_epoch_id == signal_epoch_id)
        return active

    @staticmethod
    def _thesis_exposure(
        thesis_id: str,
        pending_trades: list[Trade],
        open_orders: list[OpenOrder] | None,
    ) -> tuple[int, float]:
        positions = [trade for trade in pending_trades if trade.thesis_id == thesis_id]
        orders = [order for order in (open_orders or []) if order.thesis_id == thesis_id]
        exposure = sum(trade.size for trade in positions) + sum(order.reserved_size for order in orders)
        return len(positions) + len(orders), exposure

    def check_trade_allowed(
        self,
        signal: Signal,
        size: float,
        pending_trades: list[Trade],
        open_orders: list[OpenOrder] | None = None,
        account_equity: float | None = None,
    ) -> RiskCheck:
        """Check if a trade is allowed by all risk rules."""
        self._maybe_reset_daily()
        self._observe_account_equity(account_equity)

        if self._peak_equity > 0 and account_equity is not None:
            drawdown_pct = max(0.0, (self._peak_equity - account_equity) / self._peak_equity)
            if drawdown_pct >= self.config.max_drawdown_pct:
                self.activate_kill_switch(
                    f"drawdown {drawdown_pct:.0%} >= {self.config.max_drawdown_pct:.0%}"
                )

        if self._kill_switch:
            return RiskCheck(False, f"kill switch active: {self._kill_switch_reason}")

        daily_limit = None
        if account_equity is not None and account_equity > 0:
            daily_limit = account_equity * self.config.daily_realized_loss_limit_pct
        elif self.config.daily_max_loss > 0:
            daily_limit = self.config.daily_max_loss
        if daily_limit is not None and self._daily_losses >= daily_limit:
            return RiskCheck(
                False,
                f"daily loss limit (${self._daily_losses:.2f} >= ${daily_limit:.2f})",
            )

        now = _utc_now()
        if self._global_cooldown_until and now < self._global_cooldown_until:
            remaining = int((self._global_cooldown_until - now).total_seconds() // 60) + 1
            return RiskCheck(False, f"global cooldown active ({remaining}m remaining)")

        coin = signal.coin or _extract_coin(signal.market.slug)
        cluster_id = signal.cluster_id

        if signal.strategy == "updown" and signal.strategy_mode == STRATEGY_MODE_LIVE:
            if coin in SHADOW_ONLY_COINS or (coin and coin not in CANDIDATE_COINS):
                return RiskCheck(False, f"{coin} is shadow-only in V13")
            if signal.market_type != "5m":
                return RiskCheck(False, f"{signal.market_type} candidate path disabled in V13")

        if coin and coin in self._coin_reduce_only:
            return RiskCheck(False, f"{coin} reduce-only after execution-quality breach")
        if cluster_id and cluster_id in self._cluster_reduce_only:
            return RiskCheck(False, f"{cluster_id} reduce-only after cluster breach")

        has_market_microstructure = (
            signal.book_age_ms is not None
            or signal.best_bid is not None
            or signal.best_ask is not None
            or signal.spread is not None
        )
        if has_market_microstructure:
            if signal.book_age_ms is not None and signal.book_age_ms > FEED_HEARTBEAT_STALE_SECONDS * 1000.0:
                return RiskCheck(False, f"stale feed ({signal.book_age_ms:.0f}ms)")
            if signal.best_bid is None or signal.best_ask is None:
                return RiskCheck(False, "liquidity collapse: missing best bid/ask")
            if signal.spread is not None and signal.spread > LIVE_MAKER_MAX_SPREAD:
                return RiskCheck(
                    False,
                    f"liquidity collapse: spread {signal.spread:.3f} > {LIVE_MAKER_MAX_SPREAD:.3f}",
                )

        coin_cooldown = self._current_coin_cooldown(coin)
        if coin_cooldown and now < coin_cooldown:
            remaining = int((coin_cooldown - now).total_seconds() // 60) + 1
            return RiskCheck(False, f"{coin} cooldown active ({remaining}m remaining)")

        open_exposure = sum(t.size for t in pending_trades) + self._open_order_exposure(open_orders)
        max_open_exposure = self.config.max_open_exposure
        if account_equity is not None and account_equity > 0:
            max_open_exposure = account_equity * self.config.max_open_exposure_pct
        if open_exposure + size > max_open_exposure:
            return RiskCheck(
                False,
                f"exposure cap (${open_exposure + size:.2f} > ${max_open_exposure:.2f})",
            )

        if coin:
            if self._active_positions_for_coin(coin, pending_trades, open_orders) >= self.config.max_positions_per_coin:
                return RiskCheck(False, f"{coin} position cap ({self.config.max_positions_per_coin})")

            coin_exposure = sum(
                t.size for t in pending_trades if _extract_coin(t.market_slug) == coin
            )
            coin_exposure += sum(
                order.reserved_size
                for order in (open_orders or [])
                if _extract_coin(order.market_slug) == coin
            )
            per_coin_cap = self.config.max_exposure_per_coin
            if account_equity is not None and account_equity > 0:
                per_coin_cap = min(per_coin_cap, account_equity * self.config.hard_position_cap_pct)
            if coin_exposure + size > per_coin_cap:
                return RiskCheck(
                    False,
                    f"{coin} exposure cap (${coin_exposure + size:.2f} > ${per_coin_cap:.2f})",
                )

        if cluster_id:
            cluster_positions, cluster_exposure = self._active_positions_for_cluster(
                cluster_id,
                pending_trades,
                open_orders,
            )
            if cluster_positions >= self.config.max_positions_per_cluster:
                return RiskCheck(
                    False,
                    f"{cluster_id} cluster position cap ({cluster_positions} >= {self.config.max_positions_per_cluster})",
                )
            cluster_cap = self.config.max_open_exposure
            if account_equity is not None and account_equity > 0:
                cluster_cap = account_equity * self.config.max_cluster_exposure_pct
            if cluster_exposure + size > cluster_cap:
                return RiskCheck(
                    False,
                    f"{cluster_id} cluster exposure cap (${cluster_exposure + size:.2f} > ${cluster_cap:.2f})",
                )

        if signal.strategy == "updown" and signal.strategy_mode == STRATEGY_MODE_LIVE:
            if self._active_same_side_window_positions(signal, pending_trades, open_orders) > 0:
                return RiskCheck(False, f"{coin} no re-entry for same side/window")
            if self._active_epoch_positions(signal.signal_epoch_id, pending_trades, open_orders) > 0:
                return RiskCheck(False, f"{coin} signal epoch already active")

        thesis_id = signal.thesis_id
        if thesis_id:
            thesis_positions, thesis_exposure = self._thesis_exposure(thesis_id, pending_trades, open_orders)
            if thesis_positions >= self.config.max_positions_per_thesis:
                return RiskCheck(
                    False,
                    f"thesis position cap ({thesis_positions} >= {self.config.max_positions_per_thesis})",
                )
            thesis_cap = self.config.max_open_exposure
            if account_equity is not None and account_equity > 0:
                thesis_cap = account_equity * self.config.max_thesis_exposure_pct
            if thesis_exposure + size > thesis_cap:
                return RiskCheck(
                    False,
                    f"thesis exposure cap (${thesis_exposure + size:.2f} > ${thesis_cap:.2f})",
                )

        return RiskCheck(True, "ok")

    def record_trade_result(self, trade: Trade):
        """Update risk state after a trade settles."""
        self._maybe_reset_daily()
        coin = _extract_coin(trade.market_slug)
        now = self._trade_timestamp(trade)

        if trade.status == "lost":
            self._daily_losses += trade.size
            self._global_consecutive_losses += 1
            if coin:
                new_streak = self._coin_consecutive_losses.get(coin, 0) + 1
                self._coin_consecutive_losses[coin] = new_streak
                if new_streak >= self.config.per_coin_loss_streak:
                    self._coin_cooldown_until[coin] = now + timedelta(
                        minutes=self.config.per_coin_cooldown_minutes
                    )
            if self._global_consecutive_losses >= self.config.global_loss_streak:
                self._global_cooldown_until = now + timedelta(
                    minutes=self.config.global_cooldown_minutes
                )

            daily_limit = self.config.daily_max_loss
            if self._peak_equity > 0:
                daily_limit = self._peak_equity * self.config.daily_realized_loss_limit_pct
            if self._daily_losses >= daily_limit * 2:
                self.activate_kill_switch(
                    f"auto: daily losses ${self._daily_losses:.2f} >= 2x limit"
                )
        elif trade.status == "won":
            self._global_consecutive_losses = 0
            if coin:
                self._coin_consecutive_losses[coin] = 0

    def activate_kill_switch(self, reason: str):
        self._kill_switch = True
        self._kill_switch_reason = reason

    def record_execution_quality(
        self,
        *,
        coin: str | None,
        cluster_id: str | None,
        slippage: float | None = None,
        expected_cost: float | None = None,
        markout_5s: float | None = None,
        feed_stale: bool = False,
        liquidity_collapse: bool = False,
    ) -> None:
        normalized_coin = (coin or "").upper()
        normalized_cluster = cluster_id or ""

        if normalized_cluster and slippage is not None and expected_cost not in (None, 0.0):
            if slippage > abs(expected_cost):
                breaches = self._cluster_slippage_breaches.get(normalized_cluster, 0) + 1
                self._cluster_slippage_breaches[normalized_cluster] = breaches
                if breaches >= CLUSTER_SLIPPAGE_BREACH_LIMIT:
                    self._cluster_reduce_only.add(normalized_cluster)

        if normalized_coin and markout_5s is not None and expected_cost not in (None, 0.0):
            if markout_5s < -abs(expected_cost):
                breaches = self._coin_markout_breaches.get(normalized_coin, 0) + 1
                self._coin_markout_breaches[normalized_coin] = breaches
                if breaches >= COIN_MARKOUT_BREACH_LIMIT:
                    self._coin_reduce_only.add(normalized_coin)

        if feed_stale and normalized_cluster:
            self._cluster_reduce_only.add(normalized_cluster)
        if liquidity_collapse:
            if normalized_cluster:
                self._cluster_reduce_only.add(normalized_cluster)
            if normalized_coin:
                self._coin_reduce_only.add(normalized_coin)

    def deactivate_kill_switch(self):
        self._kill_switch = False
        self._kill_switch_reason = ""

    @property
    def daily_pnl(self) -> float:
        self._maybe_reset_daily()
        return -self._daily_losses

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch

    @property
    def consecutive_losses(self) -> int:
        return self._global_consecutive_losses

    @property
    def cooldown_cycles_remaining(self) -> int:
        if not self._global_cooldown_until:
            return 0
        remaining = (self._global_cooldown_until - _utc_now()).total_seconds()
        return max(int(remaining > 0), 0)

    @property
    def peak_equity(self) -> float:
        return self._peak_equity
