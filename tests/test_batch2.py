"""Phase 5 batch 2: returns, settings, low stock, user creation, product categories, audit viewer."""

from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from app.api.v1.endpoints import configuracion as configuracion_endpoints
from app.api.v1.endpoints import productos as productos_endpoints
from app.api.v1.endpoints import usuarios as usuarios_endpoints
from app.api.v1.endpoints import ventas as ventas_endpoints
from app.services import (
    auditoria_service,
    configuracion_service,
    producto_service,
    usuario_service,
    venta_service,
)
from tests.fakes import Counted, FakeSupabase

ADMIN_ID = "00000000-0000-0000-0000-000000000001"
SALE_ID = "22222222-2222-4222-8222-222222222222"
VARIANT_A = "11111111-1111-4111-8111-111111111111"
PRODUCT_ID = "77777777-7777-4777-8777-777777777777"
DEV_ID = "88888888-8888-4888-8888-888888888888"
NEW_USER_ID = "99999999-9999-4999-8999-999999999999"


def use(monkeypatch, module, *responses):
    fake = FakeSupabase(*responses)
    monkeypatch.setattr(module, "supabase", fake)
    return fake


def capture_audit(monkeypatch, module):
    recorded = []
    monkeypatch.setattr(module, "audit", lambda *args, **kwargs: recorded.append((args, kwargs)))
    return recorded


# --- returns -----------------------------------------------------------------------------------

DETAIL_WITH_RETURN = {
    "id": SALE_ID,
    "created_at": "2026-11-11T15:00:00+00:00",
    "subtotal": 3000.0,
    "descuento_aplicado": 300.0,
    "recargo_aplicado": 0,
    "total": 2700.0,
    "total_costo": 1200.0,
    "metodo_pago": "Efectivo",
    "estado": "completada",
    "cliente": None,
    "usuario": {"id": ADMIN_ID, "nombre": "Admin"},
    "motivo_anulacion": None,
    "anulada_at": None,
    "anulada_por": None,
    "items": [
        {
            "variante_id": VARIANT_A,
            "cantidad": 2,
            "precio_unitario": 1500.0,
            "costo_unitario": 600.0,
            "subtotal": 3000.0,
            "variante": {"sku": "REM-001", "talle": "M", "color": "Azul", "producto": {"nombre": "Remera"}},
        }
    ],
    "devoluciones": [
        {
            "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "created_at": "2026-11-11T18:00:00+00:00",
            "motivo": "Talle",
            "monto": 675.0,
            "metodo_pago": "Efectivo",
            "usuario": {"id": ADMIN_ID, "nombre": "Admin"},
            "items": [{"variante_id": VARIANT_A, "cantidad": 1, "monto": 675.0}],
        },
        {
            "id": DEV_ID,
            "created_at": "2026-11-11T17:00:00+00:00",
            "motivo": "Falla",
            "monto": 0.5,
            "metodo_pago": "Efectivo",
            "usuario": None,
            "items": [{"variante_id": VARIANT_A, "cantidad": 0 + 1, "monto": 0.5}],
        },
    ],
}
RETURN_BODY = {"motivo": "  Talle  ", "items": [{"variante_id": VARIANT_A, "cantidad": 1}]}


def test_return_calls_rpc_and_returns_the_detail(auth_client, monkeypatch):
    fake = use(monkeypatch, venta_service, {"id": DEV_ID, "monto": 675}, [DETAIL_WITH_RETURN])

    response = auth_client.post(f"/api/v1/ventas/{SALE_ID}/devoluciones", json=RETURN_BODY)

    assert response.status_code == 200
    rpc, detail = fake.queries
    assert (rpc.kind, rpc.name) == ("rpc", "registrar_devolucion")
    assert rpc.params == {
        "p_venta_id": SALE_ID,
        "p_usuario_id": ADMIN_ID,
        "p_motivo": "Talle",
        "p_items": [{"variante_id": VARIANT_A, "cantidad": 1}],
    }
    assert (detail.kind, detail.name) == ("table", "ventas")
    body = response.json()
    assert body["total_devuelto"] == 675.5
    assert body["items"][0]["cantidad_devuelta"] == 2
    # Returns come oldest first.
    assert [r["motivo"] for r in body["devoluciones"]] == ["Falla", "Talle"]
    assert body["devoluciones"][1]["items"] == [{"variante_id": VARIANT_A, "cantidad": 1, "monto": 675.0}]
    assert body["devoluciones"][0]["usuario"] is None


