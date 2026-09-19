from __future__ import annotations

import time
from typing import Optional

from pydantic import BaseModel, Field

from app.config import get_logger, get_settings

logger = get_logger(category="trades")

# Simulated market costs (approximating mainnet-beta memecoin conditions)
SIMULATED_PLATFORM_FEE_PCT = 0.25       # 0.25% platform fee (Jupiter platform fee)
SIMULATED_PRIORITY_FEE_SOL = 0.0001    # priority fee per swap
SOL_PRICE_FALLBACK_USD = 150.0

# Slippage model: base spread plus impact proportional to order size vs pool liquidity
BASE_SPREAD_PCT = 0.10
IMPACT_CONSTANT = 1.0  # scale factor for order-size vs liquidity impact


def simulate_slippage_pct(order_usd: float, pool_liquidity_usd: float) -> float:
    """Estimate realistic slippage for an order against a pool of given depth."""
    if pool_liquidity_usd <= 0:
        return BASE_SPREAD_PCT + 100.0  # effectively untradeable
    impact = IMPACT_CONSTANT * (order_usd / pool_liquidity_usd) * 100.0
    return BASE_SPREAD_PCT + min(impact, 50.0)


class PaperFill(BaseModel):
    """Simulated execution fill for a single swap."""
    side: str
    token_address: str
    input_amount: float          # in input units (SOL for buys, tokens for sells)
    output_amount: float         # in output units
    fill_price: float            # effective USD price per token
    reference_price: float       # market price before this fill
    slippage_pct: float
    fee_pct: float
    fee_usd: float
    priority_fee_sol: float = SIMULATED_PRIORITY_FEE_SOL
    pool_liquidity_usd: float
    timestamp: float = Field(default_factory=time.time)


class PaperPositionState(BaseModel):
    """In-memory state for an open paper position."""
    token_address: str
    symbol: str
    entry_price: float
    quantity: float              # token units
    capital_usd: float           # USD spent including fees
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    highest_price: float = 0.0
    opened_at: float = Field(default_factory=time.time)

    def unrealized_pnl(self, current_price: float) -> float:
        return (current_price - self.entry_price) * self.quantity

    def unrealized_pnl_pct(self, current_price: float) -> float:
        if self.capital_usd <= 0:
            return 0.0
        return self.unrealized_pnl(current_price) / self.capital_usd * 100.0


class PaperBuyResult(BaseModel):
    success: bool
    fill: Optional[PaperFill] = None
    error: Optional[str] = None


class PaperSellResult(BaseModel):
    success: bool
    fill: Optional[PaperFill] = None
    realized_pnl: float = 0.0
    realized_pnl_pct: float = 0.0
    error: Optional[str] = None


