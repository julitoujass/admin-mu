"""Role matrix: which routes an `empleado` may use and which are admin-only."""

import pytest

from app.services import (
    auditoria_service,
    caja_service,
    catalogo_service,
    cliente_service,
    configuracion_service,
    producto_service,
    reporte_service,
    usuario_service,
    venta_service,
)
from tests.fakes import FakeSupabase

API = "/api/v1"
VARIANT_ID = "11111111-1111-4111-8111-111111111111"
PRODUCT_ID = "77777777-7777-4777-8777-777777777777"
CLIENT_ID = "22222222-2222-4222-8222-222222222222"
SESSION_ID = "55555555-5555-4555-8555-555555555555"
USER_ID = "33333333-3333-4333-8333-333333333333"

VARIANT_ROW = {
    "id": VARIANT_ID,
    "producto_id": PRODUCT_ID,
    "sku": "REM-001",
    "talle": "M",
    "color": "Azul",
    "precio_venta": 1500.0,
    "precio_costo": 678.0,
    "stock_actual": 7,
    "stock_minimo": 2,
}
PRODUCT_ROW = {"id": PRODUCT_ID, "nombre": "Remera", "variantes": [VARIANT_ROW]}
SETTINGS_ROW = {"id": 1, "nombre_negocio": "Mundo Uniforme", "descuento_max_empleado": 10}
MARCA_ROW = {"id": 1, "nombre": "Acme"}
CATEGORIA_ROW = {"id": 1, "nombre": "Remeras"}
CLIENT_ROW = {"id": CLIENT_ID, "nombre": "Ana", "created_at": "2026-11-11T12:00:00+00:00"}
OPEN_SESSION = {
    "id": SESSION_ID,
    "usuario_id": USER_ID,
    "fecha_apertura": "2026-11-11T12:00:00+00:00",
    "monto_apertura": 1000.0,
    "estado": "abierta",
}
CLOSED_SESSION = {**OPEN_SESSION, "estado": "cerrada", "fecha_cierre": "2026-11-11T21:00:00+00:00"}
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
    "ventas_efectivo": 0,
    "ventas_tarjeta": 0,
    "ventas_qr": 0,
    "cantidad_ventas": 0,
    "ingresos": 0,
    "egresos": 0,
    "esperado_efectivo": 1000,
}
SALE_ROW = {
    "id": "44444444-4444-4444-8444-444444444444",
    "created_at": "2026-11-11T12:00:00+00:00",
    "subtotal": 1500.0,
    "descuento_aplicado": 0,
    "recargo_aplicado": 0,
    "total": 1500.0,
    "total_costo": 678.0,
    "metodo_pago": "Efectivo",
    "estado": "completada",
}
SALE_ID = SALE_ROW["id"]
SALE_DETAIL_ROW = {
    **SALE_ROW,
    "cliente": None,
    "usuario": {"id": USER_ID, "nombre": "Ana"},
    "motivo_anulacion": None,
    "anulada_at": None,
    "anulada_por": None,
    "items": [
        {
            "variante_id": VARIANT_ID,
            "cantidad": 1,
            "precio_unitario": 1500.0,
            "costo_unitario": 678.0,
            "subtotal": 1500.0,
            "variante": {"sku": "REM-001", "talle": "M", "color": "Azul", "producto": {"nombre": "Remera"}},
        }
    ],
}
STOCK_MOVEMENT_ROW = {
    "id": 1,
    "created_at": "2026-11-11T12:00:00+00:00",
    "tipo": "ajuste",
    "cantidad": 1,
    "stock_resultante": 8,
    "venta_id": None,
    "motivo": "Ajuste",
    "usuario": None,
}
VARIANT_BODY = {"producto_id": PRODUCT_ID, "sku": "REM-001", "precio_venta": 1500}
STOCK_BODY = {"variante_id": VARIANT_ID, "cantidad": 1, "motivo": "Ajuste"}
SALE_BODY = {"items": [{"variante_id": VARIANT_ID, "cantidad": 1}], "metodo_pago": "Efectivo"}

SERVICE_MODULES = (
    auditoria_service,
    configuracion_service,
    caja_service,
    catalogo_service,
    cliente_service,
    producto_service,
    reporte_service,
    usuario_service,
    venta_service,
)


def use_db(monkeypatch, *responses):
    """One fake shared by every service, so any database access is recorded."""
    fake = FakeSupabase(*responses)
    for module in SERVICE_MODULES:
        monkeypatch.setattr(module, "supabase", fake)
    return fake


