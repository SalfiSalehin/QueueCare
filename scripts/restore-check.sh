#!/usr/bin/env bash
# Restore drill: restores a dump into a THROW-AWAY database and compares row counts. Never touches the live database.
# Usage: scripts/restore-check.sh backups/queuecare-YYYYMMDDTHHMMSSZ.dump
set -euo pipefail
cd "$(dirname "$0")/.."
dump="${1:?usage: restore-check.sh <dump file>}"
[ -f "$dump" ] || { echo "No such file: $dump" >&2; exit 1; }
set -a; . ./.env.production; set +a
compose=(docker compose -f docker-compose.prod.yml --env-file .env.production)
scratch="restore_check_$$"
psql_owner() { "${compose[@]}" exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$@"; }

psql_owner -d postgres -c "CREATE DATABASE $scratch"
trap 'psql_owner -d postgres -c "DROP DATABASE IF EXISTS $scratch WITH (FORCE)" >/dev/null' EXIT
"${compose[@]}" exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
  pg_restore -U "$POSTGRES_USER" -d "$scratch" --no-owner --exit-on-error < "$dump"

q="SELECT 'clinics', count(*) FROM clinics UNION ALL SELECT 'users', count(*) FROM users UNION ALL SELECT 'appointments', count(*) FROM appointments UNION ALL SELECT 'queue_tokens', count(*) FROM queue_tokens"
echo "== restored copy =="; psql_owner -d "$scratch" -c "$q"
echo "== live database =="; psql_owner -d "$POSTGRES_DB" -c "$q"
echo "Row counts can differ by whatever changed since the dump. The restore itself succeeded if no error appeared above."
