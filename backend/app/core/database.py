"""Database engine, sessions, and Row-Level Security (RLS) context.

Tenant context lives in transaction-local PostgreSQL settings (set_config(..., true)).
Because those settings reset at COMMIT/ROLLBACK, the context is stored on the Session
(`session.info`) and re-applied at the start of every transaction via an event hook.
Unset context => RLS policies return no rows (fail closed).
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Connection, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_RLS_KEY = "rls_context"

_APPLY_SQL = text(
    "SELECT set_config('app.current_clinic_id', :clinic_id, true), "
    "set_config('app.current_user_id', :user_id, true), "
    "set_config('app.is_platform', :platform, true)"
)


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    return create_engine(
        s.database_url,
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        pool_timeout=s.db_pool_timeout_seconds,
        pool_pre_ping=True,
        connect_args={"options": "-c statement_timeout=15000"},
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    # expire_on_commit=False: objects stay readable after the commits we perform mid-request.
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


def _context_params(ctx: dict[str, str]) -> dict[str, str]:
    return {
        "clinic_id": ctx.get("clinic_id", ""),
        "user_id": ctx.get("user_id", ""),
        "platform": ctx.get("platform", "off"),
    }


@event.listens_for(Session, "after_begin")
def _apply_rls_on_begin(session: Session, transaction: object, connection: Connection) -> None:
    ctx = session.info.get(_RLS_KEY)
    if ctx:
        connection.execute(_APPLY_SQL, _context_params(ctx))


def set_rls_context(
    db: Session,
    *,
    user_id: uuid.UUID | None = None,
    clinic_id: uuid.UUID | None = None,
    platform: bool = False,
) -> None:
    """Bind tenant/user context to this session for the current and all later transactions."""
    ctx = {
        "user_id": str(user_id) if user_id else "",
        "clinic_id": str(clinic_id) if clinic_id else "",
        "platform": "on" if platform else "off",
    }
    db.info[_RLS_KEY] = ctx
    db.execute(_APPLY_SQL, _context_params(ctx))  # apply to the transaction already open


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request; uncommitted work is rolled back on exit."""
    with get_sessionmaker()() as session:
        yield session


def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()
