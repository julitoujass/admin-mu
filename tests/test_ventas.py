from datetime import datetime, timezone

import pytest
from postgrest.exceptions import APIError

from app.api.v1.endpoints import ventas as ventas_endpoints
from app.core.timeutils import ARGENTINA_TZ, local_day_bounds_utc
from app.services import venta_service
from tests.fakes import Counted, FakeSupabase

USER_ID = "00000000-0000-0000-0000-000000000001"
EMPLOYEE_ID = "00000000-0000-0000-0000-000000000002"
VARIANT_A = "11111111-1111-4111-8111-111111111111"
VARIANT_B = "33333333-3333-4333-8333-333333333333"
CLIENT_ID = "44444444-4444-4444-8444-444444444444"
SALE_ROW = {
    "id": "22222222-2222-4222-8222-222222222222",
    "created_at": "2026-11-11T15:00:00+00:00",
    "subtotal": 3000.0,
    "descuento_aplicado": 0,
    "recargo_aplicado": 0,
    "total": 3000.0,
    "total_costo": 1200.0,
    "metodo_pago": "Efectivo",
    "estado": "completada",
    "usuario_id": USER_ID,
}
SALE_PUBLIC = {
    "id": SALE_ROW["id"],
    "created_at": "2026-11-11T15:00:00Z",
    "subtotal": 3000.0,
    "descuento_aplicado": 0.0,
    "recargo_aplicado": 0.0,
    "total": 3000.0,
    "metodo_pago": "Efectivo",
    "estado": "completada",
}


def sale_body(**overrides):
    body = {"metodo_pago": "Efectivo", "items": [{"variante_id": VARIANT_A, "cantidad": 2}]}
    body.update(overrides)
    return body


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase(SALE_ROW)
    monkeypatch.setattr(venta_service, "supabase", fake)
    return fake


def test_create_sale_calls_rpc_with_server_side_data_only(auth_client, db):
    body = sale_body(
        cliente_id=CLIENT_ID,
        total=1,  # client totals are ignored
        items=[
            {"variante_id": VARIANT_A, "cantidad": 2, "precio_unitario": 0.01},
            {"variante_id": VARIANT_B, "cantidad": 1},
        ],
    )

    response = auth_client.post("/api/v1/ventas/", json=body)

    assert response.status_code == 200
    assert len(db.queries) == 1
    call = db.queries[0]
    assert (call.kind, call.name) == ("rpc", "registrar_venta")
    assert call.params == {
        "p_usuario_id": USER_ID,
        "p_metodo_pago": "Efectivo",
        "p_items": [
            {"variante_id": VARIANT_A, "cantidad": 2},
            {"variante_id": VARIANT_B, "cantidad": 1},
        ],
        "p_cliente_id": CLIENT_ID,
        "p_idempotency_key": None,
        "p_descuento_tipo": None,
        "p_descuento_valor": 0,
        "p_recargo_tipo": None,
        "p_recargo_valor": 0,
        "p_es_admin": True,
    }


def test_create_sale_response_hides_cost(auth_client, db):
    response = auth_client.post("/api/v1/ventas/", json=sale_body())

    assert response.json() == SALE_PUBLIC


def test_create_sale_accepts_row_wrapped_in_a_list(auth_client, monkeypatch):
    monkeypatch.setattr(venta_service, "supabase", FakeSupabase([SALE_ROW]))

    response = auth_client.post("/api/v1/ventas/", json=sale_body())

    assert response.status_code == 200
    assert response.json()["id"] == SALE_ROW["id"]


def test_idempotency_key_header_is_forwarded(auth_client, db):
    response = auth_client.post("/api/v1/ventas/", json=sale_body(), headers={"Idempotency-Key": "  sale-abc-123 "})

    assert response.status_code == 200
    assert db.queries[0].params["p_idempotency_key"] == "sale-abc-123"


def test_idempotency_key_of_100_chars_is_accepted(auth_client, db):
    response = auth_client.post("/api/v1/ventas/", json=sale_body(), headers={"Idempotency-Key": "k" * 100})

    assert response.status_code == 200
    assert db.queries[0].params["p_idempotency_key"] == "k" * 100


