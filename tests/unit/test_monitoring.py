import pytest

from app.api.state import AppState
from app.execution.paper import PaperFillSimulator
from app.monitoring.metrics import MetricsCollector
from app.portfolio.balances import BalanceTracker
from app.portfolio.positions import PositionManager
from app.workers.reconciliation_worker import ReconciliationWorker

TOKEN = "TokenAddr111111111111111111111111111111"


class TestMetricsCollector:
    def test_collect_returns_metrics(self):
        collector = MetricsCollector()
        m = collector.collect()
        assert m.uptime_seconds > 0
        assert m.disk_free_mb >= 0
        assert 0 <= m.disk_used_percent <= 100

    def test_threshold_checks_no_warnings_normally(self):
        collector = MetricsCollector()
        m = collector.collect()
        # Default thresholds: disk 80%, mem 85% — a test env should be under
        assert isinstance(collector.check_thresholds(m), list)


class TestReconciliationWorker:
    @pytest.fixture
    def wired_state(self):
        state = AppState()
        sim = PaperFillSimulator(starting_cash_usd=100.0)
        sim.update_market(TOKEN, price=1.0, liquidity_usd=50_000)
        state.paper_simulator = sim
        state.position_manager = PositionManager()
        state.balance_tracker = BalanceTracker(starting_balance_usd=100.0)
        worker = ReconciliationWorker(app_state=state)
        return state, sim, worker

    @pytest.mark.asyncio
    async def test_consistent_state(self, wired_state):
        state, sim, worker = wired_state

        sim.buy(TOKEN, "TKN", 10.0)
        state.position_manager.open_position(
            position_id=1, token_address=TOKEN, symbol="TKN",
            entry_price=1.0, quantity=sim.positions[TOKEN].quantity, capital_usd=10.0,
        )
        state.balance_tracker.record_buy(10.0, 0.0)

        report = await worker.reconcile()
        assert report.consistent
        assert report.issues == []
        assert report.checked_positions == 1

    @pytest.mark.asyncio
    async def test_detects_quantity_mismatch(self, wired_state):
        state, sim, worker = wired_state

        sim.buy(TOKEN, "TKN", 10.0)
        state.position_manager.open_position(
            position_id=1, token_address=TOKEN, symbol="TKN",
            entry_price=1.0, quantity=999.0, capital_usd=10.0,  # wrong qty
        )
        state.balance_tracker.record_buy(10.0, 0.0)

        report = await worker.reconcile()
        assert not report.consistent
        assert any("quantity mismatch" in i for i in report.issues)

    @pytest.mark.asyncio
    async def test_detects_missing_position(self, wired_state):
        state, sim, worker = wired_state

        state.position_manager.open_position(
            position_id=1, token_address=TOKEN, symbol="TKN",
            entry_price=1.0, quantity=10.0, capital_usd=10.0,
        )
        # Simulator has no position -> mismatch

        report = await worker.reconcile()
        assert not report.consistent
        assert any("not simulator" in i for i in report.issues)

    @pytest.mark.asyncio
    async def test_detects_cash_mismatch(self, wired_state):
        state, sim, worker = wired_state

        sim.cash_usd = 55.0  # tampered
        # balance tracker still thinks 100
        report = await worker.reconcile()
        assert not report.consistent
        assert any("cash mismatch" in i for i in report.issues)

    @pytest.mark.asyncio
    async def test_emits_event_on_inconsistency(self, wired_state):
        state, sim, worker = wired_state
        sim.cash_usd = 1.0
        await worker.reconcile()
        assert any(
            e.event_type == "reconciliation_failed" for e in state.event_log.recent(10)
        )
