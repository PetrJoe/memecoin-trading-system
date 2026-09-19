import time

import pytest

from app.api.security import (
    CredentialChecker,
    LoginRateLimiter,
    SessionStore,
)


@pytest.fixture
def store():
    return SessionStore(ttl_minutes=60)


@pytest.fixture
def limiter():
    return LoginRateLimiter(max_failures=3, window_seconds=60)


class TestSessionStore:
    def test_create_returns_token_and_csrf(self, store):
        token, csrf = store.create("admin")
        assert token and csrf
        assert token != csrf

    def test_validate_roundtrip(self, store):
        token, _ = store.create("admin")
        session = store.validate(token)
        assert session is not None
        assert session["username"] == "admin"

    def test_validate_invalid_token(self, store):
        assert store.validate("garbage") is None

    def test_validate_expired(self, store):
        store.ttl_seconds = 0.01
        token, _ = store.create("admin")
        time.sleep(0.02)
        assert store.validate(token) is None

    def test_sliding_expiry_extends(self, store):
        store.ttl_seconds = 0.05
        token, _ = store.create("admin")
        for _ in range(3):
            time.sleep(0.02)
            assert store.validate(token) is not None

    def test_csrf_valid(self, store):
        token, csrf = store.create("admin")
        assert store.validate_csrf(token, csrf) is True

    def test_csrf_wrong_token(self, store):
        token, csrf = store.create("admin")
        assert store.validate_csrf(token, "wrong") is False

    def test_csrf_invalid_session(self, store):
        assert store.validate_csrf("bad", "bad") is False

    def test_destroy(self, store):
        token, _ = store.create("admin")
        store.destroy(token)
        assert store.validate(token) is None

    def test_destroy_all(self, store):
        store.create("a")
        store.create("b")
        store.destroy_all()
        assert store.active_count == 0

    def test_purge_expired(self, store):
        store.ttl_seconds = 0.01
        store.create("admin")
        time.sleep(0.02)
        assert store.purge_expired() == 1

    def test_token_not_stored_plaintext(self, store):
        token, _ = store.create("admin")
        # The raw token must not appear anywhere in the store's keys
        assert all(token not in k for k in store._sessions.keys())


class TestCredentialChecker:
    def _checker_with(self, username, password):
        checker = CredentialChecker()
        checker.settings = type("S", (), {
            "WEB_UI_USERNAME": username,
            "WEB_UI_PASSWORD": type("SecretStr", (), {"get_secret_value": lambda self: password})(),
        })()
        return checker

    def test_valid_credentials(self):
        checker = self._checker_with("admin", "hunter2")
        assert checker.verify("admin", "hunter2") is True

    def test_wrong_password(self):
        checker = self._checker_with("admin", "hunter2")
        assert checker.verify("admin", "wrong") is False

    def test_wrong_username(self):
        checker = self._checker_with("admin", "hunter2")
        assert checker.verify("user", "hunter2") is False

    def test_empty_password_disables_login(self):
        checker = self._checker_with("admin", "")
        assert checker.login_enabled is False
        assert checker.verify("admin", "") is False

    def test_timing_safe_against_injection(self):
        checker = self._checker_with("admin", "hunter2")
        # hmac.compare_digest handles non-ascii safely; just verify no crash
        assert checker.verify("admin", "пαѕѕωord") is False


class TestLoginRateLimiter:
    def test_not_blocked_initially(self, limiter):
        assert limiter.is_blocked("1.2.3.4") is False

    def test_blocks_after_max_failures(self, limiter):
        for _ in range(3):
            limiter.record_failure("1.2.3.4")
        assert limiter.is_blocked("1.2.3.4") is True

    def test_keys_are_independent(self, limiter):
        for _ in range(3):
            limiter.record_failure("1.2.3.4")
        assert limiter.is_blocked("5.6.7.8") is False

    def test_success_clears_failures(self, limiter):
        limiter.record_failure("1.2.3.4")
        limiter.record_failure("1.2.3.4")
        limiter.record_success("1.2.3.4")
        assert limiter.is_blocked("1.2.3.4") is False

    def test_window_expiry(self, limiter):
        from collections import deque

        limiter.record_failure("1.2.3.4")
        limiter.record_failure("1.2.3.4")
        limiter.record_failure("1.2.3.4")
        # Age all failures out of the window
        limiter._failures["1.2.3.4"] = deque(t - 61 for t in limiter._failures["1.2.3.4"])
        assert limiter.is_blocked("1.2.3.4") is False

    def test_seconds_until_retry(self, limiter):
        for _ in range(3):
            limiter.record_failure("1.2.3.4")
        retry = limiter.seconds_until_retry("1.2.3.4")
        assert 0 <= retry <= 60
