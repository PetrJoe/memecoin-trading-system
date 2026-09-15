from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TokenInfo(BaseModel):
    address: str
    name: str
    symbol: str


class LiquidityInfo(BaseModel):
    usd: Optional[float] = None
    base: float = 0.0
    quote: float = 0.0


class TxnInfo(BaseModel):
    buys: int = 0
    sells: int = 0


class PriceChangeInfo(BaseModel):
    m5: Optional[float] = None
    h1: Optional[float] = None
    h6: Optional[float] = None
    h24: Optional[float] = None


class VolumeInfo(BaseModel):
    m5: Optional[float] = None
    h1: Optional[float] = None
    h6: Optional[float] = None
    h24: Optional[float] = None


class DexScreenerPair(BaseModel):
    chain_id: str = Field(alias="chainId")
    dex_id: str = Field(alias="dexId")
    pair_address: str = Field(alias="pairAddress")
    base_token: TokenInfo = Field(alias="baseToken")
    quote_token: Optional[TokenInfo] = Field(default=None, alias="quoteToken")
    price_native: Optional[str] = Field(default=None, alias="priceNative")
    price_usd: Optional[str] = Field(default=None, alias="priceUsd")
    txns: dict[str, TxnInfo] = Field(default_factory=dict)
    volume: VolumeInfo = Field(default_factory=VolumeInfo)
    price_change: Optional[PriceChangeInfo] = Field(default=None, alias="priceChange")
    liquidity: Optional[LiquidityInfo] = None
    fdv: Optional[float] = None
    market_cap: Optional[float] = Field(default=None, alias="marketCap")
    pair_created_at: Optional[int] = Field(default=None, alias="pairCreatedAt")

    model_config = {"populate_by_name": True}


class MarketSnapshot(BaseModel):
    token_address: str
    pair_address: str
    symbol: str
    name: str
    price: float
    liquidity: Optional[float] = None
    market_cap: Optional[float] = None
    fdv: Optional[float] = None
    volume_5m: Optional[float] = None
    volume_1h: Optional[float] = None
    volume_6h: Optional[float] = None
    volume_24h: Optional[float] = None
    price_change_m5: Optional[float] = None
    price_change_h1: Optional[float] = None
    price_change_h6: Optional[float] = None
    price_change_h24: Optional[float] = None
    buys_5m: int = 0
    sells_5m: int = 0
    buys_1h: int = 0
    sells_1h: int = 0
    buys_24h: int = 0
    sells_24h: int = 0
    pair_created_at: Optional[datetime] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    dex: str = ""

    @classmethod
    def from_pair(cls, pair: DexScreenerPair) -> MarketSnapshot:
        price = float(pair.price_usd) if pair.price_usd else 0.0

        buys_5m = 0
        sells_5m = 0
        buys_1h = 0
        sells_1h = 0
        buys_24h = 0
        sells_24h = 0

        if pair.txns:
            if "m5" in pair.txns:
                buys_5m = pair.txns["m5"].buys
                sells_5m = pair.txns["m5"].sells
            if "h1" in pair.txns:
                buys_1h = pair.txns["h1"].buys
                sells_1h = pair.txns["h1"].sells
            if "h24" in pair.txns:
                buys_24h = pair.txns["h24"].buys
                sells_24h = pair.txns["h24"].sells

        pair_created = None
        if pair.pair_created_at:
            pair_created = datetime.utcfromtimestamp(pair.pair_created_at / 1000)

        return cls(
            token_address=pair.base_token.address,
            pair_address=pair.pair_address,
            symbol=pair.base_token.symbol,
            name=pair.base_token.name,
            price=price,
            liquidity=pair.liquidity.usd if pair.liquidity else None,
            market_cap=pair.market_cap,
            fdv=pair.fdv,
            volume_5m=pair.volume.m5,
            volume_1h=pair.volume.h1,
            volume_6h=pair.volume.h6,
            volume_24h=pair.volume.h24,
            price_change_m5=pair.price_change.m5 if pair.price_change else None,
            price_change_h1=pair.price_change.h1 if pair.price_change else None,
            price_change_h6=pair.price_change.h6 if pair.price_change else None,
            price_change_h24=pair.price_change.h24 if pair.price_change else None,
            buys_5m=buys_5m,
            sells_5m=sells_5m,
            buys_1h=buys_1h,
            sells_1h=sells_1h,
            buys_24h=buys_24h,
            sells_24h=sells_24h,
            pair_created_at=pair_created,
            dex=pair.dex_id,
        )