def test_idempotency_key_too_long_is_rejected(auth_client, db):
    response = auth_client.post("/api/v1/ventas/", json=sale_body(), headers={"Idempotency-Key": "k" * 101})

    assert response.status_code == 400
    assert response.json() == {"detail": "Idempotency-Key no puede superar los 100 caracteres"}
    assert db.queries == []


@pytest.mark.parametrize(
    "body",
    [
        sale_body(metodo_pago="Bitcoin"),
        sale_body(items=[]),
        sale_body(items=[{"variante_id": VARIANT_A, "cantidad": 0}]),
        sale_body(items=[{"variante_id": VARIANT_A, "cantidad": -1}]),
        sale_body(items=[{"variante_id": VARIANT_A, "cantidad": 1001}]),
        sale_body(items=[{"variante_id": "not-a-uuid", "cantidad": 1}]),
        sale_body(items=[{"variante_id": VARIANT_A, "cantidad": 1}] * 201),
    ],
    ids=["metodo_pago", "no-items", "cantidad-0", "cantidad-negative", "cantidad-too-big", "bad-uuid", "too-many-items"],
)
def test_invalid_sale_is_rejected_before_reaching_the_database(auth_client, db, body):
    response = auth_client.post("/api/v1/ventas/", json=body)

    assert response.status_code == 422
    assert db.queries == []


@pytest.mark.parametrize(
    ("code", "status", "message"),
    [
        ("MU001", 400, "No hay una sesión de caja abierta"),
        ("MU002", 409, "Stock insuficiente para la variante"),
        ("MU003", 400, "La venta no tiene ítems"),
        ("MU004", 404, "Variante no encontrada"),
        ("MU007", 403, "El descuento máximo permitido para empleados es 10%"),
    ],
)
def test_database_business_errors_reach_the_client(auth_client, monkeypatch, code, status, message):
    error = APIError({"code": code, "message": message, "details": None, "hint": None})
    monkeypatch.setattr(venta_service, "supabase", FakeSupabase(error))

    response = auth_client.post("/api/v1/ventas/", json=sale_body())

    assert response.status_code == status
    assert response.json() == {"detail": message}


# --- discount / surcharge ----------------------------------------------------


def test_discount_and_surcharge_are_forwarded(auth_client, db):
    body = sale_body(descuento={"tipo": "porcentaje", "valor": 15}, recargo={"tipo": "monto", "valor": 250.5})

    response = auth_client.post("/api/v1/ventas/", json=body)

    assert response.status_code == 200
    params = db.queries[0].params
    assert (params["p_descuento_tipo"], params["p_descuento_valor"]) == ("porcentaje", 15)
    assert (params["p_recargo_tipo"], params["p_recargo_valor"]) == ("monto", 250.5)


def test_employee_sale_is_not_flagged_as_admin(employee_client, db):
    response = employee_client.post("/api/v1/ventas/", json=sale_body(descuento={"tipo": "monto", "valor": 10}))

    assert response.status_code == 200
    params = db.queries[0].params
    assert params["p_es_admin"] is False
    assert params["p_usuario_id"] == EMPLOYEE_ID


def test_sale_response_tolerates_null_amounts(auth_client, monkeypatch):
    row = {**SALE_ROW, "descuento_aplicado": None, "recargo_aplicado": None}
    monkeypatch.setattr(venta_service, "supabase", FakeSupabase(row))

    response = auth_client.post("/api/v1/ventas/", json=sale_body())

    assert response.json() == SALE_PUBLIC


@pytest.mark.parametrize(
    "extra",
    [
        {"descuento": {"tipo": "otro", "valor": 1}},
        {"descuento": {"tipo": "monto", "valor": -1}},
        {"descuento": {"tipo": "porcentaje", "valor": 100.5}},
        {"descuento": {"tipo": "monto"}},
        {"recargo": {"tipo": "otro", "valor": 1}},
        {"recargo": {"tipo": "monto", "valor": -0.01}},
        {"recargo": {"tipo": "porcentaje", "valor": 101}},
    ],
    ids=["d-tipo", "d-negative", "d-over-100", "d-no-valor", "r-tipo", "r-negative", "r-over-100"],
)
def test_invalid_discount_or_surcharge_is_rejected(auth_client, db, extra):
    response = auth_client.post("/api/v1/ventas/", json=sale_body(**extra))

    assert response.status_code == 422
    assert db.queries == []


