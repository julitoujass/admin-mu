from datetime import datetime, timezone

import pytest
from postgrest.exceptions import APIError

from app.core.timeutils import ARGENTINA_TZ, local_day_bounds_utc
from app.services import venta_service
from tests.fakes import FakeSupabase

USER_ID = "00000000-0000-0000-0000-000000000001"
VARIANT_A = "11111111-1111-4111-8111-111111111111"
VARIANT_B = "33333333-3333-4333-8333-333333333333"
CLIENT_ID = "44444444-4444-4444-8444-444444444444"
SALE_ROW = {
    "id": "22222222-2222-4222-8222-222222222222",
    "created_at": "2026-11-11T15:00:00+00:00",
    "total": 3000.0,
    "total_costo": 1200.0,
    "metodo_pago": "Efectivo",
    "usuario_id": USER_ID,
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
    assert (call.kind, call.name) == ("rpc", "crear_venta")
    assert call.params == {
        "p_usuario_id": USER_ID,
        "p_metodo_pago": "Efectivo",
        "p_items": [
            {"variante_id": VARIANT_A, "cantidad": 2},
            {"variante_id": VARIANT_B, "cantidad": 1},
        ],
        "p_cliente_id": CLIENT_ID,
        "p_idempotency_key": None,
    }


def test_create_sale_response_hides_cost(auth_client, db):
    response = auth_client.post("/api/v1/ventas/", json=sale_body())

    assert response.json() == {
        "id": SALE_ROW["id"],
        "created_at": "2026-11-11T15:00:00Z",
        "total": 3000.0,
        "metodo_pago": "Efectivo",
    }


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
    ],
)
def test_database_business_errors_reach_the_client(auth_client, monkeypatch, code, status, message):
    error = APIError({"code": code, "message": message, "details": None, "hint": None})
    monkeypatch.setattr(venta_service, "supabase", FakeSupabase(error))

    response = auth_client.post("/api/v1/ventas/", json=sale_body())

    assert response.status_code == status
    assert response.json() == {"detail": message}


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
    assert response.json() == [
        {
            "id": SALE_ROW["id"],
            "created_at": "2026-11-11T15:00:00Z",
            "total": 3000.0,
            "metodo_pago": "Efectivo",
        }
    ]
    query = fake.queries[0]
    assert (query.kind, query.name) == ("table", "ventas")
    assert query.args_of("select") == [("id, created_at, total, metodo_pago",)]
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
