import time

import pytest
from fastapi.testclient import TestClient

from app.api.routes import set_components
from app.api.security import CredentialChecker, LoginRateLimiter, SessionStore
from app.api.state import AppState, set_app_state
from app.api.app import create_api_app
from app.execution.orchestrator import TradeOrchestrator
from app.execution.paper import PaperFillSimulator
from app.portfolio.pnl import PnLCalculator
from app.portfolio.positions import PositionManager
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.exposure import ExposureTracker
from app.risk.position_sizing import PositionSizer
from app.risk.risk_engine import RiskEngine
from app.scanner.models import MarketSnapshot
from app.config.settings import get_settings

WSOL = "So11111111111111111111111111111111111111112"
TOKEN = "TokenAddr111111111111111111111111111111"


def make_snapshot(price=1.0):
    return MarketSnapshot(
        token_address=TOKEN,
        pair_address="PairAddr111111111111111111111111111111",
        symbol="TKN",
        name="Test Token",
        price=price,
        liquidity=50_000,
        volume_5m=10_000,
        buys_5m=60,
        sells_5m=20,
    )


def wire_state(orch=None, starting_cash=100.0):
    """Build a fully wired AppState for API tests."""
    sim = PaperFillSimulator(starting_cash_usd=starting_cash)
    sim.update_market(TOKEN, price=1.0, liquidity_usd=50_000)

    from app.portfolio.balances import BalanceTracker

    state = AppState()
    state.orchestrator = orch
    state.position_manager = orch.position_manager if orch else PositionManager()
    state.balance_tracker = BalanceTracker(starting_balance_usd=starting_cash)
    state.pnl_calculator = orch.pnl_calculator if orch else PnLCalculator()
    state.circuit_breaker = orch.circuit_breaker if orch else CircuitBreaker()
    state.paper_simulator = sim
    state.prices = {TOKEN: 1.0}
    state.mode = "paper"
    state.trading_enabled = False
    set_app_state(state)
    return state, sim


@pytest.fixture
def client(monkeypatch):
    # Ensure a deterministic password for auth tests
    import os

    monkeypatch.setenv("WEB_UI_PASSWORD", "test-password-123")
    monkeypatch.setenv("WEB_UI_USERNAME", "admin")
    get_settings.cache_clear()

    set_components(
        CredentialChecker(),
        SessionStore(ttl_minutes=60),
        LoginRateLimiter(max_failures=5, window_seconds=300),
    )
    app = create_api_app()
    with TestClient(app) as c:
        yield c


def login(client, username="admin", password="test-password-123"):
    return client.post("/api/login", json={"username": username, "password": password})


