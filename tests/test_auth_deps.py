from types import SimpleNamespace
from unittest.mock import MagicMock

from app.api import auth_deps

AUTH = {"Authorization": "Bearer some-token"}


def test_returns_401_without_exception_text_when_supabase_fails(client, monkeypatch):
    fake = MagicMock()
    fake.auth.get_user.side_effect = RuntimeError("upstream auth.internal exploded")
    monkeypatch.setattr(auth_deps, "supabase", fake)

    response = client.get("/api/v1/usuarios/me", headers=AUTH)

    assert response.status_code == 401
    assert response.json() == {"detail": "No se pudieron validar las credenciales"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert "auth.internal" not in response.text


def test_returns_401_when_supabase_returns_no_user(client, monkeypatch):
    fake = MagicMock()
    fake.auth.get_user.return_value = None
    monkeypatch.setattr(auth_deps, "supabase", fake)

    response = client.get("/api/v1/usuarios/me", headers=AUTH)

    assert response.status_code == 401
    assert response.json() == {"detail": "No se pudieron validar las credenciales"}


def test_valid_token_resolves_user_and_role(client, monkeypatch):
    fake = MagicMock()
    fake.auth.get_user.return_value = SimpleNamespace(user=SimpleNamespace(id="user-1", email="a@example.com"))
    query = fake.table.return_value.select.return_value.eq.return_value.single.return_value
    query.execute.return_value = SimpleNamespace(data={"roles": {"nombre": "admin"}})
    monkeypatch.setattr(auth_deps, "supabase", fake)

    response = client.get("/api/v1/usuarios/me", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"id": "user-1", "email": "a@example.com", "rol": "admin"}