def test_amount_discount_above_100_is_allowed(auth_client, db):
    response = auth_client.post("/api/v1/ventas/", json=sale_body(descuento={"tipo": "monto", "valor": 500}))

    assert response.status_code == 200


# --- GET /ventas/hoy ---------------------------------------------------------


def test_day_bounds_use_argentina_midnight():
    now = datetime(2026, 11, 11, 22, 30, tzinfo=ARGENTINA_TZ)

    assert local_day_bounds_utc(now) == ("2026-11-11T03:00:00Z", "2026-11-12T03:00:00Z")


def test_day_bounds_convert_other_timezones_to_argentina_first():
    # 01:00 UTC on the 12th is still 22:00 of the 11th in Argentina.
    now = datetime(2026, 11, 12, 1, 0, tzinfo=timezone.utc)

    assert local_day_bounds_utc(now) == ("2026-11-11T03:00:00Z", "2026-11-12T03:00:00Z")


def test_sales_today_filters_by_argentina_day(auth_client, monkeypatch):
    fake = FakeSupabase([SALE_ROW])
    monkeypatch.setattr(venta_service, "supabase", fake)
    monkeypatch.setattr(venta_service, "_now_local", lambda: datetime(2026, 11, 12, 0, 30, tzinfo=ARGENTINA_TZ))

    response = auth_client.get("/api/v1/ventas/hoy")

    assert response.status_code == 200
    assert response.json() == [SALE_PUBLIC]
    query = fake.queries[0]
    assert (query.kind, query.name) == ("table", "ventas")
    assert query.args_of("select") == [
        ("id, created_at, subtotal, descuento_aplicado, recargo_aplicado, total, metodo_pago, estado",)
    ]
    assert query.args_of("eq") == [("estado", "completada")]
    assert query.args_of("gte") == [("created_at", "2026-11-12T03:00:00Z")]
    assert query.args_of("lt") == [("created_at", "2026-11-13T03:00:00Z")]


def test_sales_today_pages_until_an_empty_page(auth_client, monkeypatch):
    def rows(count, start):
        return [{**SALE_ROW, "id": f"00000000-0000-4000-8000-{start + i:012d}"} for i in range(count)]

    fake = FakeSupabase(rows(1000, 0), rows(3, 1000))
    monkeypatch.setattr(venta_service, "supabase", fake)

    response = auth_client.get("/api/v1/ventas/hoy")

    assert len(response.json()) == 1003
    assert [q.args_of("range") for q in fake.executed] == [[(0, 999)], [(1000, 1999)], [(1003, 2002)]]


# --- GET /ventas/ ------------------------------------------------------------

SALE_ID = SALE_ROW["id"]
LIST_ROW = {
    "id": SALE_ID,
    "created_at": "2026-11-11T15:00:00+00:00",
    "subtotal": 3000.0,
    "descuento_aplicado": 300.0,
    "recargo_aplicado": None,
    "total": 2700.0,
    "metodo_pago": "Efectivo",
    "estado": "completada",
    "cliente": {"id": CLIENT_ID, "nombre": "Ana"},
    "usuario": {"id": USER_ID, "nombre": "Admin"},
}
LIST_ITEM = {
    "id": SALE_ID,
    "created_at": "2026-11-11T15:00:00Z",
    "subtotal": 3000.0,
    "descuento_aplicado": 300.0,
    "recargo_aplicado": 0.0,
    "total": 2700.0,
    "metodo_pago": "Efectivo",
    "estado": "completada",
    "cliente": {"id": CLIENT_ID, "nombre": "Ana"},
    "usuario": {"id": USER_ID, "nombre": "Admin"},
    "total_devuelto": 0.0,
}
BASE_SELECT = (
    "id, created_at, subtotal, descuento_aplicado, recargo_aplicado, total, metodo_pago, estado, "
    "cliente:clientes(id, nombre), usuario:perfiles!usuario_id(id, nombre)"
)
LIST_SELECT = BASE_SELECT + ", devoluciones(monto)"
RETURNS_SELECT = (
    "devoluciones(id, created_at, motivo, monto, metodo_pago, usuario:perfiles!usuario_id(id, nombre), "
    "items:devolucion_items(variante_id, cantidad, monto))"
)


