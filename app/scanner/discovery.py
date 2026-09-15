from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_logger, get_settings
from app.database.models import Token, TokenStatus
from app.database.repositories import MarketSnapshotRepository, TokenRepository
from app.scanner.dex_screener import DexScreenerClient, DexScreenerClientError
from app.scanner.filters import TokenFilter
from app.scanner.models import MarketSnapshot

logger = get_logger(category="application")


class TokenDiscovery:
    def __init__(
        self,
        dex_client: DexScreenerClient,
        token_filter: Optional[TokenFilter] = None,
    ) -> None:
        self.dex_client = dex_client
        self.token_filter = token_filter or TokenFilter.from_settings()
        self._seen_addresses: set[str] = set()

    async def scan(self, session: AsyncSession) -> list[MarketSnapshot]:
        settings = get_settings()
        token_repo = TokenRepository(session)
        snapshot_repo = MarketSnapshotRepository(session)

        try:
            snapshots = await self.dex_client.get_solana_pairs()
        except DexScreenerClientError as e:
            logger.error("discovery_scan_failed", error=str(e))
            return []

        candidates: list[MarketSnapshot] = []

        for snapshot in snapshots:
            if snapshot.token_address in self._seen_addresses:
                continue

            filter_result = self.token_filter.check(snapshot)
            if not filter_result.passed:
                logger.debug(
                    "token_filtered_out",
                    token=snapshot.symbol,
                    reasons=filter_result.reasons,
                )
                continue

            existing = await token_repo.get_by_address(snapshot.token_address)
            if existing is None:
                token = await token_repo.create(
                    address=snapshot.token_address,
                    symbol=snapshot.symbol,
                    name=snapshot.name,
                    status=TokenStatus.DISCOVERED,
                )
                logger.info(
                    "token_discovered",
                    token=snapshot.symbol,
                    address=snapshot.token_address[:12],
                    liquidity=snapshot.liquidity,
                    volume_5m=snapshot.volume_5m,
                )
            else:
                token = existing
                if existing.status == TokenStatus.REJECTED:
                    continue

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

            self._seen_addresses.add(snapshot.token_address)
            candidates.append(snapshot)

        return candidates
