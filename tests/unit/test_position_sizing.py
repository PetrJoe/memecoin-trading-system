import pytest

from app.risk.position_sizing import PositionSizer


class TestPositionSizer:
    def test_basic_calculation(self, patched_env):
        sizer = PositionSizer()
        size = sizer.calculate(
            wallet_balance_usd=100.0,
            risk_score=80,
            open_positions=0,
            total_exposure_usd=0.0,
            daily_loss_usd=0.0,
        )
        assert size > 0
        assert size <= 0.50

    def test_zero_balance_returns_zero(self, patched_env):
        sizer = PositionSizer()
        size = sizer.calculate(
            wallet_balance_usd=0.0,
            risk_score=80,
            open_positions=0,
            total_exposure_usd=0.0,
            daily_loss_usd=0.0,
        )
        assert size == 0.0

    def test_max_positions_reached(self, patched_env):
        sizer = PositionSizer()
        size = sizer.calculate(
            wallet_balance_usd=100.0,
            risk_score=80,
            open_positions=2,
            total_exposure_usd=0.50,
            daily_loss_usd=0.0,
        )
        assert size == 0.0

    def test_daily_loss_exceeded(self, patched_env):
        sizer = PositionSizer()
        size = sizer.calculate(
            wallet_balance_usd=100.0,
            risk_score=80,
            open_positions=0,
            total_exposure_usd=0.0,
            daily_loss_usd=1.50,
        )
        assert size == 0.0

    def test_max_exposure_reached(self, patched_env):
        sizer = PositionSizer()
        size = sizer.calculate(
            wallet_balance_usd=100.0,
            risk_score=80,
            open_positions=1,
            total_exposure_usd=5.00,
            daily_loss_usd=0.0,
        )
        assert size == 0.0

    def test_low_risk_score_reduces_size(self, patched_env):
        sizer = PositionSizer()
        size_high = sizer.calculate(
            wallet_balance_usd=100.0,
            risk_score=90,
            open_positions=0,
            total_exposure_usd=0.0,
            daily_loss_usd=0.0,
        )
        size_low = sizer.calculate(
            wallet_balance_usd=100.0,
            risk_score=50,
            open_positions=0,
            total_exposure_usd=0.0,
            daily_loss_usd=0.0,
        )
        assert size_high > size_low

    def test_confidence_reduces_size(self, patched_env):
        sizer = PositionSizer()
        size_high = sizer.calculate(
            wallet_balance_usd=100.0,
            risk_score=80,
            open_positions=0,
            total_exposure_usd=0.0,
            daily_loss_usd=0.0,
            strategy_confidence=1.0,
        )
        size_low = sizer.calculate(
            wallet_balance_usd=100.0,
            risk_score=80,
            open_positions=0,
            total_exposure_usd=0.0,
            daily_loss_usd=0.0,
            strategy_confidence=0.5,
        )
        assert size_high > size_low

    def test_does_not_exceed_max_position(self, patched_env):
        sizer = PositionSizer()
        size = sizer.calculate(
            wallet_balance_usd=1000.0,
            risk_score=100,
            open_positions=0,
            total_exposure_usd=0.0,
            daily_loss_usd=0.0,
            strategy_confidence=1.0,
        )
        assert size <= 0.50

    def test_size_is_rounded(self, patched_env):
        sizer = PositionSizer()
        size = sizer.calculate(
            wallet_balance_usd=100.0,
            risk_score=73,
            open_positions=0,
            total_exposure_usd=0.0,
            daily_loss_usd=0.0,
        )
        assert size == round(size, 2)
