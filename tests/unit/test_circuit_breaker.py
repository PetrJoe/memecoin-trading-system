import pytest

from app.risk.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerEvent,
    CircuitBreakerReason,
    CircuitBreakerState,
)


class TestCircuitBreakerInitialState:
    def test_starts_normal(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitBreakerState.NORMAL

    def test_can_trade_initially(self):
        cb = CircuitBreaker()
        assert cb.can_trade is True

    def test_is_normal_initially(self):
        cb = CircuitBreaker()
        assert cb.is_normal is True

    def test_not_paused_initially(self):
        cb = CircuitBreaker()
        assert cb.is_paused is False


class TestCircuitBreakerTransitions:
    def test_execution_failures_triggers_pause(self):
        cb = CircuitBreaker()
        for _ in range(5):
            cb.record_execution_failure()
        assert cb.state == CircuitBreakerState.PAUSED
        assert cb.can_trade is False

    def test_rpc_failures_triggers_pause(self):
        cb = CircuitBreaker()
        for _ in range(3):
            cb.record_rpc_failure()
        assert cb.state == CircuitBreakerState.PAUSED

    def test_jupiter_unavailable_triggers_pause(self):
        cb = CircuitBreaker()
        for _ in range(3):
            cb.record_jupiter_unavailable()
        assert cb.state == CircuitBreakerState.PAUSED

    def test_database_unavailable_triggers_pause(self):
        cb = CircuitBreaker()
        cb.record_database_unavailable()
        assert cb.state == CircuitBreakerState.PAUSED

    def test_daily_loss_exceeded_triggers_pause(self):
        cb = CircuitBreaker()
        cb.record_daily_loss_exceeded(1.50, 1.00)
        assert cb.state == CircuitBreakerState.PAUSED

    def test_consecutive_losses_triggers_pause(self):
        cb = CircuitBreaker()
        cb.record_consecutive_losses(5)
        assert cb.state == CircuitBreakerState.PAUSED

    def test_abnormal_slippage_triggers_warning(self):
        cb = CircuitBreaker()
        cb.record_abnormal_slippage(500)
        assert cb.state == CircuitBreakerState.WARNING

    def test_wallet_balance_low_triggers_pause(self):
        cb = CircuitBreaker()
        cb.record_wallet_balance_low(0.005)
        assert cb.state == CircuitBreakerState.PAUSED

    def test_unknown_tx_state_triggers_warning_after_2(self):
        cb = CircuitBreaker()
        cb.record_unknown_tx_state()
        assert cb.state == CircuitBreakerState.NORMAL
        cb.record_unknown_tx_state()
        assert cb.state == CircuitBreakerState.WARNING

    def test_manual_pause(self):
        cb = CircuitBreaker()
        cb.manual_pause("Testing pause")
        assert cb.state == CircuitBreakerState.PAUSED

    def test_emergency(self):
        cb = CircuitBreaker()
        cb.emergency("Emergency test")
        assert cb.state == CircuitBreakerState.EMERGENCY
        assert cb.is_paused is True


class TestCircuitBreakerResume:
    def test_resume_from_paused(self):
        cb = CircuitBreaker()
        cb.manual_pause()
        cb.resume()
        assert cb.state == CircuitBreakerState.NORMAL
        assert cb.can_trade is True

    def test_resume_from_emergency(self):
        cb = CircuitBreaker()
        cb.emergency()
        cb.resume()
        assert cb.state == CircuitBreakerState.NORMAL

    def test_resume_clears_trigger_counts(self):
        cb = CircuitBreaker()
        cb.record_execution_failure()
        cb.record_execution_failure()
        cb.manual_pause()
        cb.resume()
        assert cb._trigger_counts == {}

    def test_success_clears_warning(self):
        cb = CircuitBreaker()
        cb.record_abnormal_slippage(500)
        assert cb.state == CircuitBreakerState.WARNING
        cb.record_success()
        assert cb.state == CircuitBreakerState.NORMAL


class TestCircuitBreakerEvents:
    def test_events_recorded(self):
        cb = CircuitBreaker()
        cb.manual_pause("Test 1")
        cb.emergency("Test 2")
        cb.resume()
        assert len(cb.events) == 3
        assert cb.events[0].state == CircuitBreakerState.PAUSED
        assert cb.events[0].reason == CircuitBreakerReason.MANUAL_PAUSE
        assert cb.events[1].state == CircuitBreakerState.EMERGENCY
        assert cb.events[2].state == CircuitBreakerState.NORMAL

    def test_same_state_no_event(self):
        cb = CircuitBreaker()
        cb.record_success()
        assert len(cb.events) == 0


class TestCircuitBreakerDoesNotDoublePause:
    def test_same_state_no_transition(self):
        cb = CircuitBreaker()
        cb.manual_pause()
        cb.manual_pause("Again")
        assert len(cb.events) == 1
