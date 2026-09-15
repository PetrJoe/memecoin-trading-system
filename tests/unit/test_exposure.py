import pytest

from app.risk.exposure import ExposureTracker


class TestExposureTracker:
    def test_initial_state(self):
        et = ExposureTracker()
        assert et.total_exposure == 0.0
        assert et.position_count == 0

    def test_add_position(self):
        et = ExposureTracker()
        et.add_position(1, 10.0)
        assert et.total_exposure == 10.0
        assert et.position_count == 1

    def test_add_multiple_positions(self):
        et = ExposureTracker()
        et.add_position(1, 10.0)
        et.add_position(2, 20.0)
        assert et.total_exposure == 30.0
        assert et.position_count == 2

    def test_remove_position(self):
        et = ExposureTracker()
        et.add_position(1, 10.0)
        et.remove_position(1)
        assert et.total_exposure == 0.0
        assert et.position_count == 0

    def test_remove_nonexistent_returns_none(self):
        et = ExposureTracker()
        result = et.remove_position(999)
        assert result is None

    def test_update_position(self):
        et = ExposureTracker()
        et.add_position(1, 10.0)
        et.update_position(1, 25.0)
        assert et.total_exposure == 25.0

    def test_exposure_pct(self):
        et = ExposureTracker()
        et.add_position(1, 50.0)
        assert et.get_exposure_pct(200.0) == 25.0

    def test_exposure_pct_zero_balance(self):
        et = ExposureTracker()
        et.add_position(1, 50.0)
        assert et.get_exposure_pct(0.0) == 0.0

    def test_can_open_position_within_limits(self):
        et = ExposureTracker()
        assert et.can_open_position(100.0, 50.0, 2) is True

    def test_can_open_position_max_positions(self):
        et = ExposureTracker()
        et.add_position(1, 10.0)
        et.add_position(2, 10.0)
        assert et.can_open_position(100.0, 50.0, 2) is False

    def test_can_open_position_max_exposure(self):
        et = ExposureTracker()
        et.add_position(1, 50.0)
        assert et.can_open_position(100.0, 50.0, 5) is False

    def test_reset(self):
        et = ExposureTracker()
        et.add_position(1, 10.0)
        et.add_position(2, 20.0)
        et.reset()
        assert et.total_exposure == 0.0
        assert et.position_count == 0
