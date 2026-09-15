from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from solders.pubkey import Pubkey

from app.config import get_logger

logger = get_logger(category="application")

SPL_TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
WSOL_MINT = So11111111111111111111111111111111111111112


@dataclass
class TokenBalance:
    mint: str
    amount: float
    decimals: int
    ui_amount: float


class TokenService:
    async def get_sol_balance(self, client, pubkey: Pubkey) -> float:
        try:
            return await client.get_balance(pubkey)
        except Exception as e:
            logger.warning("token_sol_balance_error", error=str(e))
            return 0.0

    async def get_token_balances(self, client, owner: Pubkey) -> list[TokenBalance]:
        try:
            accounts = await client.get_token_accounts_by_owner(owner)
            return [
                TokenBalance(
                    mint=acc.get("mint", ""),
                    amount=acc.get("amount", 0),
                    decimals=acc.get("decimals", 0),
                    ui_amount=acc.get("amount", 0),
                )
                for acc in accounts
            ]
        except Exception as e:
            logger.warning("token_balances_error", error=str(e))
            return []

    async def get_token_balance(self, client, owner: Pubkey, mint: str) -> Optional[float]:
        balances = await self.get_token_balances(client, owner)
        for b in balances:
            if b.mint == mint:
                return b.ui_amount
        return 0.0