def test_return_is_admin_only(employee_client, monkeypatch):
    fake = use(monkeypatch, venta_service)

    response = employee_client.post(f"/api/v1/ventas/{SALE_ID}/devoluciones", json=RETURN_BODY)

    assert response.status_code == 403
    assert fake.queries == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"motivo": "x", "items": []},
        {"motivo": "", "items": [{"variante_id": VARIANT_A, "cantidad": 1}]},
        {"motivo": "x" * 201, "items": [{"variante_id": VARIANT_A, "cantidad": 1}]},
        {"motivo": "x", "items": [{"variante_id": "no-uuid", "cantidad": 1}]},
        {"motivo": "x", "items": [{"variante_id": VARIANT_A, "cantidad": 0}]},
        {"motivo": "x", "items": [{"variante_id": VARIANT_A, "cantidad": 1001}]},
        {"motivo": "x", "items": [{"variante_id": VARIANT_A, "cantidad": 1}] * 201},
    ],
)
def test_return_input_is_validated(auth_client, monkeypatch, body):
    fake = use(monkeypatch, venta_service)

    assert auth_client.post(f"/api/v1/ventas/{SALE_ID}/devoluciones", json=body).status_code == 422
    assert fake.queries == []


@pytest.mark.parametrize(
    ("code", "status", "message"),
    [
        ("MU008", 409, "No se puede devolver una venta anulada"),
        ("MU009", 409, "La cantidad a devolver supera lo pendiente de la variante x"),
        ("MU010", 409, "La venta tiene devoluciones; registrá una devolución por lo pendiente"),
        ("MU004", 404, "Venta no encontrada"),
        ("MU001", 400, "Abrí la caja para registrar la devolución en efectivo"),
    ],
)
def test_return_business_errors(auth_client, monkeypatch, code, status, message):
    use(monkeypatch, venta_service, APIError({"code": code, "message": message, "details": None, "hint": None}))

    response = auth_client.post(f"/api/v1/ventas/{SALE_ID}/devoluciones", json=RETURN_BODY)

    assert (response.status_code, response.json()) == (status, {"detail": message})


def test_return_is_audited(auth_client, monkeypatch):
    recorded = capture_audit(monkeypatch, ventas_endpoints)
    use(monkeypatch, venta_service, {"id": DEV_ID}, [DETAIL_WITH_RETURN])

    auth_client.post(f"/api/v1/ventas/{SALE_ID}/devoluciones", json=RETURN_BODY)

    (args, kwargs), = recorded
    assert args[2:] == ("RETURN_SALE", "ventas")
    assert kwargs["entidad_id"] == SALE_ID
    assert kwargs["payload"] == {"motivo": "Talle", "items": [{"variante_id": VARIANT_A, "cantidad": 1}]}


def test_sale_list_sums_returns_into_total_devuelto(auth_client, monkeypatch):
    row = {
        "id": SALE_ID,
        "created_at": "2026-11-11T15:00:00+00:00",
        "subtotal": 10,
        "descuento_aplicado": 0,
        "recargo_aplicado": 0,
        "total": 10,
        "metodo_pago": "QR",
        "estado": "completada",
        "cliente": None,
        "usuario": None,
    }
    use(monkeypatch, venta_service, Counted([{**row, "devoluciones": [{"monto": 1.1}, {"monto": 2.2}]}, {**row, "devoluciones": []}], 2))

    body = auth_client.get("/api/v1/ventas/").json()

    assert [item["total_devuelto"] for item in body["items"]] == [3.3, 0.0]
    assert "devoluciones" not in body["items"][0]


# --- settings ---------------------------------------------------------------------------------

SETTINGS_ROW = {
    "id": 1,
    "nombre_negocio": "Mundo Uniforme",
    "cuit": None,
    "direccion": "Calle 1",
    "telefono": None,
    "email": None,
    "pie_ticket": None,
    "descuento_max_empleado": 10,
    "updated_at": "2026-11-12T10:00:00+00:00",
    "updated_by": {"id": ADMIN_ID, "nombre": "Admin"},
}


