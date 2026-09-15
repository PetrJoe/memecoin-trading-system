# Meme Trader - Build Task List

Comprehensive task breakdown for the Autonomous Solana Memecoin Trading Bot.

---

## Phase 1: Project Scaffolding & Foundation

### 1.1 Repository Setup
- [ ] Initialize Git repository
- [ ] Create `pyproject.toml` with project metadata
- [ ] Create `requirements.txt` with all dependencies
- [ ] Create `.gitignore` (exclude `.env`, `__pycache__`, `*.pyc`, `.venv`, `*.db`, `backups/`)
- [ ] Create `.env.example` with all required env vars and defaults
- [ ] Create directory structure per PRD §4

### 1.2 Configuration System
- [ ] Create `app/config/__init__.py`
- [ ] Implement `app/config/settings.py` using pydantic-settings
  - [ ] `APP_ENV` (development/staging/production)
  - [ ] `TRADING_MODE` (paper/live_safe/live) — default `paper`
  - [ ] `TRADING_ENABLED` — default `false`
  - [ ] Solana RPC/WS URLs
  - [ ] Jupiter API URL
  - [ ] Database URL
  - [ ] Telegram bot token + chat ID
  - [ ] Bot private key
  - [ ] Risk limits: `MAX_POSITION_USD`, `MAX_OPEN_POSITIONS`, `MAX_DAILY_LOSS_USD`, `MAX_TOTAL_EXPOSURE_USD`, `MAX_SLIPPAGE_BPS`, `MAX_PRICE_IMPACT_BPS`, `MAX_CONSECUTIVE_LOSSES`, `MAX_POSITION_DURATION`
  - [ ] Strategy params: `STOP_LOSS_PERCENT`, `TAKE_PROFIT_PERCENT`, `TRAILING_STOP_PERCENT`
  - [ ] Scanner params: `SCANNER_INTERVAL_SECONDS`, `POSITION_CHECK_INTERVAL_SECONDS`, `MIN_LIQUIDITY_USD`, `MIN_VOLUME_5M_USD`, `MIN_RISK_SCORE`
  - [ ] Scoring weights (configurable, not hard-coded)
  - [ ] Validate private key never exposed in repr/str/logging
- [ ] Implement `app/config/logging.py` with structured logging
  - [ ] Separate log categories: `application`, `trades`, `errors`, `security`
  - [ ] JSON structured format
  - [ ] Ensure secrets are never logged

### 1.3 Database Foundation
- [ ] Create `app/database/__init__.py`
- [ ] Implement `app/database/database.py` — async SQLAlchemy engine + session factory
- [ ] Implement `app/database/models.py` with all SQLAlchemy models:
  - [ ] `Token` (id, address, symbol, name, decimals, status, risk_score, timestamps)
  - [ ] `Pair` (id, address, token_id FK, dex, liquidity, timestamps)
  - [ ] `MarketSnapshot` (id, token_id FK, price, liquidity, volumes, buys, sells, market_cap, timestamp)
  - [ ] `Signal` (id, token_id FK, signal, score, reasons JSON, timestamps)
  - [ ] `Order` (id, token_id FK, side, amount, status, tx_signature, timestamps)
  - [ ] `Trade` (id, order_id FK, token_id FK, side, quantity, price, fees, slippage, pnl, tx_signature, status, timestamps)
  - [ ] `Position` (id, token_id FK, entry_price, quantity, capital, stop_loss, take_profit, trailing_stop, status, opened_at, closed_at, exit_reason, realized_pnl)
  - [ ] `BotEvent` (id, level, event_type, message, metadata JSON, timestamps)
  - [ ] `DailyStats` (date, starting_balance, ending_balance, realized_pnl, unrealized_pnl, fees, trade_count, winning_trades, losing_trades)
