# 🕯️ Meme Trader

Autonomous Solana memecoin trading bot with an authenticated web dashboard.
Discovers tokens via DexScreener, scores them with a configurable strategy,
enforces hard risk limits, and executes through Jupiter — **paper mode first**.

> ⚠️ **This software is for research and education.** Memecoin trading is
> extremely high-risk; you can lose all funds you deploy. The default and
> recommended mode is paper trading. Live modes require explicit opt-in.

---

## Architecture

```
DexScreener ──▶ TradingLoop (scanner cycle)
                  ├──▶ TokenFilter ──▶ watchlist
                  ├──▶ MomentumStrategy ──▶ signal
                  ├──▶ RiskEngine ──▶ approval + score
                  ├──▶ PositionSizer ──▶ size
                  ├──▶ TradeOrchestrator ──▶ PaperExecutor (paper) / Jupiter (live)
                  └──▶ PositionManager ──▶ TP / SL / trailing / time exits
                          │
        AppState ◀────────┘ (mirrors all runtime state)
           │
        FastAPI ◀── Web dashboard (AJAX, session-auth)
           ├── /api/status   /api/events   /api/metrics
           └── /api/actions/*  (pause / resume / close / emergency)

HealthWorker · ReconciliationWorker (background verification)
```

Key modules:

| Path | Purpose |
|---|---|
| `app/workers/trading_loop.py` | Scan → analyze → trade → monitor cycle |
| `app/execution/orchestrator.py` | Buy/sell pipelines, duplicate protection |
| `app/execution/paper.py` | Fill simulator (slippage + fees) |
| `app/portfolio/` | Positions, balances, P&L statistics |
| `app/risk/` | Risk engine, sizing, exposure, circuit breaker |
| `app/api/` | Auth, routes, dashboard (`app/api/static/`) |
| `app/monitoring/` | Dependency health, resource metrics |

---

## Quick start (paper mode)

Requirements: Python 3.12+

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# Set WEB_UI_PASSWORD (required for dashboard login) and WEB_UI_SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"   # secret key

