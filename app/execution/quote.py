from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SwapMode(str, Enum):
    EXACT_IN = "ExactIn"
    EXACT_OUT = "ExactOut"


class QuoteRequest(BaseModel):
    input_mint: str
    output_mint: str
    amount: int
    slippage_bps: int = 100
    only_direct_routes: bool = False
    swap_mode: SwapMode = SwapMode.EXACT_IN


class RoutePlan(BaseModel):
    swap_info: dict
    percent: int


class QuoteResponse(BaseModel):
    model_config = {"populate_by_name": True}

    input_mint: str = Field(alias="inputMint")
    in_amount: int = Field(alias="inAmount")
    output_mint: str = Field(alias="outputMint")
    out_amount: int = Field(alias="outAmount")
    other_amount_threshold: int = Field(alias="otherAmountThreshold")
    swap_mode: str = Field(alias="swapMode")
    slippage_bps: int = Field(alias="slippageBps")
    price_impact_pct: float = Field(alias="priceImpactPct", default=0.0)
    route_plan: list[RoutePlan] = Field(default_factory=list, alias="routePlan")

    @property
    def price_impact_bps(self) -> float:
        return abs(self.price_impact_pct) * 100

    @property
    def price_impact_exceeds(self, bps: float) -> bool:
        return self.price_impact_bps > bps


class SwapTransaction(BaseModel):
    swap_transaction: str
    last_valid_block_height: int
    prioritization_fee_lamports: int


class SwapRequest(BaseModel):
    quote_response: QuoteRequest
    user_public_key: str
    wrap_and_unwrap_sol: bool = True
    dynamic_compute_unit_limit: bool = True
    prioritization_fee_lamports: int | str = "auto"