class PaperFillSimulator:
    """Simulates swap fills against a virtual pool using last known market data."""

    def __init__(self, starting_cash_usd: float) -> None:
        self.starting_cash_usd = starting_cash_usd
        self.cash_usd = starting_cash_usd
        self.positions: dict[str, PaperPositionState] = {}
        # Most recent market price/liquidity per token (set via update_market)
        self._prices: dict[str, float] = {}
        self._liquidity: dict[str, float] = {}
        self.realized_pnl_usd = 0.0
        self.total_fees_usd = 0.0
        self.trade_count = 0

    # ------------------------------------------------------------------ market
    def update_market(self, token_address: str, price: float, liquidity_usd: float) -> None:
        if price > 0:
            self._prices[token_address] = price
        if liquidity_usd >= 0:
            self._liquidity[token_address] = liquidity_usd

        pos = self.positions.get(token_address)
        if pos and price > pos.highest_price:
            pos.highest_price = price

    def get_price(self, token_address: str) -> Optional[float]:
        return self._prices.get(token_address)

    def get_liquidity(self, token_address: str) -> float:
        return self._liquidity.get(token_address, 0.0)

    # -------------------------------------------------------------------- buy
    def buy(
        self,
        token_address: str,
        symbol: str,
        amount_usd: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        trailing_stop_pct: Optional[float] = None,
    ) -> PaperBuyResult:
        if token_address in self.positions:
            return PaperBuyResult(success=False, error="Position already open for token")

        price = self._prices.get(token_address)
        if not price or price <= 0:
            return PaperBuyResult(success=False, error="No market price available")

        if amount_usd > self.cash_usd:
            return PaperBuyResult(
                success=False,
                error=f"Insufficient paper cash: ${self.cash_usd:.2f} < ${amount_usd:.2f}",
            )

        liquidity = self._liquidity.get(token_address, 0.0)
        slippage_pct = simulate_slippage_pct(amount_usd, liquidity)

        # Effective entry: price pushed up by slippage, then platform fee taken
        fill_price = price * (1 + slippage_pct / 100.0)
        fee_usd = amount_usd * (SIMULATED_PLATFORM_FEE_PCT / 100.0)
        net_usd = amount_usd - fee_usd
        quantity = net_usd / fill_price

        self.cash_usd -= amount_usd
        self.total_fees_usd += fee_usd
        self.trade_count += 1

        self.positions[token_address] = PaperPositionState(
            token_address=token_address,
            symbol=symbol,
            entry_price=fill_price,
            quantity=quantity,
            capital_usd=amount_usd,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_stop_pct=trailing_stop_pct,
            highest_price=fill_price,
        )

        fill = PaperFill(
            side="BUY",
            token_address=token_address,
            input_amount=amount_usd,
            output_amount=quantity,
            fill_price=fill_price,
            reference_price=price,
            slippage_pct=slippage_pct,
            fee_pct=SIMULATED_PLATFORM_FEE_PCT,
            fee_usd=fee_usd,
            pool_liquidity_usd=liquidity,
        )
        logger.info(
            "paper_buy_filled",
            token=symbol,
            amount_usd=amount_usd,
            fill_price=fill_price,
            quantity=quantity,
            slippage_pct=round(slippage_pct, 3),
            fee_usd=round(fee_usd, 4),
        )
        return PaperBuyResult(success=True, fill=fill)

    # ------------------------------------------------------------------- sell
    def sell(self, token_address: str, percentage: float = 100.0) -> PaperSellResult:
        pos = self.positions.get(token_address)
        if pos is None:
            return PaperSellResult(success=False, error="No open position for token")

        price = self._prices.get(token_address)
        if not price or price <= 0:
            return PaperSellResult(success=False, error="No market price available")

        if not 0 < percentage <= 100:
            return PaperSellResult(success=False, error="Percentage must be in (0, 100]")

        liquidity = self._liquidity.get(token_address, 0.0)
        quantity = pos.quantity * (percentage / 100.0)
        gross_usd = quantity * price
        slippage_pct = simulate_slippage_pct(gross_usd, liquidity)

        # Effective exit: price pushed down by slippage, then platform fee
        exit_price = price * (1 - slippage_pct / 100.0)
        proceeds_gross = quantity * exit_price
        fee_usd = proceeds_gross * (SIMULATED_PLATFORM_FEE_PCT / 100.0)
        proceeds = proceeds_gross - fee_usd

        cost_basis = pos.capital_usd * (percentage / 100.0)
        realized_pnl = proceeds - cost_basis
        realized_pnl_pct = (realized_pnl / cost_basis * 100.0) if cost_basis > 0 else 0.0

        self.cash_usd += proceeds
        self.realized_pnl_usd += realized_pnl
        self.total_fees_usd += fee_usd
        self.trade_count += 1

        if percentage >= 100.0:
            del self.positions[token_address]
        else:
            pos.quantity -= quantity
            pos.capital_usd -= cost_basis

        fill = PaperFill(
            side="SELL",
            token_address=token_address,
            input_amount=quantity,
            output_amount=proceeds,
            fill_price=exit_price,
            reference_price=price,
            slippage_pct=slippage_pct,
            fee_pct=SIMULATED_PLATFORM_FEE_PCT,
            fee_usd=fee_usd,
            pool_liquidity_usd=liquidity,
        )
        logger.info(
            "paper_sell_filled",
            token=pos.symbol,
            quantity=quantity,
            exit_price=exit_price,
            realized_pnl=round(realized_pnl, 4),
            realized_pnl_pct=round(realized_pnl_pct, 2),
            slippage_pct=round(slippage_pct, 3),
            fee_usd=round(fee_usd, 4),
        )
        return PaperSellResult(
            success=True,
            fill=fill,
            realized_pnl=realized_pnl,
            realized_pnl_pct=realized_pnl_pct,
        )

    # ----------------------------------------------------------------- status
    def portfolio_value(self) -> float:
        """Cash + mark-to-market value of all open paper positions."""
        open_value = 0.0
        for addr, pos in self.positions.items():
            price = self._prices.get(addr, pos.entry_price)
            open_value += pos.quantity * price
        return self.cash_usd + open_value

    def total_pnl(self) -> float:
        return self.portfolio_value() - self.starting_cash_usd


