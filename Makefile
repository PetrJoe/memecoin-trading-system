# =============================================================================
# Meme Trader Makefile
# =============================================================================

.PHONY: help setup install dev test test-cov lint format migrate \
        create-wallet healthcheck deploy-vps clean env secret-key db-backup

PYTHON ?= python3.12
VENV   := venv
BIN    := $(VENV)/bin
MODULE := app.main

# ---------- Default target ----------
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------- Environment ----------
$(VENV)/pyvenv.cfg:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip

setup: $(VENV)/pyvenv.cfg ## Create venv + install all deps
	$(BIN)/pip install -e ".[dev]"

install: $(VENV)/pyvenv.cfg ## Re-install deps (fast, no editable)
	$(BIN)/pip install -r requirements.txt

env: ## Copy .env.example → .env (will not overwrite)
	@test -f .env || (cp .env.example .env && echo "✔ .env created — edit it now") || true
	@test -f .env && echo "ℹ .env already exists, skipping"

secret-key: ## Print a random WEB_UI_SECRET_KEY
	@$(BIN)/python -c "import secrets; print(secrets.token_urlsafe(32))"

# ---------- Run ----------
dev: env ## Run the bot in development mode (paper, Ctrl-C to stop)
	$(BIN)/python -m $(MODULE)

live: env ## Run the bot in LIVE mode (real trades, Ctrl-C to stop)
	$(BIN)/python -m $(MODULE)

live-safe: env ## Run the bot in live-safe mode (tiny real positions)
	TRADING_MODE=live_safe $(BIN)/python -m $(MODULE)

# ---------- Testing ----------
test: ## Run unit + integration tests
	$(BIN)/pytest -q

test-cov: ## Run tests with coverage report
	$(BIN)/pytest --cov=app --cov-report=term-missing --cov-report=html

# ---------- Code quality ----------
lint: ## Lint with ruff
	$(BIN)/ruff check app tests scripts

format: ## Auto-format with ruff
	$(BIN)/ruff format app tests scripts

# ---------- Database ----------
migrate: $(VENV)/pyvenv.cfg ## Show current alembic revision
	$(BIN)/python scripts/migrate.py current

migrate-upgrade: $(VENV)/pyvenv.cfg ## Run alembic upgrade head
	$(BIN)/python scripts/migrate.py upgrade head

# ---------- Utilities ----------
create-wallet: $(VENV)/pyvenv.cfg ## Generate a new Solana bot wallet
	$(BIN)/python scripts/create_bot_wallet.py

healthcheck: $(VENV)/pyvenv.cfg ## Run the health-check script
	$(BIN)/python scripts/healthcheck.py

db-backup: ## Backup the PostgreSQL database (requires pg_dump)
	@bash deploy/backup_database.sh

deploy-vps: ## Run the VPS setup script (Ubuntu, needs sudo)
	sudo bash deploy/setup_vps.sh

clean: ## Remove caches, build artifacts, .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache dist build *.egg-info htmlcov .ruff_cache
	@echo "✔ cleaned"
