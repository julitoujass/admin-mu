from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.api import auth_deps
from app.api.auth_deps import AppUser
from app.services import log_service, usuario_service
from tests.fakes import FakeSupabase

API = "/api/v1/usuarios"
ADMIN_ID = "00000000-0000-0000-0000-000000000001"  # the `auth_client` user
TARGET_ID = "33333333-3333-4333-8333-333333333333"
ADMIN_ROLE = {"id": 1, "nombre": "admin"}
EMPLOYEE_ROLE = {"id": 2, "nombre": "empleado"}


def profile(user_id=TARGET_ID, role=EMPLOYEE_ROLE, activo=True):
    return {
        "id": user_id,
        "nombre": "Ana",
        "apellido": "Pérez",
        "activo": activo,
        "rol_id": role["id"] if role else None,
        "roles": role,
        "created_at": "2026-11-11T12:00:00+00:00",
    }


def updated_row(**changes):
    """Row as returned by the UPDATE: no embedded `roles`."""
    row = {**profile(), **changes}
    row.pop("roles")
    return row


def use_db(monkeypatch, *responses):
    fake = FakeSupabase(*responses)
    monkeypatch.setattr(usuario_service, "supabase", fake)
    return fake


def updates(db):
    return [q for q in db.queries if q.args_of("update")]


def logged_events():
    return [call.args[0]["evento"] for call in log_service.supabase.table.return_value.insert.call_args_list]


# --- /me ----------------------------------------------------------------------


def test_me_reports_role_and_active_flag(employee_client):
    response = employee_client.get(f"{API}/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": "00000000-0000-0000-0000-000000000002",
        "email": "empleado@example.com",
        "rol": "empleado",
        "activo": True,
    }


# --- PATCH /{id}/rol ----------------------------------------------------------


def test_role_change_updates_profile_and_returns_new_role(auth_client, monkeypatch):
    db = use_db(monkeypatch, [profile()], [ADMIN_ROLE], [updated_row(rol_id=1)])

    response = auth_client.patch(f"{API}/{TARGET_ID}/rol", json={"rol_id": 1})

    assert response.status_code == 200
    assert response.json()["roles"] == ADMIN_ROLE
    assert response.json()["id"] == TARGET_ID
    (update,) = updates(db)
    assert update.name == "perfiles"
    assert update.args_of("update") == [({"rol_id": 1},)]
    assert update.args_of("eq") == [("id", TARGET_ID)]
    assert logged_events() == ["UPDATE_ROL"]


def test_role_change_returns_404_for_unknown_user(auth_client, monkeypatch):
    db = use_db(monkeypatch, [])

    response = auth_client.patch(f"{API}/{TARGET_ID}/rol", json={"rol_id": 1})

    assert response.status_code == 404
    assert response.json() == {"detail": "Usuario no encontrado"}
    assert updates(db) == []


def test_role_change_returns_400_for_unknown_role(auth_client, monkeypatch):
    db = use_db(monkeypatch, [profile()], [])

    response = auth_client.patch(f"{API}/{TARGET_ID}/rol", json={"rol_id": 99})

    assert response.status_code == 400
    assert response.json() == {"detail": "El rol indicado no existe"}
    assert updates(db) == []
    assert logged_events() == []


def test_admin_cannot_demote_themself(auth_client, monkeypatch):
    db = use_db(monkeypatch, [profile(ADMIN_ID, ADMIN_ROLE)], [EMPLOYEE_ROLE])

    response = auth_client.patch(f"{API}/{ADMIN_ID}/rol", json={"rol_id": 2})

    assert response.status_code == 409
    assert response.json() == {"detail": "No podés quitarte el rol de administrador"}
    assert updates(db) == []


def test_admin_may_keep_their_own_admin_role(auth_client, monkeypatch):
    use_db(monkeypatch, [profile(ADMIN_ID, ADMIN_ROLE)], [ADMIN_ROLE], [updated_row(rol_id=1)])

    response = auth_client.patch(f"{API}/{ADMIN_ID}/rol", json={"rol_id": 1})

    assert response.status_code == 200


