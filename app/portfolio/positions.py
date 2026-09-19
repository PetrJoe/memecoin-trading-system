from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.config import get_logger, get_settings

logger = get_logger(category="trades")


class ExitDecision(BaseModel):
    should_exit: bool
    reason: Optional[str] = None  # ExitReason value as string


class ManagedPosition(BaseModel):
    """In-memory representation of a position managed by PositionManager."""
    position_id: int
    token_address: str
    symbol: str
    entry_price: float
    quantity: float
    capital_usd: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    highest_price: float
    opened_at: float
    max_duration_hours: float
    last_price: float = 0.0  # most recent observed market price

    def current_value(self, price: float) -> float:
        return self.quantity * price

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.entry_price) * self.quantity

    def unrealized_pnl_pct(self, price: float) -> float:
        if self.capital_usd <= 0:
            return 0.0
        return self.unrealized_pnl(price) / self.capital_usd * 100.0


class PositionManager:
    """
    Owns the lifecycle of open positions in memory:
    create on confirmed buy, evaluate exit conditions every price tick,
    and emit exit decisions with an ExitReason.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._positions: dict[str, ManagedPosition] = {}

    # ------------------------------------------------------------------ state
    @property
    def positions(self) -> dict[str, ManagedPosition]:
        return dict(self._positions)

    def get(self, token_address: str) -> Optional[ManagedPosition]:
        return self._positions.get(token_address)

    def open_count(self) -> int:
        return len(self._positions)

    def has_position(self, token_address: str) -> bool:
        return token_address in self._positions

    # ----------------------------------------------------------------- create
    def open_position(
        self,
        position_id: int,
        token_address: str,
        symbol: str,
        entry_price: float,
        quantity: float,
        capital_usd: float,
        stop_loss_percent: Optional[float] = None,
        take_profit_percent: Optional[float] = None,
        trailing_stop_percent: Optional[float] = None,
    ) -> ManagedPosition:
        sl_pct = stop_loss_percent if stop_loss_percent is not None else self.settings.STOP_LOSS_PERCENT
        tp_pct = take_profit_percent if take_profit_percent is not None else self.settings.TAKE_PROFIT_PERCENT

        stop_loss = entry_price * (1 - sl_pct / 100.0) if sl_pct else None
        take_profit = entry_price * (1 + tp_pct / 100.0) if tp_pct else None

        pos = ManagedPosition(
            position_id=position_id,
            token_address=token_address,
            symbol=symbol,
            entry_price=entry_price,
            quantity=quantity,
            capital_usd=capital_usd,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_stop_pct=trailing_stop_percent,
            highest_price=entry_price,
            opened_at=0.0,  # set by caller via time.time(); defaulted below
            max_duration_hours=float(self.settings.MAX_POSITION_DURATION_HOURS),
        )
        if pos.opened_at == 0.0:
            import time as _time

            pos.opened_at = _time.time()
        self._positions[token_address] = pos

        logger.info(
            "position_opened",
            position_id=position_id,
            token=symbol,
            entry_price=entry_price,
            quantity=quantity,
            capital=capital_usd,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        return pos

    def close_position(self, token_address: str) -> Optional[ManagedPosition]:
        pos = self._positions.pop(token_address, None)
        if pos:
            logger.info(
                "position_closed",
                position_id=pos.position_id,
                token=pos.symbol,
            )
        return pos

    # ------------------------------------------------------------------- exit
    def update_price(self, token_address: str, price: float) -> Optional[ExitDecision]:
        """Feed the latest price and evaluate all exit conditions."""
        pos = self._positions.get(token_address)
        if pos is None:
            return None

        if price <= 0:
            return ExitDecision(should_exit=False)

        if price > pos.highest_price:
            pos.highest_price = price
        pos.last_price = price

        decision = ExitDecision(should_exit=False)
        stop = self._check_stop_loss(pos, price)
        take = self._check_take_profit(pos, price)
        trail = self._check_trailing_stop(pos, price)
        limit = self._check_time_limit(pos)

        for candidate in (stop, take, trail, limit):
            if candidate is not None and candidate.should_exit:
                decision = candidate
                break

        if decision and decision.should_exit:
            logger.warning(
                "exit_condition_met",
                token=pos.symbol,
                price=price,
                reason=decision.reason,
                entry_price=pos.entry_price,
                unrealized_pnl=round(pos.unrealized_pnl(price), 4),
            )
        return decision

    def _check_stop_loss(self, pos: ManagedPosition, price: float) -> Optional[ExitDecision]:
        if pos.stop_loss is not None and price <= pos.stop_loss:
            return ExitDecision(should_exit=True, reason="STOP_LOSS")
        return None

    def _check_take_profit(self, pos: ManagedPosition, price: float) -> Optional[ExitDecision]:
        if pos.take_profit is not None and price >= pos.take_profit:
            return ExitDecision(should_exit=True, reason="TAKE_PROFIT")
        return None

    def _check_trailing_stop(self, pos: ManagedPosition, price: float) -> Optional[ExitDecision]:
        if pos.trailing_stop_pct is None:
            return None
        trail_price = pos.highest_price * (1 - pos.trailing_stop_pct / 100.0)
        if price <= trail_price:
            return ExitDecision(should_exit=True, reason="TRAILING_STOP")
        return None

    def _check_time_limit(self, pos: ManagedPosition) -> Optional[ExitDecision]:
        import time as _time

        elapsed_hours = (_time.time() - pos.opened_at) / 3600.0
        if elapsed_hours >= pos.max_duration_hours:
            return ExitDecision(should_exit=True, reason="TIME_LIMIT")
        return None

    # ---------------------------------------------------------------- helpers
    def total_exposure(self, prices: dict[str, float]) -> float:
        total = 0.0
        for addr, pos in self._positions.items():
            price = prices.get(addr, pos.entry_price)
            total += pos.current_value(price)
        return total

    def total_unrealized_pnl(self, prices: dict[str, float]) -> float:
        total = 0.0
        for addr, pos in self._positions.items():
            price = prices.get(addr, pos.entry_price)
            total += pos.unrealized_pnl(price)
        return total
