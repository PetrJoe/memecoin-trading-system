from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from app.config import get_logger, get_settings
from app.execution.buy import BuyExecutor, BuyResult
from app.execution.jupiter import JupiterClient, JupiterClientError
from app.execution.sell import SellExecutor, SellResult
from app.execution.transaction import TransactionManager

logger = get_logger(category="trades")

SOL_PRICE_FALLBACK_USD = 150.0
WSOL_MINT = "So11111111111111111111111111111111111111112"
SOL_DECIMALS = 9


@dataclass
class LiveFill:
    """Unified fill result matching PaperFill interface for the orchestrator."""
    side: str
    token_address: str
    input_amount: float          # USD spent (buys) or token quantity (sells)
    output_amount: float         # tokens received (buys) or USD proceeds (sells)
    fill_price: float            # effective USD price per token
    reference_price: float       # market price before this fill
    slippage_pct: float
    fee_pct: float
    fee_usd: float
    priority_fee_sol: float = 0.0
    pool_liquidity_usd: float = 0.0
    timestamp: float = 0.0
    tx_signature: str = ""


@dataclass
class LiveBuyResult:
    success: bool
    fill: Optional[LiveFill] = None
    error: Optional[str] = None


@dataclass
class LiveSellResult:
    success: bool
    fill: Optional[LiveFill] = None
    realized_pnl: float = 0.0
    realized_pnl_pct: float = 0.0
    error: Optional[str] = None


