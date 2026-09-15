from datetime import date

import pytest

from app.database.models import (
    DailyStats,
    EventLevel,
    ExitReason,
    OrderSide,
    OrderStatus,
    PositionStatus,
    SignalType,
    TokenStatus,
    TradeStatus,
)


class TestTokenStatus:
    def test_lifecycle_states(self):
        assert TokenStatus.DISCOVERED.value == "DISCOVERED"
        assert TokenStatus.WATCHING.value == "WATCHING"
        assert TokenStatus.ANALYZING.value == "ANALYZING"
        assert TokenStatus.APPROVED.value == "APPROVED"
        assert TokenStatus.TRADED.value == "TRADED"
        assert TokenStatus.REJECTED.value == "REJECTED"

    def test_lifecycle_order(self):
        states = [
            TokenStatus.DISCOVERED,
            TokenStatus.WATCHING,
            TokenStatus.ANALYZING,
            TokenStatus.APPROVED,
            TokenStatus.TRADED,
        ]
        for i in range(len(states) - 1):
            assert states[i].value != states[i + 1].value


class TestOrderSide:
    def test_buy_sell(self):
        assert OrderSide.BUY.value == "BUY"
        assert OrderSide.SELL.value == "SELL"


class TestOrderStatus:
    def test_statuses(self):
        assert OrderStatus.PENDING.value == "PENDING"
        assert OrderStatus.SUBMITTED.value == "SUBMITTED"
        assert OrderStatus.CONFIRMED.value == "CONFIRMED"
        assert OrderStatus.FAILED.value == "FAILED"
        assert OrderStatus.CANCELLED.value == "CANCELLED"


class TestTradeStatus:
    def test_statuses(self):
        assert TradeStatus.PENDING.value == "PENDING"
        assert TradeStatus.CONFIRMED.value == "CONFIRMED"
        assert TradeStatus.FAILED.value == "FAILED"


class TestPositionStatus:
    def test_statuses(self):
        assert PositionStatus.OPEN.value == "OPEN"
        assert PositionStatus.CLOSED.value == "CLOSED"


class TestExitReason:
    def test_reasons(self):
        assert ExitReason.TAKE_PROFIT.value == "TAKE_PROFIT"
        assert ExitReason.STOP_LOSS.value == "STOP_LOSS"
        assert ExitReason.TRAILING_STOP.value == "TRAILING_STOP"
        assert ExitReason.TIME_LIMIT.value == "TIME_LIMIT"
        assert ExitReason.EMERGENCY.value == "EMERGENCY"
        assert ExitReason.MANUAL.value == "MANUAL"
        assert ExitReason.RISK_EVENT.value == "RISK_EVENT"


class TestSignalType:
    def test_signals(self):
        assert SignalType.BUY.value == "BUY"
        assert SignalType.SELL.value == "SELL"
        assert SignalType.HOLD.value == "HOLD"
        assert SignalType.WATCH.value == "WATCH"
        assert SignalType.REJECT.value == "REJECT"


class TestEventLevel:
    def test_levels(self):
        assert EventLevel.DEBUG.value == "DEBUG"
        assert EventLevel.INFO.value == "INFO"
        assert EventLevel.WARNING.value == "WARNING"
        assert EventLevel.ERROR.value == "ERROR"
        assert EventLevel.CRITICAL.value == "CRITICAL"
