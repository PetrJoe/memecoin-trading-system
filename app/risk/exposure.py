from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.config import get_logger

logger = get_logger(category="application")


@dataclass
class ExposureTracker:
    _positions: dict[int, float] = field(default_factory=dict)
    _total_exposure: float = 0.0

    def add_position(self, position_id: int, capital_usd: float) -> None:
        self._positions[position_id] = capital_usd
        self._total_exposure += capital_usd
        logger.info(
            "exposure_position_added",
            position_id=position_id,
            capital=capital_usd,
            total_exposure=self._total_exposure,
        )

    def remove_position(self, position_id: int) -> Optional[float]:
        capital = self._positions.pop(position_id, None)
        if capital is not None:
            self._total_exposure -= capital
            logger.info(
                "exposure_position_removed",
                position_id=position_id,
                capital=capital,
                total_exposure=self._total_exposure,
            )
        return capital

    def update_position(self, position_id: int, new_capital_usd: float) -> None:
        old = self._positions.get(position_id, 0.0)
        self._positions[position_id] = new_capital_usd
        self._total_exposure = self._total_exposure - old + new_capital_usd

    @property
    def total_exposure(self) -> float:
        return self._total_exposure

    @property
    def position_count(self) -> int:
        return len(self._positions)

    def get_exposure_pct(self, wallet_balance: float) -> float:
        if wallet_balance <= 0:
            return 0.0
        return (self._total_exposure / wallet_balance) * 100

    def can_open_position(self, wallet_balance: float, max_exposure_usd: float, max_positions: int) -> bool:
        if len(self._positions) >= max_positions:
            return False
        remaining = max_exposure_usd - self._total_exposure
        if remaining <= 0:
            return False
        return True

    def reset(self) -> None:
        self._positions.clear()
        self._total_exposure = 0.0
