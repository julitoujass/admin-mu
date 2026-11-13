"""Connecting and disconnecting the merchant's Clover account (OAuth v2, admin only).

    authorize_url    -> the URL the admin's browser opens; carries a signed, expiring `state`
    handle_callback  -> validates the `state`, exchanges the code and stores the encrypted tokens;
                        always answers with a URL of the POS to send the browser back to
    disconnect       -> forgets the tokens and disables the integration

The callback is a browser redirect without a bearer token: the `state` (HMAC, 10 minutes, bound to
the admin who started) is what authenticates it. Codes, tokens and secrets never reach logs,
the audit trail or the redirect URL.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from urllib.parse import urlencode

from app.core.exceptions import PagoError
from app.integrations.clover.oauth import (
    CloverOAuthClient,
    CloverOAuthRejected,
    CloverOAuthUnavailable,
    InvalidState,
    sign_state,
    verify_state,
)
from app.integrations.clover.tokens import TokenCipher

logger = logging.getLogger(__name__)

ENTITY = "integracion_terminal"
NOT_CONFIGURED = "Clover no es el terminal configurado (PAYMENT_TERMINAL)"
SETTINGS_PATH = "/dashboard/settings"

_CODE = re.compile(r"[\w.~-]{1,512}")
_MERCHANT_ID = re.compile(r"[A-Za-z0-9]{1,32}")


class CloverConnectionStore(Protocol):
    def save_connection(
        self, access_cifrado: str, refresh_cifrado: str, access_expira_at: datetime, merchant_id: str | None, user_id: str
    ) -> dict | None: ...

    def clear_connection(self, user_id: str) -> dict | None: ...


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CloverConnection:
    def __init__(
        self,
        frontend_url: str,
        audit: Callable[..., None],
        oauth: CloverOAuthClient | None = None,
        store: CloverConnectionStore | None = None,
        cipher: TokenCipher | None = None,
        token_key: str = "",
        redirect_uri: str = "",
        is_admin: Callable[[str], bool] = lambda user_id: False,
        now: Callable[[], datetime] = _utcnow,
    ):
        """Without `oauth` / `store` / `cipher` (Clover is not the configured terminal) every operation refuses."""
        self._frontend_url = frontend_url.rstrip("/")
        self._audit_fn = audit
        self._oauth = oauth
        self._store = store
        self._cipher = cipher
        self._token_key = token_key
        self._redirect_uri = redirect_uri
        self._is_admin = is_admin
        self._now = now

    @property
    def configured(self) -> bool:
        return bool(self._oauth and self._store and self._cipher and self._token_key)

    def authorize_url(self, user) -> str:
        if not self.configured:
            raise PagoError(NOT_CONFIGURED, status_code=409)
        state = sign_state(str(user.id), self._token_key, self._now())
        return self._oauth.authorize_url(self._redirect_uri, state)

    def handle_callback(self, code: str | None, merchant_id: str | None, state: str | None) -> str:
        """Finish the OAuth round trip. Returns where to send the browser; never raises."""
        try:
            return self._result(self._connect(code, merchant_id, state))
        except Exception:
            logger.exception("Clover OAuth callback failed")
            return self._result("error_interno")

    def disconnect(self, user) -> dict:
        if not self.configured:
            raise PagoError(NOT_CONFIGURED, status_code=409)
        self._store.clear_connection(str(user.id))
        self._emit(str(user.id), "CLOVER_DISCONNECTED")
        return {"conectado_oauth": False, "habilitado": False}

    # Internals ------------------------------------------------------------------------------

    def _connect(self, code: str | None, merchant_id: str | None, state: str | None) -> str | None:
        """Short error code, or None when the account was connected."""
        if not self.configured:
            return "no_configurado"
        try:
            user_id = verify_state(state, self._token_key, self._now())
        except InvalidState as exc:
            return exc.reason
        if not code or not _CODE.fullmatch(code) or (merchant_id and not _MERCHANT_ID.fullmatch(merchant_id)):
            return "parametros"
        if not self._is_admin(user_id):
            return "sin_permiso"
        try:
            tokens = self._oauth.exchange_code(code)
        except CloverOAuthRejected:
            return "codigo_rechazado"
        except CloverOAuthUnavailable:
            return "clover_no_disponible"
        row = self._store.save_connection(
            self._cipher.encrypt(tokens.access_token),
            self._cipher.encrypt(tokens.refresh_token),
            tokens.access_expires_at,
            merchant_id or None,
            user_id,
        )
        if row is None:
            return "sin_integracion"
        self._emit(user_id, "CLOVER_CONNECTED", payload={"merchant_id": merchant_id or None})
        return None

    def _result(self, error: str | None) -> str:
        query = {"clover": "ok"} if error is None else {"clover": "error", "motivo": error}
        return f"{self._frontend_url}{SETTINGS_PATH}?{urlencode(query)}"

    def _emit(self, usuario_id: Any, evento: str, **fields: Any) -> None:
        try:
            self._audit_fn(usuario_id, evento, entidad=ENTITY, entidad_id=1, **fields)
        except Exception:
            logger.exception("Could not write the %s audit record", evento)
