"""Phase 5 integrity for the live queue.

The service checks these rules for friendly errors, but the constraints are the authority:
they hold under concurrent requests and even if application code is wrong.

- A patient has at most one live token per doctor per day (no double check-in / duplicate walk-in).
- A doctor has at most one patient CALLED or IN_CONSULTATION at a time.
- An appointment produces at most one token, and `source` must agree with `appointment_id`.

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# Must match app.permissions.roles.LIVE_TOKEN_STATUSES / ACTIVE_TOKEN_STATUSES.
LIVE = "'WAITING','CALLED','IN_CONSULTATION','SKIPPED'"
ACTIVE = "'CALLED','IN_CONSULTATION'"


def upgrade() -> None:
    op.execute(
        f"CREATE UNIQUE INDEX uq_queue_tokens_live_patient ON queue_tokens "
        f"(clinic_id, doctor_id, patient_id, queue_date) WHERE status IN ({LIVE})"
    )
    op.execute(
        f"CREATE UNIQUE INDEX uq_queue_tokens_one_active_per_doctor ON queue_tokens "
        f"(doctor_id) WHERE status IN ({ACTIVE})"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_queue_tokens_appointment ON queue_tokens (appointment_id) "
        "WHERE appointment_id IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE queue_tokens ADD CONSTRAINT ck_queue_tokens_source_matches_appointment "
        "CHECK ((source = 'APPOINTMENT') = (appointment_id IS NOT NULL))"
    )
    op.execute(
        "ALTER TABLE queue_tokens ADD CONSTRAINT ck_queue_tokens_priority_range "
        "CHECK (priority BETWEEN 0 AND 2)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE queue_tokens DROP CONSTRAINT IF EXISTS ck_queue_tokens_priority_range")
    op.execute("ALTER TABLE queue_tokens DROP CONSTRAINT IF EXISTS ck_queue_tokens_source_matches_appointment")
    op.execute("DROP INDEX IF EXISTS uq_queue_tokens_appointment")
    op.execute("DROP INDEX IF EXISTS uq_queue_tokens_one_active_per_doctor")
    op.execute("DROP INDEX IF EXISTS uq_queue_tokens_live_patient")
