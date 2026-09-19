#!/usr/bin/env bash
# Daily PostgreSQL backup with retention (7 daily, 4 weekly).
# Loads DATABASE_URL from /opt/meme-trader/.env. Never copies private keys.
set -euo pipefail

APP_DIR="/opt/meme-trader"
BACKUP_DIR="${APP_DIR}/backups"
ENV_FILE="${APP_DIR}/.env"

# shellcheck disable=SC1090
[ -f "$ENV_FILE" ] && export $(grep -E '^DATABASE_URL=' "$ENV_FILE" | xargs)

: "${DATABASE_URL:?DATABASE_URL not set in ${ENV_FILE}}"

mkdir -p "${BACKUP_DIR}/daily" "${BACKUP_DIR}/weekly"

STAMP="$(date +%Y%m%d_%H%M%S)"
DOW="$(date +%u)"  # 1=Monday ... 7=Sunday
OUT="${BACKUP_DIR}/daily/meme_trader_${STAMP}.sql.gz"

echo "[backup] dumping to ${OUT}"
pg_dump --no-owner --no-privileges "${DATABASE_URL}" | gzip > "${OUT}"

# Verify the dump is a valid gzip with actual content
if [ ! -s "${OUT}" ] || ! gzip -t "${OUT}" 2>/dev/null; then
  echo "[backup] ERROR: dump failed verification" >&2
  rm -f "${OUT}"
  exit 1
fi

# Weekly anchor: copy Sunday's dump into weekly/
if [ "${DOW}" = "7" ]; then
  cp "${OUT}" "${BACKUP_DIR}/weekly/meme_trader_week_${STAMP}.sql.gz"
fi

# Retention: 7 daily, 4 weekly
find "${BACKUP_DIR}/daily"  -name "meme_trader_*.sql.gz"       -mtime +7 -delete
find "${BACKUP_DIR}/weekly" -name "meme_trader_week_*.sql.gz"  -mtime +28 -delete

echo "[backup] done. current backups:"
ls -lh "${BACKUP_DIR}/daily" "${BACKUP_DIR}/weekly" 2>/dev/null || true