python -m app.main
```

Open **http://127.0.0.1:8080**, sign in, and watch the paper session:

- **PAPER TRADING — NO REAL TRANSACTIONS** is displayed at startup and in the UI.
- The loop scans DexScreener, adds passing tokens to the watchlist, buys on
  strong signals, and manages exits (stop loss / take profit / trailing / time).
- Events (discoveries, buys, exits, warnings) stream into the dashboard feed.

Run tests:

```bash
pytest -q
```

Backtest against recorded snapshots:

```python
from app.backtest import BacktestEngine, BacktestConfig
engine = BacktestEngine(BacktestConfig(starting_balance_usd=100))
report = engine.run(history)   # list of "bars": lists of MarketSnapshot
print(report.to_dict())
```

---

## Trading modes

| Mode | Behavior |
|---|---|
| `paper` (default) | Full pipeline, simulated fills, no chain interaction |
| `live_safe` | Real trades, hard-capped tiny sizes (see `MAX_POSITION_USD`) |
| `live` | Real trades at configured sizes — **know what you are doing** |

`TRADING_ENABLED=false` (default) keeps the bot in signal-only mode; nothing
executes regardless of mode.

### Going to live (full checklist)

1. Generate a dedicated wallet: `python scripts/create_bot_wallet.py`
2. Put the secret in `BOT_PRIVATE_KEY` — **never** anywhere else
3. Fund it with a small amount of SOL you are prepared to lose entirely
4. Read the risk limits below and set them deliberately
5. `TRADING_MODE=live_safe`, `TRADING_ENABLED=true`, restart, watch closely
6. Run on a VPS with the systemd unit (below), not your laptop

---

## Risk limits (all enforced before every buy)

| Setting | Default | Meaning |
|---|---|---|
| `MAX_POSITION_USD` | 0.50 | Max size of a single position |
| `MAX_OPEN_POSITIONS` | 2 | Concurrent positions cap |
| `MAX_DAILY_LOSS_USD` | 1.00 | Circuit breaker pauses trading beyond this daily loss |
| `MAX_TOTAL_EXPOSURE_USD` | 5.00 | Aggregate position value cap |
| `MAX_SLIPPAGE_BPS` | 100 | Quote rejection threshold |
| `MAX_PRICE_IMPACT_BPS` | 500 | Quote rejection threshold |
| `MAX_CONSECUTIVE_LOSSES` | 5 | Pauses trading after N losses in a row |
| `MAX_POSITION_DURATION_HOURS` | 24 | Force-exit after this holding time |

The **circuit breaker** (`NORMAL → WARNING → PAUSED → EMERGENCY`) pauses new
buys on: daily loss exceeded, consecutive losses, execution failures, RPC
failures, abnormal slippage, low wallet balance, unknown transaction state,
or manual/emergency stop from the dashboard.

### Strategy & scanner parameters

- `STOP_LOSS_PERCENT` (10), `TAKE_PROFIT_PERCENT` (25), `TRAILING_STOP_PERCENT` (15)
- `MIN_LIQUIDITY_USD` (10k), `MIN_VOLUME_5M_USD` (5k), `MAX_CANDIDATES_PER_SCAN` (3)
- Scoring weights (`SCORE_WEIGHT_*`) — configurable, must total 100

---

## Web dashboard

Login uses `WEB_UI_USERNAME` / `WEB_UI_PASSWORD` (empty password disables
login entirely). Security model:

- Random session tokens — only SHA-256 hashes stored in memory
- HttpOnly + SameSite=Strict cookie, sliding expiry (`WEB_UI_SESSION_TTL_MINUTES`)
- CSRF token required for all actions (`X-CSRF-Token` header)
- Login rate limiting (5 failures / 5 min default, per IP)
- Security headers on every response; no secrets in any API payload

Endpoints: `GET /health` (public), `GET /api/status`, `GET /api/events`,
`GET /api/metrics`, and CSRF-protected actions: pause, resume,
`positions/{token}/close`, `emergency-close-all`.

Behind HTTPS, set `WEB_UI_COOKIE_SECURE=true` and use `deploy/nginx.conf`.

---

## Configuration reference

All settings live in `.env` (see `.env.example` with full annotations).
Highlights:

```env
APP_ENV=development            # development | staging | production
TRADING_MODE=paper             # paper | live_safe | live
TRADING_ENABLED=false

SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
JUPITER_API_URL=https://quote-api.jup.ag/v6

WEB_UI_ENABLED=true
WEB_UI_USERNAME=admin
WEB_UI_PASSWORD=               # REQUIRED for login
WEB_UI_SECRET_KEY=             # random 32+ chars
```

Database: paper mode runs fully in-memory. The PostgreSQL schema
(`DATABASE_URL`, Alembic migrations in `app/database/migrations/`) is used in
live/persistence deployments: `python scripts/migrate.py`.

---

## VPS deployment (Ubuntu 24.04+)

```bash
sudo bash deploy/setup_vps.sh     # user, postgres, ufw, systemd, cron
sudo systemctl start meme-trader
journalctl -u meme-trader -f
```

- Service: `deploy/meme-trader.service` (restart on failure, hardened)
- Backups: `deploy/backup_database.sh` via cron (7 daily / 4 weekly)
- Health: `python scripts/healthcheck.py` (exit code 0/1/2; cron-friendly)
- HTTPS proxy: `deploy/nginx.conf` + certbot

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Dashboard login disabled | Set `WEB_UI_PASSWORD` and restart |
| `scanner_unavailable` events | DexScreener outage; positions still managed, discovery resumes automatically |
| Circuit breaker paused | Check the banner / `/api/metrics`; resolve cause, click Resume |
| No buys happening | Check `/api/events` for `buy_rejected` reasons (filters, risk, breaker) |
| RPC degraded | Use a paid/private RPC endpoint for anything beyond paper mode |
| Migration errors | `python scripts/migrate.py current`, then `python scripts/migrate.py upgrade head` |

---

## License

MIT — see `pyproject.toml`. Trading crypto is at your own risk.
