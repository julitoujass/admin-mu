"""Clover OAuth v2: authorization URL, code exchange, token refresh and the signed `state`.

Checked against https://docs.clover.com/dev/docs/high-trust-app-auth-flow and
https://docs.clover.com/dev/docs/refresh-access-tokens :

- `GET  <oauth host>/oauth/v2/authorize?client_id=&redirect_uri=&response_type=code&state=`
- `POST <api host>/oauth/v2/token`    JSON `{client_id, client_secret, code}`
- `POST <api host>/oauth/v2/refresh`  JSON `{client_id, refresh_token}`
- Both answer `{access_token, access_token_expiration, refresh_token, refresh_token_expiration}`
  with Unix timestamps. The refresh token is single-use.

Tokens, the app secret and authorization codes are never logged.
"""

import base64
import binascii
import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 600
_STATE_KEY_CONTEXT = b"clover-oauth-state-v1"
_MILLISECONDS_THRESHOLD = 10**11  # a Unix timestamp above this is in milliseconds


class CloverOAuthError(Exception):
    """Base class of the OAuth failures."""


class CloverOAuthRejected(CloverOAuthError):
    """Clover answered and refused (invalid code, spent refresh token, wrong credentials)."""


class CloverOAuthUnavailable(CloverOAuthError):
    """Clover could not be reached or failed; the request may be repeated later."""


class InvalidState(Exception):
    """The OAuth `state` is not ours. `reason` is a short public code."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CloverTokens:
    access_token: str
    refresh_token: str
    access_expires_at: datetime

    def __repr__(self) -> str:  # never show the tokens in logs or tracebacks
        return f"CloverTokens(access_expires_at={self.access_expires_at.isoformat()})"


# --- Signed state -----------------------------------------------------------------------------


def _state_key(token_key: str) -> bytes:
    return hmac.new(token_key.encode("utf-8"), _STATE_KEY_CONTEXT, hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text.encode("ascii") + b"=" * (-len(text) % 4))


def sign_state(user_id: str, token_key: str, now: datetime, ttl: int = STATE_TTL_SECONDS) -> str:
    """Expiring token that binds the OAuth round trip to the admin who started it."""
    payload = json.dumps(
        {"u": str(user_id), "e": int(now.timestamp()) + ttl, "n": secrets.token_urlsafe(8)}, separators=(",", ":")
    ).encode("utf-8")
    signature = hmac.new(_state_key(token_key), payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(signature)}"


def verify_state(state: str | None, token_key: str, now: datetime) -> str:
    """User id bound to a state we signed. Raises `InvalidState` (`state_invalido` / `state_expirado`)."""
    try:
        encoded_payload, encoded_signature = (state or "").split(".")
        payload = _unb64(encoded_payload)
        signature = _unb64(encoded_signature)
    except (ValueError, binascii.Error):
        raise InvalidState("state_invalido") from None
    expected = hmac.new(_state_key(token_key), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise InvalidState("state_invalido")
    try:
        data = json.loads(payload)
        user_id, expires = str(data["u"]), int(data["e"])
    except (ValueError, KeyError, TypeError):
        raise InvalidState("state_invalido") from None
    if now.timestamp() >= expires:
        raise InvalidState("state_expirado")
    return user_id


# --- HTTP client -------------------------------------------------------------------------------


class CloverOAuthClient:
    def __init__(
        self,
        oauth_url: str,
        api_url: str,
        app_id: str,
        app_secret: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ):
        self._oauth_url = oauth_url.rstrip("/")
        self._api_url = api_url.rstrip("/")
        self._app_id = app_id
        self._app_secret = app_secret
        self._http = httpx.Client(
            transport=transport or httpx.HTTPTransport(http2=False, retries=1),
            timeout=httpx.Timeout(timeout, connect=10.0),
            headers={"Accept": "application/json"},
        )

    def authorize_url(self, redirect_uri: str, state: str) -> str:
        query = urlencode(
            {"client_id": self._app_id, "redirect_uri": redirect_uri, "response_type": "code", "state": state}
        )
        return f"{self._oauth_url}/oauth/v2/authorize?{query}"

    def exchange_code(self, code: str) -> CloverTokens:
        return self._post(
            "/oauth/v2/token", {"client_id": self._app_id, "client_secret": self._app_secret, "code": code}
        )

    def refresh(self, refresh_token: str) -> CloverTokens:
        return self._post("/oauth/v2/refresh", {"client_id": self._app_id, "refresh_token": refresh_token})

    def _post(self, path: str, body: dict) -> CloverTokens:
        try:
            response = self._http.post(f"{self._api_url}{path}", json=body)
        except httpx.HTTPError as exc:
            # Only the class of the error is logged: nothing of the request may reach the logs.
            logger.warning("Clover OAuth %s failed (%s)", path, type(exc).__name__)
            raise CloverOAuthUnavailable(path) from None
        if response.status_code >= 500:
            logger.warning("Clover OAuth %s answered %s", path, response.status_code)
            raise CloverOAuthUnavailable(path)
        if response.status_code != 200:
            logger.warning("Clover OAuth %s was rejected with %s", path, response.status_code)
            raise CloverOAuthRejected(path)
        try:
            data = response.json()
            access, refresh = data["access_token"], data["refresh_token"]
            expires = float(data["access_token_expiration"])
        except (ValueError, KeyError, TypeError):
            logger.warning("Clover OAuth %s answered without the expected token fields", path)
            raise CloverOAuthRejected(path) from None
        if not (isinstance(access, str) and access and isinstance(refresh, str) and refresh):
            raise CloverOAuthRejected(path)
        if expires > _MILLISECONDS_THRESHOLD:
            expires /= 1000
        return CloverTokens(access, refresh, datetime.fromtimestamp(expires, tz=timezone.utc))
