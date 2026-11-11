import pytest
from postgrest.exceptions import APIError

from app.services import caja_service
from tests.fakes import FakeSupabase

USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER = "99999999-9999-4999-8999-999999999999"
SESSION_ID = "55555555-5555-4555-8555-555555555555"
SESSION_OWNER = "88888888-8888-4888-8888-888888888888"
OPEN_SESSION = {
    "id": SESSION_ID,
    "usuario_id": SESSION_OWNER,
    "fecha_apertura": "2026-11-11T12:00:00+00:00",
    "fecha_cierre": None,
    "monto_apertura": 1000.0,
    "monto_esperado_efectivo": None,
    "monto_real_efectivo": None,
    "estado": "abierta",
    "observaciones": None,
}
CLOSED_SESSION = {
    **OPEN_SESSION,
    "estado": "cerrada",
    "fecha_cierre": "2026-11-11T21:00:00+00:00",
    "monto_esperado_efectivo": 4500.0,
    "monto_real_efectivo": 4400.0,
    "observaciones": "Faltan 100",
}
MOVEMENT_ROW = {
    "id": "66666666-6666-4666-8666-666666666666",
    "sesion_id": SESSION_ID,
    "tipo": "egreso",
    "monto": 250.0,
    "motivo": "Pago proveedor",
    "creado_en": "2026-11-11T13:00:00+00:00",
}
SUMMARY = {
    "sesion_id": SESSION_ID,
    "estado": "abierta",
    "fecha_apertura": "2026-11-11T12:00:00+00:00",
    "monto_apertura": 1000,
    "ventas_efectivo": 3000,
    "ventas_tarjeta": 1500.5,
    "ventas_qr": 0,
    "cantidad_ventas": 4,
    "ingresos": 500,
    "egresos": 250,
    "esperado_efectivo": 4250,
}


def use_db(monkeypatch, *responses):
    fake = FakeSupabase(*responses)
    monkeypatch.setattr(caja_service, "supabase", fake)
    return fake


def db_error(code, message="internal-detail"):
    return APIError({"code": code, "message": message, "details": None, "hint": None})


# --- apertura ----------------------------------------------------------------


def test_open_register_takes_user_from_token_not_from_body(auth_client, monkeypatch):
    db = use_db(monkeypatch, [], [OPEN_SESSION])

    response = auth_client.post("/api/v1/caja/apertura", json={"monto_apertura": 1000, "usuario_id": OTHER_USER})

    assert response.status_code == 200
    insert = db.table_calls("sesiones_caja")[1]
    assert insert.args_of("insert") == [({"usuario_id": USER_ID, "monto_apertura": 1000.0, "estado": "abierta"},)]


def test_open_register_does_not_require_usuario_id(auth_client, monkeypatch):
    use_db(monkeypatch, [], [OPEN_SESSION])

    response = auth_client.post("/api/v1/caja/apertura", json={"monto_apertura": 0})

    assert response.status_code == 200
    assert response.json()["id"] == SESSION_ID


def test_open_register_rejects_negative_amount(auth_client, monkeypatch):
    db = use_db(monkeypatch)

    response = auth_client.post("/api/v1/caja/apertura", json={"monto_apertura": -1})

    assert response.status_code == 422
    assert db.queries == []


def test_open_register_with_one_already_open_is_a_conflict(auth_client, monkeypatch):
    db = use_db(monkeypatch, [OPEN_SESSION])

    response = auth_client.post("/api/v1/caja/apertura", json={"monto_apertura": 100})

    assert response.status_code == 409
    assert response.json() == {"detail": "Ya existe una sesión de caja abierta."}
    assert len(db.queries) == 1  # nothing was inserted


def test_open_register_race_hits_unique_index_and_is_a_conflict(auth_client, monkeypatch):
    use_db(monkeypatch, [], db_error("23505"))

    response = auth_client.post("/api/v1/caja/apertura", json={"monto_apertura": 100})

    assert response.status_code == 409
    assert response.json() == {"detail": "Ya existe una sesión de caja abierta."}


# --- cierre ------------------------------------------------------------------


def test_close_register_uses_cerrar_caja_rpc(auth_client, monkeypatch):
    db = use_db(monkeypatch, [OPEN_SESSION], CLOSED_SESSION)

    response = auth_client.post(
        "/api/v1/caja/cierre", json={"monto_real_efectivo": 4400, "observaciones": "Faltan 100"}
    )

    assert response.status_code == 200
    assert [q.name for q in db.rpc_calls()] == ["cerrar_caja"]
    assert db.rpc_calls()[0].params == {
        "p_sesion_id": SESSION_ID,
        "p_monto_real_efectivo": 4400.0,
        "p_observaciones": "Faltan 100",
    }
    assert response.json() == {
        "id": SESSION_ID,
        "usuario_id": SESSION_OWNER,
        "fecha_apertura": "2026-11-11T12:00:00Z",
        "fecha_cierre": "2026-11-11T21:00:00Z",
        "monto_apertura": 1000.0,
        "monto_esperado_efectivo": 4500.0,
        "monto_real_efectivo": 4400.0,
        "estado": "cerrada",
        "observaciones": "Faltan 100",
    }


