from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from app.config import get_logger, get_settings

logger = get_logger(category="application")


@dataclass
class DependencyHealth:
    name: str
    status: str  # ok | degraded | error | unknown
    latency_ms: Optional[float] = None
    detail: str = ""
    checked_at: float = field(default_factory=time.time)


class HealthChecker:
    """
    Probe dependencies and aggregate an overall status:
      - ok:       everything reachable
      - degraded: some non-critical dependency failing (scanner, web)
      - error:    critical dependency failing (database in DB mode, RPC in live mode)
    """

    def __init__(self, database_url: Optional[str] = None) -> None:
        self.settings = get_settings()
        self.database_url = database_url or self.settings.DATABASE_URL
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def check_database(self) -> DependencyHealth:
        """DB-free paper mode reports database as 'disabled' (ok)."""
        start = time.monotonic()
        try:
            from app.database.database import engine

            if engine is None:
                return DependencyHealth(
                    name="database", status="ok", detail="disabled (in-memory paper mode)"
                )
            from sqlalchemy import text

            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            latency = (time.monotonic() - start) * 1000
            return DependencyHealth(name="database", status="ok", latency_ms=round(latency, 1))
        except Exception as e:
            return DependencyHealth(name="database", status="error", detail=str(e)[:200])

    async def check_rpc(self) -> DependencyHealth:
        """Ping the Solana RPC endpoint with a getHealth request."""
        start = time.monotonic()
        try:
            client = await self._get_client()
            resp = await client.post(
                self.settings.SOLANA_RPC_URL,
                json={"jsonrpc": "2.0", "id": 1, "method": "getHealth"},
            )
            latency = (time.monotonic() - start) * 1000
            if resp.status_code == 200:
                return DependencyHealth(name="solana_rpc", status="ok", latency_ms=round(latency, 1))
            return DependencyHealth(
                name="solana_rpc", status="degraded", detail=f"HTTP {resp.status_code}",
                latency_ms=round(latency, 1),
            )
        except Exception as e:
            return DependencyHealth(name="solana_rpc", status="degraded", detail=str(e)[:200])

    async def check_scanner(self) -> DependencyHealth:
        start = time.monotonic()
        try:
            client = await self._get_client()
            resp = await client.get("https://api.dexscreener.com/token-boosts/latest/v1")
            latency = (time.monotonic() - start) * 1000
            if resp.status_code == 200:
                return DependencyHealth(name="dex_screener", status="ok", latency_ms=round(latency, 1))
            return DependencyHealth(
                name="dex_screener", status="degraded", detail=f"HTTP {resp.status_code}",
                latency_ms=round(latency, 1),
            )
        except Exception as e:
            return DependencyHealth(name="dex_screener", status="degraded", detail=str(e)[:200])

    async def check_jupiter(self) -> DependencyHealth:
        start = time.monotonic()
        try:
            client = await self._get_client()
            resp = await client.get(f"{self.settings.JUPITER_API_URL.rstrip('/')}/health")
            latency = (time.monotonic() - start) * 1000
            if resp.status_code in (200, 404):  # 404 => endpoint exists but no /health route
                return DependencyHealth(name="jupiter", status="ok", latency_ms=round(latency, 1))
            return DependencyHealth(
                name="jupiter", status="degraded", detail=f"HTTP {resp.status_code}",
                latency_ms=round(latency, 1),
            )
        except Exception as e:
            return DependencyHealth(name="jupiter", status="degraded", detail=str(e)[:200])

    async def check_all(self) -> list[DependencyHealth]:
        results = await asyncio_gather_safe(
            self.check_database(), self.check_rpc(), self.check_scanner(), self.check_jupiter()
        )
        return list(results)

    def aggregate(self, checks: list[DependencyHealth]) -> str:
        statuses = [c.status for c in checks]
        if any(s == "error" for s in statuses):
            return "error"
        if any(s == "degraded" for s in statuses):
            return "degraded"
        return "ok"


async def asyncio_gather_safe(*coroutines):
    import asyncio

    return await asyncio.gather(*coroutines)