- [ ] Add indexes on frequently queried fields (token_id, tx_signature, status, timestamps)
- [ ] Add unique constraints (tx_signature, token address, position identity)
- [ ] Add proper foreign keys and cascade rules
- [ ] Implement `app/database/repositories.py` — repository pattern for each model
- [ ] Set up Alembic: `alembic.ini`, `app/database/migrations/`
- [ ] Create initial migration
- [ ] Write unit tests for repository CRUD operations

---

## Phase 2: DEX Screener Integration

### 2.1 DEX Screener Client
- [ ] Create `app/scanner/__init__.py`
- [ ] Implement `app/scanner/dex_screener.py` — `DexScreenerClient`
  - [ ] HTTP client using `httpx` with async support
  - [ ] Methods: `get_pairs()`, `get_token()`, `search()`, `get_new_pairs()`
  - [ ] Normalize API responses into internal `MarketSnapshot` Pydantic model
  - [ ] Handle HTTP 429 rate limits with retry + exponential backoff
  - [ ] Handle HTTP 500/503 with bounded retries
  - [ ] Handle network timeouts (configurable timeout)
  - [ ] Handle DNS failures
  - [ ] Handle malformed/empty responses gracefully
  - [ ] Never crash the bot on API failure — log error and return empty/None
- [ ] Define `MarketSnapshot` Pydantic model (token address, pair address, symbol, name, price, liquidity, market cap, FDV, volumes, price changes, buys, sells, pair creation time, timestamp)

### 2.2 Token Discovery
- [ ] Implement `app/scanner/discovery.py` — `TokenDiscovery`
  - [ ] Continuously scan for Solana memecoins via DexScreenerClient
  - [ ] Filter: `chain == solana`
  - [ ] Configurable filters: min liquidity, min 5m volume, min transaction activity, max token age, min buy activity, max spread
  - [ ] Token lifecycle states: `DISCOVERED → WATCHING → ANALYZING → APPROVED → TRADED → REJECTED`
  - [ ] Store discovered tokens in PostgreSQL via Token repository
  - [ ] Deduplicate — avoid re-processing known tokens
- [ ] Implement `app/scanner/market_data.py` — fetch and store market snapshots
- [ ] Implement `app/scanner/filters.py` — configurable token filters
- [ ] Write unit tests for filters and discovery logic
- [ ] Write integration tests with mocked DexScreener API

---

## Phase 3: Risk Engine

### 3.1 Core Risk Engine
- [ ] Create `app/risk/__init__.py`
- [ ] Implement `app/risk/risk_engine.py` — `RiskEngine`
  - [ ] Runs BEFORE every buy
  - [ ] Checks: liquidity, liquidity changes, token age, buy/sell ratio, volume, holder concentration, mint authority, freeze authority, suspicious characteristics, price impact, expected slippage, wallet exposure, existing position exposure, daily loss, consecutive losses
  - [ ] Returns `RiskResult` Pydantic model: `approved`, `score`, `reasons`, `warnings`
  - [ ] Critical safety failures always reject regardless of score
- [ ] Implement `app/risk/position_sizing.py` — `PositionSizer`
  - [ ] Inputs: account balance, max position, daily loss, current exposure, open positions count, risk score, available SOL, strategy confidence
  - [ ] Output: `approved_position_size`
  - [ ] Never allow strategy to bypass position sizing
  - [ ] Support tiny positions ($0.50–$1) for live-safe testing
- [ ] Implement `app/risk/exposure.py` — track total portfolio exposure
- [ ] Implement `app/risk/circuit_breaker.py` — `CircuitBreaker`
  - [ ] States: `NORMAL → WARNING → PAUSED → EMERGENCY`
  - [ ] Auto-pause on: daily loss exceeded, too many consecutive losses, too many execution failures, too many RPC failures, Jupiter unavailable, database unavailable, abnormal slippage, wallet balance too low, unexpected transaction state
  - [ ] When paused: no new positions, continue monitoring existing, continue alerts, allow emergency exits
  - [ ] Telegram notification on activation with reason
