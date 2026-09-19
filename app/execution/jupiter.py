from __future__ import annotations

import asyncio
import time
from typing import Optional

import base58
import httpx
import structlog

from app.config import get_logger, get_settings
from app.execution.quote import (
    QuoteRequest,
    QuoteResponse,
    SwapRequest,
    SwapTransaction,
)

logger = get_logger(category="application")

MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0


class JupiterClientError(Exception):
    pass


class JupiterQuoteError(JupiterClientError):
    pass


class JupiterSwapError(JupiterClientError):
    pass


class JupiterClient:
    def __init__(self, api_url: Optional[str] = None) -> None:
        settings = get_settings()
        self.api_url = (api_url or settings.JUPITER_API_URL).rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.api_url,
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        client = await self._get_client()
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            try:
                response = await getattr(client, method)(url, **kwargs)
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException as e:
                last_error = e
                logger.warning("jupiter_timeout", attempt=attempt + 1, url=url)
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 429:
                    backoff = INITIAL_BACKOFF * (2 ** attempt)
                    logger.warning("jupiter_rate_limited", attempt=attempt + 1, backoff=backoff)
                    await asyncio.sleep(backoff)
                elif e.response.status_code >= 500:
                    backoff = INITIAL_BACKOFF * (2 ** attempt)
                    logger.warning("jupiter_server_error", attempt=attempt + 1, status=e.response.status_code, backoff=backoff)
                    await asyncio.sleep(backoff)
                else:
                    raise JupiterClientError(f"HTTP {e.response.status_code}: {e}") from e
            except Exception as e:
                last_error = e
                logger.warning("jupiter_request_error", attempt=attempt + 1, error=str(e))

        raise JupiterClientError(f"Failed after {MAX_RETRIES} retries: {url}") from last_error

    async def get_quote(self, request: QuoteRequest) -> QuoteResponse:
        try:
            data = await self._request(
                "get",
                "/quote",
                params={
                    "inputMint": request.input_mint,
                    "outputMint": request.output_mint,
                    "amount": str(request.amount),
                    "slippageBps": request.slippage_bps,
                    "onlyDirectRoutes": request.only_direct_routes,
                    "swapMode": request.swap_mode.value,
                },
            )
            return QuoteResponse.model_validate(data)
        except JupiterClientError:
            raise
        except Exception as e:
            raise JupiterQuoteError(f"Failed to get quote: {e}") from e

    async def get_swap_transaction(self, request: SwapRequest) -> SwapTransaction:
        try:
            quote_data = request.quote_response.model_dump()
            data = await self._request(
                "post",
                "/swap",
                json={
                    "quoteResponse": quote_data,
                    "userPublicKey": request.user_public_key,
                    "wrapAndUnwrapSol": request.wrap_and_unwrap_sol,
                    "dynamicComputeUnitLimit": request.dynamic_compute_unit_limit,
                    "prioritizationFeeLamports": request.prioritization_fee_lamports,
                },
            )
            return SwapTransaction(**data)
        except JupiterClientError:
            raise
        except Exception as e:
            raise JupiterSwapError(f"Failed to get swap transaction: {e}") from e

    def decode_swap_transaction(self, swap_tx: SwapTransaction) -> bytes:
        return base58.b58decode(swap_tx.swap_transaction)
