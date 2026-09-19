from datetime import datetime, timedelta, timezone

import pytest

from app.backtest import BacktestConfig, BacktestEngine
from app.scanner.models import MarketSnapshot

T1 = "TokenAddr111111111111111111111111111111"
T2 = "TokenAddr222222222222222222222222222222"


def snap(address=T1, symbol="TKN", price=1.0, liquidity=50_000, volume=10_000,
         buys=60, sells=20, ts=None):
    return MarketSnapshot(
        token_address=address,
        pair_address=f"Pair{symbol}",
        symbol=symbol,
        name=f"Test {symbol}",
        price=price,
        liquidity=liquidity,
        volume_5m=volume,
        buys_5m=buys,
        sells_5m=sells,
        timestamp=ts or datetime.now(timezone.utc),
    )


class TestBacktestEngine:
    def test_basic_run_produces_report(self):
        engine = BacktestEngine(BacktestConfig(starting_balance_usd=100.0))
        start = datetime.now(timezone.utc)
        history = [
            [snap(ts=start)],
            [snap(ts=start + timedelta(seconds=5))],
            [snap(price=1.4, ts=start + timedelta(seconds=10))],  # TP hit
        ]
        report = engine.run(history)
        assert report.summary.total_trades == 1  # one closed trade (buy+sell counted as 1 close)
        assert report.summary.net_pnl > 0
        assert report.ending_equity > report.starting_balance
        assert report.open_positions_at_end == 0
        assert report.timestamps == 3

    def test_loss_makes_negative_pnl(self):
        engine = BacktestEngine(BacktestConfig(starting_balance_usd=100.0))
        start = datetime.now(timezone.utc)
        history = [
            [snap(ts=start)],
            [snap(price=0.5, ts=start + timedelta(seconds=5))],  # SL hit
        ]
        report = engine.run(history)
        assert report.summary.net_pnl < 0
        assert report.summary.losing_trades == 1

    def test_drawdown_computed(self):
        engine = BacktestEngine(BacktestConfig(starting_balance_usd=100.0))
        start = datetime.now(timezone.utc)
        history = [
            [snap(ts=start)],
            [snap(price=0.5, ts=start + timedelta(seconds=5))],  # -50% stop loss
        ]
        report = engine.run(history)
        assert report.max_drawdown_pct > 0

    def test_end_of_data_liquidation(self):
        """Open positions are force-closed at last known price when data ends."""
        engine = BacktestEngine(BacktestConfig(starting_balance_usd=100.0))
        start = datetime.now(timezone.utc)
        history = [
            [snap(ts=start)],
            [snap(price=1.1, ts=start + timedelta(seconds=5))],  # no exit condition hit
        ]
        report = engine.run(history)
        assert report.open_positions_at_end == 0
        assert report.summary.total_trades == 1

    def test_caveats_include_small_sample(self):
        engine = BacktestEngine(BacktestConfig(starting_balance_usd=100.0))
        start = datetime.now(timezone.utc)
        report = engine.run([[snap(ts=start)]])
        assert any("sample too small" in c for c in report.caveats)
        assert any("slippage" in c.lower() for c in report.caveats)

    def test_cannot_run_inside_event_loop(self):
        engine = BacktestEngine()
        start = datetime.now(timezone.utc)

        import asyncio

        async def inner():
            engine.run([[snap(ts=start)]])

        async def outer():
            await inner()

        with pytest.raises(RuntimeError, match="event loop"):
            asyncio.run(outer())

    def test_report_to_dict(self):
        engine = BacktestEngine(BacktestConfig(starting_balance_usd=100.0))
        report = engine.run([[snap()]])
        d = report.to_dict()
        assert "net_pnl" in d
        assert "win_rate" in d
        assert "caveats" in d

    def test_winning_strategy_makes_money(self):
        """Multi-token, rising market: engine should profit with TP=25%."""
        engine = BacktestEngine(BacktestConfig(starting_balance_usd=100.0, max_candidates_per_timestamp=2))
        start = datetime.now(timezone.utc)
        history = [
            [snap(T1, "ONE", ts=start), snap(T2, "TWO", ts=start)],
            [snap(T1, "ONE", price=1.5, ts=start + timedelta(seconds=5)),
             snap(T2, "TWO", price=1.6, ts=start + timedelta(seconds=5))],
        ]
        report = engine.run(history)
        assert report.summary.net_pnl > 0
        assert report.summary.winning_trades >= 1
