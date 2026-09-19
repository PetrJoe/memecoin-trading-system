from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.schemas import (
    ActionResponse,
    BalanceOut,
    CircuitBreakerOut,
    EventOut,
    EventsResponse,
    HealthResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    PnLSummaryOut,
    PositionOut,
    RiskOut,
    StatusResponse,
)
from app.api.security import (
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    CredentialChecker,
    LoginRateLimiter,
    SessionStore,
)
from app.api.state import AppState, get_app_state
from app.config import get_logger, get_settings

logger = get_logger(category="security")

router = APIRouter()

# Component instances are attached by the app factory (see create_api_app)
# so tests can swap them; they default to globals from security.py
_components: dict = {}


def set_components(checker: CredentialChecker, sessions: SessionStore, limiter: LoginRateLimiter) -> None:
    _components["checker"] = checker
    _components["sessions"] = sessions
    _components["limiter"] = limiter


def _get_components() -> tuple[CredentialChecker, SessionStore, LoginRateLimiter]:
    if not _components:
        from app.api.security import get_security

        set_components(*get_security())
    return _components["checker"], _components["sessions"], _components["limiter"]


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _get_session_token(request: Request) -> Optional[str]:
    return request.cookies.get(SESSION_COOKIE_NAME)


def require_auth(request: Request) -> tuple[str, dict]:
    """Dependency equivalent: returns (session_token, session_data) or raises 401."""
    token = _get_session_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    _, sessions, _ = _get_components()
    session = sessions.validate(token)
    if session is None:
        raise HTTPException(status_code=401, detail="Session expired")
    return token, session


def require_auth_csrf(request: Request) -> tuple[str, dict]:
    """For state-changing (non-GET) endpoints: auth + CSRF double-submit check."""
    token, session = require_auth(request)
    csrf_header = request.headers.get(CSRF_HEADER_NAME, "")
    _, sessions, _ = _get_components()
    if not csrf_header or not sessions.validate_csrf(token, csrf_header):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return token, session


# --------------------------------------------------------------------- auth
@router.post("/api/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request, response: Response) -> LoginResponse:
    settings = get_settings()
    if not settings.WEB_UI_ENABLED:
        raise HTTPException(status_code=404, detail="Web UI disabled")

    checker, sessions, limiter = _get_components()
    ip = _client_ip(request)

    if not checker.login_enabled:
        # Fail closed: no password configured => no login
        logger.warning("web_login_disabled")
        return LoginResponse(ok=False, message="Login disabled: no password configured")

    if limiter.is_blocked(ip):
        retry = limiter.seconds_until_retry(ip)
        logger.warning("web_login_rate_limited", ip=ip)
        return LoginResponse(
            ok=False,
            message="Too many failed attempts. Try again later.",
            retry_after=retry,
        )

    if not checker.verify(body.username, body.password):
        limiter.record_failure(ip)
        logger.warning("web_login_failed", ip=ip)
        remaining = limiter.max_failures - len(limiter._failures.get(ip, []))
        return LoginResponse(
            ok=False,
            message="Invalid credentials",
            retry_after=None if remaining > 0 else limiter.seconds_until_retry(ip),
        )

    limiter.record_success(ip)
    raw_token, csrf_token = sessions.create(body.username)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        samesite="strict",
        secure=settings.WEB_UI_COOKIE_SECURE,
        max_age=settings.WEB_UI_SESSION_TTL_MINUTES * 60,
        path="/",
    )
    logger.info("web_login_success", ip=ip)
    state = get_app_state()
    state.event_log.emit("web_login", level="info", message=f"User {body.username} logged in", ip=ip)
    return LoginResponse(ok=True, csrf_token=csrf_token)


@router.post("/api/logout", response_model=LogoutResponse)
async def logout(request: Request, response: Response) -> LogoutResponse:
    token, _ = require_auth_csrf(request)
    _, sessions, _ = _get_components()
    sessions.destroy(token)
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return LogoutResponse(ok=True)


# ------------------------------------------------------------------- health
@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Unauthenticated lightweight liveness probe (no sensitive data)."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app="meme-trader",
        database="configured" if settings.DATABASE_URL else "missing",
        mode=settings.TRADING_MODE.value,
        uptime_seconds=get_app_state().uptime_seconds,
    )


