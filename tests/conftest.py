import os
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    from app.config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def env_defaults():
    return {
        "APP_ENV": "development",
        "TRADING_MODE": "paper",
        "TRADING_ENABLED": "false",
        "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com",
        "SOLANA_WS_URL": "wss://api.mainnet-beta.solana.com",
        "JUPITER_API_URL": "https://quote-api.jup.ag/v6",
        "DATABASE_URL": "postgresql+asyncpg://memetrader:password@localhost:5432/meme_trader",
        "BOT_PRIVATE_KEY": "",
    }


@pytest.fixture
def patched_env(env_defaults):
    with patch.dict(os.environ, env_defaults, clear=False):
        yield
