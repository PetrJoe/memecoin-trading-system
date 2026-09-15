import pytest

from app.risk.models import PortfolioRiskData, RiskResult, TokenRiskData
from app.risk.risk_engine import RiskEngine


@pytest.fixture
def engine():
    return RiskEngine()


def _good_token(**kwargs) -> TokenRiskData:
    defaults = dict(
        token_address="TokenAddr111111111111111111111111111111",
        symbol="GOOD",
        liquidity=50000.0,
        volume_5m=10000.0,
        buys_5m=100,
        sells_5m=50,
        buys_1h=500,
        sells_1h=200,
        price=0.001,
        token_age_hours=2.0,
    )
    defaults.update(kwargs)
    return TokenRiskData(**defaults)


def _good_portfolio(**kwargs) -> PortfolioRiskData:
    defaults = dict(
        wallet_balance_usd=100.0,
        total_exposure_usd=0.0,
        open_positions=0,
        daily_pnl=0.0,
        consecutive_losses=0,
        daily_loss_usd=0.0,
        max_position_usd=0.50,
        max_open_positions=2,
        max_daily_loss_usd=1.00,
        max_total_exposure_usd=5.00,
        max_slippage_bps=100,
        max_price_impact_bps=500,
        max_consecutive_losses=5,
    )
    defaults.update(kwargs)
    return PortfolioRiskData(**defaults)


class TestRiskEngineApproval:
    @pytest.mark.asyncio
    async def test_good_token_approved(self, engine):
        result = await engine.evaluate(_good_token(), _good_portfolio())
        assert result.approved is True
        assert result.score > 50

    @pytest.mark.asyncio
    async def test_no_liquidity_rejected(self, engine):
        token = _good_token(liquidity=None)
        result = await engine.evaluate(token, _good_portfolio())
        assert result.approved is False
        assert result.has_critical_failures

    @pytest.mark.asyncio
    async def test_critical_low_liquidity_rejected(self, engine):
        token = _good_token(liquidity=100.0)
        result = await engine.evaluate(token, _good_portfolio())
        assert result.approved is False

    @pytest.mark.asyncio
    async def test_mint_authority_rejected(self, engine):
        token = _good_token(has_mint_authority=True)
        result = await engine.evaluate(token, _good_portfolio())
        assert result.approved is False

    @pytest.mark.asyncio
    async def test_freeze_authority_rejected(self, engine):
        token = _good_token(has_freeze_authority=True)
        result = await engine.evaluate(token, _good_portfolio())
        assert result.approved is False


class TestRiskEnginePortfolioLimits:
    @pytest.mark.asyncio
    async def test_max_positions_rejected(self, engine):
        portfolio = _good_portfolio(open_positions=2)
        result = await engine.evaluate(_good_token(), portfolio)
        assert result.approved is False

    @pytest.mark.asyncio
    async def test_daily_loss_rejected(self, engine):
        portfolio = _good_portfolio(daily_loss_usd=1.50)
        result = await engine.evaluate(_good_token(), portfolio)
        assert result.approved is False

    @pytest.mark.asyncio
    async def test_max_exposure_rejected(self, engine):
        portfolio = _good_portfolio(total_exposure_usd=6.00)
        result = await engine.evaluate(_good_token(), portfolio)
        assert result.approved is False

    @pytest.mark.asyncio
    async def test_consecutive_losses_rejected(self, engine):
        portfolio = _good_portfolio(consecutive_losses=5)
        result = await engine.evaluate(_good_token(), portfolio)
        assert result.approved is False

    @pytest.mark.asyncio
    async def test_insufficient_balance_rejected(self, engine):
        portfolio = _good_portfolio(wallet_balance_usd=0.10)
        result = await engine.evaluate(_good_token(), portfolio)
        assert result.approved is False


class TestRiskEngineScoring:
    @pytest.mark.asyncio
    async def test_high_score_for_good_token(self, engine):
        result = await engine.evaluate(_good_token(), _good_portfolio())
        assert result.score >= 80

    @pytest.mark.asyncio
    async def test_low_volume_reduces_score(self, engine):
        token_low = _good_token(volume_5m=500.0)
        token_high = _good_token(volume_5m=20000.0)
        result_low = await engine.evaluate(token_low, _good_portfolio())
        result_high = await engine.evaluate(token_high, _good_portfolio())
        assert result_low.score < result_high.score

    @pytest.mark.asyncio
    async def test_weak_buy_pressure_reduces_score(self, engine):
        token_weak = _good_token(buys_5m=10, sells_5m=90)
        token_strong = _good_token(buys_5m=90, sells_5m=10)
        result_weak = await engine.evaluate(token_weak, _good_portfolio())
        result_strong = await engine.evaluate(token_strong, _good_portfolio())
        assert result_weak.score < result_strong.score


class TestRiskEngineWarnings:
    @pytest.mark.asyncio
    async def test_liquidity_drop_generates_warning(self, engine):
        token = _good_token(liquidity_change_5m=-25.0)
        result = await engine.evaluate(token, _good_portfolio())
        assert len(result.warnings) > 0

    @pytest.mark.asyncio
    async def test_high_exposure_generates_warning(self, engine):
        portfolio = _good_portfolio(wallet_balance_usd=10.0, total_exposure_usd=9.0)
        result = await engine.evaluate(_good_token(), portfolio)
        assert any("exposure" in w.message.lower() for w in result.warnings)
