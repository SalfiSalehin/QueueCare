"""In-process connection registry and fan-out.

One Hub per API process. The broker (Redis, or in-memory for a single process) delivers every
published message to `Hub.dispatch`; the hub hands it only to connections subscribed to that channel.

Back-pressure: each connection has a bounded queue. A client that cannot keep up is disconnected
(code 1013, "try again later") rather than letting memory grow; on reconnect it re-fetches
authoritative state over REST, so nothing is lost.

All Hub methods run on the event loop thread (the broker hops threads for us).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from app.websocket.broker import Broker

log = logging.getLogger("queuecare.ws")

CLOSE_TRY_AGAIN = 1013
CLOSE_POLICY = 1008


class HubLimitError(Exception):
    """Too many connections for this user or address."""


@dataclass(eq=False)
class Connection:
    user_id: str
    ip: str | None
    channels: frozenset[str]
    queue: asyncio.Queue[str]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    closed: asyncio.Event = field(default_factory=asyncio.Event)
    close_code: int = 1000


class Hub:
    def __init__(self, *, max_per_user: int = 5, max_per_ip: int = 50, queue_size: int = 100) -> None:
        self.max_per_user = max_per_user
        self.max_per_ip = max_per_ip
        self.queue_size = queue_size
        self._by_channel: dict[str, set[Connection]] = defaultdict(set)
        self._all: set[Connection] = set()
        self._user_count: dict[str, int] = defaultdict(int)
        self._ip_count: dict[str, int] = defaultdict(int)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._unsubscribe = None

    # ------------------------------------------------------------- registry
    def register(self, user_id: str, ip: str | None, channels: frozenset[str]) -> Connection:
        if self._user_count[user_id] >= self.max_per_user:
            raise HubLimitError("user connection limit")
        if ip is not None and self._ip_count[ip] >= self.max_per_ip:
            raise HubLimitError("address connection limit")
        conn = Connection(user_id=user_id, ip=ip, channels=channels, queue=asyncio.Queue(self.queue_size))
        self._all.add(conn)
        self._user_count[user_id] += 1
        if ip is not None:
            self._ip_count[ip] += 1
        for channel in channels:
            self._by_channel[channel].add(conn)
        return conn

    def unregister(self, conn: Connection) -> None:
        if conn not in self._all:
            return
        self._all.discard(conn)
        for channel in conn.channels:
            members = self._by_channel.get(channel)
            if members is not None:
                members.discard(conn)
                if not members:
                    del self._by_channel[channel]
        self._user_count[conn.user_id] -= 1
        if self._user_count[conn.user_id] <= 0:
            del self._user_count[conn.user_id]
        if conn.ip is not None:
            self._ip_count[conn.ip] -= 1
            if self._ip_count[conn.ip] <= 0:
                del self._ip_count[conn.ip]

    @property
    def connection_count(self) -> int:
        return len(self._all)

    # -------------------------------------------------------------- fan-out
    def _push(self, conn: Connection, message: str) -> None:
        try:
            conn.queue.put_nowait(message)
        except asyncio.QueueFull:
            log.warning("ws: slow consumer disconnected conn=%s", conn.id)
            conn.close_code = CLOSE_TRY_AGAIN
            conn.closed.set()

    def dispatch(self, channel: str, message: str) -> None:
        for conn in tuple(self._by_channel.get(channel, ())):
            self._push(conn, message)

    def broadcast_resync(self) -> None:
        """Tell every client events may have been missed (e.g. Redis reconnected): refetch via REST."""
        note = json.dumps({"type": "resync"}, separators=(",", ":"))
        for conn in tuple(self._all):
            self._push(conn, note)

    # --------------------------------------------------------------- broker
    def ensure_attached(self, broker: Broker) -> None:
        """Subscribe this hub to the broker on the *current* event loop (restarts if the loop changed)."""
        loop = asyncio.get_running_loop()
        if self._loop is loop and self._unsubscribe is not None:
            return
        self.detach()
        self._loop = loop
        self._unsubscribe = broker.subscribe(self.dispatch, self.broadcast_resync)

    def detach(self) -> None:
        if self._unsubscribe is not None:
            try:
                self._unsubscribe()
            except Exception:  # noqa: BLE001  (loop may already be closed during shutdown)
                log.debug("ws: detach failed", exc_info=True)
        self._unsubscribe = None
        self._loop = None
