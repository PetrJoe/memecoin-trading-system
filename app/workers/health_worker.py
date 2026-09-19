from __future__ import annotations

import asyncio
import time
from typing import Optional

from app.api.state import get_app_state
from app.config import get_logger, get_settings
from app.monitoring.health import HealthChecker
from app.monitoring.metrics import MetricsCollector

logger = get_logger(category="application")

CHECK_INTERVAL_SECONDS = 60.0


class HealthWorker:
    """Runs dependency + resource checks periodically; emits warnings to the event feed."""

    def __init__(self, interval: float = CHECK_INTERVAL_SECONDS) -> None:
        self.settings = get_settings()
        self.interval = interval
        self.checker = HealthChecker()
        self.collector = MetricsCollector()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.last_overall: str = "unknown"
        self.last_checks: list = []
        self.last_metrics = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("health_worker_started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.checker.close()
        logger.info("health_worker_stopped")

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def _run(self) -> None:
        try:
            while self._running:
                try:
                    await self.run_checks()
                except Exception as e:
                    logger.error("health_worker_error", error=str(e))
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            raise

    async def run_checks(self) -> str:
        """One round of checks; returns overall status."""
        state = get_app_state()

        self.last_checks = await self.checker.check_all()
        self.last_overall = self.checker.aggregate(self.last_checks)

        self.last_metrics = self.collector.collect()
        threshold_warnings = self.collector.check_thresholds(self.last_metrics)

        # Emit warnings for degraded/error dependencies (cooldown handled by level)
        for check in self.last_checks:
            if check.status in ("degraded", "error"):
                state.event_log.emit(
                    "dependency_degraded",
                    level="warning" if check.status == "degraded" else "error",
                    message=f"{check.name}: {check.status} {check.detail}".strip(),
                    dependency=check.name,
                    latency_ms=check.latency_ms,
                )

        for warning in threshold_warnings:
            state.event_log.emit(
                "resource_warning", level="warning", message=warning
            )

        return self.last_overall
