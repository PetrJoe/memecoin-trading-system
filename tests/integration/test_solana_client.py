import os
from unittest.mock import AsyncMock, MagicMock, patch

import base58
import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.blockchain.solana_client import SolanaClient, SolanaClientError


@pytest.fixture
def client():
    return SolanaClient(rpc_url="https://fake-rpc.solana.com")


class TestSolanaClient:
    @pytest.mark.asyncio
    async def test_get_balance(self, client):
        mock_response = MagicMock()
        mock_response.value = 1_000_000_000  # 1 SOL in lamports

        with patch.object(client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get_balance = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http

            balance = await client.get_balance(Pubkey.default())
            assert balance == 1.0

    @pytest.mark.asyncio
    async def test_get_recent_blockhash(self, client):
        mock_value = MagicMock()
        mock_value.blockhash = "FakeBlockhash123"
        mock_response = MagicMock()
        mock_response.value = mock_value

        with patch.object(client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get_latest_blockhash = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http

            blockhash = await client.get_recent_blockhash()
            assert blockhash == "FakeBlockhash123"

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, client):
        with patch.object(client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get_balance = AsyncMock(side_effect=[Exception("RPC error"), MagicMock(value=500_000_000)])
            mock_get.return_value = mock_http

            with patch("app.blockchain.solana_client.asyncio.sleep", new_callable=AsyncMock):
                balance = await client.get_balance(Pubkey.default())
                assert balance == 0.5

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self, client):
        with patch.object(client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get_balance = AsyncMock(side_effect=Exception("persistent error"))
            mock_get.return_value = mock_http

            with patch("app.blockchain.solana_client.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(SolanaClientError, match="Failed after"):
                    await client.get_balance(Pubkey.default())

    @pytest.mark.asyncio
    async def test_close(self, client):
        mock_http = AsyncMock()
        client._client = mock_http

        await client.close()
        mock_http.close.assert_called_once()
        assert client._client is None