# (method, path, json body, database responses for a successful admin call).
# Routes with `None` responses have their admin behaviour covered in test_usuarios.py / test_pagos.py.
ADMIN_ONLY_ROUTES = [
    ("POST", "/productos/", {"nombre": "Remera"}, [[PRODUCT_ROW]]),
    ("PATCH", f"/productos/{PRODUCT_ID}", {"nombre": "Remera"}, [[PRODUCT_ROW]]),
    ("DELETE", f"/productos/{PRODUCT_ID}", None, [[], [], [PRODUCT_ROW]]),
    ("POST", "/productos/variante", VARIANT_BODY, [[VARIANT_ROW]]),
    ("PATCH", f"/productos/variante/{VARIANT_ID}", {"talle": "L"}, [[VARIANT_ROW]]),
    ("DELETE", f"/productos/variante/{VARIANT_ID}", None, [[], [VARIANT_ROW]]),
    ("PATCH", "/productos/inventario/stock", STOCK_BODY, [VARIANT_ROW]),
    ("GET", f"/productos/variante/{VARIANT_ID}/movimientos", None, [[STOCK_MOVEMENT_ROW]]),
    ("POST", f"/ventas/{SALE_ID}/anular", {"motivo": "Error de carga"}, [SALE_ROW, [SALE_DETAIL_ROW]]),
    (
        "POST",
        f"/ventas/{SALE_ID}/devoluciones",
        {"motivo": "Talle", "items": [{"variante_id": VARIANT_ID, "cantidad": 1}]},
        [SALE_ROW, [SALE_DETAIL_ROW]],
    ),
    ("PATCH", "/configuracion/", {"cuit": "20"}, [[{"id": 1}], [SETTINGS_ROW]]),
    ("PUT", f"/productos/{PRODUCT_ID}/categorias", {"categoria_ids": []}, [[PRODUCT_ROW], [], [PRODUCT_ROW]]),
    ("GET", "/auditoria/", None, [[]]),
    ("POST", "/usuarios/", None, None),
    ("POST", "/catalogos/marcas", {"nombre": "Acme"}, [[MARCA_ROW]]),
    ("PATCH", "/catalogos/marcas/1", {"nombre": "Acme"}, [[MARCA_ROW]]),
    ("DELETE", "/catalogos/marcas/1", None, [[], [MARCA_ROW]]),
    ("POST", "/catalogos/categorias", {"nombre": "Remeras"}, [[CATEGORIA_ROW]]),
    ("PATCH", "/catalogos/categorias/1", {"nombre": "Remeras"}, [[CATEGORIA_ROW]]),
    ("DELETE", "/catalogos/categorias/1", None, [[], [CATEGORIA_ROW]]),
    ("GET", "/caja/sesiones", None, [[CLOSED_SESSION]]),
    ("GET", f"/caja/sesiones/{SESSION_ID}/movimientos", None, [[MOVEMENT_ROW]]),
    ("GET", "/reportes/ventas", None, [{"total_ingresos": 0, "cantidad_operaciones": 0, "ventas_por_dia": []}]),
    ("GET", "/reportes/productos-top", None, [[]]),
    ("GET", "/reportes/cajas", None, [{"resumen_diario": [], "diferencia_total_periodo": 0}]),
    ("GET", "/usuarios/", None, [[]]),
    ("GET", "/usuarios/roles", None, [[]]),
    ("PATCH", f"/usuarios/{USER_ID}/rol", {"rol_id": 1}, None),
    ("PATCH", f"/usuarios/{USER_ID}/activo", {"activo": True}, None),
    ("GET", "/pagos/", None, None),
    ("POST", f"/pagos/{SALE_ID}/conciliar", None, None),
    ("PATCH", "/integraciones/terminal", {"habilitado": True}, None),
]

# (method, path, json body, database responses)
EMPLOYEE_ROUTES = [
    ("POST", "/ventas/", SALE_BODY, [SALE_ROW]),
    ("GET", "/ventas/hoy", None, [[SALE_ROW], []]),
    ("GET", "/ventas/", None, [[SALE_DETAIL_ROW]]),
    ("GET", f"/ventas/{SALE_ID}", None, [[SALE_DETAIL_ROW]]),
    ("GET", "/caja/estado", None, [[OPEN_SESSION]]),
    ("GET", "/caja/resumen", None, [[OPEN_SESSION], SUMMARY]),
    ("POST", "/caja/apertura", {"monto_apertura": 100}, [[], [OPEN_SESSION]]),
    ("POST", "/caja/movimiento", {"tipo": "egreso", "monto": 250, "motivo": "Pago"}, [[OPEN_SESSION], [MOVEMENT_ROW]]),
    ("GET", "/caja/movimientos", None, [[OPEN_SESSION], [MOVEMENT_ROW]]),
    ("POST", "/caja/cierre", {"monto_real_efectivo": 10}, [[OPEN_SESSION], CLOSED_SESSION]),
    ("GET", "/productos/", None, [[PRODUCT_ROW], []]),
    ("GET", "/productos/sku/REM-001", None, [[{"producto_id": PRODUCT_ID}], PRODUCT_ROW]),
    ("GET", "/catalogos/marcas", None, [[MARCA_ROW]]),
    ("GET", "/catalogos/categorias", None, [[CATEGORIA_ROW]]),
    ("GET", "/clientes/", None, [[CLIENT_ROW]]),
    ("POST", "/clientes/", {"nombre": "Ana"}, [[CLIENT_ROW]]),
    ("PATCH", f"/clientes/{CLIENT_ID}", {"nombre": "Ana"}, [[CLIENT_ROW]]),
    ("GET", "/usuarios/me", None, []),
    ("GET", "/configuracion/", None, [[SETTINGS_ROW]]),
    ("GET", "/productos/stock-bajo", None, [[]]),
]


