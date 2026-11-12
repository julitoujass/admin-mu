import pytest
from postgrest.exceptions import APIError

from app.services import producto_service
from tests.fakes import Counted, FakeSupabase

VARIANT_ID = "11111111-1111-4111-8111-111111111111"
PRODUCT_ID = "77777777-7777-4777-8777-777777777777"
VARIANT_ROW = {
    "id": VARIANT_ID,
    "producto_id": PRODUCT_ID,
    "sku": "REM-001",
    "talle": "M",
    "color": "Azul",
    "precio_venta": 1500.0,
    "precio_costo": 600.0,
    "stock_actual": 7,
    "stock_minimo": 2,
}


def use_db(monkeypatch, *responses):
    fake = FakeSupabase(*responses)
    monkeypatch.setattr(producto_service, "supabase", fake)
    return fake


def product_row(index):
    return {"id": f"00000000-0000-4000-8000-{index:012d}", "nombre": f"Producto {index}", "variantes": []}


# --- stock -------------------------------------------------------------------


def test_stock_adjustment_uses_atomic_rpc(auth_client, monkeypatch):
    db = use_db(monkeypatch, VARIANT_ROW)

    response = auth_client.patch(
        "/api/v1/productos/inventario/stock",
        json={"variante_id": VARIANT_ID, "cantidad": -3, "motivo": "Rotura"},
    )

    assert response.status_code == 200
    assert response.json()["stock_actual"] == 7
    assert len(db.queries) == 1
    assert (db.queries[0].kind, db.queries[0].name) == ("rpc", "registrar_ajuste_stock")
    assert db.queries[0].params == {
        "p_variante_id": VARIANT_ID,
        "p_cantidad": -3,
        "p_usuario_id": "00000000-0000-0000-0000-000000000001",
        "p_motivo": "Rotura",
    }


@pytest.mark.parametrize(
    "body",
    [
        {"variante_id": VARIANT_ID, "cantidad": 0, "motivo": "x"},
        {"variante_id": VARIANT_ID, "cantidad": 1.5, "motivo": "x"},
        {"variante_id": VARIANT_ID, "cantidad": 1, "motivo": ""},
        {"variante_id": VARIANT_ID, "cantidad": 1, "motivo": "  "},
        {"variante_id": VARIANT_ID, "cantidad": 1, "motivo": "x" * 201},
        {"variante_id": "nope", "cantidad": 1, "motivo": "x"},
    ],
    ids=["cantidad-0", "cantidad-fraction", "motivo-empty", "motivo-blank", "motivo-long", "bad-uuid"],
)
def test_stock_adjustment_validation(auth_client, monkeypatch, body):
    db = use_db(monkeypatch)

    response = auth_client.patch("/api/v1/productos/inventario/stock", json=body)

    assert response.status_code == 422
    assert db.queries == []


def test_stock_adjustment_going_negative_is_a_conflict(auth_client, monkeypatch):
    error = APIError({"code": "MU002", "message": "El stock no puede quedar negativo", "details": None, "hint": None})
    use_db(monkeypatch, error)

    response = auth_client.patch(
        "/api/v1/productos/inventario/stock",
        json={"variante_id": VARIANT_ID, "cantidad": -99, "motivo": "Ajuste"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "El stock no puede quedar negativo"}


# --- kardex ------------------------------------------------------------------

KARDEX_URL = f"/api/v1/productos/variante/{VARIANT_ID}/movimientos"
MOVEMENT_ROW = {
    "id": 42,
    "created_at": "2026-11-11T15:00:00+00:00",
    "tipo": "venta",
    "cantidad": -2,
    "stock_resultante": 5,
    "venta_id": "22222222-2222-4222-8222-222222222222",
    "motivo": None,
    "usuario": {"id": "00000000-0000-0000-0000-000000000001", "nombre": "Admin"},
}


def calls_of(query, method):
    return [(args, kwargs) for name, args, kwargs in query.calls if name == method]


def test_kardex_lists_the_variant_movements_with_total(auth_client, monkeypatch):
    adjustment = {**MOVEMENT_ROW, "id": 41, "tipo": "ajuste", "cantidad": 7, "venta_id": None, "usuario": None}
    db = use_db(monkeypatch, Counted([MOVEMENT_ROW, adjustment], 61))

    response = auth_client.get(KARDEX_URL)

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {**MOVEMENT_ROW, "created_at": "2026-11-11T15:00:00Z"},
            {**adjustment, "created_at": "2026-11-11T15:00:00Z"},
        ],
        "total": 61,
    }
    query = db.queries[0]
    assert (query.kind, query.name) == ("table", "movimientos_stock")
    assert calls_of(query, "select") == [
        (
            ("id, created_at, tipo, cantidad, stock_resultante, venta_id, motivo, usuario:perfiles(id, nombre)",),
            {"count": "exact"},
        )
    ]
    assert query.args_of("eq") == [("variante_id", VARIANT_ID)]
    assert calls_of(query, "order") == [(("created_at",), {"desc": True}), (("id",), {"desc": True})]
    assert query.args_of("range") == [(0, 49)]


