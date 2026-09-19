import time

import pytest

from app.portfolio.balances import BalanceTracker
from app.portfolio.pnl import ClosedTrade, PnLCalculator


class TestBalanceTracker:
    def test_initial_state(self):
        tracker = BalanceTracker(starting_balance_usd=100.0)
        assert tracker.cash_usd == 100.0
        assert tracker.total_equity == 100.0
        assert tracker.total_pnl == 0.0

    def test_buy_reduces_cash(self):
        tracker = BalanceTracker(starting_balance_usd=100.0)
        tracker.record_buy(amount_usd=10.0, fee_usd=0.025)
        assert tracker.cash_usd == pytest.approx(90.0)
        assert tracker.total_fees_usd == pytest.approx(0.025)

    def test_sell_restores_cash_and_pnl(self):
        tracker = BalanceTracker(starting_balance_usd=100.0)
        tracker.record_buy(amount_usd=10.0, fee_usd=0.025)
        tracker.record_sell(proceeds_usd=12.0, fee_usd=0.03, realized_pnl_usd=1.945)
        assert tracker.cash_usd == pytest.approx(102.0)
        assert tracker.realized_pnl == pytest.approx(1.945)
        assert tracker.total_fees_usd == pytest.approx(0.055)

    def test_position_value_mark_to_market(self):
        tracker = BalanceTracker(starting_balance_usd=100.0)
        tracker.record_buy(amount_usd=10.0, fee_usd=0.0)
        tracker.update_position_value(12.0)
        assert tracker.total_equity == pytest.approx(102.0)
        assert tracker.total_pnl == pytest.approx(2.0)

    def test_unrealized_pnl(self):
        tracker = BalanceTracker(starting_balance_usd=100.0)
        tracker.record_buy(amount_usd=10.0, fee_usd=0.0)
        tracker.record_sell(proceeds_usd=11.0, fee_usd=0.0, realized_pnl_usd=1.0)
        tracker.record_buy(amount_usd=10.0, fee_usd=0.0)
        tracker.update_position_value(12.0)
        # cash 100 - 10 + 11 - 10 = 91, equity 91 + 12 = 103
        # total_pnl 3 - realized 1 = 2 unrealized
        assert tracker.unrealized_pnl == pytest.approx(2.0)

    def test_pnl_pct(self):
        tracker = BalanceTracker(starting_balance_usd=100.0)
        tracker.record_buy(amount_usd=100.0, fee_usd=0.0)
        tracker.record_sell(proceeds_usd=110.0, fee_usd=0.0, realized_pnl_usd=10.0)
        assert tracker.total_pnl_pct == pytest.approx(10.0)

    def test_snapshot(self):
        tracker = BalanceTracker(starting_balance_usd=100.0)
        tracker.record_buy(amount_usd=10.0, fee_usd=0.0)
        tracker.update_position_value(5.0)
        snap = tracker.snapshot()
        assert snap.cash_usd == pytest.approx(90.0)
        assert snap.position_value_usd == pytest.approx(5.0)
        assert snap.total_usd == pytest.approx(95.0)

    def test_reset(self):
        tracker = BalanceTracker(starting_balance_usd=100.0)
        tracker.record_buy(amount_usd=50.0, fee_usd=1.0)
        tracker.reset()
        assert tracker.cash_usd == 100.0
        assert tracker.realized_pnl == 0.0

    def test_negative_position_value_clamped(self):
        tracker = BalanceTracker(starting_balance_usd=100.0)
        tracker.update_position_value(-5.0)
        assert tracker.position_value_usd == 0.0


def make_trade(pnl, symbol="TKN", fees=0.01, exit_time=None, entry_time=0.0):
    return ClosedTrade(
        symbol=symbol,
        capital_usd=10.0,
        proceeds_usd=10.0 + pnl,
        fees_usd=fees,
        pnl_usd=pnl,
        pnl_pct=pnl / 10.0 * 100,
        exit_time=exit_time if exit_time is not None else time.time(),
        entry_time=entry_time,
    )


