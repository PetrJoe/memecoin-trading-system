"""
Meme Trader — Autonomous Solana Memecoin Trading Bot.

Entry point: wires all services, starts the trading loop + workers +
web dashboard, and handles graceful shutdown.

    python -m app.main
"""
from __future__ import annotations

import asyncio
import signal
import sys

from app.api.app import create_api_app
from app.api.state import get_app_state
from app.config import get_logger, get_settings, setup_logging
from app.monitoring.health import HealthChecker
from app.workers.health_worker import HealthWorker
from app.workers.reconciliation_worker import ReconciliationWorker
from app.workers.trading_loop import TradingLoop

logger = get_logger(category="application")

BANNER = """
╔══════════════════════════════════════════════════════════════╗
║                     🕯️  MEME TRADER                          ║
╚══════════════════════════════════════════════════════════════╝
"""


def print_startup_banner() -> None:
    settings = get_settings()
    print(BANNER)
    if settings.is_paper:
        print("  ⚠️  PAPER TRADING — NO REAL TRANSACTIONS")
    elif settings.is_live_safe:
        print("  ⚠️  LIVE-SAFE MODE — tiny real positions")
    else:
        print("  🔴 LIVE MODE — REAL MONEY AT RISK")
    print(f"  Mode:        {settings.TRADING_MODE.value}")
    print(f"  Trading:     {'ENABLED' if settings.TRADING_ENABLED else 'signals only (TRADING_ENABLED=false)'}")
    print(f"  Environment: {settings.APP_ENV.value}")
    print(f"  Paper bal:   ${settings.PAPER_STARTING_BALANCE_USD:,.2f}")
    if settings.NEW_LAUNCH_ENABLED:
        print(f"  Sniper:      🎯 NEW-LAUNCH enabled (max age: {settings.NEW_LAUNCH_MAX_AGE_MINUTES:.0f}min)")
    if not settings.is_paper:
        print(f"  RPC:         {settings.SOLANA_RPC_URL}")
        key = settings.BOT_PRIVATE_KEY.get_secret_value()
        if key:
            from app.blockchain.wallet import WalletService
            try:
                ws = WalletService(private_key_b58=key)
                print(f"  Wallet:      {ws.address}")
            except Exception:
                print("  Wallet:      ⚠️  Invalid BOT_PRIVATE_KEY")
        else:
            print("  Wallet:      ⚠️  BOT_PRIVATE_KEY not set")
    print(f"  Web UI:      {'enabled' if settings.WEB_UI_ENABLED else 'disabled'}")
    if settings.WEB_UI_ENABLED:
        if not settings.WEB_UI_PASSWORD.get_secret_value():
            print("  ⚠️  WEB_UI_PASSWORD empty — login disabled (set it to use the dashboard)")
        else:
            print("  Dashboard:   http://127.0.0.1:8080  (login with WEB_UI_USERNAME/PASSWORD)")
    print()


async def check_dependencies() -> bool:
    """Pre-flight dependency check; paper mode tolerates degraded deps."""
    settings = get_settings()
    checker = HealthChecker()
    try:
        checks = await checker.check_all()
        overall = checker.aggregate(checks)
        for c in checks:
            logger.info(
                "dependency_check",
                name=c.name,
                status=c.status,
                latency_ms=c.latency_ms,
                detail=c.detail,
            )
        if overall == "error" and not settings.is_paper:
            logger.error("startup_aborted_critical_dependency")
            return False
        # Paper mode: continue even if degraded (scanner may recover)
        return True
    finally:
        await checker.close()


class AppRuntime:
    """Owns all long-running services and orchestrates shutdown."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.state = get_app_state()
        self.trading_loop: TradingLoop | None = None
        self.health_worker: HealthWorker | None = None
        self.recon_worker: ReconciliationWorker | None = None
        self.api_server = None
        self._api_task: asyncio.Task | None = None
        self._shutdown = asyncio.Event()

    async def start(self) -> None:
        import uvicorn

        # 1. Trading loop (registers components into AppState)
        self.trading_loop = TradingLoop()
        await self.trading_loop.start()

        # 2. Workers
        self.health_worker = HealthWorker()
        await self.health_worker.start()

        self.recon_worker = ReconciliationWorker()
        await self.recon_worker.start()

        # 3. Web dashboard/API
        if self.settings.WEB_UI_ENABLED:
            app = create_api_app()
            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8080,
                log_level="warning",
            )
            self.api_server = uvicorn.Server(config)
            self._api_task = asyncio.create_task(self.api_server.serve())
            logger.info("api_server_started", port=config.port)

    async def run_forever(self) -> None:
        await self._shutdown.wait()

    def request_shutdown(self) -> None:
        logger.info("shutdown_requested")
        self._shutdown.set()

    async def shutdown(self) -> None:
        """Graceful stop: no new trades → finish in-flight → stop workers → exit."""
        logger.info("graceful_shutdown_begin")

        # 1. Stop accepting new trades
        self.state.trading_enabled = False

        # 2. Stop the loop (finishes current cycle via cancellation at await points)
        if self.trading_loop:
            await self.trading_loop.stop()

        # 3. Stop workers
        if self.recon_worker:
            await self.recon_worker.stop()
        if self.health_worker:
            await self.health_worker.stop()

        # 4. Stop API server (await clean teardown, bounded)
        if self.api_server and self._api_task:
            self.api_server.should_exit = True
            try:
                await asyncio.wait_for(self._api_task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.warning("api_server_shutdown_timeout")

        # 5. Close scanner client
        if self.trading_loop and self.trading_loop.dex_client:
            await self.trading_loop.dex_client.close()

        # 6. Close live execution clients (Jupiter, Solana RPC)
        if self.trading_loop:
            await self.trading_loop.close()

        logger.info("graceful_shutdown_complete")


async def run() -> None:
    setup_logging("INFO")
    print_startup_banner()

    runtime = AppRuntime()

    # Signal handlers → graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, runtime.request_shutdown)
        except NotImplementedError:  # Windows
            signal.signal(sig, lambda *_: runtime.request_shutdown())

    # Pre-flight checks
    if not await check_dependencies():
        sys.exit(1)

    await runtime.start()

    if runtime.trading_loop:
        logger.info(
            "bot_running",
            mode=runtime.settings.TRADING_MODE.value,
            paper_balance=runtime.settings.PAPER_STARTING_BALANCE_USD,
        )

    try:
        await runtime.run_forever()
    finally:
        await runtime.shutdown()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
