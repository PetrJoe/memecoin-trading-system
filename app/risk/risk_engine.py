from __future__ import annotations

from app.config import get_logger, get_settings
from app.risk.models import (
    PortfolioRiskData,
    RiskCheckType,
    RiskResult,
    RiskWarning,
    TokenRiskData,
)

logger = get_logger(category="application")


class RiskEngine:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def evaluate(
        self,
        token_data: TokenRiskData,
        portfolio_data: PortfolioRiskData,
    ) -> RiskResult:
        reasons: list[str] = []
        warnings: list[RiskWarning] = []
        critical_failures: list[str] = []
        score = 100

        score, reasons, warnings, critical_failures = self._check_liquidity(
            token_data, reasons, warnings, critical_failures, score
        )

        score, reasons, warnings = self._check_volume(token_data, reasons, warnings, score)

        score, reasons, warnings = self._check_buy_sell_ratio(token_data, reasons, warnings, score)

        score, reasons, warnings = self._check_token_age(token_data, reasons, warnings, score)

        critical_failures, warnings = self._check_token_safety(token_data, critical_failures, warnings)

        score, critical_failures, reasons, warnings = self._check_portfolio_limits(
            portfolio_data, critical_failures, reasons, warnings, score
        )

        approved = len(critical_failures) == 0

        logger.info(
            "risk_evaluation",
            token=token_data.symbol,
            approved=approved,
            score=score,
            reasons_count=len(reasons),
            warnings_count=len(warnings),
            critical_count=len(critical_failures),
        )

        return RiskResult(
            approved=approved,
            score=max(0, min(100, score)),
            reasons=reasons,
            warnings=warnings,
            critical_failures=critical_failures,
        )

    def _check_liquidity(
        self,
        token: TokenRiskData,
        reasons: list[str],
        warnings: list[RiskWarning],
        critical_failures: list[str],
        score: int,
    ) -> tuple[int, list[str], list[RiskWarning], list[str]]:
        if token.liquidity is None:
            critical_failures.append("No liquidity data available")
            return score, reasons, warnings, critical_failures

        min_liq = self.settings.MIN_LIQUIDITY_USD
        if token.liquidity < min_liq * 0.5:
            critical_failures.append(
                f"Liquidity critically low: ${token.liquidity:,.0f} (min: ${min_liq:,.0f})"
            )
        elif token.liquidity < min_liq:
            score -= 30
            reasons.append(f"Liquidity below minimum: ${token.liquidity:,.0f} < ${min_liq:,.0f}")
        elif token.liquidity < min_liq * 2:
            score -= 10
            reasons.append(f"Liquidity adequate: ${token.liquidity:,.0f}")
        else:
            reasons.append(f"Strong liquidity: ${token.liquidity:,.0f}")

        if token.liquidity_change_5m is not None and token.liquidity_change_5m < -20:
            warnings.append(RiskWarning(
                check_type=RiskCheckType.LIQUIDITY_CHANGE,
                message=f"Liquidity dropped {token.liquidity_change_5m:.1f}% in 5m",
                severity="high",
            ))
            score -= 15

        return score, reasons, warnings, critical_failures

    def _check_volume(
        self,
        token: TokenRiskData,
        reasons: list[str],
        warnings: list[RiskWarning],
        score: int,
    ) -> tuple[int, list[str], list[RiskWarning]]:
        min_vol = self.settings.MIN_VOLUME_5M_USD
        vol = token.volume_5m or 0.0

        if vol < min_vol * 0.3:
            score -= 25
            reasons.append(f"Very low volume: ${vol:,.0f}")
        elif vol < min_vol:
            score -= 15
            reasons.append(f"Volume below minimum: ${vol:,.0f} < ${min_vol:,.0f}")
        elif vol < min_vol * 2:
            reasons.append(f"Adequate volume: ${vol:,.0f}")
        else:
            reasons.append(f"Strong volume: ${vol:,.0f}")
            score += 5

        return score, reasons, warnings

    def _check_buy_sell_ratio(
        self,
        token: TokenRiskData,
        reasons: list[str],
        warnings: list[RiskWarning],
        score: int,
    ) -> tuple[int, list[str], list[RiskWarning]]:
        total_5m = token.buys_5m + token.sells_5m
        if total_5m > 0:
            ratio = token.buys_5m / total_5m
            if ratio < 0.3:
                score -= 20
                reasons.append(f"Weak buy pressure: {ratio:.0%} buy ratio")
            elif ratio < 0.5:
                score -= 10
                reasons.append(f"Neutral buy pressure: {ratio:.0%} buy ratio")
            else:
                reasons.append(f"Strong buy pressure: {ratio:.0%} buy ratio")
                score += 5

        total_1h = token.buys_1h + token.sells_1h
        if total_1h > 0:
            ratio_1h = token.buys_1h / total_1h
            if ratio_1h < 0.3:
                warnings.append(RiskWarning(
                    check_type=RiskCheckType.BUY_SELL_RATIO,
                    message=f"Low 1h buy ratio: {ratio_1h:.0%}",
                    severity="medium",
                ))

        return score, reasons, warnings

    def _check_token_age(
        self,
        token: TokenRiskData,
        reasons: list[str],
        warnings: list[RiskWarning],
        score: int,
    ) -> tuple[int, list[str], list[RiskWarning]]:
        if token.token_age_hours is None:
            return score, reasons, warnings

        if token.token_age_hours < 0.5:
            warnings.append(RiskWarning(
                check_type=RiskCheckType.TOKEN_AGE,
                message=f"Very new token: {token.token_age_hours:.1f}h old",
                severity="medium",
            ))
        elif token.token_age_hours > 48:
            reasons.append(f"Established token: {token.token_age_hours:.0f}h old")
        else:
            reasons.append(f"Token age: {token.token_age_hours:.1f}h")

        return score, reasons, warnings

    def _check_token_safety(
        self,
        token: TokenRiskData,
        critical_failures: list[str],
        warnings: list[RiskWarning],
    ) -> tuple[list[str], list[RiskWarning]]:
        if token.has_mint_authority is True:
            critical_failures.append("Token has mint authority — can be inflated")

        if token.has_freeze_authority is True:
            critical_failures.append("Token has freeze authority — trades can be frozen")

        return critical_failures, warnings

    def _check_portfolio_limits(
        self,
        portfolio: PortfolioRiskData,
        critical_failures: list[str],
        reasons: list[str],
        warnings: list[RiskWarning],
        score: int,
    ) -> tuple[int, list[str], list[RiskWarning], list[str]]:
        if portfolio.open_positions >= portfolio.max_open_positions:
            critical_failures.append(
                f"Max open positions reached: {portfolio.open_positions}/{portfolio.max_open_positions}"
            )

        if portfolio.daily_loss_usd >= portfolio.max_daily_loss_usd:
            critical_failures.append(
                f"Daily loss limit reached: ${portfolio.daily_loss_usd:.2f} >= ${portfolio.max_daily_loss_usd:.2f}"
            )

        if portfolio.total_exposure_usd >= portfolio.max_total_exposure_usd:
            critical_failures.append(
                f"Max exposure reached: ${portfolio.total_exposure_usd:.2f} >= ${portfolio.max_total_exposure_usd:.2f}"
            )

        if portfolio.consecutive_losses >= portfolio.max_consecutive_losses:
            critical_failures.append(
                f"Too many consecutive losses: {portfolio.consecutive_losses} >= {portfolio.max_consecutive_losses}"
            )

        if portfolio.wallet_balance_usd < portfolio.max_position_usd:
            critical_failures.append(
                f"Insufficient balance: ${portfolio.wallet_balance_usd:.2f} < ${portfolio.max_position_usd:.2f}"
            )

        exposure_pct = (
            (portfolio.total_exposure_usd / portfolio.wallet_balance_usd * 100)
            if portfolio.wallet_balance_usd > 0
            else 0
        )
        if exposure_pct > 80:
            warnings.append(RiskWarning(
                check_type=RiskCheckType.WALLET_EXPOSURE,
                message=f"High portfolio exposure: {exposure_pct:.0f}%",
                severity="high",
            ))
            score -= 10

        return score, critical_failures, reasons, warnings
