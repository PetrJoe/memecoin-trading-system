from __future__ import annotations

import asyncio
import time
from typing import Optional

from app.api.state import AppState, get_app_state
from app.config import get_logger, get_settings
from app.execution.orchestrator import TradeOrchestrator
from app.execution.paper import PaperFillSimulator
from app.portfolio.balances import BalanceTracker
from app.portfolio.pnl import PnLCalculator
from app.portfolio.positions import PositionManager
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.exposure import ExposureTracker
from app.risk.models import PortfolioRiskData, TokenRiskData
from app.risk.position_sizing import PositionSizer
from app.risk.risk_engine import RiskEngine
from app.scanner.dex_screener import DexScreenerClient, DexScreenerClientError
from app.scanner.filters import NewLaunchFilter, TokenFilter
from app.scanner.models import MarketSnapshot
from app.strategy.base import StrategyContext, StrategySignal
from app.strategy.momentum import MomentumStrategy
from app.strategy.new_launch import NewLaunchSniper

logger = get_logger(category="trades")

# Cooldown (seconds) before re-emitting the same event_type for the same token
EVENT_COOLDOWN_SECONDS = 60.0


class _SimExecutor:
    """Executor adapter binding the PaperFillSimulator to the orchestrator interface."""

    def __init__(self, sim: PaperFillSimulator) -> None:
        self.sim = sim

    async def execute_buy(self, token_address: str, symbol: str, amount_usd: float, **kwargs):
        return self.sim.buy(token_address, symbol, amount_usd, **kwargs)

    async def execute_sell(self, token_address: str, percentage: float = 100.0):
        return self.sim.sell(token_address, percentage)


