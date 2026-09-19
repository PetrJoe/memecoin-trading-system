from __future__ import annotations

import hmac
import secrets
import time
from collections import defaultdict, deque

from app.config import get_logger, get_settings

logger = get_logger(category="security")

SESSION_COOKIE_NAME = "mt_session"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_TIMEOUT_SECONDS = 3600


class SecurityError(Exception):
    pass


class LoginRateLimiter:
    """Sliding-window failure tracker keyed by client IP."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 300) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        dq = self._failures[key]
        cutoff = now - self.window_seconds
        while dq and dq[0] < cutoff:
            dq.popleft()
        return dq

    def is_blocked(self, key: str) -> bool:
        dq = self._prune(key, time.time())
        return len(dq) >= self.max_failures

    def record_failure(self, key: str) -> None:
        self._failures[key].append(time.time())

    def record_success(self, key: str) -> None:
        self._failures.pop(key, None)

    def seconds_until_retry(self, key: str) -> int:
        dq = self._prune(key, time.time())
        if not dq:
            return 0
        return max(0, int(self.window_seconds - (time.time() - dq[0])))


class SessionStore:
    """
    In-memory session store. Tokens are random; only their SHA-256 hashes
    are retained, so a memory dump does not reveal usable session tokens.
    """

    def __init__(self, ttl_minutes: int = 60) -> None:
        self.ttl_seconds = ttl_minutes * 60
        self._sessions: dict[str, dict] = {}  # token_hash -> {username, created_at, expires_at, csrf_token}

    def create(self, username: str) -> tuple[str, str]:
        """Return (raw_token, csrf_token)."""
        raw_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        token_hash = self._hash(raw_token)
        now = time.time()
        self._sessions[token_hash] = {
            "username": username,
            "created_at": now,
            "expires_at": now + self.ttl_seconds,
            "csrf_token": csrf_token,
            "last_seen": now,
        }
        return raw_token, csrf_token

    def validate(self, raw_token: str) -> dict | None:
        """Return session data if valid and unexpired, sliding-expiry renewal."""
        token_hash = self._hash(raw_token)
        session = self._sessions.get(token_hash)
        if session is None:
            return None
        now = time.time()
        if now >= session["expires_at"]:
            del self._sessions[token_hash]
            return None
        # Sliding expiration: activity extends the session
        session["expires_at"] = now + self.ttl_seconds
        session["last_seen"] = now
        return session

    def validate_csrf(self, raw_token: str, csrf_token: str) -> bool:
        session = self.validate(raw_token)
        if session is None:
            return False
        return hmac.compare_digest(session["csrf_token"], csrf_token)

    def destroy(self, raw_token: str) -> None:
        self._sessions.pop(self._hash(raw_token), None)

    def destroy_all(self) -> None:
        self._sessions.clear()

    def purge_expired(self) -> int:
        now = time.time()
        expired = [h for h, s in self._sessions.items() if now >= s["expires_at"]]
        for h in expired:
            del self._sessions[h]
        return len(expired)

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    @staticmethod
    def _hash(token: str) -> str:
        return hmac.new(b"mt-session-store", token.encode(), "sha256").hexdigest()


class CredentialChecker:
    """Constant-time credential verification. Empty password disables login."""

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def login_enabled(self) -> bool:
        return bool(self.settings.WEB_UI_PASSWORD.get_secret_value())

    def verify(self, username: str, password: str) -> bool:
        expected_password = self.settings.WEB_UI_PASSWORD.get_secret_value()
        expected_username = self.settings.WEB_UI_USERNAME
        if not expected_password:
            # No password configured: fail closed, never authenticate
            return False
        username_ok = hmac.compare_digest(username.encode(), expected_username.encode())
        password_ok = hmac.compare_digest(password.encode(), expected_password.encode())
        return username_ok and password_ok


def hash_csrf_token(token: str) -> str:
    return SessionStore._hash(token)


def get_security() -> tuple[CredentialChecker, SessionStore, LoginRateLimiter]:
    """Build security components from current settings."""
    settings = get_settings()
    checker = CredentialChecker()
    sessions = SessionStore(ttl_minutes=settings.WEB_UI_SESSION_TTL_MINUTES)
    limiter = LoginRateLimiter(
        max_failures=settings.WEB_UI_LOGIN_MAX_FAILURES,
        window_seconds=settings.WEB_UI_RATE_LIMIT_WINDOW_SECONDS,
    )
    return checker, sessions, limiter
