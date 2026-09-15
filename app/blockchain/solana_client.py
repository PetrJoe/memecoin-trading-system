from __future__ import annotations

import asyncio
from typing import Optional

from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from app.config import get_logger, get_settings

logger = get_logger(category="application")

MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0


class SolanaClientError(Exception):
    pass


class SolanaClient:
    def __init__(self, rpc_url: Optional[str] = None) -> None:
        settings = get_settings()
        self.rpc_url = rpc_url or settings.SOLANA_RPC_URL
        self._client: Optional[AsyncClient] = None

    async def _get_client(self) -> AsyncClient:
        if self._client is None:
            self._client = AsyncClient(self.rpc_url, commitment=Confirmed)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def _request(self, method: str, *args, **kwargs):
        client = await self._get_client()
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            try:
                func = getattr(client, method)
                response = await func(*args, **kwargs)
                return response.value
            except Exception as e:
                last_error = e
                backoff = INITIAL_BACKOFF * (2 ** attempt)
                logger.warning(
                    "solana_rpc_error",
                    method=method,
                    attempt=attempt + 1,
                    error=str(e),
                    backoff=backoff,
                )
                await asyncio.sleep(backoff)

        raise SolanaClientError(f"Failed after {MAX_RETRIES} retries: {method}") from last_error

    async def get_balance(self, pubkey: Pubkey) -> float:
        lamports = await self._request("get_balance", pubkey)
        return lamports / 1e9

    async def get_token_accounts_by_owner(self, owner: Pubkey) -> list[dict]:
        response = await self._request(
            "get_token_accounts_by_owner",
            owner,
            opts={"programId": Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")},
        )
        accounts = []
        for item in response:
            account = item.account
            data = account.data
            if hasattr(data, "parsed"):
                parsed = data.parsed
                accounts.append({
                    "mint": parsed.get("info", {}).get("mint", ""),
                    "amount": parsed.get("info", {}).get("tokenAmount", {}).get("uiAmount", 0),
                    "decimals": parsed.get("info", {}).get("tokenAmount", {}).get("decimals", 0),
                })
        return accounts

    async def get_recent_blockhash(self) -> str:
        response = await self._request("get_latest_blockhash")
        return str(response.blockhash)

    async def confirm_transaction(self, signature: str, timeout: float = 30.0) -> bool:
        client = await self._get_client()
        sig = signature
        elapsed = 0.0
        interval = 2.0

        while elapsed < timeout:
            try:
                result = await client.confirm_transaction(sig, commitment=Confirmed)
                if result.value:
                    return True
            except Exception:
                pass
            await asyncio.sleep(interval)
            elapsed += interval

        return False

    async def get_signature_status(self, signature: str) -> Optional[dict]:
        client = await self._get_client()
        try:
            result = await client.get_signature_statuses([signature])
            if result.value and result.value[0]:
                status = result.value[0]
                return {
                    "confirmation_status": str(status.confirmation_status) if status.confirmation_status else None,
                    "err": status.err,
                    "slot": status.slot,
                }
        except Exception as e:
            logger.warning("solana_signature_status_error", error=str(e))
        return None