# ------------------------------------------------------------------ metrics
@router.get("/api/metrics")
async def metrics(request: Request) -> dict:
    """Operational metrics: resources, loop health, dependency status."""
    require_auth(request)
    from app.monitoring.metrics import MetricsCollector
    from app.monitoring.health import HealthChecker

    state = get_app_state()
    settings = get_settings()

    collector = MetricsCollector()
    m = collector.collect()
    threshold_warnings = collector.check_thresholds(m)

    # Dependency health (cheap, cached per call)
    checker = HealthChecker()
    try:
        checks = await checker.check_all()
        deps = {
            c.name: {"status": c.status, "latency_ms": c.latency_ms, "detail": c.detail}
            for c in checks
        }
        overall = checker.aggregate(checks)
    finally:
        await checker.close()

    return {
        "status": overall,
        "resources": {
            "cpu_percent": m.cpu_percent,
            "memory_rss_mb": round(m.memory_rss_mb, 1),
            "memory_percent": round(m.memory_percent, 1),
            "threads": m.threads,
            "open_files": m.open_files,
            "disk_used_percent": m.disk_used_percent,
            "disk_free_mb": m.disk_free_mb,
            "uptime_seconds": round(m.uptime_seconds, 1),
        },
        "dependencies": deps,
        "trading_loop": {
            "running": state.trading_enabled,
            "scans_completed": state.scans_completed,
            "last_scan_at": state.last_scan_at,
            "watchlist_size": len(state.watchlist),
            "tracked_prices": len(state.prices),
            "open_signals": len(state.open_signals),
            "last_error": state.last_loop_error,
            "error_count": len(state.loop_errors),
        },
        "threshold_warnings": threshold_warnings,
        "mode": settings.TRADING_MODE.value,
    }


# ------------------------------------------------------------------- status
def _position_out(pos, price: float) -> PositionOut:
    return PositionOut(
        position_id=pos.position_id,
        token_address=pos.token_address,
        symbol=pos.symbol,
        entry_price=pos.entry_price,
        current_price=price or pos.entry_price,
        quantity=pos.quantity,
        capital_usd=pos.capital_usd,
        value_usd=pos.quantity * (price or pos.entry_price),
        unrealized_pnl=pos.unrealized_pnl(price or pos.entry_price),
        unrealized_pnl_pct=pos.unrealized_pnl_pct(price or pos.entry_price),
        stop_loss=pos.stop_loss,
        take_profit=pos.take_profit,
        trailing_stop_pct=pos.trailing_stop_pct,
        highest_price=pos.highest_price,
        opened_at=pos.opened_at,
    )


@router.get("/api/status", response_model=StatusResponse)
async def status(request: Request) -> StatusResponse:
    require_auth(request)
    state: AppState = get_app_state()
    settings = get_settings()

    cb_out = CircuitBreakerOut(state="NORMAL", can_trade=True, is_paused=False, recent_events=[])
    if state.circuit_breaker is not None:
        cb = state.circuit_breaker
        cb_out = CircuitBreakerOut(
            state=cb.state.value,
            can_trade=cb.can_trade,
            is_paused=cb.is_paused,
            recent_events=[
                {"state": e.state.value, "reason": e.reason.value, "message": e.message, "timestamp": e.timestamp}
                for e in cb.events[-5:]
            ],
        )

    balance_out = None
    if state.balance_tracker is not None:
        bt = state.balance_tracker
        balance_out = BalanceOut(
            cash_usd=bt.cash_usd,
            position_value_usd=bt.position_value_usd,
            total_usd=bt.total_equity,
            starting_balance_usd=bt.starting_balance_usd,
            realized_pnl=bt.realized_pnl,
            unrealized_pnl=bt.unrealized_pnl,
            total_pnl=bt.total_pnl,
            total_pnl_pct=bt.total_pnl_pct,
            total_fees=bt.total_fees_usd,
        )

    positions_out: list[PositionOut] = []
    if state.position_manager is not None:
        for addr, pos in state.position_manager.positions.items():
            price = state.prices.get(addr, 0.0)
            positions_out.append(_position_out(pos, price))

    pnl_out = None
    if state.pnl_calculator is not None:
        calc = state.pnl_calculator
        s = calc.summary()
        starting = state.balance_tracker.starting_balance_usd if state.balance_tracker else 100.0
        pnl_out = PnLSummaryOut(
            total_trades=s.total_trades,
            winning_trades=s.winning_trades,
            losing_trades=s.losing_trades,
            win_rate=s.win_rate,
            net_pnl=s.net_pnl,
            gross_profit=s.gross_profit,
            gross_loss=s.gross_loss,
            profit_factor=(s.profit_factor if s.profit_factor != float("inf") else None),
            average_win=s.average_win,
            average_loss=s.average_loss,
            best_trade_pnl=s.best_trade_pnl,
            worst_trade_pnl=s.worst_trade_pnl,
            avg_holding_seconds=s.avg_holding_seconds,
            consecutive_losses=calc.consecutive_losses(),
            max_drawdown_pct=calc.max_drawdown_pct(starting),
            total_fees=s.total_fees,
        )

    risk_out = None
    if state.position_manager is not None:
        exposure = sum(
            p.quantity * state.prices.get(a, p.entry_price)
            for a, p in state.position_manager.positions.items()
        )
        risk_out = RiskOut(
            max_position_usd=settings.MAX_POSITION_USD,
            max_open_positions=settings.MAX_OPEN_POSITIONS,
            max_daily_loss_usd=settings.MAX_DAILY_LOSS_USD,
            max_total_exposure_usd=settings.MAX_TOTAL_EXPOSURE_USD,
            max_consecutive_losses=settings.MAX_CONSECUTIVE_LOSSES,
            current_open_positions=len(positions_out),
            current_exposure_usd=exposure,
            consecutive_losses=(state.pnl_calculator.consecutive_losses() if state.pnl_calculator else 0),
            daily_net_pnl=(state.pnl_calculator.daily_summary().net_pnl if state.pnl_calculator else 0.0),
        )

    return StatusResponse(
        mode=settings.TRADING_MODE.value,
        trading_enabled=state.trading_enabled,
        uptime_seconds=state.uptime_seconds,
        circuit_breaker=cb_out,
        balance=balance_out,
        open_positions=positions_out,
        pnl=pnl_out,
        risk=risk_out,
        paper_mode=settings.is_paper,
        scans_completed=state.scans_completed,
        last_scan_at=state.last_scan_at,
    )


