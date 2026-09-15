
# Build a Production-Ready Autonomous Solana Memecoin Trading Bot

## 1. Project Objective

Build a production-ready, modular Python application that runs continuously on a Linux VPS and autonomously monitors the Solana memecoin market, discovers potential trading opportunities using DEX Screener data, evaluates token and market risk, generates trading signals, optionally executes swaps through Jupiter, manages open positions, records all activity in PostgreSQL, and reports everything through Telegram.

The system must be designed to operate 24/7 with:

* Automatic startup
* Automatic restart after crashes
* Recovery after VPS reboot
* On-chain position reconciliation
* Persistent database state
* Risk controls
* Circuit breakers
* Telegram notifications
* Telegram administrative commands
* Paper-trading mode
* Safe live-trading mode
* Comprehensive logging
* Health monitoring
* Database backups
* Graceful shutdown

The system must NOT be designed as a simple one-file trading script. Use a clean modular architecture suitable for long-term maintenance.

---

# 2. Core Technology Stack

Use:

### Backend

* Python 3.12+
* asyncio
* FastAPI for health/status API
* Pydantic / pydantic-settings
* SQLAlchemy
* asyncpg
* Alembic
* httpx
* structured Python logging

### Blockchain

* Solana
* Solana RPC
* Python Solana tooling
* Jupiter for swap routing/execution

### Market Data

* DEX Screener API/data endpoints where appropriate
* Do not scrape web pages if an official API/data endpoint is available.

### Database

* PostgreSQL

### Notifications

* Telegram Bot API

### Deployment

* Ubuntu 24.04+
* systemd
* Nginx only if the FastAPI dashboard/API needs public HTTPS access
* UFW firewall
* Git/GitHub

### Testing

* pytest
* pytest-asyncio
* mocked external APIs
* integration tests
* paper-trading tests

Do not introduce Docker or Kubernetes unless there is a compelling technical reason. The first deployment should be simple and VPS-friendly.

---

# 3. High-Level Architecture

Implement the following architecture:

```text
                         DEX Screener
                              |
                              v
                     +------------------+
                     | Token Discovery  |
                     +--------+---------+
                              |
                              v
                     +------------------+
                     | Market Analyzer  |
                     +--------+---------+
                              |
                              v
                     +------------------+
                     |   Risk Engine    |
                     +--------+---------+
                              |
                         PASS / REJECT
                              |
                              v
                     +------------------+
                     | Strategy Engine  |
                     +--------+---------+
                              |
                       BUY / SELL / HOLD
                              |
                              v
                     +------------------+
                     |  Risk Manager    |
                     +--------+---------+
                              |
                           APPROVE
                              |
                              v
                     +------------------+
                     | Jupiter Executor |
                     +--------+---------+
                              |
                              v
                         Solana Wallet
                              |
                              v
                       Solana Network

      +-------------------+-------------------+
      |                   |                   |
      v                   v                   v
 PostgreSQL          Telegram            FastAPI
      |                   |                   |
      v                   v                   v
 Persistence       Alerts/Commands       Health/Status
```

---

# 4. Repository Structure

Create this structure:

```text
meme-trader/
│
├── app/
│   ├── main.py
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py
│   │   └── logging.py
│   │
│   ├── database/
│   │   ├── __init__.py
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── repositories.py
│   │   └── migrations/
│   │
│   ├── scanner/
│   │   ├── __init__.py
│   │   ├── dex_screener.py
│   │   ├── discovery.py
│   │   ├── market_data.py
│   │   └── filters.py
│   │
│   ├── blockchain/
│   │   ├── __init__.py
│   │   ├── solana_client.py
│   │   ├── wallet.py
│   │   ├── token.py
│   │   └── reconciliation.py
│   │
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── risk_engine.py
│   │   ├── position_sizing.py
│   │   ├── exposure.py
│   │   └── circuit_breaker.py
│   │
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── momentum.py
│   │   ├── volume_breakout.py
│   │   └── scoring.py
│   │
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── jupiter.py
│   │   ├── quote.py
│   │   ├── buy.py
│   │   ├── sell.py
│   │   └── transaction.py
│   │
│   ├── portfolio/
│   │   ├── __init__.py
│   │   ├── positions.py
│   │   ├── balances.py
│   │   └── pnl.py
│   │
│   ├── monitoring/
│   │   ├── __init__.py
│   │   ├── telegram.py
│   │   ├── alerts.py
│   │   ├── health.py
│   │   └── metrics.py
│   │
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── scanner_worker.py
│   │   ├── strategy_worker.py
│   │   ├── position_worker.py
│   │   ├── reconciliation_worker.py
│   │   └── health_worker.py
│   │
│   └── api/
│       ├── __init__.py
│       ├── app.py
│       ├── routes.py
│       └── schemas.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── scripts/
│   ├── migrate.py
│   ├── healthcheck.py
│   ├── create_bot_wallet.py
│   └── backup_database.sh
│
├── deploy/
│   ├── meme-trader.service
│   ├── nginx.conf
│   └── logrotate.conf
│
├── .env.example
├── .gitignore
├── requirements.txt
├── alembic.ini
├── pyproject.toml
├── README.md
└── LICENSE
```

