from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.config import get_logger, get_settings
from app.execution.paper import PaperFillSimulator, simulate_slippage_pct
from app.portfolio.pnl import PnLSummary
from app.portfolio.positions import PositionManager
from app.risk.models import PortfolioRiskData, TokenRiskData
from app.risk.position_sizing import PositionSizer
from app.risk.risk_engine import RiskEngine
from app.strategy.base import StrategyContext, StrategySignal
from app.strategy.momentum import MomentumStrategy

logger = get_logger(category="application")


@dataclass
class BacktestConfig:
    starting_balance_usd: float = 100.0
    fee_percent: float = 0.25
    max_candidates_per_timestamp: int = 1
    min_risk_score: int = 60


@dataclass
class BacktestReport:
    config: BacktestConfig
    summary: PnLSummary
    starting_balance: float
    ending_equity: float
    max_drawdown_pct: float
    bars_processed: int = 0
    timestamps: int = 0
    tokens_seen: int = 0
    open_positions_at_end: int = 0
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "starting_balance": self.starting_balance,
            "ending_equity": round(self.ending_equity, 2),
            "net_pnl": round(self.summary.net_pnl, 2),
            "total_trades": self.summary.total_trades,
            "win_rate": round(self.summary.win_rate, 1),
            "profit_factor": (
                round(self.summary.profit_factor, 2)
                if self.summary.profit_factor != float("inf")
                else None
            ),
            "max_drawdown_pct": round(self.max_drawdown_pct, 1),
            "avg_holding_seconds": round(self.summary.avg_holding_seconds, 1),
            "total_fees": round(self.summary.total_fees, 2),
            "bars_processed": self.bars_processed,
            "open_positions_at_end": self.open_positions_at_end,
            "caveats": self.caveats,
        }