def test_settings_are_readable_by_any_user(employee_client, monkeypatch):
    fake = use(monkeypatch, configuracion_service, [SETTINGS_ROW])

    response = employee_client.get("/api/v1/configuracion/")

    assert response.status_code == 200
    assert response.json()["updated_by"] == {"id": ADMIN_ID, "nombre": "Admin"}
    assert response.json()["descuento_max_empleado"] == 10.0
    query = fake.queries[0]
    assert query.name == "configuracion"
    assert query.args_of("select") == [("*, updated_by:perfiles!updated_by(id, nombre)",)]
    assert query.args_of("eq") == [("id", 1)]


def test_missing_settings_row_is_404(auth_client, monkeypatch):
    use(monkeypatch, configuracion_service, [])

    assert auth_client.get("/api/v1/configuracion/").status_code == 404


def test_settings_update_is_partial_stamped_and_audited(auth_client, monkeypatch):
    recorded = capture_audit(monkeypatch, configuracion_endpoints)
    fake = use(monkeypatch, configuracion_service, [{"id": 1}], [{**SETTINGS_ROW, "descuento_max_empleado": 15}])

    response = auth_client.patch(
        "/api/v1/configuracion/", json={"descuento_max_empleado": 15, "cuit": "  ", "email": "a@b.com"}
    )

    assert response.status_code == 200
    update = fake.queries[0]
    (values,) = update.args_of("update")
    values = values[0]
    assert values["descuento_max_empleado"] == 15
    assert values["cuit"] is None
    assert values["email"] == "a@b.com"
    assert values["updated_by"] == ADMIN_ID
    assert values["updated_at"]
    assert "nombre_negocio" not in values
    assert update.args_of("eq") == [("id", 1)]
    (args, kwargs), = recorded
    assert args[2:] == ("UPDATE", "configuracion")
    assert kwargs["entidad_id"] == 1


def test_settings_update_is_admin_only(employee_client, monkeypatch):
    fake = use(monkeypatch, configuracion_service)

    assert employee_client.patch("/api/v1/configuracion/", json={"cuit": "1"}).status_code == 403
    assert fake.queries == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"nombre_negocio": ""},
        {"nombre_negocio": None},
        {"nombre_negocio": "x" * 121},
        {"cuit": "1" * 21},
        {"direccion": "x" * 201},
        {"telefono": "1" * 31},
        {"email": "not-an-email"},
        {"pie_ticket": "x" * 301},
        {"descuento_max_empleado": -1},
        {"descuento_max_empleado": 101},
        {"descuento_max_empleado": None},
    ],
)
def test_settings_update_rejects_invalid_input(auth_client, monkeypatch, body):
    fake = use(monkeypatch, configuracion_service)

    assert auth_client.patch("/api/v1/configuracion/", json=body).status_code == 422
    assert fake.queries == []


def test_settings_update_of_a_missing_row_is_404(auth_client, monkeypatch):
    use(monkeypatch, configuracion_service, [])

    assert auth_client.patch("/api/v1/configuracion/", json={"cuit": "1"}).status_code == 404


# --- low stock --------------------------------------------------------------------------------

LOW_ROW = {
    "variante_id": VARIANT_A,
    "producto_id": PRODUCT_ID,
    "producto_nombre": "Remera",
    "sku": "REM-001",
    "talle": "M",
    "color": None,
    "stock_actual": 1,
    "stock_minimo": 3,
}


def test_low_stock_is_open_to_employees_and_not_captured_by_other_routes(employee_client, monkeypatch):
    fake = use(monkeypatch, producto_service, [LOW_ROW])

    response = employee_client.get("/api/v1/productos/stock-bajo")

    assert response.status_code == 200
    assert response.json() == {"items": [LOW_ROW], "total": 1}
    assert (fake.queries[0].kind, fake.queries[0].name) == ("rpc", "variantes_stock_bajo")


def test_low_stock_empty(auth_client, monkeypatch):
    use(monkeypatch, producto_service, None)

    assert auth_client.get("/api/v1/productos/stock-bajo").json() == {"items": [], "total": 0}


# --- user creation ----------------------------------------------------------------------------