class TradingLoop:
    """
    Drives the full trading pipeline on intervals:

        scanner ──▶ filter ──▶ strategy ──▶ orchestrator.buy
            │                                      │
            └──▶ price feed ──▶ position monitor ──┘ (exits via orchestrator.sell)

    Supports paper and live modes:
      - Paper: in-memory simulator, no chain interaction
      - Live:  real Jupiter swaps via Solana mainnet, on-chain balance tracking
    """

    def __init__(
        self,
        dex_client: Optional[DexScreenerClient] = None,
        app_state: Optional[AppState] = None,
        search_query: str = "",
    ) -> None:
        self.settings = get_settings()
        self.state = app_state or get_app_state()
        self.dex_client = dex_client or DexScreenerClient()
        self.token_filter = TokenFilter.from_settings()
        self.strategy = MomentumStrategy()

        # New-launch sniper (separate scanner + strategy)
        self.new_launch_enabled = self.settings.NEW_LAUNCH_ENABLED
        self.new_launch_filter = NewLaunchFilter.from_settings() if self.new_launch_enabled else None
        self.new_launch_strategy = NewLaunchSniper() if self.new_launch_enabled else None
        self._new_launch_seen: set[str] = set()  # dedup new-launch tokens
        self._last_new_launch_scan_at: float = 0.0

        self._jupiter_client = None  # kept for cleanup in live mode
        self._wallet_service = None
        self._solana_client = None

        # --- wiring: paper or live based on TRADING_MODE ---
        if self.settings.is_paper:
            self._wire_paper_mode()
        else:
            self._wire_live_mode()

        # Register everything so the dashboard can render
        self.state.orchestrator = self.orchestrator
        self.state.position_manager = self.position_manager
        self.state.pnl_calculator = self.pnl_calculator
        self.state.circuit_breaker = self.circuit_breaker
        self.state.mode = self.settings.TRADING_MODE.value
        self.state.trading_enabled = True

        self.search_query = search_query
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_scan_at: float = 0.0
        self._last_emit: dict[tuple[str, str], float] = {}  # (event_type, token) -> ts

    # ---------------------------------------------------------- mode wiring
    def _wire_paper_mode(self) -> None:
        """Wire everything for paper (simulated) trading."""
        sim = self.state.paper_simulator or PaperFillSimulator(
            starting_cash_usd=self.settings.PAPER_STARTING_BALANCE_USD
        )
        self.simulator = sim
        self.state.paper_simulator = sim

        if self.state.orchestrator is None:
            orchestrator = TradeOrchestrator(
                risk_engine=RiskEngine(),
                position_sizer=PositionSizer(),
                circuit_breaker=CircuitBreaker(),
                position_manager=PositionManager(),
                pnl_calculator=PnLCalculator(),
                exposure_tracker=ExposureTracker(),
                executor=_SimExecutor(sim),
            )
            self.orchestrator = orchestrator
        else:
            self.orchestrator = self.state.orchestrator

        self.circuit_breaker = self.orchestrator.circuit_breaker
        self.position_manager = self.orchestrator.position_manager
        self.pnl_calculator = self.orchestrator.pnl_calculator

        if self.state.balance_tracker is None:
            self.state.balance_tracker = BalanceTracker(
                starting_balance_usd=self.settings.PAPER_STARTING_BALANCE_USD
            )
        self.balance_tracker = self.state.balance_tracker

    def _wire_live_mode(self) -> None:
        """Wire the full live execution stack: Jupiter + Solana + wallet."""
        from app.blockchain.solana_client import SolanaClient
        from app.blockchain.wallet import WalletService
        from app.execution.live import LiveExecutor, get_live_executor

        # 1. Initialize wallet
        key_b58 = self.settings.BOT_PRIVATE_KEY.get_secret_value()
        if not key_b58:
            raise RuntimeError(
                "BOT_PRIVATE_KEY is required for live trading. "
                "Generate one with: python scripts/create_bot_wallet.py"
            )

        self._wallet_service = WalletService(private_key_b58=key_b58)
        wallet_pubkey = self._wallet_service.address
        logger.info("live_wallet_loaded", address=wallet_pubkey)

        # 2. Initialize Solana RPC client
        self._solana_client = SolanaClient()

        # 3. Build the live executor
        self._jupiter_client, tx_manager, live_executor = get_live_executor(
            wallet_public_key=wallet_pubkey,
            solana_rpc_url=self.settings.SOLANA_RPC_URL,
        )
        self.simulator = None  # no paper simulator in live mode

        # 4. Wire orchestrator
        if self.state.orchestrator is None:
            orchestrator = TradeOrchestrator(
                risk_engine=RiskEngine(),
                position_sizer=PositionSizer(),
                circuit_breaker=CircuitBreaker(),
                position_manager=PositionManager(),
                pnl_calculator=PnLCalculator(),
                exposure_tracker=ExposureTracker(),
                executor=live_executor,
            )
            self.orchestrator = orchestrator
        else:
            self.orchestrator = self.state.orchestrator

        self.circuit_breaker = self.orchestrator.circuit_breaker
        self.position_manager = self.orchestrator.position_manager
        self.pnl_calculator = self.orchestrator.pnl_calculator

        # 5. Initialize balance tracker with on-chain source
        if self.state.balance_tracker is None:
            self.state.balance_tracker = BalanceTracker()
        self.balance_tracker = self.state.balance_tracker
        self.balance_tracker.set_wallet(wallet_pubkey, self._solana_client)

        logger.info(
            "live_mode_initialized",
            wallet=wallet_pubkey,
            rpc=self.settings.SOLANA_RPC_URL,
            mode=self.settings.TRADING_MODE.value,
        )

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())

        if self.settings.is_paper:
            self.state.event_log.emit(
                "bot_started",
                level="info",
                message=f"Paper trading loop started (balance ${self.settings.PAPER_STARTING_BALANCE_USD:,.2f})",
            )
        else:
            # Fetch initial on-chain balance
            if self._solana_client:
                await self.balance_tracker.fetch_onchain_balance()
            self.state.event_log.emit(
                "bot_started",
                level="info",
                message=f"Live trading started ({self.settings.TRADING_MODE.value} mode)",
            )

        logger.info("trading_loop_started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.state.trading_enabled = False
        self.state.event_log.emit("bot_stopped", level="warning", message="Trading loop stopped")
        logger.info("trading_loop_stopped")

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def _run(self) -> None:
        scanner_interval = max(5.0, float(self.settings.SCANNER_INTERVAL_SECONDS))
        position_interval = max(1.0, float(self.settings.POSITION_CHECK_INTERVAL_SECONDS))
        new_launch_interval = max(5.0, float(self.settings.NEW_LAUNCH_SCAN_INTERVAL_SECONDS))

        try:
            while self._running:
                cycle_start = time.monotonic()

                # Position monitoring runs every cycle (cheap, in-memory)
                try:
                    await self._position_cycle()
                except Exception as e:
                    self._record_loop_error("position", e)

                # New-launch scanner runs on FASTER cadence (priority)
                if (
                    self.new_launch_enabled
                    and time.monotonic() - self._last_new_launch_scan_at >= new_launch_interval
                ):
                    self._last_new_launch_scan_at = time.monotonic()
                    try:
                        await self._new_launch_cycle()
                    except Exception as e:
                        self._record_loop_error("new_launch_scan", e)

                # Standard scanner runs on its own (slower) cadence
                if time.monotonic() - self._last_scan_at >= scanner_interval:
                    self._last_scan_at = time.monotonic()
                    try:
                        await self._scan_cycle()
                    except Exception as e:
                        self._record_loop_error("scan", e)

                # Live mode: refresh on-chain balance periodically
                if not self.settings.is_paper and self._solana_client:
                    try:
                        await self.balance_tracker.fetch_onchain_balance()
                        # Trigger circuit breaker if wallet is nearly empty
                        if self.balance_tracker.sol_balance < 0.01:
                            self.circuit_breaker.record_wallet_balance_low(
                                self.balance_tracker.sol_balance
                            )
                    except Exception as e:
                        self._record_loop_error("balance", e)

                elapsed = time.monotonic() - cycle_start
                await asyncio.sleep(max(0.5, position_interval - elapsed))
        except asyncio.CancelledError:
            raise

    def _record_loop_error(self, phase: str, exc: Exception) -> None:
        self.state.last_loop_error = f"{phase}: {exc}"
        self.state.loop_errors.append({"phase": phase, "error": str(exc), "at": time.time()})
        logger.error("trading_loop_error", phase=phase, error=str(exc))

    # --------------------------------------------------------------- events
    def _emit(self, event_type: str, token: str = "", level: str = "info", **data) -> None:
        """Emit to the dashboard feed with per-(type, token) cooldown to avoid spam."""
        key = (event_type, token)
        now = time.time()
        last = self._last_emit.get(key)
        if last is not None and (now - last) < EVENT_COOLDOWN_SECONDS:
            return
        self._last_emit[key] = now
        self.state.event_log.emit(event_type, level=level, token=token or None, **data)

    # ------------------------------------------------------------ scan cycle
    async def _scan_cycle(self) -> None:
        """Fetch snapshots from DexScreener, feed prices, run strategy on candidates."""
        try:
            snapshots = await self.dex_client.get_solana_pairs(self.search_query)
        except DexScreenerClientError as e:
            # Scanner outage: keep managing existing positions, stop discovering
            self.state.event_log.emit(
                "scanner_unavailable",
                level="warning",
                message=f"Scanner unavailable: {e}",
            )
            return

        self.state.scans_completed += 1
        self.state.last_scan_at = time.time()
        if not snapshots:
            return

        now = time.time()
        # Refresh the price feed for ALL seen tokens (drives TP/SL evaluation)
        # and feed the paper simulator so candidate fills have market data.
        for snap in snapshots:
            self.state.prices[snap.token_address] = snap.price
            self.state.latest_snapshots[snap.token_address] = snap
            if self.simulator is not None:
                self.simulator.update_market(snap.token_address, price=snap.price, liquidity_usd=snap.liquidity or 0.0)

        # Discovery: new tokens passing filters join the watchlist
        for snap in snapshots:
            if snap.token_address in self.state.watchlist:
                continue
            result = self.token_filter.check(snap)
            if result.passed:
                self.state.watchlist[snap.token_address] = now
                self._emit(
                    "token_discovered",
                    token=snap.symbol,
                    message=f"{snap.symbol} added to watchlist",
                    price=snap.price,
                    liquidity=snap.liquidity,
                    volume_5m=snap.volume_5m,
                )
                logger.info(
                    "loop_token_discovered",
                    token=snap.symbol,
                    liquidity=snap.liquidity,
                    volume_5m=snap.volume_5m,
                )
            else:
                self.state.open_signals[snap.token_address] = {
                    "symbol": snap.symbol,
                    "signal": "filtered",
                    "reasons": result.reasons[:3],
                    "at": now,
                }

        await self._analyze_watchlist(now)

    # ------------------------------------------------------ new-launch cycle
    async def _new_launch_cycle(self) -> None:
        """
        Fast scanner for newly launched Solana tokens.
        Uses the token-profiles/latest endpoint and the NewLaunchSniper strategy.
        Runs on a faster cadence than the standard scanner to catch tokens early.
        """
        try:
            snapshots = await self.dex_client.get_new_solana_pairs(
                max_age_seconds=int(self.settings.NEW_LAUNCH_MAX_AGE_MINUTES * 60),
                min_liquidity_usd=self.settings.NEW_LAUNCH_MIN_LIQUIDITY_USD,
            )
        except DexScreenerClientError as e:
            self._emit(
                "new_launch_scanner_error",
                level="warning",
                message=f"New-launch scanner error: {e}",
            )
            return

        if not snapshots:
            return

        now = time.time()
        new_tokens_found = 0

        for snap in snapshots:
            # Skip if already seen or already in watchlist
            if snap.token_address in self._new_launch_seen:
                continue
            if snap.token_address in self.state.watchlist:
                continue

            self._new_launch_seen.add(snap.token_address)

            # Update price feed
            self.state.prices[snap.token_address] = snap.price
            self.state.latest_snapshots[snap.token_address] = snap
            if self.simulator is not None:
                self.simulator.update_market(
                    snap.token_address, price=snap.price, liquidity_usd=snap.liquidity or 0.0
                )

            # Run new-launch filter
            assert self.new_launch_filter is not None
            filter_result = self.new_launch_filter.check(snap)
            if not filter_result.passed:
                logger.debug(
                    "new_launch_filtered",
                    token=snap.symbol,
                    reasons=filter_result.reasons,
                )
                continue

            new_tokens_found += 1

            # Add to watchlist
            self.state.watchlist[snap.token_address] = now

            self._emit(
                "new_launch_discovered",
                token=snap.symbol,
                message=f"🆕 New launch: {snap.symbol}",
                price=snap.price,
                liquidity=snap.liquidity,
                volume_5m=snap.volume_5m,
                pair_created=str(snap.pair_created_at) if snap.pair_created_at else None,
            )
            logger.info(
                "new_launch_discovered",
                token=snap.symbol,
                address=snap.token_address[:12],
                price=snap.price,
                liquidity=snap.liquidity,
            )

            # Immediately attempt buy with the sniper strategy
            await self._attempt_new_launch_buy(snap, now)

        if new_tokens_found > 0:
            self._emit(
                "new_launch_scan_complete",
                level="info",
                message=f"New-launch scan: {new_tokens_found} fresh token(s) found",
                tokens_found=new_tokens_found,
            )

    async def _attempt_new_launch_buy(
        self,
        snap: MarketSnapshot,
        now: float,
    ) -> None:
        """Run the new-launch sniper strategy and attempt a buy."""
        assert self.new_launch_strategy is not None

        # Calculate age
        token_age_hours = None
        if snap.pair_created_at:
            created = snap.pair_created_at.replace(tzinfo=None)
            token_age_hours = (now - created.timestamp()) / 3600.0

        context = StrategyContext(
            snapshot=snap,
            risk_score=self._heuristic_risk_score(snap),
            token_age_hours=token_age_hours,
        )

        try:
            signal = await self.new_launch_strategy.analyze(context)
        except Exception as e:
            self._record_loop_error("new_launch_strategy", e)
            return

        # Record signal for dashboard
        self.state.open_signals[snap.token_address] = {
            "symbol": snap.symbol,
            "signal": signal.signal.value,
            "score": signal.score,
            "confidence": signal.confidence,
            "reasons": signal.reasons[:5],
            "strategy": "new_launch_sniper",
            "at": now,
        }

        if signal.is_buy:
            await self._attempt_new_launch_buy_order(snap, signal, token_age_hours, now)

    async def _attempt_new_launch_buy_order(
        self,
        snap: MarketSnapshot,
        signal: StrategySignal,
        token_age_hours: Optional[float],
        now: float,
    ) -> None:
        """Execute a buy for a new-launch token with sniper-specific sizing."""
        token_risk = TokenRiskData(
            token_address=snap.token_address,
            symbol=snap.symbol,
            liquidity=snap.liquidity,
            volume_5m=snap.volume_5m,
            buys_5m=snap.buys_5m,
            sells_5m=snap.sells_5m,
            price=snap.price,
            token_age_hours=token_age_hours,
        )

        result = await self.orchestrator.process_buy_signal(
            token_address=snap.token_address,
            symbol=snap.symbol,
            snapshot=snap,
            token_risk=token_risk,
            portfolio_risk=self._portfolio_risk(),
            strategy_context=self._build_context(snap, now - (token_age_hours or 0) * 3600, now),
        )

        status = result.get("status")
        if status == "executed":
            self.balance_tracker.record_buy(
                amount_usd=result["size_usd"],
                fee_usd=result.get("fee_usd", 0.0),
            )
            self._emit(
                "new_launch_buy_executed",
                token=snap.symbol,
                message=f"🎯 New launch buy: {snap.symbol}",
                size_usd=result["size_usd"],
                entry_price=result["entry_price"],
                slippage_pct=result.get("slippage_pct"),
            )
            logger.info(
                "new_launch_buy_executed",
                token=snap.symbol,
                size_usd=result["size_usd"],
                entry_price=result["entry_price"],
            )
        elif status == "rejected":
            self.state.watchlist.pop(snap.token_address, None)
            self._emit(
                "new_launch_buy_rejected",
                token=snap.symbol,
                level="warning",
                message=f"New launch {snap.symbol} rejected: {result.get('reason')}",
                reason=result.get("reason"),
            )
        elif status == "failed":
            self._emit(
                "new_launch_buy_failed",
                token=snap.symbol,
                level="error",
                message=f"New launch buy failed: {snap.symbol}: {result.get('detail')}",
            )

    async def _analyze_watchlist(self, now: float) -> None:
        """Run strategy on watched tokens; attempt buys on BUY signals."""
        max_analyze = self.settings.MAX_CANDIDATES_PER_SCAN
        analyzed = 0
        for addr, discovered_at in list(self.state.watchlist.items()):
            snap = self.state.latest_snapshots.get(addr)
            if snap is None:
                continue

            context = self._build_context(snap, discovered_at, now)
            try:
                signal = await self.strategy.analyze(context)
            except Exception as e:
                self._record_loop_error("strategy", e)
                continue

            self.state.open_signals[addr] = {
                "symbol": snap.symbol,
                "signal": signal.signal.value,
                "score": signal.score,
                "confidence": signal.confidence,
                "reasons": signal.reasons[:5],
                "at": now,
            }

            if signal.is_buy and analyzed < max_analyze:
                analyzed += 1
                await self._attempt_buy(addr, snap, signal, discovered_at, now)

    def _build_context(self, snap: MarketSnapshot, discovered_at: float, now: float) -> StrategyContext:
        age_hours = (now - discovered_at) / 3600.0
        return StrategyContext(
            snapshot=snap,
            risk_score=self._heuristic_risk_score(snap),
            token_age_hours=age_hours if age_hours > 0 else None,
        )

    def _heuristic_risk_score(self, snap: MarketSnapshot) -> int:
        """Deterministic 0-100 score from observable market data (no on-chain checks in paper loop)."""
        score = 50
        liq = snap.liquidity or 0
        if liq >= 100_000:
            score += 20
        elif liq >= self.settings.MIN_LIQUIDITY_USD:
            score += 10
        else:
            score -= 15
        vol = snap.volume_5m or 0
        if vol >= self.settings.MIN_VOLUME_5M_USD * 2:
            score += 10
        elif vol < self.settings.MIN_VOLUME_5M_USD:
            score -= 10
        total_tx = snap.buys_5m + snap.sells_5m
        if total_tx > 0:
            buy_ratio = snap.buys_5m / total_tx
            if buy_ratio >= 0.6:
                score += 10
            elif buy_ratio < 0.4:
                score -= 10
        return max(0, min(100, score))

    async def _attempt_buy(
        self,
        addr: str,
        snap: MarketSnapshot,
        signal: StrategySignal,
        discovered_at: float,
        now: float,
    ) -> None:
        token_risk = TokenRiskData(
            token_address=addr,
            symbol=snap.symbol,
            liquidity=snap.liquidity,
            volume_5m=snap.volume_5m,
            buys_5m=snap.buys_5m,
            sells_5m=snap.sells_5m,
            price=snap.price,
            token_age_hours=(now - discovered_at) / 3600.0 if now > discovered_at else None,
        )

        result = await self.orchestrator.process_buy_signal(
            token_address=addr,
            symbol=snap.symbol,
            snapshot=snap,
            token_risk=token_risk,
            portfolio_risk=self._portfolio_risk(),
            strategy_context=self._build_context(snap, discovered_at, now),
        )

        status = result.get("status")
        if status == "executed":
            self.balance_tracker.record_buy(
                amount_usd=result["size_usd"],
                fee_usd=result.get("fee_usd", 0.0),
            )
            self._emit(
                "buy_executed",
                token=snap.symbol,
                message=f"Bought {snap.symbol}",
                size_usd=result["size_usd"],
                entry_price=result["entry_price"],
                slippage_pct=result.get("slippage_pct"),
            )
        elif status == "rejected":
            # Rejected candidates don't linger on the watchlist
            self.state.watchlist.pop(addr, None)
            self._emit(
                "buy_rejected",
                token=snap.symbol,
                level="warning",
                message=f"{snap.symbol} rejected: {result.get('reason')}",
                reason=result.get("reason"),
            )
        elif status == "failed":
            self._emit(
                "buy_failed",
                token=snap.symbol,
                level="error",
                message=f"{snap.symbol} buy failed: {result.get('detail')}",
            )
        # skipped: normal (already open / duplicate window) — no event spam

    # -------------------------------------------------------- position cycle
    async def _position_cycle(self) -> None:
        """Update prices from latest snapshots and evaluate exits."""
        if not self.position_manager.positions:
            return

        for addr in list(self.position_manager.positions.keys()):
            price = self.state.prices.get(addr, 0.0)
            if price <= 0:
                continue  # no fresh data: hold

            result = await self.orchestrator.process_price_update(addr, price)

            if result["status"] == "exited":
                self.balance_tracker.record_sell(
                    proceeds_usd=result["proceeds_usd"],
                    fee_usd=result["fee_usd"],
                    realized_pnl_usd=result["realized_pnl"],
                )
                self.state.watchlist.pop(addr, None)  # position done, stop analyzing
                self._emit(
                    "position_closed",
                    token=self._symbol_for(addr),
                    level="info" if result["realized_pnl"] >= 0 else "warning",
                    message=f"Closed {self._symbol_for(addr)} ({result['reason']})",
                    reason=result["reason"],
                    realized_pnl=round(result["realized_pnl"], 4),
                    realized_pnl_pct=round(result["realized_pnl_pct"], 2),
                )
            elif result["status"] == "failed":
                self._emit(
                    "sell_failed",
                    token=self._symbol_for(addr),
                    level="error",
                    message=f"Sell failed for {self._symbol_for(addr)}: {result.get('detail')}",
                )

        self._sync_balance_tracker()

    def _sync_balance_tracker(self) -> None:
        """Mark-to-market sync so dashboard equity reflects current prices."""
        total_position_value = 0.0
        for addr, pos in self.position_manager.positions.items():
            price = self.state.prices.get(addr, pos.entry_price)
            total_position_value += pos.quantity * price
        self.balance_tracker.update_position_value(total_position_value)

    def _symbol_for(self, addr: str) -> str:
        pos = self.position_manager.get(addr)
        if pos:
            return pos.symbol
        snap = self.state.latest_snapshots.get(addr)
        return snap.symbol if snap else addr[:8]

    # ---------------------------------------------------------------- helpers
    def _portfolio_risk(self) -> PortfolioRiskData:
        daily = self.pnl_calculator.daily_summary()

        # Live mode: use on-chain SOL balance as wallet balance
        if not self.settings.is_paper and self._solana_client:
            wallet_balance_usd = self.balance_tracker.sol_balance_usd
        else:
            wallet_balance_usd = max(0.0, self.simulator.cash_usd) if self.simulator else 0.0

        return PortfolioRiskData(
            wallet_balance_usd=wallet_balance_usd,
            total_exposure_usd=(
                (self.balance_tracker.position_value_usd if self.balance_tracker else 0.0)
                - (self.balance_tracker.cash_usd if self.balance_tracker else 0.0)
            ),
            open_positions=self.position_manager.open_count(),
            daily_pnl=daily.net_pnl,
            consecutive_losses=self.pnl_calculator.consecutive_losses(),
            daily_loss_usd=max(0.0, -daily.net_pnl),
        )

    async def close(self) -> None:
        """Clean up external resources (Jupiter, Solana clients)."""
        if self._jupiter_client:
            await self._jupiter_client.close()
        if self._solana_client:
            await self._solana_client.close()


def build_default_loop(search_query: str = "") -> TradingLoop:
    """Factory used by the app entry point."""
    return TradingLoop(dex_client=DexScreenerClient(), search_query=search_query)
