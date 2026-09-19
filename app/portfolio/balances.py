from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from app.config import get_logger, get_settings

logger = get_logger(category="trades")


@dataclass
class BalanceSnapshot:
    cash_usd: float
    position_value_usd: float
    total_usd: float
    timestamp: float = field(default_factory=time.time)


class BalanceTracker:
    """
    Tracks the bot's virtual (paper) or real (live) equity:
    cash plus mark-to-market position value, with P&L versus start.
    """

    def __init__(self, starting_balance_usd: Optional[float] = None) -> None:
        self.settings = get_settings()
        starting = (
            starting_balance_usd
            if starting_balance_usd is not None
            else settings.PAPER_STARTING_BALANCE_USD
        )
        self.starting_balance_usd = starting
        self.cash_usd = starting
        self.realized_pnl_usd = 0.0
        self.total_fees_usd = 0.0
        self._position_value_usd = 0.0
        self._last_snapshot: Optional[BalanceSnapshot] = None

    # ------------------------------------------------------------------ input
    def record_buy(self, amount_usd: float, fee_usd: float) -> None:
        self.cash_usd -= amount_usd
        self.total_fees_usd += fee_usd

    def record_sell(self, proceeds_usd: float, fee_usd: float, realized_pnl_usd: float) -> None:
        self.cash_usd += proceeds_usd
        self.total_fees_usd += fee_usd
        self.realized_pnl_usd += realized_pnl_usd

    def update_position_value(self, value_usd: float) -> None:
        self._position_value_usd = max(0.0, value_usd)

    # ----------------------------------------------------------------- output
    @property
    def position_value_usd(self) -> float:
        return self._position_value_usd

    @property
    def total_equity(self) -> float:
        return self.cash_usd + self._position_value_usd

    @property
    def total_pnl(self) -> float:
        return self.total_equity - self.starting_balance_usd

    @property
    def total_pnl_pct(self) -> float:
        if self.starting_balance_usd <= 0:
            return 0.0
        return self.total_pnl / self.starting_balance_usd * 100.0

    @property
    def realized_pnl(self) -> float:
        return self.realized_pnl_usd

    @property
    def unrealized_pnl(self) -> float:
        return self.total_equity - self.starting_balance_usd - self.realized_pnl_usd

    def snapshot(self) -> BalanceSnapshot:
        snap = BalanceSnapshot(
            cash_usd=round(self.cash_usd, 6),
            position_value_usd=round(self._position_value_usd, 6),
            total_usd=round(self.total_equity, 6),
        )
        self._last_snapshot = snap
        return snap

    def reset(self, starting_balance_usd: Optional[float] = None) -> None:
        starting = (
            starting_balance_usd
            if starting_balance_usd is not None
            else self.starting_balance_usd
        )
        self.starting_balance_usd = starting
        self.cash_usd = starting
        self.realized_pnl_usd = 0.0
        self.total_fees_usd = 0.0
        self._position_value_usd = 0.0
        self._last_snapshot = None
        logger.info("balance_tracker_reset", starting_balance=starting)
