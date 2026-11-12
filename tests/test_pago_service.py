"""Charge orchestration (`PagoService`) against a scripted `FakeTerminal` and an in-memory store."""

import logging
from uuid import UUID

import pytest
from postgrest.exceptions import APIError

from app.api.auth_deps import AppUser
from app.core.exceptions import PagoError
from app.integrations.payment_terminal.fake import FakeTerminal
from app.integrations.payment_terminal.port import (
    ChargeOutcome,
    ChargeResult,
    RefundOutcome,
    TerminalBadRequest,
    TerminalBusy,
    TerminalUnavailable,
)
from app.schemas.pagos import CobroTerminalCreate
from app.services.pago_ports import SaleRejected
from app.services.pago_service import PagoService
from tests.fakes_pagos import SESSION_ID, InMemoryPagoStore

ADMIN = AppUser(id="00000000-0000-0000-0000-000000000001", email="admin@example.com", rol="admin")
EMPLOYEE = AppUser(id="00000000-0000-0000-0000-000000000002", email="empleado@example.com", rol="empleado")
OTHER_EMPLOYEE = AppUser(id="00000000-0000-0000-0000-000000000003", email="otro@example.com", rol="empleado")
VARIANT_A = "11111111-1111-4111-8111-111111111111"
CLIENT_ID = "44444444-4444-4444-8444-444444444444"

UNKNOWN = ChargeOutcome.UNKNOWN
APPROVED = ChargeOutcome.APPROVED
DECLINED = ChargeOutcome.DECLINED
CANCELLED = ChargeOutcome.CANCELLED


def mu_error(code, message):
    return APIError({"code": code, "message": message, "details": None, "hint": None})


class Harness:
    def __init__(self, terminal=None, store=None, **options):
        self.terminal = terminal or FakeTerminal()
        self.store = store or InMemoryPagoStore()
        self.audits = []
        self.sleeps = []
        self.scheduled = []
        self.service = PagoService(
            terminal=self.terminal,
            store=self.store,
            provider="fake",
            audit=lambda usuario_id, evento, **kwargs: self.audits.append((usuario_id, evento, kwargs)),
            sleep=self.sleeps.append,
            now=lambda: self.store.now,
            **options,
        )

    def start(self, user=EMPLOYEE, **overrides):
        body = {"metodo_pago": "Tarjeta", "items": [{"variante_id": VARIANT_A, "cantidad": 2}], **overrides}
        return self.service.iniciar_cobro(
            CobroTerminalCreate(**body), user, schedule=lambda func, *args: self.scheduled.append((func, args))
        )

    def run_job(self):
        """Run the scheduled background job(s), as FastAPI would after sending the response."""
        for func, args in list(self.scheduled):
            func(*args)

    def charge(self, **overrides):
        started = self.start(**overrides)
        self.run_job()
        return self.store.get_pago(started["pago_id"])

    @property
    def events(self):
        return [evento for _, evento, _ in self.audits]


# --- starting a charge ---------------------------------------------------------


def test_start_quotes_inserts_a_pending_charge_and_schedules_the_job():
    h = Harness()

    started = h.start(
        cliente_id=CLIENT_ID,
        descuento={"tipo": "porcentaje", "valor": 5},
        recargo={"tipo": "monto", "valor": 100},
    )

    pago = h.store.only()
    assert started == {"pago_id": pago["id"], "total": 1500.0, "estado": "pendiente"}
    assert pago["estado"] == "pendiente"
    assert pago["monto"] == 1500.0
    assert pago["metodo_pago"] == "Tarjeta"
    assert pago["proveedor"] == "fake"
    assert pago["usuario_id"] == EMPLOYEE.id
    assert pago["sesion_caja"] == SESSION_ID
    assert 0 < len(pago["external_payment_id"]) <= 32
    assert pago["carrito"] == {
        "items": [{"variante_id": VARIANT_A, "cantidad": 2}],
        "cliente_id": CLIENT_ID,
        "descuento": {"tipo": "porcentaje", "valor": 5.0},
        "recargo": {"tipo": "monto", "valor": 100.0},
        "es_admin": False,
    }
    assert h.store.quote_calls == [(pago["carrito"], False)]
    assert h.terminal.charges == []  # nothing is charged inside the request
    assert [(func, args) for func, args in h.scheduled] == [(h.service.ejecutar_cobro, (pago["id"],))]
    assert h.events == ["CHARGE_STARTED"]


