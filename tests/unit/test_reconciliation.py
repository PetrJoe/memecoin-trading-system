import pytest

from app.blockchain.reconciliation import ReconciliationResult, ReconciliationService
from app.database.models import Position, PositionStatus


class TestReconciliationResult:
    def test_consistent_when_empty(self):
        r = ReconciliationResult()
        assert r.is_consistent is True
        assert r.has_discrepancies is False

    def test_inconsistent_when_missing_onchain(self):
        r = ReconciliationResult(missing_onchain=["token1"])
        assert r.is_consistent is False
        assert r.has_discrepancies is True

    def test_inconsistent_when_missing_in_db(self):
        r = ReconciliationResult(missing_in_db=["token2"])
        assert r.has_discrepancies is True

    def test_inconsistent_when_balance_mismatch(self):
        r = ReconciliationResult(balance_mismatch=[{"token": "t", "db_quantity": 1, "onchain_quantity": 2}])
        assert r.has_discrepancies is True


class TestReconciliationService:
    @pytest.mark.asyncio
    async def test_perfect_match(self):
        svc = ReconciliationService()
        positions = [
            Position(
                id=1, token_id=1, entry_price=1.0, quantity=100.0,
                capital=100.0, status=PositionStatus.OPEN,
            ),
        ]
        onchain = {"TokenAddr111111111111111111111111111111": 100.0}
        token_addrs = {1: "TokenAddr111111111111111111111111111111"}

        result = await svc.reconcile(positions, onchain, token_addrs)
        assert result.is_consistent is True
        assert len(result.matched) == 1

    @pytest.mark.asyncio
    async def test_missing_onchain(self):
        svc = ReconciliationService()
        positions = [
            Position(
                id=1, token_id=1, entry_price=1.0, quantity=100.0,
                capital=100.0, status=PositionStatus.OPEN,
            ),
        ]
        onchain = {}
        token_addrs = {1: "TokenAddr111111111111111111111111111111"}

        result = await svc.reconcile(positions, onchain, token_addrs)
        assert result.is_consistent is False
        assert len(result.missing_onchain) == 1

    @pytest.mark.asyncio
    async def test_missing_in_db(self):
        svc = ReconciliationService()
        positions = []
        onchain = {"UnknownToken11111111111111111111111111111": 50.0}
        token_addrs = {}

        result = await svc.reconcile(positions, onchain, token_addrs)
        assert result.is_consistent is False
        assert len(result.missing_in_db) == 1

    @pytest.mark.asyncio
    async def test_balance_mismatch(self):
        svc = ReconciliationService()
        positions = [
            Position(
                id=1, token_id=1, entry_price=1.0, quantity=100.0,
                capital=100.0, status=PositionStatus.OPEN,
            ),
        ]
        onchain = {"TokenAddr111111111111111111111111111111": 90.0}
        token_addrs = {1: "TokenAddr111111111111111111111111111111"}

        result = await svc.reconcile(positions, onchain, token_addrs)
        assert result.is_consistent is False
        assert len(result.balance_mismatch) == 1

    @pytest.mark.asyncio
    async def test_closed_positions_ignored(self):
        svc = ReconciliationService()
        positions = [
            Position(
                id=1, token_id=1, entry_price=1.0, quantity=100.0,
                capital=100.0, status=PositionStatus.CLOSED,
            ),
        ]
        onchain = {}
        token_addrs = {1: "TokenAddr111111111111111111111111111111"}

        result = await svc.reconcile(positions, onchain, token_addrs)
        assert result.is_consistent is True
        assert len(result.matched) == 0
