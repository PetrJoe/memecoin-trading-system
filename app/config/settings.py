from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE_SAFE = "live_safe"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    APP_ENV: AppEnv = AppEnv.DEVELOPMENT

    # Trading
    TRADING_MODE: TradingMode = TradingMode.PAPER
    TRADING_ENABLED: bool = False

    # Solana
    SOLANA_RPC_URL: str = "https://api.mainnet-beta.solana.com"
    SOLANA_WS_URL: str = "wss://api.mainnet-beta.solana.com"

    # Jupiter
    JUPITER_API_URL: str = "https://quote-api.jup.ag/v6"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://memetrader:password@localhost:5432/meme_trader"

    # Telegram
    TELEGRAM_BOT_TOKEN: SecretStr = SecretStr("")
    TELEGRAM_CHAT_ID: str = ""

    # Web UI (authenticated AJAX dashboard)
    WEB_UI_ENABLED: bool = True
    WEB_UI_USERNAME: str = "admin"
    WEB_UI_PASSWORD: SecretStr = SecretStr("")  # empty => login disabled (secure default)
    WEB_UI_SECRET_KEY: SecretStr = SecretStr("")
    WEB_UI_SESSION_TTL_MINUTES: int = 60
    WEB_UI_LOGIN_MAX_FAILURES: int = 5
    WEB_UI_RATE_LIMIT_WINDOW_SECONDS: int = 300
    WEB_UI_COOKIE_SECURE: bool = False  # set true behind HTTPS in production

    # Bot Wallet
    BOT_PRIVATE_KEY: SecretStr = SecretStr("")

    # Risk Limits
    MAX_POSITION_USD: float = 0.50
    MAX_OPEN_POSITIONS: int = 2
    MAX_DAILY_LOSS_USD: float = 1.00
    MAX_TOTAL_EXPOSURE_USD: float = 5.00
    MAX_SLIPPAGE_BPS: int = 100
    MAX_PRICE_IMPACT_BPS: int = 500
    MAX_CONSECUTIVE_LOSSES: int = 5
    MAX_POSITION_DURATION_HOURS: int = 24

    # Strategy Parameters
    STOP_LOSS_PERCENT: float = 10.0
    TAKE_PROFIT_PERCENT: float = 25.0
    TRAILING_STOP_PERCENT: float = 15.0

    # Paper Trading
    PAPER_STARTING_BALANCE_USD: float = 100.0
    PAPER_FEE_PERCENT: float = 0.25

    # Scanner
    SCANNER_INTERVAL_SECONDS: int = 20
    POSITION_CHECK_INTERVAL_SECONDS: int = 5
    MIN_LIQUIDITY_USD: float = 10000.0
    MIN_VOLUME_5M_USD: float = 5000.0
    MIN_RISK_SCORE: int = 70
    MAX_CANDIDATES_PER_SCAN: int = 3

    # Backtesting
    BACKTEST_FEE_PERCENT: float = 0.25
    BACKTEST_SLIPPAGE_PCT: float = 0.10

    # Monitoring thresholds
    DISK_USAGE_WARN_PCT: int = 80
    MEM_USAGE_WARN_PCT: int = 85

    # Scoring Weights
    SCORE_WEIGHT_LIQUIDITY: int = 20
    SCORE_WEIGHT_VOLUME: int = 20
    SCORE_WEIGHT_BUY_PRESSURE: int = 15
    SCORE_WEIGHT_MOMENTUM: int = 15
    SCORE_WEIGHT_VOLUME_ACCELERATION: int = 10
    SCORE_WEIGHT_TOKEN_AGE: int = 10
    SCORE_WEIGHT_RISK_SCORE: int = 10

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use asyncpg driver: postgresql+asyncpg://...")
        return v

    @field_validator("TRADING_ENABLED")
    @classmethod
    def validate_trading_enabled(cls, v: bool, info) -> bool:
        mode = info.data.get("TRADING_MODE", TradingMode.PAPER)
        if v and mode == TradingMode.PAPER:
            raise ValueError("Cannot enable trading in paper mode")
        return v

    @property
    def is_paper(self) -> bool:
        return self.TRADING_MODE == TradingMode.PAPER

    @property
    def is_live_safe(self) -> bool:
        return self.TRADING_MODE == TradingMode.LIVE_SAFE

    @property
    def is_live(self) -> bool:
        return self.TRADING_MODE == TradingMode.LIVE

    @property
    def scoring_weights(self) -> dict[str, int]:
        return {
            "liquidity": self.SCORE_WEIGHT_LIQUIDITY,
            "volume": self.SCORE_WEIGHT_VOLUME,
            "buy_pressure": self.SCORE_WEIGHT_BUY_PRESSURE,
            "momentum": self.SCORE_WEIGHT_MOMENTUM,
            "volume_acceleration": self.SCORE_WEIGHT_VOLUME_ACCELERATION,
            "token_age": self.SCORE_WEIGHT_TOKEN_AGE,
            "risk_score": self.SCORE_WEIGHT_RISK_SCORE,
        }

    @property
    def total_scoring_weight(self) -> int:
        return sum(self.scoring_weights.values())


@lru_cache
def get_settings() -> Settings:
    return Settings()
