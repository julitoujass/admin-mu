import pytest
from postgrest.exceptions import APIError

from app.services import producto_service
from tests.fakes import FakeSupabase

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
    assert (db.queries[0].kind, db.queries[0].name) == ("rpc", "ajustar_stock")
    assert db.queries[0].params == {"p_variante_id": VARIANT_ID, "p_cantidad": -3}


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
    assert all(q.args_of("select") == [("*, variantes:producto_variantes(*)",)] for q in db.executed)


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