def test_cannot_demote_the_last_active_admin(auth_client, monkeypatch):
    # third query: no other active admin is left
    db = use_db(monkeypatch, [profile(role=ADMIN_ROLE)], [EMPLOYEE_ROLE], [])

    response = auth_client.patch(f"{API}/{TARGET_ID}/rol", json={"rol_id": 2})

    assert response.status_code == 409
    assert response.json() == {"detail": "Debe quedar al menos un administrador activo"}
    assert updates(db) == []
    check = db.queries[2]
    assert ("rol_id", 1) in check.args_of("eq")
    assert ("activo", True) in check.args_of("eq")
    assert check.args_of("neq") == [("id", TARGET_ID)]


def test_can_demote_an_admin_when_another_active_admin_remains(auth_client, monkeypatch):
    db = use_db(monkeypatch, [profile(role=ADMIN_ROLE)], [EMPLOYEE_ROLE], [{"id": ADMIN_ID}], [updated_row(rol_id=2)])

    response = auth_client.patch(f"{API}/{TARGET_ID}/rol", json={"rol_id": 2})

    assert response.status_code == 200
    assert response.json()["roles"] == EMPLOYEE_ROLE
    assert len(updates(db)) == 1


def test_role_change_invalidates_cached_sessions_of_that_user(auth_client, monkeypatch):
    use_db(monkeypatch, [profile()], [ADMIN_ROLE], [updated_row(rol_id=1)])
    auth_deps._TOKEN_CACHE.set("target-token", AppUser(id=TARGET_ID, email="t@example.com", rol="empleado"))
    auth_deps._TOKEN_CACHE.set("other-token", AppUser(id=ADMIN_ID, email="a@example.com", rol="admin"))

    auth_client.patch(f"{API}/{TARGET_ID}/rol", json={"rol_id": 1})

    assert auth_deps._TOKEN_CACHE.get("target-token") is None
    assert auth_deps._TOKEN_CACHE.get("other-token") is not None


@pytest.mark.parametrize("body", [{}, {"rol_id": "x"}, {"rol_id": None}])
def test_role_change_validates_body(auth_client, monkeypatch, body):
    db = use_db(monkeypatch)

    response = auth_client.patch(f"{API}/{TARGET_ID}/rol", json=body)

    assert response.status_code == 422
    assert db.queries == []


# --- PATCH /{id}/activo -------------------------------------------------------


def test_deactivating_a_user_updates_profile(auth_client, monkeypatch):
    db = use_db(monkeypatch, [profile()], [updated_row(activo=False)])

    response = auth_client.patch(f"{API}/{TARGET_ID}/activo", json={"activo": False})

    assert response.status_code == 200
    assert response.json()["activo"] is False
    assert response.json()["roles"] == EMPLOYEE_ROLE
    (update,) = updates(db)
    assert update.name == "perfiles"
    assert update.args_of("update") == [({"activo": False},)]
    assert update.args_of("eq") == [("id", TARGET_ID)]
    assert logged_events() == ["UPDATE_ACTIVO"]


def test_reactivating_a_user(auth_client, monkeypatch):
    db = use_db(monkeypatch, [profile(activo=False)], [updated_row(activo=True)])

    response = auth_client.patch(f"{API}/{TARGET_ID}/activo", json={"activo": True})

    assert response.status_code == 200
    assert response.json()["activo"] is True
    assert updates(db)[0].args_of("update") == [({"activo": True},)]


def test_activo_returns_404_for_unknown_user(auth_client, monkeypatch):
    db = use_db(monkeypatch, [])

    response = auth_client.patch(f"{API}/{TARGET_ID}/activo", json={"activo": False})

    assert response.status_code == 404
    assert response.json() == {"detail": "Usuario no encontrado"}
    assert updates(db) == []


