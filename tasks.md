# Meme Trader - Build Task List

Comprehensive task breakdown for the Autonomous Solana Memecoin Trading Bot.

---

## Phase 1: Project Scaffolding & Foundation

### 1.1 Repository Setup

- [X] Initialize Git repository
- [X] Create `pyproject.toml` with project metadata
- [X] Create `requirements.txt` with all dependencies
- [X] Create `.gitignore` (exclude `.env`, `__pycache__`, `*.pyc`, `.venv`, `*.db`, `backups/`)
- [X] Create `.env.example` with all required env vars and defaults
- [X] Create directory structure per PRD §4

### 1.2 Configuration System

- [X] Create `app/config/__init__.py`
- [X] Implement `app/config/settings.py` using pydantic-settings
  - [X] `APP_ENV` (development/staging/production)
  - [X] `TRADING_MODE` (paper/live_safe/live) — default `paper`
  - [X] `TRADING_ENABLED` — default `false`
  - [X] Solana RPC/WS URLs
  - [X] Jupiter API URL
  - [X] Database URL
  - [X] Telegram bot token + chat ID
  - [X] Bot private key (SecretStr)
  - [X] Risk limits: `MAX_POSITION_USD`, `MAX_OPEN_POSITIONS`, `MAX_DAILY_LOSS_USD`, `MAX_TOTAL_EXPOSURE_USD`, `MAX_SLIPPAGE_BPS`, `MAX_PRICE_IMPACT_BPS`, `MAX_CONSECUTIVE_LOSSES`, `MAX_POSITION_DURATION`
  - [X] Strategy params: `STOP_LOSS_PERCENT`, `TAKE_PROFIT_PERCENT`, `TRAILING_STOP_PERCENT`
  - [X] Scanner params: `SCANNER_INTERVAL_SECONDS`, `POSITION_CHECK_INTERVAL_SECONDS`, `MIN_LIQUIDITY_USD`, `MIN_VOLUME_5M_USD`, `MIN_RISK_SCORE`
  - [X] Scoring weights (configurable, not hard-coded)
  - [X] Validate private key never exposed in repr/str/logging
- [X] Implement `app/config/logging.py` with structured logging
  - [X] Separate log categories: `application`, `trades`, `errors`, `security`
  - [X] JSON structured format
  - [X] Ensure secrets are never logged

### 1.3 Database Foundation

- [X] Create `app/database/__init__.py`
- [X] Implement `app/database/database.py` — async SQLAlchemy engine + session factory
- [X] Implement `app/database/models.py` with all SQLAlchemy models:
  - [X] `Token` (id, address, symbol, name, decimals, status, risk_score, timestamps)
  - [X] `Pair` (id, address, token_id FK, dex, liquidity, timestamps)
  - [X] `MarketSnapshot` (id, token_id FK, price, liquidity, volumes, buys, sells, market_cap, timestamp)
  - [X] `Signal` (id, token_id FK, signal, score, reasons JSON, timestamps)
  - [X] `Order` (id, token_id FK, side, amount, status, tx_signature, timestamps)
  - [X] `Trade` (id, order_id FK, token_id FK, side, quantity, price, fees, slippage, pnl, tx_signature, status, timestamps)
  - [X] `Position` (id, token_id FK, entry_price, quantity, capital, stop_loss, take_profit, trailing_stop, status, opened_at, closed_at, exit_reason, realized_pnl)
  - [X] `BotEvent` (id, level, event_type, message, extra_data JSON, timestamps)
  - [X] `DailyStats` (date, starting_balance, ending_balance, realized_pnl, unrealized_pnl, fees, trade_count, winning_trades, losing_trades)
- [X] Add indexes on frequently queried fields (token_id, tx_signature, status, timestamps)
- [X] Add unique constraints (tx_signature, token address, position identity)
- [X] Add proper foreign keys and cascade rules
- [X] Implement `app/database/repositories.py` — repository pattern for each model
- [X] Set up Alembic: `alembic.ini`, `app/database/migrations/`
- [X] Create initial migration
- [X] Write unit tests for repository CRUD operations

---

## Phase 2: DEX Screener Integration

### 2.1 DEX Screener Client

