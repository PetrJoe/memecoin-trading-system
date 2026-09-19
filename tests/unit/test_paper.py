import pytest

from app.execution.paper import (
    PaperFillSimulator,
    PaperExecutor,
    simulate_slippage_pct,
)
from app.execution.transaction import TransactionManager, TransactionState


@pytest.fixture
def sim():
    return PaperFillSimulator(starting_cash_usd=100.0)


@pytest.fixture
def executor(sim):
    return PaperExecutor(simulator=sim, tx_manager=TransactionManager())


class TestSlippageModel:
    def test_zero_liquidity_gives_high_slippage(self):
        assert simulate_slippage_pct(100, 0) > 50

    def test_small_order_low_slippage(self):
        s = simulate_slippage_pct(10, 50_000)
        assert 0 < s < 1

    def test_large_order_relative_to_pool(self):
        small = simulate_slippage_pct(10, 50_000)
        large = simulate_slippage_pct(10_000, 50_000)
        assert large > small

    def test_impact_capped(self):
        assert simulate_slippage_pct(10_000_000, 100) <= 50.1


class TestPaperBuy:
    def test_buy_reduces_cash_and_creates_position(self, sim):
        sim.update_market("TOKEN1", price=1.0, liquidity_usd=50_000)
        result = sim.buy("TOKEN1", "TKN", amount_usd=10.0)
        assert result.success
        assert result.fill is not None
        assert sim.cash_usd == pytest.approx(90.0)
        assert "TOKEN1" in sim.positions

    def test_buy_fill_price_above_market(self, sim):
        sim.update_market("TOKEN1", price=1.0, liquidity_usd=50_000)
        result = sim.buy("TOKEN1", "TKN", amount_usd=10.0)
        assert result.fill.fill_price > 1.0  # slippage pushes entry up

    def test_buy_insufficient_cash(self, sim):
        sim.update_market("TOKEN1", price=1.0, liquidity_usd=50_000)
        result = sim.buy("TOKEN1", "TKN", amount_usd=500.0)
        assert not result.success
        assert "Insufficient" in result.error

    def test_buy_no_price(self, sim):
        result = sim.buy("UNKNOWN", "UNK", amount_usd=10.0)
        assert not result.success
        assert "No market price" in result.error

    def test_duplicate_buy_rejected(self, sim):
        sim.update_market("TOKEN1", price=1.0, liquidity_usd=50_000)
        assert sim.buy("TOKEN1", "TKN", 10.0).success
        result = sim.buy("TOKEN1", "TKN", 10.0)
        assert not result.success
        assert "already open" in result.error

    def test_buy_quantity_conservation(self, sim):
        """quantity * fill_price should equal net USD after fee."""
        sim.update_market("TOKEN1", price=1.0, liquidity_usd=100_000)
        result = sim.buy("TOKEN1", "TKN", amount_usd=20.0)
        net = 20.0 - result.fill.fee_usd
        assert result.fill.output_amount * result.fill.fill_price == pytest.approx(net)


class TestPaperSell:
    def test_full_sell_restores_cash(self, sim):
        sim.update_market("TOKEN1", price=1.0, liquidity_usd=50_000)
        sim.buy("TOKEN1", "TKN", 10.0)
        sim.update_market("TOKEN1", price=1.2, liquidity_usd=50_000)
        result = sim.sell("TOKEN1")
        assert result.success
        assert result.realized_pnl > 0
        assert "TOKEN1" not in sim.positions
        # Cash back plus profit minus round-trip fees/slippage
        assert sim.cash_usd < 100.0 + 2.0  # sanity upper bound
        assert sim.cash_usd > 100.0  # 20% move beats ~0.35% round-trip costs

    def test_sell_loss(self, sim):
        sim.update_market("TOKEN1", price=1.0, liquidity_usd=50_000)
        sim.buy("TOKEN1", "TKN", 10.0)
        sim.update_market("TOKEN1", price=0.5, liquidity_usd=50_000)
        result = sim.sell("TOKEN1")
        assert result.success
        assert result.realized_pnl < 0

    def test_partial_sell(self, sim):
        sim.update_market("TOKEN1", price=1.0, liquidity_usd=50_000)
        sim.buy("TOKEN1", "TKN", 10.0)
        original_qty = sim.positions["TOKEN1"].quantity
        result = sim.sell("TOKEN1", percentage=50.0)
        assert result.success
        assert sim.positions["TOKEN1"].quantity == pytest.approx(original_qty / 2)

    def test_sell_without_position(self, sim):
        result = sim.sell("TOKEN1")
        assert not result.success
        assert "No open position" in result.error

    def test_sell_invalid_percentage(self, sim):
        sim.update_market("TOKEN1", price=1.0, liquidity_usd=50_000)
        sim.buy("TOKEN1", "TKN", 10.0)
        assert not sim.sell("TOKEN1", percentage=0).success
        assert not sim.sell("TOKEN1", percentage=150).success

    def test_sell_no_price_after_buy(self, sim):
        sim.update_market("TOKEN1", price=1.0, liquidity_usd=50_000)
        sim.buy("TOKEN1", "TKN", 10.0)
        sim._prices.pop("TOKEN1")
        result = sim.sell("TOKEN1")
        assert not result.success