def test_admin_cannot_deactivate_themself(auth_client, monkeypatch):
    db = use_db(monkeypatch, [profile(ADMIN_ID, ADMIN_ROLE)])

    response = auth_client.patch(f"{API}/{ADMIN_ID}/activo", json={"activo": False})

    assert response.status_code == 409
    assert response.json() == {"detail": "No podés desactivar tu propio usuario"}
    assert updates(db) == []
    assert logged_events() == []


def test_cannot_deactivate_the_last_active_admin(auth_client, monkeypatch):
    db = use_db(monkeypatch, [profile(role=ADMIN_ROLE)], [])

    response = auth_client.patch(f"{API}/{TARGET_ID}/activo", json={"activo": False})

    assert response.status_code == 409
    assert response.json() == {"detail": "Debe quedar al menos un administrador activo"}
    assert updates(db) == []


def test_can_deactivate_an_admin_when_another_active_admin_remains(auth_client, monkeypatch):
    use_db(monkeypatch, [profile(role=ADMIN_ROLE)], [{"id": ADMIN_ID}], [updated_row(activo=False, rol_id=1)])

    response = auth_client.patch(f"{API}/{TARGET_ID}/activo", json={"activo": False})

    assert response.status_code == 200
    assert response.json()["roles"] == ADMIN_ROLE


def test_activo_change_invalidates_cached_sessions_of_that_user(auth_client, monkeypatch):
    use_db(monkeypatch, [profile()], [updated_row(activo=False)])
    auth_deps._TOKEN_CACHE.set("target-token", AppUser(id=TARGET_ID, email="t@example.com", rol="empleado"))

    auth_client.patch(f"{API}/{TARGET_ID}/activo", json={"activo": False})

    assert auth_deps._TOKEN_CACHE.get("target-token") is None


@pytest.mark.parametrize("body", [{}, {"activo": "tal vez"}, {"activo": None}])
def test_activo_validates_body(auth_client, monkeypatch, body):
    db = use_db(monkeypatch)

    response = auth_client.patch(f"{API}/{TARGET_ID}/activo", json=body)

    assert response.status_code == 422
    assert db.queries == []


def test_deactivated_user_is_rejected_on_the_next_request(client, monkeypatch):
    """End to end: a cached session stops working as soon as the user is deactivated."""
    profiles = {"admin-token": (ADMIN_ID, "admin", True), "target-token": (TARGET_ID, "empleado", True)}
    fake_auth = MagicMock()

    def get_user(token):
        return SimpleNamespace(user=SimpleNamespace(id=profiles[token][0], email=f"{token}@example.com"))

    current = {}

    def table(_name):
        query = MagicMock()

        def eq(_column, user_id):
            current["id"] = user_id
            return query

        def execute():
            _, rol, activo = next(p for p in profiles.values() if p[0] == current["id"])
            return SimpleNamespace(data={"activo": activo, "roles": {"nombre": rol}})

        query.select.return_value = query
        query.eq.side_effect = eq
        query.single.return_value = query
        query.execute.side_effect = execute
        return query

    fake_auth.auth.get_user.side_effect = get_user
    fake_auth.table.side_effect = table
    monkeypatch.setattr(auth_deps, "supabase", fake_auth)
    use_db(monkeypatch, [profile()], [updated_row(activo=False)])

    target = {"Authorization": "Bearer target-token"}
    assert client.get(f"{API}/me", headers=target).status_code == 200  # now cached

    response = client.patch(
        f"{API}/{TARGET_ID}/activo", json={"activo": False}, headers={"Authorization": "Bearer admin-token"}
    )
    assert response.status_code == 200
    profiles["target-token"] = (TARGET_ID, "empleado", False)

    response = client.get(f"{API}/me", headers=target)
    assert response.status_code == 403
    assert response.json() == {"detail": "Usuario inactivo"}
