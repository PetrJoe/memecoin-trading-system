from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router, set_components
from app.api.security import get_security
from app.config import get_logger, get_settings

logger = get_logger(category="application")

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_api_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Meme Trader", docs_url=None, redoc_url=None, openapi_url=None)

    # Security components
    checker, sessions, limiter = get_security()
    set_components(checker, sessions, limiter)

    # Security headers on every response
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    # Failed-login counter feeding the rate limiter (4xx on /api/login)
    @app.middleware("http")
    async def login_rate_limit(request: Request, call_next):
        if request.url.path == "/api/login" and request.method == "POST":
            _, _, limiter = get_security()
            ip = request.client.host if request.client else "unknown"
            if limiter.is_blocked(ip):
                return JSONResponse(
                    status_code=429,
                    content={"ok": False, "message": "Too many attempts", "retry_after": limiter.seconds_until_retry(ip)},
                )
        response = await call_next(request)
        if request.url.path == "/api/login" and response.status_code == 401:
            limiter.record_failure(ip)
        return response

    app.include_router(router)

    # Single-page AJAX dashboard
    if (STATIC_DIR / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="dashboard")

    return app


def run_api_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    """Blocking server entry point for the web UI."""
    import uvicorn

    app = create_api_app()
    uvicorn.run(app, host=host, port=port, log_level="info")