USER_BODY = {"email": "nuevo@example.com", "password": "s3cret-pass", "nombre": " Ana ", "apellido": "Pérez", "rol_id": 2}
EMPLOYEE_ROLE = {"id": 2, "nombre": "empleado"}
PROFILE_ROW = {
    "id": NEW_USER_ID,
    "nombre": "Ana",
    "apellido": "Pérez",
    "activo": True,
    "rol_id": 2,
    "created_at": "2026-11-12T12:00:00+00:00",
}


def fake_auth(create=None, delete=None):
    admin = SimpleNamespace(
        create_user=create or (lambda attrs: SimpleNamespace(user=SimpleNamespace(id=NEW_USER_ID, email=attrs["email"]))),
        delete_user=delete or (lambda user_id: None),
    )
    return SimpleNamespace(admin=admin)


def use_users(monkeypatch, *responses, auth=None):
    fake = FakeSupabase(*responses)
    fake.auth = auth or fake_auth()
    monkeypatch.setattr(usuario_service, "supabase", fake)
    return fake


def test_create_user_makes_auth_user_then_profile(auth_client, monkeypatch):
    created = []
    deleted = []
    auth = fake_auth(
        create=lambda attrs: created.append(attrs) or SimpleNamespace(user=SimpleNamespace(id=NEW_USER_ID, email=attrs["email"])),
        delete=deleted.append,
    )
    fake = use_users(monkeypatch, [EMPLOYEE_ROLE], [PROFILE_ROW], auth=auth)
    recorded = capture_audit(monkeypatch, usuarios_endpoints)

    response = auth_client.post("/api/v1/usuarios/", json=USER_BODY)

    assert response.status_code == 200
    assert created == [{"email": "nuevo@example.com", "password": "s3cret-pass", "email_confirm": True}]
    assert deleted == []
    role_query, insert_query = fake.queries
    assert (role_query.name, insert_query.name) == ("roles", "perfiles")
    assert insert_query.args_of("insert") == [
        ({"id": NEW_USER_ID, "nombre": "Ana", "apellido": "Pérez", "rol_id": 2, "activo": True},)
    ]
    body = response.json()
    assert body["email"] == "nuevo@example.com"
    assert body["roles"] == EMPLOYEE_ROLE
    assert body["activo"] is True
    assert "password" not in response.text
    (args, kwargs), = recorded
    assert args[2:] == ("CREATE", "perfiles")
    assert "password" not in str(kwargs)


def test_create_user_rejects_unknown_role_before_touching_auth(auth_client, monkeypatch):
    created = []
    auth = fake_auth(create=lambda attrs: created.append(attrs))
    use_users(monkeypatch, [], auth=auth)

    response = auth_client.post("/api/v1/usuarios/", json=USER_BODY)

    assert response.status_code == 400
    assert response.json() == {"detail": "El rol indicado no existe"}
    assert created == []


class FakeAuthError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.message = message
        self.code = code


@pytest.mark.parametrize(
    "error",
    [
        FakeAuthError("A user with this email address has already been registered", "email_exists"),
        FakeAuthError("User already registered"),
        FakeAuthError("whatever", "user_already_exists"),
    ],
)
def test_create_user_maps_taken_email_to_409(auth_client, monkeypatch, error):
    def boom(attrs):
        raise error

    use_users(monkeypatch, [EMPLOYEE_ROLE], auth=fake_auth(create=boom))

    response = auth_client.post("/api/v1/usuarios/", json=USER_BODY)

    assert response.status_code == 409
    assert response.json() == {"detail": "Ya existe un usuario con ese email"}


def test_create_user_other_auth_errors_are_internal(auth_client, monkeypatch):
    def boom(attrs):
        raise FakeAuthError("Password is too weak", "weak_password")

    use_users(monkeypatch, [EMPLOYEE_ROLE], auth=fake_auth(create=boom))

    response = auth_client.post("/api/v1/usuarios/", json=USER_BODY)

    assert response.status_code == 500
    assert "weak" not in response.text


