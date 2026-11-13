"""Composition root: wires the application services to their adapters."""

from functools import lru_cache

from app.api import auth_deps
from app.core.config import settings
from app.integrations.clover.connection import CloverConnection
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
        requires_oauth=settings.clover_configured,
        # The Clover ping goes through its cloud: give it more room than the in-memory fake.
        ping_timeout=5.0 if settings.clover_configured else 2.0,
    )


def _is_active_admin(user_id: str) -> bool:
    """Whether the user is an active admin right now (the OAuth callback has no bearer token to check)."""
    try:
        rol, activo = auth_deps._load_profile(str(user_id))
    except Exception:
        return False
    return activo and rol == "admin"


@lru_cache(maxsize=1)
def get_clover_connection() -> CloverConnection:
    """Connect / disconnect the Clover account. Refuses everything unless PAYMENT_TERMINAL=clover."""
    if not settings.clover_configured:
        return CloverConnection(frontend_url=settings.FRONTEND_URL, audit=record_audit)
    from app.integrations.clover.wiring import get_clover_store, get_oauth_client, get_token_cipher

    return CloverConnection(
        frontend_url=settings.FRONTEND_URL,
        audit=record_audit,
        oauth=get_oauth_client(),
        store=get_clover_store(),
        cipher=get_token_cipher(),
        token_key=settings.CLOVER_TOKEN_KEY.get_secret_value().strip(),
        redirect_uri=settings.CLOVER_REDIRECT_URI,
        is_admin=_is_active_admin,
    )
