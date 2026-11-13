"""HTTP contract of `/api/v1/pagos` and `/api/v1/integraciones/terminal`."""

import asyncio
from typing import get_args

import pytest
from postgrest.exceptions import APIError

from app import main
from app.api.auth_deps import AppUser, get_current_user
from app.api.deps import get_pago_service
from app.integrations.payment_terminal.fake import FakeTerminal
from app.integrations.payment_terminal.port import ChargeOutcome
from app.main import app
from app.services import log_service, pago_reconciler, venta_service
from app.services.audit import AuditEvent, record_audit
from app.services.pago_service import PagoService
from tests.fakes import FakeSupabase
from tests.fakes_pagos import InMemoryPagoStore

API = "/api/v1"
ADMIN_ID = "00000000-0000-0000-0000-000000000001"
EMPLOYEE_ID = "00000000-0000-0000-0000-000000000002"
VARIANT_A = "11111111-1111-4111-8111-111111111111"
MISSING_ID = "99999999-9999-4999-8999-999999999999"
BODY = {"metodo_pago": "Tarjeta", "items": [{"variante_id": VARIANT_A, "cantidad": 2}]}


class Setup:
    def __init__(self, terminal=None, **store_options):
        self.terminal = terminal or FakeTerminal()
        self.store = InMemoryPagoStore(**store_options)
        self.audits = []
        self.service = PagoService(
            terminal=self.terminal,
            store=self.store,
            provider="fake",
            audit=lambda usuario_id, evento, **kwargs: self.audits.append((usuario_id, evento, kwargs)),
            sleep=lambda seconds: None,
        )


@pytest.fixture
def pagos(client):
    """Wire the endpoints to an in-memory service; `pagos(terminal=..., habilitado=...)` builds another one."""

    def install(terminal=None, **store_options):
        setup = Setup(terminal, **store_options)
        app.dependency_overrides[get_pago_service] = lambda: setup.service
        return setup

    return install


def login(user_id, rol):
    app.dependency_overrides[get_current_user] = lambda: AppUser(id=user_id, email=f"{rol}@example.com", rol=rol)


def test_mu011_is_a_conflict_with_the_database_message(auth_client, monkeypatch):
    message = "El total cambió desde que se inició el cobro (1600.00 vs 1500.00)"
    error = APIError({"code": "MU011", "message": message, "details": "internal", "hint": None})
    monkeypatch.setattr(venta_service, "supabase", FakeSupabase(error))

    response = auth_client.post(f"{API}/ventas/", json={**BODY, "metodo_pago": "Efectivo"})

    assert response.status_code == 409
    assert response.json() == {"detail": message}


def test_audit_events_include_the_payment_ones():
    assert {
        "CHARGE_STARTED",
        "CHARGE_APPROVED",
        "CHARGE_FAILED",
        "CHARGE_UNKNOWN",
        "CHARGE_CANCELLED",
        "REFUND_DONE",
        "TERMINAL_SETTINGS",
    } <= set(get_args(AuditEvent))


def test_record_audit_writes_the_log_row(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(log_service, "supabase", fake)

    record_audit(ADMIN_ID, "CHARGE_APPROVED", entidad="pagos_externos", entidad_id="p1", payload={"monto": 10})

    [query] = fake.table_calls("logs")
    [(row,)] = query.args_of("insert")
    assert row["usuario_id"] == ADMIN_ID
    assert row["evento"] == "CHARGE_APPROVED"
    assert row["entidad"] == "pagos_externos"
    assert row["entidad_id"] == "p1"
    assert row["payload_enviado"] == {"monto": 10}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/pagos/terminal"),
        ("get", f"/pagos/{MISSING_ID}"),
        ("post", f"/pagos/{MISSING_ID}/cancelar"),
        ("get", "/pagos/"),
        ("post", f"/pagos/{MISSING_ID}/conciliar"),
        ("get", "/integraciones/terminal"),
        ("patch", "/integraciones/terminal"),
    ],
)
def test_every_route_needs_a_token(client, pagos, method, path):
    pagos()

    response = getattr(client, method)(f"{API}{path}")

    assert response.status_code in (401, 403)