def test_kardex_paging(auth_client, monkeypatch):
    db = use_db(monkeypatch, Counted([], 0))

    response = auth_client.get(KARDEX_URL, params={"limit": 200, "offset": 400})

    assert response.json() == {"items": [], "total": 0}
    assert db.queries[0].args_of("range") == [(400, 599)]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
def test_kardex_rejects_invalid_paging(auth_client, monkeypatch, params):
    db = use_db(monkeypatch)

    response = auth_client.get(KARDEX_URL, params=params)

    assert response.status_code == 422
    assert db.queries == []


def test_kardex_is_admin_only(employee_client, monkeypatch):
    db = use_db(monkeypatch)

    response = employee_client.get(KARDEX_URL)

    assert response.status_code == 403
    assert db.queries == []


# --- schema validation -------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"precio_venta": -1},
        {"precio_costo": -1},
        {"stock_actual": -1},
        {"stock_minimo": -1},
        {"sku": "s" * 65},
        {"talle": "t" * 21},
        {"color": "c" * 41},
    ],
    ids=["precio_venta", "precio_costo", "stock_actual", "stock_minimo", "sku", "talle", "color"],
)
def test_variant_create_validation(auth_client, monkeypatch, overrides):
    db = use_db(monkeypatch)
    body = {"producto_id": PRODUCT_ID, "precio_venta": 100, **overrides}

    response = auth_client.post("/api/v1/productos/variante", json=body)

    assert response.status_code == 422
    assert db.queries == []


@pytest.mark.parametrize(
    "body",
    [{"precio_venta": -1}, {"precio_costo": -0.5}, {"stock_minimo": -1}, {"sku": "s" * 65}],
    ids=["precio_venta", "precio_costo", "stock_minimo", "sku"],
)
def test_variant_update_validation(auth_client, monkeypatch, body):
    db = use_db(monkeypatch)

    response = auth_client.patch(f"/api/v1/productos/variante/{VARIANT_ID}", json=body)

    assert response.status_code == 422
    assert db.queries == []


@pytest.mark.parametrize(
    "body",
    [{"nombre": "n" * 121}, {"nombre": "ok", "descripcion": "d" * 1001}],
    ids=["nombre", "descripcion"],
)
def test_product_create_validation(auth_client, monkeypatch, body):
    db = use_db(monkeypatch)

    response = auth_client.post("/api/v1/productos/", json=body)

    assert response.status_code == 422
    assert db.queries == []


def test_valid_variant_is_created(auth_client, monkeypatch):
    db = use_db(monkeypatch, [VARIANT_ROW])
    body = {"producto_id": PRODUCT_ID, "sku": "REM-001", "precio_venta": 1500, "precio_costo": 600, "stock_actual": 7}

    response = auth_client.post("/api/v1/productos/variante", json=body)

    assert response.status_code == 200
    assert db.queries[0].name == "producto_variantes"


def test_listing_tolerates_stored_rows_outside_the_input_limits(auth_client, monkeypatch):
    legacy = {**product_row(1), "nombre": "n" * 300, "variantes": [{**VARIANT_ROW, "sku": "s" * 100}]}
    use_db(monkeypatch, [legacy])

    response = auth_client.get("/api/v1/productos/")

    assert response.status_code == 200
    assert response.json()[0]["variantes"][0]["sku"] == "s" * 100


# --- full catalog paging -----------------------------------------------------


def test_catalog_is_fetched_page_by_page_until_empty(auth_client, monkeypatch):
    first = [product_row(i) for i in range(1000)]
    second = [product_row(i) for i in range(1000, 1250)]
    db = use_db(monkeypatch, first, second)

    response = auth_client.get("/api/v1/productos/")

    assert response.status_code == 200
    assert len(response.json()) == 1250
    assert [(q.kind, q.name, q.params) for q in db.executed] == [("rpc", "obtener_productos", {})] * 3
    assert [q.args_of("range") for q in db.executed] == [[(0, 999)], [(1000, 1999)], [(1250, 2249)]]
    assert all(q.args_of("select") == [(f"*, {producto_service.PRODUCT_EMBEDS}",)] for q in db.executed)


def test_catalog_paging_survives_a_smaller_server_page(auth_client, monkeypatch):
    # PostgREST may cap rows below the requested page size (max-rows).
    db = use_db(monkeypatch, [product_row(i) for i in range(500)], [product_row(i) for i in range(500, 520)])

    response = auth_client.get("/api/v1/productos/")

    assert len(response.json()) == 520
    assert [q.args_of("range") for q in db.executed] == [[(0, 999)], [(500, 1499)], [(520, 1519)]]


def test_catalog_category_filter_is_forwarded(auth_client, monkeypatch):
    db = use_db(monkeypatch, [product_row(1)])

    auth_client.get("/api/v1/productos/?categoria_id=3")

    assert db.executed[0].params == {"p_categoria_id": 3}
