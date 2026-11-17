#!/bin/sh
# Runs once on first database initialisation.
# Creates the least-privilege runtime role used by the API.
# The owner role (POSTGRES_USER) runs migrations; the app role cannot bypass
# Row-Level Security and does not own tables, so RLS policies always apply to it.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  CREATE EXTENSION IF NOT EXISTS btree_gist;
  CREATE EXTENSION IF NOT EXISTS citext;
  CREATE EXTENSION IF NOT EXISTS pgcrypto;

  DO \$\$
  BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${APP_DB_USER}') THEN
      CREATE ROLE ${APP_DB_USER} LOGIN PASSWORD '${APP_DB_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
  END
  \$\$;

  GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${APP_DB_USER};
  GRANT USAGE ON SCHEMA public TO ${APP_DB_USER};
  ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${APP_DB_USER};
  ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO ${APP_DB_USER};
EOSQL
