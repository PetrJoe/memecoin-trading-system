from datetime import datetime, timezone

import pytest

from app.scanner.models import MarketSnapshot
from app.strategy.base import SignalType, StrategyContext, StrategySignal
from app.strategy.momentum import MomentumStrategy


def _context(**kwargs) -> StrategyContext:
    snap_defaults = dict(
        token_address="Addr111",
        pair_address="Pair111",
        symbol="TEST",
        name="Test",
        price=0.001,
        liquidity=50000.0,
        volume_5m=10000.0,
        volume_1h=50000.0,
        buys_5m=100,
        sells_5m=50,
        buys_1h=500,
        sells_1h=300,
        price_change_h1=10.0,
        pair_created_at=datetime.now(timezone.utc),
    )
    snap_defaults.update(kwargs.pop("snap_overrides", {}))
    snapshot = MarketSnapshot(**snap_defaults)
    ctx_defaults = dict(snapshot=snapshot, risk_score=80, token_age_hours=3.0)
    ctx_defaults.update(kwargs)
    return StrategyContext(**ctx_defaults)


class TestMomentumStrategy:
    @pytest.mark.asyncio
    async def test_strong_buy_signal(self, patched_env):
        strategy = MomentumStrategy()
        ctx = _context(
            risk_score=85,
            snap_overrides=dict(
                liquidity=100000,
                volume_5m=50000,
                buys_5m=200,
                sells_5m=50,
                price_change_h1=20,
            ),
        )
        signal = await strategy.analyze(ctx)
        assert signal.signal == SignalType.BUY
        assert signal.score >= 70
        assert signal.confidence > 0.5
        assert len(signal.reasons) > 0

    @pytest.mark.asyncio
    async def test_low_risk_score_rejects(self, patched_env):
        strategy = MomentumStrategy()
        ctx = _context(risk_score=30)
        signal = await strategy.analyze(ctx)
        assert signal.signal == SignalType.REJECT
        assert signal.confidence == 0.0

    @pytest.mark.asyncio
    async def test_mint_authority_rejects(self, patched_env):
        strategy = MomentumStrategy()
        ctx = _context(has_mint_authority=True, risk_score=80)
        signal = await strategy.analyze(ctx)
        assert signal.signal == SignalType.REJECT

    @pytest.mark.asyncio
    async def test_freeze_authority_rejects(self, patched_env):
        strategy = MomentumStrategy()
        ctx = _context(has_freeze_authority=True, risk_score=80)
        signal = await strategy.analyze(ctx)
        assert signal.signal == SignalType.REJECT

    @pytest.mark.asyncio
    async def test_weak_token_watches(self, patched_env):
        strategy = MomentumStrategy()
        ctx = _context(
            risk_score=70,
            snap_overrides=dict(
                liquidity=3000,
                volume_5m=1000,
                buys_5m=20,
                sells_5m=30,
                price_change_h1=-5,
            ),
        )
        signal = await strategy.analyze(ctx)
        assert signal.signal in (SignalType.WATCH, SignalType.REJECT)

    @pytest.mark.asyncio
    async def test_signal_contains_token_info(self, patched_env):
        strategy = MomentumStrategy()
        ctx = _context()
        signal = await strategy.analyze(ctx)
        assert signal.token_address == "Addr111"
        assert signal.symbol == "TEST"

    @pytest.mark.asyncio
    async def test_generate_signal_buy(self, patched_env):
        strategy = MomentumStrategy()
        ctx = _context()
        signal = strategy.generate_signal(ctx, 80, ["strong signal"])
        assert signal.signal == SignalType.BUY
        assert signal.score == 80

    @pytest.mark.asyncio
    async def test_generate_signal_watch(self, patched_env):
        strategy = MomentumStrategy()
        ctx = _context()
        signal = strategy.generate_signal(ctx, 50, ["marginal"])
        assert signal.signal == SignalType.WATCH

    @pytest.mark.asyncio
    async def test_generate_signal_reject_low_score(self, patched_env):
        strategy = MomentumStrategy()
        ctx = _context()
        signal = strategy.generate_signal(ctx, 20, ["too low"])
        assert signal.signal == SignalType.REJECT