def test_create_user_deletes_the_auth_user_if_the_profile_fails(auth_client, monkeypatch):
    deleted = []
    use_users(monkeypatch, [EMPLOYEE_ROLE], RuntimeError("db down"), auth=fake_auth(delete=deleted.append))

    response = auth_client.post("/api/v1/usuarios/", json=USER_BODY)

    assert response.status_code == 500
    assert deleted == [NEW_USER_ID]


def test_create_user_is_admin_only(employee_client, monkeypatch):
    fake = use_users(monkeypatch)

    assert employee_client.post("/api/v1/usuarios/", json=USER_BODY).status_code == 403
    assert fake.queries == []


@pytest.mark.parametrize(
    "changes",
    [
        {"email": "nope"},
        {"password": "short"},
        {"password": "x" * 73},
        {"nombre": ""},
        {"nombre": "x" * 81},
        {"apellido": "x" * 81},
        {"rol_id": "abc"},
    ],
)
def test_create_user_input_is_validated(auth_client, monkeypatch, changes):
    fake = use_users(monkeypatch)

    assert auth_client.post("/api/v1/usuarios/", json={**USER_BODY, **changes}).status_code == 422
    assert fake.queries == []


# --- product categories -----------------------------------------------------------------------

PRODUCT_WITH_CATS = {
    "id": PRODUCT_ID,
    "nombre": "Remera",
    "variantes": [],
    "categorias": [{"categoria": {"id": 2, "nombre": "Verano"}}, {"categoria": {"id": 1, "nombre": "Remeras"}}],
}
FLAT_CATS = [{"id": 1, "nombre": "Remeras"}, {"id": 2, "nombre": "Verano"}]


def test_product_list_embeds_flattened_categories(employee_client, monkeypatch):
    fake = use(monkeypatch, producto_service, [PRODUCT_WITH_CATS], [])

    response = employee_client.get("/api/v1/productos/")

    assert response.json()[0]["categorias"] == FLAT_CATS
    assert "categoria:categorias(id, nombre)" in fake.executed[0].args_of("select")[0][0]


def test_product_by_sku_includes_categories(auth_client, monkeypatch):
    use(monkeypatch, producto_service, [{"producto_id": PRODUCT_ID}], PRODUCT_WITH_CATS)

    assert auth_client.get("/api/v1/productos/sku/REM-001").json()["categorias"] == FLAT_CATS


def test_set_categories_writes_only_the_difference(auth_client, monkeypatch):
    recorded = capture_audit(monkeypatch, productos_endpoints)
    fake = use(
        monkeypatch,
        producto_service,
        [{"id": PRODUCT_ID}],  # product exists
        [{"id": 2}, {"id": 3}],  # wanted categories exist
        [{"categoria_id": 1}, {"categoria_id": 2}],  # current
        [],  # delete
        [],  # insert
        [PRODUCT_WITH_CATS],  # fresh product
    )

    response = auth_client.put(f"/api/v1/productos/{PRODUCT_ID}/categorias", json={"categoria_ids": [3, 2]})

    assert response.status_code == 200
    assert response.json()["categorias"] == FLAT_CATS
    queries = fake.queries
    assert [q.name for q in queries] == [
        "productos", "categorias", "producto_categorias", "producto_categorias", "producto_categorias", "productos"
    ]
    assert queries[1].args_of("in_") == [("id", [2, 3])]
    assert queries[3].args_of("in_") == [("categoria_id", [1])]
    assert queries[4].args_of("insert") == [([{"producto_id": PRODUCT_ID, "categoria_id": 3}],)]
    (args, kwargs), = recorded
    assert args[2:] == ("UPDATE", "productos")
    assert kwargs["payload"] == {"categoria_ids": [3, 2]}


def test_set_categories_can_clear_the_set(auth_client, monkeypatch):
    fake = use(
        monkeypatch, producto_service, [{"id": PRODUCT_ID}], [{"categoria_id": 1}], [], [{**PRODUCT_WITH_CATS, "categorias": []}]
    )

    response = auth_client.put(f"/api/v1/productos/{PRODUCT_ID}/categorias", json={"categoria_ids": []})

    assert response.status_code == 200
    assert response.json()["categorias"] == []
    assert [q.name for q in fake.queries] == ["productos", "producto_categorias", "producto_categorias", "productos"]


