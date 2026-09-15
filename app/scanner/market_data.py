from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_logger
from app.database.repositories import MarketSnapshotRepository, TokenRepository
from app.scanner.dex_screener import DexScreenerClient, DexScreenerClientError
from app.scanner.models import MarketSnapshot

logger = get_logger(category="application")


class MarketDataService:
    def __init__(self, dex_client: DexScreenerClient) -> None:
        self.dex_client = dex_client

    async def get_latest_snapshot(
        self,
        session: AsyncSession,
        token_address: str,
    ) -> Optional[MarketSnapshot]:
        token_repo = TokenRepository(session)
        snapshot_repo = MarketSnapshotRepository(session)

        token = await token_repo.get_by_address(token_address)
        if not token:
            return None

        try:
            pairs = await self.dex_client.get_token_pairs("solana", token_address)
        except DexScreenerClientError as e:
            logger.warning("market_data_fetch_failed", token=token_address[:12], error=str(e))
            return None

        if not pairs:
            return None

        best_pair = max(
            pairs,
            key=lambda p: (p.liquidity.usd if p.liquidity else 0) or 0,
        )
        snapshot = MarketSnapshot.from_pair(best_pair)

        await snapshot_repo.create(
            token_id=token.id,
            price=snapshot.price,
            liquidity=snapshot.liquidity,
            volume_5m=snapshot.volume_5m,
            volume_1h=snapshot.volume_1h,
            volume_6h=snapshot.volume_6h,
            volume_24h=snapshot.volume_24h,
            buys=snapshot.buys_5m,
            sells=snapshot.sells_5m,
            market_cap=snapshot.market_cap,
        )

        return snapshot

    async def get_price(
        self,
        session: AsyncSession,
        token_address: str,
    ) -> Optional[float]:
        snapshot = await self.get_latest_snapshot(session, token_address)
        return snapshot.price if snapshot else None