- [X] Create `app/scanner/__init__.py`
- [X] Implement `app/scanner/dex_screener.py` — `DexScreenerClient`
  - [X] HTTP client using `httpx` with async support
  - [X] Methods: `get_token_pairs()`, `search_pairs()`, `get_solana_pairs()`
  - [X] Normalize API responses into internal `MarketSnapshot` Pydantic model
  - [X] Handle HTTP 429 rate limits with retry + exponential backoff
  - [X] Handle HTTP 500/503 with bounded retries
  - [X] Handle network timeouts (configurable timeout)
  - [X] Handle DNS failures
  - [X] Handle malformed/empty responses gracefully
  - [X] Never crash the bot on API failure — log error and return empty/None
- [X] Define `MarketSnapshot` Pydantic model (token address, pair address, symbol, name, price, liquidity, market cap, FDV, volumes, price changes, buys, sells, pair creation time, timestamp)

### 2.2 Token Discovery

- [X] Implement `app/scanner/discovery.py` — `TokenDiscovery`
  - [X] Continuously scan for Solana memecoins via DexScreenerClient
  - [X] Filter: `chain == solana`
  - [X] Configurable filters: min liquidity, min 5m volume, min transaction activity, max token age, min buy activity
  - [X] Token lifecycle states: `DISCOVERED → WATCHING → ANALYZING → APPROVED → TRADED → REJECTED`
  - [X] Store discovered tokens in PostgreSQL via Token repository
  - [X] Deduplicate — avoid re-processing known tokens
- [X] Implement `app/scanner/market_data.py` — fetch and store market snapshots
- [X] Implement `app/scanner/filters.py` — configurable token filters
- [X] Write unit tests for filters and discovery logic
- [X] Write integration tests with mocked DexScreener API

---

## Phase 3: Risk Engine

### 3.1 Core Risk Engine

- [X] Create `app/risk/__init__.py`
- [X] Implement `app/risk/risk_engine.py` — `RiskEngine`
  - [X] Runs BEFORE every buy
  - [X] Checks: liquidity, liquidity changes, token age, buy/sell ratio, volume, mint authority, freeze authority, wallet exposure, existing position exposure, daily loss, consecutive losses
  - [X] Returns `RiskResult` Pydantic model: `approved`, `score`, `reasons`, `warnings`
  - [X] Critical safety failures always reject regardless of score
- [X] Implement `app/risk/position_sizing.py` — `PositionSizer`
  - [X] Inputs: account balance, max position, daily loss, current exposure, open positions count, risk score, available SOL, strategy confidence
  - [X] Output: `approved_position_size`
  - [X] Never allow strategy to bypass position sizing
  - [X] Support tiny positions ($0.50–$1) for live-safe testing
- [X] Implement `app/risk/exposure.py` — track total portfolio exposure
- [X] Implement `app/risk/circuit_breaker.py` — `CircuitBreaker`
  - [X] States: `NORMAL → WARNING → PAUSED → EMERGENCY`
  - [X] Auto-pause on: daily loss exceeded, too many consecutive losses, too many execution failures, too many RPC failures, Jupiter unavailable, database unavailable, abnormal slippage, wallet balance too low, unexpected transaction state
  - [X] When paused: no new positions, continue monitoring existing, continue alerts, allow emergency exits
  - [X] Telegram notification on activation with reason
- [X] Write unit tests for risk scoring, position sizing, circuit breaker states
- [X] Write integration tests for risk engine pipeline

---

## Phase 4: Strategy Engine

### 4.1 Strategy Framework

- [X] Create `app/strategy/__init__.py`
- [X] Implement `app/strategy/base.py` — `BaseStrategy` abstract class
  - [X] Methods: `analyze()`, `generate_signal()`
  - [X] Signal types: `BUY`, `SELL`, `HOLD`, `WATCH`, `REJECT`
  - [X] Every signal must contain reasons (explainable)
- [X] Implement `app/strategy/scoring.py` — configurable scoring system
  - [X] Weights stored in config, not hard-coded
  - [X] Default: Liquidity 20, Volume 20, Buy pressure 15, Momentum 15, Volume acceleration 10, Token age 10, Risk score 10
  - [X] Allow future strategies to use different scoring systems

### 4.2 Initial Strategy

- [X] Implement `app/strategy/momentum.py` — `MomentumStrategy`
  - [X] Consider: short-term price momentum, volume acceleration, buy/sell ratio, liquidity, transaction activity, token age, risk score
  - [X] Deterministic and explainable (no ML in v1)
  - [X] Return score + reasons for every signal
- [ ] Implement `app/strategy/volume_breakout.py` — `VolumeBreakoutStrategy` (optional additional strategy)
- [X] Write unit tests for scoring, signal generation, strategy edge cases

---

## Phase 5: Blockchain & Wallet Integration

