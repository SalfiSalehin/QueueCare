"""Phase 6 core pieces with no database and no web framework: channels, hub, in-memory broker, tickets."""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid

import jwt
import pytest

from app.permissions.roles import ClinicRole
from app.websocket.broker import MemoryBroker
from app.websocket.channels import belongs_to_clinic, channels_for, doctor_channel, staff_channel, user_channel
from app.websocket.hub import CLOSE_TRY_AGAIN, Hub, HubLimitError
from app.websocket.tickets import (
    MemoryTicketStore, TicketError, issue_ticket, verify_ticket,
)

CID, OTHER_CID = uuid.uuid4(), uuid.uuid4()
UID, DID = uuid.uuid4(), uuid.uuid4()
SECRET = "unit-test-secret-" + "x" * 32


# --------------------------------------------------------------------- channels
def test_channels_per_role():
    kw = {"clinic_id": CID, "user_id": UID, "doctor_id": DID}
    assert channels_for(ClinicRole.PATIENT, **kw) == {user_channel(CID, UID)}
    assert channels_for(ClinicRole.DOCTOR, **kw) == {user_channel(CID, UID), doctor_channel(CID, DID)}
    for role in (ClinicRole.CLINIC_ADMIN, ClinicRole.RECEPTIONIST):
        assert channels_for(role, **kw) == {user_channel(CID, UID), staff_channel(CID)}


def test_doctor_without_profile_gets_only_personal_channel_and_patients_never_staff():
    assert channels_for(ClinicRole.DOCTOR, clinic_id=CID, user_id=UID) == {user_channel(CID, UID)}
    assert staff_channel(CID) not in channels_for(ClinicRole.PATIENT, clinic_id=CID, user_id=UID, doctor_id=DID)


def test_every_channel_is_clinic_scoped():
    for ch in channels_for(ClinicRole.CLINIC_ADMIN, clinic_id=CID, user_id=UID):
        assert belongs_to_clinic(ch, CID) and not belongs_to_clinic(ch, OTHER_CID)


# -------------------------------------------------------------------------- hub
def test_hub_delivers_only_to_subscribed_channels_and_stops_after_unregister():
    async def run():
        hub = Hub()
        a = hub.register("u1", "1.1.1.1", frozenset({"c:1"}))
        b = hub.register("u2", "1.1.1.2", frozenset({"c:2"}))
        hub.dispatch("c:1", "m1")
        assert a.queue.get_nowait() == "m1" and b.queue.empty()
        hub.dispatch("c:none", "m2")
        assert a.queue.empty() and b.queue.empty()
        hub.unregister(a)
        hub.dispatch("c:1", "m3")
        assert a.queue.empty() and hub.connection_count == 1
        hub.unregister(a)                                  # idempotent
        hub.unregister(b)
        assert hub.connection_count == 0 and not hub._by_channel and not hub._user_count

    asyncio.run(run())


def test_hub_connection_limits_per_user_and_ip():
    async def run():
        hub = Hub(max_per_user=2, max_per_ip=3)
        c1 = hub.register("u", "9.9.9.9", frozenset())
        hub.register("u", "9.9.9.9", frozenset())
        with pytest.raises(HubLimitError):
            hub.register("u", "9.9.9.9", frozenset())
        hub.register("v", "9.9.9.9", frozenset())
        with pytest.raises(HubLimitError):                  # 4th from the same address
            hub.register("w", "9.9.9.9", frozenset())
        hub.unregister(c1)                                  # frees a slot
        hub.register("u", "9.9.9.9", frozenset())

    asyncio.run(run())


def test_slow_consumer_is_disconnected_instead_of_growing_memory():
    async def run():
        hub = Hub(queue_size=2)
        conn = hub.register("u", None, frozenset({"c"}))
        for i in range(3):
            hub.dispatch("c", f"m{i}")
        assert conn.closed.is_set() and conn.close_code == CLOSE_TRY_AGAIN and conn.queue.qsize() == 2

    asyncio.run(run())


def test_resync_broadcast_reaches_every_connection():
    async def run():
        hub = Hub()
        a = hub.register("u1", None, frozenset({"x"}))
        b = hub.register("u2", None, frozenset({"y"}))
        hub.broadcast_resync()
        assert json.loads(a.queue.get_nowait()) == {"type": "resync"}
        assert json.loads(b.queue.get_nowait()) == {"type": "resync"}

    asyncio.run(run())


