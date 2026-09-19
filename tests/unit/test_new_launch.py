"""Tests for the new-launch sniper feature."""
from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scanner.filters import FilterResult, NewLaunchFilter
from app.scanner.models import MarketSnapshot
from app.strategy.base import SignalType, StrategyContext, StrategySignal
from app.strategy.new_launch import NewLaunchScorer, NewLaunchSniper


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_snapshot(
    symbol: str = "TEST",
    price: float = 0.00001,
    liquidity: float = 5000.0,
    volume_5m: float = 1000.0,
    buys_5m: int = 10,
    sells_5m: int = 2,
    created_ago_seconds: int = 600,  # 10 minutes ago
) -> MarketSnapshot:
    now_ms = int(time.time() * 1000)
    return MarketSnapshot(
        token_address=f"addr_{symbol.lower()}",
        pair_address=f"pair_{symbol.lower()}",
        symbol=symbol,
        name=f"{symbol} Token",
        price=price,
        liquidity=liquidity,
        volume_5m=volume_5m,
        buys_5m=buys_5m,
        sells_5m=sells_5m,
        pair_created_at=datetime.fromtimestamp(
            (now_ms - created_ago_seconds * 1000) / 1000, tz=timezone.utc
        ),
    )


# ---------------------------------------------------------------------------
# NewLaunchFilter tests
# ---------------------------------------------------------------------------

class TestNewLaunchFilter:
    def setup_method(self):
        self.filt = NewLaunchFilter(
            max_token_age_minutes=60.0,
            min_liquidity_usd=500.0,
            min_buys_5m=1,
            min_buy_sell_ratio=0.4,
            min_volume_5m_usd=100.0,
            max_price=0.01,
        )

    def test_passes_valid_new_token(self):
        snap = _make_snapshot(price=0.00001, liquidity=5000, volume_5m=1000, buys_5m=10, sells_5m=2, created_ago_seconds=300)
        result = self.filt.check(snap)
        assert result.passed, f"Expected pass, got reasons: {result.reasons}"

    def test_rejects_old_token(self):
        snap = _make_snapshot(created_ago_seconds=7200)  # 2 hours old
        result = self.filt.check(snap)
        assert not result.passed
        assert any("too old" in r.lower() for r in result.reasons)

    def test_rejects_no_liquidity(self):
        snap = _make_snapshot(liquidity=100)
        result = self.filt.check(snap)
        assert not result.passed
        assert any("liquidity" in r.lower() for r in result.reasons)

    def test_rejects_no_buys(self):
        snap = _make_snapshot(buys_5m=0, sells_5m=5)
        result = self.filt.check(snap)
        assert not result.passed
        assert any("buys" in r.lower() for r in result.reasons)

    def test_rejects_high_price(self):
        snap = _make_snapshot(price=0.05)  # already mooned
        result = self.filt.check(snap)
        assert not result.passed
        assert any("price" in r.lower() or "pumped" in r.lower() for r in result.reasons)

    def test_rejects_sell_dominant(self):
        snap = _make_snapshot(buys_5m=2, sells_5m=10)
        result = self.filt.check(snap)
        assert not result.passed
        assert any("buy/sell" in r.lower() for r in result.reasons)

    def test_rejects_unknown_age(self):
        snap = _make_snapshot()
        snap.pair_created_at = None
        result = self.filt.check(snap)
        assert not result.passed
        assert any("unknown" in r.lower() for r in result.reasons)


# ---------------------------------------------------------------------------
# NewLaunchScorer tests
# ---------------------------------------------------------------------------

