#!/usr/bin/env bash
# Logical backup of the QueueCare database (pg_dump custom format) into ./backups, then prunes old dumps.
# Usage: scripts/backup.sh [keep_days]   (default 14).  Run from cron on the host, e.g. daily at 02:30.
# A backup you have never restored is a hope, not a backup: run scripts/restore-check.sh regularly.
set -euo pipefail
cd "$(dirname "$0")/.."
keep_days="${1:-14}"
compose=(docker compose -f docker-compose.prod.yml --env-file .env.production)
mkdir -p backups && chmod 700 backups
"${compose[@]}" --profile ops run --rm backup
find backups -name 'queuecare-*.dump' -mtime +"$keep_days" -print -delete
echo "Done. Copy ./backups off this machine (another host or object storage); a backup on the same disk dies with it."
