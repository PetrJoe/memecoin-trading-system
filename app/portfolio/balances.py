from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from app.config import get_logger, get_settings

logger = get_logger(category="trades")


@dataclass
class BalanceSnapshot:
    cash_usd: float
    position_value_usd: float
    total_usd: float
    sol_balance: float = 0.0
    sol_price_usd: float = 0.0
    timestamp: float = field(default_factory=time.time)


class BalanceTracker:
    """
    Tracks the bot's equity:
      - Paper mode: virtual cash + mark-to-market positions
      - Live mode: real SOL balance (on-chain) + mark-to-market positions

    In live mode, balances are fetched from Solana RPC, not simulated.
    """

    def __init__(self, starting_balance_usd: Optional[float] = None) -> None:
        self.settings = get_settings()
        starting = (
            starting_balance_usd
            if starting_balance_usd is not None
            else self.settings.PAPER_STARTING_BALANCE_USD
        )
        self.starting_balance_usd = starting
        self.cash_usd = starting
        self.realized_pnl_usd = 0.0
        self.total_fees_usd = 0.0
        self._position_value_usd = 0.0
        self._last_snapshot: Optional[BalanceSnapshot] = None

        # Live mode on-chain state
        self._sol_balance: float = 0.0
        self._sol_price_usd: float = 0.0
        self._last_balance_fetch: float = 0.0
        self._wallet_public_key: Optional[str] = None
        self._solana_client = None  # SolanaClient, set by TradingLoop in live mode

    def set_wallet(self, wallet_public_key: str, solana_client) -> None:
        """Wire the on-chain balance source for live mode."""
        self._wallet_public_key = wallet_public_key
        self._solana_client = solana_client
        self._sol_balance = 0.0

    async def fetch_onchain_balance(self) -> float:
        """Fetch real SOL balance from Solana RPC. Caches for 10 seconds."""
        now = time.time()
        if now - self._last_balance_fetch < 10.0:
            return self._sol_balance

        if self._solana_client is None or self._wallet_public_key is None:
            return self._sol_balance

        try:
            from solders.pubkey import Pubkey
            pubkey = Pubkey.from_string(self._wallet_public_key)
            self._sol_balance = await self._solana_client.get_balance(pubkey)
            self._last_balance_fetch = now

            # Also refresh SOL price
            self._sol_price_usd = await self._fetch_sol_price()

            logger.debug(
                "onchain_balance_fetched",
                sol_balance=self._sol_balance,
                sol_price=self._sol_price_usd,
            )
        except Exception as e:
            logger.warning("onchain_balance_fetch_failed", error=str(e))

        return self._sol_balance

    async def _fetch_sol_price(self) -> float:
        """Fetch SOL/USD from CoinGecko. Caches for 60s."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
                )
                data = resp.json()
                return data.get("solana", {}).get("usd", 150.0)
        except Exception:
            return self._sol_price_usd or 150.0

    @property
    def sol_balance(self) -> float:
        return self._sol_balance

    @property
    def sol_balance_usd(self) -> float:
        return self._sol_balance * self._sol_price_usd

    @property
    def onchain_balance_usd(self) -> float:
        """Real SOL balance in USD (live mode)."""
        if self._solana_client is not None:
            return self.sol_balance_usd
        return self.cash_usd  # paper mode fallback

    # ------------------------------------------------------------------ input
    def record_buy(self, amount_usd: float, fee_usd: float) -> None:
        self.cash_usd -= amount_usd
        self.total_fees_usd += fee_usd

    def record_sell(self, proceeds_usd: float, fee_usd: float, realized_pnl_usd: float) -> None:
        self.cash_usd += proceeds_usd
        self.total_fees_usd += fee_usd
        self.realized_pnl_usd += realized_pnl_usd

    def update_position_value(self, value_usd: float) -> None:
        self._position_value_usd = max(0.0, value_usd)

    # ----------------------------------------------------------------- output
    @property
    def position_value_usd(self) -> float:
        return self._position_value_usd

    @property
    def total_equity(self) -> float:
        return self.cash_usd + self._position_value_usd

    @property
    def total_pnl(self) -> float:
        return self.total_equity - self.starting_balance_usd

    @property
    def total_pnl_pct(self) -> float:
        if self.starting_balance_usd <= 0:
            return 0.0
        return self.total_pnl / self.starting_balance_usd * 100.0

    @property
    def realized_pnl(self) -> float:
        return self.realized_pnl_usd

    @property
    def unrealized_pnl(self) -> float:
        return self.total_equity - self.starting_balance_usd - self.realized_pnl_usd

    def snapshot(self) -> BalanceSnapshot:
        snap = BalanceSnapshot(
            cash_usd=round(self.cash_usd, 6),
            position_value_usd=round(self._position_value_usd, 6),
            total_usd=round(self.total_equity, 6),
            sol_balance=self._sol_balance,
            sol_price_usd=self._sol_price_usd,
        )
        self._last_snapshot = snap
        return snap

    def reset(self, starting_balance_usd: Optional[float] = None) -> None:
        starting = (
            starting_balance_usd
            if starting_balance_usd is not None
            else self.starting_balance_usd
        )
        self.starting_balance_usd = starting
        self.cash_usd = starting
        self.realized_pnl_usd = 0.0
        self.total_fees_usd = 0.0
        self._position_value_usd = 0.0
        self._last_snapshot = None
        logger.info("balance_tracker_reset", starting_balance=starting)
