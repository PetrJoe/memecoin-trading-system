"""Tests for the rug-pull detector."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone, timedelta

import pytest

from app.risk.rug_detector import (
    OnChainRugChecker,
    RugAnalysisResult,
    RugCheckType,
    RugDetector,
    RugFlag,
    RugSeverity,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _base_kwargs(
    symbol: str = "TEST",
    name: str = "Test Token",
    price: float = 0.00001,
    liquidity: float = 5000.0,
    market_cap: float = 50000.0,
    fdv: float = 50000.0,
    buys_5m: int = 10,
    sells_5m: int = 3,
    buys_1h: int = 50,
    sells_1h: int = 20,
    volume_5m: float = 2000.0,
    volume_1h: float = 10000.0,
    price_change_m5: float = 10.0,
    price_change_h1: float = 20.0,
    has_mint_authority: bool | None = None,
    has_freeze_authority: bool | None = None,
    token_age_hours: float = 0.5,
    dex: str = "raydium",
    social_links: dict | None = None,
) -> dict:
    return dict(
        token_address="addr_test123",
        symbol=symbol,
        name=name,
        price=price,
        liquidity=liquidity,
        market_cap=market_cap,
        fdv=fdv,
        buys_5m=buys_5m,
        sells_5m=sells_5m,
        buys_1h=buys_1h,
        sells_1h=sells_1h,
        volume_5m=volume_5m,
        volume_1h=volume_1h,
        price_change_m5=price_change_m5,
        price_change_h1=price_change_h1,
        has_mint_authority=has_mint_authority,
        has_freeze_authority=has_freeze_authority,
        token_age_hours=token_age_hours,
        dex=dex,
        social_links=social_links,
    )


# ---------------------------------------------------------------------------
# RugDetector: veto-level checks (CRITICAL)
# ---------------------------------------------------------------------------

class TestRugDetectorCritical:
    def setup_method(self):
        self.detector = RugDetector()

    @pytest.mark.asyncio
    async def test_mint_authority_vetoes(self):
        result = await self.detector.analyze(**_base_kwargs(has_mint_authority=True))
        assert not result.approved
        assert any("mint authority" in v.lower() for v in result.veto_reasons)

    @pytest.mark.asyncio
    async def test_freeze_authority_vetoes(self):
        result = await self.detector.analyze(**_base_kwargs(has_freeze_authority=True))
        assert not result.approved
        assert any("freeze authority" in v.lower() for v in result.veto_reasons)

    @pytest.mark.asyncio
    async def test_honeypot_name_vetoes(self):
        result = await self.detector.analyze(**_base_kwargs(
            name="Honeypot Coin", symbol="HONEYPOT"
        ))
        assert not result.approved
        assert any("honeypot" in v.lower() for v in result.veto_reasons)

    @pytest.mark.asyncio
    async def test_zero_sells_1h_vetoes(self):
        """1h with buys but zero sells = honeypot."""
        result = await self.detector.analyze(**_base_kwargs(
            buys_1h=15, sells_1h=0, buys_5m=5, sells_5m=0
        ))
        assert not result.approved
        assert any("honeypot" in v.lower() for v in result.veto_reasons)

    @pytest.mark.asyncio
    async def test_extreme_1h_pump_vetoes(self):
        result = await self.detector.analyze(**_base_kwargs(price_change_h1=1500))
        assert not result.approved
        assert any("manipulated" in v.lower() or "manipulation" in v.lower() for v in result.veto_reasons)

    @pytest.mark.asyncio
    async def test_critically_low_liquidity_vetoes(self):
        result = await self.detector.analyze(**_base_kwargs(liquidity=50))
        assert not result.approved
        assert any("liquidity" in v.lower() for v in result.veto_reasons)


# ---------------------------------------------------------------------------
# RugDetector: HIGH severity checks (score penalty)
# ---------------------------------------------------------------------------

class TestRugDetectorHigh:
    def setup_method(self):
        self.detector = RugDetector()

    @pytest.mark.asyncio
    async def test_very_low_liquidity_penalty(self):
        result = await self.detector.analyze(**_base_kwargs(liquidity=300))
        assert result.rug_score < 80
        assert any(f.severity == RugSeverity.HIGH for f in result.flags)

    @pytest.mark.asyncio
    async def test_buy_bot_pattern_detected(self):
        """Many buys, tiny avg size, few sells = buy bot."""
        result = await self.detector.analyze(**_base_kwargs(
            buys_5m=30, sells_5m=1, volume_5m=50.0  # avg $1.6/trade
        ))
        assert result.rug_score < 80
        assert any(f.check_type == RugCheckType.BUY_BOT_PATTERN for f in result.flags)

    @pytest.mark.asyncio
    async def test_extreme_sell_pressure(self):
        result = await self.detector.analyze(**_base_kwargs(
            buys_5m=1, sells_5m=10
        ))
        assert result.rug_score < 80

    @pytest.mark.asyncio
    async def test_vertical_5m_pump(self):
        result = await self.detector.analyze(**_base_kwargs(price_change_m5=600))
        assert result.rug_score < 80
        assert any(f.check_type == RugCheckType.PRICE_MANIPULATION for f in result.flags)

    @pytest.mark.asyncio
    async def test_suspicious_name_keyword(self):
        result = await self.detector.analyze(**_base_kwargs(name="TestToken Scam"))
        assert result.rug_score < 80
        assert any(f.check_type == RugCheckType.SUSPICIOUS_NAME for f in result.flags)

    @pytest.mark.asyncio
    async def test_low_liquidity_fdv_ratio(self):
        result = await self.detector.analyze(**_base_kwargs(
            liquidity=100, fdv=100000
        ))
        assert result.rug_score < 80
        assert any(f.check_type == RugCheckType.HOLDER_CONCENTRATION for f in result.flags)

    @pytest.mark.asyncio
    async def test_low_float(self):
        result = await self.detector.analyze(**_base_kwargs(
            liquidity=200, market_cap=200000
        ))
        assert result.rug_score < 80


# ---------------------------------------------------------------------------
# RugDetector: MEDIUM severity (warnings)
# ---------------------------------------------------------------------------

class TestRugDetectorMedium:
    def setup_method(self):
        self.detector = RugDetector()

    @pytest.mark.asyncio
    async def test_no_social_links_warning(self):
        result = await self.detector.analyze(
            **_base_kwargs(token_age_hours=1.0, social_links=None)
        )
        assert any(f.check_type == RugCheckType.NO_SOCIAL for f in result.flags)
        assert any(f.severity == RugSeverity.MEDIUM for f in result.flags)

    @pytest.mark.asyncio
    async def test_stealth_launch_detected(self):
        result = await self.detector.analyze(
            **_base_kwargs(
                token_age_hours=2.0,
                dex="unknown_dex",
                social_links=None,
            )
        )
        assert any(f.check_type == RugCheckType.STEALTH_LAUNCH for f in result.flags)

    @pytest.mark.asyncio
    async def test_no_socials_not_flagged_for_new_token(self):
        """Tokens < 15 min old don't need socials yet."""
        result = await self.detector.analyze(
            **_base_kwargs(token_age_hours=0.1, social_links=None)
        )
        assert not any(f.check_type == RugCheckType.NO_SOCIAL for f in result.flags)

    @pytest.mark.asyncio
    async def test_social_links_present_no_warning(self):
        result = await self.detector.analyze(
            **_base_kwargs(
                token_age_hours=1.0,
                social_links={"twitter": "https://x.com/test"},
            )
        )
        assert not any(f.check_type == RugCheckType.NO_SOCIAL for f in result.flags)


