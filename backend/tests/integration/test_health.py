"""Health endpoints. Readiness once reported "degraded" on a healthy system (it compared an unset response status)."""
from __future__ import annotations

from app.api import health


def test_live(client):
    r = client.get("/health/live")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_ready_reports_ok_when_the_database_answers(client):
    r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["redis"] in {"ok", "disabled"}


def test_ready_reports_degraded_with_503_when_the_database_is_down(client, monkeypatch):
    def broken():
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(health, "get_engine", broken)
    r = client.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded" and r.json()["database"] == "unavailable"
    assert "unreachable" not in r.text          # no internal error detail leaks
