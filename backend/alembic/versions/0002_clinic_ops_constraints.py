"""Phase 3 integrity: one doctor profile per account per clinic, no overlapping schedule windows.

Both rules are also checked in the service for friendly errors, but these constraints are the
authority: they hold under concurrent requests and even if application code is wrong.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_doctors_clinic_user ON doctors (clinic_id, user_id) WHERE user_id IS NOT NULL"
    )
    # Same weekday + overlapping wall-clock window + overlapping validity dates => rejected.
    # NULL date bounds mean open-ended. Windows are half-open, so 09:00-12:00 and 12:00-15:00 may touch.
    op.execute(
        """
        ALTER TABLE doctor_schedules ADD CONSTRAINT doctor_schedules_no_overlap EXCLUDE USING gist (
            doctor_id WITH =,
            day_of_week WITH =,
            tsrange(date '2000-01-01' + start_time, date '2000-01-01' + end_time, '[)') WITH &&,
            daterange(valid_from, valid_to, '[]') WITH &&
        )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE doctor_schedules DROP CONSTRAINT IF EXISTS doctor_schedules_no_overlap")
    op.execute("DROP INDEX IF EXISTS uq_doctors_clinic_user")
