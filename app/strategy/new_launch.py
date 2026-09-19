"""
New-Launch Sniper Strategy

Optimized for buying freshly launched Solana memecoins within minutes
of their pair creation. Prioritizes:
- Extreme newness (< 60 min old)
- Immediate buy pressure (first buyers)
- Minimum viable liquidity
- Volume surge from zero
- Low price (pre-pump)

Unlike the momentum strategy which waits for established trends,
this strategy aims to enter BEFORE the major move, accepting higher
risk for potentially larger returns.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.config import get_logger, get_settings
from app.scanner.models import MarketSnapshot
from app.strategy.base import BaseStrategy, SignalType, StrategyContext, StrategySignal
from app.strategy.scoring import TokenScorer, ScoreComponent, ScoringResult

logger = get_logger(category="trades")


class NewLaunchScorer:
    """
    Scoring system specifically tuned for brand-new token launches.
    Different weights than the standard momentum scorer:
    - Heavily weights buy pressure and volume surge
    - Rewards extreme newness
    - Lighter on liquidity (new tokens naturally have less)
    """

    WEIGHTS = {
        "buy_pressure": 25,      # strongest signal for new launches
        "volume_surge": 20,      # volume from zero = interest
        "newness": 20,           # fresher = better entry
        "liquidity": 15,         # enough to trade, not too much (already pumped)
        "price_entry": 10,       # low price = early entry
        "sell_pressure_penalty": 10,  # penalty for heavy selling
    }

    def score(
        self,
        snapshot: MarketSnapshot,
        token_age_minutes: Optional[float] = None,
    ) -> ScoringResult:
        components: list[ScoreComponent] = []
        reasons: list[str] = []

        # 1. Buy pressure (most important for new launches)
        bp = self._score_buy_pressure(snapshot)
        components.append(bp)
        if bp.reason:
            reasons.append(bp.reason)

        # 2. Volume surge (volume appearing from nothing)
        vs = self._score_volume_surge(snapshot)
        components.append(vs)
        if vs.reason:
            reasons.append(vs.reason)

        # 3. Newness (fresher = better entry price)
        nw = self._score_newness(token_age_minutes)
        components.append(nw)
        if nw.reason:
            reasons.append(nw.reason)

        # 4. Liquidity (minimum viable, but not too much)
        lq = self._score_liquidity(snapshot)
        components.append(lq)
        if lq.reason:
            reasons.append(lq.reason)

        # 5. Price entry (low price = early)
        pe = self._score_price_entry(snapshot)
        components.append(pe)
        if pe.reason:
            reasons.append(pe.reason)

        # 6. Sell pressure penalty
        sp = self._score_sell_pressure(snapshot)
        components.append(sp)
        if sp.reason:
            reasons.append(sp.reason)

        total = sum(c.score for c in components)
        total = max(0, min(100, total))

        return ScoringResult(
            total_score=total,
            components=components,
            reasons=reasons,
        )

    def _score_buy_pressure(self, snap: MarketSnapshot) -> ScoreComponent:
        weight = self.WEIGHTS["buy_pressure"]
        total = snap.buys_5m + snap.sells_5m

        if total == 0:
            return ScoreComponent(name="buy_pressure", weight=weight, score=weight // 2, reason="No txns yet (neutral)")

        ratio = snap.buys_5m / total
        if ratio >= 0.8:
            return ScoreComponent(name="buy_pressure", weight=weight, score=weight, reason=f"Strong buy pressure: {ratio:.0%}")
        elif ratio >= 0.6:
            return ScoreComponent(name="buy_pressure", weight=weight, score=int(weight * 0.8), reason=f"Good buy pressure: {ratio:.0%}")
        elif ratio >= 0.4:
            return ScoreComponent(name="buy_pressure", weight=weight, score=int(weight * 0.4), reason=f"Neutral buy pressure: {ratio:.0%}")
        else:
            return ScoreComponent(name="buy_pressure", weight=weight, score=0, reason=f"Sell dominant: {ratio:.0%}")

    def _score_volume_surge(self, snap: MarketSnapshot) -> ScoreComponent:
        weight = self.WEIGHTS["volume_surge"]
        vol_5m = snap.volume_5m or 0.0
        vol_1h = snap.volume_1h or 0.0

        # For new tokens, any 5m volume is significant
        if vol_5m >= 5000:
            return ScoreComponent(name="volume_surge", weight=weight, score=weight, reason=f"Strong volume: ${vol_5m:,.0f}")
        elif vol_5m >= 1000:
            return ScoreComponent(name="volume_surge", weight=weight, score=int(weight * 0.8), reason=f"Good volume: ${vol_5m:,.0f}")
        elif vol_5m >= 200:
            return ScoreComponent(name="volume_surge", weight=weight, score=int(weight * 0.5), reason=f"Emerging volume: ${vol_5m:,.0f}")
        else:
            return ScoreComponent(name="volume_surge", weight=weight, score=int(weight * 0.2), reason=f"Low volume: ${vol_5m:,.0f}")

    def _score_newness(self, age_minutes: Optional[float]) -> ScoreComponent:
        weight = self.WEIGHTS["newness"]

        if age_minutes is None:
            return ScoreComponent(name="newness", weight=weight, score=int(weight * 0.5), reason="Unknown age")

        if age_minutes < 5:
            return ScoreComponent(name="newness", weight=weight, score=weight, reason=f"Ultra fresh: {age_minutes:.0f}min")
        elif age_minutes < 15:
            return ScoreComponent(name="newness", weight=weight, score=int(weight * 0.9), reason=f"Very fresh: {age_minutes:.0f}min")
        elif age_minutes < 30:
            return ScoreComponent(name="newness", weight=weight, score=int(weight * 0.7), reason=f"Fresh: {age_minutes:.0f}min")
        elif age_minutes < 60:
            return ScoreComponent(name="newness", weight=weight, score=int(weight * 0.4), reason=f"Recent: {age_minutes:.0f}min")
        else:
            return ScoreComponent(name="newness", weight=weight, score=int(weight * 0.1), reason=f"Too old for sniper: {age_minutes:.0f}min")

    def _score_liquidity(self, snap: MarketSnapshot) -> ScoreComponent:
        weight = self.WEIGHTS["liquidity"]
        liq = snap.liquidity or 0.0

        # For new launches, moderate liquidity is ideal
        # Too low = can't exit, too high = already pumped
        if liq >= 50000:
            return ScoreComponent(name="liquidity", weight=weight, score=int(weight * 0.5), reason=f"High liquidity (may have pumped): ${liq:,.0f}")
        elif liq >= 10000:
            return ScoreComponent(name="liquidity", weight=weight, score=weight, reason=f"Good liquidity: ${liq:,.0f}")
        elif liq >= 2000:
            return ScoreComponent(name="liquidity", weight=weight, score=int(weight * 0.7), reason=f"Adequate liquidity: ${liq:,.0f}")
        elif liq >= 500:
            return ScoreComponent(name="liquidity", weight=weight, score=int(weight * 0.4), reason=f"Low liquidity: ${liq:,.0f}")
        else:
            return ScoreComponent(name="liquidity", weight=weight, score=0, reason=f"Very low liquidity: ${liq:,.0f}")

    def _score_price_entry(self, snap: MarketSnapshot) -> ScoreComponent:
        weight = self.WEIGHTS["price_entry"]
        price = snap.price

        # Lower price = earlier entry = more upside potential
        if price <= 0.000001:
            return ScoreComponent(name="price_entry", weight=weight, score=weight, reason=f"Very early entry: ${price:.10f}")
        elif price <= 0.00001:
            return ScoreComponent(name="price_entry", weight=weight, score=int(weight * 0.8), reason=f"Early entry: ${price:.10f}")
        elif price <= 0.0001:
            return ScoreComponent(name="price_entry", weight=weight, score=int(weight * 0.6), reason=f"Moderate entry: ${price:.8f}")
        elif price <= 0.001:
            return ScoreComponent(name="price_entry", weight=weight, score=int(weight * 0.3), reason=f"Late entry: ${price:.6f}")
        else:
            return ScoreComponent(name="price_entry", weight=weight, score=0, reason=f"Very late entry: ${price:.6f}")

    def _score_sell_pressure(self, snap: MarketSnapshot) -> ScoreComponent:
        weight = self.WEIGHTS["sell_pressure_penalty"]
        total = snap.buys_5m + snap.sells_5m

        if total == 0:
            return ScoreComponent(name="sell_pressure", weight=weight, score=weight // 2, reason="")

        sell_ratio = snap.sells_5m / total
        if sell_ratio > 0.6:
            return ScoreComponent(name="sell_pressure", weight=weight, score=0, reason=f"Heavy selling: {sell_ratio:.0%} sells")
        elif sell_ratio > 0.4:
            return ScoreComponent(name="sell_pressure", weight=weight, score=int(weight * 0.5), reason=f"Moderate selling: {sell_ratio:.0%} sells")
        else:
            return ScoreComponent(name="sell_pressure", weight=weight, score=weight, reason="")


class NewLaunchSniper(BaseStrategy):
    """
    Strategy for sniping newly launched Solana memecoins.
    Uses aggressive entry criteria optimized for speed and early position.
    """

    def __init__(self) -> None:
        super().__init__(name="new_launch_sniper")
        self.settings = get_settings()
        self.scorer = NewLaunchScorer()

    async def analyze(self, context: StrategyContext) -> StrategySignal:
        snapshot = context.snapshot

        # Calculate age in minutes
        token_age_minutes = None
        if context.token_age_hours is not None:
            token_age_minutes = context.token_age_hours * 60.0
        elif snapshot.pair_created_at:
            now = datetime.now(timezone.utc)
            created = snapshot.pair_created_at.replace(tzinfo=timezone.utc) if snapshot.pair_created_at.tzinfo is None else snapshot.pair_created_at
            token_age_minutes = (now - created).total_seconds() / 60.0

        scoring = self.scorer.score(
            snapshot=snapshot,
            token_age_minutes=token_age_minutes,
        )

        signal = self.generate_signal(context, scoring.total_score, scoring.reasons)

        logger.info(
            "new_launch_analysis",
            strategy=self.name,
            token=snapshot.symbol,
            signal=signal.signal.value,
            score=signal.score,
            age_min=round(token_age_minutes, 1) if token_age_minutes else None,
        )

        return signal

    def generate_signal(
        self,
        context: StrategyContext,
        score: int,
        reasons: list[str],
    ) -> StrategySignal:
        snapshot = context.snapshot

        # Hard reject: mint/freeze authority = scam risk
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

        # New launch sniper uses lower threshold (60) since we're early
        if score >= 60:
            confidence = min(1.0, score / 100.0)
            reasons.insert(0, f"New launch BUY signal (score: {score})")
            return StrategySignal(
                signal=SignalType.BUY,
                score=score,
                reasons=reasons,
                token_address=snapshot.token_address,
                symbol=snapshot.symbol,
                confidence=confidence,
            )
        elif score >= 40:
            reasons.insert(0, f"Watching new launch (score: {score})")
            return StrategySignal(
                signal=SignalType.WATCH,
                score=score,
                reasons=reasons,
                token_address=snapshot.token_address,
                symbol=snapshot.symbol,
                confidence=0.3,
            )
        else:
            reasons.insert(0, f"Score too low for sniper (score: {score})")
            return StrategySignal(
                signal=SignalType.REJECT,
                score=score,
                reasons=reasons,
                token_address=snapshot.token_address,
                symbol=snapshot.symbol,
                confidence=0.0,
            )
