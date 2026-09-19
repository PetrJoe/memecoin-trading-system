from __future__ import annotations

import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

from app.config import get_logger, get_settings

logger = get_logger(category="application")


@dataclass
class ResourceMetrics:
    cpu_percent: float = 0.0
    memory_rss_mb: float = 0.0
    memory_percent: float = 0.0
    threads: int = 0
    open_files: int = 0
    disk_used_percent: float = 0.0
    disk_free_mb: float = 0.0
    uptime_seconds: float = 0.0
    collected_at: float = field(default_factory=time.time)


class MetricsCollector:
    """
    Collects lightweight operational metrics from the OS.
    Uses the stdlib where possible; psutil is optional (graceful degradation).
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._process = None
        try:
            import psutil  # optional dependency

            self._process = psutil.Process()
        except ImportError:
            logger.warning("psutil_not_installed", hint="pip install psutil for full metrics")

    def collect(self) -> ResourceMetrics:
        metrics = ResourceMetrics()
        metrics.uptime_seconds = time.time() - _BOOT_TIME

        if self._process is not None:
            try:
                with self._process.oneshot():
                    metrics.cpu_percent = self._process.cpu_percent(interval=0.0)
                    mem = self._process.memory_full_info()
                    metrics.memory_rss_mb = mem.rss / (1024 * 1024)
                    metrics.memory_percent = self._process.memory_percent()
                    metrics.threads = self._process.num_threads()
                    try:
                        metrics.open_files = self._process.num_fds()
                    except (AttributeError, PermissionError):
                        metrics.open_files = 0
            except Exception as e:
                logger.warning("metrics_process_error", error=str(e))

        metrics.disk_used_percent, metrics.disk_free_mb = self._disk_usage()
        return metrics

    def _disk_usage(self) -> tuple[float, float]:
        try:
            usage = shutil.disk_usage(_project_root())
            used_pct = usage.used / usage.total * 100.0
            free_mb = usage.free / (1024 * 1024)
            return round(used_pct, 1), round(free_mb, 1)
        except Exception:
            return 0.0, 0.0

    def check_thresholds(self, m: ResourceMetrics) -> list[str]:
        """Return warning messages when usage exceeds configured thresholds."""
        warnings: list[str] = []
        if m.disk_used_percent >= self.settings.DISK_USAGE_WARN_PCT:
            warnings.append(
                f"Disk usage {m.disk_used_percent:.0f}% >= {self.settings.DISK_USAGE_WARN_PCT}%"
            )
        if m.memory_percent >= self.settings.MEM_USAGE_WARN_PCT:
            warnings.append(
                f"Memory usage {m.memory_percent:.0f}% >= {self.settings.MEM_USAGE_WARN_PCT}%"
            )
        for w in warnings:
            logger.warning("resource_threshold_exceeded", warning=w)
        return warnings


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _boot_time() -> float:
    try:
        import psutil

        return psutil.boot_time()
    except ImportError:
        return time.time() - _PROCESS_START_FALLBACK


# Fallback: process start approximates boot time if psutil missing
import time as _time

_PROCESS_START_FALLBACK = 0.0
_BOOT_TIME = _boot_time()