# ---------------------------------------------------------------------------
# RugDetector: clean token passes
# ---------------------------------------------------------------------------

class TestRugDetectorClean:
    def setup_method(self):
        self.detector = RugDetector()

    @pytest.mark.asyncio
    async def test_clean_token_passes(self):
        result = await self.detector.analyze(**_base_kwargs(
            name="DogWifHat",
            symbol="WIF",
            liquidity=50000,
            market_cap=500000,
            fdv=500000,
            buys_5m=15,
            sells_5m=5,
            buys_1h=80,
            sells_1h=30,
            volume_5m=5000,
            price_change_m5=5.0,
            price_change_h1=10.0,
            has_mint_authority=False,
            has_freeze_authority=False,
            token_age_hours=1.0,
            dex="raydium",
            social_links={"twitter": "https://x.com/test"},
        ))
        assert result.approved
        assert result.rug_score >= 70
        assert len(result.veto_reasons) == 0

    @pytest.mark.asyncio
    async def test_minimal_but_clean_passes(self):
        """A very new token with basic stats should pass if no red flags."""
        result = await self.detector.analyze(**_base_kwargs(
            name="PepeCoin",
            symbol="PEPE",
            liquidity=1000,
            buys_5m=5,
            sells_5m=2,
            buys_1h=20,
            sells_1h=8,
            token_age_hours=0.2,  # 12 min old
        ))
        assert result.approved


# ---------------------------------------------------------------------------
# RugDetector: flag structure
# ---------------------------------------------------------------------------

class TestRugDetectorFlags:
    def setup_method(self):
        self.detector = RugDetector()

    @pytest.mark.asyncio
    async def test_flags_have_correct_structure(self):
        result = await self.detector.analyze(**_base_kwargs(has_mint_authority=True))
        assert len(result.flags) > 0
        flag = result.flags[0]
        assert isinstance(flag.check_type, RugCheckType)
        assert isinstance(flag.severity, RugSeverity)
        assert flag.message
        assert flag.score_penalty > 0

    @pytest.mark.asyncio
    async def test_veto_reasons_populated(self):
        result = await self.detector.analyze(**_base_kwargs(has_mint_authority=True))
        assert len(result.veto_reasons) > 0

    @pytest.mark.asyncio
    async def test_analysis_time_is_recorded(self):
        result = await self.detector.analyze(**_base_kwargs())
        assert result.analysis_time_ms >= 0


# ---------------------------------------------------------------------------
# RugDetector: multiple flags compound
# ---------------------------------------------------------------------------

class TestRugDetectorCompound:
    def setup_method(self):
        self.detector = RugDetector()

    @pytest.mark.asyncio
    async def test_multiple_flags_reduce_score(self):
        """Token with several medium issues should have very low score."""
        result = await self.detector.analyze(**_base_kwargs(
            name="TestScam",
            liquidity=300,
            buys_5m=25,
            sells_5m=0,
            buys_1h=30,
            sells_1h=0,
            volume_5m=40.0,
            price_change_m5=100,
            token_age_hours=2.0,
            dex="unknown",
            social_links=None,
        ))
        # Should have multiple flags
        assert len(result.flags) >= 3
        # Score should be very low
        assert result.rug_score < 30


# ---------------------------------------------------------------------------
# OnChainRugChecker
# ---------------------------------------------------------------------------

class TestOnChainRugChecker:
    def test_checker_instantiates(self):
        checker = OnChainRugChecker()
        assert checker._client is None