def test_admin_charges_are_quoted_without_the_employee_discount_limit():
    h = Harness()

    h.start(user=ADMIN)

    assert h.store.quote_calls[0][1] is True
    assert h.store.only()["carrito"]["es_admin"] is True


def test_start_is_refused_when_the_integration_is_disabled():
    h = Harness(store=InMemoryPagoStore(habilitado=False))

    with pytest.raises(PagoError) as error:
        h.start()

    assert (error.value.status_code, error.value.message) == (409, "La integración con el terminal está deshabilitada")
    assert h.store.pagos == {} and h.scheduled == [] and h.store.quote_calls == []


def test_second_charge_while_one_is_active_is_a_conflict():
    h = Harness()
    h.start()

    with pytest.raises(PagoError) as error:
        h.start()

    assert (error.value.status_code, error.value.message) == (409, "Ya hay un cobro en curso")
    assert len(h.store.pagos) == 1 and len(h.scheduled) == 1


def test_quote_errors_propagate_and_nothing_is_inserted():
    h = Harness()
    h.store.quote_error = mu_error("MU002", "Stock insuficiente para la variante X")

    with pytest.raises(APIError):
        h.start()

    assert h.store.pagos == {} and h.scheduled == []


def test_a_zero_total_cannot_be_charged():
    h = Harness(store=InMemoryPagoStore(total=0))

    with pytest.raises(PagoError) as error:
        h.start()

    assert error.value.status_code == 400
    assert h.store.pagos == {}


def test_start_needs_an_open_cash_session():
    h = Harness(store=InMemoryPagoStore(session_id=None))

    with pytest.raises(PagoError) as error:
        h.start()

    assert (error.value.status_code, error.value.message) == (400, "No hay sesión de caja abierta.")


# --- the background job ----------------------------------------------------------


def test_approved_charge_registers_the_sale():
    h = Harness()

    pago = h.charge()

    assert pago["estado"] == "venta_registrada"
    assert pago["venta_id"] == h.store.sales[pago["id"]]["id"]
    assert (pago["tarjeta_marca"], pago["tarjeta_ultimos4"], pago["cuotas"]) == ("VISA", "4242", 1)
    assert pago["codigo_autorizacion"] and pago["proveedor_payment_id"]
    assert pago["error"] is None
    [request] = h.terminal.charges
    assert request.amount_cents == 150000
    assert request.external_id == pago["external_payment_id"]
    assert request.metodo == "Tarjeta"
    assert len(h.store.register_calls) == 1
    assert h.terminal.refund_calls == []
    assert h.terminal.welcome_calls == 1
    assert h.events == ["CHARGE_STARTED", "CHARGE_APPROVED", "CREATE_SALE"]


def test_amount_is_sent_in_cents_without_float_drift():
    h = Harness(store=InMemoryPagoStore(total=1234.57))

    h.charge()

    assert h.terminal.charges[0].amount_cents == 123457


def test_declined_charge_registers_nothing():
    h = Harness(FakeTerminal(script=[ChargeResult(outcome=DECLINED, error="Fondos insuficientes")]))

    pago = h.charge()

    assert (pago["estado"], pago["error"], pago["venta_id"]) == ("rechazado", "Fondos insuficientes", None)
    assert h.store.register_calls == []
    assert h.terminal.welcome_calls == 1
    assert h.events == ["CHARGE_STARTED", "CHARGE_FAILED"]


def test_charge_cancelled_on_the_device():
    h = Harness(FakeTerminal(script=[CANCELLED]))

    pago = h.charge()

    assert pago["estado"] == "cancelado"
    assert h.store.register_calls == []
    assert h.terminal.welcome_calls == 1
    assert h.events == ["CHARGE_STARTED", "CHARGE_CANCELLED"]


def test_busy_terminal_rejects_the_charge_without_reconciling():
    h = Harness(FakeTerminal(script=[TerminalBusy("device busy")]))

    pago = h.charge()

    assert (pago["estado"], pago["error"]) == ("rechazado", "Terminal ocupado")
    assert h.terminal.lookup_calls == [] and h.terminal.refund_calls == []
    assert h.events == ["CHARGE_STARTED", "CHARGE_FAILED"]