@router.get("/api/events", response_model=EventsResponse)
async def events(request: Request, since: float = 0.0, limit: int = 100) -> EventsResponse:
    require_auth(request)
    state = get_app_state()
    all_events = state.event_log.recent(limit=min(limit, 500))
    if since > 0:
        all_events = [e for e in all_events if e.timestamp > since]
    return EventsResponse(
        events=[
            EventOut(event_type=e.event_type, level=e.level, message=e.message, data=e.data, timestamp=e.timestamp)
            for e in all_events
        ],
        count=len(all_events),
    )


# ------------------------------------------------------------------ actions
@router.post("/api/actions/pause", response_model=ActionResponse)
async def pause_trading(request: Request) -> ActionResponse:
    require_auth_csrf(request)
    state = get_app_state()
    if state.circuit_breaker is None:
        raise HTTPException(status_code=503, detail="Circuit breaker not initialized")
    state.circuit_breaker.manual_pause("Paused via web UI")
    state.event_log.emit("trading_paused", level="warning", message="Trading paused via web UI")
    logger.info("web_action_pause")
    return ActionResponse(ok=True, message="Trading paused")


@router.post("/api/actions/resume", response_model=ActionResponse)
async def resume_trading(request: Request) -> ActionResponse:
    require_auth_csrf(request)
    state = get_app_state()
    if state.circuit_breaker is None:
        raise HTTPException(status_code=503, detail="Circuit breaker not initialized")
    state.circuit_breaker.resume()
    state.event_log.emit("trading_resumed", level="info", message="Trading resumed via web UI")
    logger.info("web_action_resume")
    return ActionResponse(ok=True, message="Trading resumed")


@router.post("/api/actions/positions/{token_address}/close", response_model=ActionResponse)
async def close_position(token_address: str, request: Request) -> ActionResponse:
    require_auth_csrf(request)
    state = get_app_state()
    if state.orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    result = await state.orchestrator.close_position_now(token_address, reason="MANUAL")
    if result["status"] == "skipped":
        return ActionResponse(ok=False, message=f"Cannot close: {result.get('reason')}")
    if result["status"] == "failed":
        return ActionResponse(ok=False, message=f"Close failed: {result.get('detail')}")
    state.event_log.emit(
        "position_closed_manual",
        level="info",
        message=f"Position closed manually",
        token=token_address,
        pnl=result.get("realized_pnl"),
    )
    return ActionResponse(
        ok=True,
        message="Position closed",
        detail={"realized_pnl": result.get("realized_pnl"), "reason": result.get("reason")},
    )


@router.post("/api/actions/emergency-close-all", response_model=ActionResponse)
async def emergency_close_all(request: Request) -> ActionResponse:
    require_auth_csrf(request)
    state = get_app_state()
    if state.orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    state.circuit_breaker.emergency("Emergency stop via web UI") if state.circuit_breaker else None
    results = await state.orchestrator.emergency_close_all()
    closed = sum(1 for r in results if r.get("status") == "exited")
    state.event_log.emit(
        "emergency_close_all",
        level="error",
        message=f"Emergency stop: {closed} position(s) closed",
        results=results,
    )
    logger.warning("web_action_emergency", closed=closed)
    return ActionResponse(ok=True, message=f"Emergency stop: {closed} position(s) closed", detail={"results": results})
