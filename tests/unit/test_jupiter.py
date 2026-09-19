import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.execution.quote import QuoteRequest, QuoteResponse, SwapRequest
from app.execution.jupiter import JupiterClient, JupiterClientError


class TestQuoteRequest:
    def test_default_values(self):
        req = QuoteRequest(
            input_mint="So11111111111111111111111111111111111111112",
            output_mint="TokenAddr111111111111111111111111111111",
            amount=1000000000,
        )
        assert req.slippage_bps == 100
        assert req.only_direct_routes is False

    def test_price_impact_bps(self):
        qr = QuoteResponse(
            input_mint="a",
            in_amount=1000000000,
            output_mint="b",
            out_amount=500000000,
            other_amount_threshold=490000000,
            swap_mode="ExactIn",
            slippage_bps=100,
            priceImpactPct=0.5,
        )
        assert qr.price_impact_bps == 50.0


class TestJupiterClient:
    def test_init_with_url(self):
        client = JupiterClient(api_url="https://custom-jup.ag")
        assert client.api_url == "https://custom-jup.ag"

    def test_init_strips_trailing_slash(self):
        client = JupiterClient(api_url="https://custom-jup.ag/")
        assert client.api_url == "https://custom-jup.ag"

    @pytest.mark.asyncio
    async def test_close(self):
        client = JupiterClient()
        mock_http = AsyncMock()
        mock_http.is_closed = False
        client._client = mock_http
        await client.close()
        mock_http.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_when_none(self):
        client = JupiterClient()
        client._client = None
        await client.close()

    @pytest.mark.asyncio
    async def test_get_quote_success(self):
        client = JupiterClient()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "inputMint": "So11111111111111111111111111111111111111112",
            "inAmount": "1000000000",
            "outputMint": "TokenAddr111111111111111111111111111111",
            "outAmount": "500000000",
            "otherAmountThreshold": "490000000",
            "swapMode": "ExactIn",
            "slippageBps": 100,
            "priceImpactPct": "0.5",
            "routePlan": [],
        }
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_http.is_closed = False
        client._client = mock_http

        req = QuoteRequest(
            input_mint="So11111111111111111111111111111111111111112",
            output_mint="TokenAddr111111111111111111111111111111",
            amount=1000000000,
        )

        quote = await client.get_quote(req)
        assert quote.out_amount == 500000000
        assert quote.price_impact_pct == 0.5
