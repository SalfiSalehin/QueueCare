"""Initial schema: all core tables, constraints, Row-Level Security, grants.

Design notes
- Enums are TEXT + CHECK (easier to evolve than PostgreSQL enum types).
- Every clinic-owned table has clinic_id. Cross-tenant references are blocked by
  composite foreign keys (clinic_id, x_id) -> parent(clinic_id, id).
- Double booking is prevented by a GiST EXCLUDE constraint on appointments.
- Row-Level Security fails CLOSED: with no tenant context set, tenant tables
  return zero rows to the application role.
- The application role cannot UPDATE/DELETE audit_logs or queue_token_events.

Revision ID: 0001
Revises:
"""
from __future__ import annotations

import os
import re

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_USER", "queuecare_app")
if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", APP_ROLE):
    raise RuntimeError("APP_DB_USER must be a plain lowercase identifier")

ACTIVE_APPT_STATUSES = "'PENDING','CONFIRMED','CHECKED_IN','IN_PROGRESS'"

# Tables carrying clinic_id with a plain tenant-isolation policy.
TENANT_TABLES = [
    "departments", "doctors", "doctor_schedules", "doctor_time_off", "patients",
    "appointments", "queue_counters", "queue_tokens", "queue_token_events",
    "consultations", "prediction_logs", "notifications", "outbox_events",
]

# Tables with an updated_at column (trigger keeps it correct for non-ORM writes).
UPDATED_AT_TABLES = [
    "clinics", "users", "clinic_memberships", "departments", "doctors", "doctor_schedules",
    "doctor_time_off", "patients", "appointments", "queue_counters", "queue_tokens",
    "consultations", "model_versions", "prediction_logs", "notifications", "sessions",
    "refresh_tokens", "one_time_tokens", "outbox_events",
]

