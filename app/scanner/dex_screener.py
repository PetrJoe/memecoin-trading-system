from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx

from app.config import get_logger
from app.scanner.models import DexScreenerPair, MarketSnapshot

logger = get_logger(category="application")

BASE_URL = "https://api.dexscreener.com"
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0


class DexScreenerClientError(Exception):
    pass


class DexScreenerClient:
    def __init__(self, base_url: str = BASE_URL, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._last_request_time = 0.0
        self._min_interval = 1.0 / 55.0  # stay under 60 req/min

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={"Accept": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)

        client = await self._get_client()
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            try:
                response = await client.request(method, path, **kwargs)
                self._last_request_time = time.monotonic()

                if response.status_code == 429:
                    retry_after = float(response.headers.get("Retry-After", INITIAL_BACKOFF * (2 ** attempt)))
                    logger.warning("dex_screener_rate_limit", path=path, retry_after=retry_after)
                    await asyncio.sleep(retry_after)
                    continue

                if response.status_code >= 500:
                    backoff = INITIAL_BACKOFF * (2 ** attempt)
                    logger.warning(
                        "dex_screener_server_error",
                        path=path,
                        status=response.status_code,
                        backoff=backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue

                response.raise_for_status()
                return response

            except httpx.TimeoutException as e:
                last_error = e
                backoff = INITIAL_BACKOFF * (2 ** attempt)
                logger.warning("dex_screener_timeout", path=path, attempt=attempt + 1, backoff=backoff)
                await asyncio.sleep(backoff)
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code < 500:
                    raise DexScreenerClientError(f"HTTP {e.response.status_code}: {path}") from e
                backoff = INITIAL_BACKOFF * (2 ** attempt)
                await asyncio.sleep(backoff)
            except httpx.RequestError as e:
                last_error = e
                backoff = INITIAL_BACKOFF * (2 ** attempt)
                logger.warning("dex_screener_request_error", path=path, error=str(e), backoff=backoff)
                await asyncio.sleep(backoff)

        raise DexScreenerClientError(f"Failed after {MAX_RETRIES} retries: {path}") from last_error

    async def get_token_pairs(self, chain_id: str, token_address: str) -> list[DexScreenerPair]:
        try:
            response = await self._request("GET", f"/tokens/v1/{chain_id}/{token_address}")
            data = response.json()
            if not isinstance(data, list):
                data = [data] if data else []
            return [DexScreenerPair.model_validate(item) for item in data]
        except DexScreenerClientError:
            raise
        except Exception as e:
            raise DexScreenerClientError(f"Failed to parse token pairs: {e}") from e

    async def search_pairs(self, query: str) -> list[DexScreenerPair]:
        try:
            response = await self._request("GET", "/latest/dex/search", params={"q": query})
            data = response.json()
            pairs = data.get("pairs") or data.get("pair") or []
            if isinstance(pairs, dict):
                pairs = [pairs]
            return [DexScreenerPair.model_validate(item) for item in pairs if item.get("chainId") == "solana"]
        except DexScreenerClientError:
            raise
        except Exception as e:
            raise DexScreenerClientError(f"Failed to parse search results: {e}") from e

    async def get_solana_pairs(self, query: str = "") -> list[MarketSnapshot]:
        if query:
            pairs = await self.search_pairs(query)
        else:
            pairs = await self._get_trending_solana()

        return [MarketSnapshot.from_pair(pair) for pair in pairs]

    async def _get_trending_solana(self) -> list[DexScreenerPair]:
        try:
            response = await self._request("GET", "/token-boosts/latest/v1")
            data = response.json()
            if not isinstance(data, list):
                return []

            solana_addresses = [
                item.get("tokenAddress", "")
                for item in data
                if item.get("chainId") == "solana" and item.get("tokenAddress")
            ]

            if not solana_addresses:
                return []

            all_pairs: list[DexScreenerPair] = []
            batch_size = 30
            for i in range(0, len(solana_addresses), batch_size):
                batch = solana_addresses[i : i + batch_size]
                addr_str = ",".join(batch)
                try:
                    response = await self._request("GET", f"/tokens/v1/solana/{addr_str}")
                    data = response.json()
                    if isinstance(data, list):
                        for item in data:
                            pair = DexScreenerPair.model_validate(item)
                            all_pairs.append(pair)
                except DexScreenerClientError:
                    continue

            return all_pairs
        except Exception as e:
            logger.warning("dex_screener_trending_failed", error=str(e))
            return []

    async def get_new_solana_pairs(
        self,
        max_age_seconds: int = 3600,
        min_liquidity_usd: float = 0.0,
        limit: int = 50,
    ) -> list[MarketSnapshot]:
        """
        Fetch recently created Solana pairs from DexScreener.
        Uses the token-profiles/latest endpoint to discover brand-new tokens,
        then enriches them with pair data.
        """
        try:
            # Step 1: Get latest token profiles (newly launched tokens)
            response = await self._request("GET", "/token-profiles/latest/v1")
            data = response.json()
            if not isinstance(data, list):
                return []

            # Filter to Solana tokens only
            solana_tokens = [
                item.get("tokenAddress", "")
                for item in data
                if item.get("chainId") == "solana" and item.get("tokenAddress")
            ]

            if not solana_tokens:
                return []

            # Step 2: Fetch pair data for these new tokens (batched)
            all_pairs: list[DexScreenerPair] = []
            batch_size = 30
            for i in range(0, len(solana_tokens), batch_size):
                batch = solana_tokens[i : i + batch_size]
                addr_str = ",".join(batch)
                try:
                    resp = await self._request("GET", f"/tokens/v1/solana/{addr_str}")
                    items = resp.json()
                    if isinstance(items, list):
                        for item in items:
                            try:
                                pair = DexScreenerPair.model_validate(item)
                                all_pairs.append(pair)
                            except Exception:
                                continue
                except DexScreenerClientError:
                    continue

            # Step 3: Filter by age and liquidity, convert to MarketSnapshot
            now_ms = int(__import__("time").time() * 1000)
            cutoff_ms = now_ms - (max_age_seconds * 1000)
            snapshots: list[MarketSnapshot] = []

            for pair in all_pairs:
                # Check age
                if pair.pair_created_at and pair.pair_created_at < cutoff_ms:
                    continue

                # Check minimum liquidity
                liq = pair.liquidity.usd if pair.liquidity and pair.liquidity.usd else 0.0
                if liq < min_liquidity_usd:
                    continue

                snapshot = MarketSnapshot.from_pair(pair)
                snapshots.append(snapshot)

                if len(snapshots) >= limit:
                    break

            logger.info(
                "new_solana_pairs_fetched",
                total_pairs=len(all_pairs),
                filtered=len(snapshots),
                max_age_s=max_age_seconds,
            )
            return snapshots

        except Exception as e:
            logger.warning("dex_screener_new_pairs_failed", error=str(e))
            return []
