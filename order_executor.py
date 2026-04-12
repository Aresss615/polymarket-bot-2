"""Order execution abstraction.

Three modes:
- PaperExecutor: instant fill at quoted price, zero fees (current behavior)
- SimulationExecutor: realistic fills with fees, slippage, partial fills
- LiveExecutor: stub for real CLOB execution (not yet implemented)
"""

import random
import uuid
from abc import ABC, abstractmethod

from config import OrderResult, Signal, MAX_TAKER_FEE_RATE


class OrderExecutor(ABC):
    """Base class for order execution."""

    @abstractmethod
    def place_order(self, signal: Signal, size: float, entry_price: float) -> OrderResult:
        """Execute an order and return the result."""


class PaperExecutor(OrderExecutor):
    """Instant fill at quoted price with zero fees.

    Preserves the original paper trading behavior exactly.
    """

    def place_order(self, signal: Signal, size: float, entry_price: float) -> OrderResult:
        return OrderResult(
            filled=True,
            fill_price=entry_price,
            fill_size=size,
            fees=0.0,
            slippage=0.0,
            latency_ms=0.0,
            order_id=f"paper-{uuid.uuid4().hex[:8]}",
            status="filled",
        )


def polymarket_taker_fee(price: float) -> float:
    """Estimate Polymarket dynamic taker fee rate.

    Fee is highest (1.8%) at price 0.50 and decreases toward extremes.
    Formula: fee_rate = MAX_TAKER_FEE_RATE * (1 - 2 * |price - 0.50|)
    Examples: price 0.50 → 1.8%, price 0.75 → 0.9%, price 0.85 → 0.54%
    """
    return max(0.0, MAX_TAKER_FEE_RATE * (1.0 - 2.0 * abs(price - 0.50)))


class SimulationExecutor(OrderExecutor):
    """Realistic fill simulation with fees, slippage, and partial fills.

    Models:
    - Dynamic taker fees based on entry price
    - Adverse slippage (0.5-1.5% of entry price)
    - Partial fills: 90% chance full, 10% chance 60-90% fill
    - 2% rejection rate (rate limits, stale prices)
    """

    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)

    def place_order(self, signal: Signal, size: float, entry_price: float) -> OrderResult:
        # 2% rejection
        if self._rng.random() < 0.02:
            return OrderResult(
                filled=False,
                fill_price=entry_price,
                fill_size=0.0,
                fees=0.0,
                slippage=0.0,
                latency_ms=self._rng.uniform(50, 300),
                order_id=f"sim-{uuid.uuid4().hex[:8]}",
                status="rejected",
                reason="simulated rejection (rate limit / stale)",
            )

        # Fee calculation
        fee_rate = polymarket_taker_fee(entry_price)
        fees = size * fee_rate

        # Adverse slippage: 0.5-1.5% of entry price
        slippage_pct = self._rng.uniform(0.005, 0.015)
        # Slippage always makes the fill worse (higher price for buys)
        slippage = entry_price * slippage_pct
        fill_price = min(entry_price + slippage, 0.99)

        # Partial fill: 10% chance
        if self._rng.random() < 0.10:
            fill_ratio = self._rng.uniform(0.6, 0.9)
            fill_size = size * fill_ratio
            status = "partial"
        else:
            fill_size = size
            status = "filled"

        # Adjust fees for actual fill size
        fees = fill_size * fee_rate

        return OrderResult(
            filled=True,
            fill_price=fill_price,
            fill_size=fill_size,
            fees=fees,
            slippage=slippage,
            latency_ms=self._rng.uniform(50, 300),
            order_id=f"sim-{uuid.uuid4().hex[:8]}",
            status=status,
        )


class LiveExecutor(OrderExecutor):
    """Real CLOB execution via py-clob-client.

    Not yet implemented — requires wallet setup, token allowances,
    and at least one manual trade on polymarket.com UI first.
    """

    def place_order(self, signal: Signal, size: float, entry_price: float) -> OrderResult:
        raise NotImplementedError(
            "Live trading not yet enabled. "
            "See LIVE_TRADING_PLAN.md for setup steps."
        )