def test_start_charge_answers_202_and_the_job_finishes_the_sale(employee_client, pagos):
    setup = pagos()

    response = employee_client.post(f"{API}/pagos/terminal", json=BODY)

    pago = setup.store.only()
    assert response.status_code == 202
    assert response.json() == {"pago_id": pago["id"], "total": 1500.0, "estado": "pendiente"}
    assert pago["usuario_id"] == EMPLOYEE_ID

    # The test client runs background tasks before returning, so the job already ran.
    polled = employee_client.get(f"{API}/pagos/{pago['id']}")
    assert polled.status_code == 200
    body = polled.json()
    assert set(body) == {
        "id",
        "estado",
        "metodo_pago",
        "monto",
        "venta_id",
        "tarjeta_marca",
        "tarjeta_ultimos4",
        "codigo_autorizacion",
        "cuotas",
        "error",
        "created_at",
        "updated_at",
    }
    assert body["estado"] == "venta_registrada"
    assert body["venta_id"] == setup.store.sales[pago["id"]]["id"]
    assert (body["metodo_pago"], body["monto"]) == ("Tarjeta", 1500.0)
    assert (body["tarjeta_marca"], body["tarjeta_ultimos4"], body["cuotas"]) == ("VISA", "4242", 1)


@pytest.mark.parametrize(
    "body",
    [
        {**BODY, "metodo_pago": "Efectivo"},
        {**BODY, "items": []},
        {"metodo_pago": "QR"},
        {**BODY, "descuento": {"tipo": "porcentaje", "valor": 101}},
    ],
    ids=["efectivo", "no-items", "missing-items", "bad-discount"],
)
def test_start_charge_validates_the_body(employee_client, pagos, body):
    setup = pagos()

    response = employee_client.post(f"{API}/pagos/terminal", json=body)

    assert response.status_code == 422
    assert setup.store.pagos == {}


def test_qr_is_accepted(employee_client, pagos):
    setup = pagos()

    response = employee_client.post(f"{API}/pagos/terminal", json={**BODY, "metodo_pago": "QR"})

    assert response.status_code == 202
    assert setup.store.only()["metodo_pago"] == "QR"
    assert setup.terminal.charges[0].metodo == "QR"


def test_start_charge_with_the_integration_disabled_is_a_conflict(employee_client, pagos):
    pagos(habilitado=False)

    response = employee_client.post(f"{API}/pagos/terminal", json=BODY)

    assert response.status_code == 409
    assert response.json() == {"detail": "La integración con el terminal está deshabilitada"}


def test_second_charge_is_a_conflict(employee_client, pagos):
    pagos(FakeTerminal(script=[ChargeOutcome.UNKNOWN], lookups=[ChargeOutcome.UNKNOWN] * 3))
    assert employee_client.post(f"{API}/pagos/terminal", json=BODY).status_code == 202

    response = employee_client.post(f"{API}/pagos/terminal", json=BODY)

    assert response.status_code == 409
    assert response.json() == {"detail": "Ya hay un cobro en curso"}


def test_quote_business_errors_keep_their_status_and_message(employee_client, pagos):
    setup = pagos()
    setup.store.quote_error = APIError(
        {"code": "MU002", "message": "Stock insuficiente para la variante X", "details": None, "hint": None}
    )

    response = employee_client.post(f"{API}/pagos/terminal", json=BODY)

    assert response.status_code == 409
    assert response.json() == {"detail": "Stock insuficiente para la variante X"}


def test_only_the_owner_or_an_admin_can_read_and_cancel(client, pagos):
    setup = pagos(FakeTerminal(script=[ChargeOutcome.DECLINED]))
    login(EMPLOYEE_ID, "empleado")
    pago_id = client.post(f"{API}/pagos/terminal", json=BODY).json()["pago_id"]

    login("00000000-0000-0000-0000-000000000003", "empleado")
    assert client.get(f"{API}/pagos/{pago_id}").status_code == 404
    assert client.post(f"{API}/pagos/{pago_id}/cancelar").status_code == 404

    login(ADMIN_ID, "admin")
    assert client.get(f"{API}/pagos/{pago_id}").json()["estado"] == "rechazado"
    cancelled = client.post(f"{API}/pagos/{pago_id}/cancelar")
    assert cancelled.status_code == 200
    assert cancelled.json()["estado"] == "rechazado"
    assert setup.terminal.cancel_calls == 0