class TestNewLaunchScorer:
    def setup_method(self):
        self.scorer = NewLaunchScorer()

    def test_high_score_for_good_new_token(self):
        snap = _make_snapshot(
            price=0.000001,
            liquidity=10000,
            volume_5m=3000,
            buys_5m=20,
            sells_5m=2,
            created_ago_seconds=120,  # 2 min old
        )
        result = self.scorer.score(snap, token_age_minutes=2.0)
        assert result.total_score >= 70, f"Expected >= 70, got {result.total_score}"

    def test_low_score_for_old_token(self):
        snap = _make_snapshot(
            price=0.001,
            liquidity=500,
            volume_5m=50,
            buys_5m=3,
            sells_5m=3,
            created_ago_seconds=5400,  # 90 min old
        )
        result = self.scorer.score(snap, token_age_minutes=90.0)
        assert result.total_score < 50, f"Expected < 50, got {result.total_score}"

    def test_penalizes_sell_pressure(self):
        snap = _make_snapshot(buys_5m=2, sells_5m=10, created_ago_seconds=300)
        result = self.scorer.score(snap, token_age_minutes=5.0)
        # Sell pressure component should get 0 score
        sell_comp = [c for c in result.components if c.name == "sell_pressure"]
        assert len(sell_comp) == 1
        assert sell_comp[0].score == 0, "Sell pressure should be penalized"
        # Overall score should be lower than a token with same stats but no selling
        good_snap = _make_snapshot(buys_5m=12, sells_5m=0, created_ago_seconds=300)
        good_result = self.scorer.score(good_snap, token_age_minutes=5.0)
        assert result.total_score < good_result.total_score

    def test_ultra_fresh_gets_bonus(self):
        snap = _make_snapshot(created_ago_seconds=120)  # 2 min
        result = self.scorer.score(snap, token_age_minutes=2.0)
        # Should have a newness component with high score
        newness = [c for c in result.components if c.name == "newness"]
        assert len(newness) == 1
        assert newness[0].score >= 18  # near full weight of 20


# ---------------------------------------------------------------------------
# NewLaunchSniper strategy tests
# ---------------------------------------------------------------------------

class TestNewLaunchSniper:
    def setup_method(self):
        self.strategy = NewLaunchSniper()

    @pytest.mark.asyncio
    async def test_buy_signal_for_strong_new_token(self):
        snap = _make_snapshot(
            price=0.000001,
            liquidity=10000,
            volume_5m=3000,
            buys_5m=20,
            sells_5m=2,
            created_ago_seconds=120,
        )
        ctx = StrategyContext(
            snapshot=snap,
            risk_score=80,
            token_age_hours=2.0 / 60.0,
        )
        signal = await self.strategy.analyze(ctx)
        assert signal.signal == SignalType.BUY, f"Expected BUY, got {signal.signal}"
        assert signal.score >= 60

    @pytest.mark.asyncio
    async def test_reject_token_with_mint_authority(self):
        snap = _make_snapshot(price=0.000001, liquidity=10000, created_ago_seconds=120)
        ctx = StrategyContext(
            snapshot=snap,
            risk_score=80,
            token_age_hours=2.0 / 60.0,
            has_mint_authority=True,
        )
        signal = await self.strategy.analyze(ctx)
        assert signal.signal == SignalType.REJECT

    @pytest.mark.asyncio
    async def test_watch_signal_for_marginal_token(self):
        snap = _make_snapshot(
            price=0.005,  # late entry
            liquidity=600,  # low
            volume_5m=150,  # low
            buys_5m=3,
            sells_5m=2,
            created_ago_seconds=2400,  # 40 min
        )
        ctx = StrategyContext(
            snapshot=snap,
            risk_score=50,
            token_age_hours=2400 / 3600.0,
        )
        signal = await self.strategy.analyze(ctx)
        # Should be WATCH or REJECT, not BUY
        assert signal.signal in (SignalType.WATCH, SignalType.REJECT)


# ---------------------------------------------------------------------------
# Integration: filter + strategy pipeline
# ---------------------------------------------------------------------------

class TestNewLaunchPipeline:
    def test_filter_then_score_pipeline(self):
        filt = NewLaunchFilter()
        scorer = NewLaunchScorer()

        # Good new token
        snap = _make_snapshot(
            price=0.000001,
            liquidity=8000,
            volume_5m=2000,
            buys_5m=15,
            sells_5m=3,
            created_ago_seconds=180,
        )

        filter_result = filt.check(snap)
        assert filter_result.passed, f"Should pass filter: {filter_result.reasons}"

        age_minutes = 180 / 60.0
        scoring = scorer.score(snap, token_age_minutes=age_minutes)
        assert scoring.total_score >= 60

    def test_bad_token_filtered_before_scoring(self):
        filt = NewLaunchFilter()
        snap = _make_snapshot(
            price=0.05,  # too high
            liquidity=100,  # too low
            buys_5m=0,
            sells_5m=5,
            created_ago_seconds=7200,  # too old
        )

        filter_result = filt.check(snap)
        assert not filter_result.passed
        assert len(filter_result.reasons) >= 2  # multiple failures