def test_bad_request_rejects_the_charge():
    h = Harness(FakeTerminal(script=[TerminalBadRequest("amount is required")]))

    pago = h.charge()

    assert pago["estado"] == "rechazado"
    assert h.terminal.lookup_calls == []


def test_unknown_result_is_reconciled_immediately_as_approved():
    h = Harness(FakeTerminal(script=[UNKNOWN], lookups=[UNKNOWN, APPROVED]))

    pago = h.charge()

    assert pago["estado"] == "venta_registrada"
    assert pago["tarjeta_ultimos4"] == "4242"
    assert len(h.terminal.charges) == 1  # never charged again
    assert h.terminal.lookup_calls == [pago["external_payment_id"]] * 2
    assert h.sleeps == [2, 5]
    assert h.events == ["CHARGE_STARTED", "CHARGE_UNKNOWN", "CHARGE_APPROVED", "CREATE_SALE"]


def test_unknown_result_is_reconciled_immediately_as_declined():
    h = Harness(FakeTerminal(script=[UNKNOWN], lookups=[DECLINED]))

    pago = h.charge()

    assert pago["estado"] == "rechazado"
    assert h.store.register_calls == []
    assert h.events == ["CHARGE_STARTED", "CHARGE_UNKNOWN", "CHARGE_FAILED"]


@pytest.mark.parametrize("failure", [TerminalUnavailable("network down"), RuntimeError("boom")])
def test_unreachable_terminal_is_an_unknown_result(failure):
    h = Harness(FakeTerminal(script=[failure], lookups=[APPROVED]))

    pago = h.charge()

    assert pago["estado"] == "venta_registrada"
    assert len(h.terminal.charges) == 1


def test_persistent_unknown_stays_indeterminate_until_the_sweep_resolves_it():
    h = Harness(FakeTerminal(script=[UNKNOWN], lookups=[UNKNOWN, None, TerminalUnavailable("down")]))

    pago = h.charge()

    assert pago["estado"] == "indeterminado"
    assert h.sleeps == [2, 5, 10]
    assert len(h.terminal.lookup_calls) == 3
    assert h.terminal.welcome_calls == 1
    # A new charge is blocked while this one is unresolved.
    with pytest.raises(PagoError):
        h.start()

    h.terminal.lookups.append(APPROVED)
    h.service.conciliar_pendientes()

    pago = h.store.get_pago(pago["id"])
    assert pago["estado"] == "venta_registrada"
    assert pago["intentos_conciliacion"] == 1
    assert len(h.terminal.charges) == 1
    assert h.sleeps == [2, 5, 10]  # the sweep does not wait


def test_backoff_is_configurable():
    h = Harness(FakeTerminal(script=[UNKNOWN], lookups=[UNKNOWN, UNKNOWN]), backoff=(0, 0))

    pago = h.charge()

    assert pago["estado"] == "indeterminado"
    assert h.sleeps == [0, 0]


def test_sweep_gives_up_after_the_maximum_attempts(caplog):
    h = Harness(FakeTerminal(script=[UNKNOWN], lookups=[UNKNOWN] * 10), backoff=(), max_attempts=2)
    pago = h.charge()

    with caplog.at_level(logging.WARNING):
        h.service.conciliar_pendientes()
        h.service.conciliar_pendientes()
        h.service.conciliar_pendientes()  # not picked up any more

    pago = h.store.get_pago(pago["id"])
    assert (pago["estado"], pago["intentos_conciliacion"]) == ("indeterminado", 2)
    assert len(h.terminal.lookup_calls) == 2
    assert "revisión" in caplog.text or "review" in caplog.text


def test_fresh_indeterminate_charge_missing_on_the_terminal_is_not_rejected_yet():
    h = Harness(FakeTerminal(script=[UNKNOWN]), backoff=())
    pago = h.charge()

    h.service.conciliar_pendientes()  # the terminal answers "not found"

    assert h.store.get_pago(pago["id"])["estado"] == "indeterminado"

    h.store.advance(181)
    h.service.conciliar_pendientes()

    pago = h.store.get_pago(pago["id"])
    assert (pago["estado"], pago["error"]) == ("rechazado", "El terminal no registra el cobro")


