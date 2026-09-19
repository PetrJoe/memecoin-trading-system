import time

import pytest

from app.execution.transaction import TransactionManager, TransactionState, TERMINAL_STATES


class TestTransactionManager:
    def test_create_record(self):
        tm = TransactionManager()
        record = tm.create(
            tx_id="tx_1",
            token_address="TokenAddr111111111111111111111111111111",
            input_mint="So11111111111111111111111111111111111111112",
            output_mint="TokenAddr111111111111111111111111111111",
            amount=1000000000,
        )
        assert record.tx_id == "tx_1"
        assert record.state == TransactionState.CREATED
        assert record.amount == 1000000000

    def test_get_record(self):
        tm = TransactionManager()
        tm.create(tx_id="tx_1", token_address="t", input_mint="a", output_mint="b", amount=100)
        assert tm.get("tx_1") is not None
        assert tm.get("tx_2") is None

    @pytest.mark.asyncio
    async def test_transition_valid(self):
        tm = TransactionManager()
        tm.create(tx_id="tx_1", token_address="t", input_mint="a", output_mint="b", amount=100)
        record = await tm.transition("tx_1", TransactionState.QUOTE_REQUESTED)
        assert record.state == TransactionState.QUOTE_REQUESTED

    @pytest.mark.asyncio
    async def test_transition_async(self):
        tm = TransactionManager()
        tm.create(tx_id="tx_1", token_address="t", input_mint="a", output_mint="b", amount=100)
        record = await tm.transition("tx_1", TransactionState.QUOTE_REQUESTED)
        assert record.state == TransactionState.QUOTE_REQUESTED

    @pytest.mark.asyncio
    async def test_transition_invalid(self):
        tm = TransactionManager()
        tm.create(tx_id="tx_1", token_address="t", input_mint="a", output_mint="b", amount=100)
        with pytest.raises(ValueError, match="Invalid transition"):
            await tm.transition("tx_1", TransactionState.CONFIRMED)

    @pytest.mark.asyncio
    async def test_transition_unknown_tx(self):
        tm = TransactionManager()
        with pytest.raises(ValueError, match="Unknown transaction"):
            await tm.transition("tx_1", TransactionState.QUOTE_REQUESTED)

    @pytest.mark.asyncio
    async def test_full_buy_flow(self):
        tm = TransactionManager()
        tm.create(tx_id="tx_1", token_address="t", input_mint="a", output_mint="b", amount=100)

        transitions = [
            TransactionState.QUOTE_REQUESTED,
            TransactionState.QUOTE_RECEIVED,
            TransactionState.RISK_APPROVED,
            TransactionState.TRANSACTION_BUILT,
            TransactionState.SIGNED,
            TransactionState.SUBMITTED,
            TransactionState.CONFIRMING,
            TransactionState.CONFIRMED,
        ]

        for state in transitions:
            record = await tm.transition("tx_1", state)
            assert record.state == state

    @pytest.mark.asyncio
    async def test_failure_from_created(self):
        tm = TransactionManager()
        tm.create(tx_id="tx_1", token_address="t", input_mint="a", output_mint="b", amount=100)
        record = await tm.transition("tx_1", TransactionState.FAILED)
        assert record.state == TransactionState.FAILED

    @pytest.mark.asyncio
    async def test_is_terminal(self):
        tm = TransactionManager()
        tm.create(tx_id="tx_1", token_address="t", input_mint="a", output_mint="b", amount=100)
        assert tm.is_terminal("tx_1") is False
        await tm.transition("tx_1", TransactionState.QUOTE_REQUESTED)
        await tm.transition("tx_1", TransactionState.QUOTE_RECEIVED)
        await tm.transition("tx_1", TransactionState.RISK_APPROVED)
        await tm.transition("tx_1", TransactionState.TRANSACTION_BUILT)
        await tm.transition("tx_1", TransactionState.SIGNED)
        await tm.transition("tx_1", TransactionState.SUBMITTED)
        await tm.transition("tx_1", TransactionState.CONFIRMING)
        await tm.transition("tx_1", TransactionState.CONFIRMED)
        assert tm.is_terminal("tx_1") is True

    def test_is_terminal_unknown(self):
        tm = TransactionManager()
        assert tm.is_terminal("nonexistent") is True

    def test_get_all(self):
        tm = TransactionManager()
        tm.create(tx_id="tx_1", token_address="t", input_mint="a", output_mint="b", amount=100)
        tm.create(tx_id="tx_2", token_address="t2", input_mint="a", output_mint="b", amount=200)
        all_records = tm.get_all()
        assert len(all_records) == 2

    @pytest.mark.asyncio
    async def test_failure_from_submitted(self):
        tm = TransactionManager()
        tm.create(tx_id="tx_1", token_address="t", input_mint="a", output_mint="b", amount=100)
        await tm.transition("tx_1", TransactionState.QUOTE_REQUESTED)
        await tm.transition("tx_1", TransactionState.QUOTE_RECEIVED)
        await tm.transition("tx_1", TransactionState.RISK_APPROVED)
        await tm.transition("tx_1", TransactionState.TRANSACTION_BUILT)
        await tm.transition("tx_1", TransactionState.SIGNED)
        await tm.transition("tx_1", TransactionState.SUBMITTED)
        record = await tm.transition("tx_1", TransactionState.FAILED)
        assert record.state == TransactionState.FAILED

    @pytest.mark.asyncio
    async def test_unknown_state_from_submitted(self):
        tm = TransactionManager()
        tm.create(tx_id="tx_1", token_address="t", input_mint="a", output_mint="b", amount=100)
        await tm.transition("tx_1", TransactionState.QUOTE_REQUESTED)
        await tm.transition("tx_1", TransactionState.QUOTE_RECEIVED)
        await tm.transition("tx_1", TransactionState.RISK_APPROVED)
        await tm.transition("tx_1", TransactionState.TRANSACTION_BUILT)
        await tm.transition("tx_1", TransactionState.SIGNED)
        await tm.transition("tx_1", TransactionState.SUBMITTED)
        record = await tm.transition("tx_1", TransactionState.UNKNOWN)
        assert record.state == TransactionState.UNKNOWN