### 5.1 Solana Client

- [X] Create `app/blockchain/__init__.py`
- [X] Implement `app/blockchain/solana_client.py` — `SolanaClient`
  - [X] Connect to Solana RPC (async)
  - [X] Query SOL balance
  - [X] Query token balances (SPL tokens)
  - [X] Get transaction status
  - [X] Get recent blockhash
  - [X] Send raw transaction
  - [X] Handle RPC errors, timeouts, rate limits
  - [X] Bounded retries with exponential backoff

### 5.2 Wallet Service

- [X] Implement `app/blockchain/wallet.py` — `WalletService`
  - [X] Load signing credentials securely from env
  - [X] Validate wallet address
  - [X] Query SOL balance
  - [X] Query token balances
  - [X] Sign transactions locally
  - [X] NEVER expose secret material (private key)
  - [X] Provide public wallet address to other components
  - [X] Never send private key to external APIs
- [X] Create `scripts/create_bot_wallet.py`
  - [X] Generate new wallet/keypair
  - [X] Display public address
  - [X] Warn user to backup secret key securely
  - [X] Do NOT automatically fund the wallet
- [X] Implement `app/blockchain/token.py` — SPL token helpers
- [X] Implement `app/blockchain/reconciliation.py` — on-chain reconciliation
  - [X] Compare database positions vs blockchain wallet balances
  - [X] Detect: missing position, unexpected token balance, unconfirmed trade, unknown transaction, incorrect quantity
  - [X] Run on: startup, VPS reboot, database recovery, transaction timeout, unknown tx status
  - [X] Never blindly retry when state is uncertain

---

## Phase 6: Jupiter Integration

### 6.1 Jupiter Client

- [X] Create `app/execution/__init__.py`
- [X] Implement `app/execution/jupiter.py` — `JupiterClient`
  - [X] Request swap quotes
  - [X] Validate routing
  - [X] Calculate expected output
  - [X] Calculate price impact
  - [X] Enforce slippage limit (`MAX_SLIPPAGE_BPS`)
  - [X] Build swap transaction
  - [X] Submit transaction
  - [X] Track transaction status (poll for confirmation)
  - [X] Verify on-chain confirmation (not just submission)
- [X] Implement `app/execution/quote.py` — quote request/response models
- [X] Implement `app/execution/buy.py` — buy execution flow
- [X] Implement `app/execution/sell.py` — sell execution flow
- [X] Implement `app/execution/transaction.py` — transaction state machine
  - [X] States: `CREATED → QUOTE_REQUESTED → QUOTE_RECEIVED → RISK_APPROVED → TRANSACTION_BUILT → SIGNED → SUBMITTED → CONFIRMING → CONFIRMED`
  - [X] Failure states: `FAILED`, `CANCELLED`, `EXPIRED`, `UNKNOWN`
  - [X] On `UNKNOWN` state: reconcile blockchain first, never blindly retry
  - [X] Duplicate execution prevention (idempotency)

---

## Phase 7: Paper Trading Engine

### 7.1 Paper Execution

- [X] Implement `app/execution/paper.py` — `PaperFillSimulator`
  - [X] Simulate buy: entry price pushed by slippage, platform fee deducted, quantity computed from net proceeds
  - [X] Simulate sell: exit price pushed by slippage, platform fee deducted, proceeds returned to cash
  - [X] Slippage model: base spread + impact proportional to order size vs pool liquidity (capped, untradeable pools rejected)
  - [X] Duplicate buy prevention (one position per token)
  - [X] Partial sells (percentage-based) with correct cost-basis accounting
  - [X] Track cash, realized P&L, total fees, trade count
  - [X] Mark-to-market portfolio valuation (`portfolio_value()`, `total_pnl()`)
  - [X] High-water-mark tracking per position for trailing stops
- [X] Implement `PaperExecutor` — same call shape as live `BuyExecutor`/`SellExecutor`
  - [X] Uses SAME `TransactionManager` state machine (CREATED → … → CONFIRMED) as live trades
  - [X] Only execution differs — no blockchain calls, no Jupiter calls
  - [X] Failed fills mark transaction FAILED (not silently swallowed)
- [X] Add `PAPER_STARTING_BALANCE_USD` and `PAPER_FEE_PERCENT` to settings
- [ ] Price feed adapter: pipe live DexScreener snapshots into the simulator (`update_market`)
- [ ] Simulated latency/failure injection for testing recovery paths
- [ ] Display `⚠️ PAPER TRADING — NO REAL TRANSACTIONS` on startup and in every Telegram report
- [X] Write tests verifying paper trades traverse the same state machine as live (`tests/unit/test_paper.py`, 23 tests)
- [ ] Write end-to-end test: paper buy → TP/SL trigger → paper sell → P&L assertion