---

# 5. Environment Configuration

Create `.env.example`.

Required configuration:

```env
APP_ENV=development

TRADING_MODE=paper

SOLANA_RPC_URL=
SOLANA_WS_URL=

JUPITER_API_URL=

DATABASE_URL=

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

BOT_PRIVATE_KEY=

MAX_POSITION_USD=0.50
MAX_OPEN_POSITIONS=2
MAX_DAILY_LOSS_USD=1.00

STOP_LOSS_PERCENT=10
TAKE_PROFIT_PERCENT=25

MAX_SLIPPAGE_BPS=100

SCANNER_INTERVAL_SECONDS=20
POSITION_CHECK_INTERVAL_SECONDS=5

MIN_LIQUIDITY_USD=10000
MIN_VOLUME_5M_USD=5000

MIN_RISK_SCORE=70

TRADING_ENABLED=false
```

Never commit `.env`.

Never print private keys.

Never include private keys in logs.

Never send private keys through Telegram.

---

# 6. Trading Modes

Implement three modes.

## PAPER

No blockchain transactions.

The bot simulates:

* Buy
* Sell
* Position
* P&L
* Fees
* Slippage assumptions

Default mode must be:

```text
TRADING_MODE=paper
TRADING_ENABLED=false
```

## LIVE_SAFE

Real transactions but strict low limits.

Example:

```text
MAX_POSITION_USD=0.50
MAX_OPEN_POSITIONS=2
MAX_DAILY_LOSS_USD=1
```

## LIVE

Uses configured production risk limits.

Never automatically switch from paper to live.

Live trading must require explicit configuration.

---

# 7. Wallet Architecture

The bot must use a dedicated Solana trading wallet.

Do not design the application around the user's primary wallet.

Implement:

```text
WalletService
```

Responsibilities:

* Load signing credentials securely
* Validate wallet address
* Query SOL balance
* Query token balances
* Sign transactions locally
* Never expose secret material
* Provide public wallet address to other components
* Never send private key to external APIs

Create:

```text
scripts/create_bot_wallet.py
```

This script should generate a new wallet/keypair and display the public address.

It must warn the user that the secret key must be backed up securely.

Do not automatically fund the wallet.

---

# 8. DEX Screener Integration

Implement:

```text
DexScreenerClient
```

It should retrieve relevant Solana token/pair information.

Normalize external API responses into internal models.

Create:

```text
MarketSnapshot
```

containing:

* token address
* pair address
* symbol
* name
* price
* liquidity
* market cap
* FDV
* volume 5m
* volume 1h
* volume 6h
* volume 24h
* price change
* buys
* sells
* pair creation time
* timestamp

Handle:

* HTTP errors
* timeouts
* rate limits
* malformed responses
* temporary outages
* retries with exponential backoff

Never let one API failure crash the entire bot.

---

# 9. Token Discovery

Implement a scanner that continuously identifies potential Solana memecoin candidates.

Initial filtering:

```text
chain == solana
```

Then configurable filters:

```text
minimum liquidity
minimum 5m volume
minimum transaction activity
maximum token age
minimum buy activity
maximum spread/slippage
```

Store discovered tokens in PostgreSQL.

Avoid duplicate processing.

A token should have a lifecycle:

```text
DISCOVERED
    ↓
WATCHING
    ↓
ANALYZING
    ↓
APPROVED
    ↓
TRADED
    ↓
REJECTED
```

---

# 10. Risk Engine

Create a dedicated risk engine.

It must run BEFORE every buy.

Risk checks should include, where reliable data is available:

