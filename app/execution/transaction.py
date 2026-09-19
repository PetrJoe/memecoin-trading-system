from __future__ import annotations

import asyncio
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.config import get_logger

logger = get_logger(category="application")


class TransactionState(str, Enum):
    CREATED = "CREATED"
    QUOTE_REQUESTED = "QUOTE_REQUESTED"
    QUOTE_RECEIVED = "QUOTE_RECEIVED"
    RISK_APPROVED = "RISK_APPROVED"
    TRANSACTION_BUILT = "TRANSACTION_BUILT"
    SIGNED = "SIGNED"
    SUBMITTED = "SUBMITTED"
    CONFIRMING = "CONFIRMING"
    CONFIRMED = "CONFIRMED"

    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


TERMINAL_STATES = {
    TransactionState.CONFIRMED,
    TransactionState.FAILED,
    TransactionState.CANCELLED,
    TransactionState.EXPIRED,
}

VALID_TRANSITIONS: dict[TransactionState, set[TransactionState]] = {
    TransactionState.CREATED: {TransactionState.QUOTE_REQUESTED, TransactionState.FAILED, TransactionState.CANCELLED},
    TransactionState.QUOTE_REQUESTED: {TransactionState.QUOTE_RECEIVED, TransactionState.FAILED, TransactionState.EXPIRED},
    TransactionState.QUOTE_RECEIVED: {TransactionState.RISK_APPROVED, TransactionState.FAILED, TransactionState.CANCELLED},
    TransactionState.RISK_APPROVED: {TransactionState.TRANSACTION_BUILT, TransactionState.FAILED, TransactionState.CANCELLED},
    TransactionState.TRANSACTION_BUILT: {TransactionState.SIGNED, TransactionState.FAILED},
    TransactionState.SIGNED: {TransactionState.SUBMITTED, TransactionState.FAILED},
    TransactionState.SUBMITTED: {TransactionState.CONFIRMING, TransactionState.FAILED, TransactionState.UNKNOWN},
    TransactionState.CONFIRMING: {TransactionState.CONFIRMED, TransactionState.FAILED, TransactionState.UNKNOWN},
    TransactionState.UNKNOWN: {TransactionState.CONFIRMED, TransactionState.FAILED, TransactionState.CANCELLED},
}


class TransactionRecord(BaseModel):
    tx_id: str = ""
    token_address: str = ""
    input_mint: str = ""
    output_mint: str = ""
    amount: int = 0
    quote_price: float = 0.0
    state: TransactionState = TransactionState.CREATED
    error: Optional[str] = None
    tx_signature: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0


class TransactionManager:
    def __init__(self) -> None:
        self._records: dict[str, TransactionRecord] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, tx_id: str) -> asyncio.Lock:
        if tx_id not in self._locks:
            self._locks[tx_id] = asyncio.Lock()
        return self._locks[tx_id]

    def create(self, tx_id: str, token_address: str, input_mint: str, output_mint: str, amount: int) -> TransactionRecord:
        import time
        record = TransactionRecord(
            tx_id=tx_id,
            token_address=token_address,
            input_mint=input_mint,
            output_mint=output_mint,
            amount=amount,
            state=TransactionState.CREATED,
            created_at=time.time(),
            updated_at=time.time(),
        )
        self._records[tx_id] = record
        logger.info("tx_created", tx_id=tx_id, token=token_address)
        return record

    async def transition(self, tx_id: str, new_state: TransactionState, error: Optional[str] = None) -> TransactionRecord:
        import time
        lock = self._get_lock(tx_id)
        async with lock:
            record = self._records.get(tx_id)
            if record is None:
                raise ValueError(f"Unknown transaction: {tx_id}")

            if new_state not in VALID_TRANSITIONS.get(record.state, set()):
                raise ValueError(
                    f"Invalid transition: {record.state.value} -> {new_state.value}"
                )

            old_state = record.state
            record.state = new_state
            record.error = error
            record.updated_at = time.time()

            logger.info(
                "tx_transition",
                tx_id=tx_id,
                from_state=old_state.value,
                to_state=new_state.value,
            )
            return record

    def get(self, tx_id: str) -> Optional[TransactionRecord]:
        return self._records.get(tx_id)

    def get_all(self) -> list[TransactionRecord]:
        return list(self._records.values())

    def is_terminal(self, tx_id: str) -> bool:
        record = self._records.get(tx_id)
        if record is None:
            return True
        return record.state in TERMINAL_STATES

    def mark_unknown(self, tx_id: str) -> Optional[TransactionRecord]:
        record = self._records.get(tx_id)
        if record and record.state in {TransactionState.SUBMITTED, TransactionState.CONFIRMING}:
            record.state = TransactionState.UNKNOWN
            record.updated_at = __import__("time").time()
            logger.warning("tx_marked_unknown", tx_id=tx_id, state=record.state.value)
            return record
        return None
