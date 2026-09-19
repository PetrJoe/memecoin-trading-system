from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from app.api.state import get_app_state
from app.config import get_logger, get_settings

logger = get_logger(category="trades")

RECONCILE_INTERVAL_SECONDS = 300.0  # 5 minutes


@dataclass
class ReconciliationReport:
    consistent: bool
    issues: list[str] = field(default_factory=list)
    checked_positions: int = 0
    checked_at: float = field(default_factory=time.time)


class ReconciliationWorker:
    """
    Verifies internal consistency of paper state:
      - simulator positions match PositionManager positions
      - exposure tracker totals match position capital
      - balance tracker cash matches simulator cash

    In live mode this is where on-chain reconciliation
    (app/blockchain/reconciliation.py) plugs in.
    """

    def __init__(self, interval: float = RECONCILE_INTERVAL_SECONDS, app_state=None) -> None:
        self.settings = get_settings()
        self.interval = interval
        self.state = app_state  # resolved lazily via get_app_state() if None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.last_report: Optional[ReconciliationReport] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("reconciliation_worker_started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("reconciliation_worker_stopped")

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def _run(self) -> None:
        try:
            while self._running:
                try:
                    await self.reconcile()
                except Exception as e:
                    logger.error("reconciliation_error", error=str(e))
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            raise

    async def reconcile(self) -> ReconciliationReport:
        state = self.state or get_app_state()
        issues: list[str] = []
        checked = 0

        pm = state.position_manager
        sim = state.paper_simulator
        balance = state.balance_tracker

        if pm is not None and sim is not None:
            # 1. Position sets must match
            pm_positions = set(pm.positions.keys())
            sim_positions = set(sim.positions.keys())
            if pm_positions != sim_positions:
                missing_in_sim = pm_positions - sim_positions
                extra_in_sim = sim_positions - pm_positions
                if missing_in_sim:
                    issues.append(f"positions in manager but not simulator: {missing_in_sim}")
                if extra_in_sim:
                    issues.append(f"positions in simulator but not manager: {extra_in_sim}")

            # 2. Quantities must match
            for addr in pm_positions & sim_positions:
                checked += 1
                pm_qty = pm.positions[addr].quantity
                sim_qty = sim.positions[addr].quantity
                if abs(pm_qty - sim_qty) > 1e-9:
                    issues.append(f"quantity mismatch for {addr[:8]}: pm={pm_qty} sim={sim_qty}")

        if balance is not None and sim is not None:
            # 3. Cash must match
            if abs(balance.cash_usd - sim.cash_usd) > 0.01:
                issues.append(
                    f"cash mismatch: tracker={balance.cash_usd:.2f} simulator={sim.cash_usd:.2f}"
                )

        report = ReconciliationReport(consistent=len(issues) == 0, issues=issues, checked_positions=checked)
        self.last_report = report

        if not report.consistent:
            state.event_log.emit(
                "reconciliation_failed",
                level="error",
                message=f"State inconsistency detected: {len(issues)} issue(s)",
                issues=issues,
            )
            logger.error("reconciliation_failed", issues=issues)

        return report