def test_close_register_without_open_session(auth_client, monkeypatch):
    db = use_db(monkeypatch, [])

    response = auth_client.post("/api/v1/caja/cierre", json={"monto_real_efectivo": 10})

    assert response.status_code == 400
    assert response.json() == {"detail": "No hay sesión de caja abierta."}
    assert db.rpc_calls() == []


def test_close_register_already_closed_maps_mu005(auth_client, monkeypatch):
    use_db(monkeypatch, [OPEN_SESSION], db_error("MU005", "La sesión de caja ya está cerrada"))

    response = auth_client.post("/api/v1/caja/cierre", json={"monto_real_efectivo": 10})

    assert response.status_code == 409
    assert response.json() == {"detail": "La sesión de caja ya está cerrada"}


@pytest.mark.parametrize(
    "body",
    [{"monto_real_efectivo": -0.01}, {"monto_real_efectivo": 10, "observaciones": "x" * 501}],
    ids=["negative-amount", "long-notes"],
)
def test_close_register_validation(auth_client, monkeypatch, body):
    db = use_db(monkeypatch)

    response = auth_client.post("/api/v1/caja/cierre", json=body)

    assert response.status_code == 422
    assert db.queries == []


# --- resumen -----------------------------------------------------------------


def test_summary_of_open_session(auth_client, monkeypatch):
    db = use_db(monkeypatch, [OPEN_SESSION], SUMMARY)

    response = auth_client.get("/api/v1/caja/resumen")

    assert response.status_code == 200
    assert db.rpc_calls()[0].name == "resumen_caja"
    assert db.rpc_calls()[0].params == {"p_sesion_id": SESSION_ID}
    assert response.json() == {
        "sesion_id": SESSION_ID,
        "estado": "abierta",
        "fecha_apertura": "2026-11-11T12:00:00Z",
        "monto_apertura": 1000.0,
        "ventas_efectivo": 3000.0,
        "ventas_tarjeta": 1500.5,
        "ventas_qr": 0.0,
        "cantidad_ventas": 4,
        "ingresos": 500.0,
        "egresos": 250.0,
        "esperado_efectivo": 4250.0,
    }


def test_summary_without_open_session_is_null(auth_client, monkeypatch):
    db = use_db(monkeypatch, [])

    response = auth_client.get("/api/v1/caja/resumen")

    assert response.status_code == 200
    assert response.json() is None
    assert db.rpc_calls() == []


def test_summary_requires_authentication(client):
    assert client.get("/api/v1/caja/resumen").status_code in (401, 403)


# --- movimiento --------------------------------------------------------------


def test_movement_response_has_the_same_shape_as_the_listing(auth_client, monkeypatch):
    db = use_db(monkeypatch, [OPEN_SESSION], [MOVEMENT_ROW])

    response = auth_client.post(
        "/api/v1/caja/movimiento", json={"tipo": "egreso", "monto": 250, "motivo": "  Pago proveedor "}
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": MOVEMENT_ROW["id"],
        "sesion_id": SESSION_ID,
        "tipo": "egreso",
        "monto": 250.0,
        "descripcion": "Pago proveedor",
        "created_at": "2026-11-11T13:00:00Z",
    }
    insert = db.table_calls("movimientos_caja")[0]
    assert insert.args_of("insert") == [
        ({"sesion_id": SESSION_ID, "tipo": "egreso", "monto": 250.0, "motivo": "Pago proveedor"},)
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"tipo": "retiro", "monto": 10, "motivo": "x"},
        {"tipo": "ingreso", "monto": 0, "motivo": "x"},
        {"tipo": "ingreso", "monto": -5, "motivo": "x"},
        {"tipo": "ingreso", "monto": 10, "motivo": ""},
        {"tipo": "ingreso", "monto": 10, "motivo": "   "},
        {"tipo": "ingreso", "monto": 10, "motivo": "x" * 201},
        {"tipo": "ingreso", "monto": 10},
    ],
    ids=["tipo", "monto-0", "monto-negative", "motivo-empty", "motivo-blank", "motivo-long", "motivo-missing"],
)
def test_movement_validation(auth_client, monkeypatch, body):
    db = use_db(monkeypatch)

    response = auth_client.post("/api/v1/caja/movimiento", json=body)

    assert response.status_code == 422
    assert db.queries == []


# --- sesiones ----------------------------------------------------------------


def test_sessions_default_pagination(auth_client, monkeypatch):
    db = use_db(monkeypatch, [CLOSED_SESSION])

    response = auth_client.get("/api/v1/caja/sesiones")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert db.queries[0].args_of("range") == [(0, 199)]


def test_sessions_custom_pagination(auth_client, monkeypatch):
    db = use_db(monkeypatch, [])

    auth_client.get("/api/v1/caja/sesiones?limit=50&offset=100")

    assert db.queries[0].args_of("range") == [(100, 149)]


@pytest.mark.parametrize("params", ["limit=0", "limit=1001", "offset=-1"])
def test_sessions_pagination_bounds(auth_client, monkeypatch, params):
    db = use_db(monkeypatch)

    response = auth_client.get(f"/api/v1/caja/sesiones?{params}")

    assert response.status_code == 422
    assert db.queries == []