def use_db(monkeypatch, *responses):
    fake = FakeSupabase(*responses)
    monkeypatch.setattr(venta_service, "supabase", fake)
    return fake


def calls_of(query, method):
    return [(args, kwargs) for name, args, kwargs in query.calls if name == method]


def test_sales_list_returns_items_and_exact_total(employee_client, monkeypatch):
    fake = use_db(monkeypatch, Counted([LIST_ROW, {**LIST_ROW, "cliente": None, "usuario": None}], 137))

    response = employee_client.get("/api/v1/ventas/")

    assert response.status_code == 200
    assert response.json() == {"items": [LIST_ITEM, {**LIST_ITEM, "cliente": None, "usuario": None}], "total": 137}
    query = fake.queries[0]
    assert (query.kind, query.name) == ("table", "ventas")
    assert calls_of(query, "select") == [((LIST_SELECT,), {"count": "exact"})]
    assert calls_of(query, "order") == [(("created_at",), {"desc": True}), (("id",), {"desc": True})]
    assert query.args_of("range") == [(0, 49)]
    assert query.args_of("eq") == []
    assert query.args_of("gte") == []
    assert query.args_of("lt") == []


def test_sales_list_applies_filters_and_paging(auth_client, monkeypatch):
    fake = use_db(monkeypatch, Counted([], 0))

    response = auth_client.get(
        "/api/v1/ventas/",
        params={
            "desde": "2026-11-01",
            "hasta": "2026-11-11",
            "metodo_pago": "QR",
            "estado": "anulada",
            "cliente_id": CLIENT_ID,
            "usuario_id": USER_ID,
            "limit": 20,
            "offset": 40,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}
    query = fake.queries[0]
    # Argentina local dates, inclusive: [Nov 1 00:00 -03, Nov 12 00:00 -03)
    assert query.args_of("gte") == [("created_at", "2026-11-01T03:00:00Z")]
    assert query.args_of("lt") == [("created_at", "2026-11-12T03:00:00Z")]
    assert sorted(query.args_of("eq")) == sorted(
        [("metodo_pago", "QR"), ("estado", "anulada"), ("cliente_id", CLIENT_ID), ("usuario_id", USER_ID)]
    )
    assert query.args_of("range") == [(40, 59)]


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
        {"desde": "11/11/2026"},
        {"hasta": "nope"},
        {"metodo_pago": "Bitcoin"},
        {"estado": "borrada"},
        {"cliente_id": "not-a-uuid"},
        {"usuario_id": "not-a-uuid"},
    ],
    ids=["limit-0", "limit-201", "offset", "desde", "hasta", "metodo_pago", "estado", "cliente_id", "usuario_id"],
)
def test_sales_list_rejects_invalid_filters(auth_client, monkeypatch, params):
    fake = use_db(monkeypatch)

    response = auth_client.get("/api/v1/ventas/", params=params)

    assert response.status_code == 422
    assert fake.queries == []


def test_sales_list_never_exposes_cost(auth_client, monkeypatch):
    use_db(monkeypatch, Counted([{**LIST_ROW, "total_costo": 1200.0}], 1))

    response = auth_client.get("/api/v1/ventas/")

    assert "total_costo" not in response.text


# --- GET /ventas/{id} ----------------------------------------------------------

