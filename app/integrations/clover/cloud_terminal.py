"""Clover Cloud Pay Display adapter of the `PaymentTerminal` port.

Backend -> Clover cloud (`<base>/connect/v1/...`) -> device. Checked against the "Clover Card
Present REST API" reference (https://docs.clover.com/dev/reference/pay and siblings):

    GET  /v1/device/ping                         {connected}
    GET  /v1/device/status                       {status: IDLE | BUSY | WAITING_FOR_CUSTOMER | UNKNOWN}
    POST /v1/payments                            {amount, externalPaymentId, final}  -> {payment, issues}
    GET  /v1/payments/external/{externalId}      -> {payment}
    POST /v1/payments/{paymentId}/refunds        {amount} | {fullRefund: true}       -> {refund, payment}
    POST /v1/device/cancel
    POST /v1/device/welcome

Status codes shared by every operation: 200 processed (not necessarily approved), 209 cancelled,
400 invalid (do not repeat), 401 invalid bearer token, 503 device busy, 504 device did not answer,
500 indeterminate.

How they map to the port:

- charge: 200 -> `payment.result`; 209 -> CANCELLED; 400 -> `TerminalBadRequest`; 503 ->
  `TerminalBusy`; anything else (500, 504, timeouts, network errors, unexpected codes) -> UNKNOWN,
  because the customer may have been charged. It is never retried here.
- every other operation raises `TerminalUnavailable` where a charge would answer UNKNOWN.
- 401: the access token is renewed once and the request repeated once (POSTs carry the same
  `Idempotency-Key`); a second 401 is `TerminalUnavailable`.

Card data: only brand, last 4 digits, authorization code and entry type are read. The raw response
kept for troubleshooting is stripped of everything else about the card, and nothing of a response
body is ever logged.
"""

import logging
import re
from typing import Any, Callable

import httpx

from app.integrations.clover.tokens import CloverTokenProvider
from app.integrations.payment_terminal.port import (
    ChargeOutcome,
    ChargeRequest,
    ChargeResult,
    RefundOutcome,
    RefundResult,
    TerminalBadRequest,
    TerminalBusy,
    TerminalStatus,
    TerminalUnavailable,
)

logger = logging.getLogger(__name__)

DEVICE_NOT_CONFIGURED = "Falta configurar la serie del dispositivo Clover"
NOT_REACHABLE = "No se pudo contactar al Clover"

# Seconds the device may take (`X-Clover-Timeout`, 0-300) and, a bit longer, our own HTTP deadline.
# The charge must end before PAYMENT_STALE_SECONDS (180 s), when the sweep takes the charge over.
CHARGE_TIMEOUT = (120, 150.0)
REFUND_TIMEOUT = (60, 75.0)
LOOKUP_TIMEOUT = (15, 25.0)
DEVICE_TIMEOUT = (10, 15.0)  # status, cancel, welcome
PING_HTTP_TIMEOUT = 5.0

_DECLINED_RESULTS = {"FAIL", "VOIDED"}
_NOT_FOUND = re.compile(r"not\s*found|no\s+payment|does\s+not\s+exist", re.IGNORECASE)
_INSTALLMENTS_KEY = re.compile(r"installments|cuotas", re.IGNORECASE)
# Card fields that must not leave this module, wherever they appear in a response.
_CARD_SECRET_KEYS = {"first6", "cardholdername", "token", "vaultedcard", "track1", "track2", "pan", "expirationdate"}


class _Unreachable(Exception):
    """No HTTP response at all (timeout or network error)."""