class TestAuth:
    def test_login_success_sets_cookie_and_csrf(self, client):
        resp = login(client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["csrf_token"]
        assert "mt_session" in resp.cookies

    def test_login_wrong_password(self, client):
        resp = login(client, password="wrong")
        assert resp.json()["ok"] is False
        assert resp.json()["message"] == "Invalid credentials"

    def test_login_wrong_username(self, client):
        resp = login(client, username="nope")
        assert resp.json()["ok"] is False

    def test_status_requires_auth(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 401

    def test_events_requires_auth(self, client):
        resp = client.get("/api/events")
        assert resp.status_code == 401

    def test_logout_kills_session(self, client):
        login(client)
        status = client.get("/api/status")
        assert status.status_code == 200
        # Logout requires CSRF; fetch it from login
        csrf = login(client).json()["csrf_token"]
        resp = client.post("/api/logout", headers={"X-CSRF-Token": csrf})
        assert resp.json()["ok"] is True
        assert client.get("/api/status").status_code == 401

    def test_actions_require_csrf(self, client):
        login(client)
        resp = client.post("/api/actions/pause")  # no CSRF header
        assert resp.status_code == 403

    def test_health_is_unauthenticated(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "password" not in resp.text.lower()


class TestRateLimiting:
    def test_rate_limit_after_max_failures(self, client):
        for _ in range(5):
            login(client, password="wrong")
        resp = login(client, password="test-password-123")
        # 6th attempt (even with correct creds) must be blocked
        assert resp.json()["ok"] is False
        assert resp.json()["retry_after"] is not None


class TestMetricsEndpoint:
    def test_metrics_requires_auth(self, client):
        resp = client.get("/api/metrics")
        assert resp.status_code == 401

    def test_metrics_payload(self, client):
        wire_state()
        login(client)
        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded", "error")
        assert "resources" in data
        assert "dependencies" in data
        assert "trading_loop" in data
        assert "cpu_percent" in data["resources"]
        assert "threshold_warnings" in data

    def test_metrics_no_secrets(self, client):
        wire_state()
        login(client)
        resp = client.get("/api/metrics")
        text = resp.text.lower()
        for secret in ("password", "private_key", "secret"):
            assert secret not in text, f"leaked: {secret}"


class TestStatusEndpoint:
    def test_status_empty_state(self, client):
        wire_state()
        login(client)
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "paper"
        assert data["paper_mode"] is True
        assert data["open_positions"] == []
        assert data["balance"]["total_usd"] == 100.0
        assert data["pnl"]["total_trades"] == 0
        assert data["circuit_breaker"]["state"] == "NORMAL"

    def test_status_no_secrets(self, client):
        wire_state()
        login(client)
        resp = client.get("/api/status")
        text = resp.text.lower()
        for secret in ("password", "private_key", "secret", "token=", "bot_private"):
            assert secret not in text, f"leaked: {secret}"


class TestEventsEndpoint:
    def test_events_auth_required_and_payload(self, client):
        state, _ = wire_state()
        login(client)
        state.event_log.emit("test_event", level="info", message="hello", token="ABC")
        resp = client.get("/api/events")
        assert resp.status_code == 200
        data = resp.json()
        types = [e["event_type"] for e in data["events"]]
        assert "test_event" in types
        test_event = next(e for e in data["events"] if e["event_type"] == "test_event")
        assert test_event["data"]["token"] == "ABC"


class TestActions:
    def _build_orch(self, sim):
        orch = TradeOrchestrator(
            risk_engine=RiskEngine(),
            position_sizer=PositionSizer(),
            circuit_breaker=CircuitBreaker(),
            position_manager=PositionManager(),
            pnl_calculator=PnLCalculator(),
            exposure_tracker=ExposureTracker(),
            executor=_ApiStubExecutor(sim),
        )
        return orch

    def _open_position(self, client, orch, sim):
        orch.executor.sim = sim
        import asyncio

        asyncio.run(
            orch.process_buy_signal(
                token_address=TOKEN,
                symbol="TKN",
                snapshot=make_snapshot(),
                token_risk=_token_risk(),
                portfolio_risk=_portfolio_risk(),
            )
        )

    def test_pause_resume(self, client):
        state, _ = wire_state()
        login(client)
        csrf = client.post("/api/login", json={"username": "admin", "password": "test-password-123"}).json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}

        resp = client.post("/api/actions/pause", headers=headers)
        assert resp.json()["ok"] is True
        assert state.circuit_breaker.is_paused

        resp = client.post("/api/actions/resume", headers=headers)
        assert resp.json()["ok"] is True
        assert state.circuit_breaker.can_trade

    def test_close_position_endpoint(self, client):
        sim = PaperFillSimulator(starting_cash_usd=100.0)
        sim.update_market(TOKEN, price=1.0, liquidity_usd=50_000)
        orch = self._build_orch(sim)
        state, _ = wire_state(orch=orch)
        self._open_position(client, orch, sim)
        assert orch.position_manager.has_position(TOKEN)

        login(client)
        csrf = client.post("/api/login", json={"username": "admin", "password": "test-password-123"}).json()["csrf_token"]
        resp = client.post(f"/api/actions/positions/{TOKEN}/close", headers={"X-CSRF-Token": csrf})
        assert resp.json()["ok"] is True
        assert not orch.position_manager.has_position(TOKEN)

    def test_emergency_close_all(self, client):
        sim = PaperFillSimulator(starting_cash_usd=100.0)
        sim.update_market(TOKEN, price=1.0, liquidity_usd=50_000)
        orch = self._build_orch(sim)
        state, _ = wire_state(orch=orch)
        self._open_position(client, orch, sim)

        login(client)
        csrf = client.post("/api/login", json={"username": "admin", "password": "test-password-123"}).json()["csrf_token"]
        resp = client.post("/api/actions/emergency-close-all", headers={"X-CSRF-Token": csrf})
        assert resp.json()["ok"] is True
        assert not orch.position_manager.has_position(TOKEN)
        assert state.circuit_breaker.state.value == "EMERGENCY"


class _ApiStubExecutor:
    def __init__(self, sim):
        self.sim = sim

    async def execute_buy(self, token_address, symbol, amount_usd, **kwargs):
        return self.sim.buy(token_address, symbol, amount_usd, **kwargs)

    async def execute_sell(self, token_address, percentage=100.0):
        return self.sim.sell(token_address, percentage)


def _token_risk():
    from app.risk.models import TokenRiskData

    return TokenRiskData(
        token_address=TOKEN, symbol="TKN", liquidity=50_000, volume_5m=10_000,
        buys_5m=60, sells_5m=20, price=1.0,
    )


def _portfolio_risk():
    from app.risk.models import PortfolioRiskData

    return PortfolioRiskData(
        wallet_balance_usd=100.0, total_exposure_usd=0.0, open_positions=0,
        daily_pnl=0.0, consecutive_losses=0, daily_loss_usd=0.0,
    )