DETAIL_ROW = {
    **LIST_ROW,
    "motivo_anulacion": None,
    "anulada_at": None,
    "anulada_por": None,
    "total_costo": 1200.0,
    "items": [
        {
            "variante_id": VARIANT_A,
            "cantidad": 2,
            "precio_unitario": 1500.0,
            "costo_unitario": 600.0,
            "subtotal": 3000.0,
            "variante": {"sku": "REM-001", "talle": "M", "color": "Azul", "producto": {"nombre": "Remera"}},
        },
        {
            "variante_id": VARIANT_B,
            "cantidad": 1,
            "precio_unitario": 10.0,
            "costo_unitario": 4.0,
            "subtotal": 10.0,
            "variante": None,
        },
    ],
}
DETAIL_EMPLOYEE = {
    **LIST_ITEM,
    "motivo_anulacion": None,
    "anulada_at": None,
    "anulada_por": None,
    "devoluciones": [],
    "pago": None,
    "items": [
        {
            "variante_id": VARIANT_A,
            "sku": "REM-001",
            "producto_nombre": "Remera",
            "talle": "M",
            "color": "Azul",
            "cantidad": 2,
            "cantidad_devuelta": 0,
            "precio_unitario": 1500.0,
            "subtotal": 3000.0,
        },
        {
            "variante_id": VARIANT_B,
            "sku": None,
            "producto_nombre": None,
            "talle": None,
            "color": None,
            "cantidad": 1,
            "cantidad_devuelta": 0,
            "precio_unitario": 10.0,
            "subtotal": 10.0,
        },
    ],
}
DETAIL_ADMIN = {
    **DETAIL_EMPLOYEE,
    "total_costo": 1200.0,
    "items": [
        {**DETAIL_EMPLOYEE["items"][0], "costo_unitario": 600.0},
        {**DETAIL_EMPLOYEE["items"][1], "costo_unitario": 4.0},
    ],
}
DETAIL_SELECT = (
    BASE_SELECT
    + ", motivo_anulacion, anulada_at, anulada_por:perfiles!anulada_por(id, nombre){total_cost}, "
    + "items:venta_detalle(variante_id, cantidad, precio_unitario, subtotal{cost}, "
    + "variante:producto_variantes(sku, talle, color, producto:productos(nombre))), "
    + RETURNS_SELECT
    + ", pago:pagos_externos!pago_externo_id(metodo_pago, tarjeta_marca, tarjeta_ultimos4, codigo_autorizacion, cuotas, proveedor)"
)
ADMIN_DETAIL_SELECT = DETAIL_SELECT.format(cost=", costo_unitario", total_cost=", total_costo")
EMPLOYEE_DETAIL_SELECT = DETAIL_SELECT.format(cost="", total_cost="")


def without_costs(row):
    items = [{k: v for k, v in item.items() if k != "costo_unitario"} for item in row["items"]]
    return {**{k: v for k, v in row.items() if k != "total_costo"}, "items": items}


def test_sale_detail_for_admin_includes_costs(auth_client, monkeypatch):
    fake = use_db(monkeypatch, [DETAIL_ROW])

    response = auth_client.get(f"/api/v1/ventas/{SALE_ID}")

    assert response.status_code == 200
    assert response.json() == DETAIL_ADMIN
    query = fake.queries[0]
    assert (query.kind, query.name) == ("table", "ventas")
    assert query.args_of("select") == [(ADMIN_DETAIL_SELECT,)]
    assert query.args_of("eq") == [("id", SALE_ID)]


def test_sale_detail_includes_the_terminal_payment_that_paid_it(employee_client, monkeypatch):
    pago = {
        "metodo_pago": "Tarjeta",
        "tarjeta_marca": "VISA",
        "tarjeta_ultimos4": "4242",
        "codigo_autorizacion": "123456",
        "cuotas": 3,
        "proveedor": "fake",
    }
    use_db(monkeypatch, [{**without_costs(DETAIL_ROW), "pago": {**pago, "respuesta": {"raw": True}}}])

    response = employee_client.get(f"/api/v1/ventas/{SALE_ID}")

    assert response.status_code == 200
    assert response.json() == {**DETAIL_EMPLOYEE, "pago": pago}


def test_sale_detail_for_employee_never_reads_costs(employee_client, monkeypatch):
    fake = use_db(monkeypatch, [without_costs(DETAIL_ROW)])

    response = employee_client.get(f"/api/v1/ventas/{SALE_ID}")

    assert response.status_code == 200
    assert response.json() == DETAIL_EMPLOYEE
    assert fake.queries[0].args_of("select") == [(EMPLOYEE_DETAIL_SELECT,)]


def test_sale_detail_hides_costs_from_employee_even_if_the_row_has_them(employee_client, monkeypatch):
    use_db(monkeypatch, [DETAIL_ROW])

    response = employee_client.get(f"/api/v1/ventas/{SALE_ID}")

    assert response.status_code == 200
    assert "costo" not in response.text


