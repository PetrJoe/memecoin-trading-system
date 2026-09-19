import time

import pytest

from app.portfolio.positions import PositionManager


@pytest.fixture
def manager():
    return PositionManager()


def open_position(manager, entry_price=1.0, capital=10.0, **kwargs):
    return manager.open_position(
        position_id=1,
        token_address="TOKEN1",
        symbol="TKN",
        entry_price=entry_price,
        quantity=capital / entry_price,
        capital_usd=capital,
        **kwargs,
    )


class TestOpenClose:
    def test_open_creates_position_with_configured_exits(self, manager):
        pos = open_position(manager, entry_price=1.0, stop_loss_percent=10.0, take_profit_percent=25.0)
        assert manager.has_position("TOKEN1")
        assert pos.stop_loss == pytest.approx(0.9)
        assert pos.take_profit == pytest.approx(1.25)
        assert pos.highest_price == 1.0

    def test_defaults_from_settings(self, manager):
        pos = open_position(manager)
        assert pos.stop_loss == pytest.approx(0.9)   # STOP_LOSS_PERCENT=10
        assert pos.take_profit == pytest.approx(1.25)  # TAKE_PROFIT_PERCENT=25

    def test_open_duplicate_replaces(self, manager):
        open_position(manager)
        open_position(manager, entry_price=2.0)
        assert manager.get("TOKEN1").entry_price == 2.0

    def test_close_removes_position(self, manager):
        open_position(manager)
        closed = manager.close_position("TOKEN1")
        assert closed is not None
        assert not manager.has_position("TOKEN1")
        assert manager.close_position("TOKEN1") is None

    def test_open_count(self, manager):
        assert manager.open_count() == 0
        open_position(manager)
        assert manager.open_count() == 1

    def test_max_duration_from_settings(self, manager):
        pos = open_position(manager)
        assert pos.max_duration_hours == 24.0


class TestStopLoss:
    def test_triggers_below_stop(self, manager):
        open_position(manager, entry_price=1.0)
        decision = manager.update_price("TOKEN1", 0.89)
        assert decision.should_exit
        assert decision.reason == "STOP_LOSS"

    def test_no_trigger_above_stop(self, manager):
        open_position(manager, entry_price=1.0)
        decision = manager.update_price("TOKEN1", 0.95)
        assert not decision.should_exit

    def test_exact_stop_triggers(self, manager):
        open_position(manager, entry_price=1.0)
        decision = manager.update_price("TOKEN1", 0.90)
        assert decision.should_exit


class TestTakeProfit:
    def test_triggers_above_target(self, manager):
        open_position(manager, entry_price=1.0)
        decision = manager.update_price("TOKEN1", 1.26)
        assert decision.should_exit
        assert decision.reason == "TAKE_PROFIT"

    def test_no_trigger_below_target(self, manager):
        open_position(manager, entry_price=1.0)
        decision = manager.update_price("TOKEN1", 1.10)
        assert not decision.should_exit


class TestTrailingStop:
    def test_no_trigger_when_disabled(self, manager):
        # 0 disables the exit entirely (None means "use settings default")
        open_position(manager, stop_loss_percent=0, take_profit_percent=0)
        decision = manager.update_price("TOKEN1", 0.5)
        assert not decision.should_exit

    def test_triggers_after_pullback_from_high(self, manager):
        open_position(manager, entry_price=1.0, stop_loss_percent=0,
                      take_profit_percent=0, trailing_stop_percent=15.0)
        manager.update_price("TOKEN1", 2.0)   # high water mark
        decision = manager.update_price("TOKEN1", 1.68)  # 16% below high
        assert decision.should_exit
        assert decision.reason == "TRAILING_STOP"

    def test_no_trigger_within_tolerance(self, manager):
        open_position(manager, entry_price=1.0, stop_loss_percent=0,
                      take_profit_percent=0, trailing_stop_percent=15.0)
        manager.update_price("TOKEN1", 2.0)
        decision = manager.update_price("TOKEN1", 1.80)  # 10% below high
        assert not decision.should_exit

    def test_high_water_mark_ratchets(self, manager):
        open_position(manager, entry_price=1.0, stop_loss_percent=0,
                      take_profit_percent=0, trailing_stop_percent=15.0)
        manager.update_price("TOKEN1", 2.0)
        manager.update_price("TOKEN1", 1.9)   # pullback, high stays 2.0
        manager.update_price("TOKEN1", 2.5)   # new high
        assert manager.get("TOKEN1").highest_price == 2.5


class TestTimeLimit:
    def test_triggers_after_max_duration(self, manager):
        pos = open_position(manager)
        pos.opened_at = time.time() - 25 * 3600  # 25h ago
        decision = manager.update_price("TOKEN1", 1.0)
        assert decision.should_exit
        assert decision.reason == "TIME_LIMIT"

    def test_no_trigger_within_duration(self, manager):
        open_position(manager)
        decision = manager.update_price("TOKEN1", 1.0)
        assert not decision.should_exit


class TestPriority:
    def test_stop_loss_wins_over_take_profit(self, manager):
        open_position(manager, entry_price=1.0)
        # Impossible in practice, but SL must be checked first
        pos = manager.get("TOKEN1")
        pos.stop_loss = 0.99
        pos.take_profit = 0.98
        decision = manager.update_price("TOKEN1", 0.985)
        assert decision.reason == "STOP_LOSS"


class TestAggregation:
    def test_total_exposure_and_unrealized(self, manager):
        open_position(manager, entry_price=1.0, capital=10.0)
        prices = {"TOKEN1": 1.5}
        assert manager.total_exposure(prices) == pytest.approx(15.0)
        expected_pnl = (1.5 - manager.get("TOKEN1").entry_price) * 10.0
        assert manager.total_unrealized_pnl(prices) == pytest.approx(expected_pnl)

    def test_update_price_unknown_token(self, manager):
        assert manager.update_price("UNKNOWN", 1.0) is None

    def test_invalid_price_ignored(self, manager):
        open_position(manager)
        decision = manager.update_price("TOKEN1", 0.0)
        assert not decision.should_exit
        assert manager.get("TOKEN1").highest_price == 1.0
