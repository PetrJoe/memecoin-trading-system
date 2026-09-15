from datetime import datetime, timezone

import pytest

from app.scanner.models import MarketSnapshot
from app.strategy.scoring import ScoringResult, TokenScorer


def _snap(**kwargs) -> MarketSnapshot:
    defaults = dict(
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
    defaults.update(kwargs)
    return MarketSnapshot(**defaults)


class TestTokenScorer:
    def test_perfect_score(self, patched_env):
        scorer = TokenScorer()
        snap = _snap(
            liquidity=100000,
            volume_5m=50000,
            buys_5m=200,
            sells_5m=50,
            price_change_h1=25,
            volume_1h=100000,
        )
        result = scorer.score(snap, risk_score=90, token_age_hours=3.0)
        assert result.total_score >= 80
        assert len(result.components) == 7

    def test_low_liquidity_reduces_score(self, patched_env):
        scorer = TokenScorer()
        high_liq = scorer.score(_snap(liquidity=100000), risk_score=50)
        low_liq = scorer.score(_snap(liquidity=2000), risk_score=50)
        assert low_liq.total_score < high_liq.total_score

    def test_low_volume_reduces_score(self, patched_env):
        scorer = TokenScorer()
        high_vol = scorer.score(_snap(volume_5m=50000), risk_score=50)
        low_vol = scorer.score(_snap(volume_5m=500), risk_score=50)
        assert low_vol.total_score < high_vol.total_score

    def test_sell_pressure_reduces_score(self, patched_env):
        scorer = TokenScorer()
        buy_heavy = scorer.score(_snap(buys_5m=200, sells_5m=50), risk_score=50)
        sell_heavy = scorer.score(_snap(buys_5m=50, sells_5m=200), risk_score=50)
        assert sell_heavy.total_score < buy_heavy.total_score

    def test_negative_momentum_reduces_score(self, patched_env):
        scorer = TokenScorer()
        positive = scorer.score(_snap(price_change_h1=20), risk_score=50)
        negative = scorer.score(_snap(price_change_h1=-20), risk_score=50)
        assert negative.total_score < positive.total_score

    def test_volume_acceleration(self, patched_env):
        scorer = TokenScorer()
        accelerating = scorer.score(_snap(volume_5m=20000, volume_1h=50000), risk_score=50)
        declining = scorer.score(_snap(volume_5m=1000, volume_1h=100000), risk_score=50)
        assert accelerating.total_score > declining.total_score

    def test_custom_weights(self, patched_env):
        custom = {"liquidity": 50, "volume": 50, "buy_pressure": 0, "momentum": 0, "volume_acceleration": 0, "token_age": 0, "risk_score": 0}
        scorer = TokenScorer(weights=custom)
        result = scorer.score(_snap(), risk_score=50)
        assert result.total_score <= 100

    def test_score_clamped_to_100(self, patched_env):
        scorer = TokenScorer()
        result = scorer.score(
            _snap(liquidity=1e9, volume_5m=1e9, buys_5m=10000, sells_5m=1, price_change_h1=100),
            risk_score=100,
            token_age_hours=3.0,
        )
        assert result.total_score <= 100

    def test_score_not_negative(self, patched_env):
        scorer = TokenScorer()
        result = scorer.score(
            _snap(liquidity=0, volume_5m=0, buys_5m=0, sells_5m=1000, price_change_h1=-50),
            risk_score=0,
        )
        assert result.total_score >= 0


class TestScoringResult:
    def test_passed_above_50(self, patched_env):
        scorer = TokenScorer()
        result = scorer.score(_snap(), risk_score=80)
        assert isinstance(result.passed, bool)

    def test_components_have_reasons(self, patched_env):
        scorer = TokenScorer()
        result = scorer.score(_snap(), risk_score=50)
        for comp in result.components:
            assert comp.reason != ""