def crashed_while_sent(h):
    """A charge whose process died after sending it to the terminal."""
    started = h.start()
    h.store.transition(started["pago_id"], "pendiente", "enviado")
    return started["pago_id"]


def test_stale_sent_charge_is_resolved_by_the_sweep():
    h = Harness(FakeTerminal(lookups=[APPROVED]))
    pago_id = crashed_while_sent(h)

    h.store.advance(60)
    h.service.conciliar_pendientes()
    assert h.store.get_pago(pago_id)["estado"] == "enviado"  # still inside the charge window
    assert h.terminal.lookup_calls == []

    h.store.advance(121)
    h.service.conciliar_pendientes()

    pago = h.store.get_pago(pago_id)
    assert pago["estado"] == "venta_registrada"
    assert h.terminal.charges == []  # the sweep never charges
    assert len(h.store.sales) == 1


def test_stale_sent_charge_unknown_to_the_terminal_is_rejected():
    h = Harness()
    pago_id = crashed_while_sent(h)

    h.store.advance(181)
    h.service.conciliar_pendientes()

    assert h.store.get_pago(pago_id)["estado"] == "rechazado"
    h.start()  # the terminal is free again


def test_stale_sent_charge_with_unreachable_terminal_stays_for_later():
    h = Harness(FakeTerminal(lookups=[TerminalUnavailable("down")]))
    pago_id = crashed_while_sent(h)

    h.store.advance(181)
    h.service.conciliar_pendientes()

    pago = h.store.get_pago(pago_id)
    assert (pago["estado"], pago["intentos_conciliacion"]) == ("enviado", 1)


def test_stale_pending_charge_is_rejected_and_its_late_job_does_not_charge():
    h = Harness()
    started = h.start()

    h.store.advance(181)
    h.service.conciliar_pendientes()
    h.run_job()  # the job finally runs: too late

    assert h.store.get_pago(started["pago_id"])["estado"] == "rechazado"
    assert h.terminal.charges == []


def test_one_broken_charge_does_not_stop_the_sweep(caplog):
    h = Harness(FakeTerminal(lookups=[APPROVED]))
    pago_id = crashed_while_sent(h)
    h.store.advance(181)
    original = h.store.set_attempts
    calls = []

    def flaky(pago_id, attempts):
        calls.append(pago_id)
        if len(calls) == 1:
            raise RuntimeError("database down")
        original(pago_id, attempts)

    h.store.set_attempts = flaky

    h.service.conciliar_pendientes()  # must not raise
    h.service.conciliar_pendientes()

    assert h.store.get_pago(pago_id)["estado"] == "venta_registrada"


def test_job_that_runs_twice_charges_once_and_registers_one_sale():
    h = Harness()
    started = h.start()

    h.run_job()
    h.run_job()

    assert len(h.terminal.charges) == 1
    assert len(h.store.sales) == 1
    assert len(h.store.register_calls) == 1
    assert h.store.get_pago(started["pago_id"])["estado"] == "venta_registrada"


def test_job_of_a_missing_charge_does_nothing():
    h = Harness()

    h.service.ejecutar_cobro("99999999-9999-4999-8999-999999999999")

    assert h.terminal.charges == [] and h.terminal.welcome_calls == 0


def test_welcome_screen_errors_are_swallowed():
    h = Harness()
    h.terminal.show_welcome = lambda: (_ for _ in ()).throw(TerminalUnavailable("down"))

    pago = h.charge()

    assert pago["estado"] == "venta_registrada"


# --- registration failures and refunds -------------------------------------------------


@pytest.mark.parametrize("code", ["MU011", "MU002", "MU001", "XX000"])
def test_registration_rejected_by_the_database_refunds_the_charge(code):
    h = Harness()
    h.store.register_errors = [SaleRejected("Motivo del rechazo", code)]

    pago = h.charge()

    assert pago["estado"] == "reembolsado"
    assert pago["venta_id"] is None
    assert h.terminal.refund_calls == [(pago["proveedor_payment_id"], None)]  # full refund
    assert h.store.sales == {}
    assert h.terminal.welcome_calls == 1
    assert h.events == ["CHARGE_STARTED", "CHARGE_APPROVED", "CHARGE_FAILED", "REFUND_DONE"]