class TestPnLCalculator:
    def test_empty_summary(self):
        calc = PnLCalculator()
        s = calc.summary()
        assert s.total_trades == 0
        assert s.win_rate == 0.0
        assert s.profit_factor == 0.0

    def test_win_loss_counts(self):
        calc = PnLCalculator()
        calc.record_trade(make_trade(2.0))
        calc.record_trade(make_trade(-1.0))
        calc.record_trade(make_trade(0.5))
        s = calc.summary()
        assert s.total_trades == 3
        assert s.winning_trades == 2
        assert s.losing_trades == 1
        assert s.win_rate == pytest.approx(66.67, rel=0.01)

    def test_gross_and_net(self):
        calc = PnLCalculator()
        calc.record_trade(make_trade(3.0, fees=0.1))
        calc.record_trade(make_trade(-1.0, fees=0.1))
        s = calc.summary()
        assert s.gross_profit == pytest.approx(3.0)
        assert s.gross_loss == pytest.approx(-1.0)
        assert s.net_pnl == pytest.approx(2.0)
        assert s.total_fees == pytest.approx(0.2)

    def test_profit_factor(self):
        calc = PnLCalculator()
        calc.record_trade(make_trade(4.0))
        calc.record_trade(make_trade(-2.0))
        assert calc.summary().profit_factor == pytest.approx(2.0)

    def test_profit_factor_no_losses(self):
        calc = PnLCalculator()
        calc.record_trade(make_trade(1.0))
        assert calc.summary().profit_factor == float("inf")

    def test_best_worst(self):
        calc = PnLCalculator()
        calc.record_trade(make_trade(5.0))
        calc.record_trade(make_trade(-3.0))
        s = calc.summary()
        assert s.best_trade_pnl == 5.0
        assert s.worst_trade_pnl == -3.0

    def test_averages(self):
        calc = PnLCalculator()
        calc.record_trade(make_trade(4.0))
        calc.record_trade(make_trade(2.0))
        calc.record_trade(make_trade(-2.0))
        s = calc.summary()
        assert s.average_win == pytest.approx(3.0)
        assert s.average_loss == pytest.approx(2.0)

    def test_consecutive_losses(self):
        calc = PnLCalculator()
        calc.record_trade(make_trade(1.0))
        calc.record_trade(make_trade(-1.0))
        calc.record_trade(make_trade(-1.0))
        calc.record_trade(make_trade(-0.5))
        assert calc.consecutive_losses() == 3

    def test_consecutive_losses_reset_by_win(self):
        calc = PnLCalculator()
        calc.record_trade(make_trade(-1.0))
        calc.record_trade(make_trade(1.0))
        assert calc.consecutive_losses() == 0

    def test_today_filter(self):
        calc = PnLCalculator()
        now = time.time()
        calc.record_trade(make_trade(1.0, exit_time=now))
        calc.record_trade(make_trade(1.0, exit_time=now - 3 * 86400))  # 3 days ago
        assert len(calc.today()) == 1
        assert calc.daily_summary().total_trades == 1

    def test_max_drawdown(self):
        calc = PnLCalculator()
        # equity: 100 -> 120 -> 90 -> 110 ; peak 120, trough 90 => 25%
        calc.record_trade(make_trade(20.0))
        calc.record_trade(make_trade(-30.0))
        calc.record_trade(make_trade(20.0))
        assert calc.max_drawdown_pct(100.0) == pytest.approx(25.0)

    def test_max_drawdown_no_loss(self):
        calc = PnLCalculator()
        calc.record_trade(make_trade(10.0))
        assert calc.max_drawdown_pct(100.0) == 0.0

    def test_holding_time(self):
        calc = PnLCalculator()
        now = time.time()
        calc.record_trade(make_trade(1.0, exit_time=now, entry_time=now - 60))
        s = calc.summary()
        assert s.avg_holding_seconds == pytest.approx(60.0)