class CloverCloudTerminal:
    def __init__(
        self,
        base_url: str,
        tokens: CloverTokenProvider,
        get_integration: Callable[[], dict | None],
        default_pos_id: str,
        user_agent: str,
        transport: httpx.BaseTransport | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._tokens = tokens
        self._get_integration = get_integration
        self._default_pos_id = default_pos_id
        # Own client, HTTP/1.1: one long blocking request per charge, no shared multiplexed connection.
        self._http = httpx.Client(
            transport=transport or httpx.HTTPTransport(http2=False, retries=1),  # retries: connection setup only
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )

    # Port ---------------------------------------------------------------------------------------

    def ping(self) -> bool:
        try:
            response = self._request("GET", "/v1/device/ping", http_timeout=PING_HTTP_TIMEOUT)
        except (_Unreachable, TerminalUnavailable, TerminalBadRequest):
            return False
        if response.status_code == 503:
            return True  # busy with another call: reachable
        return response.status_code == 200 and _json(response).get("connected") is True

    def status(self) -> TerminalStatus:
        response = self._send("GET", "/v1/device/status", DEVICE_TIMEOUT)
        if response.status_code == 503:
            return TerminalStatus.BUSY
        if response.status_code != 200:
            raise TerminalUnavailable(NOT_REACHABLE)
        try:
            return TerminalStatus(_json(response).get("status"))
        except ValueError:
            return TerminalStatus.UNKNOWN

    def charge(self, req: ChargeRequest) -> ChargeResult:
        body = {"amount": req.amount_cents, "externalPaymentId": req.external_id, "final": True}
        try:
            response = self._request(
                "POST",
                "/v1/payments",
                clover_timeout=CHARGE_TIMEOUT[0],
                http_timeout=CHARGE_TIMEOUT[1],
                json=body,
                idempotency_key=req.external_id,
            )
        except _Unreachable:
            return ChargeResult(outcome=ChargeOutcome.UNKNOWN, error="Sin respuesta del Clover")
        status = response.status_code
        if status == 200:
            return _charge_result(_json(response))
        if status == 209:
            return ChargeResult(outcome=ChargeOutcome.CANCELLED)
        if status == 400:
            raise TerminalBadRequest(f"Clover rejected the charge request ({_error_type(response)})")
        if status == 503:
            raise TerminalBusy("The Clover device is busy")
        logger.warning("Clover answered %s to a charge: the result is unknown", status)
        return ChargeResult(outcome=ChargeOutcome.UNKNOWN, error=f"Clover respondió {status}")

    def find_by_external_id(self, external_id: str) -> ChargeResult | None:
        response = self._send("GET", f"/v1/payments/external/{external_id}", LOOKUP_TIMEOUT)
        status = response.status_code
        if status == 200:
            return _charge_result(_json(response))
        if status == 404 or (status == 400 and _NOT_FOUND.search(_error_message(response))):
            # The device positively answered that it has no such payment.
            return None
        if status == 400:
            raise TerminalBadRequest(f"Clover rejected the lookup ({_error_type(response)})")
        raise TerminalUnavailable(f"{NOT_REACHABLE} ({status})")

    def cancel_current(self) -> None:
        response = self._send("POST", "/v1/device/cancel", DEVICE_TIMEOUT)
        if response.status_code not in (200, 209):
            raise TerminalUnavailable(f"{NOT_REACHABLE} ({response.status_code})")

    def refund(self, payment_id: str, amount_cents: int | None) -> RefundResult:
        body = {"fullRefund": True} if amount_cents is None else {"amount": amount_cents}
        amount_label = "full" if amount_cents is None else str(amount_cents)
        try:
            response = self._request(
                "POST",
                f"/v1/payments/{payment_id}/refunds",
                clover_timeout=REFUND_TIMEOUT[0],
                http_timeout=REFUND_TIMEOUT[1],
                json=body,
                idempotency_key=f"refund-{payment_id}-{amount_label}",
            )
        except _Unreachable:
            return RefundResult(outcome=RefundOutcome.UNKNOWN, error="Sin respuesta del Clover")
        status = response.status_code
        if status == 200:
            data = _json(response)
            refund = data.get("refund") if isinstance(data.get("refund"), dict) else {}
            if refund.get("id"):
                return RefundResult(outcome=RefundOutcome.DONE, refund_id=str(refund["id"]), raw=_strip_card_data(data))
            return RefundResult(
                outcome=RefundOutcome.UNKNOWN, raw=_strip_card_data(data), error="Clover no informó el reembolso"
            )
        if status == 209:
            return RefundResult(outcome=RefundOutcome.FAILED, error="Reembolso cancelado en el dispositivo")
        if status == 400:
            raise TerminalBadRequest(f"Clover rejected the refund request ({_error_type(response)})")
        if status == 503:
            raise TerminalBusy("The Clover device is busy")
        logger.warning("Clover answered %s to a refund: the result is unknown", status)
        return RefundResult(outcome=RefundOutcome.UNKNOWN, error=f"Clover respondió {status}")

    def show_welcome(self) -> None:
        response = self._send("POST", "/v1/device/welcome", DEVICE_TIMEOUT)
        if 400 <= response.status_code < 500:
            # Cosmetic: a rejected welcome screen must never fail a transaction.
            logger.info("Clover did not show the welcome screen (%s)", response.status_code)
            return
        if response.status_code not in (200, 209):
            raise TerminalUnavailable(f"{NOT_REACHABLE} ({response.status_code})")

    # HTTP ----------------------------------------------------------------------------------------

    def _send(self, method: str, path: str, timeouts: tuple[int, float]) -> httpx.Response:
        """A request whose missing answer is simply "terminal unavailable" (everything but charge / refund)."""
        try:
            return self._request(method, path, clover_timeout=timeouts[0], http_timeout=timeouts[1])
        except _Unreachable:
            raise TerminalUnavailable(NOT_REACHABLE) from None

    def _request(
        self,
        method: str,
        path: str,
        http_timeout: float,
        clover_timeout: int | None = None,
        json: dict | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        """Send with the mandatory headers; on 401 renew the token once and repeat once.

        Raises `TerminalBadRequest` (no device configured), `TerminalUnavailable` (no usable
        token, or 401 twice) and `_Unreachable` (no HTTP response).
        """
        integration = self._get_integration() or {}
        device_id = (integration.get("device_id") or "").strip()
        if not device_id:
            raise TerminalBadRequest(DEVICE_NOT_CONFIGURED)
        headers = {
            "X-Clover-Device-Id": device_id,
            "X-POS-Id": (integration.get("pos_id") or "").strip() or self._default_pos_id,
        }
        if clover_timeout is not None:
            headers["X-Clover-Timeout"] = str(clover_timeout)
        if method == "POST":
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key

        token = self._tokens.get_access_token()
        for attempt in (1, 2):
            try:
                response = self._http.request(
                    method,
                    f"{self._base_url}{path}",
                    headers={**headers, "Authorization": f"Bearer {token}"},
                    json=json,
                    timeout=httpx.Timeout(http_timeout, connect=10.0),
                )
            except httpx.HTTPError as exc:
                logger.warning("Clover %s %s got no response (%s)", method, _safe_path(path), type(exc).__name__)
                raise _Unreachable() from None
            if response.status_code != 401:
                return response
            if attempt == 1:
                token = self._tokens.get_access_token(rejected=token)
        logger.error("Clover keeps answering 401 after renewing the access token")
        raise TerminalUnavailable(NOT_REACHABLE)


# --- Response parsing -----------------------------------------------------------------------------


def _json(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _error_message(response: httpx.Response) -> str:
    return str(_json(response).get("message") or "")


def _error_type(response: httpx.Response) -> str:
    """The `type` of a Clover error body (`ERROR`, `RESOURCE_CONFLICT`, ...): safe to log."""
    return re.sub(r"[^A-Z_]", "", str(_json(response).get("type") or "").upper())[:40] or "no type"


def _safe_path(path: str) -> str:
    """Path with its ids removed, for logs."""
    return re.sub(r"/(payments|external)/[^/]+", r"/\1/*", path)


def _charge_result(data: dict) -> ChargeResult:
    payment = data.get("payment") if isinstance(data.get("payment"), dict) else None
    raw = _strip_card_data(data)
    if payment is None:
        return ChargeResult(outcome=ChargeOutcome.UNKNOWN, raw=raw, error="Clover no informó el pago")
    result = str(payment.get("result") or "").upper()
    card = payment.get("cardTransaction") if isinstance(payment.get("cardTransaction"), dict) else {}
    details = {
        "provider_payment_id": _text(payment.get("id")),
        "card_brand": _text(card.get("cardType")),
        "last4": _last4(card.get("last4")),
        "auth_code": _text(card.get("authCode")),
        "entry_type": _text(card.get("entryType")),
        "installments": _find_installments(data),
        "raw": raw,
    }
    if result == "SUCCESS":
        return ChargeResult(outcome=ChargeOutcome.APPROVED, **details)
    if result in _DECLINED_RESULTS:
        return ChargeResult(outcome=ChargeOutcome.DECLINED, **details, error="Pago rechazado")
    # INITIATED, AUTH, VOIDING, ...: not a final sale yet; reconcile instead of guessing.
    return ChargeResult(outcome=ChargeOutcome.UNKNOWN, **details, error=f"Resultado del Clover: {result or 'vacío'}"[:80])


def _text(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return str(value) or None


def _last4(value: Any) -> str | None:
    text = _text(value)
    return text if text and re.fullmatch(r"\d{4}", text) else None


def _find_installments(value: Any) -> int | None:
    """Number of installments, wherever the response carries it (Argentina regional extras)."""
    if isinstance(value, dict):
        for key, item in value.items():
            if _INSTALLMENTS_KEY.search(str(key)) and not isinstance(item, bool):
                try:
                    count = int(item)
                except (TypeError, ValueError):
                    continue
                if 1 <= count <= 99:
                    return count
        for item in value.values():
            found = _find_installments(item)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_installments(item)
            if found is not None:
                return found
    return None


def _strip_card_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_card_data(item) for key, item in value.items() if str(key).lower() not in _CARD_SECRET_KEYS
        }
    if isinstance(value, list):
        return [_strip_card_data(item) for item in value]
    return value