def test_cancelled_sale_detail_shows_who_and_why(auth_client, monkeypatch):
    row = {
        **DETAIL_ROW,
        "estado": "anulada",
        "motivo_anulacion": "Error de carga",
        "anulada_at": "2026-11-11T16:00:00+00:00",
        "anulada_por": {"id": USER_ID, "nombre": "Admin"},
    }
    use_db(monkeypatch, [row])

    body = auth_client.get(f"/api/v1/ventas/{SALE_ID}").json()

    assert body["estado"] == "anulada"
    assert body["motivo_anulacion"] == "Error de carga"
    assert body["anulada_at"] == "2026-11-11T16:00:00Z"
    assert body["anulada_por"] == {"id": USER_ID, "nombre": "Admin"}


def test_missing_sale_is_404(auth_client, monkeypatch):
    use_db(monkeypatch, [])

    response = auth_client.get(f"/api/v1/ventas/{SALE_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Venta no encontrada"}


def test_sale_detail_rejects_malformed_id(auth_client, monkeypatch):
    fake = use_db(monkeypatch)

    response = auth_client.get("/api/v1/ventas/not-a-uuid")

    assert response.status_code == 422
    assert fake.queries == []


# --- POST /ventas/{id}/anular ---------------------------------------------------


def test_cancel_sale_calls_rpc_and_returns_the_detail(auth_client, monkeypatch):
    cancelled = {**DETAIL_ROW, "estado": "anulada", "motivo_anulacion": "Error de carga"}
    fake = use_db(monkeypatch, {**SALE_ROW, "estado": "anulada"}, [cancelled])

    response = auth_client.post(f"/api/v1/ventas/{SALE_ID}/anular", json={"motivo": "  Error de carga "})

    assert response.status_code == 200
    assert response.json() == {**DETAIL_ADMIN, "estado": "anulada", "motivo_anulacion": "Error de carga"}
    rpc, detail = fake.queries
    assert (rpc.kind, rpc.name) == ("rpc", "anular_venta")
    assert rpc.params == {"p_venta_id": SALE_ID, "p_usuario_id": USER_ID, "p_motivo": "Error de carga"}
    assert (detail.kind, detail.name) == ("table", "ventas")
    assert detail.args_of("select") == [(ADMIN_DETAIL_SELECT,)]
    assert detail.args_of("eq") == [("id", SALE_ID)]


def test_cancel_sale_is_admin_only(employee_client, monkeypatch):
    fake = use_db(monkeypatch)

    response = employee_client.post(f"/api/v1/ventas/{SALE_ID}/anular", json={"motivo": "x"})

    assert response.status_code == 403
    assert fake.queries == []


@pytest.mark.parametrize("body", [{}, {"motivo": ""}, {"motivo": "   "}, {"motivo": "x" * 201}])
def test_cancel_sale_requires_a_reason(auth_client, monkeypatch, body):
    fake = use_db(monkeypatch)

    response = auth_client.post(f"/api/v1/ventas/{SALE_ID}/anular", json=body)

    assert response.status_code == 422
    assert fake.queries == []


@pytest.mark.parametrize(
    ("code", "status", "message"),
    [
        ("MU004", 404, "Venta no encontrada"),
        ("MU006", 409, "La venta ya está anulada"),
        ("MU001", 400, "Abrí la caja para registrar la devolución en efectivo"),
        ("MU003", 400, "El motivo de anulación es obligatorio"),
    ],
)
def test_cancel_sale_business_errors(auth_client, monkeypatch, code, status, message):
    use_db(monkeypatch, APIError({"code": code, "message": message, "details": None, "hint": None}))

    response = auth_client.post(f"/api/v1/ventas/{SALE_ID}/anular", json={"motivo": "Error"})

    assert response.status_code == status
    assert response.json() == {"detail": message}


def test_cancel_sale_is_audited(auth_client, monkeypatch):
    recorded = []
    monkeypatch.setattr(ventas_endpoints, "audit", lambda *args, **kwargs: recorded.append((args, kwargs)))
    use_db(monkeypatch, {**SALE_ROW, "estado": "anulada"}, [DETAIL_ROW])

    auth_client.post(f"/api/v1/ventas/{SALE_ID}/anular", json={"motivo": "Error de carga"})

    assert len(recorded) == 1
    args, kwargs = recorded[0]
    assert args[2:] == ("CANCEL_SALE", "ventas")
    assert kwargs["entidad_id"] == SALE_ID
    assert kwargs["payload"] == {"motivo": "Error de carga"}