- [ ] Write unit tests for risk scoring, position sizing, circuit breaker states
- [ ] Write integration tests for risk engine pipeline

---

## Phase 4: Strategy Engine

### 4.1 Strategy Framework
- [ ] Create `app/strategy/__init__.py`
- [ ] Implement `app/strategy/base.py` — `BaseStrategy` abstract class
  - [ ] Methods: `analyze()`, `generate_signal()`
  - [ ] Signal types: `BUY`, `SELL`, `HOLD`, `WATCH`, `REJECT`
  - [ ] Every signal must contain reasons (explainable)
- [ ] Implement `app/strategy/scoring.py` — configurable scoring system
  - [ ] Weights stored in config, not hard-coded
  - [ ] Default: Liquidity 20, Volume 20, Buy pressure 15, Momentum 15, Volume acceleration 10, Token age 10, Risk score 10
  - [ ] Allow future strategies to use different scoring systems

### 4.2 Initial Strategy
- [ ] Implement `app/strategy/momentum.py` — `MomentumStrategy`
  - [ ] Consider: short-term price momentum, volume acceleration, buy/sell ratio, liquidity, transaction activity, token age, risk score
  - [ ] Deterministic and explainable (no ML in v1)
  - [ ] Return score + reasons for every signal
- [ ] Implement `app/strategy/volume_breakout.py` — `VolumeBreakoutStrategy` (optional additional strategy)
- [ ] Write unit tests for scoring, signal generation, strategy edge cases

---

## Phase 5: Blockchain & Wallet Integration

### 5.1 Solana Client
- [ ] Create `app/blockchain/__init__.py`
- [ ] Implement `app/blockchain/solana_client.py` — `SolanaClient`
  - [ ] Connect to Solana RPC (async)
  - [ ] Query SOL balance
  - [ ] Query token balances (SPL tokens)
  - [ ] Get transaction status
  - [ ] Get recent blockhash
  - [ ] Send raw transaction
  - [ ] Handle RPC errors, timeouts, rate limits
  - [ ] Bounded retries with exponential backoff

### 5.2 Wallet Service
- [ ] Implement `app/blockchain/wallet.py` — `WalletService`
  - [ ] Load signing credentials securely from env
  - [ ] Validate wallet address
  - [ ] Query SOL balance
  - [ ] Query token balances
  - [ ] Sign transactions locally
  - [ ] NEVER expose secret material (private key)
  - [ ] Provide public wallet address to other components
  - [ ] Never send private key to external APIs
- [ ] Create `scripts/create_bot_wallet.py`
  - [ ] Generate new wallet/keypair
  - [ ] Display public address
  - [ ] Warn user to backup secret key securely
  - [ ] Do NOT automatically fund the wallet
- [ ] Implement `app/blockchain/token.py` — SPL token helpers
- [ ] Implement `app/blockchain/reconciliation.py` — on-chain reconciliation
  - [ ] Compare database positions vs blockchain wallet balances
  - [ ] Detect: missing position, unexpected token balance, unconfirmed trade, unknown transaction, incorrect quantity
  - [ ] Run on: startup, VPS reboot, database recovery, transaction timeout, unknown tx status
  - [ ] Never blindly retry when state is uncertain

---

## Phase 6: Jupiter Integration

### 6.1 Jupiter Client
- [ ] Create `app/execution/__init__.py`
- [ ] Implement `app/execution/jupiter.py` — `JupiterClient`
  - [ ] Request swap quotes
  - [ ] Validate routing
  - [ ] Calculate expected output
  - [ ] Calculate price impact
  - [ ] Enforce slippage limit (`MAX_SLIPPAGE_BPS`)
  - [ ] Build swap transaction
  - [ ] Submit transaction
  - [ ] Track transaction status (poll for confirmation)
  - [ ] Verify on-chain confirmation (not just submission)
