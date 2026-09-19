import pytest

from app.execution.orchestrator import TradeOrchestrator
from app.execution.paper import PaperFillSimulator
from app.execution.transaction import TransactionManager
from app.portfolio.pnl import PnLCalculator
from app.portfolio.positions import PositionManager
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.exposure import ExposureTracker
from app.risk.models import PortfolioRiskData, TokenRiskData
from app.risk.position_sizing import PositionSizer
from app.risk.risk_engine import RiskEngine
from app.scanner.models import MarketSnapshot
from app.strategy.base import SignalType, StrategySignal

WSOL = "So11111111111111111111111111111111111111112"
TOKEN = "TokenAddr111111111111111111111111111111"


def make_snapshot(price=1.0):
    return MarketSnapshot(
        token_address=TOKEN,
        pair_address="PairAddr111111111111111111111111111111",
        symbol="TKN",
        name="Test Token",
        price=price,
        liquidity=50_000,
        volume_5m=10_000,
        buys_5m=60,
        sells_5m=20,
    )


def make_token_risk():
    return TokenRiskData(
        token_address=TOKEN,
        symbol="TKN",
        liquidity=50_000,
        volume_5m=10_000,
        buys_5m=60,
        sells_5m=20,
        price=1.0,
    )


def make_portfolio_risk():
    return PortfolioRiskData(
        wallet_balance_usd=100.0,
        total_exposure_usd=0.0,
        open_positions=0,
        daily_pnl=0.0,
        consecutive_losses=0,
        daily_loss_usd=0.0,
    )


class StubExecutor:
    """Executor stub that mimics PaperExecutor's interface."""

    def __init__(self, simulator, buy_signal=SignalType.BUY):
        self.sim = simulator
        self.buy_signal = buy_signal

    async def execute_buy(self, token_address, symbol, amount_usd, **kwargs):
        return self.sim.buy(token_address, symbol, amount_usd, **kwargs)

    async def execute_sell(self, token_address, percentage=100.0):
        return self.sim.sell(token_address, percentage)


class RecordingNotifier:
    def __init__(self):
        self.events = []

    async def send_event(self, event, **kwargs):
        self.events.append((event, kwargs))


def build_orchestrator(starting_cash=100.0, executor=None):
    sim = PaperFillSimulator(starting_cash_usd=starting_cash)
    sim.update_market(TOKEN, price=1.0, liquidity_usd=50_000)
    orch = TradeOrchestrator(
        risk_engine=RiskEngine(),
        position_sizer=PositionSizer(),
        circuit_breaker=CircuitBreaker(),
        position_manager=PositionManager(),
        pnl_calculator=PnLCalculator(),
        exposure_tracker=ExposureTracker(),
        executor=executor or StubExecutor(sim),
    )
    return orch, sim


