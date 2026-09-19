from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from app.config import get_logger

logger = get_logger(category="trades")


@dataclass
class ClosedTrade:
    side: str = "SELL"
    token_address: str = ""
    symbol: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: float = 0.0
    capital_usd: float = 0.0
    proceeds_usd: float = 0.0
    fees_usd: float = 0.0
    pnl_usd: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    entry_time: float = 0.0
    exit_time: float = field(default_factory=time.time)

    @property
    def holding_time_seconds(self) -> float:
        return self.exit_time - self.entry_time

    @property
    def is_win(self) -> bool:
        return self.pnl_usd > 0


@dataclass
class PnLSummary:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_pnl: float = 0.0
    total_fees: float = 0.0
    best_trade_pnl: float = 0.0
    worst_trade_pnl: float = 0.0
    avg_holding_seconds: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.winning_trades / self.total_trades * 100.0 if self.total_trades else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_loss == 0:
            return float("inf") if self.gross_profit > 0 else 0.0
        return self.gross_profit / abs(self.gross_loss)

    @property
    def average_win(self) -> float:
        return self.gross_profit / self.winning_trades if self.winning_trades else 0.0

    @property
    def average_loss(self) -> float:
        return abs(self.gross_loss) / self.losing_trades if self.losing_trades else 0.0


class PnLCalculator:
    """Aggregates closed trades into P&L statistics."""

    def __init__(self) -> None:
        self._closed_trades: list[ClosedTrade] = []

    @property
    def closed_trades(self) -> list[ClosedTrade]:
        return list(self._closed_trades)

    def record_trade(self, trade: ClosedTrade) -> ClosedTrade:
        self._closed_trades.append(trade)
        logger.info(
            "pnl_trade_recorded",
            token=trade.symbol,
            pnl=round(trade.pnl_usd, 4),
            pnl_pct=round(trade.pnl_pct, 2),
            reason=trade.exit_reason,
            is_win=trade.is_win,
        )
        return trade

    def summary(self, trades: Optional[list[ClosedTrade]] = None) -> PnLSummary:
        trades = trades if trades is not None else self._closed_trades

        summary = PnLSummary(total_trades=len(trades))
        holding_times: list[float] = []

        for t in trades:
            if t.is_win:
                summary.winning_trades += 1
                summary.gross_profit += t.pnl_usd
            else:
                summary.losing_trades += 1
                summary.gross_loss += t.pnl_usd  # negative
            summary.net_pnl += t.pnl_usd
            summary.total_fees += t.fees_usd
            holding_times.append(t.holding_time_seconds)

        summary.best_trade_pnl = max((t.pnl_usd for t in trades), default=0.0)
        summary.worst_trade_pnl = min((t.pnl_usd for t in trades), default=0.0)
        summary.avg_holding_seconds = (
            sum(holding_times) / len(holding_times) if holding_times else 0.0
        )
        return summary

    def today(self) -> list[ClosedTrade]:
        """Trades closed since local midnight (UTC-based day boundary)."""
        midnight = time.time() - (time.time() % 86400)
        return [t for t in self._closed_trades if t.exit_time >= midnight]

    def daily_summary(self) -> PnLSummary:
        return self.summary(trades=self.today())

    def consecutive_losses(self) -> int:
        """Count trailing losses from the most recent trade backwards."""
        count = 0
        for t in reversed(self._closed_trades):
            if t.pnl_usd < 0:
                count += 1
            else:
                break
        return count

    def max_drawdown_pct(self, starting_equity: float) -> float:
        """
        Peak-to-trough drawdown of realized equity curve
        (starting equity + cumulative realized P&L).
        """
        if starting_equity <= 0:
            return 0.0
        equity = starting_equity
        peak = starting_equity
        max_dd = 0.0
        for t in self._closed_trades:
            equity += t.pnl_usd
            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100.0
            max_dd = max(max_dd, dd)
        return max_dd

    def reset(self) -> None:
        self._closed_trades.clear()
