"""Composition root: wires the application services to their adapters."""

from functools import lru_cache

from app.core.config import settings
from app.integrations.payment_terminal.factory import get_terminal
from app.repositories.supabase_pago_store import SupabasePagoStore
from app.services.audit import record_audit
from app.services.pago_service import PagoService


@lru_cache(maxsize=1)
def get_pago_service() -> PagoService:
    """The charge orchestration, built once per process (the terminal adapter is stateful)."""
    return PagoService(
        terminal=get_terminal(),
        store=SupabasePagoStore(),
        provider=settings.PAYMENT_TERMINAL,
        audit=record_audit,
        backoff=settings.payment_reconcile_backoff,
        stale_seconds=settings.PAYMENT_STALE_SECONDS,
        max_attempts=settings.PAYMENT_RECONCILE_MAX_ATTEMPTS,
    )
