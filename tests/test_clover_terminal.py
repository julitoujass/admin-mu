"""Clover Cloud Pay Display adapter against simulated HTTP responses (`httpx.MockTransport`)."""

import json
import logging

import httpx
import pytest

from app.integrations.clover.cloud_terminal import CloverCloudTerminal
from app.integrations.clover.oauth import CloverOAuthRejected
from app.integrations.clover.tokens import CloverTokenProvider
from app.integrations.payment_terminal.port import (
    ChargeOutcome,
    ChargeRequest,
    PaymentTerminal,
    RefundOutcome,
    TerminalBadRequest,
    TerminalBusy,
    TerminalStatus,
    TerminalUnavailable,
)
from tests.fakes_clover import CIPHER, NOW, InMemoryCloverStore, ScriptedOAuth

BASE = "https://apisandbox.dev.clover.com/connect"
EXTERNAL_ID = "a" * 32
REQUEST = ChargeRequest(external_id=EXTERNAL_ID, amount_cents=150050, metodo="Tarjeta", description="Venta POS")
PAYMENT = {
    "payment": {
        "id": "PAY1234567890",
        "result": "SUCCESS",
        "amount": 150050,
        "externalPaymentId": EXTERNAL_ID,
        "cardTransaction": {
            "cardType": "VISA",
            "last4": "4242",
            "first6": "411111",
            "cardholderName": "DOE/JANE",
            "authCode": "OK1234",
            "entryType": "EMV_CONTACTLESS",
            "type": "AUTH",
            "state": "CLOSED",
            "token": "tok_secret",
            "vaultedCard": {"token": "vault_secret", "expirationDate": "1230"},
            "extra": {"numInstallments": "3"},
        },
    },
    "issues": {},
}


