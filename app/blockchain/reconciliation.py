from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.config import get_logger
from app.database.models import Position, PositionStatus, Token

logger = get_logger(category="application")


@dataclass
class ReconciliationResult:
    matched: list[str] = field(default_factory=list)
    missing_in_db: list[str] = field(default_factory=list)
    missing_onchain: list[str] = field(default_factory=list)
    balance_mismatch: list[dict] = field(default_factory=list)
    is_consistent: bool = True

    @property
    def has_discrepancies(self) -> bool:
        return bool(self.missing_in_db or self.missing_onchain or self.balance_mismatch)


class ReconciliationService:
    async def reconcile(
        self,
        db_positions: list[Position],
        onchain_balances: dict[str, float],
        token_addresses: dict[int, str],
    ) -> ReconciliationResult:
        result = ReconciliationResult()

        db_token_map: dict[str, Position] = {}
        for pos in db_positions:
            if pos.status == PositionStatus.OPEN:
                addr = token_addresses.get(pos.token_id, "")
                if addr:
                    db_token_map[addr] = pos

        onchain_tokens = set(onchain_balances.keys())
        db_tokens = set(db_token_map.keys())

        for token_addr in db_tokens:
            if token_addr in onchain_tokens:
                result.matched.append(token_addr)
                pos = db_token_map[token_addr]
                onchain_amt = onchain_balances.get(token_addr, 0.0)
                if pos.quantity > 0 and abs(onchain_amt - pos.quantity) / max(pos.quantity, 1e-9) > 0.01:
                    result.balance_mismatch.append({
                        "token": token_addr,
                        "db_quantity": pos.quantity,
                        "onchain_quantity": onchain_amt,
                    })
            else:
                result.missing_onchain.append(token_addr)

        for token_addr in onchain_tokens - db_tokens:
            if token_addr != str(WSOL_MINT):
                result.missing_in_db.append(token_addr)

        result.is_consistent = not result.has_discrepancies

        if result.has_discrepancies:
            logger.warning(
                "reconciliation_discrepancies",
                missing_in_db=len(result.missing_in_db),
                missing_onchain=len(result.missing_onchain),
                balance_mismatches=len(result.balance_mismatch),
            )
        else:
            logger.info("reconciliation_complete", positions=len(db_positions))

        return result


WSOL_MINT = "So11111111111111111111111111111111111111112"
