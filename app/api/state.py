from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from app.scanner.models import MarketSnapshot


@dataclass
class WebEvent:
    """Alert record displayed in the web UI (replaces Telegram push alerts)."""
    event_type: str
    level: str = "info"  # info | warning | error
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class EventLog:
    """
    In-memory ring buffer of bot events for the dashboard.
    The orchestrator's notifier writes here; the web UI polls it.
    """

    def __init__(self, max_events: int = 500) -> None:
        self._events: deque[WebEvent] = deque(maxlen=max_events)
        self._seq = 0

    def emit(self, event_type: str, level: str = "info", message: str = "", **data) -> WebEvent:
        self._seq += 1
        event = WebEvent(
            event_type=event_type,
            level=level,
            message=message or event_type,
            data=data,
            timestamp=time.time(),
        )
        self._events.append(event)
        return event

    def since(self, last_seq: int = 0) -> tuple[list[WebEvent], int]:
        """Return events newer than last_seq plus the current sequence number."""
        events = [e for e in self._events if e.timestamp > 0]
        # seq is monotonic via list position; use index-based filtering
        start = max(0, len(self._events) - _count_newer(self._events, last_seq))
        return list(self._events)[start:], self._seq

    def recent(self, limit: int = 100) -> list[WebEvent]:
        events = list(self._events)
        events.reverse()
        return events[:limit]

    def clear(self) -> None:
        self._events.clear()


def _count_newer(events: deque[WebEvent], since_ts: float) -> int:
    return sum(1 for e in events if e.timestamp > since_ts)


class AppState:
    """
    Process-wide registry the API reads from. Workers/orchestrator register
    their live components here at startup; endpoints never construct services.
    """

    def __init__(self) -> None:
        self.started_at: float = time.time()
        self.orchestrator = None       # TradeOrchestrator
        self.position_manager = None   # PositionManager
        self.balance_tracker = None    # BalanceTracker
        self.pnl_calculator = None     # PnLCalculator
        self.circuit_breaker = None    # CircuitBreaker
        self.paper_simulator = None    # PaperFillSimulator (paper mode)
        self.event_log = EventLog()
        self.prices: dict[str, float] = {}      # token -> latest price
        self.last_scan_at: float = 0.0
        self.scans_completed: int = 0
        self.mode: str = "paper"
        self.trading_enabled: bool = False

        # Trading loop runtime state (DB-free paper mode)
        self.latest_snapshots: dict[str, MarketSnapshot] = {}   # token -> newest snapshot
        self.watchlist: dict[str, float] = {}                   # token -> discovery time
        self.open_signals: dict[str, dict] = {}                 # token -> last signal summary
        self.loop_errors: deque = deque(maxlen=20)
        self.last_loop_error: str = ""

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.started_at

    def reset(self) -> None:
        """Test helper."""
        self.__init__()


# Process-wide singleton
_state: Optional[AppState] = None


def get_app_state() -> AppState:
    global _state
    if _state is None:
        _state = AppState()
    return _state


def set_app_state(state: AppState) -> None:
    global _state
    _state = state
