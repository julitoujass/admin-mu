import pytest

from app.services import cliente_service
from app.services.cliente_service import sanitize_search_term
from tests.fakes import FakeSupabase

CLIENT_ID = "44444444-4444-4444-8444-444444444444"
CLIENT_ROW = {
    "id": CLIENT_ID,
    "nombre": "Ana Pérez",
    "dni_cuit": "20-12345678-9",
    "email": "ana@example.com",
    "telefono": None,
    "direccion": None,
    "ciudad": None,
    "tipo_iva": "Consumidor Final",
    "created_at": "2026-11-11T12:00:00+00:00",
}


def use_db(monkeypatch, *responses):
    fake = FakeSupabase(*responses)
    monkeypatch.setattr(cliente_service, "supabase", fake)
    return fake


# --- validation --------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "not-an-email"},
        {"nombre": "n" * 121},
        {"nombre": "   "},
        {"dni_cuit": "1" * 21},
        {"telefono": "1" * 31},
        {"direccion": "d" * 201},
        {"ciudad": "c" * 81},
        {"tipo_iva": "Otro"},
    ],
    ids=["email", "nombre-long", "nombre-blank", "dni_cuit", "telefono", "direccion", "ciudad", "tipo_iva"],
)
def test_client_create_validation(auth_client, monkeypatch, overrides):
    db = use_db(monkeypatch)

    response = auth_client.post("/api/v1/clientes/", json={"nombre": "Ana", **overrides})

    assert response.status_code == 422
    assert db.queries == []


@pytest.mark.parametrize("body", [{"email": "nope"}, {"tipo_iva": "Otro"}, {"nombre": "n" * 121}])
def test_client_update_validation(auth_client, monkeypatch, body):
    db = use_db(monkeypatch)

    response = auth_client.patch(f"/api/v1/clientes/{CLIENT_ID}", json=body)

    assert response.status_code == 422
    assert db.queries == []


def test_valid_client_is_created_and_blank_optionals_are_dropped(auth_client, monkeypatch):
    db = use_db(monkeypatch, [CLIENT_ROW])
    body = {"nombre": " Ana Pérez ", "email": "ana@example.com", "telefono": "", "tipo_iva": "Monotributista"}

    response = auth_client.post("/api/v1/clientes/", json=body)

    assert response.status_code == 200
    assert db.queries[0].args_of("insert") == [
        ({"nombre": "Ana Pérez", "email": "ana@example.com", "tipo_iva": "Monotributista"},)
    ]


def test_update_can_clear_a_field_with_blank_or_null(auth_client, monkeypatch):
    db = use_db(monkeypatch, [CLIENT_ROW])

    response = auth_client.patch(f"/api/v1/clientes/{CLIENT_ID}", json={"email": "", "telefono": None})

    assert response.status_code == 200
    assert db.queries[0].args_of("update") == [({"email": None, "telefono": None},)]


def test_listing_tolerates_stored_rows_that_would_fail_input_validation(auth_client, monkeypatch):
    use_db(monkeypatch, [{**CLIENT_ROW, "email": "legacy-not-an-email", "tipo_iva": "Otro"}])

    response = auth_client.get("/api/v1/clientes/")

    assert response.status_code == 200
    assert response.json()[0]["email"] == "legacy-not-an-email"


# --- search sanitization -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("Ana", "Ana"),
        ("  José   Núñez ", "José Núñez"),
        ("20-12345678-9", "20-12345678-9"),
        ("a,dni_cuit.ilike.*", "a dni cuit ilike"),
        ("%_()\"'\\:.*@", ""),
        ("x" * 80, "x" * 50),
        (None, ""),
    ],
)
def test_sanitize_search_term(raw, clean):
    assert sanitize_search_term(raw) == clean


def test_search_uses_only_the_sanitized_term(auth_client, monkeypatch):
    db = use_db(monkeypatch, [CLIENT_ROW])

    response = auth_client.get("/api/v1/clientes/", params={"query": "ana),id.not.is.null,or(nombre.ilike.%"})

    assert response.status_code == 200
    term = "ana id not is null or nombre ilike"
    assert db.queries[0].args_of("or_") == [(f"nombre.ilike.%{term}%,dni_cuit.ilike.%{term}%",)]


def test_search_with_nothing_left_after_sanitizing_returns_unfiltered_list(auth_client, monkeypatch):
    db = use_db(monkeypatch, [CLIENT_ROW])

    response = auth_client.get("/api/v1/clientes/", params={"query": "%,()"})

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert db.queries[0].args_of("or_") == []


# --- pagination --------------------------------------------------------------


def test_clients_default_pagination(auth_client, monkeypatch):
    db = use_db(monkeypatch, [CLIENT_ROW])

    auth_client.get("/api/v1/clientes/")

    assert db.queries[0].args_of("range") == [(0, 999)]


def test_clients_custom_pagination(auth_client, monkeypatch):
    db = use_db(monkeypatch, [])

    auth_client.get("/api/v1/clientes/?limit=1000&offset=2000")

    assert db.queries[0].args_of("range") == [(2000, 2999)]


@pytest.mark.parametrize("params", ["limit=0", "limit=1001", "offset=-1"])
def test_clients_pagination_bounds(auth_client, monkeypatch, params):
    db = use_db(monkeypatch)

    response = auth_client.get(f"/api/v1/clientes/?{params}")

    assert response.status_code == 422
    assert db.queries == []