- [ ] Implement `app/execution/quote.py` — quote request/response models
- [ ] Implement `app/execution/buy.py` — buy execution flow
- [ ] Implement `app/execution/sell.py` — sell execution flow
- [ ] Implement `app/execution/transaction.py` — transaction state machine
  - [ ] States: `CREATED → QUOTE_REQUESTED → QUOTE_RECEIVED → RISK_APPROVED → TRANSACTION_BUILT → SIGNED → SUBMITTED → CONFIRMING → CONFIRMED`
  - [ ] Failure states: `FAILED`, `CANCELLED`, `EXPIRED`, `UNKNOWN`
  - [ ] On `UNKNOWN` state: reconcile blockchain first, never blindly retry
  - [ ] Duplicate execution prevention (idempotency)

---

## Phase 7: Paper Trading Engine

### 7.1 Paper Execution
- [ ] Implement paper trading execution layer
  - [ ] Simulate buy: entry, slippage, fees
  - [ ] Simulate sell: exit, slippage, fees
  - [ ] Simulate price movement
  - [ ] Use SAME scanner, strategy, risk engine, position sizing, position manager as live
  - [ ] Only execution differs (no blockchain calls)
  - [ ] Simulate TP/SL/trailing stop triggers
  - [ ] Track paper positions and P&L
- [ ] Display `⚠️ PAPER TRADING — NO REAL TRANSACTIONS` on startup
- [ ] Write tests verifying paper trades go through same pipeline as live

---

## Phase 8: Position & Portfolio Management

### 8.1 Position Manager
- [ ] Create `app/portfolio/__init__.py`
- [ ] Implement `app/portfolio/positions.py` — `PositionManager`
  - [ ] Create position on confirmed buy
  - [ ] Track: token, entry price, quantity, capital invested, entry time, stop loss, take profit, trailing stop, current price, unrealized P&L, realized P&L, status, exit reason
  - [ ] Exit reasons: `TAKE_PROFIT`, `STOP_LOSS`, `TRAILING_STOP`, `TIME_LIMIT`, `EMERGENCY`, `MANUAL`, `RISK_EVENT`
  - [ ] Implement stop loss (`STOP_LOSS_PERCENT`)
  - [ ] Implement take profit (`TAKE_PROFIT_PERCENT`)
  - [ ] Design trailing stop component (configurable, enable later)
  - [ ] Enforce max position duration

### 8.2 Portfolio Manager
- [ ] Implement `app/portfolio/balances.py` — balance tracking
- [ ] Implement `app/portfolio/pnl.py` — P&L calculation
  - [ ] Realized P&L per trade
  - [ ] Unrealized P&L for open positions
  - [ ] Daily P&L
  - [ ] Win rate, wins, losses, fees
  - [ ] Best/worst trade tracking
- [ ] Reconcile portfolio state against blockchain data periodically
- [ ] Write unit tests for P&L calculations, stop loss, take profit, trailing stop

---

## Phase 9: Trade Execution State Machine

### 9.1 Buy Flow
- [ ] Implement exact buy flow per PRD §18:
  - [ ] Candidate detected → Market snapshot → Risk analysis → Strategy signal → Position sizing → Circuit breaker check → Jupiter quote → Slippage/price-impact validation → Build transaction → Sign locally → Broadcast → Confirm on-chain → Create position → Store trade → Telegram notification
- [ ] Each step handles failure gracefully (does not crash bot)
- [ ] On failure: log, alert via Telegram, mark trade as failed

### 9.2 Sell Flow
- [ ] Implement sell flow per PRD §19:
  - [ ] Open position → Current price → Evaluate exit conditions → Check TP/SL/trailing stop/time limit/risk event → Jupiter quote → Validate → Execute → Confirm → Close position → Calculate actual P&L → Store trade → Telegram notification

### 9.3 Concurrency & Duplicate Protection
- [ ] Prevent two BUY orders for the same token simultaneously
- [ ] Prevent BUY while SELL is being processed for same token
- [ ] Implement locks or database-level safeguards
- [ ] Use idempotency: token + strategy + signal window must not generate duplicate execution

