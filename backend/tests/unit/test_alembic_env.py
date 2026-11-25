"""The migration environment explains a badly pasted database address instead of failing with a stack trace, and never prints it
(the address contains the database password). These run the real `alembic` command, so they need the backend's own dependencies."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SECRET = "SECRET-PW-123"


def _alembic_current(url: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("MIGRATION_DATABASE_URL", "DATABASE_URL")}
    env["MIGRATION_DATABASE_URL"] = url
    return subprocess.run(  # noqa: S603 - fixed argument list, no shell
        [sys.executable, "-m", "alembic", "current"],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120, check=False,
    )


def test_a_badly_pasted_address_gets_a_clear_message_and_is_not_printed():
    # "psycopg//" (one colon missing) is the kind of slip a dashboard paste produces.
    result = _alembic_current(f"postgresql+psycopg//user:{SECRET}@host/db")
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "MIGRATION_DATABASE_URL is not a valid database URL" in output
    assert "postgresql+psycopg://USER:PASSWORD@HOST/DBNAME" in output
    assert SECRET not in output


def test_text_that_is_not_an_address_at_all_gets_the_same_message():
    result = _alembic_current("not a url")
    assert result.returncode != 0
    assert "is not a valid database URL" in result.stdout + result.stderr


def test_quotes_and_spaces_around_a_good_address_are_ignored():
    # Nothing listens on port 1, so the command still fails, but at the connection step: the address itself was accepted.
    result = _alembic_current(' "postgresql+psycopg://user:pw@127.0.0.1:1/db?connect_timeout=3" ')
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "is not a valid database URL" not in output
    assert "Could not parse" not in output
