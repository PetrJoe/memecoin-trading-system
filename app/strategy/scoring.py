from __future__ import annotations

from dataclasses import dataclass, field

from app.config import get_settings
from app.scanner.models import MarketSnapshot


@dataclass
class ScoreComponent:
    name: str
    weight: int
    score: int = 0
    reason: str = ""


@dataclass
class ScoringResult:
    total_score: int = 0
    components: list[ScoreComponent] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.total_score >= 50


class TokenScorer:
    def __init__(self, weights: dict[str, int] | None = None) -> None:
        settings = get_settings()
        self.weights = weights or settings.scoring_weights

    def score(
        self,
        snapshot: MarketSnapshot,
        risk_score: int = 50,
        token_age_hours: float | None = None,
        liquidity_change_5m: float | None = None,
    ) -> ScoringResult:
        components: list[ScoreComponent] = []
        reasons: list[str] = []

        liq = self._score_liquidity(snapshot)
        components.append(liq)
        if liq.reason:
            reasons.append(liq.reason)

        vol = self._score_volume(snapshot)
        components.append(vol)
        if vol.reason:
            reasons.append(vol.reason)

        bp = self._score_buy_pressure(snapshot)
        components.append(bp)
        if bp.reason:
            reasons.append(bp.reason)

        mom = self._score_momentum(snapshot)
        components.append(mom)
        if mom.reason:
            reasons.append(mom.reason)

        va = self._score_volume_acceleration(snapshot)
        components.append(va)
        if va.reason:
            reasons.append(va.reason)

        age = self._score_token_age(token_age_hours)
        components.append(age)
        if age.reason:
            reasons.append(age.reason)

        rs = self._score_risk(risk_score)
        components.append(rs)
        if rs.reason:
            reasons.append(rs.reason)

        total = sum(c.score for c in components)
        total = max(0, min(100, total))

        return ScoringResult(
            total_score=total,
            components=components,
            reasons=reasons,
        )

    def _score_liquidity(self, snap: MarketSnapshot) -> ScoreComponent:
        weight = self.weights.get("liquidity", 20)
        liq = snap.liquidity or 0.0
        min_liq = 10000.0

        if liq >= min_liq * 5:
            score = weight
            reason = f"Excellent liquidity: ${liq:,.0f}"
        elif liq >= min_liq * 2:
            score = int(weight * 0.8)
            reason = f"Good liquidity: ${liq:,.0f}"
        elif liq >= min_liq:
            score = int(weight * 0.5)
            reason = f"Adequate liquidity: ${liq:,.0f}"
        elif liq >= min_liq * 0.5:
            score = int(weight * 0.2)
            reason = f"Low liquidity: ${liq:,.0f}"
        else:
            score = 0
            reason = f"Very low liquidity: ${liq:,.0f}"

        return ScoreComponent(name="liquidity", weight=weight, score=score, reason=reason)

    def _score_volume(self, snap: MarketSnapshot) -> ScoreComponent:
        weight = self.weights.get("volume", 20)
        vol = snap.volume_5m or 0.0
        min_vol = 5000.0

        if vol >= min_vol * 5:
            score = weight
            reason = f"Excellent volume: ${vol:,.0f}"
        elif vol >= min_vol * 2:
            score = int(weight * 0.8)
            reason = f"Good volume: ${vol:,.0f}"
        elif vol >= min_vol:
            score = int(weight * 0.5)
            reason = f"Adequate volume: ${vol:,.0f}"
        else:
            score = int(weight * 0.2)
            reason = f"Low volume: ${vol:,.0f}"

        return ScoreComponent(name="volume", weight=weight, score=score, reason=reason)

    def _score_buy_pressure(self, snap: MarketSnapshot) -> ScoreComponent:
        weight = self.weights.get("buy_pressure", 15)
        total = snap.buys_5m + snap.sells_5m

        if total == 0:
            return ScoreComponent(name="buy_pressure", weight=weight, score=0, reason="No transaction data")

        ratio = snap.buys_5m / total
        if ratio >= 0.7:
            score = weight
            reason = f"Strong buy pressure: {ratio:.0%}"
        elif ratio >= 0.5:
            score = int(weight * 0.7)
            reason = f"Moderate buy pressure: {ratio:.0%}"
        elif ratio >= 0.3:
            score = int(weight * 0.3)
            reason = f"Weak buy pressure: {ratio:.0%}"
        else:
            score = 0
            reason = f"Sell pressure dominant: {ratio:.0%}"

        return ScoreComponent(name="buy_pressure", weight=weight, score=score, reason=reason)

    def _score_momentum(self, snap: MarketSnapshot) -> ScoreComponent:
        weight = self.weights.get("momentum", 15)
        change = snap.price_change_h1

        if change is None:
            return ScoreComponent(name="momentum", weight=weight, score=int(weight * 0.5), reason="No momentum data")

        if change >= 20:
            score = weight
            reason = f"Strong momentum: +{change:.1f}%"
        elif change >= 5:
            score = int(weight * 0.7)
            reason = f"Positive momentum: +{change:.1f}%"
        elif change >= -5:
            score = int(weight * 0.5)
            reason = f"Flat momentum: {change:.1f}%"
        elif change >= -20:
            score = int(weight * 0.3)
            reason = f"Negative momentum: {change:.1f}%"
        else:
            score = 0
            reason = f"Strong downtrend: {change:.1f}%"

        return ScoreComponent(name="momentum", weight=weight, score=score, reason=reason)

    def _score_volume_acceleration(self, snap: MarketSnapshot) -> ScoreComponent:
        weight = self.weights.get("volume_acceleration", 10)
        vol_5m = snap.volume_5m or 0.0
        vol_1h = snap.volume_1h or 0.0

        if vol_1h == 0:
            return ScoreComponent(name="volume_acceleration", weight=weight, score=0, reason="No volume history")

        expected_5m = vol_1h / 12
        if expected_5m == 0:
            ratio = 0.0
        else:
            ratio = vol_5m / expected_5m

        if ratio >= 2.0:
            score = weight
            reason = f"Volume accelerating: {ratio:.1f}x average"
        elif ratio >= 1.2:
            score = int(weight * 0.7)
            reason = f"Volume above average: {ratio:.1f}x"
        elif ratio >= 0.8:
            score = int(weight * 0.5)
            reason = f"Volume average: {ratio:.1f}x"
        else:
            score = int(weight * 0.2)
            reason = f"Volume declining: {ratio:.1f}x average"

        return ScoreComponent(name="volume_acceleration", weight=weight, score=score, reason=reason)

    def _score_token_age(self, age_hours: float | None) -> ScoreComponent:
        weight = self.weights.get("token_age", 10)

        if age_hours is None:
            return ScoreComponent(name="token_age", weight=weight, score=int(weight * 0.5), reason="Unknown token age")

        if age_hours < 0.5:
            score = int(weight * 0.3)
            reason = f"Very new: {age_hours:.1f}h"
        elif age_hours < 6:
            score = weight
            reason = f"Fresh: {age_hours:.1f}h"
        elif age_hours < 24:
            score = int(weight * 0.8)
            reason = f"Recent: {age_hours:.0f}h"
        else:
            score = int(weight * 0.5)
            reason = f"Established: {age_hours:.0f}h"

        return ScoreComponent(name="token_age", weight=weight, score=score, reason=reason)

    def _score_risk(self, risk_score: int) -> ScoreComponent:
        weight = self.weights.get("risk_score", 10)

        if risk_score >= 80:
            score = weight
            reason = f"Low risk: {risk_score}/100"
        elif risk_score >= 60:
            score = int(weight * 0.7)
            reason = f"Moderate risk: {risk_score}/100"
        elif risk_score >= 40:
            score = int(weight * 0.4)
            reason = f"Elevated risk: {risk_score}/100"
        else:
            score = 0
            reason = f"High risk: {risk_score}/100"

        return ScoreComponent(name="risk_score", weight=weight, score=score, reason=reason)