* Liquidity
* Liquidity changes
* Token age
* Buy/sell ratio
* Trading volume
* Holder concentration
* Mint authority
* Freeze authority
* Suspicious token characteristics
* Price impact
* Expected slippage
* Wallet exposure
* Existing position exposure
* Daily loss
* Number of consecutive losses

Return:

```text
RiskResult
```

with:

```text
approved
score
reasons
warnings
```

Example:

```json
{
  "approved": true,
  "score": 84,
  "reasons": [
    "Strong 5m volume",
    "Healthy liquidity",
    "Positive buy pressure"
  ],
  "warnings": []
}
```

Critical safety failures must always result in rejection regardless of score.

---

# 11. Strategy Engine

Create a strategy abstraction:

```text
BaseStrategy
```

Methods:

```text
analyze()
generate_signal()
```

Signals:

```text
BUY
SELL
HOLD
WATCH
REJECT
```

Implement initial strategy:

## Momentum + Volume Strategy

Consider:

* Short-term price momentum
* Volume acceleration
* Buy/sell ratio
* Liquidity
* Transaction activity
* Token age
* Risk score

Do NOT use machine learning in version 1.

Keep the strategy deterministic and explainable.

Every generated signal must contain reasons.

Example:

```text
BUY SIGNAL

Score: 82

Reasons:
+ Strong volume acceleration
+ Positive buy pressure
+ Price momentum
+ Sufficient liquidity
+ Acceptable risk score
```

---

# 12. Strategy Scoring

Create a configurable scoring system.

Example:

```text
Liquidity:             20
Volume:                20
Buy pressure:          15
Momentum:              15
Volume acceleration:   10
Token age:             10
Risk score:            10
--------------------------
TOTAL:                100
```

Do not hard-code these values throughout the application.

Store them in configuration.

Allow future strategies to use different scoring systems.

---

# 13. Position Sizing

Implement:

```text
PositionSizer
```

Inputs:

* account balance
* configured maximum position
* daily loss
* current exposure
* number of open positions
* risk score
* available SOL
* strategy confidence

Output:

```text
approved_position_size
```

Never allow the strategy to bypass position sizing.

Example:

```text
Account: $500
Maximum position: 2%
Maximum position: $10
```

For initial live testing:

```text
$0.50–$1 positions
```

must be possible.

---

# 14. Risk Limits

Implement configurable:

```text
MAX_POSITION_USD
MAX_OPEN_POSITIONS
MAX_DAILY_LOSS_USD
MAX_TOTAL_EXPOSURE_USD
MAX_SLIPPAGE_BPS
MAX_PRICE_IMPACT_BPS
MAX_CONSECUTIVE_LOSSES
MAX_POSITION_DURATION
```

Every trade must pass the risk manager.

The risk manager has final authority.

If strategy says BUY but risk manager says NO:

```text
NO TRADE
```

---

# 15. Circuit Breaker

Implement a global circuit breaker.

Automatically pause NEW trades if:

```text
Daily loss limit exceeded
Too many consecutive losses
Too many execution failures
Too many RPC failures
Jupiter unavailable
Database unavailable
Abnormal slippage
Wallet balance too low
Unexpected transaction state
```

States:

```text
NORMAL
WARNING
PAUSED
EMERGENCY
```

When paused:

* Do not open new positions.
* Continue monitoring existing positions.
* Continue sending alerts.
* Continue allowing emergency exits where safe.

Telegram notification:

```text
🚨 CIRCUIT BREAKER ACTIVATED

Reason:
Daily loss limit exceeded.

New trades: DISABLED

Existing positions:
Still being monitored.
```

---

# 16. Jupiter Integration

Create:

```text
JupiterClient
```

Responsibilities:

* Request quotes
* Validate route
* Calculate expected output
* Calculate price impact
* Enforce slippage limit
* Build swap transaction
* Submit transaction
* Track transaction status

Do not assume transaction submission means success.

The system must verify confirmation.

Handle:

* quote failure
* route unavailable
* insufficient balance
* slippage exceeded
* transaction failure
* RPC failure
* timeout
* duplicate execution prevention

---

# 17. Trade Execution State Machine

Implement:

```text
CREATED
 ↓
QUOTE_REQUESTED
 ↓
QUOTE_RECEIVED
 ↓
RISK_APPROVED
 ↓
TRANSACTION_BUILT
 ↓
SIGNED
 ↓
SUBMITTED
 ↓
CONFIRMING
 ↓
CONFIRMED
```