def test_unknown_or_malformed_charge_ids(auth_client, pagos):
    pagos()

    assert auth_client.get(f"{API}/pagos/{MISSING_ID}").json() == {"detail": "Pago no encontrado"}
    assert auth_client.get(f"{API}/pagos/{MISSING_ID}").status_code == 404
    assert auth_client.get(f"{API}/pagos/not-a-uuid").status_code == 422
    assert auth_client.post(f"{API}/pagos/{MISSING_ID}/conciliar").status_code == 404


def test_cancel_while_the_charge_is_on_the_terminal(employee_client, pagos):
    setup = pagos()
    pago = setup.store.insert_pago(
        {
            "proveedor": "fake",
            "external_payment_id": "e" * 32,
            "estado": "enviado",
            "metodo_pago": "Tarjeta",
            "monto": 1500.0,
            "carrito": {"items": [], "es_admin": False},
            "sesion_caja": None,
            "usuario_id": EMPLOYEE_ID,
        }
    )

    response = employee_client.post(f"{API}/pagos/{pago['id']}/cancelar")

    assert response.status_code == 200
    assert response.json()["estado"] == "enviado"
    assert setup.terminal.cancel_calls == 1


def test_review_list_and_forced_reconciliation_are_admin_only(client, pagos):
    setup = pagos(FakeTerminal(script=[ChargeOutcome.UNKNOWN], lookups=[ChargeOutcome.UNKNOWN] * 3))
    login(EMPLOYEE_ID, "empleado")
    pago_id = client.post(f"{API}/pagos/terminal", json=BODY).json()["pago_id"]

    assert client.get(f"{API}/pagos/").status_code == 403
    assert client.post(f"{API}/pagos/{pago_id}/conciliar").status_code == 403

    login(ADMIN_ID, "admin")
    listing = client.get(f"{API}/pagos/", params={"estado": "indeterminado", "limit": 10})
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    [item] = body["items"]
    assert item["id"] == pago_id
    assert item["estado"] == "indeterminado"
    assert item["usuario_id"] == EMPLOYEE_ID
    assert item["intentos_conciliacion"] == 0
    assert item["proveedor"] == "fake"
    assert "carrito" not in item and "respuesta" not in item
    assert client.get(f"{API}/pagos/", params={"estado": "rechazado"}).json() == {"items": [], "total": 0}

    setup.terminal.lookups.append(ChargeOutcome.APPROVED)
    reconciled = client.post(f"{API}/pagos/{pago_id}/conciliar")
    assert reconciled.status_code == 200
    assert reconciled.json()["estado"] == "venta_registrada"
    assert reconciled.json()["intentos_conciliacion"] == 1


@pytest.mark.parametrize(
    "params",
    [{"estado": "pagado"}, {"limit": 0}, {"limit": 201}, {"offset": -1}],
    ids=["estado", "limit-0", "limit-201", "offset"],
)
def test_review_list_validates_its_filters(auth_client, pagos, params):
    pagos()

    assert auth_client.get(f"{API}/pagos/", params=params).status_code == 422


def test_terminal_status_is_visible_to_any_user_without_device_details(employee_client, pagos):
    setup = pagos()
    setup.store.integration.update(device_id="C0123", pos_id="POS-1")

    response = employee_client.get(f"{API}/integraciones/terminal")

    assert response.status_code == 200
    assert response.json() == {
        "proveedor": "fake",
        "habilitado": True,
        "conectado": True,
        "conectado_oauth": False,
        "merchant_id": None,
        "device_id": None,
        "pos_id": None,
        "updated_at": None,
    }


def test_merchant_id_is_only_shown_to_admins(client, pagos):
    setup = pagos()
    setup.store.integration.update(merchant_id="M123", access_token_cifrado="enc-a", refresh_token_cifrado="enc-r")

    login(EMPLOYEE_ID, "empleado")
    body = client.get(f"{API}/integraciones/terminal").json()
    assert (body["conectado_oauth"], body["merchant_id"]) == (True, None)

    login(ADMIN_ID, "admin")
    body = client.get(f"{API}/integraciones/terminal").json()
    assert (body["conectado_oauth"], body["merchant_id"]) == (True, "M123")
    assert not any("token" in key for key in body)


