from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Optional

from app.config import get_logger, get_settings

logger = get_logger(category="application")


class CircuitBreakerState(str, enum.Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    PAUSED = "PAUSED"
    EMERGENCY = "EMERGENCY"


class CircuitBreakerReason(str, enum.Enum):
    DAILY_LOSS_EXCEEDED = "DAILY_LOSS_EXCEEDED"
    CONSECUTIVELOSSES = "CONSECUTIVE_LOSSES"
    EXECUTION_FAILURES = "EXECUTION_FAILURES"
    RPC_FAILURES = "RPC_FAILURES"
    JUPITER_UNAVAILABLE = "JUPITER_UNAVAILABLE"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    ABNORMAL_SLIPPAGE = "ABNORMAL_SLIPPAGE"
    WALLET_BALANCE_LOW = "WALLET_BALANCE_LOW"
    UNKNOWN_TX_STATE = "UNKNOWN_TX_STATE"
    MANUAL_PAUSE = "MANUAL_PAUSE"
    EMERGENCY_MODE = "EMERGENCY_MODE"


@dataclass
class CircuitBreakerEvent:
    state: CircuitBreakerState
    reason: CircuitBreakerReason
    message: str
    timestamp: float = field(default_factory=time.time)


class CircuitBreaker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._state = CircuitBreakerState.NORMAL
        self._events: list[CircuitBreakerEvent] = []
        self._trigger_counts: dict[str, int] = {}
        self._last_state_change = time.time()

    @property
    def state(self) -> CircuitBreakerState:
        return self._state

    @property
    def is_normal(self) -> bool:
        return self._state == CircuitBreakerState.NORMAL

    @property
    def is_paused(self) -> bool:
        return self._state in (CircuitBreakerState.PAUSED, CircuitBreakerState.EMERGENCY)

    @property
    def can_trade(self) -> bool:
        return self._state == CircuitBreakerState.NORMAL

    @property
    def events(self) -> list[CircuitBreakerEvent]:
        return list(self._events)

    def record_execution_failure(self) -> None:
        self._increment("execution_failures")
        count = self._trigger_counts.get("execution_failures", 0)
        if count >= 5:
            self._transition(CircuitBreakerState.PAUSED, CircuitBreakerReason.EXECUTION_FAILURES,
                           f"Too many execution failures: {count}")

    def record_rpc_failure(self) -> None:
        self._increment("rpc_failures")
        count = self._trigger_counts.get("rpc_failures", 0)
        if count >= 3:
            self._transition(CircuitBreakerState.PAUSED, CircuitBreakerReason.RPC_FAILURES,
                           f"Too many RPC failures: {count}")

    def record_jupiter_unavailable(self) -> None:
        self._increment("jupiter_failures")
        count = self._trigger_counts.get("jupiter_failures", 0)
        if count >= 3:
            self._transition(CircuitBreakerState.PAUSED, CircuitBreakerReason.JUPITER_UNAVAILABLE,
                           f"Jupiter unavailable: {count} failures")

    def record_database_unavailable(self) -> None:
        self._transition(CircuitBreakerState.PAUSED, CircuitBreakerReason.DATABASE_UNAVAILABLE,
                        "Database connection lost")

    def record_daily_loss_exceeded(self, loss: float, max_loss: float) -> None:
        self._transition(CircuitBreakerState.PAUSED, CircuitBreakerReason.DAILY_LOSS_EXCEEDED,
                        f"Daily loss ${loss:.2f} exceeded limit ${max_loss:.2f}")

    def record_consecutive_losses(self, count: int) -> None:
        if count >= self.settings.MAX_CONSECUTIVE_LOSSES:
            self._transition(CircuitBreakerState.PAUSED, CircuitBreakerReason.CONSECUTIVELOSSES,
                           f"Consecutive losses: {count}")

    def record_abnormal_slippage(self, slippage_bps: int) -> None:
        if slippage_bps > self.settings.MAX_SLIPPAGE_BPS * 3:
            self._transition(CircuitBreakerState.WARNING, CircuitBreakerReason.ABNORMAL_SLIPPAGE,
                           f"Abnormal slippage: {slippage_bps}bps")

    def record_wallet_balance_low(self, balance: float) -> None:
        if balance < 0.01:
            self._transition(CircuitBreakerState.PAUSED, CircuitBreakerReason.WALLET_BALANCE_LOW,
                           f"Wallet balance critically low: {balance:.6f} SOL")

    def record_unknown_tx_state(self) -> None:
        self._increment("unknown_tx_count")
        count = self._trigger_counts.get("unknown_tx_count", 0)
        if count >= 2:
            self._transition(CircuitBreakerState.WARNING, CircuitBreakerReason.UNKNOWN_TX_STATE,
                           f"Multiple unknown transaction states: {count}")

    def manual_pause(self, reason: str = "Manual pause") -> None:
        self._transition(CircuitBreakerState.PAUSED, CircuitBreakerReason.MANUAL_PAUSE, reason)

    def emergency(self, reason: str = "Emergency mode") -> None:
        self._transition(CircuitBreakerState.EMERGENCY, CircuitBreakerReason.EMERGENCY_MODE, reason)

    def resume(self) -> None:
        if self._state != CircuitBreakerState.NORMAL:
            old_state = self._state
            self._state = CircuitBreakerState.NORMAL
            self._last_state_change = time.time()
            self._trigger_counts.clear()
            event = CircuitBreakerEvent(
                state=CircuitBreakerState.NORMAL,
                reason=CircuitBreakerReason.MANUAL_PAUSE,
                message=f"Resumed from {old_state.value}",
            )
            self._events.append(event)
            logger.info("circuit_breaker_resume", previous_state=old_state.value)

    def record_success(self) -> None:
        if self._state == CircuitBreakerState.WARNING:
            self._trigger_counts.clear()
            self._state = CircuitBreakerState.NORMAL
            self._last_state_change = time.time()

    def _increment(self, key: str) -> None:
        self._trigger_counts[key] = self._trigger_counts.get(key, 0) + 1

    def _transition(
        self,
        new_state: CircuitBreakerState,
        reason: CircuitBreakerReason,
        message: str,
    ) -> None:
        if new_state == self._state:
            return

        old_state = self._state
        self._state = new_state
        self._last_state_change = time.time()

        event = CircuitBreakerEvent(
            state=new_state,
            reason=reason,
            message=message,
        )
        self._events.append(event)

        logger.warning(
            "circuit_breaker_transition",
            from_state=old_state.value,
            to_state=new_state.value,
            reason=reason.value,
            message=message,
        )