---

## Phase 8: Position & Portfolio Management

### 8.1 Position Manager

- [X] Create `app/portfolio/__init__.py`
- [X] Implement `app/portfolio/positions.py` — `PositionManager`
  - [X] Open position on confirmed buy (`open_position`) with exits derived from config
  - [X] Track: token, entry price, quantity, capital invested, entry time, stop loss, take profit, trailing stop, highest price (high-water mark), unrealized P&L
  - [X] Exit reasons: `TAKE_PROFIT`, `STOP_LOSS`, `TRAILING_STOP`, `TIME_LIMIT`, `EMERGENCY`, `MANUAL`, `RISK_EVENT`
  - [X] Implement stop loss (`STOP_LOSS_PERCENT`) — checked first (protective priority)
  - [X] Implement take profit (`TAKE_PROFIT_PERCENT`)
  - [X] Implement trailing stop (ratcheting high-water mark, configurable pct; `0` disables an exit, `None` uses settings default)
  - [X] Enforce max position duration (`MAX_POSITION_DURATION_HOURS`)
  - [X] `update_price()` returns a typed `ExitDecision` on every tick (never `None` for an open position)
  - [X] Aggregations: `total_exposure(prices)`, `total_unrealized_pnl(prizes)`
- [ ] Persist position snapshots to PostgreSQL on open/close (bridge `PositionManager` ↔ `PositionRepository`)
- [ ] Add `EMERGENCY`/`MANUAL`/`RISK_EVENT` close paths wired to Telegram commands and circuit breaker

### 8.2 Portfolio Manager

- [X] Implement `app/portfolio/balances.py` — `BalanceTracker`
  - [X] Cash tracking on buys/sells, mark-to-market position value
  - [X] Total equity, total P&L (USD and %), realized/unrealized split
  - [X] Fee accounting, `BalanceSnapshot` capture, reset support
- [X] Implement `app/portfolio/pnl.py` — `PnLCalculator`
  - [X] Realized P&L per closed trade (`ClosedTrade` records)
  - [X] Win rate, wins, losses, fees, gross profit/loss, net P&L
  - [X] Best/worst trade, average win/loss, average holding time
  - [X] Profit factor (inf when no losses)
  - [X] Consecutive-losses counter (feeds circuit breaker)
  - [X] Max drawdown % over realized equity curve
  - [X] Daily P&L (`today()`, `daily_summary()` with UTC day boundary)
- [ ] Reconcile portfolio state against blockchain data periodically (live mode; use `app/blockchain/reconciliation.py`)
- [ ] Feed `DailyStats` table from `PnLCalculator` on each close and at day rollover
- [X] Write unit tests for P&L calculations, stop loss, take profit, trailing stop (`tests/unit/test_positions.py`, `tests/unit/test_pnl.py` — 43 tests)

---

## Phase 9: Trade Execution State Machine

### 9.1 Buy Flow

- [X] Implement `app/execution/orchestrator.py` — `TradeOrchestrator` implementing the buy flow per PRD §18:
  - [X] Candidate → Risk analysis (rejects before strategy runs) → Strategy signal → Circuit breaker check → Position sizing → Executor (paper or live) → Create position → Record exposure → Notify
  - [X] Risk engine runs BEFORE strategy (cheap rejection first)
  - [X] Position sizing uses risk score + strategy confidence; zero size aborts before execution
  - [X] Each step returns a structured result (`executed|rejected|skipped|failed`) — no exceptions escape
  - [X] On execution failure: record with circuit breaker, log, leave state consistent
- [ ] Wire Telegram notification into every pipeline outcome (currently success paths only)
- [ ] Persist `Order`/`Trade` rows on pipeline completion (currently in-memory)
- [ ] Slippage/price-impact validation gate before live broadcast (live mode; quote-level `MAX_SLIPPAGE_BPS`/`MAX_PRICE_IMPACT_BPS` check)

### 9.2 Sell Flow

- [X] Implement sell flow per PRD §19 via `TradeOrchestrator.process_price_update()`:
  - [X] Open position → Current price → Evaluate exit conditions (TP/SL/trailing/time limit, priority-ordered) → Execute sell → Close position → Record actual P&L (`ClosedTrade`) → Notify
  - [X] Failed sell leaves position OPEN (retryable) — never loses the position on RPC error
  - [X] Daily-loss and consecutive-loss circuit breaker checks after each close