class TestPortfolio:
    def test_portfolio_value_mark_to_market(self, sim):
        sim.update_market("TOKEN1", price=1.0, liquidity_usd=50_000)
        sim.buy("TOKEN1", "TKN", 10.0)
        # All cash converted: value ~= position marked at market
        assert sim.portfolio_value() == pytest.approx(100.0, rel=0.01)

    def test_total_pnl_includes_open_positions(self, sim):
        sim.update_market("TOKEN1", price=1.0, liquidity_usd=50_000)
        sim.buy("TOKEN1", "TKN", 10.0)
        sim.update_market("TOKEN1", price=2.0, liquidity_usd=50_000)
        # Price doubled after entry; slippage at entry keeps total positive
        assert sim.total_pnl() > 0

    def test_unrealized_pnl(self, sim):
        sim.update_market("TOKEN1", price=1.0, liquidity_usd=50_000)
        sim.buy("TOKEN1", "TKN", 10.0)
        pos = sim.positions["TOKEN1"]
        sim.update_market("TOKEN1", price=1.5, liquidity_usd=50_000)
        expected = (1.5 - pos.entry_price) * pos.quantity
        assert pos.unrealized_pnl(1.5) == pytest.approx(expected)
        assert pos.unrealized_pnl_pct(1.5) > 0

    def test_trailing_high_water_mark(self, sim):
        sim.update_market("TOKEN1", price=1.0, liquidity_usd=50_000)
        sim.buy("TOKEN1", "TKN", 10.0)
        sim.update_market("TOKEN1", price=2.0, liquidity_usd=50_000)
        sim.update_market("TOKEN1", price=1.5, liquidity_usd=50_000)
        pos = sim.positions["TOKEN1"]
        assert pos.highest_price == 2.0


class TestPaperExecutor:
    @pytest.mark.asyncio
    async def test_buy_traverses_state_machine(self, executor, sim):
        sim.update_market("TOKEN1", price=1.0, liquidity_usd=50_000)
        result = await executor.execute_buy("TOKEN1", "TKN", 10.0, stop_loss=0.9, take_profit=1.3)
        assert result.success

        # Every tx went through the full state machine
        records = executor._tx_manager.get_all()
        assert records
        assert all(r.state == TransactionState.CONFIRMED for r in records)

        # Position carries the configured exits
        pos = sim.positions["TOKEN1"]
        assert pos.stop_loss == 0.9
        assert pos.take_profit == 1.3

    @pytest.mark.asyncio
    async def test_failed_buy_marks_failed(self, executor):
        result = await executor.execute_buy("UNKNOWN", "UNK", 10.0)
        assert not result.success
        records = executor._tx_manager.get_all()
        assert records[-1].state == TransactionState.FAILED

    @pytest.mark.asyncio
    async def test_buy_sell_round_trip(self, executor, sim):
        sim.update_market("TOKEN1", price=1.0, liquidity_usd=100_000)
        buy = await executor.execute_buy("TOKEN1", "TKN", 10.0)
        assert buy.success

        sim.update_market("TOKEN1", price=1.4, liquidity_usd=100_000)
        sell = await executor.execute_sell("TOKEN1")
        assert sell.success
        assert sell.realized_pnl > 0
        assert "TOKEN1" not in sim.positions