Failure states:

```text
FAILED
CANCELLED
EXPIRED
UNKNOWN
```

If state becomes `UNKNOWN`, do not blindly retry.

First reconcile the blockchain.

This prevents accidental duplicate trades.

---

# 18. Buy Flow

Implement exactly:

```text
Candidate detected
        ↓
Market snapshot
        ↓
Risk analysis
        ↓
Strategy signal
        ↓
Position sizing
        ↓
Circuit breaker
        ↓
Jupiter quote
        ↓
Slippage/price-impact validation
        ↓
Build transaction
        ↓
Sign locally
        ↓
Broadcast
        ↓
Confirm on-chain
        ↓
Create position
        ↓
Store trade
        ↓
Telegram notification
```

---

# 19. Sell Flow

Implement:

```text
Open position
       ↓
Current price
       ↓
Evaluate exit conditions
       ↓
STOP LOSS?
TAKE PROFIT?
TRAILING STOP?
TIME LIMIT?
RISK EVENT?
       ↓
YES
       ↓
Jupiter quote
       ↓
Validate
       ↓
Execute
       ↓
Confirm
       ↓
Close position
       ↓
Calculate actual P&L
       ↓
Store trade
       ↓
Telegram notification
```

---

# 20. Position Management

Each position should contain:

```text
token
entry price
quantity
capital invested
entry time
stop loss
take profit
trailing stop
current price
unrealized P&L
realized P&L
status
exit reason
```

Exit reasons:

```text
TAKE_PROFIT
STOP_LOSS
TRAILING_STOP
TIME_LIMIT
EMERGENCY
MANUAL
RISK_EVENT
```

---

# 21. Take Profit

Implement configurable take profit.

Example:

```text
TAKE_PROFIT_PERCENT=25
```

If:

```text
entry = $1.00
current = $1.25
```

trigger an exit.

Allow future multi-level TP:

```text
TP1 = +20%
TP2 = +40%
TP3 = +75%
```

Do not implement complex scaling unless architecture allows it cleanly.

---

# 22. Stop Loss

Implement:

```text
STOP_LOSS_PERCENT=10
```

Example:

```text
Entry: $1.00
SL: $0.90
```

Do not allow a strategy to disable the global maximum-loss protection.

---

# 23. Trailing Stop

Design a trailing-stop component that can be enabled later.

Example:

```text
Entry: $1.00

Price → $1.20
Trailing stop → $1.08

Price → $1.40
Trailing stop → $1.26
```

Make this configurable.

---

# 24. PostgreSQL Database

Create SQLAlchemy models for:

### Token

```text
id
address
symbol
name
decimals
created_at
updated_at
status
risk_score
```

### Pair

```text
id
address
token_id
dex
liquidity
created_at
```

### MarketSnapshot

```text
id
token_id
price
liquidity
volume_5m
volume_1h
volume_6h
volume_24h
buys
sells
market_cap
timestamp
```

### Signal

```text
id
token_id
signal
score
reasons
created_at
```

### Order

```text
id
token_id
side
amount
status
tx_signature
created_at
```

### Trade

```text
id
order_id
token_id
side
quantity
price
fees
slippage
pnl
tx_signature
status
created_at
```

### Position

```text
id
token_id
entry_price
quantity
capital
stop_loss
take_profit
trailing_stop
status
opened_at
closed_at
exit_reason
realized_pnl
```

### BotEvent

```text
id
level
event_type
message
metadata
created_at
```

### DailyStats

```text
date
starting_balance
ending_balance
realized_pnl
unrealized_pnl
fees
trade_count
winning_trades
losing_trades
```

---

# 25. Database Requirements

Use:

* Alembic migrations
* indexes
* proper foreign keys
* unique constraints
* timestamps
* transaction boundaries

Important unique constraints:

```text
transaction signature
token address
position identity
```

Prevent duplicate trades and duplicate token records.

---

# 26. Portfolio Manager

Implement:

```text
PortfolioManager
```

Responsibilities:

* wallet balance
* token balances
* open positions
* total exposure
* realized P&L
* unrealized P&L
* daily P&L
* win rate
* losses
* fees

Reconcile portfolio state against blockchain data periodically.

---

# 27. On-Chain Reconciliation

This is mandatory.

After:

* application startup
* VPS reboot
* database recovery
* transaction timeout
* unknown transaction status

perform reconciliation.

