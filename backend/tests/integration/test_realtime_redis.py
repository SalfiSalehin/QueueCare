"""Redis-backed broker and ticket store. Runs only when a real Redis is reachable (it is inside the
Docker backend container, using the REDIS_URL from .env); otherwise these tests are skipped, so the
rest of the suite never depends on Redis."""
from __future__ import annotations

import asyncio
import threading
import uuid

import pytest

from app.websocket.broker import RedisBroker
from app.websocket.hub import Hub
from app.websocket.tickets import RedisTicketStore
from tests.conftest import ORIGINAL_REDIS_URL


def _redis_or_skip() -> str:
    if not ORIGINAL_REDIS_URL:
        pytest.skip("REDIS_URL not set")
    try:
        import redis

        redis.Redis.from_url(ORIGINAL_REDIS_URL, socket_connect_timeout=1, socket_timeout=1).ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis not reachable: {exc}")
    return ORIGINAL_REDIS_URL


def test_redis_broker_fans_out_to_every_subscribed_hub():
    url = _redis_or_skip()

    async def run():
        broker = RedisBroker(url)
        h1, h2 = Hub(), Hub()
        channel = f"clinic:{uuid.uuid4()}:staff"
        c1 = h1.register("u1", None, frozenset({channel}))
        c2 = h2.register("u2", None, frozenset({channel}))
        h1.ensure_attached(broker)
        h2.ensure_attached(broker)
        await asyncio.sleep(0.5)                                  # let both psubscribe calls complete
        threading.Thread(target=broker.publish_sync, args=(channel, "hello")).start()
        assert await asyncio.wait_for(c1.queue.get(), 5) == "hello"
        assert await asyncio.wait_for(c2.queue.get(), 5) == "hello"
        h1.detach()
        h2.detach()

    asyncio.run(run())


def test_redis_ticket_store_is_single_use():
    url = _redis_or_skip()
    store = RedisTicketStore(url)
    jti = uuid.uuid4().hex
    assert store.consume(jti, 30) is True
    assert store.consume(jti, 30) is False
