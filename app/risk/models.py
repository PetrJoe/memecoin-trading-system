from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RiskCheckType(str, Enum):
    LIQUIDITY = "LIQUIDITY"
    LIQUIDITY_CHANGE = "LIQUIDITY_CHANGE"
    TOKEN_AGE = "TOKEN_AGE"
    BUY_SELL_RATIO = "BUY_SELL_RATIO"
    VOLUME = "VOLUME"
    HOLDER_CONCENTRATION = "HOLDER_CONCENTRATION"
    MINT_AUTHORITY = "MINT_AUTHORITY"
    FREEZE_AUTHORITY = "FREEZE_AUTHORITY"
    SUSPICIOUS_TOKEN = "SUSPICIOUS_TOKEN"
    PRICE_IMPACT = "PRICE_IMPACT"
    SLIPPAGE = "SLIPPAGE"
    WALLET_EXPOSURE = "WALLET_EXPOSURE"
    POSITION_EXPOSURE = "POSITION_EXPOSURE"
    DAILY_LOSS = "DAILY_LOSS"
    CONSECUTIVE_LOSSES = "CONSECUTIVE_LOSSES"
    BALANCE_TOO_LOW = "BALANCE_TOO_LOW"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"


class RiskWarning(BaseModel):
    check_type: RiskCheckType
    message: str
    severity: str = "warning"


class RiskResult(BaseModel):
    approved: bool
    score: int = Field(ge=0, le=100, default=0)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[RiskWarning] = Field(default_factory=list)
    critical_failures: list[str] = Field(default_factory=list)

    @property
    def has_critical_failures(self) -> bool:
        return len(self.critical_failures) > 0


class TokenRiskData(BaseModel):
    token_address: str
    symbol: str = ""
    liquidity: Optional[float] = None
    liquidity_change_5m: Optional[float] = None
    volume_5m: Optional[float] = None
    volume_1h: Optional[float] = None
    buys_5m: int = 0
    sells_5m: int = 0
    buys_1h: int = 0
    sells_1h: int = 0
    price: float = 0.0
    price_change_5m: Optional[float] = None
    token_age_hours: Optional[float] = None
    has_mint_authority: Optional[bool] = None
    has_freeze_authority: Optional[bool] = None


class PortfolioRiskData(BaseModel):
    wallet_balance_usd: float = 0.0
    total_exposure_usd: float = 0.0
    open_positions: int = 0
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    daily_loss_usd: float = 0.0
    max_position_usd: float = 0.50
    max_open_positions: int = 2
    max_daily_loss_usd: float = 1.00
    max_total_exposure_usd: float = 5.00
    max_slippage_bps: int = 100
    max_price_impact_bps: int = 500
    max_consecutive_losses: int = 5
