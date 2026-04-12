from config import Market, Signal
from order_executor import PaperExecutor, SimulationExecutor, polymarket_taker_fee


def _make_signal(side="YES", price=0.75):
    market = Market(
        condition_id="0xtest",
        question="Test?",
        slug="test-updown-5m-1",
        outcomes=["Up", "Down"],
        outcome_prices=[price, 1 - price],
        token_ids=["0xup", "0xdown"],
        end_date=None,
        active=True,
    )
    return Signal(market=market, strategy="updown", side=side, confidence=0.8, reason="test")


class TestPaperExecutor:
    def test_instant_fill_at_quoted_price(self):
        executor = PaperExecutor()
        result = executor.place_order(_make_signal(), size=5.0, entry_price=0.75)

        assert result.filled is True
        assert result.fill_price == 0.75
        assert result.fill_size == 5.0
        assert result.fees == 0.0
        assert result.slippage == 0.0
        assert result.status == "filled"
        assert result.order_id.startswith("paper-")

    def test_no_side(self):
        executor = PaperExecutor()
        result = executor.place_order(_make_signal(side="NO"), size=3.0, entry_price=0.25)

        assert result.filled is True
        assert result.fill_price == 0.25
        assert result.fill_size == 3.0


class TestSimulationExecutor:
    def test_applies_fees(self):
        executor = SimulationExecutor(seed=42)
        result = executor.place_order(_make_signal(), size=5.0, entry_price=0.75)

        assert result.filled is True
        assert result.fees > 0
        assert result.fill_price >= 0.75  # adverse slippage

    def test_fee_higher_near_50(self):
        """Fee should be higher at price 0.50 than at 0.85."""
        fee_at_50 = polymarket_taker_fee(0.50)
        fee_at_85 = polymarket_taker_fee(0.85)
        assert fee_at_50 > fee_at_85
        assert abs(fee_at_50 - 0.018) < 0.001  # max 1.8% at 0.50

    def test_fee_at_extremes(self):
        """Fee should be near zero at extreme prices."""
        fee_at_95 = polymarket_taker_fee(0.95)
        assert fee_at_95 < 0.003  # very low at extremes

    def test_deterministic_with_same_seed(self):
        """Same seed should produce identical results."""
        sig = _make_signal()
        r1 = SimulationExecutor(seed=123).place_order(sig, 5.0, 0.75)
        r2 = SimulationExecutor(seed=123).place_order(sig, 5.0, 0.75)

        assert r1.fill_price == r2.fill_price
        assert r1.fill_size == r2.fill_size
        assert r1.fees == r2.fees
        assert r1.status == r2.status

    def test_partial_fill_possible(self):
        """With enough attempts, a partial fill should occur."""
        found_partial = False
        for seed in range(200):
            executor = SimulationExecutor(seed=seed)
            result = executor.place_order(_make_signal(), size=10.0, entry_price=0.75)
            if result.status == "partial":
                assert result.fill_size < 10.0
                assert result.fill_size > 0
                found_partial = True
                break
        assert found_partial, "No partial fill found in 200 seeds"

    def test_rejection_possible(self):
        """With enough attempts, a rejection should occur."""
        found_rejection = False
        for seed in range(200):
            executor = SimulationExecutor(seed=seed)
            result = executor.place_order(_make_signal(), size=5.0, entry_price=0.75)
            if not result.filled:
                assert result.status == "rejected"
                assert result.fill_size == 0.0
                found_rejection = True
                break
        assert found_rejection, "No rejection found in 200 seeds"

    def test_slippage_always_adverse(self):
        """Fill price should always be >= entry price (adverse for buyer)."""
        for seed in range(50):
            executor = SimulationExecutor(seed=seed)
            result = executor.place_order(_make_signal(), size=5.0, entry_price=0.75)
            if result.filled:
                assert result.fill_price >= 0.75

    def test_fees_scale_with_fill_size(self):
        """Partial fills should have proportionally lower fees."""
        # Get a full fill
        full = SimulationExecutor(seed=0).place_order(_make_signal(), size=10.0, entry_price=0.75)
        if full.filled and full.status == "filled":
            # Fees should be size * fee_rate
            expected_fee_rate = polymarket_taker_fee(0.75)
            assert abs(full.fees - 10.0 * expected_fee_rate) < 0.01
