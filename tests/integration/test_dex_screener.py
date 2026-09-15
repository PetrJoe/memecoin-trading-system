import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.scanner.dex_screener import DexScreenerClient, DexScreenerClientError


@pytest.fixture
def client():
    return DexScreenerClient(base_url="https://api.dexscreener.com", timeout=5.0)


@pytest.fixture
def mock_response():
    def _make(status_code=200, json_data=None):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status_code
        resp.json.return_value = json_data or {}
        resp.raise_for_status = MagicMock()
        if status_code >= 400:
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                message=f"HTTP {status_code}",
                request=MagicMock(),
                response=resp,
            )
        return resp
    return _make


class TestDexScreenerClient:
    @pytest.mark.asyncio
    async def test_get_token_pairs_success(self, client, mock_response):
        mock_data = [
            {
                "chainId": "solana",
                "dexId": "raydium",
                "pairAddress": "Pair123",
                "baseToken": {"address": "Token123", "name": "Test", "symbol": "TST"},
                "priceUsd": "0.001",
            }
        ]
        mock_resp = mock_response(200, mock_data)

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request.return_value = mock_resp
            mock_get_client.return_value = mock_http

            pairs = await client.get_token_pairs("solana", "Token123")
            assert len(pairs) == 1
            assert pairs[0].base_token.symbol == "TST"

    @pytest.mark.asyncio
    async def test_search_pairs_filters_solana(self, client, mock_response):
        mock_data = {
            "pairs": [
                {
                    "chainId": "solana",
                    "dexId": "raydium",
                    "pairAddress": "P1",
                    "baseToken": {"address": "T1", "name": "Coin1", "symbol": "C1"},
                    "priceUsd": "1.0",
                },
                {
                    "chainId": "ethereum",
                    "dexId": "uniswap",
                    "pairAddress": "P2",
                    "baseToken": {"address": "T2", "name": "Coin2", "symbol": "C2"},
                    "priceUsd": "2.0",
                },
            ]
        }
        mock_resp = mock_response(200, mock_data)

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request.return_value = mock_resp
            mock_get_client.return_value = mock_http

            pairs = await client.search_pairs("test")
            assert len(pairs) == 1
            assert pairs[0].chain_id == "solana"

    @pytest.mark.asyncio
    async def test_handles_timeout_with_retry(self, client):
        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request.side_effect = httpx.TimeoutException("timeout")
            mock_get_client.return_value = mock_http

            with pytest.raises(DexScreenerClientError, match="Failed after"):
                await client.get_token_pairs("solana", "Token123")

    @pytest.mark.asyncio
    async def test_handles_server_error_with_retry(self, client, mock_response):
        error_resp = mock_response(500)
        ok_resp = mock_response(200, [])

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request.side_effect = [error_resp, ok_resp]
            mock_get_client.return_value = mock_http

            with patch("app.scanner.dex_screener.asyncio.sleep", new_callable=AsyncMock):
                pairs = await client.get_token_pairs("solana", "Token123")
                assert pairs == []

    @pytest.mark.asyncio
    async def test_rate_limit_retries(self, client, mock_response):
        rate_resp = mock_response(429)
        rate_resp.headers = {"Retry-After": "0.01"}
        ok_resp = mock_response(200, [])

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request.side_effect = [rate_resp, ok_resp]
            mock_get_client.return_value = mock_http

            with patch("app.scanner.dex_screener.asyncio.sleep", new_callable=AsyncMock):
                pairs = await client.get_token_pairs("solana", "Token123")
                assert pairs == []

    @pytest.mark.asyncio
    async def test_close(self, client):
        mock_http = AsyncMock()
        mock_http.is_closed = False
        client._client = mock_http

        await client.close()
        mock_http.aclose.assert_called_once()
