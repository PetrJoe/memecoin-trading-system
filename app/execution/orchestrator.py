from __future__ import annotations

import asyncio
import time
from typing import Optional

from app.config import get_logger, get_settings
from app.portfolio.pnl import ClosedTrade, PnLCalculator
from app.portfolio.positions import PositionManager
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.exposure import ExposureTracker
from app.risk.models import PortfolioRiskData, RiskResult, TokenRiskData
from app.risk.position_sizing import PositionSizer
from app.risk.risk_engine import RiskEngine
from app.strategy.base import SignalType, StrategyContext, StrategySignal

logger = get_logger(category="trades")

DUPLICATE_WINDOW_SECONDS = 120.0


class OrchestratorError(Exception):
    pass


class TradeOrchestrator:
    """
    Coordinates the full buy/sell pipeline per PRD §18/§19:

      candidate -> risk analysis -> strategy signal -> position sizing
      -> circuit breaker -> execution -> position creation -> P&L

    Enforces duplicate protection (one in-flight operation per token,
    signal-window idempotency) and fails gracefully on every step.
    Execution is delegated to a pluggable executor (paper or live), so
    paper and live modes share the identical decision pipeline.
    """

    def __init__(
        self,
        risk_engine: RiskEngine,
        position_sizer: PositionSizer,
        circuit_breaker: CircuitBreaker,
        position_manager: PositionManager,
        pnl_calculator: PnLCalculator,
        exposure_tracker: ExposureTracker,
        executor,  # PaperExecutor or live Buy/Sell executor pair
        notifier=None,  # optional Telegram notifier
    ) -> None:
        self.settings = get_settings()
        self.risk_engine = risk_engine
        self.position_sizer = position_sizer
        self.circuit_breaker = circuit_breaker
        self.position_manager = position_manager
        self.pnl_calculator = pnl_calculator
        self.exposure_tracker = exposure_tracker
        self.executor = executor
        self.notifier = notifier

        # Duplicate protection: per-token locks + recent signal window
        self._token_locks: dict[str, asyncio.Lock] = {}
        self._recent_signals: dict[str, float] = {}
        self._in_flight: set[str] = set()

    # ------------------------------------------------------------ protection
    def _get_lock(self, token_address: str) -> asyncio.Lock:
        if token_address not in self._token_locks:
            self._token_locks[token_address] = asyncio.Lock()
        return self._token_locks[token_address]

    def _is_duplicate_signal(self, token_address: str) -> bool:
        last = self._recent_signals.get(token_address)
        return last is not None and (time.time() - last) < DUPLICATE_WINDOW_SECONDS

    def _mark_signal(self, token_address: str) -> None:
        self._recent_signals[token_address] = time.time()

    def is_busy(self, token_address: str) -> bool:
        return token_address in self._in_flight

    # ------------------------------------------------------------------- buy
    async def process_buy_signal(
        self,
        token_address: str,
        symbol: str,
        snapshot,
        token_risk: TokenRiskData,
        portfolio_risk: PortfolioRiskData,
        strategy_context: Optional[StrategyContext] = None,
    ) -> dict:
        """
        Full buy pipeline. Returns a result dict:
        {status: executed|rejected|skipped|failed, reason, ...}
        """
        if self._is_duplicate_signal(token_address):
            return {"status": "skipped", "reason": "duplicate_signal_window"}

        if self.is_busy(token_address):
            return {"status": "skipped", "reason": "operation_in_progress"}

        if not self.circuit_breaker.can_trade:
            return {
                "status": "rejected",
                "reason": f"circuit_breaker_{self.circuit_breaker.state.value.lower()}",
            }

        async with self._get_lock(token_address):
            self._in_flight.add(token_address)
            try:
                return await self._buy_pipeline(
                    token_address, symbol, snapshot, token_risk, portfolio_risk, strategy_context
                )
            finally:
                self._in_flight.discard(token_address)

    async def _buy_pipeline(
        self,
        token_address: str,
        symbol: str,
        snapshot,
        token_risk: TokenRiskData,
        portfolio_risk: PortfolioRiskData,
        strategy_context: Optional[StrategyContext],
    ) -> dict:
        # 1. Risk analysis (PRD: risk before strategy)
        risk_result: RiskResult = await self.risk_engine.evaluate(token_risk, portfolio_risk)
        if not risk_result.approved:
            logger.info("buy_rejected_by_risk", token=symbol, reasons=risk_result.critical_failures)
            return {"status": "rejected", "reason": "risk_engine", "detail": risk_result.critical_failures}

        # Hard guard: never double-buy a token we already hold
        if self.position_manager.has_position(token_address):
            return {"status": "skipped", "reason": "position_already_open"}

        # 2. Strategy signal
        context = strategy_context or StrategyContext(snapshot=snapshot, risk_score=risk_result.score)
        signal: StrategySignal = await self.executor.analyze(context) if hasattr(
            self.executor, "analyze"
        ) else await self._default_analyze(context, risk_result.score)

        if not signal.is_buy:
            return {"status": "skipped", "reason": f"signal_{signal.signal.value.lower()}", "score": signal.score}

        # 3. Circuit breaker check
        if not self.circuit_breaker.can_trade:
            self.circuit_breaker.record_execution_failure()
            return {"status": "rejected", "reason": "circuit_breaker_mid_pipeline"}

        # 4. Position sizing
        position_size_usd = self.position_sizer.calculate(
            wallet_balance_usd=portfolio_risk.wallet_balance_usd,
            risk_score=risk_result.score,
            open_positions=portfolio_risk.open_positions,
            total_exposure_usd=portfolio_risk.total_exposure_usd,
            daily_loss_usd=portfolio_risk.daily_loss_usd,
            strategy_confidence=signal.confidence,
        )
        if position_size_usd <= 0:
            return {"status": "skipped", "reason": "position_size_zero"}

        # 5. Execute via executor (paper or live)
        result = await self.executor.execute_buy(
            token_address=token_address,
            symbol=symbol,
            amount_usd=position_size_usd,
        )
        if not result.success:
            self.circuit_breaker.record_execution_failure()
            return {"status": "failed", "reason": "execution_failed", "detail": result.error}

        # 6. Create position with configured exits
        fill = result.fill
        entry_price = fill.fill_price
        quantity = fill.output_amount
        stop_loss = entry_price * (1 - self.settings.STOP_LOSS_PERCENT / 100.0)
        take_profit = entry_price * (1 + self.settings.TAKE_PROFIT_PERCENT / 100.0)

        position_id = int(time.time() * 1000) % 1_000_000  # placeholder id until DB integration
        self.position_manager.open_position(
            position_id=position_id,
            token_address=token_address,
            symbol=symbol,
            entry_price=entry_price,
            quantity=quantity,
            capital_usd=position_size_usd,
        )
        self.exposure_tracker.add_position(position_id, position_size_usd)
        self._mark_signal(token_address)

        logger.info(
            "buy_pipeline_complete",
            token=symbol,
            size_usd=position_size_usd,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        if self.notifier:
            await self._notify_safe("buy_executed", token=symbol, size_usd=position_size_usd,
                                    entry_price=entry_price)

        return {
            "status": "executed",
            "position_id": position_id,
            "entry_price": entry_price,
            "quantity": quantity,
            "size_usd": position_size_usd,
            "slippage_pct": fill.slippage_pct,
            "fee_usd": fill.fee_usd,
        }

    async def _default_analyze(self, context: StrategyContext, risk_score: int) -> StrategySignal:
        from app.strategy.momentum import MomentumStrategy

        context.risk_score = risk_score
        strategy = MomentumStrategy()
        return await strategy.analyze(context)

    # ------------------------------------------------------------------ sell
    async def process_price_update(
        self,
        token_address: str,
        current_price: float,
        portfolio_risk: Optional[PortfolioRiskData] = None,
    ) -> dict:
        """
        Evaluate exit conditions for an open position; on exit decision,
        run the sell pipeline (PRD §19).
        """
        if self.is_busy(token_address):
            return {"status": "skipped", "reason": "operation_in_progress"}

        decision = self.position_manager.update_price(token_address, current_price)
        if decision is None or not decision.should_exit:
            return {"status": "holding", "price": current_price}

        async with self._get_lock(token_address):
            self._in_flight.add(token_address)
            try:
                return await self._sell_pipeline(
                    token_address, current_price, decision.reason, portfolio_risk
                )
            finally:
                self._in_flight.discard(token_address)

    async def _sell_pipeline(
        self,
        token_address: str,
        current_price: float,
        exit_reason: str,
        portfolio_risk: Optional[PortfolioRiskData],
    ) -> dict:
        pos = self.position_manager.get(token_address)
        if pos is None:
            return {"status": "skipped", "reason": "no_position"}

        logger.info(
            "sell_pipeline_start",
            token=pos.symbol,
            reason=exit_reason,
            entry_price=pos.entry_price,
            current_price=current_price,
        )

        result = await self.executor.execute_sell(token_address)
        if not result.success:
            self.circuit_breaker.record_execution_failure()
            logger.error("sell_execution_failed", token=pos.symbol, error=result.error)
            return {"status": "failed", "reason": "execution_failed", "detail": result.error}

        closed = self.position_manager.close_position(token_address)

        fill = result.fill
        trade = ClosedTrade(
            side="SELL",
            token_address=token_address,
            symbol=pos.symbol,
            entry_price=pos.entry_price,
            exit_price=fill.fill_price,
            quantity=fill.input_amount,
            capital_usd=pos.capital_usd,
            proceeds_usd=fill.output_amount,
            fees_usd=fill.fee_usd,
            pnl_usd=result.realized_pnl,
            pnl_pct=result.realized_pnl_pct,
            exit_reason=exit_reason,
            entry_time=pos.opened_at,
        )
        self.pnl_calculator.record_trade(trade)
        self.exposure_tracker.remove_position(closed.position_id if closed else 0)

        self.circuit_breaker.record_success()

        logger.info(
            "sell_pipeline_complete",
            token=pos.symbol,
            reason=exit_reason,
            realized_pnl=round(result.realized_pnl, 4),
            realized_pnl_pct=round(result.realized_pnl_pct, 2),
        )

        if self.notifier:
            await self._notify_safe(
                "position_closed",
                token=pos.symbol,
                reason=exit_reason,
                pnl=result.realized_pnl,
            )

        # Daily loss circuit breaker check
        if portfolio_risk is not None:
            daily_loss = self.pnl_calculator.daily_summary().net_pnl
            if daily_loss < 0 and abs(daily_loss) >= self.settings.MAX_DAILY_LOSS_USD:
                self.circuit_breaker.record_daily_loss_exceeded(
                    abs(daily_loss), self.settings.MAX_DAILY_LOSS_USD
                )
            consecutive = self.pnl_calculator.consecutive_losses()
            if consecutive > 0:
                self.circuit_breaker.record_consecutive_losses(consecutive)

        return {
            "status": "exited",
            "reason": exit_reason,
            "realized_pnl": result.realized_pnl,
            "realized_pnl_pct": result.realized_pnl_pct,
            "exit_price": fill.fill_price,
            "proceeds_usd": fill.output_amount,
            "fee_usd": fill.fee_usd,
        }

    # --------------------------------------------------- manual / emergency
    async def close_position_now(
        self,
        token_address: str,
        reason: str = "MANUAL",
        current_price: Optional[float] = None,
    ) -> dict:
        """Manual/emergency exit outside the normal exit-condition loop."""
        if self.is_busy(token_address):
            return {"status": "skipped", "reason": "operation_in_progress"}

        pos = self.position_manager.get(token_address)
        if pos is None:
            return {"status": "skipped", "reason": "no_position"}

        price = current_price or pos.last_price or pos.entry_price
        async with self._get_lock(token_address):
            self._in_flight.add(token_address)
            try:
                return await self._sell_pipeline(token_address, price, reason, None)
            finally:
                self._in_flight.discard(token_address)

    async def emergency_close_all(self) -> list[dict]:
        """Close every open position with reason EMERGENCY (used by web UI / kill switch)."""
        results = []
        for token_address in list(self.position_manager.positions.keys()):
            result = await self.close_position_now(token_address, reason="EMERGENCY")
            results.append({"token": token_address, **result})
        logger.warning("emergency_close_all", closed=len(results))
        return results

    # --------------------------------------------------------------- helpers
    async def _notify_safe(self, event: str, **kwargs) -> None:
        """Telegram failures must never break the trading pipeline."""
        try:
            await self.notifier.send_event(event, **kwargs)
        except Exception as e:
            logger.warning("notification_failed", event_type=event, error=str(e))

    def is_trading_allowed(self) -> bool:
        return self.circuit_breaker.can_trade and self.settings.TRADING_MODE != "disabled"