# ------------------------------------------------------------------ memory broker
def test_memory_broker_delivers_across_threads_to_each_subscriber():
    async def run():
        broker = MemoryBroker()
        h1, h2 = Hub(), Hub()
        c1 = h1.register("u1", None, frozenset({"room"}))
        c2 = h2.register("u2", None, frozenset({"room"}))
        h1.ensure_attached(broker)
        h2.ensure_attached(broker)
        h1.ensure_attached(broker)                          # idempotent on the same loop
        t = threading.Thread(target=broker.publish_sync, args=("room", "hello"))
        t.start()
        t.join()
        assert await asyncio.wait_for(c1.queue.get(), 2) == "hello"
        assert await asyncio.wait_for(c2.queue.get(), 2) == "hello"
        h1.detach()
        broker.publish_sync("room", "second")
        assert await asyncio.wait_for(c2.queue.get(), 2) == "second"
        await asyncio.sleep(0.05)
        assert c1.queue.empty()                             # detached hub gets nothing
        h2.detach()

    asyncio.run(run())


def test_memory_broker_drops_subscribers_on_closed_loops():
    broker = MemoryBroker()
    hub = Hub()

    def other_loop():
        async def go():
            hub.ensure_attached(broker)
        asyncio.run(go())                                   # loop closes when this returns

    other_loop()
    broker.publish_sync("anything", "x")                    # must not raise
    assert broker._subs == []


def test_hub_reattaches_when_the_event_loop_changes():
    broker, hub = MemoryBroker(), Hub()
    got: list[str] = []

    async def first():
        hub.ensure_attached(broker)

    async def second():
        conn = hub.register("u", None, frozenset({"c"}))
        hub.ensure_attached(broker)                         # new loop -> fresh subscription
        broker.publish_sync("c", "after-restart")
        got.append(await asyncio.wait_for(conn.queue.get(), 2))
        hub.unregister(conn)
        hub.detach()

    asyncio.run(first())
    asyncio.run(second())
    assert got == ["after-restart"]


# ---------------------------------------------------------------------- tickets
def _ticket(**kw):
    base = {"user_id": UID, "clinic_id": CID, "session_id": uuid.uuid4(), "ttl_seconds": 30}
    return issue_ticket(SECRET, "HS256", **{**base, **kw})


def test_ticket_round_trip_carries_user_clinic_and_session():
    sid = uuid.uuid4()
    claims = verify_ticket(SECRET, "HS256", _ticket(session_id=sid))
    assert (claims.user_id, claims.clinic_id, claims.session_id) == (UID, CID, sid) and claims.jti


def test_ticket_rejects_expired_tampered_wrong_secret_and_garbage():
    expired = _ticket(now=time.time() - 120)
    for bad in (expired, _ticket()[:-3] + "abc", "", "not-a-jwt", "a.b.c"):
        with pytest.raises(TicketError):
            verify_ticket(SECRET, "HS256", bad)
    with pytest.raises(TicketError):
        verify_ticket("another-secret-" + "y" * 32, "HS256", _ticket())


def test_an_access_style_token_signed_with_the_main_secret_is_not_a_valid_ticket():
    now = int(time.time())
    lookalike = jwt.encode({"iss": "queuecare", "aud": "queuecare-ws", "sub": str(UID), "cid": str(CID),
                            "sid": str(uuid.uuid4()), "jti": "x", "iat": now, "exp": now + 30},
                           SECRET, algorithm="HS256")
    with pytest.raises(TicketError):
        verify_ticket(SECRET, "HS256", lookalike)            # signed with the raw secret, not the derived key


def test_ticket_with_missing_claims_is_rejected():
    from app.websocket import tickets

    now = int(time.time())
    partial = jwt.encode({"iss": "queuecare", "aud": "queuecare-ws", "sub": str(UID), "iat": now, "exp": now + 30},
                         tickets._key(SECRET), algorithm="HS256")
    with pytest.raises(TicketError):
        verify_ticket(SECRET, "HS256", partial)


def test_memory_ticket_store_allows_each_ticket_once_and_forgets_after_ttl():
    store = MemoryTicketStore()
    assert store.consume("a", 60) is True
    assert store.consume("a", 60) is False
    assert store.consume("b", 60) is True
    assert store.consume("c", 0) is True
    time.sleep(0.01)
    assert store.consume("c", 0) is True                     # expired entries are pruned
