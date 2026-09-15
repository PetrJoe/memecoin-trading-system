from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.config import get_settings
from app.scanner.models import MarketSnapshot


@dataclass
class FilterResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)


class TokenFilter:
    def __init__(
        self,
        min_liquidity_usd: Optional[float] = None,
        min_volume_5m_usd: Optional[float] = None,
        min_buys_5m: int = 0,
        min_sells_5m: int = 0,
        min_buy_sell_ratio: float = 0.0,
        max_token_age_hours: Optional[float] = None,
        min_price: float = 0.0,
        max_price: float = float("inf"),
        chain: str = "solana",
    ) -> None:
        self.min_liquidity_usd = min_liquidity_usd
        self.min_volume_5m_usd = min_volume_5m_usd
        self.min_buys_5m = min_buys_5m
        self.min_sells_5m = min_sells_5m
        self.min_buy_sell_ratio = min_buy_sell_ratio
        self.max_token_age_hours = max_token_age_hours
        self.min_price = min_price
        self.max_price = max_price
        self.chain = chain

    @classmethod
    def from_settings(cls) -> TokenFilter:
        settings = get_settings()
        return cls(
            min_liquidity_usd=settings.MIN_LIQUIDITY_USD,
            min_volume_5m_usd=settings.MIN_VOLUME_5M_USD,
        )

    def check(self, snapshot: MarketSnapshot) -> FilterResult:
        reasons: list[str] = []

        if self.min_liquidity_usd is not None:
            if snapshot.liquidity is None or snapshot.liquidity < self.min_liquidity_usd:
                reasons.append(
                    f"Liquidity ${snapshot.liquidity or 0:,.0f} < ${self.min_liquidity_usd:,.0f}"
                )

        if self.min_volume_5m_usd is not None:
            vol = snapshot.volume_5m or 0.0
            if vol < self.min_volume_5m_usd:
                reasons.append(
                    f"Volume 5m ${vol:,.0f} < ${self.min_volume_5m_usd:,.0f}"
                )

        if self.min_buys_5m > 0:
            if snapshot.buys_5m < self.min_buys_5m:
                reasons.append(
                    f"Buys 5m {snapshot.buys_5m} < {self.min_buys_5m}"
                )

        if self.min_sells_5m > 0:
            if snapshot.sells_5m < self.min_sells_5m:
                reasons.append(
                    f"Sells 5m {snapshot.sells_5m} < {self.min_sells_5m}"
                )

        if self.min_buy_sell_ratio > 0:
            total = snapshot.buys_5m + snapshot.sells_5m
            if total > 0:
                ratio = snapshot.buys_5m / total
                if ratio < self.min_buy_sell_ratio:
                    reasons.append(
                        f"Buy/sell ratio {ratio:.2f} < {self.min_buy_sell_ratio:.2f}"
                    )

        if self.max_token_age_hours is not None and snapshot.pair_created_at:
            age_hours = (datetime.now(timezone.utc) - snapshot.pair_created_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600
            if age_hours > self.max_token_age_hours:
                reasons.append(
                    f"Token age {age_hours:.1f}h > {self.max_token_age_hours:.1f}h"
                )

        if snapshot.price < self.min_price:
            reasons.append(f"Price ${snapshot.price} < ${self.min_price}")

        if snapshot.price > self.max_price:
            reasons.append(f"Price ${snapshot.price} > ${self.max_price}")

        return FilterResult(passed=len(reasons) == 0, reasons=reasons)
