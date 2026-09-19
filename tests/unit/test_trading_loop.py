import asyncio
import time

import pytest

from app.api.state import AppState
from app.config.settings import get_settings
from app.execution.paper import PaperFillSimulator, PaperSellResult
from app.scanner.dex_screener import DexScreenerClientError
from app.scanner.models import MarketSnapshot
from app.workers.trading_loop import TradingLoop

TOKEN = "TokenAddr111111111111111111111111111111"
TOKEN2 = "TokenAddr222222222222222222222222222222"


def make_snap(address=TOKEN, symbol="TKN", price=1.0, liquidity=50_000, volume=10_000, buys=60, sells=20):
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
    )


class FakeScanner:
    """Scriptable stand-in for DexScreenerClient."""

    def __init__(self, pages=None, error=None):
        self.pages = pages or []
        self.error = error
        self.calls = 0
        self.closed = False

    async def get_solana_pairs(self, query=""):
        self.calls += 1
        if self.error:
            raise self.error
        page = self.pages[min(self.calls - 1, len(self.pages) - 1)] if self.pages else []
        return list(page)

    async def close(self):
        self.closed = True


@pytest.fixture
def fresh_state():
    state = AppState()
    return state


@pytest.fixture
def loop_factory(fresh_state):
    def _build(scanner):
        return TradingLoop(dex_client=scanner, app_state=fresh_state)

    return _build


