"""Token vault of the Clover integration.

- `TokenCipher` encrypts the OAuth tokens at rest with Fernet (`CLOVER_TOKEN_KEY`).
- `CloverTokenProvider.get_access_token()` returns a usable access token, renewing it when it
  expires within 5 minutes.

The refresh token is single-use, so two renewals must never run with the same one:

- inside a process, renewals are serialized with a lock;
- across processes, the new pair is stored with a compare-and-set on the refresh token that was
  spent (`CloverTokenStore.replace_tokens`). Whoever loses the race re-reads the row and uses
  what the winner stored. Likewise, when Clover rejects a refresh token the row is re-read
  first: another process may just have spent it.

A rejected renewal disables the integration and asks the admin to reconnect. Tokens are never logged.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, NoReturn, Protocol

from cryptography.fernet import Fernet, InvalidToken

from app.integrations.clover.oauth import CloverOAuthRejected, CloverOAuthUnavailable, CloverTokens
from app.integrations.payment_terminal.port import TerminalUnavailable

logger = logging.getLogger(__name__)

RECONNECT = "Reconectá Clover desde Configuración"
REFRESH_UNAVAILABLE = "No se pudo renovar la sesión de Clover. Intentá de nuevo."
REFRESH_MARGIN = timedelta(minutes=5)


class TokenCipher:
    def __init__(self, key: str):
        self._fernet = Fernet(key.encode("ascii"))

    def encrypt(self, plain: str) -> str:
        return self._fernet.encrypt(plain.encode("utf-8")).decode("ascii")

    def decrypt(self, cipher: str) -> str:
        """Raises `cryptography.fernet.InvalidToken` when the text was not encrypted with this key."""
        return self._fernet.decrypt(cipher.encode("ascii")).decode("utf-8")


class CloverTokenStore(Protocol):
    def get(self) -> dict | None:
        """The integration row (`access_token_cifrado`, `refresh_token_cifrado`, `access_expira_at`, ...)."""

    def replace_tokens(
        self, expected_refresh_cifrado: str, access_cifrado: str, refresh_cifrado: str, access_expira_at: datetime
    ) -> bool:
        """Store a renewed pair only if the row still holds `expected_refresh_cifrado`. False when it lost."""

    def disable(self) -> None:
        """Set `habilitado = false`."""


class OAuthRefresher(Protocol):
    def refresh(self, refresh_token: str) -> CloverTokens: ...


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def has_tokens(row: dict | None) -> bool:
    return bool(row and row.get("access_token_cifrado") and row.get("refresh_token_cifrado"))


class CloverTokenProvider:
    def __init__(
        self,
        store: CloverTokenStore,
        oauth: OAuthRefresher,
        cipher: TokenCipher,
        now: Callable[[], datetime] = _utcnow,
    ):
        self._store = store
        self._oauth = oauth
        self._cipher = cipher
        self._now = now
        self._lock = threading.Lock()

    def get_access_token(self, rejected: str | None = None) -> str:
        """A valid access token.

        `rejected` is an access token Clover just answered 401 to: it forces a renewal unless
        the stored token is already a different one (someone else renewed it meanwhile).
        Raises `TerminalUnavailable` when there is no usable connection.
        """
        with self._lock:
            row = self._store.get()
            if not has_tokens(row):
                raise TerminalUnavailable(RECONNECT)
            access = self._decrypt(row["access_token_cifrado"])
            if access != rejected and not self._expiring(row):
                return access
            return self._renew(row)

    # Internals ------------------------------------------------------------------------------

    def _renew(self, row: dict) -> str:
        spent_cifrado = row["refresh_token_cifrado"]
        refresh_token = self._decrypt(spent_cifrado)
        try:
            tokens = self._oauth.refresh(refresh_token)
        except CloverOAuthUnavailable:
            raise TerminalUnavailable(REFRESH_UNAVAILABLE) from None
        except CloverOAuthRejected:
            current = self._renewed_elsewhere(spent_cifrado)
            if current is not None:
                return current
            self._give_up("Clover rejected the refresh token")
        stored = self._store.replace_tokens(
            spent_cifrado,
            self._cipher.encrypt(tokens.access_token),
            self._cipher.encrypt(tokens.refresh_token),
            tokens.access_expires_at,
        )
        if stored:
            logger.info("Clover access token renewed; it expires at %s", tokens.access_expires_at.isoformat())
            return tokens.access_token
        # The row changed while we renewed (another process, a reconnection or a disconnection).
        current = self._renewed_elsewhere(spent_cifrado)
        if current is None:
            raise TerminalUnavailable(RECONNECT)
        return current

    def _renewed_elsewhere(self, spent_cifrado: str) -> str | None:
        """The access token someone else stored after the refresh token we hold was spent, if any."""
        row = self._store.get()
        if not has_tokens(row) or row["refresh_token_cifrado"] == spent_cifrado or self._expiring(row):
            return None
        return self._decrypt(row["access_token_cifrado"])

    def _expiring(self, row: dict) -> bool:
        raw = row.get("access_expira_at")
        if not raw:
            return True
        try:
            expires = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
        except ValueError:
            return True
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires - self._now() <= REFRESH_MARGIN

    def _decrypt(self, cipher_text: str) -> str:
        try:
            return self._cipher.decrypt(cipher_text)
        except (InvalidToken, ValueError):
            # Stored with another CLOVER_TOKEN_KEY: the tokens are unusable.
            self._give_up("Stored Clover tokens cannot be decrypted with the current key")

    def _give_up(self, reason: str) -> NoReturn:
        logger.error("%s: the integration was disabled until an admin reconnects", reason)
        try:
            self._store.disable()
        except Exception:
            logger.exception("Could not disable the terminal integration")
        raise TerminalUnavailable(RECONNECT) from None