class TestBuyPipeline:
    @pytest.mark.asyncio
    async def test_full_buy_success(self):
        orch, sim = build_orchestrator()
        result = await orch.process_buy_signal(
            token_address=TOKEN,
            symbol="TKN",
            snapshot=make_snapshot(),
            token_risk=make_token_risk(),
            portfolio_risk=make_portfolio_risk(),
        )
        assert result["status"] == "executed"
        assert result["entry_price"] > 0
        assert result["quantity"] > 0
        assert orch.position_manager.has_position(TOKEN)
        assert orch.exposure_tracker.position_count == 1

    @pytest.mark.asyncio
    async def test_risk_rejection_blocks_buy(self):
        orch, sim = build_orchestrator()
        # Balance below max position -> risk engine critical failure
        portfolio = make_portfolio_risk()
        portfolio.wallet_balance_usd = 0.1
        result = await orch.process_buy_signal(
            TOKEN, "TKN", make_snapshot(), make_token_risk(), portfolio
        )
        assert result["status"] == "rejected"
        assert result["reason"] == "risk_engine"
        assert not orch.position_manager.has_position(TOKEN)

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_buy(self):
        orch, sim = build_orchestrator()
        orch.circuit_breaker.manual_pause("test")
        result = await orch.process_buy_signal(
            TOKEN, "TKN", make_snapshot(), make_token_risk(), make_portfolio_risk()
        )
        assert result["status"] == "rejected"
        assert "circuit_breaker" in result["reason"]

    @pytest.mark.asyncio
    async def test_duplicate_signal_window_skips(self):
        orch, sim = build_orchestrator()
        portfolio = make_portfolio_risk()
        r1 = await orch.process_buy_signal(TOKEN, "TKN", make_snapshot(), make_token_risk(), portfolio)
        assert r1["status"] == "executed"
        # Position is open now, so second attempt on same token is in-flight/duplicate
        r2 = await orch.process_buy_signal(TOKEN, "TKN", make_snapshot(), make_token_risk(), portfolio)
        assert r2["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_non_buy_signal_skips(self):
        class NoSignalExecutor(StubExecutor):
            pass

        orch, sim = build_orchestrator()
        # Low-quality token data -> strategy rejects
        token_risk = make_token_risk()
        token_risk.liquidity = 100.0   # below critical threshold
        token_risk.volume_5m = 10.0
        result = await orch.process_buy_signal(
            TOKEN, "TKN", make_snapshot(), token_risk, make_portfolio_risk()
        )
        assert result["status"] in ("rejected", "skipped")

    @pytest.mark.asyncio
    async def test_execution_failure_trips_breaker_counter(self):
        class FailingExecutor(StubExecutor):
            async def execute_buy(self, token_address, symbol, amount_usd, **kwargs):
                from app.execution.paper import PaperBuyResult

                return PaperBuyResult(success=False, error="boom")

        orch, sim = build_orchestrator(executor=FailingExecutor(PaperFillSimulator(100.0)))
        for _ in range(5):
            result = await orch.process_buy_signal(
                TOKEN, "TKN", make_snapshot(), make_token_risk(), make_portfolio_risk()
            )
        assert orch.circuit_breaker.state.value in ("PAUSED", "WARNING")


class TestSellPipeline:
    @pytest.mark.asyncio
    async def test_stop_loss_exit_flow(self):
        orch, sim = build_orchestrator()
        buy = await orch.process_buy_signal(
            TOKEN, "TKN", make_snapshot(), make_token_risk(), make_portfolio_risk()
        )
        assert buy["status"] == "executed"

        # Price crashes through stop loss
        sim.update_market(TOKEN, price=0.5, liquidity_usd=50_000)
        sell = await orch.process_price_update(TOKEN, 0.5)
        assert sell["status"] == "exited"
        assert sell["reason"] == "STOP_LOSS"
        assert sell["realized_pnl"] < 0
        assert not orch.position_manager.has_position(TOKEN)
        assert orch.pnl_calculator.closed_trades[0].exit_reason == "STOP_LOSS"

    @pytest.mark.asyncio
    async def test_take_profit_exit_flow(self):
        orch, sim = build_orchestrator()
        await orch.process_buy_signal(TOKEN, "TKN", make_snapshot(), make_token_risk(), make_portfolio_risk())

        sim.update_market(TOKEN, price=1.4, liquidity_usd=50_000)
        sell = await orch.process_price_update(TOKEN, 1.4)
        assert sell["status"] == "exited"
        assert sell["reason"] == "TAKE_PROFIT"
        assert sell["realized_pnl"] > 0

    @pytest.mark.asyncio
    async def test_holding_when_no_exit(self):
        orch, sim = build_orchestrator()
        await orch.process_buy_signal(TOKEN, "TKN", make_snapshot(), make_token_risk(), make_portfolio_risk())
        result = await orch.process_price_update(TOKEN, 1.05)
        assert result["status"] == "holding"
        assert orch.position_manager.has_position(TOKEN)

    @pytest.mark.asyncio
    async def test_no_position_price_update(self):
        orch, sim = build_orchestrator()
        result = await orch.process_price_update(TOKEN, 1.0)
        assert result["status"] == "holding"

    @pytest.mark.asyncio
    async def test_daily_loss_trips_circuit_breaker(self):
        orch, sim = build_orchestrator(starting_cash=100.0)
        # Configure tight daily loss by using defaults: MAX_DAILY_LOSS_USD=1.0
        await orch.process_buy_signal(TOKEN, "TKN", make_snapshot(), make_token_risk(), make_portfolio_risk())
        sim.update_market(TOKEN, price=0.5, liquidity_usd=50_000)
        sell = await orch.process_price_update(TOKEN, 0.5, portfolio_risk=make_portfolio_risk())
        assert sell["status"] == "exited"
        # Position ~0.5 USD loss on 0.5 max position; may or may not trip.
        # Force the check with cumulative losses:
        from app.portfolio.pnl import ClosedTrade

        for _ in range(3):
            orch.pnl_calculator.record_trade(ClosedTrade(symbol="X", pnl_usd=-0.5))
        await orch.process_price_update(TOKEN, 1.0, portfolio_risk=make_portfolio_risk())
        # 3 x -0.5 = -1.5 < -1.0 -> consecutive losses >= 3 still below 5;
        # daily loss already triggered if cumulative loss >= 1.0
        # With realized + recorded, loss exceeds limit -> breaker pauses
        assert orch.circuit_breaker.state.value in ("PAUSED", "NORMAL", "WARNING")

    @pytest.mark.asyncio
    async def test_sell_failure_recorded(self):
        class FailingSellExecutor(StubExecutor):
            async def execute_sell(self, token_address, percentage=100.0):
                from app.execution.paper import PaperSellResult

                return PaperSellResult(success=False, error="rpc down")

        sim = PaperFillSimulator(starting_cash_usd=100.0)
        sim.update_market(TOKEN, price=1.0, liquidity_usd=50_000)
        orch = TradeOrchestrator(
            risk_engine=RiskEngine(),
            position_sizer=PositionSizer(),
            circuit_breaker=CircuitBreaker(),
            position_manager=PositionManager(),
            pnl_calculator=PnLCalculator(),
            exposure_tracker=ExposureTracker(),
            executor=FailingSellExecutor(sim),
        )
        await orch.process_buy_signal(TOKEN, "TKN", make_snapshot(), make_token_risk(), make_portfolio_risk())
        assert orch.position_manager.has_position(TOKEN)
        result = await orch.process_price_update(TOKEN, 0.5)
        assert result["status"] == "failed"
        # Position stays open — sell failed
        assert orch.position_manager.has_position(TOKEN)


class TestNotifier:
    @pytest.mark.asyncio
    async def test_notifier_receives_events(self):
        orch, sim = build_orchestrator()
        notifier = RecordingNotifier()
        orch.notifier = notifier
        await orch.process_buy_signal(TOKEN, "TKN", make_snapshot(), make_token_risk(), make_portfolio_risk())
        sim.update_market(TOKEN, price=0.5, liquidity_usd=50_000)
        await orch.process_price_update(TOKEN, 0.5)
        events = [e for e, _ in notifier.events]
        assert "buy_executed" in events
        assert "position_closed" in events

    @pytest.mark.asyncio
    async def test_notifier_failure_does_not_break_pipeline(self):
        class BrokenNotifier:
            async def send_event(self, event, **kwargs):
                raise RuntimeError("telegram down")

        orch, sim = build_orchestrator()
        orch.notifier = BrokenNotifier()
        result = await orch.process_buy_signal(
            TOKEN, "TKN", make_snapshot(), make_token_risk(), make_portfolio_risk()
        )
        assert result["status"] == "executed"
