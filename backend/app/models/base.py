"""Declarative base and shared column definitions.

Schema DDL is owned by Alembic migrations (hand-written for constraints SQLAlchemy cannot
express, such as the GiST exclusion constraint and RLS). These ORM models map onto it.
Models for later phases (appointments, queue, ...) are added as those features are built.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Model(Base):
    """Abstract parent: UUID primary key.

    eager_defaults=False avoids INSERT ... RETURNING for server defaults. With RLS,
    RETURNING is checked against SELECT policies, which can reject rows the caller may
    legitimately insert (e.g. append-only tables).
    """

    __abstract__ = True
    __mapper_args__ = {"eager_defaults": False}

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
