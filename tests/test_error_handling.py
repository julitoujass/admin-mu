import pytest
from postgrest.exceptions import APIError

from app.services.catalogo_service import CatalogoService

SECRET = "relation public.marcas_nombre_key internal-detail"


def raiser(exc):
    def _raise(*args, **kwargs):
        raise exc

    return _raise


def api_error(code):
    return APIError({"code": code, "message": SECRET, "details": SECRET, "hint": None})


@pytest.mark.parametrize(
    ("code", "status", "detail"),
    [
        ("23505", 409, "Conflicto: el registro ya existe"),
        ("23503", 409, "Conflicto: el registro está referenciado por otros datos"),
        ("PGRST116", 404, "Recurso no encontrado"),
        ("22P02", 400, "Dato inválido"),
        ("23514", 400, "Dato fuera de rango"),
        ("XX000", 500, "Error interno del servidor"),
    ],
)
def test_api_error_is_mapped_by_code(auth_client, monkeypatch, code, status, detail):
    monkeypatch.setattr(CatalogoService, "get_marcas", raiser(api_error(code)))

    response = auth_client.get("/api/v1/catalogos/marcas")

    assert response.status_code == status
    assert response.json() == {"detail": detail}
    assert "internal-detail" not in response.text


@pytest.mark.parametrize(
    ("code", "status"),
    [("MU001", 400), ("MU002", 409), ("MU003", 400), ("MU004", 404), ("MU005", 409)],
)
def test_database_business_error_keeps_its_own_message(auth_client, monkeypatch, code, status):
    message = "Stock insuficiente para la variante REM-001"
    error = APIError({"code": code, "message": message, "details": SECRET, "hint": None})
    monkeypatch.setattr(CatalogoService, "get_marcas", raiser(error))

    response = auth_client.get("/api/v1/catalogos/marcas")

    assert response.status_code == status
    assert response.json() == {"detail": message}
    assert "internal-detail" not in response.text


def test_unknown_mu_code_is_not_trusted(auth_client, monkeypatch):
    monkeypatch.setattr(CatalogoService, "get_marcas", raiser(api_error("MU999")))

    response = auth_client.get("/api/v1/catalogos/marcas")

    assert response.status_code == 500
    assert response.json() == {"detail": "Error interno del servidor"}


def test_duplicate_on_create_is_a_conflict(auth_client, monkeypatch):
    monkeypatch.setattr(CatalogoService, "create_marca", raiser(api_error("23505")))

    response = auth_client.post("/api/v1/catalogos/marcas", json={"nombre": "Acme"})

    assert response.status_code == 409
    assert response.json() == {"detail": "Conflicto: el registro ya existe"}


def test_unhandled_exception_returns_generic_500(auth_client, monkeypatch):
    monkeypatch.setattr(CatalogoService, "get_marcas", raiser(RuntimeError("boom internal-detail")))

    response = auth_client.get("/api/v1/catalogos/marcas")

    assert response.status_code == 500
    assert response.json() == {"detail": "Error interno del servidor"}


def test_unhandled_exception_on_delete_is_not_echoed(auth_client, monkeypatch):
    monkeypatch.setattr(CatalogoService, "delete_marca", raiser(RuntimeError("boom internal-detail")))

    response = auth_client.delete("/api/v1/catalogos/marcas/1")

    assert response.status_code == 500
    assert response.json() == {"detail": "Error interno del servidor"}


def test_business_value_error_message_is_kept(auth_client, monkeypatch):
    message = "No se puede eliminar la marca porque hay productos asignados a ella."
    monkeypatch.setattr(CatalogoService, "delete_marca", raiser(ValueError(message)))

    response = auth_client.delete("/api/v1/catalogos/marcas/1")

    assert response.status_code == 400
    assert response.json() == {"detail": message}


def test_delete_missing_marca_returns_404(auth_client, monkeypatch):
    monkeypatch.setattr(CatalogoService, "delete_marca", lambda marca_id: False)

    response = auth_client.delete("/api/v1/catalogos/marcas/1")

    assert response.status_code == 404
    assert response.json() == {"detail": "Marca no encontrada"}


def test_delete_missing_categoria_returns_404(auth_client, monkeypatch):
    monkeypatch.setattr(CatalogoService, "delete_categoria", lambda categoria_id: False)

    response = auth_client.delete("/api/v1/catalogos/categorias/1")

    assert response.status_code == 404
    assert response.json() == {"detail": "Categoría no encontrada"}