- [ ] Partial-exit support (sell X% on TP1, rest on TP2/trailing)
- [ ] Emergency exit path: close ALL positions when circuit breaker enters EMERGENCY

### 9.3 Concurrency & Duplicate Protection

- [X] Prevent two BUY orders for the same token simultaneously (per-token `asyncio.Lock`)
- [X] Prevent BUY while SELL is being processed for same token (shared `_in_flight` set + lock)
- [X] Signal-window idempotency (`DUPLICATE_WINDOW_SECONDS`) — same token cannot re-trigger within window
- [ ] Database-level safeguards: `SELECT ... FOR UPDATE` on position rows / unique constraint on (token_id, status=OPEN) partial index
- [ ] Cross-process lock for multi-worker deployments (Postgres advisory lock)

### 9.4 Unified Execution Interface

- [ ] Extract `ExecutionBackend` protocol so paper and live executors are strictly interchangeable
- [ ] Live buy/sell executors: replace ad-hoc `AsyncClient` creation per call with a shared session
- [ ] Live executors: mark `UNKNOWN` transaction state and trigger reconciliation instead of returning `CONFIRMING`

---

## Phase 10: Control Interface

> **Decision:** Telegram is deferred. The authenticated AJAX web dashboard (Phase 12) is the primary control interface. Telegram can be added later as a secondary notifier reusing the same seam (`TradeOrchestrator.notifier` and the `EventLog` event types).

### 10.1 Web Dashboard (primary — implemented)

- [X] Login overlay + session cookie auth (see Phase 12 for security details)
- [X] Live status: mode, uptime, circuit breaker state, balance, open positions with unrealized P&L, win rate
- [X] Events feed (replaces Telegram push alerts) with incremental polling (`?since=` timestamp)
- [X] Controls: pause, resume, close position (click-to-confirm), emergency close-all (click-to-confirm)
- [X] All rendered values HTML-escaped (textContent, no innerHTML) — no XSS from event/position data
- [ ] P&L equity chart (sparkline from `DailyStats` history)
- [ ] Daily report card generated at UTC rollover from `PnLCalculator.daily_summary()`
- [ ] Sound/desktop notification on error-level events (optional)

### 10.2 Telegram (deferred — implement when needed)

- [ ] Create `app/monitoring/telegram.py` — `TelegramBot` implementing the same `send_event(event, **kwargs)` seam as the web `EventLog`
  - [ ] Startup notification (status, mode, wallet, balance, service health)
  - [ ] Opportunity / buy executed / position closed alerts (reuse `EventLog` event types)
  - [ ] Circuit breaker + error/warning alerts
  - [ ] Queue alerts if Telegram is offline, retry later (mirror `EventLog` ring buffer)
- [ ] Implement `app/monitoring/alerts.py` — shared alert formatting (single source for both UIs)
- [ ] Authenticated commands: `/status`, `/balance`, `/positions`, `/pnl`, `/today`, `/stats`, `/pause`, `/resume`, `/close <token>`, `/emergency`
- [ ] Only configured Telegram chat/user ID can issue admin commands
- [ ] Dangerous operations require confirmation; log all commands
- [ ] NEVER expose: private key, seed phrase, API secrets, database credentials
- [ ] Tests for command parsing and authentication

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

## Phase 12: FastAPI Health API & Authenticated Web Dashboard

> Primary control interface (Telegram deferred — see Phase 10).

### 12.1 Security Layer (`app/api/security.py`) — implemented

