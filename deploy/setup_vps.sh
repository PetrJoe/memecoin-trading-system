#!/usr/bin/env bash
# VPS setup for Ubuntu 24.04+: dedicated user, dependencies, permissions, firewall.
# Run as root:  bash deploy/setup_vps.sh
set -euo pipefail

APP_DIR="/opt/meme-trader"
APP_USER="memetrader"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root (sudo bash deploy/setup_vps.sh)" >&2
  exit 1
fi

echo "==> Installing system packages"
apt-get update -y
apt-get install -y python3.12 python3.12-venv python3-pip postgresql git ufw nginx logrotate

echo "==> Creating dedicated user: ${APP_USER}"
id -u "${APP_USER}" &>/dev/null || useradd --system --create-home --shell /bin/bash "${APP_USER}"

echo "==> Deploying to ${APP_DIR}"
mkdir -p "${APP_DIR}"
rsync -a --exclude venv --exclude .git --exclude .env --exclude backups ./ "${APP_DIR}/"
cd "${APP_DIR}"

echo "==> Python environment"
sudo -u "${APP_USER}" python3.12 -m venv venv
sudo -u "${APP_USER}" ./venv/bin/pip install --upgrade pip
sudo -u "${APP_USER}" ./venv/bin/pip install -e ".[dev]"

echo "==> Environment file (interactive)"
if [ ! -f "${APP_DIR}/.env" ]; then
  cp .env.example .env
  chown "${APP_USER}:${APP_USER}" .env
  echo ">>> EDIT ${APP_DIR}/.env now: set WEB_UI_PASSWORD, WEB_UI_SECRET_KEY, DATABASE_URL."
  echo ">>> Generate a secret:  python3 -c \"import secrets; print(secrets.token_urlsafe(32))\""
fi
chmod 600 "${APP_DIR}/.env" 2>/dev/null || true

echo "==> PostgreSQL: local only, dedicated db/user"
systemctl enable --now postgresql
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='${APP_USER}'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE ROLE ${APP_USER} LOGIN PASSWORD 'CHANGE_ME';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='meme_trader'" | grep -q 1 || \
  sudo -u postgres createdb -O "${APP_USER}" meme_trader
# pg_hba: keep postgres listening on localhost only (default on Ubuntu)

echo "==> Firewall (UFW)"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
# Dashboard is proxied by nginx over 443 (optional):
ufw allow "Nginx Full" 2>/dev/null || true
ufw --force enable

echo "==> systemd service"
cp deploy/meme-trader.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable meme-trader.service

echo "==> Logrotate"
cp deploy/logrotate.conf /etc/logrotate.d/meme-trader

echo "==> Backups (cron: daily 04:00)"
chmod +x deploy/backup_database.sh
cron_file="/etc/cron.d/meme-trader-backup"
echo "0 4 * * * ${APP_USER} ${APP_DIR}/deploy/backup_database.sh >> ${APP_DIR}/backups/backup.log 2>&1" > "${cron_file}"
chmod 644 "${cron_file}"

echo
echo "Setup complete. Remaining manual steps:"
echo "  1. Edit ${APP_DIR}/.env (WEB_UI_PASSWORD, WEB_UI_SECRET_KEY, DATABASE_URL password)"
echo "  2. Set the postgres password:  sudo -u postgres psql -c \"ALTER ROLE ${APP_USER} PASSWORD '...';\""
echo "  3. systemctl start meme-trader"
echo "  4. Optional HTTPS: certbot --nginx -d your-domain"
