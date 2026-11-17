"""The shipped production template must itself satisfy the production safety checks once secrets are filled,
and must not ship real-looking secrets or unsafe defaults."""
from __future__ import annotations

import re
import secrets
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

TEMPLATE = Path(__file__).resolve().parents[3] / ".env.production.example"
# Deliberately no skip: a silently skipped safety test is worse than a failing one. docker-compose.yml mounts the file.


def parse(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        line = line.split("  #")[0].strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def filled() -> dict[str, str]:
    """Template with every CHANGE_ME replaced by a distinct random value, as scripts/generate-secrets.sh does."""
    env = parse(TEMPLATE.read_text())
    values = {name: secrets.token_hex(24) for name in
              ("OWNER_PASSWORD", "APP_PASSWORD", "REDIS_PASSWORD", "64_BYTE_RANDOM_SECRET", "CSRF_SECRET")}
    return {k: re.sub(r"CHANGE_ME_(\w+)", lambda m: values[m.group(1)], v) for k, v in env.items()}


def build(monkeypatch, env: dict[str, str]) -> Settings:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)


def test_template_with_secrets_filled_passes_the_production_validator(monkeypatch):
    s = build(monkeypatch, filled())
    assert s.is_production and s.cookie_secure and not s.debug
    assert all(o.startswith("https://") for o in s.cors_origins)
    assert s.email_provider == "mock"


def test_template_contains_only_placeholders_for_secrets():
    raw = parse(TEMPLATE.read_text())
    for key in ("POSTGRES_PASSWORD", "APP_DB_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET", "CSRF_SECRET"):
        assert raw[key].startswith("CHANGE_ME"), key


@pytest.mark.parametrize("override", [
    {"COOKIE_SECURE": "false"},
    {"DEBUG": "true"},
    {"BACKEND_CORS_ORIGINS": "http://queuecare.example.com"},
    {"BACKEND_CORS_ORIGINS": "*"},
    {"JWT_SECRET": "short"},
])
def test_production_refuses_unsafe_settings(monkeypatch, override):
    with pytest.raises(ValidationError):
        build(monkeypatch, {**filled(), **override})


def test_unfilled_template_is_rejected(monkeypatch):
    with pytest.raises(ValidationError):
        build(monkeypatch, parse(TEMPLATE.read_text()))
