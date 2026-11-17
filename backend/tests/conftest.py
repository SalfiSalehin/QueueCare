"""Test harness.

Runs against a REAL PostgreSQL database named `queuecare_test` (created fresh per session by
the owner role and migrated with Alembic). The application connects as the least-privilege
role so Row-Level Security is genuinely exercised. Nothing here touches the dev database.

Requires DATABASE_URL and MIGRATION_DATABASE_URL in the environment (the Docker backend
container has them from .env). Set TEST_DB_HOST to override the host when running outside Docker.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

TEST_DB = "queuecare_test"
ORIGINAL_REDIS_URL = os.environ.get("REDIS_URL")   # kept for the optional Redis tests; the suite itself uses memory
ROOT = Path(__file__).resolve().parents[1]


def _test_url(env_name: str) -> URL:
    raw = os.environ.get(env_name)
    if not raw:
        pytest.exit(f"{env_name} is not set. Run tests inside the backend container: "
                    "docker compose run --rm backend pytest", returncode=2)
    url = make_url(raw).set(database=TEST_DB)
    if os.environ.get("TEST_DB_HOST"):
        url = url.set(host=os.environ["TEST_DB_HOST"])
    return url


APP_URL = _test_url("DATABASE_URL")
OWNER_URL = _test_url("MIGRATION_DATABASE_URL")

# Configure the app BEFORE any `app.*` import (settings are cached on first use).
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": APP_URL.render_as_string(hide_password=False),
    "MIGRATION_DATABASE_URL": OWNER_URL.render_as_string(hide_password=False),
    "JWT_SECRET": "test-jwt-secret-" + "a" * 40,
    "CSRF_SECRET": "test-csrf-secret-" + "b" * 40,
    "REDIS_URL": "",
    "RATE_LIMIT_BACKEND": "memory",
    "RATE_LIMIT_ENABLED": "true",
    "REFRESH_REUSE_GRACE_SECONDS": "0",
    "COOKIE_SECURE": "false",
    "BACKEND_CORS_ORIGINS": "http://localhost:3000",
    "MAX_REQUEST_BODY_BYTES": "100000",
    "LOG_LEVEL": "WARNING",
    "OUTBOX_RELAY_ENABLED": "false",      # tests drive the relay explicitly, so timing is deterministic
    "NOTIFICATION_WORKER_ENABLED": "false",   # tests drive the notification worker explicitly
    "ML_MODEL_DIR": "/nonexistent/queuecare-models",   # other tests never depend on a locally trained model
})

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.ratelimit import get_rate_limiter  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import User  # noqa: E402
from app.services.email import get_email_provider  # noqa: E402

PASSWORD = "Correct-Horse-Battery-9"


def _owner_engine(database: str = TEST_DB):
    return create_engine(OWNER_URL.set(database=database), isolation_level="AUTOCOMMIT")


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    from alembic import command
    from alembic.config import Config

    admin = _owner_engine("postgres")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    admin.dispose()

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean_state() -> Iterator[None]:
    """Empty every table and reset in-memory state before each test."""
    engine = _owner_engine()
    with engine.connect() as conn:
        tables = [r[0] for r in conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'"))]
        conn.execute(text("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"))
    engine.dispose()
    get_rate_limiter.cache_clear()
    get_email_provider().outbox.clear()  # type: ignore[attr-defined]
    yield


@pytest.fixture
def owner_engine():
    engine = _owner_engine()
    yield engine
    engine.dispose()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(get_settings()), base_url="http://localhost") as c:
        yield c


def new_client() -> TestClient:
    """A second, independent browser (separate cookie jar)."""
    return TestClient(create_app(get_settings()), base_url="http://localhost")


def csrf(c: TestClient) -> dict[str, str]:
    token = c.cookies.get("qc_csrf")
    return {"X-CSRF-Token": token} if token else {}


def register(c: TestClient, email: str, password: str = PASSWORD, name: str = "Synthetic User"):
    return c.post("/api/v1/auth/register", json={"email": email, "password": password, "full_name": name})


def login(c: TestClient, email: str, password: str = PASSWORD):
    return c.post("/api/v1/auth/login", json={"email": email, "password": password})


def signup(c: TestClient, email: str, password: str = PASSWORD) -> TestClient:
    assert register(c, email, password).status_code == 201
    assert login(c, email, password).status_code == 200
    return c


def make_superadmin(owner_engine, email: str = "root@example.com") -> str:
    from sqlalchemy.orm import Session

    with Session(owner_engine) as db:
        db.add(User(email=email, password_hash=hash_password(PASSWORD), full_name="Root",
                    platform_role="SUPER_ADMIN", email_verified=True))
        db.commit()
    return email


def reset_token_from_outbox(kind: str) -> str:
    for msg in reversed(list(get_email_provider().outbox)):  # type: ignore[attr-defined]
        if msg.kind == kind:
            match = re.search(r"token=([A-Za-z0-9_\-]+)", msg.body)
            assert match
            return match.group(1)
    raise AssertionError(f"no {kind} email sent")


def create_active_clinic(owner_engine, admin_client: TestClient, slug: str, name: str = "Test Clinic") -> str:
    """Admin registers a clinic via the API; a super admin approves it. Returns the clinic id."""
    r = admin_client.post("/api/v1/clinics", json={"name": name, "slug": slug}, headers=csrf(admin_client))
    assert r.status_code == 201, r.text
    clinic_id = r.json()["id"]
    email = make_superadmin(owner_engine, f"root-{slug}@example.com")
    root = new_client()
    assert login(root, email).status_code == 200
    r = root.post(f"/api/v1/platform/clinics/{clinic_id}/status", json={"status": "ACTIVE"}, headers=csrf(root))
    assert r.status_code == 200, r.text
    return clinic_id


@pytest.fixture(scope="session")
def quick_model_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    pytest.importorskip("lightgbm")
    pytest.importorskip("pandas")
    pytest.importorskip("sklearn")
    from ml.training.run import run_pipeline

    root = tmp_path_factory.mktemp("ml-models")
    run_pipeline(seed=7, out_root=root, quick=True, promote=True, work_dir=tmp_path_factory.mktemp("ml-data"))
    return root
