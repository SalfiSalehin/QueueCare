"""Per-user throttles on authenticated endpoints (app/api/limits.py)."""
from __future__ import annotations

from tests.conftest import new_client
from tests.integration.test_appointments import setup_bookable
from tests.integration.test_clinic_management import post


def simulate(b, client=None):
    return post(client or b.env.admin, f"{b.env.base}/simulation", {"scenarios": [{"days": 5}]})


def test_simulation_is_throttled_per_user_with_retry_after(owner_engine):
    b = setup_bookable(owner_engine, slug="alpha")
    codes = [simulate(b).status_code for _ in range(12)]
    assert codes[:10] == [200] * 10 and codes[10:] == [429, 429]
    limited = simulate(b)
    assert limited.json()["error"]["code"] and int(limited.headers["Retry-After"]) >= 1


def test_one_users_budget_does_not_throttle_another(owner_engine):
    b = setup_bookable(owner_engine, slug="alpha")
    for _ in range(11):
        simulate(b)
    assert simulate(b).status_code == 429
    assert b.env.doctor.get(f"{b.env.base}/doctors").status_code == 200       # another user is untouched
    assert b.env.patient.get(f"{b.env.base}/queue/mine").status_code == 200


def test_anonymous_calls_cannot_spend_a_users_budget(owner_engine):
    b = setup_bookable(owner_engine, slug="alpha")
    for _ in range(15):
        assert simulate(b, new_client()).status_code in (401, 403)
    assert simulate(b).status_code == 200


def test_limits_are_generous_for_normal_use(owner_engine):
    b = setup_bookable(owner_engine, slug="alpha")
    for _ in range(30):
        assert b.env.admin.get(f"{b.env.base}/analytics/overview").status_code == 200