class TestScanCycle:
    @pytest.mark.asyncio
    async def test_scan_updates_prices_and_state(self, loop_factory, fresh_state):
        scanner = FakeScanner(pages=[[make_snap()]])
        loop = loop_factory(scanner)
        await loop._scan_cycle()
        assert fresh_state.prices[TOKEN] == 1.0
        assert fresh_state.scans_completed == 1
        assert TOKEN in fresh_state.latest_snapshots

    @pytest.mark.asyncio
    async def test_discovery_adds_filtered_tokens(self, loop_factory, fresh_state):
        scanner = FakeScanner(pages=[[make_snap()]])
        loop = loop_factory(scanner)
        await loop._scan_cycle()
        assert TOKEN in fresh_state.watchlist
        assert any(e.event_type == "token_discovered" for e in fresh_state.event_log.recent(10))

    @pytest.mark.asyncio
    async def test_filtered_out_tokens_not_watched(self, loop_factory, fresh_state):
        # Liquidity far below MIN_LIQUIDITY_USD (10k)
        bad = make_snap(liquidity=100.0, volume=10.0)
        scanner = FakeScanner(pages=[[bad]])
        loop = loop_factory(scanner)
        await loop._scan_cycle()
        assert bad.token_address not in fresh_state.watchlist
        assert fresh_state.open_signals[bad.token_address]["signal"] == "filtered"

    @pytest.mark.asyncio
    async def test_scanner_outage_is_survivable(self, loop_factory, fresh_state):
        scanner = FakeScanner(error=DexScreenerClientError("api down"))
        loop = loop_factory(scanner)
        # Must not raise
        await loop._scan_cycle()
        assert any(e.event_type == "scanner_unavailable" for e in fresh_state.event_log.recent(10))

    @pytest.mark.asyncio
    async def test_buy_on_strong_signal(self, loop_factory, fresh_state):
        scanner = FakeScanner(pages=[[make_snap()]])
        loop = loop_factory(scanner)
        await loop._scan_cycle()
        # High-quality snapshot: momentum strategy should BUY and orchestrator execute
        assert loop.position_manager.has_position(TOKEN)
        assert loop.simulator.cash_usd < 100.0  # cash spent
        types = [e.event_type for e in fresh_state.event_log.recent(20)]
        assert "buy_executed" in types

    @pytest.mark.asyncio
    async def test_no_duplicate_position_on_rescan(self, loop_factory, fresh_state):
        scanner = FakeScanner(pages=[[make_snap()], [make_snap(price=1.1)]])
        loop = loop_factory(scanner)
        await loop._scan_cycle()
        await loop._scan_cycle()
        # Still exactly one position, one buy
        assert loop.position_manager.open_count() == 1

    @pytest.mark.asyncio
    async def test_exit_on_stop_loss(self, loop_factory, fresh_state):
        # Page 1: buy at 1.0; Page 2: crash through the 10% stop loss
        scanner = FakeScanner(pages=[[make_snap()], [make_snap(price=0.5)]])
        loop = loop_factory(scanner)
        await loop._scan_cycle()
        assert loop.position_manager.has_position(TOKEN)

        await loop._scan_cycle()      # second scan delivers the crash price
        await loop._position_cycle()  # evaluates exits against it
        assert not loop.position_manager.has_position(TOKEN)
        assert loop.pnl_calculator.closed_trades[0].exit_reason == "STOP_LOSS"
        types = [e.event_type for e in fresh_state.event_log.recent(20)]
        assert "position_closed" in types
        # Balance tracker recorded the sell
        assert loop.balance_tracker.realized_pnl < 0

    @pytest.mark.asyncio
    async def test_take_profit_exit(self, loop_factory, fresh_state):
        scanner = FakeScanner(pages=[[make_snap()], [make_snap(price=1.4)]])
        loop = loop_factory(scanner)
        await loop._scan_cycle()
        await loop._scan_cycle()
        await loop._position_cycle()
        assert not loop.position_manager.has_position(TOKEN)
        assert loop.pnl_calculator.closed_trades[0].exit_reason == "TAKE_PROFIT"
        assert loop.pnl_calculator.closed_trades[0].pnl_usd > 0

    @pytest.mark.asyncio
    async def test_balance_tracker_mark_to_market(self, loop_factory, fresh_state):
        scanner = FakeScanner(pages=[[make_snap()], [make_snap(price=1.2)]])
        loop = loop_factory(scanner)
        await loop._scan_cycle()
        await loop._scan_cycle()
        await loop._position_cycle()
        # Position still open, value should be reflected
        assert loop.balance_tracker.position_value_usd > 0


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop(self, loop_factory, fresh_state):
        scanner = FakeScanner(pages=[[make_snap()]])
        loop = loop_factory(scanner)
        await loop.start()
        assert loop.is_running
        assert fresh_state.trading_enabled is True
        await asyncio.sleep(0.1)
        await loop.stop()
        assert not loop.is_running
        assert fresh_state.trading_enabled is False

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self, loop_factory):
        loop = loop_factory(FakeScanner())
        await loop.start()
        await loop.stop()
        await loop.stop()  # no error

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_buys(self, loop_factory, fresh_state):
        scanner = FakeScanner(pages=[[make_snap()]])
        loop = loop_factory(scanner)
        loop.circuit_breaker.manual_pause("test")
        await loop._scan_cycle()
        assert not loop.position_manager.has_position(TOKEN)


class TestEventCooldown:
    @pytest.mark.asyncio
    async def test_cooldown_suppresses_repeats(self, loop_factory, fresh_state):
        scanner = FakeScanner(pages=[[make_snap()], [make_snap()]])
        loop = loop_factory(scanner)
        await loop._scan_cycle()
        first_count = len(fresh_state.event_log.recent(100))
        await loop._scan_cycle()
        # token_discovered for the same token must not re-emit within cooldown
        discovered = [e for e in fresh_state.event_log.recent(100) if e.event_type == "token_discovered"]
        assert len(discovered) == 1


class TestRiskScore:
    @pytest.mark.asyncio
    async def test_heuristic_score_bounds(self, loop_factory):
        loop = loop_factory(FakeScanner())
        assert 0 <= loop._heuristic_risk_score(make_snap()) <= 100
        assert loop._heuristic_risk_score(make_snap(liquidity=500_000, volume=50_000, buys=90, sells=10)) > 50
        assert loop._heuristic_risk_score(make_snap(liquidity=100, volume=10, buys=1, sells=99)) < 50