class PaperExecutor:
    """
    Paper-mode executor with the same call shape as the live Buy/Sell executors.
    Uses the shared TransactionManager so paper trades traverse the identical
    state machine (CREATED -> ... -> CONFIRMED) as live trades.
    """

    def __init__(self, simulator: PaperFillSimulator, tx_manager) -> None:
        self._sim = simulator
        self._tx_manager = tx_manager

    async def execute_buy(
        self,
        token_address: str,
        symbol: str,
        amount_usd: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        trailing_stop_pct: Optional[float] = None,
    ) -> PaperBuyResult:
        from app.execution.transaction import TransactionState

        tx_id = f"paper_buy_{token_address[:8]}_{int(time.time() * 1000)}"
        self._tx_manager.create(
            tx_id=tx_id,
            token_address=token_address,
            input_mint="So11111111111111111111111111111111111111112",
            output_mint=token_address,
            amount=int(amount_usd * 1_000_000),
        )
        await self._tx_manager.transition(tx_id, TransactionState.QUOTE_REQUESTED)
        await self._tx_manager.transition(tx_id, TransactionState.QUOTE_RECEIVED)
        await self._tx_manager.transition(tx_id, TransactionState.RISK_APPROVED)
        await self._tx_manager.transition(tx_id, TransactionState.TRANSACTION_BUILT)
        await self._tx_manager.transition(tx_id, TransactionState.SIGNED)
        await self._tx_manager.transition(tx_id, TransactionState.SUBMITTED)

        result = self._sim.buy(
            token_address=token_address,
            symbol=symbol,
            amount_usd=amount_usd,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_stop_pct=trailing_stop_pct,
        )

        if result.success:
            await self._tx_manager.transition(tx_id, TransactionState.CONFIRMING)
            await self._tx_manager.transition(tx_id, TransactionState.CONFIRMED)
        else:
            await self._tx_manager.transition(tx_id, TransactionState.FAILED, error=result.error)
        return result

    async def execute_sell(self, token_address: str, percentage: float = 100.0) -> PaperSellResult:
        from app.execution.transaction import TransactionState

        tx_id = f"paper_sell_{token_address[:8]}_{int(time.time() * 1000)}"
        self._tx_manager.create(
            tx_id=tx_id,
            token_address=token_address,
            input_mint=token_address,
            output_mint="So11111111111111111111111111111111111111112",
            amount=1_000_000,
        )
        await self._tx_manager.transition(tx_id, TransactionState.QUOTE_REQUESTED)
        await self._tx_manager.transition(tx_id, TransactionState.QUOTE_RECEIVED)
        await self._tx_manager.transition(tx_id, TransactionState.RISK_APPROVED)
        await self._tx_manager.transition(tx_id, TransactionState.TRANSACTION_BUILT)
        await self._tx_manager.transition(tx_id, TransactionState.SIGNED)
        await self._tx_manager.transition(tx_id, TransactionState.SUBMITTED)

        result = self._sim.sell(token_address, percentage)

        if result.success:
            await self._tx_manager.transition(tx_id, TransactionState.CONFIRMING)
            await self._tx_manager.transition(tx_id, TransactionState.CONFIRMED)
        else:
            await self._tx_manager.transition(tx_id, TransactionState.FAILED, error=result.error)
        return result


def get_paper_executor(starting_cash_usd: Optional[float] = None) -> tuple[PaperFillSimulator, PaperExecutor]:
    """Factory matching project convention of settings-driven construction."""
    settings = get_settings()
    cash = starting_cash_usd if starting_cash_usd is not None else settings.PAPER_STARTING_BALANCE_USD
    sim = PaperFillSimulator(starting_cash_usd=cash)
    from app.execution.transaction import TransactionManager

    executor = PaperExecutor(simulator=sim, tx_manager=TransactionManager())
    return sim, executor