def test_set_categories_unknown_category_is_400(auth_client, monkeypatch):
    fake = use(monkeypatch, producto_service, [{"id": PRODUCT_ID}], [{"id": 2}])

    response = auth_client.put(f"/api/v1/productos/{PRODUCT_ID}/categorias", json={"categoria_ids": [2, 99]})

    assert response.status_code == 400
    assert len(fake.queries) == 2


def test_set_categories_unknown_product_is_404(auth_client, monkeypatch):
    use(monkeypatch, producto_service, [])

    assert auth_client.put(f"/api/v1/productos/{PRODUCT_ID}/categorias", json={"categoria_ids": [1]}).status_code == 404


@pytest.mark.parametrize("body", [{}, {"categoria_ids": [1, 1]}, {"categoria_ids": list(range(51))}, {"categoria_ids": ["a"]}])
def test_set_categories_input_is_validated(auth_client, monkeypatch, body):
    fake = use(monkeypatch, producto_service)

    assert auth_client.put(f"/api/v1/productos/{PRODUCT_ID}/categorias", json=body).status_code == 422
    assert fake.queries == []


def test_set_categories_is_admin_only(employee_client, monkeypatch):
    fake = use(monkeypatch, producto_service)

    assert employee_client.put(f"/api/v1/productos/{PRODUCT_ID}/categorias", json={"categoria_ids": []}).status_code == 403
    assert fake.queries == []


# --- audit viewer -----------------------------------------------------------------------------

LOG_ROW = {
    "id": 7,
    "created_at": "2026-11-12T15:00:00+00:00",
    "evento": "CREATE_SALE",
    "entidad": "ventas",
    "entidad_id": SALE_ID,
    "descripcion": "Total: $10",
    "estado": "SUCCESS",
    "payload_enviado": {"a": 1},
    "respuesta_recibida": None,
    "usuario_id": ADMIN_ID,
}


def test_audit_list_joins_user_names_and_pages(auth_client, monkeypatch):
    fake = use(
        monkeypatch,
        auditoria_service,
        Counted([LOG_ROW, {**LOG_ROW, "id": 6, "usuario_id": None}], 42),
        [{"id": ADMIN_ID, "nombre": "Admin"}],
    )

    response = auth_client.get("/api/v1/auditoria/")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 42
    assert body["items"][0]["usuario"] == {"id": ADMIN_ID, "nombre": "Admin"}
    assert body["items"][1]["usuario"] is None
    assert body["items"][0]["payload_enviado"] == {"a": 1}
    assert "usuario_id" not in body["items"][0]
    logs, profiles = fake.queries
    assert logs.name == "logs"
    assert logs.args_of("range") == [(0, 49)]
    assert logs.args_of("order") == [("created_at",), ("id",)]
    assert profiles.args_of("in_") == [("id", [ADMIN_ID])]


def test_audit_list_applies_filters(auth_client, monkeypatch):
    fake = use(monkeypatch, auditoria_service, Counted([], 0))

    response = auth_client.get(
        "/api/v1/auditoria/",
        params={
            "desde": "2026-11-01",
            "hasta": "2026-11-11",
            "evento": "CANCEL_SALE",
            "entidad": "ventas",
            "usuario_id": ADMIN_ID,
            "limit": 20,
            "offset": 40,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}
    query = fake.queries[0]
    assert query.args_of("gte") == [("created_at", "2026-11-01T03:00:00Z")]
    assert query.args_of("lt") == [("created_at", "2026-11-12T03:00:00Z")]
    assert query.args_of("eq") == [("evento", "CANCEL_SALE"), ("entidad", "ventas"), ("usuario_id", ADMIN_ID)]
    assert query.args_of("range") == [(40, 59)]
    assert len(fake.queries) == 1  # no profile lookup without rows


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"desde": "x"}, {"usuario_id": "x"}])
def test_audit_list_rejects_invalid_params(auth_client, monkeypatch, params):
    fake = use(monkeypatch, auditoria_service)

    assert auth_client.get("/api/v1/auditoria/", params=params).status_code == 422
    assert fake.queries == []


def test_audit_list_is_admin_only(employee_client, monkeypatch):
    fake = use(monkeypatch, auditoria_service)

    assert employee_client.get("/api/v1/auditoria/").status_code == 403
    assert fake.queries == []