Compare:

```text
Database positions
        VS
Blockchain wallet balances
```

Detect:

```text
missing position
unexpected token balance
unconfirmed trade
unknown transaction
incorrect quantity
```

Never blindly create another transaction when state is uncertain.

---

# 28. Telegram Integration

Create a Telegram bot.

The bot should send automatic notifications.

### Startup

```text
🤖 BOT STARTED

Status: ONLINE

Mode: PAPER
Trading: DISABLED

Wallet: xxx...xxx

Balance: $2.00

Scanner: 🟢
Solana RPC: 🟢
Jupiter: 🟢
Database: 🟢
```

### Opportunity

```text
🔎 OPPORTUNITY

Token: ABC
Price: $0.00042

Liquidity: $42K
5m Volume: $18K

Buys: 142
Sells: 71

Risk Score: 84/100

Action: WATCHING
```

### Buy

```text
🟢 BUY EXECUTED

Token: ABC

Amount: $0.50
Entry: $0.00042

TP: +25%
SL: -10%

Transaction: CONFIRMED
```

### Sell

```text
🔴 POSITION CLOSED

Token: ABC

Entry: $0.00042
Exit: $0.00053

P&L: +26.2%
Profit: +$0.13

Reason: TAKE_PROFIT
```

### Daily report

```text
📊 DAILY REPORT

Trades: 12
Wins: 7
Losses: 5

Win rate: 58.3%

Profit: +$1.42
Fees: $0.12
Net P&L: +$1.30

Open positions: 2

Bot status: 🟢
```

---

# 29. Telegram Commands

Implement authenticated commands:

```text
/start
/help
/status
/balance
/positions
/pnl
/today
/stats
/pause
/resume
/close <token>
/emergency
```

Only the configured Telegram chat/user ID can issue administrative commands.

All commands must be logged.

For dangerous operations use confirmation.

Example:

```text
/emergency
```

responds:

```text
⚠️ EMERGENCY MODE

This will disable new trades.

Confirm?
[YES] [CANCEL]
```

Never expose:

* private key
* seed phrase
* API secrets
* database credentials

through Telegram.

---

# 30. Telegram Daily Report

Send a daily summary automatically.

Include:

```text
Starting balance
Ending balance
Realized P&L
Unrealized P&L
Net P&L
Fees
Number of trades
Wins
Losses
Win rate
Best trade
Worst trade
Open positions
Circuit breaker status
```

---

# 31. FastAPI Health API

Create:

```text
GET /health
GET /status
GET /metrics
```

`/health` should verify:

```text
Application
Database
Solana RPC
Jupiter
Telegram
```

Return appropriate HTTP status.

Example:

```json
{
  "status": "healthy",
  "database": "ok",
  "solana_rpc": "ok",
  "jupiter": "ok",
  "telegram": "ok",
  "trading_mode": "paper"
}
```

Do not expose secrets.

---

# 32. Worker Architecture

Use asynchronous workers.

Implement:

### Scanner Worker

Runs every configurable interval.

```text
discover tokens
fetch market data
store snapshots
```

### Strategy Worker

```text
read candidates
calculate signals
store signals
```

### Position Worker

Runs frequently.

```text
update prices
calculate P&L
evaluate exits
```

### Reconciliation Worker

Runs periodically.

```text
verify wallet
verify positions
verify transactions
```

### Health Worker

```text
check dependencies
check resource state
send alerts
```

Avoid blocking the event loop.

Use timeouts for all external calls.

---

# 33. Concurrency and Duplicate Protection

The bot must prevent:

```text
two BUY orders for the same token
```

and:

```text
BUY while SELL is already being processed
```

Implement locks or database-level safeguards.

Use idempotency wherever possible.

Example:

```text
token + strategy + signal window
```

must not generate duplicate execution.

---

# 34. Error Handling

External services will fail.

Handle:

```text
HTTP 429
HTTP 500
HTTP 503
network timeout
DNS failure
RPC timeout
Jupiter failure
database connection failure
Telegram failure
malformed API response
```

Use:

```text
exponential backoff
bounded retries
circuit breakers
timeouts
```

Never use infinite retries.

A failed trade must not crash the entire bot.

---

# 35. Logging

Use structured logs.

Example:

```text
INFO BUY_SIGNAL token=ABC score=84
INFO TRADE_SUBMITTED token=ABC tx=...
INFO TRADE_CONFIRMED token=ABC tx=...
INFO POSITION_OPENED token=ABC
INFO POSITION_CLOSED token=ABC pnl=0.13
WARNING JUPITER_TIMEOUT
ERROR DATABASE_CONNECTION_FAILED
```

Never log secrets.

Create separate log categories where practical:

```text
application
trades
errors
security
```

---

# 36. VPS Deployment

Target:

```text
Ubuntu 24.04+
```

Installation:

```text
Python
PostgreSQL
Git
UFW
systemd
```

Create a dedicated Linux user:

```text
memetrader
```

Do not run the application as root.

Directory:

```text
/opt/meme-trader
```

Permissions must prevent other users from reading secrets.

---

# 37. systemd

Create:

```text
deploy/meme-trader.service
```

Requirements:

```text
User=memetrader
WorkingDirectory=/opt/meme-trader
Restart=always
RestartSec=5
```

The service must:

* start on boot
* restart after failure
* stop gracefully
* load environment variables securely
* write logs to journald

Example behavior:

```text
VPS reboot
     ↓
systemd
     ↓
Trading bot starts
     ↓
database connection
     ↓
dependency checks
     ↓
on-chain reconciliation
     ↓
resume operation
```

---

# 38. Graceful Shutdown

On:

```text
SIGTERM
SIGINT
```

the application should:

1. Stop accepting new trades.
2. Finish safe in-flight operations.
3. Persist state.
4. Close database connections.
5. Stop workers.
6. Exit cleanly.

Never abruptly terminate during transaction state changes without attempting reconciliation later.

---

# 39. Database Backup

Create:

```text
scripts/backup_database.sh
```

Implement daily PostgreSQL backups.

Retention:

```text
7 daily
4 weekly
```

Do not include private keys in backups.

---

# 40. Security

Implement security-first defaults.

Requirements:

* Dedicated trading wallet
* Never use main wallet
* `.env` excluded from Git
* Private key never logged
* Private key never sent to Telegram
* Application runs as non-root
* UFW enabled
* SSH key authentication
* Disable password SSH login where practical
* PostgreSQL not publicly exposed
* FastAPI not publicly exposed unless required
* Rate-limit administrative endpoints
* Telegram admin authentication
* Validate all external API responses

If a secret appears in a log or error message, sanitize it.

---

# 41. Monitoring

Track:

```text
CPU
RAM
disk
network
bot uptime
database availability
RPC availability
Jupiter availability
scanner activity
trade execution failures
```

Send Telegram warning when:

```text
disk > 80%
memory > 85%
bot worker stopped
database unavailable
RPC unavailable
too many failed trades
circuit breaker activated
```

---

# 42. Dashboard

Create a simple FastAPI-based JSON dashboard initially.

Return:

```text
bot status
wallet balance
daily P&L
total P&L
open positions
recent trades
strategy signals
risk status
system health
```

Do not spend significant time building a frontend in version 1.

A frontend can be added later.

---

# 43. Paper Trading Engine

Paper trading should simulate:

* entry
* exit
* slippage
* fees
* price movement
* position management
* stop loss
* take profit
* trailing stop

Paper trades must use the same:

```text
scanner
strategy
risk engine
position sizing
position manager
```

as live trading.

Only execution should differ.

This ensures paper results are meaningful.

---

# 44. Backtesting

Create an interface allowing historical market snapshots to be replayed through the strategy.

Output:

```text
total trades
winning trades
losing trades
win rate
gross profit
gross loss
net profit
maximum drawdown
profit factor
average win
average loss
average holding time
```

Do not claim a strategy is profitable simply because a small sample produces profit.

---

# 45. Testing Requirements

Write tests for:

### Unit

* scoring
* position sizing
* stop loss
* take profit
* trailing stop
* circuit breaker
* P&L
* risk engine
* filters

### Integration

* PostgreSQL
* DEX Screener client mocked
* Jupiter client mocked
* Solana client mocked
* Telegram mocked

### Failure tests

Simulate:

```text
RPC outage
Jupiter outage
DEX Screener outage
database outage
Telegram outage
transaction timeout
duplicate signal
duplicate transaction
VPS restart
```

The application must recover gracefully.

---

# 46. Development Order

Build in this exact order:

## Phase 1

Project setup:

* Python
* configuration
* logging
* PostgreSQL
* SQLAlchemy
* Alembic

## Phase 2

DEX Screener:

* API client
* market normalization
* token discovery
* snapshots

## Phase 3

Risk engine:

* liquidity
* volume
* token checks
* scoring

## Phase 4

Strategy:

* momentum
* volume breakout
* signal generation

## Phase 5

Paper trading:

* simulated execution
* positions
* P&L
* TP/SL

## Phase 6

Telegram:

* notifications
* reports
* commands

## Phase 7

Solana:

* wallet
* RPC
* balance
* transaction handling

## Phase 8

Jupiter:

* quotes
* swap transaction
* signing
* confirmation

## Phase 9

Live-safe mode:

* tiny position sizes
* strict limits
* circuit breaker

## Phase 10

VPS:

* systemd
* health monitoring
* backups
* automatic recovery

---

# 47. Important Development Rule

DO NOT implement live trading first.

The initial application must start as:

```text
TRADING_MODE=paper
TRADING_ENABLED=false
```

The application should clearly display:

```text
⚠️ PAPER TRADING
NO REAL TRANSACTIONS
```

Only after the paper engine, risk system, position management, and reconciliation are working should live execution be enabled.

---

# 48. AI Coding Agent Behavior

While implementing:

1. Inspect the existing repository before changing anything.
2. Create a clean architecture.
3. Do not put everything into `main.py`.
4. Use dependency injection where appropriate.
5. Keep external integrations isolated.
6. Write tests alongside functionality.
7. Never hard-code secrets.
8. Never hard-code trading limits.
9. Never silently swallow errors.
10. Never bypass risk controls.
11. Never execute live trades while in paper mode.
12. Never assume an on-chain transaction succeeded without confirmation.
13. Never automatically retry an unknown transaction without reconciliation.
14. Make every trade decision explainable.
15. Keep the application restart-safe.

---

# 49. Final Acceptance Criteria

The project is complete when:

### Local

```text
python -m app.main
```

starts successfully.

### Paper mode

The bot can:

```text
discover token
↓
analyze
↓
generate signal
↓
simulate buy
↓
monitor
↓
simulate TP/SL
↓
simulate sell
↓
calculate P&L
↓
send Telegram report
```

### Live-safe mode

The bot can:

```text
discover
↓
risk check
↓
strategy
↓
position sizing
↓
Jupiter quote
↓
sign
↓
submit
↓
confirm
↓
record
↓
monitor
↓
exit
```

### VPS

After:

```text
sudo reboot
```

the bot automatically:

```text
starts
↓
connects to database
↓
checks dependencies
↓
reconciles wallet
↓
reconciles positions
↓
resumes operation
```

### Failure recovery

If:

```text
Jupiter goes offline
```

the bot does not crash.

If:

```text
DEX Screener goes offline
```

the bot stops discovering new opportunities but continues safely managing existing positions.

If:

```text
Telegram goes offline
```

trading infrastructure continues, while Telegram alerts are retried later.

If:

```text
database goes offline
```

the bot must fail closed for new trades rather than trading without persistent state.

---

# 50. Telegram Final Interface

The completed system should feel like having a trading assistant operating on the VPS.

Example:

```text
🤖 MEME TRADER

🟢 ONLINE

Mode: PAPER
Trading: DISABLED

Balance: $2.00
Today's P&L: +$0.00

Open Positions: 0
Trades Today: 0

Scanner: 🟢
Risk Engine: 🟢
Solana: 🟢
Jupiter: 🟢
Database: 🟢

Last scan: 12 seconds ago
```

The user should be able to monitor the entire system from Telegram while the VPS performs the actual work autonomously.

---

# 51. Deliverables

Produce:

1. Complete Python source code.
2. PostgreSQL models.
3. Alembic migrations.
4. DEX Screener integration.
5. Solana integration.
6. Jupiter integration.
7. Risk engine.
8. Strategy engine.
9. Paper trading engine.
10. Live-safe execution.
11. Position manager.
12. P&L engine.
13. Circuit breaker.
14. Telegram bot.
15. FastAPI health API.
16. Automated tests.
17. systemd service.
18. VPS deployment scripts.
19. Database backup script.
20. `.env.example`.
21. Complete README.
22. Security documentation.
23. Trading configuration documentation.
24. Troubleshooting documentation.

Do not skip infrastructure, monitoring, recovery, or tests.

The final result should be capable of running continuously on a VPS with minimal human intervention while keeping **paper trading as the default and live trading explicitly opt-in**.