def test_business_error_message_is_kept_but_internal_errors_are_not():
    h = Harness()
    h.store.register_errors = [SaleRejected("El total cambió desde que se inició el cobro (1600.00 vs 1500.00)", "MU011")]
    assert h.charge()["error"] == "El total cambió desde que se inició el cobro (1600.00 vs 1500.00)"

    h = Harness()
    h.store.register_errors = [SaleRejected(None, "XX000")]
    assert h.charge()["error"] == "No se pudo registrar la venta"


@pytest.mark.parametrize("refund", [RefundOutcome.FAILED, RefundOutcome.UNKNOWN, TerminalUnavailable("down")])
def test_failed_refund_keeps_the_charge_for_admin_review(refund):
    h = Harness(FakeTerminal(refunds=[refund]))
    h.store.register_errors = [SaleRejected("El total cambió desde que se inició el cobro (1600.00 vs 1500.00)", "MU011")]

    pago = h.charge()

    assert pago["estado"] == "error_registro"
    assert "El total cambió" in pago["error"]
    assert "reembolso" in pago["error"]
    assert len(h.terminal.refund_calls) == 1  # no blind retry
    assert "REFUND_DONE" not in h.events
    # It no longer blocks the terminal.
    h.start()


def test_transport_error_while_registering_is_retried_because_it_is_idempotent():
    h = Harness()
    h.store.register_errors = [ConnectionError("server disconnected")]

    pago = h.charge()

    assert pago["estado"] == "venta_registrada"
    assert len(h.store.register_calls) == 2
    assert h.terminal.refund_calls == []


def test_unknown_registration_outcome_is_never_refunded_and_the_sweep_finishes_it():
    h = Harness()
    h.store.register_errors = [ConnectionError("down"), ConnectionError("down")]

    pago = h.charge()

    # The sale may or may not exist: refunding now could leave a sale without payment.
    assert pago["estado"] == "aprobado"
    assert h.terminal.refund_calls == []

    h.store.advance(181)
    h.service.conciliar_pendientes()

    pago = h.store.get_pago(pago["id"])
    assert pago["estado"] == "venta_registrada"
    assert len(h.store.sales) == 1
    assert len(h.terminal.charges) == 1


# --- card data hygiene --------------------------------------------------------------------


def test_sensitive_card_data_is_never_stored_or_audited():
    raw = {
        "payment": {
            "id": "P1",
            "cardTransaction": {
                "cardType": "VISA",
                "last4": "4242",
                "first6": "411111",
                "pan": "4111111111114242",
                "track2": "4111111111114242=2912",
                "cardholderName": "ANA PEREZ",
                "token": "tok_123",
                "note": "card 4111111111114242 ok",
            },
        }
    }
    approved = ChargeResult(
        outcome=APPROVED, provider_payment_id="P1", card_brand="VISA", last4="4242", auth_code="123456", raw=raw
    )
    h = Harness(FakeTerminal(script=[approved]))

    pago = h.charge()

    stored = repr(pago["respuesta"])
    assert "4111111111114242" not in stored
    for key in ("pan", "track2", "cardholderName", "token", "first6"):
        assert key not in stored
    assert pago["respuesta"]["payment"]["cardTransaction"]["cardType"] == "VISA"
    audited = repr(h.audits)
    assert "4111111111114242" not in audited and "123456" not in audited and "ANA PEREZ" not in audited
    assert "4242" in audited and "VISA" in audited  # brand and last 4 are allowed


# --- reading, cancelling, reviewing ---------------------------------------------------------


def test_owner_and_admin_can_read_a_charge_others_get_not_found():
    h = Harness()
    pago = h.charge()

    assert h.service.get_pago(pago["id"], EMPLOYEE)["id"] == pago["id"]
    assert h.service.get_pago(pago["id"], ADMIN)["id"] == pago["id"]
    for call in (
        lambda: h.service.get_pago(pago["id"], OTHER_EMPLOYEE),
        lambda: h.service.get_pago(str(UUID(int=7)), ADMIN),
        lambda: h.service.cancelar(pago["id"], OTHER_EMPLOYEE),
    ):
        with pytest.raises(PagoError) as error:
            call()
        assert (error.value.status_code, error.value.message) == (404, "Pago no encontrado")