- [X] Session auth: random URL-safe tokens, only SHA-256 hashes stored in memory (memory-dump safe)
- [X] HttpOnly + SameSite=Strict session cookie; `Secure` flag behind HTTPS (`WEB_UI_COOKIE_SECURE`)
- [X] Sliding session expiry (`WEB_UI_SESSION_TTL_MINUTES`, default 60)
- [X] CSRF double-submit via `X-CSRF-Token` header on all state-changing endpoints (constant-time compare)
- [X] Login rate limiting: sliding window per IP (`WEB_UI_LOGIN_MAX_FAILURES` in `WEB_UI_RATE_LIMIT_WINDOW_SECONDS`)
- [X] Constant-time credential verification (`hmac.compare_digest`)
- [X] Fail closed: empty `WEB_UI_PASSWORD` disables the login endpoint entirely
- [X] Security headers on every response: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Cache-Control: no-store`
- [X] OpenAPI/docs endpoints disabled (`docs_url=None`, `redoc_url=None`, `openapi_url=None`)
- [ ] Argon2/bcrypt password hashing for at-rest config (current: env var compared in constant time)
- [ ] Optional TOTP second factor

### 12.2 API Endpoints (`app/api/routes.py`) — implemented

- [X] `POST /api/login` — credential check, rate limit, sets session cookie, returns CSRF token
- [X] `POST /api/logout` — CSRF-protected session destruction
- [X] `GET /health` — unauthenticated liveness probe (no sensitive data)
- [X] `GET /api/status` — mode, uptime, circuit breaker + recent events, balance, open positions with unrealized P&L, P&L summary (win rate, profit factor, drawdown), risk-limit usage
- [X] `GET /api/events?since=&limit=` — incremental event feed (alert source, replaces Telegram push)
- [X] `POST /api/actions/pause` — manual circuit-breaker pause (CSRF)
- [X] `POST /api/actions/resume` — resume trading (CSRF)
- [X] `POST /api/actions/positions/{token}/close` — manual position close via orchestrator (CSRF)
- [X] `POST /api/actions/emergency-close-all` — EMERGENCY breaker + close all positions (CSRF)
- [X] `app/api/state.py` — `AppState` registry + `EventLog` ring buffer wired to orchestrator notifier
- [X] Typed response schemas (`app/api/schemas.py`); endpoints never construct services, only read `AppState`
- [X] No secrets in any response (asserted in tests)
- [ ] `GET /api/metrics` — operational metrics (CPU/RAM/disk, dependency availability)
- [ ] DB-backed event persistence so events survive restarts
- [ ] Read-only vs admin roles (single admin user for now)
- [X] Tests: auth flows, CSRF enforcement, rate limiting, endpoint payloads, action wiring (`tests/unit/test_security.py`, `tests/integration/test_api.py` — 39 tests)

### 12.3 Dashboard UI (`app/api/static/`) — implemented

- [X] Single-page AJAX client (vanilla JS, zero dependencies, no CDN)
- [X] Login overlay with error/retry-after display
- [X] 5s polling: status + incremental events; auto-relogin on 401
- [X] Stat cards: equity, cash, open positions, total P&L, win rate, circuit breaker
- [X] Positions table with live unrealized P&L and per-row Close button
- [X] Events feed with level coloring; P&L summary table
- [X] Click-to-confirm on all destructive actions (close, emergency close-all)
- [X] Banner on non-NORMAL circuit breaker state
- [ ] Chart of equity/history (see Phase 10.1)

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

> Current suite: **256 tests passing** (`venv/bin/python -m pytest tests/ -q`).

### 16.1 Unit Tests (`tests/unit/`)

- [X] Scoring system tests (`test_scoring.py`)
- [X] Position sizing tests (`test_position_sizing.py`)
- [X] Stop loss tests (`test_positions.py`)
- [X] Take profit tests (`test_positions.py`)
- [X] Trailing stop tests (`test_positions.py`)
- [X] Circuit breaker state tests (`test_circuit_breaker.py`)
- [X] P&L calculation tests (`test_pnl.py`)
- [X] Risk engine tests (`test_risk_engine.py`)
- [X] Filter tests (`test_filters.py`)
- [X] Token lifecycle tests (`test_models_scanner.py`)
- [X] Configuration validation tests (`test_settings.py`)
- [X] Exposure tracker tests (`test_exposure.py`)
- [X] Wallet/token/reconciliation tests (`test_wallet.py`, `test_reconciliation.py`)
- [X] Paper trading engine tests (`test_paper.py` — slippage model, fills, portfolio math)
- [X] Position manager tests (`test_positions.py` — exit priority, high-water mark, time limit)
- [X] Orchestrator pipeline tests (`test_orchestrator.py` — buy/sell flows, duplicate protection, breaker integration)
- [ ] Momentum strategy edge cases: stale snapshots, zero-liquidity, missing volume fields
- [ ] Property-based tests for P&L math (hypothesis): round-trip conservation, no negative cash

### 16.2 Integration Tests (`tests/integration/`)

- [ ] PostgreSQL repository tests (with test DB)
- [X] DEX Screener client tests (mocked API)
- [ ] Jupiter client tests (mocked API)
- [X] Jupiter client tests (mocked API)
- [ ] Solana client tests (mocked RPC)
- [X] Solana client tests (mocked RPC)
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

### 17.2 systemd Serviceq1

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