def route_id(route):
    return f"{route[0]} {route[1]}"


@pytest.mark.parametrize("route", ADMIN_ONLY_ROUTES, ids=route_id)
def test_admin_only_route_rejects_employee(employee_client, monkeypatch, route):
    method, path, body, _ = route
    db = use_db(monkeypatch)

    response = employee_client.request(method, API + path, json=body)

    assert response.status_code == 403
    assert response.json() == {"detail": "No tienes permisos suficientes para realizar esta acción."}
    assert db.queries == []


@pytest.mark.parametrize("route", [r for r in ADMIN_ONLY_ROUTES if r[3] is not None], ids=route_id)
def test_admin_only_route_works_for_admin(auth_client, monkeypatch, route):
    method, path, body, responses = route
    use_db(monkeypatch, *responses)

    response = auth_client.request(method, API + path, json=body)

    assert response.status_code == 200


@pytest.mark.parametrize("route", EMPLOYEE_ROUTES, ids=route_id)
def test_employee_can_use_allowed_route(employee_client, monkeypatch, route):
    method, path, body, responses = route
    use_db(monkeypatch, *responses)

    response = employee_client.request(method, API + path, json=body)

    assert response.status_code == 200


# --- cost data ----------------------------------------------------------------


def test_product_list_hides_cost_from_employee(employee_client, monkeypatch):
    use_db(monkeypatch, [PRODUCT_ROW], [])

    response = employee_client.get(f"{API}/productos/")

    variant = response.json()[0]["variantes"][0]
    assert variant["precio_costo"] is None
    assert variant["precio_venta"] == 1500.0
    assert variant["stock_actual"] == 7


def test_product_list_keeps_cost_for_admin(auth_client, monkeypatch):
    use_db(monkeypatch, [PRODUCT_ROW], [])

    response = auth_client.get(f"{API}/productos/")

    assert response.json()[0]["variantes"][0]["precio_costo"] == 678.0


def test_product_by_sku_hides_cost_from_employee(employee_client, monkeypatch):
    use_db(monkeypatch, [{"producto_id": PRODUCT_ID}], PRODUCT_ROW)

    response = employee_client.get(f"{API}/productos/sku/REM-001")

    assert response.status_code == 200
    assert response.json()["variantes"][0]["precio_costo"] is None


def test_product_by_sku_keeps_cost_for_admin(auth_client, monkeypatch):
    use_db(monkeypatch, [{"producto_id": PRODUCT_ID}], PRODUCT_ROW)

    response = auth_client.get(f"{API}/productos/sku/REM-001")

    assert response.json()["variantes"][0]["precio_costo"] == 678.0


@pytest.mark.parametrize("route", EMPLOYEE_ROUTES, ids=route_id)
def test_employee_responses_never_expose_cost_values(employee_client, monkeypatch, route):
    method, path, body, responses = route
    use_db(monkeypatch, *responses)

    response = employee_client.request(method, API + path, json=body)

    # 678 is the cost used by every fixture row above.
    assert "total_costo" not in response.text
    assert "costo_unitario" not in response.text
    assert "678" not in response.text


# --- UUID path params -----------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PATCH", "/productos/not-a-uuid", {"nombre": "x"}),
        ("DELETE", "/productos/not-a-uuid", None),
        ("PATCH", "/productos/variante/not-a-uuid", {"talle": "L"}),
        ("DELETE", "/productos/variante/not-a-uuid", None),
        ("PATCH", "/clientes/not-a-uuid", {"nombre": "Ana"}),
        ("GET", "/caja/sesiones/not-a-uuid/movimientos", None),
        ("GET", "/productos/variante/not-a-uuid/movimientos", None),
        ("GET", "/ventas/not-a-uuid", None),
        ("POST", "/ventas/not-a-uuid/anular", {"motivo": "Error"}),
        ("PATCH", "/usuarios/not-a-uuid/rol", {"rol_id": 1}),
        ("PATCH", "/usuarios/not-a-uuid/activo", {"activo": False}),
    ],
)
def test_malformed_uuid_is_rejected_before_the_database(auth_client, monkeypatch, method, path, body):
    db = use_db(monkeypatch)

    response = auth_client.request(method, API + path, json=body)

    assert response.status_code == 422
    assert db.queries == []


def test_uuid_path_param_reaches_the_service_as_string(auth_client, monkeypatch):
    db = use_db(monkeypatch, [MOVEMENT_ROW])

    auth_client.get(f"{API}/caja/sesiones/{SESSION_ID.upper()}/movimientos")

    assert db.queries[0].args_of("eq") == [("sesion_id", SESSION_ID)]