---

## Phase 10: Telegram Bot

### 10.1 Telegram Notifications
- [ ] Create `app/monitoring/__init__.py`
- [ ] Implement `app/monitoring/telegram.py` — `TelegramBot`
  - [ ] Send startup notification (status, mode, wallet, balance, service health)
  - [ ] Send opportunity alert (token, price, liquidity, volume, risk score, action)
  - [ ] Send buy executed alert (token, amount, entry, TP, SL, tx status)
  - [ ] Send sell/position closed alert (entry, exit, P&L, reason)
  - [ ] Send daily report (trades, wins, losses, win rate, P&L, fees, open positions, circuit breaker status)
  - [ ] Send circuit breaker alerts
  - [ ] Send error/warning alerts
  - [ ] Queue alerts if Telegram is offline, retry later
- [ ] Implement `app/monitoring/alerts.py` — alert formatting

### 10.2 Telegram Commands
- [ ] Implement authenticated commands:
  - [ ] `/start`, `/help`
  - [ ] `/status` — bot status, mode, balance, open positions
  - [ ] `/balance` — wallet balance
  - [ ] `/positions` — open positions with P&L
  - [ ] `/pnl` — profit/loss summary
  - [ ] `/today` — today's stats
  - [ ] `/stats` — full statistics
  - [ ] `/pause` — pause new trades
  - [ ] `/resume` — resume trading
  - [ ] `/close <token>` — close specific position (with confirmation)
  - [ ] `/emergency` — emergency mode (with confirmation)
- [ ] Only configured Telegram chat/user ID can issue admin commands
- [ ] Log all commands
- [ ] Dangerous operations require confirmation
- [ ] NEVER expose: private key, seed phrase, API secrets, database credentials
- [ ] Write tests for command parsing and authentication

---

## Phase 11: Worker Architecture

### 11.1 Async Workers
- [ ] Create `app/workers/__init__.py`
- [ ] Implement `app/workers/scanner_worker.py`
  - [ ] Runs every `SCANNER_INTERVAL_SECONDS`
  - [ ] Discovers tokens, fetches market data, stores snapshots
  - [ ] Does not block event loop
- [ ] Implement `app/workers/strategy_worker.py`
  - [ ] Reads candidates from DB
  - [ ] Calculates signals using strategy engine
  - [ ] Stores signals
- [ ] Implement `app/workers/position_worker.py`
  - [ ] Runs every `POSITION_CHECK_INTERVAL_SECONDS`
  - [ ] Updates prices for open positions
  - [ ] Calculates unrealized P&L
  - [ ] Evaluates exit conditions (TP/SL/trailing stop)
- [ ] Implement `app/workers/reconciliation_worker.py`
  - [ ] Runs periodically
  - [ ] Verifies wallet balance
  - [ ] Verifies positions against blockchain
  - [ ] Verifies pending transactions
- [ ] Implement `app/workers/health_worker.py`
  - [ ] Checks all dependencies (DB, RPC, Jupiter, Telegram)
  - [ ] Checks resource state (CPU, RAM, disk)
  - [ ] Sends alerts on degradation
- [ ] All workers use timeouts for external calls
- [ ] All workers handle exceptions without crashing

---

## Phase 12: FastAPI Health API & Dashboard

### 12.1 Health API
- [ ] Create `app/api/__init__.py`
- [ ] Implement `app/api/app.py` — FastAPI application
- [ ] Implement `app/api/routes.py`
  - [ ] `GET /health` — verify app, database, Solana RPC, Jupiter, Telegram; return appropriate HTTP status
  - [ ] `GET /status` — bot status, wallet balance, daily P&L, total P&L, open positions, recent trades, strategy signals, risk status, system health
  - [ ] `GET /metrics` — operational metrics
- [ ] Implement `app/api/schemas.py` — response Pydantic models
- [ ] Do not expose secrets in any endpoint
- [ ] Rate-limit administrative endpoints
- [ ] Write tests for all endpoints