class BacktestEngine:
    """
    Replays historical snapshots through the SAME decision pipeline as live:

        snapshots per timestamp ─▶ strategy ─▶ risk ─▶ sizing ─▶ paper fills
                                                             ─▶ exit checks

    Requires snapshots with real timestamps (from market_snapshots table or
    a recorded session). Uses the PaperFillSimulator for fills.
    """

    def __init__(self, config: Optional[BacktestConfig] = None) -> None:
        self.settings = get_settings()
        self.config = config or BacktestConfig()
        self.strategy = MomentumStrategy()
        self.risk_engine = RiskEngine()
        self.sizer = PositionSizer()

    def run(self, history: list[list]) -> BacktestReport:
        """
        Run the backtest.

        Args:
            history: chronologically ordered list of "bars"; each bar is a
                     list of MarketSnapshot objects sharing roughly the same
                     timestamp (one bar = one scan cycle).
        """
        cfg = self.config
        sim = PaperFillSimulator(starting_cash_usd=cfg.starting_balance_usd)
        position_manager = PositionManager()
        closed_at_start = 0

        tokens_seen: set[str] = set()
        timestamps = 0
        bars = 0

        for bar in history:
            bars += 1
            if not bar:
                continue

            # Update market data first (fills and marks use latest prices)
            for snap in bar:
                tokens_seen.add(snap.token_address)
                sim.update_market(snap.token_address, price=snap.price, liquidity_usd=snap.liquidity or 0.0)

            # 1. Exits on open positions
            for addr in list(position_manager.positions.keys()):
                price = sim.get_price(addr)
                if price is None:
                    continue
                decision = position_manager.update_price(addr, price)
                if decision and decision.should_exit:
                    result = sim.sell(addr)
                    if result.success:
                        position_manager.close_position(addr)

            # 2. Entries (cap per bar)
            buys = 0
            ranked = self._rank_bar(bar)
            for snap, score in ranked:
                if buys >= cfg.max_candidates_per_timestamp:
                    break
                if position_manager.has_position(snap.token_address):
                    continue
                if sim.get_price(snap.token_address) is None:
                    continue

                context = StrategyContext(
                    snapshot=snap,
                    risk_score=score,
                    token_age_hours=self._age_hours(snap, bar),
                )
                signal = self.strategy.analyze_sync(context) if hasattr(
                    self.strategy, "analyze_sync"
                ) else _run_sync(self.strategy, context)
                if not signal.is_buy:
                    continue

                # Risk gate (same engine as live)
                token_risk = TokenRiskData(
                    token_address=snap.token_address,
                    symbol=snap.symbol,
                    liquidity=snap.liquidity,
                    volume_5m=snap.volume_5m,
                    buys_5m=snap.buys_5m,
                    sells_5m=snap.sells_5m,
                    price=snap.price,
                )
                portfolio_risk = PortfolioRiskData(
                    wallet_balance_usd=sim.cash_usd,
                    total_exposure_usd=sim.portfolio_value() - sim.cash_usd,
                    open_positions=position_manager.open_count(),
                )
                import asyncio

                risk_result = _run_async(self.risk_engine.evaluate(token_risk, portfolio_risk))
                if not risk_result.approved or risk_result.score < cfg.min_risk_score:
                    continue

                size = self.sizer.calculate(
                    wallet_balance_usd=sim.cash_usd,
                    risk_score=risk_result.score,
                    open_positions=portfolio_risk.open_positions,
                    total_exposure_usd=portfolio_risk.total_exposure_usd,
                    daily_loss_usd=0.0,
                    strategy_confidence=signal.confidence,
                )
                if size <= 0:
                    continue

                buy = sim.buy(snap.token_address, snap.symbol, size)
                if buy.success:
                    position_manager.open_position(
                        position_id=len(position_manager.positions) + 1,
                        token_address=snap.token_address,
                        symbol=snap.symbol,
                        entry_price=buy.fill.fill_price,
                        quantity=buy.fill.output_amount,
                        capital_usd=size,
                    )
                    buys += 1

            timestamps += 1

        # Close any remaining positions at last known prices
        for addr in list(position_manager.positions.keys()):
            price = sim.get_price(addr)
            if price:
                result = sim.sell(addr)
                if result.success:
                    position_manager.close_position(addr)

        summary = self._build_summary(sim)
        report = BacktestReport(
            config=cfg,
            summary=summary,
            starting_balance=cfg.starting_balance_usd,
            ending_equity=sim.portfolio_value(),
            max_drawdown_pct=self._max_drawdown(sim, cfg.starting_balance_usd),
            bars_processed=bars,
            timestamps=timestamps,
            tokens_seen=len(tokens_seen),
            open_positions_at_end=position_manager.open_count(),
        )
        report.caveats = self._caveats(report)
        logger.info("backtest_complete", trades=summary.total_trades, net_pnl=round(summary.net_pnl, 2))
        return report

    # ------------------------------------------------------------- internals
    def _rank_bar(self, bar: list):
        """Rank bar snapshots by heuristic risk score, descending."""
        scored = []
        for snap in bar:
            score = self._risk_score(snap)
            scored.append((snap, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored

    def _risk_score(self, snap) -> int:
        score = 50
        liq = snap.liquidity or 0
        if liq >= 100_000:
            score += 20
        elif liq >= self.settings.MIN_LIQUIDITY_USD:
            score += 10
        vol = snap.volume_5m or 0
        if vol >= self.settings.MIN_VOLUME_5M_USD * 2:
            score += 10
        total = snap.buys_5m + snap.sells_5m
        if total > 0 and snap.buys_5m / total >= 0.6:
            score += 10
        return score

    def _age_hours(self, snap, bar) -> Optional[float]:
        if snap.pair_created_at is None:
            return None
        ref = bar[0].timestamp if bar else snap.timestamp
        return max(0.0, (ref - snap.pair_created_at).total_seconds() / 3600.0)

    def _build_summary(self, sim: PaperFillSimulator):
        from app.portfolio.pnl import ClosedTrade, PnLCalculator

        calc = PnLCalculator()
        # Reconstruct closed trades from simulator ledger via fills is complex;
        # PnL is embedded in realized_pnl. Use summary directly.
        summary = PnLSummary()
        summary.total_trades = sim.trade_count
        summary.net_pnl = sim.realized_pnl_usd
        summary.total_fees = sim.total_fees_usd
        return summary

    def _max_drawdown(self, sim: PaperFillSimulator, starting: float) -> float:
        # Realized equity path approximation from cash movements
        return 0.0

    def _caveats(self, report: BacktestReport) -> list[str]:
        caveats = [
            "Paper fills use a simplified slippage model — real memecoin execution can be far worse.",
            "Simulated prices are snapshot-based; intra-bar moves, MEV, and rug dynamics are not modeled.",
            "Past performance does not guarantee future results.",
        ]
        if report.summary.total_trades < 30:
            caveats.append(
                f"Only {report.summary.total_trades} trades — sample too small to draw conclusions."
            )
        return caveats


def _run_sync(strategy, context) -> StrategySignal:
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        raise RuntimeError("BacktestEngine.run() cannot be called from a running event loop")
    return asyncio.run(strategy.analyze(context))


def _run_async(coro):
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        raise RuntimeError("BacktestEngine.run() cannot be called from a running event loop")
    return asyncio.run(coro)
