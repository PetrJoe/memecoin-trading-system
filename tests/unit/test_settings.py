import os
from unittest.mock import patch

import pytest

from app.config.settings import AppEnv, Settings, TradingMode, get_settings


class TestSettingsDefaults:
    def test_default_trading_mode_is_paper(self, patched_env):
        settings = Settings()
        assert settings.TRADING_MODE == TradingMode.PAPER

    def test_default_trading_enabled_is_false(self, patched_env):
        settings = Settings()
        assert settings.TRADING_ENABLED is False

    def test_default_max_position_usd(self, patched_env):
        settings = Settings()
        assert settings.MAX_POSITION_USD == 0.50

    def test_default_max_open_positions(self, patched_env):
        settings = Settings()
        assert settings.MAX_OPEN_POSITIONS == 2

    def test_default_max_daily_loss(self, patched_env):
        settings = Settings()
        assert settings.MAX_DAILY_LOSS_USD == 1.00

    def test_default_scanner_interval(self, patched_env):
        settings = Settings()
        assert settings.SCANNER_INTERVAL_SECONDS == 20

    def test_default_min_liquidity(self, patched_env):
        settings = Settings()
        assert settings.MIN_LIQUIDITY_USD == 10000.0

    def test_default_scoring_weights_sum_to_100(self, patched_env):
        settings = Settings()
        assert settings.total_scoring_weight == 100


class TestSettingsProperties:
    def test_is_paper_true(self, patched_env):
        settings = Settings()
        assert settings.is_paper is True

    def test_is_live_safe_false_by_default(self, patched_env):
        settings = Settings()
        assert settings.is_live_safe is False

    def test_is_live_false_by_default(self, patched_env):
        settings = Settings()
        assert settings.is_live is False

    def test_scoring_weights_dict(self, patched_env):
        settings = Settings()
        weights = settings.scoring_weights
        assert isinstance(weights, dict)
        assert "liquidity" in weights
        assert "volume" in weights
        assert weights["liquidity"] == 20


class TestSettingsValidation:
    def test_database_url_must_use_asyncpg(self, patched_env):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://localhost/db"}):
            with pytest.raises(ValueError, match="asyncpg"):
                Settings()

    def test_trading_enabled_rejected_in_paper_mode(self, patched_env):
        with patch.dict(os.environ, {"TRADING_MODE": "paper", "TRADING_ENABLED": "true"}):
            with pytest.raises(ValueError, match="Cannot enable trading"):
                Settings()

    def test_trading_enabled_allowed_in_live_safe_mode(self, patched_env):
        with patch.dict(os.environ, {"TRADING_MODE": "live_safe", "TRADING_ENABLED": "true"}):
            settings = Settings()
            assert settings.TRADING_ENABLED is True

    def test_private_key_is_secret_str(self, patched_env):
        settings = Settings()
        assert hasattr(settings.BOT_PRIVATE_KEY, "get_secret_value")

    def test_repr_does_not_expose_secrets(self, patched_env):
        settings = Settings()
        repr_str = repr(settings)
        # SecretStr shows as SecretStr('***') in repr, not the actual value
        assert "SecretStr('***')" in repr_str or "BOT_PRIVATE_KEY=SecretStr" in repr_str
        # The actual secret value (if set) should not appear
        secret = settings.BOT_PRIVATE_KEY.get_secret_value()
        if secret:
            assert secret not in repr_str


class TestGetSettingsCache:
    def test_same_instance(self, patched_env):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
