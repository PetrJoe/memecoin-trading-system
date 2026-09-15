from __future__ import annotations

from app.config import get_logger, get_settings
from app.scanner.models import MarketSnapshot
from app.strategy.base import BaseStrategy, SignalType, StrategyContext, StrategySignal
from app.strategy.scoring import TokenScorer

logger = get_logger(category="application")


class MomentumStrategy(BaseStrategy):
    def __init__(self) -> None:
        super().__init__(name="momentum")
        self.settings = get_settings()
        self.scorer = TokenScorer()

    async def analyze(self, context: StrategyContext) -> StrategySignal:
        snapshot = context.snapshot
        scoring = self.scorer.score(
            snapshot=snapshot,
            risk_score=context.risk_score or 50,
            token_age_hours=context.token_age_hours,
            liquidity_change_5m=context.liquidity_change_5m,
        )

        signal = self.generate_signal(context, scoring.total_score, scoring.reasons)

        logger.info(
            "strategy_analysis",
            strategy=self.name,
            token=snapshot.symbol,
            signal=signal.signal.value,
            score=signal.score,
            confidence=signal.confidence,
        )

        return signal

    def generate_signal(
        self,
        context: StrategyContext,
        score: int,
        reasons: list[str],
    ) -> StrategySignal:
        snapshot = context.snapshot
        min_risk_score = self.settings.MIN_RISK_SCORE

        if context.risk_score is not None and context.risk_score < min_risk_score:
            reasons.append(f"Risk score {context.risk_score} below minimum {min_risk_score}")
            return StrategySignal(
                signal=SignalType.REJECT,
                score=score,
                reasons=reasons,
                token_address=snapshot.token_address,
                symbol=snapshot.symbol,
                confidence=0.0,
            )

        if context.has_mint_authority is True or context.has_freeze_authority is True:
            reasons.append("Token has safety concerns (mint/freeze authority)")
            return StrategySignal(
                signal=SignalType.REJECT,
                score=score,
                reasons=reasons,
                token_address=snapshot.token_address,
                symbol=snapshot.symbol,
                confidence=0.0,
            )

        if score >= 75:
            confidence = min(1.0, score / 100.0)
            reasons.insert(0, f"Strong buy signal (score: {score})")
            return StrategySignal(
                signal=SignalType.BUY,
                score=score,
                reasons=reasons,
                token_address=snapshot.token_address,
                symbol=snapshot.symbol,
                confidence=confidence,
            )
        elif score >= 60:
            confidence = score / 100.0 * 0.8
            reasons.insert(0, f"Moderate buy signal (score: {score})")
            return StrategySignal(
                signal=SignalType.BUY,
                score=score,
                reasons=reasons,
                token_address=snapshot.token_address,
                symbol=snapshot.symbol,
                confidence=confidence,
            )
        elif score >= 45:
            reasons.insert(0, f"Watching — marginal score (score: {score})")
            return StrategySignal(
                signal=SignalType.WATCH,
                score=score,
                reasons=reasons,
                token_address=snapshot.token_address,
                symbol=snapshot.symbol,
                confidence=0.3,
            )
        else:
            reasons.insert(0, f"Score too low (score: {score})")
            return StrategySignal(
                signal=SignalType.REJECT,
                score=score,
                reasons=reasons,
                token_address=snapshot.token_address,
                symbol=snapshot.symbol,
                confidence=0.0,
            )
