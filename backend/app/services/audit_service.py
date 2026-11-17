"""Audit logging. Append-only; uses a Core INSERT with no RETURNING (see models.base)."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models import AuditLog


def record_audit(
    db: Session,
    *,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    clinic_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    ip: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Queue an audit row in the caller's transaction (commit is the caller's job).

    Never pass secrets, tokens, passwords or raw emails in `metadata`.
    """
    db.execute(
        insert(AuditLog).values(
            id=uuid.uuid4(),
            action=action,
            actor_user_id=actor_user_id,
            clinic_id=clinic_id,
            entity_type=entity_type,
            entity_id=entity_id,
            ip=ip,
            metadata_=metadata or {},
        )
    )