class LiveExecutor:
    """
    Live-mode executor with the same call shape as PaperExecutor.

    Wraps JupiterClient + BuyExecutor + SellExecutor to perform real
    on-chain swaps. The orchestrator is agnostic to whether it's talking
    to PaperExecutor or LiveExecutor — the interface is identical.

    Flow:
      1. Fetch SOL balance to determine available capital
      2. Convert USD amount → lamports
      3. Get Jupiter quote (validates slippage/price impact)
      4. Build + sign + broadcast transaction via Jupiter swap API
      5. Confirm on-chain
      6. Return unified fill result

    Safety:
      - live_safe mode caps MAX_POSITION_USD at $0.50 by config
      - All transactions use skip_preflight=false for validation
      - Circuit breaker integration at orchestrator level
      - Slippage and price impact checked before execution
    """

    def __init__(
        self,
        jupiter: JupiterClient,
        buy_executor: BuyExecutor,
        sell_executor: SellExecutor,
        tx_manager: TransactionManager,
        wallet_public_key: str,
        solana_rpc_url: Optional[str] = None,
    ) -> None:
        self._jupiter = jupiter
        self._buy_executor = buy_executor
        self._sell_executor = sell_executor
        self._tx_manager = tx_manager
        self._wallet_public_key = wallet_public_key
        settings = get_settings()
        self._solana_rpc_url = solana_rpc_url or settings.SOLANA_RPC_URL
        self._slippage_bps = settings.MAX_SLIPPAGE_BPS
        self._max_price_impact_bps = settings.MAX_PRICE_IMPACT_BPS
        self._is_live_safe = settings.is_live_safe
        self._sol_price_cache: float = SOL_PRICE_FALLBACK_USD
        self._sol_price_updated: float = 0.0

        # Track positions: token_address → {amount, entry_price, capital_usd}
        self._positions: dict[str, dict] = {}

    async def _refresh_sol_price(self) -> float:
        """Fetch SOL/USD price from a public API. Caches for 60 seconds."""
        now = time.time()
        if now - self._sol_price_updated < 60.0 and self._sol_price_cache > 0:
            return self._sol_price_cache

        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd")
                data = resp.json()
                price = data.get("solana", {}).get("usd", SOL_PRICE_FALLBACK_USD)
                if price > 0:
                    self._sol_price_cache = price
                    self._sol_price_updated = now
                    return price
        except Exception as e:
            logger.warning("sol_price_fetch_failed", error=str(e))

        return self._sol_price_cache

    async def _usd_to_lamports(self, amount_usd: float) -> int:
        """Convert a USD amount to SOL lamports."""
        sol_price = await self._refresh_sol_price()
        sol_amount = amount_usd / sol_price
        return int(sol_amount * (10 ** SOL_DECIMALS))

    async def _lamports_to_usd(self, lamports: int) -> float:
        """Convert lamports to USD."""
        sol_price = await self._refresh_sol_price()
        return (lamports / (10 ** SOL_DECIMALS)) * sol_price

    async def _token_amount_to_usd(self, token_amount: int, decimals: int = 0) -> float:
        """Convert a raw token amount to USD using Jupiter quote."""
        try:
            from app.execution.quote import QuoteRequest
            quote_req = QuoteRequest(
                input_mint="So11111111111111111111111111111111111111112",
                output_mint="So11111111111111111111111111111111111111112",
                amount=token_amount,
                slippage_bps=50,
            )
            quote = await self._jupiter.get_quote(quote_req)
            return await self._lamports_to_usd(quote.out_amount)
        except Exception:
            return 0.0

    async def execute_buy(
        self,
        token_address: str,
        symbol: str,
        amount_usd: float,
        **kwargs,
    ) -> LiveBuyResult:
        """
        Execute a buy: SOL → Token via Jupiter.

        Args:
            token_address: SPL token mint address
            symbol: Token ticker for logging
            amount_usd: USD amount to spend

        Returns:
            LiveBuyResult with fill data or error
        """
        logger.info(
            "live_buy_start",
            token=symbol,
            amount_usd=amount_usd,
            wallet=self._wallet_public_key[:8] + "...",
        )

        try:
            input_lamports = await self._usd_to_lamports(amount_usd)

            if input_lamports <= 0:
                return LiveBuyResult(success=False, error="Calculated input amount is zero")

            # Validate via Jupiter quote first (checks slippage, price impact)
            from app.execution.quote import QuoteRequest
            quote_req = QuoteRequest(
                input_mint=WSOL_MINT,
                output_mint=token_address,
                amount=input_lamports,
                slippage_bps=self._slippage_bps,
            )
            quote = await self._jupiter.get_quote(quote_req)

            # Check price impact
            if quote.price_impact_bps > self._max_price_impact_bps:
                logger.warning(
                    "live_buy_price_impact_too_high",
                    token=symbol,
                    impact_bps=quote.price_impact_bps,
                    max_bps=self._max_price_impact_bps,
                )
                return LiveBuyResult(
                    success=False,
                    error=f"Price impact {quote.price_impact_bps:.0f}bps exceeds max {self._max_price_impact_bps}bps",
                )

            # Execute the swap via Jupiter
            result = await self._buy_executor.execute(
                token_address=token_address,
                input_amount_lamports=input_lamports,
                user_public_key=self._wallet_public_key,
                slippage_bps=self._slippage_bps,
            )

            if not result.success:
                return LiveBuyResult(success=False, error=result.error)

            # Calculate fill details
            sol_price = await self._refresh_sol_price()
            fill_price = await self._lamports_to_usd(result.output_amount) / max(1, result.output_amount) if result.output_amount > 0 else 0
            # More accurate: use quote data
            out_usd = await self._lamports_to_usd(result.output_amount) if result.output_amount > 0 else 0
            fill_price = out_usd / max(1, result.output_amount) if result.output_amount > 0 else 0
            slippage_pct = abs(quote.price_impact_pct)
            fee_usd = amount_usd * 0.0025  # Jupiter ~0.25% platform fee

            # Store position data for future sell + P&L calculation
            self._positions[token_address] = {
                "amount": result.output_amount,
                "entry_price": fill_price,
                "capital_usd": amount_usd,
            }

            fill = LiveFill(
                side="BUY",
                token_address=token_address,
                input_amount=amount_usd,
                output_amount=result.output_amount,
                fill_price=fill_price,
                reference_price=fill_price * (1 - slippage_pct / 100),
                slippage_pct=slippage_pct,
                fee_pct=0.25,
                fee_usd=fee_usd,
                priority_fee_sol=0.0,
                timestamp=time.time(),
                tx_signature=result.tx_signature or "",
            )

            logger.info(
                "live_buy_filled",
                token=symbol,
                amount_usd=amount_usd,
                fill_price=fill_price,
                tx_signature=result.tx_signature,
                slippage_pct=round(slippage_pct, 3),
            )

            return LiveBuyResult(success=True, fill=fill)

        except JupiterClientError as e:
            logger.error("live_buy_jupiter_error", token=symbol, error=str(e))
            return LiveBuyResult(success=False, error=f"Jupiter error: {e}")
        except Exception as e:
            logger.error("live_buy_unexpected_error", token=symbol, error=str(e))
            return LiveBuyResult(success=False, error=f"Unexpected error: {e}")

    async def execute_sell(
        self,
        token_address: str,
        percentage: float = 100.0,
    ) -> LiveSellResult:
        """
        Execute a sell: Token → SOL via Jupiter.

        Args:
            token_address: SPL token mint address
            percentage: Percentage of position to sell (default 100%)

        Returns:
            LiveSellResult with fill data, P&L, or error
        """
        logger.info("live_sell_start", token=token_address[:8], percentage=percentage)

        try:
            # Get the position data we're holding
            pos_data = self._positions.get(token_address)
            if pos_data is None or pos_data["amount"] <= 0:
                return LiveSellResult(success=False, error="No token balance tracked for this position")

            raw_amount = pos_data["amount"]
            entry_price = pos_data["entry_price"]
            capital_usd = pos_data["capital_usd"]

            # Calculate amount to sell based on percentage
            sell_amount = int(raw_amount * (percentage / 100.0))
            if sell_amount <= 0:
                return LiveSellResult(success=False, error="Sell amount is zero")

            # Execute the swap via Jupiter
            result = await self._sell_executor.execute(
                token_address=token_address,
                token_amount=sell_amount,
                user_public_key=self._wallet_public_key,
                slippage_bps=self._slippage_bps,
            )

            if not result.success:
                return LiveSellResult(success=False, error=result.error)

            # Calculate proceeds in USD
            proceeds_usd = await self._lamports_to_usd(result.output_amount) if result.output_amount > 0 else 0
            fee_usd = proceeds_usd * 0.0025

            # Calculate realized P&L
            cost_basis = capital_usd * (percentage / 100.0)
            realized_pnl = proceeds_usd - cost_basis
            realized_pnl_pct = (realized_pnl / cost_basis * 100.0) if cost_basis > 0 else 0.0

            fill = LiveFill(
                side="SELL",
                token_address=token_address,
                input_amount=sell_amount,
                output_amount=proceeds_usd,
                fill_price=proceeds_usd / max(1, sell_amount),
                reference_price=entry_price,
                slippage_pct=abs(result.price_impact_pct),
                fee_pct=0.25,
                fee_usd=fee_usd,
                timestamp=time.time(),
                tx_signature=result.tx_signature or "",
            )

            # Update tracked position
            remaining = raw_amount - sell_amount
            if remaining > 0 and percentage < 100.0:
                self._positions[token_address] = {
                    "amount": remaining,
                    "entry_price": entry_price,
                    "capital_usd": capital_usd - cost_basis,
                }
            else:
                self._positions.pop(token_address, None)

            logger.info(
                "live_sell_filled",
                token=token_address[:8],
                sell_amount=sell_amount,
                proceeds_usd=proceeds_usd,
                realized_pnl=realized_pnl,
                tx_signature=result.tx_signature,
            )

            return LiveSellResult(
                success=True,
                fill=fill,
                realized_pnl=realized_pnl,
                realized_pnl_pct=realized_pnl_pct,
            )

        except JupiterClientError as e:
            logger.error("live_sell_jupiter_error", token=token_address[:8], error=str(e))
            return LiveSellResult(success=False, error=f"Jupiter error: {e}")
        except Exception as e:
            logger.error("live_sell_unexpected_error", token=token_address[:8], error=str(e))
            return LiveSellResult(success=False, error=f"Unexpected error: {e}")


def get_live_executor(
    wallet_public_key: str,
    wallet_private_key_b58: Optional[str] = None,
    solana_rpc_url: Optional[str] = None,
) -> tuple[JupiterClient, TransactionManager, LiveExecutor]:
    """
    Factory: builds the full live execution stack.

    Returns:
        (jupiter_client, tx_manager, live_executor)
    """
    settings = get_settings()
    rpc_url = solana_rpc_url or settings.SOLANA_RPC_URL

    jupiter = JupiterClient()
    tx_manager = TransactionManager()

    buy_executor = BuyExecutor(
        jupiter=jupiter,
        tx_manager=tx_manager,
        solana_rpc_url=rpc_url,
    )
    sell_executor = SellExecutor(
        jupiter=jupiter,
        tx_manager=tx_manager,
        solana_rpc_url=rpc_url,
    )

    live_executor = LiveExecutor(
        jupiter=jupiter,
        buy_executor=buy_executor,
        sell_executor=sell_executor,
        tx_manager=tx_manager,
        wallet_public_key=wallet_public_key,
        solana_rpc_url=rpc_url,
    )

    return jupiter, tx_manager, live_executor
