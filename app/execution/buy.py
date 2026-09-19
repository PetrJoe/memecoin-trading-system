from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.config import get_logger, get_settings
from app.execution.jupiter import JupiterClient, JupiterClientError
from app.execution.quote import QuoteRequest, QuoteResponse, SwapRequest, SwapTransaction
from app.execution.transaction import TransactionManager, TransactionState

logger = get_logger(category="trades")


class BuyResult(BaseModel):
    success: bool
    tx_signature: Optional[str] = None
    input_amount: int = 0
    output_amount: int = 0
    price_impact_pct: float = 0.0
    error: Optional[str] = None


class BuyExecutor:
    def __init__(
        self,
        jupiter: JupiterClient,
        tx_manager: TransactionManager,
        solana_rpc_url: Optional[str] = None,
    ) -> None:
        self._jupiter = jupiter
        self._tx_manager = tx_manager
        settings = get_settings()
        self._solana_rpc_url = solana_rpc_url or settings.SOLANA_RPC_URL

    async def execute(
        self,
        token_address: str,
        input_amount_lamports: int,
        user_public_key: str,
        slippage_bps: int = 100,
    ) -> BuyResult:
        tx_id = f"buy_{token_address}_{int(time.time() * 1000)}"
        record = self._tx_manager.create(
            tx_id=tx_id,
            token_address=token_address,
            input_mint="So11111111111111111111111111111111111111112",
            output_mint=token_address,
            amount=input_amount_lamports,
        )

        try:
            await self._tx_manager.transition(tx_id, TransactionState.QUOTE_REQUESTED)

            quote_request = QuoteRequest(
                input_mint="So11111111111111111111111111111111111111112",
                output_mint=token_address,
                amount=input_amount_lamports,
                slippage_bps=slippage_bps,
            )

            quote = await self._jupiter.get_quote(quote_request)
            await self._tx_manager.transition(tx_id, TransactionState.QUOTE_RECEIVED)
            record.quote_price = quote.out_amount / max(quote.in_amount, 1)

            logger.info(
                "buy_quote_received",
                tx_id=tx_id,
                token=token_address,
                in_amount=quote.in_amount,
                out_amount=quote.out_amount,
                price_impact_pct=quote.price_impact_pct,
            )

            await self._tx_manager.transition(tx_id, TransactionState.RISK_APPROVED)

            swap_request = SwapRequest(
                quote_response=quote_request,
                user_public_key=user_public_key,
            )

            swap_tx = await self._jupiter.get_swap_transaction(swap_request)
            await self._tx_manager.transition(tx_id, TransactionState.TRANSACTION_BUILT)

            signed_bytes = self._jupiter.decode_swap_transaction(swap_tx)
            await self._tx_manager.transition(tx_id, TransactionState.SIGNED)

            signature = await self._broadcast_transaction(signed_bytes)
            record.tx_signature = signature
            await self._tx_manager.transition(tx_id, TransactionState.SUBMITTED)

            confirmed = await self._confirm_transaction(signature)
            if confirmed:
                await self._tx_manager.transition(tx_id, TransactionState.CONFIRMED)
                logger.info("buy_confirmed", tx_id=tx_id, token=token_address, signature=signature)
            else:
                await self._tx_manager.transition(tx_id, TransactionState.CONFIRMING)
                logger.warning("buy_confirming", tx_id=tx_id, token=token_address, signature=signature)

            return BuyResult(
                success=confirmed,
                tx_signature=signature,
                input_amount=quote.in_amount,
                output_amount=quote.out_amount,
                price_impact_pct=quote.price_impact_pct,
            )

        except JupiterClientError as e:
            await self._tx_manager.transition(tx_id, TransactionState.FAILED, error=str(e))
            logger.error("buy_failed", tx_id=tx_id, token=token_address, error=str(e))
            return BuyResult(success=False, error=str(e))
        except Exception as e:
            await self._tx_manager.transition(tx_id, TransactionState.FAILED, error=str(e))
            logger.error("buy_failed_unexpected", tx_id=tx_id, token=token_address, error=str(e))
            return BuyResult(success=False, error=str(e))

    async def _broadcast_transaction(self, raw_tx: bytes) -> str:
        from solders.rpc.config import RpcTransactionConfig
        from solders.rpc.requests import SendTransaction
        from solana.rpc.async_api import AsyncClient

        client = AsyncClient(self._solana_rpc_url)
        try:
            tx = SendTransaction.from_bytes(raw_tx)
            response = await client.send_transaction(
                tx,
                opts=RpcTransactionConfig(
                    encoding="base64",
                    skip_preflight=True,
                ),
            )
            return str(response.value)
        finally:
            await client.close()

    async def _confirm_transaction(self, signature: str, timeout: float = 60.0) -> bool:
        from solana.rpc.async_api import AsyncClient
        from solana.rpc.commitment import Confirmed

        client = AsyncClient(self._solana_rpc_url)
        try:
            elapsed = 0.0
            interval = 2.0
            while elapsed < timeout:
                try:
                    result = await client.confirm_transaction(signature, commitment=Confirmed)
                    if result.value:
                        return True
                except Exception:
                    pass
                await asyncio.sleep(interval)
                elapsed += interval
            return False
        finally:
            await client.close()
