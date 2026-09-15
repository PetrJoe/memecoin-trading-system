from datetime import datetime, timedelta, timezone

import pytest

from app.scanner.filters import FilterResult, TokenFilter
from app.scanner.models import MarketSnapshot


def _make_snapshot(
    liquidity: float = 50000.0,
    volume_5m: float = 10000.0,
    buys_5m: int = 100,
    sells_5m: int = 50,
    price: float = 0.001,
    pair_created_hours_ago: float = 2.0,
) -> MarketSnapshot:
    return MarketSnapshot(
        token_address="TokenAddress111111111111111111111111111111",
        pair_address="PairAddress1111111111111111111111111111111",
        symbol="TEST",
        name="Test Token",
        price=price,
        liquidity=liquidity,
        volume_5m=volume_5m,
        buys_5m=buys_5m,
        sells_5m=sells_5m,
        pair_created_at=datetime.now(timezone.utc) - timedelta(hours=pair_created_hours_ago),
    )


class TestTokenFilterDefaults:
    def test_from_settings_creates_filter(self, patched_env):
        f = TokenFilter.from_settings()
        assert f.min_liquidity_usd == 10000.0
        assert f.min_volume_5m_usd == 5000.0

    def test_no_filters_passes_everything(self):
        f = TokenFilter()
        snap = _make_snapshot()
        result = f.check(snap)
        assert result.passed is True
        assert result.reasons == []


class TestLiquidityFilter:
    def test_passes_when_above_min(self):
        f = TokenFilter(min_liquidity_usd=10000)
        snap = _make_snapshot(liquidity=50000)
        result = f.check(snap)
        assert result.passed is True

    def test_fails_when_below_min(self):
        f = TokenFilter(min_liquidity_usd=10000)
        snap = _make_snapshot(liquidity=5000)
        result = f.check(snap)
        assert result.passed is False
        assert any("Liquidity" in r for r in result.reasons)

    def test_fails_when_none(self):
        f = TokenFilter(min_liquidity_usd=10000)
        snap = _make_snapshot()
        snap.liquidity = None
        result = f.check(snap)
        assert result.passed is False


class TestVolumeFilter:
    def test_passes_when_above_min(self):
        f = TokenFilter(min_volume_5m_usd=5000)
        snap = _make_snapshot(volume_5m=10000)
        result = f.check(snap)
        assert result.passed is True

    def test_fails_when_below_min(self):
        f = TokenFilter(min_volume_5m_usd=5000)
        snap = _make_snapshot(volume_5m=1000)
        result = f.check(snap)
        assert result.passed is False
        assert any("Volume" in r for r in result.reasons)


class TestBuySellFilter:
    def test_passes_when_enough_buys(self):
        f = TokenFilter(min_buys_5m=50)
        snap = _make_snapshot(buys_5m=100)
        result = f.check(snap)
        assert result.passed is True

    def test_fails_when_not_enough_buys(self):
        f = TokenFilter(min_buys_5m=50)
        snap = _make_snapshot(buys_5m=10)
        result = f.check(snap)
        assert result.passed is False

    def test_buy_sell_ratio_passes(self):
        f = TokenFilter(min_buy_sell_ratio=0.6)
        snap = _make_snapshot(buys_5m=80, sells_5m=20)
        result = f.check(snap)
        assert result.passed is True

    def test_buy_sell_ratio_fails(self):
        f = TokenFilter(min_buy_sell_ratio=0.7)
        snap = _make_snapshot(buys_5m=50, sells_5m=50)
        result = f.check(snap)
        assert result.passed is False
        assert any("ratio" in r for r in result.reasons)


class TestTokenAgeFilter:
    def test_passes_when_young_enough(self):
        f = TokenFilter(max_token_age_hours=24)
        snap = _make_snapshot(pair_created_hours_ago=2)
        result = f.check(snap)
        assert result.passed is True

    def test_fails_when_too_old(self):
        f = TokenFilter(max_token_age_hours=24)
        snap = _make_snapshot(pair_created_hours_ago=48)
        result = f.check(snap)
        assert result.passed is False
        assert any("age" in r for r in result.reasons)


class TestPriceFilter:
    def test_passes_within_range(self):
        f = TokenFilter(min_price=0.0001, max_price=1.0)
        snap = _make_snapshot(price=0.001)
        result = f.check(snap)
        assert result.passed is True

    def test_fails_below_min_price(self):
        f = TokenFilter(min_price=0.001)
        snap = _make_snapshot(price=0.0001)
        result = f.check(snap)
        assert result.passed is False
        assert any("Price" in r for r in result.reasons)

    def test_fails_above_max_price(self):
        f = TokenFilter(max_price=0.001)
        snap = _make_snapshot(price=1.0)
        result = f.check(snap)
        assert result.passed is False
        assert any("Price" in r for r in result.reasons)


class TestMultipleFilters:
    def test_all_must_pass(self):
        f = TokenFilter(
            min_liquidity_usd=10000,
            min_volume_5m_usd=5000,
            min_buys_5m=50,
        )
        snap = _make_snapshot(liquidity=5000, volume_5m=1000, buys_5m=10)
        result = f.check(snap)
        assert result.passed is False
        assert len(result.reasons) == 3