---

## Phase 13: Application Entry Point & Orchestration

### 13.1 Main Application
- [ ] Implement `app/main.py`
  - [ ] Load configuration
  - [ ] Initialize database connection
  - [ ] Run Alembic migrations
  - [ ] Initialize all services (DEX Screener, Solana, Jupiter, Risk, Strategy, Portfolio, Telegram)
  - [ ] Start all workers
  - [ ] Start FastAPI server
  - [ ] Handle graceful shutdown on SIGTERM/SIGINT:
    1. Stop accepting new trades
    2. Finish safe in-flight operations
    3. Persist state
    4. Close database connections
    5. Stop workers
    6. Exit cleanly
  - [ ] On startup: reconcile on-chain positions before resuming
  - [ ] Display mode clearly (PAPER vs LIVE)

---

## Phase 14: Logging, Monitoring & Metrics

### 14.1 Structured Logging
- [ ] Structured JSON logs with fields: level, event_type, token, tx_signature, score, reasons, etc.
- [ ] Separate log files/categories: application, trades, errors, security
- [ ] Never log secrets (sanitize any accidental secret in logs)
- [ ] Log rotation (via logrotate on VPS)

### 14.2 Monitoring
- [ ] Implement `app/monitoring/health.py` — health check logic
- [ ] Implement `app/monitoring/metrics.py` — operational metrics
- [ ] Track: CPU, RAM, disk, network, bot uptime, DB availability, RPC availability, Jupiter availability, scanner activity, trade execution failures
- [ ] Send Telegram warning on: disk > 80%, memory > 85%, worker stopped, DB unavailable, RPC unavailable, too many failed trades, circuit breaker activated

---

## Phase 15: Backtesting

### 15.1 Backtest Framework
- [ ] Create interface for replaying historical market snapshots through strategy
- [ ] Output metrics: total trades, winning/losing trades, win rate, gross profit, gross loss, net profit, maximum drawdown, profit factor, average win, average loss, average holding time
- [ ] Do not claim profitability from small samples

---

## Phase 16: Testing

### 16.1 Unit Tests (`tests/unit/`)
- [ ] Scoring system tests
- [ ] Position sizing tests
- [ ] Stop loss tests
- [ ] Take profit tests
- [ ] Trailing stop tests
- [ ] Circuit breaker state tests
- [ ] P&L calculation tests
- [ ] Risk engine tests
- [ ] Filter tests
- [ ] Token lifecycle tests
- [ ] Configuration validation tests

### 16.2 Integration Tests (`tests/integration/`)
- [ ] PostgreSQL repository tests (with test DB)
- [ ] DEX Screener client tests (mocked API)
- [ ] Jupiter client tests (mocked API)
- [ ] Solana client tests (mocked RPC)
- [ ] Telegram bot tests (mocked API)
- [ ] End-to-end buy flow test (paper mode)
- [ ] End-to-end sell flow test (paper mode)
- [ ] Full pipeline test (discover → analyze → signal → execute → monitor → exit)

### 16.3 Failure/Recovery Tests
- [ ] RPC outage recovery
- [ ] Jupiter outage recovery
- [ ] DEX Screener outage recovery
- [ ] Database outage recovery (fail closed for new trades)
- [ ] Telegram outage recovery (trading continues, alerts queued)
- [ ] Transaction timeout handling
- [ ] Duplicate signal prevention
- [ ] Duplicate transaction prevention
- [ ] VPS restart recovery simulation

---

## Phase 17: VPS Deployment

### 17.1 VPS Setup
- [ ] Create deployment script for Ubuntu 24.04+
- [ ] Install: Python 3.12+, PostgreSQL, Git, UFW, systemd
- [ ] Create dedicated Linux user: `memetrader`
- [ ] Deploy to `/opt/meme-trader`
- [ ] Set permissions (prevent other users from reading secrets)
- [ ] Configure UFW firewall
- [ ] SSH key authentication (disable password login where practical)
- [ ] PostgreSQL not publicly exposed
- [ ] FastAPI not publicly exposed unless required

