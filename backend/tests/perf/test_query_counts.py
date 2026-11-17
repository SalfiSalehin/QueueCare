"""Performance guard rails that are deterministic: SQL statements per request must not grow with the amount of data
(no N+1 queries). Wall-clock timings are measured separately by scripts/perf_smoke.py, because timing asserts are
flaky on shared CI machines."""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import event

from app.core.database import get_engine
from tests.integration.test_appointments import setup_bookable
from tests.integration.test_queue import board, mk_patient, walk_in


@contextmanager
def count_statements():
    counter = {"n": 0}

    def hook(*_args, **_kw):
        counter["n"] += 1

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", hook)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", hook)


@pytest.fixture
def q(owner_engine):
    return setup_bookable(owner_engine, slug="alpha", link_doctor=True)


def statements_for(call) -> int:
    call()                                   # warm-up: first request may load caches
    with count_statements() as c:
        assert call().status_code == 200
    return c["n"]


def test_queue_board_statements_do_not_grow_with_queue_length(q):
    for i in range(3):
        assert walk_in(q, mk_patient(q, f"Few {i}")).status_code == 201
    small = statements_for(lambda: board(q))
    for i in range(12):
        assert walk_in(q, mk_patient(q, f"Many {i}")).status_code == 201
    large = statements_for(lambda: board(q))
    assert large <= small + 1, f"queue board went from {small} to {large} statements for 5x the tokens (N+1?)"


def test_analytics_statements_do_not_grow_with_data(q, owner_engine):
    from tests.integration.test_analytics import hours_ago, insert_visit, my_patient_id
    pid = my_patient_id(q)
    insert_visit(owner_engine, q, pid, hours_ago(5), 5, 10)
    url = f"{q.env.base}/analytics/overview"
    small = statements_for(lambda: q.env.admin.get(url))
    for i in range(25):
        insert_visit(owner_engine, q, pid, hours_ago(2 + (i % 4)), 5 + i, 10 + i)
    large = statements_for(lambda: q.env.admin.get(url))
    assert large == small, f"analytics statements changed with data volume: {small} -> {large}"
