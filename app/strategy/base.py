from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.scanner.models import MarketSnapshot


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    WATCH = "WATCH"
    REJECT = "REJECT"


class StrategySignal(BaseModel):
    signal: SignalType
    score: int = Field(ge=0, le=100, default=0)
    reasons: list[str] = Field(default_factory=list)
    token_address: str = ""
    symbol: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)

    @property
    def is_buy(self) -> bool:
        return self.signal == SignalType.BUY

    @property
    def is_sell(self) -> bool:
        return self.signal == SignalType.SELL


class StrategyContext(BaseModel):
    snapshot: MarketSnapshot
    risk_score: Optional[int] = None
    token_age_hours: Optional[float] = None
    has_mint_authority: Optional[bool] = None
    has_freeze_authority: Optional[bool] = None
    liquidity_change_5m: Optional[float] = None


class BaseStrategy(ABC):
    def __init__(self, name: str = "base") -> None:
        self.name = name

    @abstractmethod
    async def analyze(self, context: StrategyContext) -> StrategySignal:
        ...

    @abstractmethod
    def generate_signal(self, context: StrategyContext, score: int, reasons: list[str]) -> StrategySignal:
        ...