def test_cancel_before_sending_cancels_the_charge_itself():
    h = Harness()
    started = h.start()

    pago = h.service.cancelar(started["pago_id"], EMPLOYEE)
    h.run_job()

    assert pago["estado"] == "cancelado"
    assert h.terminal.cancel_calls == 0 and h.terminal.charges == []
    assert h.events == ["CHARGE_STARTED", "CHARGE_CANCELLED"]


def test_cancel_while_sent_asks_the_terminal_and_keeps_the_state():
    h = Harness()
    pago_id = crashed_while_sent(h)

    pago = h.service.cancelar(pago_id, ADMIN)

    assert pago["estado"] == "enviado"  # the final state comes from the charge
    assert h.terminal.cancel_calls == 1


def test_cancel_of_a_finished_charge_does_not_touch_the_terminal():
    h = Harness()
    pago = h.charge()

    result = h.service.cancelar(pago["id"], EMPLOYEE)

    assert result["estado"] == "venta_registrada"
    assert h.terminal.cancel_calls == 0


def test_cancel_reports_an_unreachable_terminal():
    h = Harness()
    pago_id = crashed_while_sent(h)
    h.terminal.cancel_current = lambda: (_ for _ in ()).throw(TerminalUnavailable("down"))

    with pytest.raises(PagoError) as error:
        h.service.cancelar(pago_id, EMPLOYEE)

    assert error.value.status_code == 503


def test_admin_can_force_the_reconciliation_of_one_charge():
    h = Harness(FakeTerminal(script=[UNKNOWN], lookups=[APPROVED]), backoff=(), max_attempts=1)
    pago = h.charge()
    h.store.set_attempts(pago["id"], 5)  # the sweep already gave up

    result = h.service.conciliar_pago(pago["id"])

    assert result["estado"] == "venta_registrada"
    assert result["intentos_conciliacion"] == 6

    with pytest.raises(PagoError) as error:
        h.service.conciliar_pago(str(UUID(int=7)))
    assert error.value.status_code == 404


def test_list_filters_by_state():
    h = Harness(FakeTerminal(script=[DECLINED]))
    h.charge()
    h.charge()

    assert h.service.listar(estado="rechazado", limit=1, offset=0)["total"] == 1
    page = h.service.listar(estado=None, limit=1, offset=0)
    assert (len(page["items"]), page["total"]) == (1, 2)
    assert h.service.listar(estado="indeterminado", limit=50, offset=0) == {"items": [], "total": 0}


# --- integration settings ---------------------------------------------------------------------


def test_integration_status_reports_the_connection():
    h = Harness()
    assert h.service.estado_integracion() == {
        "proveedor": "fake",
        "habilitado": True,
        "conectado": True,
        "device_id": None,
        "pos_id": None,
        "updated_at": None,
    }

    h = Harness(FakeTerminal(connected=False), store=InMemoryPagoStore(habilitado=False))
    status = h.service.estado_integracion()
    assert (status["habilitado"], status["conectado"]) == (False, False)


def test_ping_errors_and_timeouts_mean_not_connected():
    h = Harness()
    h.terminal.ping = lambda: (_ for _ in ()).throw(TerminalUnavailable("down"))
    assert h.service.estado_integracion()["conectado"] is False

    import threading

    never = threading.Event()
    h = Harness(ping_timeout=0.05)
    h.terminal.ping = lambda: never.wait(5) or True
    assert h.service.estado_integracion()["conectado"] is False
    never.set()


def test_update_integration_settings_is_audited():
    h = Harness(store=InMemoryPagoStore(habilitado=False))

    status = h.service.actualizar_integracion({"habilitado": True, "device_id": "C0123"}, ADMIN)

    assert (status["habilitado"], status["device_id"], status["proveedor"]) == (True, "C0123", "fake")
    assert h.store.integration["updated_by"] == ADMIN.id
    assert h.store.integration["proveedor"] == "fake"
    [(usuario_id, evento, kwargs)] = h.audits
    assert (usuario_id, evento) == (ADMIN.id, "TERMINAL_SETTINGS")
    assert kwargs["payload"] == {"habilitado": True, "device_id": "C0123"}
