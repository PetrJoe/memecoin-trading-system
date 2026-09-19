from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    ok: bool
    csrf_token: Optional[str] = None
    message: Optional[str] = None
    retry_after: Optional[int] = None


class LogoutResponse(BaseModel):
    ok: bool


class HealthResponse(BaseModel):
    status: str  # ok | degraded | error
    app: str
    database: str
    mode: str
    uptime_seconds: float


class PositionOut(BaseModel):
    position_id: int
    token_address: str
    symbol: str
    entry_price: float
    current_price: float
    quantity: float
    capital_usd: float
    value_usd: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    highest_price: float
    opened_at: float


class BalanceOut(BaseModel):
    cash_usd: float
    position_value_usd: float
    total_usd: float
    starting_balance_usd: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    total_pnl_pct: float
    total_fees: float


class PnLSummaryOut(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    net_pnl: float
    gross_profit: float
    gross_loss: float
    profit_factor: Optional[float] = None
    average_win: float
    average_loss: float
    best_trade_pnl: float
    worst_trade_pnl: float
    avg_holding_seconds: float
    consecutive_losses: int
    max_drawdown_pct: float
    total_fees: float


class CircuitBreakerOut(BaseModel):
    state: str
    can_trade: bool
    is_paused: bool
    recent_events: list[dict[str, Any]] = Field(default_factory=list)


class RiskOut(BaseModel):
    max_position_usd: float
    max_open_positions: int
    max_daily_loss_usd: float
    max_total_exposure_usd: float
    max_consecutive_losses: int
    current_open_positions: int
    current_exposure_usd: float
    consecutive_losses: int
    daily_net_pnl: float


class StatusResponse(BaseModel):
    mode: str
    trading_enabled: bool
    uptime_seconds: float
    circuit_breaker: CircuitBreakerOut
    balance: Optional[BalanceOut] = None
    open_positions: list[PositionOut] = Field(default_factory=list)
    pnl: Optional[PnLSummaryOut] = None
    risk: Optional[RiskOut] = None
    paper_mode: bool = True
    scans_completed: int = 0
    last_scan_at: float = 0.0


class EventOut(BaseModel):
    event_type: str
    level: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: float


class EventsResponse(BaseModel):
    events: list[EventOut]
    count: int


class ActionResponse(BaseModel):
    ok: bool
    message: str
    detail: Optional[dict[str, Any]] = None
