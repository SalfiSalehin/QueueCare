"""Message brokers between the outbox relay and the WebSocket hubs.

- MemoryBroker: process-wide, thread-safe. Used when REDIS_URL is not set (single process, local
  development, tests). It delivers to every subscribed hub just like Redis would.
- RedisBroker: Redis Pub/Sub, so any API replica's relay reaches clients connected to any replica.

Redis is transient by design: a message published while a hub is disconnected is gone. That is
safe because (a) the outbox row is the durable record and (b) clients re-fetch state over REST on
reconnect. After the Redis listener reconnects, `on_gap` tells connected clients to resync.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger("queuecare.ws")

Dispatch = Callable[[str, str], None]
Unsubscribe = Callable[[], None]


class Broker(Protocol):
    def publish_sync(self, channel: str, message: str) -> None:
        """Publish from any thread. Must raise if the message could not be handed over."""

    def subscribe(self, dispatch: Dispatch, on_gap: Callable[[], None] | None = None) -> Unsubscribe:
        """Start delivering messages to `dispatch` on the *calling* event loop."""


class MemoryBroker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: list[tuple[Dispatch, asyncio.AbstractEventLoop]] = []

    def publish_sync(self, channel: str, message: str) -> None:
        with self._lock:
            subs = list(self._subs)
        for dispatch, loop in subs:
            try:
                loop.call_soon_threadsafe(dispatch, channel, message)
            except RuntimeError:                      # that loop has been closed: drop the subscriber
                with self._lock:
                    self._subs = [s for s in self._subs if s[1] is not loop]

    def subscribe(self, dispatch: Dispatch, on_gap: Callable[[], None] | None = None) -> Unsubscribe:
        entry = (dispatch, asyncio.get_running_loop())
        with self._lock:
            self._subs.append(entry)

        def unsubscribe() -> None:
            with self._lock:
                if entry in self._subs:
                    self._subs.remove(entry)

        return unsubscribe


class RedisBroker:
    PREFIX = "qc:"

    def __init__(self, url: str) -> None:
        self._url = url
        self._client = None
        self._lock = threading.Lock()

    def _publisher(self):  # type: ignore[no-untyped-def]
        import redis

        with self._lock:
            if self._client is None:
                self._client = redis.Redis.from_url(self._url, socket_timeout=2, socket_connect_timeout=2)
            return self._client

    def publish_sync(self, channel: str, message: str) -> None:
        self._publisher().publish(self.PREFIX + channel, message)   # raises -> relay keeps the row unpublished

    def subscribe(self, dispatch: Dispatch, on_gap: Callable[[], None] | None = None) -> Unsubscribe:
        task = asyncio.get_running_loop().create_task(self._listen(dispatch, on_gap))
        return task.cancel

    async def _listen(self, dispatch: Dispatch, on_gap: Callable[[], None] | None) -> None:
        import redis.asyncio as aioredis

        backoff, connected_before = 0.5, False
        while True:
            client = aioredis.Redis.from_url(self._url, decode_responses=True)
            pubsub = client.pubsub()
            try:
                await pubsub.psubscribe(self.PREFIX + "*")
                if connected_before and on_gap is not None:
                    on_gap()                          # we may have missed messages while disconnected
                connected_before, backoff = True, 0.5
                async for item in pubsub.listen():
                    if item.get("type") == "pmessage":
                        dispatch(str(item["channel"])[len(self.PREFIX):], str(item["data"]))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.warning("ws: Redis subscription lost; retrying in %.1fs", backoff, exc_info=True)
            finally:
                try:
                    close = getattr(pubsub, "aclose", None) or pubsub.close
                    await close()
                    await client.aclose()
                except Exception:  # noqa: BLE001
                    log.debug("ws: error closing Redis connection", exc_info=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10.0)


_memory_broker = MemoryBroker()
_redis_brokers: dict[str, RedisBroker] = {}
_brokers_lock = threading.Lock()


def get_broker(redis_url: str | None) -> Broker:
    if not redis_url:
        return _memory_broker
    with _brokers_lock:
        if redis_url not in _redis_brokers:
            _redis_brokers[redis_url] = RedisBroker(redis_url)
        return _redis_brokers[redis_url]
