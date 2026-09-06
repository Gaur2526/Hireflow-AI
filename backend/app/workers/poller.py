"""Background reconciliation loop.

Webhooks are the fast path, but they need a public HTTPS URL and they can be
missed. This loop polls Hunar for every in-flight call so the dashboard is
correct even on a laptop behind NAT.
"""

from __future__ import annotations

import asyncio
import contextlib

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import session_scope
from app.services.campaigns import sync_stale_calls

log = get_logger(__name__)


async def _tick() -> None:
    with session_scope() as db:
        updated = await sync_stale_calls(db)
    if updated:
        log.info("poller.updated", calls=updated)


async def run_poller(stop: asyncio.Event) -> None:
    interval = max(5, settings.call_poll_interval_seconds)
    log.info("poller.started", interval_seconds=interval)
    while not stop.is_set():
        try:
            await _tick()
        except Exception as exc:  # keep the loop alive whatever happens
            log.warning("poller.error", error=str(exc)[:300])
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
    log.info("poller.stopped")
