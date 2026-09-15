from __future__ import annotations

from app.config import get_logger, get_settings

logger = get_logger(category="application")


class PositionSizer:
    def __init__(self) -> None:
        self.settings = get_settings()

    def calculate(
        self,
        wallet_balance_usd: float,
        risk_score: int,
        open_positions: int,
        total_exposure_usd: float,
        daily_loss_usd: float,
        available_sol: float = 0.0,
        strategy_confidence: float = 1.0,
    ) -> float:
        max_position = self.settings.MAX_POSITION_USD
        max_positions = self.settings.MAX_OPEN_POSITIONS
        max_daily_loss = self.settings.MAX_DAILY_LOSS_USD
        max_exposure = self.settings.MAX_TOTAL_EXPOSURE_USD

        if wallet_balance_usd <= 0:
            logger.warning("position_sizer_no_balance", balance=wallet_balance_usd)
            return 0.0

        if open_positions >= max_positions:
            logger.warning("position_sizer_max_positions", open=open_positions, max=max_positions)
            return 0.0

        if daily_loss_usd >= max_daily_loss:
            logger.warning("position_sizer_daily_loss", loss=daily_loss_usd, max=max_daily_loss)
            return 0.0

        if total_exposure_usd >= max_exposure:
            logger.warning("position_sizer_max_exposure", exposure=total_exposure_usd, max=max_exposure)
            return 0.0

        position_size = max_position

        balance_factor = min(1.0, wallet_balance_usd / (max_position * max_positions))
        position_size *= balance_factor

        risk_factor = risk_score / 100.0
        position_size *= risk_factor

        confidence_factor = max(0.5, min(1.0, strategy_confidence))
        position_size *= confidence_factor

        remaining_exposure = max_exposure - total_exposure_usd
        position_size = min(position_size, remaining_exposure)

        remaining_daily = max_daily_loss - daily_loss_usd
        position_size = min(position_size, remaining_daily)

        position_size = min(position_size, wallet_balance_usd)

        position_size = round(position_size, 2)

        if position_size < 0.50 and self.settings.is_live_safe:
            position_size = 0.0
            logger.warning("position_sizer_below_minimum", size=position_size)

        logger.info(
            "position_sizer_calculated",
            size=position_size,
            balance=wallet_balance_usd,
            risk_score=risk_score,
            confidence=strategy_confidence,
        )

        return position_size