class Clover:
    """A scripted Clover cloud: each request consumes one entry (a response, or an exception to raise)."""

    def __init__(self, *script, store=None, oauth=None):
        self.script = list(script)
        self.requests: list[httpx.Request] = []
        self.store = store or InMemoryCloverStore()
        self.oauth = oauth or ScriptedOAuth()
        self.terminal = CloverCloudTerminal(
            base_url=BASE + "/",
            tokens=CloverTokenProvider(store=self.store, oauth=self.oauth, cipher=CIPHER, now=lambda: NOW),
            get_integration=self.store.get,
            default_pos_id="mundo-uniforme-pos",
            user_agent="MundoUniformePOS/1.0.0",
            transport=httpx.MockTransport(self._handle),
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        entry = self.script.pop(0)
        if isinstance(entry, Exception):
            raise entry
        if isinstance(entry, tuple):
            status, body = entry
            return httpx.Response(status, json=body)
        return httpx.Response(entry, json={"message": "error", "type": "ERROR"})

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


def body_of(request: httpx.Request) -> dict:
    return json.loads(request.content)


def test_it_is_a_payment_terminal():
    assert isinstance(Clover().terminal, PaymentTerminal)


# --- charge ---------------------------------------------------------------------------------------


def test_charge_sends_cents_external_id_headers_and_idempotency_key():
    clover = Clover((200, PAYMENT))

    result = clover.terminal.charge(REQUEST)

    request = clover.last
    assert (request.method, str(request.url)) == ("POST", f"{BASE}/v1/payments")
    assert body_of(request) == {"amount": 150050, "externalPaymentId": EXTERNAL_ID, "final": True}
    assert request.headers["authorization"] == "Bearer access-1"
    assert request.headers["x-clover-device-id"] == "C0123"
    assert request.headers["x-pos-id"] == "mundo-uniforme-pos"
    assert request.headers["user-agent"] == "MundoUniformePOS/1.0.0"
    assert request.headers["idempotency-key"] == EXTERNAL_ID
    assert request.headers["content-type"] == "application/json"
    assert request.headers["x-clover-timeout"] == "120"
    assert request.extensions["timeout"]["read"] == 150.0

    assert result.outcome is ChargeOutcome.APPROVED
    assert result.provider_payment_id == "PAY1234567890"
    assert (result.card_brand, result.last4, result.auth_code) == ("VISA", "4242", "OK1234")
    assert (result.entry_type, result.installments) == ("EMV_CONTACTLESS", 3)


def test_charge_keeps_no_card_data_beyond_brand_and_last4(caplog):
    caplog.set_level(logging.DEBUG)
    result = Clover((200, PAYMENT)).terminal.charge(REQUEST)

    stored = json.dumps(result.raw)
    for secret in ("411111", "DOE/JANE", "tok_secret", "vault_secret", "1230"):
        assert secret not in stored
        assert secret not in caplog.text
    assert result.raw["payment"]["cardTransaction"]["cardType"] == "VISA"
    for logged in ("4242", "OK1234", "access-1"):
        assert logged not in caplog.text


def test_pos_id_of_the_integration_row_wins():
    clover = Clover((200, PAYMENT), store=InMemoryCloverStore(pos_id="POS-7"))

    clover.terminal.charge(REQUEST)

    assert clover.last.headers["x-pos-id"] == "POS-7"


@pytest.mark.parametrize(
    ("result", "outcome"),
    [
        ("SUCCESS", ChargeOutcome.APPROVED),
        ("FAIL", ChargeOutcome.DECLINED),
        ("VOIDED", ChargeOutcome.DECLINED),
        ("INITIATED", ChargeOutcome.UNKNOWN),
        ("AUTH", ChargeOutcome.UNKNOWN),
        ("VOIDING", ChargeOutcome.UNKNOWN),
        (None, ChargeOutcome.UNKNOWN),
    ],
)
def test_charge_result_mapping(result, outcome):
    payment = {"payment": {"id": "PAY1", "result": result, "cardTransaction": {"cardType": "MC", "last4": "0001"}}}

    charged = Clover((200, payment)).terminal.charge(REQUEST)

    assert charged.outcome is outcome
    assert charged.installments is None
    if outcome is ChargeOutcome.DECLINED:
        assert charged.error == "Pago rechazado"


def test_charge_200_without_a_payment_is_unknown():
    assert Clover((200, {"issues": {"x": 1}})).terminal.charge(REQUEST).outcome is ChargeOutcome.UNKNOWN
    assert Clover((200, ["not", "an", "object"])).terminal.charge(REQUEST).outcome is ChargeOutcome.UNKNOWN


def test_charge_209_is_cancelled():
    assert Clover(209).terminal.charge(REQUEST).outcome is ChargeOutcome.CANCELLED


def test_charge_400_is_a_bad_request_and_503_is_busy():
    with pytest.raises(TerminalBadRequest):
        Clover(400).terminal.charge(REQUEST)
    with pytest.raises(TerminalBusy):
        Clover(503).terminal.charge(REQUEST)


@pytest.mark.parametrize(
    "failure",
    [
        500,
        504,
        501,
        415,
        502,
        httpx.ReadTimeout("timed out"),
        httpx.ConnectError("no route"),
        httpx.RemoteProtocolError("server disconnected"),
    ],
    ids=lambda failure: str(failure) if isinstance(failure, int) else type(failure).__name__,
)
def test_charge_without_a_definite_answer_is_unknown_and_never_retried(failure):
    clover = Clover(failure)

    result = clover.terminal.charge(REQUEST)

    assert result.outcome is ChargeOutcome.UNKNOWN
    assert len(clover.requests) == 1


def test_charge_without_a_device_serial_is_not_sent():
    clover = Clover(store=InMemoryCloverStore(device_id=None))

    with pytest.raises(TerminalBadRequest):
        clover.terminal.charge(REQUEST)

    assert clover.requests == []


# --- 401 and token renewal ---------------------------------------------------------------------------


def test_401_renews_the_token_and_retries_once_with_the_same_idempotency_key():
    clover = Clover(401, (200, PAYMENT))

    result = clover.terminal.charge(REQUEST)

    assert result.outcome is ChargeOutcome.APPROVED
    first, second = clover.requests
    assert first.headers["authorization"] == "Bearer access-1"
    assert second.headers["authorization"] == "Bearer access-2"
    assert first.headers["idempotency-key"] == second.headers["idempotency-key"] == EXTERNAL_ID
    assert clover.oauth.refresh_calls == ["refresh-1"]
    assert clover.store.access == "access-2"


def test_401_twice_is_unavailable():
    clover = Clover(401, 401)

    with pytest.raises(TerminalUnavailable):
        clover.terminal.find_by_external_id(EXTERNAL_ID)

    assert len(clover.requests) == 2
    assert clover.oauth.refresh_calls == ["refresh-1"]


def test_401_with_a_refresh_token_clover_rejects_disables_the_integration():
    clover = Clover(401, oauth=ScriptedOAuth(CloverOAuthRejected("/oauth/v2/refresh")))

    with pytest.raises(TerminalUnavailable) as error:
        clover.terminal.charge(REQUEST)

    assert str(error.value) == "Reconectá Clover desde Configuración"
    assert clover.store.row["habilitado"] is False
    assert len(clover.requests) == 1


def test_an_expiring_token_is_renewed_before_the_request():
    clover = Clover((200, {"connected": True}), store=InMemoryCloverStore(expires_in=120))

    assert clover.terminal.ping() is True

    assert clover.last.headers["authorization"] == "Bearer access-2"


def test_without_a_connected_account_nothing_is_sent():
    clover = Clover(store=InMemoryCloverStore(access=None, refresh=None))

    with pytest.raises(TerminalUnavailable):
        clover.terminal.charge(REQUEST)
    assert clover.terminal.ping() is False
    assert clover.requests == []


# --- find_by_external_id ---------------------------------------------------------------------------


def test_lookup_returns_the_payment():
    clover = Clover((200, PAYMENT))

    found = clover.terminal.find_by_external_id(EXTERNAL_ID)

    request = clover.last
    assert (request.method, str(request.url)) == ("GET", f"{BASE}/v1/payments/external/{EXTERNAL_ID}")
    assert "idempotency-key" not in request.headers
    assert request.headers["x-clover-device-id"] == "C0123"
    assert (found.outcome, found.provider_payment_id, found.last4) == (ChargeOutcome.APPROVED, "PAY1234567890", "4242")


@pytest.mark.parametrize(
    "response",
    [(404, {"message": "Not Found"}), (400, {"message": "Payment not found", "type": "ERROR"})],
    ids=["404", "400-not-found"],
)
def test_lookup_definitive_not_found_is_none(response):
    assert Clover(response).terminal.find_by_external_id(EXTERNAL_ID) is None


@pytest.mark.parametrize(
    "failure",
    [500, 503, 504, 209, 501, httpx.ReadTimeout("timed out"), httpx.ConnectError("down")],
    ids=lambda failure: str(failure) if isinstance(failure, int) else type(failure).__name__,
)
def test_lookup_transient_failures_raise_instead_of_answering_none(failure):
    with pytest.raises(TerminalUnavailable):
        Clover(failure).terminal.find_by_external_id(EXTERNAL_ID)


def test_lookup_other_400_is_a_bad_request_not_a_missing_payment():
    with pytest.raises(TerminalBadRequest):
        Clover((400, {"message": "Invalid device", "type": "ERROR"})).terminal.find_by_external_id(EXTERNAL_ID)


# --- refund -----------------------------------------------------------------------------------------


def test_full_refund():
    clover = Clover((200, {"refund": {"id": "REF1", "amount": 150050}, "paymentId": "PAY1"}))

    result = clover.terminal.refund("PAY1", None)

    request = clover.last
    assert (request.method, str(request.url)) == ("POST", f"{BASE}/v1/payments/PAY1/refunds")
    assert body_of(request) == {"fullRefund": True}
    assert request.headers["idempotency-key"] == "refund-PAY1-full"
    assert (result.outcome, result.refund_id) == (RefundOutcome.DONE, "REF1")


def test_partial_refund_sends_cents_and_a_key_per_amount():
    clover = Clover((200, {"refund": {"id": "REF2", "amount": 5000}}))

    result = clover.terminal.refund("PAY1", 5000)

    assert body_of(clover.last) == {"amount": 5000}
    assert clover.last.headers["idempotency-key"] == "refund-PAY1-5000"
    assert result.outcome is RefundOutcome.DONE


def test_refund_outcomes_by_status():
    assert Clover(209).terminal.refund("PAY1", None).outcome is RefundOutcome.FAILED
    assert Clover(500).terminal.refund("PAY1", None).outcome is RefundOutcome.UNKNOWN
    assert Clover(504).terminal.refund("PAY1", None).outcome is RefundOutcome.UNKNOWN
    assert Clover(httpx.ReadTimeout("slow")).terminal.refund("PAY1", None).outcome is RefundOutcome.UNKNOWN
    assert Clover((200, {"payment": {}})).terminal.refund("PAY1", None).outcome is RefundOutcome.UNKNOWN
    with pytest.raises(TerminalBadRequest):
        Clover(400).terminal.refund("PAY1", None)
    with pytest.raises(TerminalBusy):
        Clover(503).terminal.refund("PAY1", None)


# --- device ------------------------------------------------------------------------------------------


def test_ping():
    clover = Clover((200, {"connected": True}))
    assert clover.terminal.ping() is True
    assert (clover.last.method, str(clover.last.url)) == ("GET", f"{BASE}/v1/device/ping")

    assert Clover((200, {"connected": False})).terminal.ping() is False
    assert Clover(503).terminal.ping() is True  # busy = reachable
    assert Clover(504).terminal.ping() is False
    assert Clover(httpx.ConnectError("down")).terminal.ping() is False
    assert Clover(store=InMemoryCloverStore(device_id=" ")).terminal.ping() is False


def test_status():
    clover = Clover((200, {"status": "WAITING_FOR_CUSTOMER"}))
    assert clover.terminal.status() is TerminalStatus.WAITING_FOR_CUSTOMER
    assert (clover.last.method, str(clover.last.url)) == ("GET", f"{BASE}/v1/device/status")

    assert Clover((200, {"status": "IDLE"})).terminal.status() is TerminalStatus.IDLE
    assert Clover((200, {"status": "REBOOTING"})).terminal.status() is TerminalStatus.UNKNOWN
    assert Clover(503).terminal.status() is TerminalStatus.BUSY
    with pytest.raises(TerminalUnavailable):
        Clover(504).terminal.status()


def test_cancel_current():
    clover = Clover(200)
    clover.terminal.cancel_current()
    assert (clover.last.method, str(clover.last.url)) == ("POST", f"{BASE}/v1/device/cancel")
    assert "idempotency-key" not in clover.last.headers

    with pytest.raises(TerminalUnavailable):
        Clover(500).terminal.cancel_current()
    with pytest.raises(TerminalUnavailable):
        Clover(httpx.ConnectError("down")).terminal.cancel_current()


def test_show_welcome_swallows_client_errors():
    clover = Clover(200)
    clover.terminal.show_welcome()
    assert (clover.last.method, str(clover.last.url)) == ("POST", f"{BASE}/v1/device/welcome")

    for status in (400, 404, 415):
        Clover(status).terminal.show_welcome()
    with pytest.raises(TerminalUnavailable):
        Clover(500).terminal.show_welcome()


# --- behind the charge orchestration -------------------------------------------------------------------


def test_network_cut_during_a_charge_is_reconciled_without_charging_twice():
    from app.api.auth_deps import AppUser
    from app.schemas.pagos import CobroTerminalCreate
    from app.services.pago_service import PagoService
    from tests.fakes_pagos import InMemoryPagoStore

    # charge: no answer; first lookup: device still busy; second lookup: the payment went through; welcome.
    clover = Clover(httpx.ReadTimeout("cut"), 503, (200, PAYMENT), 200)
    store = InMemoryPagoStore(total=1500.5)
    service = PagoService(
        terminal=clover.terminal,
        store=store,
        provider="clover",
        audit=lambda *args, **kwargs: None,
        sleep=lambda seconds: None,
        requires_oauth=True,
    )
    user = AppUser(id="00000000-0000-0000-0000-000000000002", email="e@example.com", rol="empleado")
    cart = CobroTerminalCreate(
        metodo_pago="Tarjeta", items=[{"variante_id": "11111111-1111-4111-8111-111111111111", "cantidad": 1}]
    )

    service.iniciar_cobro(cart, user, schedule=lambda job, pago_id: job(pago_id))

    pago = store.only()
    assert pago["estado"] == "venta_registrada"
    assert (pago["proveedor_payment_id"], pago["tarjeta_marca"], pago["tarjeta_ultimos4"]) == ("PAY1234567890", "VISA", "4242")
    assert (pago["codigo_autorizacion"], pago["cuotas"], pago["tipo_ingreso"]) == ("OK1234", 3, "EMV_CONTACTLESS")
    charges = [request for request in clover.requests if request.url.path.endswith("/v1/payments")]
    assert len(charges) == 1
    assert body_of(charges[0])["amount"] == 150050
    assert charges[0].headers["idempotency-key"] == pago["external_payment_id"]
    assert clover.requests[-1].url.path.endswith("/v1/device/welcome")
    assert "411111" not in json.dumps(pago["respuesta"]) and "DOE" not in json.dumps(pago["respuesta"])