### 17.2 systemd Service
- [ ] Create `deploy/meme-trader.service`
  - [ ] `User=memetrader`
  - [ ] `WorkingDirectory=/opt/meme-trader`
  - [ ] `Restart=always`
  - [ ] `RestartSec=5`
  - [ ] Start on boot
  - [ ] Restart after failure
  - [ ] Graceful stop
  - [ ] Load env vars securely (via `EnvironmentFile`)
  - [ ] Logs to journald

### 17.3 Nginx (if needed)
- [ ] Create `deploy/nginx.conf` — reverse proxy for FastAPI if public HTTPS access needed

### 17.4 Log Rotation
- [ ] Create `deploy/logrotate.conf`

### 17.5 Database Backup
- [ ] Create `scripts/backup_database.sh`
  - [ ] Daily PostgreSQL backups via cron
  - [ ] Retention: 7 daily, 4 weekly
  - [ ] Never include private keys in backups

---

## Phase 18: Scripts & Utilities

- [ ] `scripts/migrate.py` — run Alembic migrations programmatically
- [ ] `scripts/healthcheck.py` — standalone health check script
- [ ] `scripts/create_bot_wallet.py` — generate new wallet (see Phase 5)
- [ ] `scripts/backup_database.sh` — see Phase 17.5

---

## Phase 19: Documentation

### 19.1 README
- [ ] Project overview
- [ ] Architecture diagram
- [ ] Prerequisites
- [ ] Installation guide (local development)
- [ ] Configuration guide (`.env` variables)
- [ ] Running the bot (paper mode first)
- [ ] Running the bot (live-safe mode)
- [ ] Telegram commands reference
- [ ] API endpoints reference
- [ ] VPS deployment guide
- [ ] Troubleshooting section

### 19.2 Security Documentation
- [ ] Security-first defaults documented
- [ ] Private key handling rules
- [ ] Wallet architecture explained
- [ ] What is NEVER exposed (keys, secrets, credentials)
- [ ] Network security (UFW, SSH, PostgreSQL access)
- [ ] Telegram authentication

### 19.3 Trading Configuration Documentation
- [ ] All configurable parameters explained
- [ ] Risk limits explained with examples
- [ ] Scoring weights explained
- [ ] Strategy parameters explained
- [ ] Trading modes explained (paper/live_safe/live)
- [ ] Circuit breaker triggers explained

---

## Phase 20: Final Verification

### 20.1 Acceptance Criteria
- [ ] `python -m app.main` starts successfully
- [ ] Paper mode: discover → analyze → signal → simulate buy → monitor → simulate TP/SL → simulate sell → calculate P&L → send Telegram report
- [ ] Live-safe mode: discover → risk check → strategy → position sizing → Jupiter quote → sign → submit → confirm → record → monitor → exit
- [ ] VPS reboot: bot auto-starts → connects DB → checks dependencies → reconciles wallet → reconciles positions → resumes
- [ ] Failure: Jupiter offline → bot doesn't crash
- [ ] Failure: DEX Screener offline → stops discovering, manages existing positions
- [ ] Failure: Telegram offline → trading continues, alerts queued
- [ ] Failure: Database offline → fails closed for new trades
- [ ] All tests passing
- [ ] No secrets in logs
- [ ] No private keys in Telegram messages
- [ ] Default mode is paper trading
- [ ] Live trading requires explicit opt-in

---

## Dependencies (requirements.txt)

```
Python>=3.12
fastapi
uvicorn[standard]
pydantic
pydantic-settings
sqlalchemy[asyncio]
asyncpg
alembic
httpx
python-telegram-bot
solders
solana
base58
python-dotenv
structlog
pytest
pytest-asyncio
pytest-cov
```
