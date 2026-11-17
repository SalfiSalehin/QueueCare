"""Outbox relay: moves committed outbox rows to the broker (Redis Pub/Sub).

Delivery is AT LEAST ONCE and never loses a committed event:
  1. lock a batch of unpublished rows (FOR UPDATE SKIP LOCKED, so several API replicas can run a
     relay at the same time without double work),
  2. publish each row, then mark it published,
  3. commit. If the process dies between publish and commit, the rows stay unpublished and are
     published again later: a duplicate, never a loss. Clients deduplicate on the event id.

The relay reads across clinics, so it binds the explicit platform RLS context. It only ever reads
and marks outbox rows; it has no other cross-tenant access.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.database import get_sessionmaker, set_rls_context
from app.models import OutboxEvent
from app.services.outbox import envelope
from app.websocket.broker import Broker

log = logging.getLogger("queuecare.relay")

Publish = Callable[[str, str], None]


class RelayPublishError(Exception):
    """A publish failed mid-batch. Rows delivered before it are already marked published."""

    def __init__(self, published: int) -> None:
        super().__init__(f"publish failed after {published} event(s)")
        self.published = published


def relay_batch(factory: sessionmaker[Session], publish: Publish, batch_size: int = 100) -> int:
    """Publish up to `batch_size` pending events in version order. Returns how many were published."""
    published = 0
    failure: Exception | None = None
    with factory() as db:
        set_rls_context(db, platform=True)
        rows = db.scalars(
            select(OutboxEvent).where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.version).limit(batch_size).with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            try:
                publish(row.channel, envelope(row))
            except Exception as exc:  # noqa: BLE001  (broker down, etc.)
                failure = exc
                break
            row.published_at = datetime.now(UTC)
            published += 1
        db.commit()                       # keep what was delivered even if a later publish failed
    if failure is not None:
        log.warning("outbox relay: publish failed after %d event(s): %s", published, failure)
        raise RelayPublishError(published) from failure
    return published


def purge_published(factory: sessionmaker[Session], retention_days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    with factory() as db:
        set_rls_context(db, platform=True)
        result = db.execute(delete(OutboxEvent).where(OutboxEvent.published_at < cutoff))
        db.commit()
        return int(result.rowcount or 0)


async def relay_loop(settings: Settings, broker: Broker) -> None:
    """Background task started with the API. Cancelled on shutdown."""
    factory = get_sessionmaker()
    last_purge = 0.0
    loop = asyncio.get_running_loop()
    while True:
        delay = settings.outbox_poll_interval_seconds
        try:
            count = await asyncio.to_thread(relay_batch, factory, broker.publish_sync, settings.outbox_batch_size)
            if count >= settings.outbox_batch_size:
                delay = 0                 # more waiting: keep draining
        except RelayPublishError:
            delay = max(delay, 2.0)       # broker trouble: back off (already logged)
        except Exception:  # noqa: BLE001
            log.exception("outbox relay: unexpected error")
            delay = max(delay, 5.0)
        if loop.time() - last_purge > 3600:
            last_purge = loop.time()
            try:
                purged = await asyncio.to_thread(purge_published, factory, settings.outbox_retention_days)
                if purged:
                    log.info("outbox relay: purged %d old event(s)", purged)
            except Exception:  # noqa: BLE001
                log.exception("outbox relay: purge failed")
        await asyncio.sleep(delay)