TABLE_DDL = [
    # ---------------------------------------------------------------- clinics
    """
    CREATE TABLE clinics (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name text NOT NULL CHECK (length(name) BETWEEN 2 AND 200),
        slug citext NOT NULL UNIQUE CHECK (slug::text ~ '^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$'),
        timezone text NOT NULL DEFAULT 'UTC',
        status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','ACTIVE','SUSPENDED')),
        settings jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    # ------------------------------------------------------------------ users
    """
    CREATE TABLE users (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        email citext NOT NULL UNIQUE,
        password_hash text NOT NULL,
        full_name text NOT NULL CHECK (length(full_name) BETWEEN 1 AND 200),
        phone text,
        platform_role text NOT NULL DEFAULT 'NONE' CHECK (platform_role IN ('NONE','SUPER_ADMIN')),
        email_verified boolean NOT NULL DEFAULT false,
        is_active boolean NOT NULL DEFAULT true,
        failed_login_count integer NOT NULL DEFAULT 0,
        locked_until timestamptz,
        last_login_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    # ---------------------------------------------------- clinic_memberships
    """
    CREATE TABLE clinic_memberships (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE RESTRICT,
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        role text NOT NULL CHECK (role IN ('CLINIC_ADMIN','RECEPTIONIST','DOCTOR','PATIENT')),
        is_active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (clinic_id, user_id, role)
    )
    """,
    # ------------------------------------------------------------ departments
    """
    CREATE TABLE departments (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE RESTRICT,
        name text NOT NULL,
        queue_prefix text NOT NULL CHECK (queue_prefix ~ '^[A-Z]{1,3}$'),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (clinic_id, id),
        UNIQUE (clinic_id, name),
        UNIQUE (clinic_id, queue_prefix)
    )
    """,
    # ---------------------------------------------------------------- doctors
    """
    CREATE TABLE doctors (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE RESTRICT,
        department_id uuid NOT NULL,
        user_id uuid REFERENCES users(id) ON DELETE RESTRICT,
        display_name text NOT NULL,
        default_slot_minutes integer NOT NULL DEFAULT 15 CHECK (default_slot_minutes BETWEEN 5 AND 240),
        buffer_minutes integer NOT NULL DEFAULT 5 CHECK (buffer_minutes BETWEEN 0 AND 120),
        status text NOT NULL DEFAULT 'AVAILABLE' CHECK (status IN ('AVAILABLE','BUSY','DELAYED','OFF_DUTY')),
        current_delay_minutes integer NOT NULL DEFAULT 0 CHECK (current_delay_minutes >= 0),
        is_active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (clinic_id, id),
        FOREIGN KEY (clinic_id, department_id) REFERENCES departments (clinic_id, id) ON DELETE RESTRICT
    )
    """,
    # ------------------------------------------------------- doctor_schedules
    """
    CREATE TABLE doctor_schedules (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE RESTRICT,
        doctor_id uuid NOT NULL,
        day_of_week smallint NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
        start_time time NOT NULL,
        end_time time NOT NULL,
        valid_from date,
        valid_to date,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CHECK (end_time > start_time),
        CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
        FOREIGN KEY (clinic_id, doctor_id) REFERENCES doctors (clinic_id, id) ON DELETE CASCADE
    )
    """,
    # --------------------------------------------------------- doctor_time_off
    """
    CREATE TABLE doctor_time_off (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE RESTRICT,
        doctor_id uuid NOT NULL,
        period tstzrange NOT NULL CHECK (NOT isempty(period)),
        reason text,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY (clinic_id, doctor_id) REFERENCES doctors (clinic_id, id) ON DELETE CASCADE
    )
    """,
    # --------------------------------------------------------------- patients
    """
    CREATE TABLE patients (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE RESTRICT,
        user_id uuid REFERENCES users(id) ON DELETE RESTRICT,
        full_name text NOT NULL,
        phone text,
        date_of_birth date,
        is_synthetic boolean NOT NULL DEFAULT true,
        deleted_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (clinic_id, id)
    )
    """,
    # ----------------------------------------------------------- appointments
    f"""
    CREATE TABLE appointments (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE RESTRICT,
        doctor_id uuid NOT NULL,
        patient_id uuid NOT NULL,
        starts_at timestamptz NOT NULL,
        ends_at timestamptz NOT NULL,
        status text NOT NULL DEFAULT 'PENDING' CHECK (status IN
            ('PENDING','CONFIRMED','CHECKED_IN','IN_PROGRESS','COMPLETED','CANCELLED','NO_SHOW')),
        rescheduled_from uuid,
        cancel_reason text,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CHECK (ends_at > starts_at),
        UNIQUE (clinic_id, id),
        FOREIGN KEY (clinic_id, doctor_id) REFERENCES doctors (clinic_id, id) ON DELETE RESTRICT,
        FOREIGN KEY (clinic_id, patient_id) REFERENCES patients (clinic_id, id) ON DELETE RESTRICT,
        FOREIGN KEY (clinic_id, rescheduled_from) REFERENCES appointments (clinic_id, id) ON DELETE RESTRICT,
        CONSTRAINT appointments_no_doctor_overlap EXCLUDE USING gist (
            doctor_id WITH =,
            tstzrange(starts_at, ends_at, '[)') WITH &&
        ) WHERE (status IN ({ACTIVE_APPT_STATUSES}))
    )
    """,
    # --------------------------------------------------------- queue_counters
    """
    CREATE TABLE queue_counters (
        clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE RESTRICT,
        queue_date date NOT NULL,
        prefix text NOT NULL,
        last_sequence integer NOT NULL DEFAULT 0 CHECK (last_sequence >= 0),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (clinic_id, queue_date, prefix)
    )
    """,
    # ----------------------------------------------------------- queue_tokens
    """
    CREATE TABLE queue_tokens (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE RESTRICT,
        doctor_id uuid NOT NULL,
        patient_id uuid NOT NULL,
        appointment_id uuid,
        queue_date date NOT NULL,
        prefix text NOT NULL,
        sequence_no integer NOT NULL CHECK (sequence_no > 0),
        token_label text NOT NULL,
        source text NOT NULL CHECK (source IN ('WALK_IN','APPOINTMENT')),
        status text NOT NULL DEFAULT 'WAITING' CHECK (status IN
            ('WAITING','CALLED','IN_CONSULTATION','COMPLETED','SKIPPED','CANCELLED','NO_SHOW')),
        priority integer NOT NULL DEFAULT 0,
        arrived_at timestamptz NOT NULL DEFAULT now(),
        called_at timestamptz,
        started_at timestamptz,
        completed_at timestamptz,
        version bigint NOT NULL DEFAULT 1,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (clinic_id, id),
        UNIQUE (clinic_id, queue_date, prefix, sequence_no),
        FOREIGN KEY (clinic_id, doctor_id) REFERENCES doctors (clinic_id, id) ON DELETE RESTRICT,
        FOREIGN KEY (clinic_id, patient_id) REFERENCES patients (clinic_id, id) ON DELETE RESTRICT,
        FOREIGN KEY (clinic_id, appointment_id) REFERENCES appointments (clinic_id, id) ON DELETE RESTRICT
    )
    """,
    # ------------------------------------------------------ queue_token_events
    """
    CREATE TABLE queue_token_events (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE RESTRICT,
        token_id uuid NOT NULL,
        actor_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
        from_status text,
        to_status text NOT NULL,
        reason text,
        created_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY (clinic_id, token_id) REFERENCES queue_tokens (clinic_id, id) ON DELETE CASCADE
    )
    """,
    # ---------------------------------------------------------- consultations
    """
    CREATE TABLE consultations (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE RESTRICT,
        token_id uuid NOT NULL,
        doctor_id uuid NOT NULL,
        started_at timestamptz NOT NULL,
        ended_at timestamptz,
        duration_minutes integer CHECK (duration_minutes IS NULL OR duration_minutes >= 0),
        actual_wait_minutes integer CHECK (actual_wait_minutes IS NULL OR actual_wait_minutes >= 0),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (token_id),
        CHECK (ended_at IS NULL OR ended_at >= started_at),
        FOREIGN KEY (clinic_id, token_id) REFERENCES queue_tokens (clinic_id, id) ON DELETE RESTRICT,
        FOREIGN KEY (clinic_id, doctor_id) REFERENCES doctors (clinic_id, id) ON DELETE RESTRICT
    )
    """,
    # --------------------------------------------------------- model_versions
    """
    CREATE TABLE model_versions (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        version text NOT NULL UNIQUE,
        algorithm text NOT NULL,
        metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
        feature_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
        artifact_ref text NOT NULL,
        is_active boolean NOT NULL DEFAULT false,
        trained_at timestamptz NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE UNIQUE INDEX uq_model_versions_single_active ON model_versions (is_active) WHERE is_active",
    # -------------------------------------------------------- prediction_logs
    """
    CREATE TABLE prediction_logs (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE RESTRICT,
        token_id uuid,
        model_version_id uuid NOT NULL REFERENCES model_versions(id) ON DELETE RESTRICT,
        pred_lower double precision NOT NULL,
        pred_median double precision NOT NULL,
        pred_upper double precision NOT NULL,
        actual_wait double precision,
        abs_error double precision,
        latency_ms integer,
        feature_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
        predicted_at timestamptz NOT NULL DEFAULT now(),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CHECK (pred_lower >= 0 AND pred_lower <= pred_median AND pred_median <= pred_upper),
        FOREIGN KEY (clinic_id, token_id) REFERENCES queue_tokens (clinic_id, id) ON DELETE SET NULL (token_id)
    )
    """,
    # ---------------------------------------------------------- notifications
    """
    CREATE TABLE notifications (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE RESTRICT,
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        channel text NOT NULL CHECK (channel IN ('EMAIL','SMS','IN_APP')),
        type text NOT NULL,
        status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','SENT','FAILED','READ')),
        attempts integer NOT NULL DEFAULT 0,
        idempotency_key text NOT NULL UNIQUE,
        payload jsonb NOT NULL DEFAULT '{}'::jsonb,
        next_attempt_at timestamptz,
        last_error text,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    # ------------------------------------------------------------- audit_logs
    # Append-only: no updated_at, and the app role gets no UPDATE/DELETE.
    """
    CREATE TABLE audit_logs (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        clinic_id uuid REFERENCES clinics(id) ON DELETE RESTRICT,
        actor_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
        action text NOT NULL,
        entity_type text,
        entity_id uuid,
        metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
        ip inet,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    # --------------------------------------------------------------- sessions
    """
    CREATE TABLE sessions (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        user_agent text,
        ip inet,
        last_seen_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL,
        revoked_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    # ---------------------------------------------------------- refresh_tokens
    """
    CREATE TABLE refresh_tokens (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        session_id uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        family_id uuid NOT NULL,
        token_hash text NOT NULL UNIQUE,
        expires_at timestamptz NOT NULL,
        used_at timestamptz,
        revoked_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    # --------------------------------------------------------- one_time_tokens
    """
    CREATE TABLE one_time_tokens (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        purpose text NOT NULL CHECK (purpose IN ('PASSWORD_RESET','EMAIL_VERIFY')),
        token_hash text NOT NULL UNIQUE,
        expires_at timestamptz NOT NULL,
        used_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    # ----------------------------------------------------------- outbox_events
    "CREATE SEQUENCE outbox_version_seq",
    """
    CREATE TABLE outbox_events (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE RESTRICT,
        channel text NOT NULL,
        event_type text NOT NULL,
        payload jsonb NOT NULL DEFAULT '{}'::jsonb,
        version bigint NOT NULL DEFAULT nextval('outbox_version_seq'),
        published_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
]

INDEX_DDL = [
    "CREATE INDEX ix_memberships_user ON clinic_memberships (user_id)",
    "CREATE INDEX ix_memberships_clinic ON clinic_memberships (clinic_id)",
    "CREATE INDEX ix_doctors_clinic ON doctors (clinic_id, department_id)",
    "CREATE INDEX ix_doctor_schedules_doctor ON doctor_schedules (clinic_id, doctor_id, day_of_week)",
    "CREATE INDEX ix_doctor_time_off_doctor ON doctor_time_off USING gist (doctor_id, period)",
    "CREATE INDEX ix_patients_clinic_phone ON patients (clinic_id, phone)",
    "CREATE INDEX ix_patients_clinic_name ON patients (clinic_id, lower(full_name))",
    "CREATE UNIQUE INDEX uq_patients_clinic_user ON patients (clinic_id, user_id) "
    "WHERE user_id IS NOT NULL AND deleted_at IS NULL",
    "CREATE INDEX ix_appointments_doctor_start ON appointments (clinic_id, doctor_id, starts_at)",
    "CREATE INDEX ix_appointments_status_start ON appointments (clinic_id, status, starts_at)",
    "CREATE INDEX ix_appointments_patient ON appointments (clinic_id, patient_id)",
    "CREATE INDEX ix_queue_tokens_queue ON queue_tokens (clinic_id, doctor_id, queue_date, status)",
    "CREATE INDEX ix_queue_tokens_patient ON queue_tokens (clinic_id, patient_id)",
    "CREATE INDEX ix_queue_token_events_token ON queue_token_events (clinic_id, token_id, created_at)",
    "CREATE INDEX ix_prediction_logs_clinic_time ON prediction_logs (clinic_id, predicted_at)",
    "CREATE INDEX ix_notifications_status ON notifications (status, next_attempt_at)",
    "CREATE INDEX ix_notifications_user ON notifications (clinic_id, user_id, created_at)",
    "CREATE INDEX ix_audit_logs_clinic_time ON audit_logs (clinic_id, created_at)",
    "CREATE INDEX ix_audit_logs_actor ON audit_logs (actor_user_id, created_at)",
    "CREATE INDEX ix_sessions_user ON sessions (user_id) WHERE revoked_at IS NULL",
    "CREATE INDEX ix_refresh_tokens_session ON refresh_tokens (session_id)",
    "CREATE INDEX ix_refresh_tokens_family ON refresh_tokens (family_id)",
    "CREATE INDEX ix_one_time_tokens_user ON one_time_tokens (user_id, purpose)",
    "CREATE INDEX ix_outbox_unpublished ON outbox_events (version) WHERE published_at IS NULL",
]

FUNCTION_DDL = [
    """
    CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END;
    $$
    """,
    # Tenant context helpers. current_setting(..., true) returns NULL when unset,
    # so unset context => comparisons are NULL => no rows (fail closed).
    """
    CREATE FUNCTION app_clinic_id() RETURNS uuid LANGUAGE sql STABLE AS $$
        SELECT nullif(current_setting('app.current_clinic_id', true), '')::uuid
    $$
    """,
    """
    CREATE FUNCTION app_user_id() RETURNS uuid LANGUAGE sql STABLE AS $$
        SELECT nullif(current_setting('app.current_user_id', true), '')::uuid
    $$
    """,
    """
    CREATE FUNCTION app_is_platform() RETURNS boolean LANGUAGE sql STABLE AS $$
        SELECT coalesce(current_setting('app.is_platform', true), 'off') = 'on'
    $$
    """,
]

DROP_ORDER = [
    "outbox_events", "one_time_tokens", "refresh_tokens", "sessions", "audit_logs", "notifications",
    "prediction_logs", "model_versions", "consultations", "queue_token_events", "queue_tokens",
    "queue_counters", "appointments", "patients", "doctor_time_off", "doctor_schedules", "doctors",
    "departments", "clinic_memberships", "users", "clinics",
]


def upgrade() -> None:
    for ext in ("btree_gist", "citext", "pgcrypto"):
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")

    for stmt in FUNCTION_DDL:
        op.execute(stmt)
    for stmt in TABLE_DDL:
        op.execute(stmt)
    for stmt in INDEX_DDL:
        op.execute(stmt)

    for table in UPDATED_AT_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )

    # ---- Row-Level Security -------------------------------------------------
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (clinic_id = app_clinic_id() OR app_is_platform())"
        )

    # A user can always see their own memberships (needed to resolve access);
    # staff see memberships of the clinic in context.
    op.execute("ALTER TABLE clinic_memberships ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY membership_access ON clinic_memberships "
        "USING (clinic_id = app_clinic_id() OR user_id = app_user_id() OR app_is_platform())"
    )

    # Audit log: anyone may append (including failed logins with no identity),
    # but reads are limited to the clinic in context, the actor, or platform admins.
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY audit_read ON audit_logs FOR SELECT "
        "USING (app_is_platform() OR clinic_id = app_clinic_id() OR actor_user_id = app_user_id())"
    )
    op.execute("CREATE POLICY audit_insert ON audit_logs FOR INSERT WITH CHECK (true)")

    # ---- Grants to the least-privilege application role --------------------
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                RAISE EXCEPTION 'Application role {APP_ROLE} does not exist';
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE "
        f"ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )
    # Immutability of audit trails for the application role.
    op.execute(f"REVOKE UPDATE, DELETE ON audit_logs, queue_token_events FROM {APP_ROLE}")


def downgrade() -> None:
    for table in DROP_ORDER:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP SEQUENCE IF EXISTS outbox_version_seq")
    for fn in ("app_is_platform()", "app_user_id()", "app_clinic_id()", "set_updated_at()"):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")
