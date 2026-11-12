"""Periodic sweep of unresolved terminal charges, run from the FastAPI lifespan."""

import asyncio
import logging
from contextlib import suppress
from typing import Callable

logger = logging.getLogger(__name__)


async def _run(sweep: Callable[[], None], interval: float) -> None:
    """Call the blocking `sweep` in a worker thread now, and again every `interval` seconds."""
    while True:
        try:
            await asyncio.to_thread(sweep)
        except Exception:
            logger.exception("Payment reconciliation sweep failed")
        await asyncio.sleep(interval)


def start_reconciler(sweep: Callable[[], None], interval: float) -> asyncio.Task | None:
    """Start the loop on the running event loop; `interval <= 0` disables it (returns None)."""
    if interval <= 0:
        return None
    return asyncio.create_task(_run(sweep, interval), name="payment-reconciler")


async def stop_reconciler(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