def test_admin_updates_the_terminal_settings(client, pagos):
    setup = pagos(habilitado=False)
    login(EMPLOYEE_ID, "empleado")
    assert client.patch(f"{API}/integraciones/terminal", json={"habilitado": True}).status_code == 403

    login(ADMIN_ID, "admin")
    response = client.patch(f"{API}/integraciones/terminal", json={"habilitado": True, "device_id": " C0123 "})

    assert response.status_code == 200
    body = response.json()
    assert (body["proveedor"], body["habilitado"], body["conectado"]) == ("fake", True, True)
    assert (body["device_id"], body["pos_id"]) == ("C0123", None)
    assert body["updated_at"] is not None
    assert setup.store.integration["habilitado"] is True
    assert [evento for _, evento, _ in setup.audits] == ["TERMINAL_SETTINGS"]
    # Admins also see the device details when reading.
    assert client.get(f"{API}/integraciones/terminal").json()["device_id"] == "C0123"


@pytest.mark.parametrize(
    "body",
    [{}, {"habilitado": None}, {"habilitado": "maybe"}, {"device_id": "x" * 65}, {"proveedor": "clover"}],
    ids=["empty", "null-flag", "bad-flag", "long-device", "unknown-only"],
)
def test_terminal_settings_validation(auth_client, pagos, body):
    setup = pagos()

    assert auth_client.patch(f"{API}/integraciones/terminal", json=body).status_code == 422
    assert setup.audits == []


def test_blank_device_fields_are_cleared(auth_client, pagos):
    setup = pagos()
    setup.store.integration.update(device_id="C0123")

    response = auth_client.patch(f"{API}/integraciones/terminal", json={"device_id": "  "})

    assert response.status_code == 200
    assert setup.store.integration["device_id"] is None


# --- background reconciliation loop ------------------------------------------------------------


def test_reconciler_is_disabled_in_tests():
    assert main.settings.PAYMENT_RECONCILE_INTERVAL_SECONDS == 0
    assert pago_reconciler.start_reconciler(lambda: None, 0) is None


def test_reconciler_sweeps_at_startup_and_then_periodically_surviving_errors():
    calls = []

    def sweep():
        calls.append(len(calls))
        if len(calls) == 2:
            raise RuntimeError("database down")

    async def scenario():
        task = pago_reconciler.start_reconciler(sweep, 0.01)
        while len(calls) < 4:
            await asyncio.sleep(0.005)
        await pago_reconciler.stop_reconciler(task)
        return task

    task = asyncio.run(scenario())

    assert len(calls) >= 4
    assert task.done()


def test_lifespan_starts_and_stops_the_reconciler_when_enabled(monkeypatch):
    from fastapi.testclient import TestClient

    swept = []
    stopped = []
    monkeypatch.setattr(main.settings, "PAYMENT_RECONCILE_INTERVAL_SECONDS", 60)
    monkeypatch.setattr(main, "get_pago_service", lambda: type("S", (), {"conciliar_pendientes": swept.append})())
    real_start, real_stop = pago_reconciler.start_reconciler, pago_reconciler.stop_reconciler

    def start(sweep, interval):
        assert interval == 60
        return real_start(lambda: sweep("startup"), interval)

    async def stop(task):
        stopped.append(task)
        await real_stop(task)

    monkeypatch.setattr(main, "start_reconciler", start)
    monkeypatch.setattr(main, "stop_reconciler", stop)

    with TestClient(app) as test_client:
        assert test_client.get("/health").status_code == 200

    assert len(stopped) == 1 and stopped[0].done()
    assert swept[:1] == ["startup"]  # the first sweep runs right at startup


def test_payment_settings_defaults_and_backoff_parsing():
    from pydantic import ValidationError

    from app.core.config import Settings

    base = {"SUPABASE_URL": "http://localhost", "SUPABASE_KEY": "key", "_env_file": None}
    defaults = Settings(**base, PAYMENT_RECONCILE_INTERVAL_SECONDS=60)
    assert defaults.PAYMENT_STALE_SECONDS == 180
    assert defaults.PAYMENT_RECONCILE_MAX_ATTEMPTS == 10
    assert defaults.payment_reconcile_backoff == (2.0, 5.0, 10.0)
    assert Settings(**base, PAYMENT_RECONCILE_BACKOFF="0, 0.5,").payment_reconcile_backoff == (0.0, 0.5)
    for bad in ({"PAYMENT_TERMINAL": "stripe"}, {"PAYMENT_RECONCILE_BACKOFF": "2,x"}, {"PAYMENT_RECONCILE_BACKOFF": "-1"}):
        with pytest.raises(ValidationError):
            Settings(**base, **bad)
