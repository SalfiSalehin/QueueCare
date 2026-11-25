"""Alembic environment.

Migrations run as the OWNER role (MIGRATION_DATABASE_URL). The application itself
connects as a least-privilege role that is subject to Row-Level Security.
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_name = "MIGRATION_DATABASE_URL" if os.environ.get("MIGRATION_DATABASE_URL") else "DATABASE_URL"
# Values pasted into a hosting dashboard often carry a stray space, line break or pair of quotes; those are removed here.
_url = (os.environ.get(_name) or "").strip().strip("\"'").strip()
if not _url:
    raise RuntimeError("Set MIGRATION_DATABASE_URL (or DATABASE_URL) to run migrations.")
try:
    make_url(_url)
except ArgumentError:
    # The value itself is never printed: it contains the database password.
    raise RuntimeError(
        f"{_name} is not a valid database URL. Expected postgresql+psycopg://USER:PASSWORD@HOST/DBNAME?sslmode=require "
        "(no spaces, no line breaks, no quotation marks). Check the value in the hosting dashboard."
    ) from None
config.set_main_option("sqlalchemy.url", _url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
