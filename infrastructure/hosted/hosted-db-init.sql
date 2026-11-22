-- One-time setup of a hosted PostgreSQL database (Neon) for QueueCare. Run it ONCE, as the database's owner role, BEFORE the first deploy:
-- the first migration refuses to run unless the restricted application role already exists.
-- It does the same job as infrastructure/docker/postgres-init.sh does for the local Docker database.
--
--   Get-Content -Raw infrastructure\hosted\hosted-db-init.sql | docker compose exec -T postgres psql "<OWNER URL>" -v app_password=<APP PASSWORD>
--
-- <OWNER URL> is the plain postgresql://... address (not the +psycopg one). <APP PASSWORD> is a new random value that you also put in
-- DATABASE_URL on Render; use letters and digits only so it needs no escaping. Nothing secret is stored in this file.
\set ON_ERROR_STOP on

CREATE EXTENSION IF NOT EXISTS btree_gist;   -- the no-double-booking constraint
CREATE EXTENSION IF NOT EXISTS citext;       -- case-insensitive email and slug columns
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- The runtime role: it can log in but cannot own tables, bypass row-level security, create roles or databases.
SELECT format('CREATE ROLE queuecare_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'queuecare_app')
\gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO queuecare_app', current_database())
\gexec
GRANT USAGE ON SCHEMA public TO queuecare_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO queuecare_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO queuecare_app;

-- Check: expect one row, with rolsuper, rolcreaterole and rolbypassrls all false (f).
SELECT rolname, rolsuper, rolcreaterole, rolbypassrls FROM pg_roles WHERE rolname = 'queuecare_app';
