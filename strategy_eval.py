"""Patch-scoped strategy evaluation.

All analytics are strictly scoped to the current STRATEGY_VERSION.
No historical leakage from old patches — each version is evaluated independently.
"""

from dataclasses import dataclass

from config import (
    Trade,
    STRATEGY_VERSION,
    MIN_PATCH_TRADES_FOR_EVAL,
    ENABLE_15M_MIN_WIN_RATE,
    ENABLE_15M_MIN_PROFIT_FACTOR,
    ENABLE_15M_MIN_AVG_PNL,
    ADAPTIVE_CONFIDENCE_BOOST,
    ADAPTIVE_EDGE_BOOST,
)


@dataclass
class PatchStats:
    """Performance stats for a single strategy version."""
    version: int
    total_trades: int
    settled_trades: int
    wins: int
    losses: int
    gross_profit: float
    gross_loss: float

    @property
    def win_rate(self) -> float:
        return self.wins / self.settled_trades if self.settled_trades > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        return self.gross_profit / self.gross_loss if self.gross_loss > 0 else float("inf")

    @property
    def net_pnl(self) -> float:
        return self.gross_profit - self.gross_loss

    @property
    def avg_pnl(self) -> float:
        return self.net_pnl / self.settled_trades if self.settled_trades > 0 else 0.0

    @property
    def expectancy(self) -> float:
        """Expected PnL per trade: (WR * avg_win) - ((1-WR) * avg_loss)."""
        if self.settled_trades == 0:
            return 0.0
        avg_win = self.gross_profit / self.wins if self.wins > 0 else 0.0
        avg_loss = self.gross_loss / self.losses if self.losses > 0 else 0.0
        return (self.win_rate * avg_win) - ((1.0 - self.win_rate) * avg_loss)


@dataclass
class Mode15mResult:
    """Decision for 15-minute market trading."""
    enabled: bool
    tightened: bool  # True = enabled but with stricter params
    confidence_boost: float  # extra confidence required (0.0 if not tightened)
    edge_boost: float  # extra edge required (0.0 if not tightened)
    reason: str


def compute_patch_stats(
    trades: list[Trade],
    version: int = STRATEGY_VERSION,
    market_type: str | None = None,
) -> PatchStats:
    """Compute performance stats for trades matching the given version.

    Args:
        trades: All trades (will be filtered by version).
        version: Strategy version to evaluate.
        market_type: Optional filter ("5m" or "15m"). None = all types.
    """
    filtered = [t for t in trades if t.strategy_version == version]
    if market_type is not None:
        filtered = [t for t in filtered if t.market_type == market_type]

    settled = [t for t in filtered if t.status in ("won", "lost")]
    wins = [t for t in settled if t.status == "won"]
    losses = [t for t in settled if t.status == "lost"]

    gross_profit = sum(t.payout - t.size for t in wins)
    gross_loss = sum(t.size for t in losses)  # absolute value of losses

    return PatchStats(
        version=version,
        total_trades=len(filtered),
        settled_trades=len(settled),
        wins=len(wins),
        losses=len(losses),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
    )


def evaluate_15m_mode(trades: list[Trade]) -> Mode15mResult:
    """Decide whether 15-minute markets should be enabled, tightened, or disabled.

    Uses ONLY current patch trades — no historical leakage.

    Decision logic:
    1. Not enough data → enable (give the patch a chance to prove itself)
    2. Strong performance → enable normally
    3. Marginal performance → enable with tightened parameters
    4. Poor performance → disable
    """
    stats = compute_patch_stats(trades, market_type="15m")

    # Not enough data to evaluate — default to enabled so we can gather data
    if stats.settled_trades < MIN_PATCH_TRADES_FOR_EVAL:
        return Mode15mResult(
            enabled=True,
            tightened=False,
            confidence_boost=0.0,
            edge_boost=0.0,
            reason=f"15m enabled (collecting data: {stats.settled_trades}/{MIN_PATCH_TRADES_FOR_EVAL} trades)",
        )

    wr = stats.win_rate
    pf = stats.profit_factor
    avg = stats.avg_pnl

    # Strong performance — enable normally
    if wr >= ENABLE_15M_MIN_WIN_RATE and pf > ENABLE_15M_MIN_PROFIT_FACTOR and avg > ENABLE_15M_MIN_AVG_PNL:
        return Mode15mResult(
            enabled=True,
            tightened=False,
            confidence_boost=0.0,
            edge_boost=0.0,
            reason=f"15m enabled (WR={wr:.0%}, PF={pf:.1f}, avg=${avg:.2f})",
        )

    # Marginal — one threshold missed but not terrible. Tighten instead of disable.
    # "Marginal" = win rate above 50% and not deeply negative
    if wr >= 0.50 and stats.net_pnl > -5.0:
        return Mode15mResult(
            enabled=True,
            tightened=True,
            confidence_boost=ADAPTIVE_CONFIDENCE_BOOST,
            edge_boost=ADAPTIVE_EDGE_BOOST,
            reason=f"15m tightened (WR={wr:.0%}, PF={pf:.1f}, avg=${avg:.2f})",
        )

    # Poor performance — disable until next patch
    return Mode15mResult(
        enabled=False,
        tightened=False,
        confidence_boost=0.0,
        edge_boost=0.0,
        reason=f"15m disabled (WR={wr:.0%}, PF={pf:.1f}, avg=${avg:.2f})",
    )
