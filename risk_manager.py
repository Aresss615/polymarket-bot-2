"""Risk management for trade gating.

Every trade passes through RiskManager.check_trade_allowed() before execution.
Enforces: daily loss limits, exposure caps, consecutive loss cooldown,
per-coin exposure limits, and a global kill switch.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from config import OpenOrder, RiskConfig, Signal, Trade


@dataclass
class RiskCheck:
    """Result of a risk check."""
    allowed: bool
    reason: str


_COIN_RE = re.compile(r"^([a-z]+)-updown-", re.IGNORECASE)


def _extract_coin(slug: str) -> str | None:
    m = _COIN_RE.match(slug)
    return m.group(1).upper() if m else None


class RiskManager:
    def __init__(self, config: RiskConfig | None = None):
        self.config = config or RiskConfig()
        self._daily_losses: float = 0.0
        self._daily_start: datetime = datetime.now(timezone.utc)
        self._consecutive_losses: int = 0
        self._cooldown_cycles_remaining: int = 0
        self._kill_switch: bool = False
        self._kill_switch_reason: str = ""
        self._peak_equity: float = 0.0

    def _maybe_reset_daily(self):
        """Reset daily counters if a new UTC day has started."""
        now = datetime.now(timezone.utc)
        if now.date() != self._daily_start.date():
            self._daily_losses = 0.0
            self._daily_start = now

    def on_cycle_start(self):
        """Advance any finite cooldowns at the top of a new engine cycle."""
        if self._cooldown_cycles_remaining <= 0:
            return

        self._cooldown_cycles_remaining -= 1
        if self._cooldown_cycles_remaining == 0:
            self._consecutive_losses = 0

    def _observe_account_equity(self, account_equity: float | None):
        if account_equity is None or account_equity <= 0:
            return
        if account_equity > self._peak_equity:
            self._peak_equity = account_equity

    def observe_account_equity(self, account_equity: float | None):
        """Record the latest account-equity snapshot for drawdown checks."""
        self._observe_account_equity(account_equity)

    @staticmethod
    def _open_order_exposure(open_orders: list[OpenOrder] | None) -> float:
        return sum(order.reserved_size for order in (open_orders or []))

    def check_trade_allowed(
        self,
        signal: Signal,
        size: float,
        pending_trades: list[Trade],
        open_orders: list[OpenOrder] | None = None,
        account_equity: float | None = None,
    ) -> RiskCheck:
        """Check if a trade is allowed by all risk rules.

        Returns RiskCheck with allowed=False and reason on first failure.
        """
        self._maybe_reset_daily()
        self._observe_account_equity(account_equity)

        if self._peak_equity > 0 and account_equity is not None:
            drawdown_pct = max(0.0, (self._peak_equity - account_equity) / self._peak_equity)
            if drawdown_pct >= self.config.max_drawdown_pct:
                self.activate_kill_switch(
                    f"drawdown {drawdown_pct:.0%} >= {self.config.max_drawdown_pct:.0%}"
                )

        # 1. Kill switch
        if self._kill_switch:
            return RiskCheck(False, f"kill switch active: {self._kill_switch_reason}")

        # 2. Daily loss limit
        if self._daily_losses >= self.config.daily_max_loss:
            return RiskCheck(
                False,
                f"daily loss limit (${self._daily_losses:.2f} >= ${self.config.daily_max_loss:.2f})",
            )

        # 3. Open exposure cap
        open_exposure = sum(t.size for t in pending_trades) + self._open_order_exposure(open_orders)
        if open_exposure + size > self.config.max_open_exposure:
            return RiskCheck(
                False,
                f"exposure cap (${open_exposure + size:.2f} > ${self.config.max_open_exposure:.2f})",
            )

        # 4. Consecutive loss cooldown
        if self._cooldown_cycles_remaining > 0:
            return RiskCheck(
                False,
                f"consecutive loss cooldown ({self._cooldown_cycles_remaining} cycle remaining)",
            )

        # 5. Per-coin exposure limit
        coin = _extract_coin(signal.market.slug)
        if coin:
            coin_exposure = sum(
                t.size for t in pending_trades
                if _extract_coin(t.market_slug) == coin
            )
            coin_exposure += sum(
                order.reserved_size
                for order in (open_orders or [])
                if _extract_coin(order.market_slug) == coin
            )
            if coin_exposure + size > self.config.max_exposure_per_coin:
                return RiskCheck(
                    False,
                    f"{coin} exposure cap (${coin_exposure + size:.2f} > ${self.config.max_exposure_per_coin:.2f})",
                )

        return RiskCheck(True, "ok")

    def record_trade_result(self, trade: Trade):
        """Update risk state after a trade settles."""
        self._maybe_reset_daily()

        if trade.status == "lost":
            self._daily_losses += trade.size
            self._consecutive_losses += 1

            if self._consecutive_losses >= self.config.max_consecutive_losses:
                self._cooldown_cycles_remaining = max(
                    self._cooldown_cycles_remaining,
                    self.config.consecutive_loss_cooldown_cycles,
                )

            # Auto kill switch at 2x daily loss
            if self._daily_losses >= self.config.daily_max_loss * 2:
                self.activate_kill_switch(
                    f"auto: daily losses ${self._daily_losses:.2f} >= 2x limit"
                )
        elif trade.status == "won":
            self._consecutive_losses = 0
            self._cooldown_cycles_remaining = 0

    def activate_kill_switch(self, reason: str):
        self._kill_switch = True
        self._kill_switch_reason = reason

    def deactivate_kill_switch(self):
        self._kill_switch = False
        self._kill_switch_reason = ""

    @property
    def daily_pnl(self) -> float:
        """Negative value representing daily realized losses."""
        self._maybe_reset_daily()
        return -self._daily_losses

    @property
    def open_exposure(self) -> float:
        """Must be called with current pending trades externally."""
        # This is a convenience — actual exposure is computed from trades
        return 0.0

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    @property
    def cooldown_cycles_remaining(self) -> int:
        return self._cooldown_cycles_remaining

    @property
    def peak_equity(self) -> float:
        return self._peak_equity
