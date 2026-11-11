from types import SimpleNamespace
from unittest.mock import MagicMock

from postgrest.exceptions import APIError

from app.api import auth_deps
from app.api.auth_deps import AppUser, TTLCache

AUTH = {"Authorization": "Bearer some-token"}


def fake_supabase(monkeypatch, profile=None, profile_error=None, user_id="user-1"):
    """Supabase stand-in: a valid token for `user_id` and the given `perfiles` answer."""
    fake = MagicMock()
    fake.auth.get_user.return_value = SimpleNamespace(user=SimpleNamespace(id=user_id, email="a@example.com"))
    query = fake.table.return_value.select.return_value.eq.return_value.single.return_value
    if profile_error is not None:
        query.execute.side_effect = profile_error
    else:
        query.execute.return_value = SimpleNamespace(data=profile)
    monkeypatch.setattr(auth_deps, "supabase", fake)
    return fake


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
    fake_supabase(monkeypatch, {"activo": True, "roles": {"nombre": "admin"}})

    response = client.get("/api/v1/usuarios/me", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"id": "user-1", "email": "a@example.com", "rol": "admin", "activo": True}


def test_role_and_active_flag_are_read_in_a_single_query(client, monkeypatch):
    fake = fake_supabase(monkeypatch, {"activo": True, "roles": {"nombre": "admin"}})

    client.get("/api/v1/usuarios/me", headers=AUTH)

    fake.table.assert_called_once_with("perfiles")
    fake.table.return_value.select.assert_called_once_with("activo, roles(nombre)")
    fake.table.return_value.select.return_value.eq.assert_called_once_with("id", "user-1")


# --- inactive users -----------------------------------------------------------


def test_inactive_user_is_rejected_with_403(client, monkeypatch):
    fake_supabase(monkeypatch, {"activo": False, "roles": {"nombre": "admin"}})

    response = client.get("/api/v1/usuarios/me", headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"detail": "Usuario inactivo"}


def test_inactive_user_is_not_cached(client, monkeypatch):
    fake = fake_supabase(monkeypatch, {"activo": False, "roles": {"nombre": "empleado"}})
    client.get("/api/v1/usuarios/me", headers=AUTH)

    # Reactivated: the very next request must go through.
    query = fake.table.return_value.select.return_value.eq.return_value.single.return_value
    query.execute.return_value = SimpleNamespace(data={"activo": True, "roles": {"nombre": "empleado"}})
    response = client.get("/api/v1/usuarios/me", headers=AUTH)

    assert response.status_code == 200


def test_missing_profile_falls_back_to_active_employee(client, monkeypatch):
    not_found = APIError({"code": "PGRST116", "message": "0 rows", "details": None, "hint": None})
    fake_supabase(monkeypatch, profile_error=not_found)

    response = client.get("/api/v1/usuarios/me", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"id": "user-1", "email": "a@example.com", "rol": "empleado", "activo": True}


def test_empty_profile_falls_back_to_active_employee(client, monkeypatch):
    fake_supabase(monkeypatch, None)

    response = client.get("/api/v1/usuarios/me", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["rol"] == "empleado"
    assert response.json()["activo"] is True


def test_profile_without_role_is_an_employee(client, monkeypatch):
    fake_supabase(monkeypatch, {"activo": True, "roles": None})

    response = client.get("/api/v1/usuarios/me", headers=AUTH)

    assert response.json()["rol"] == "empleado"


def test_profile_lookup_failure_does_not_let_the_request_through(client, monkeypatch):
    """If the active flag cannot be read we cannot know the user is allowed in."""
    fake_supabase(monkeypatch, profile_error=RuntimeError("db.internal is down"))

    response = client.get("/api/v1/usuarios/me", headers=AUTH)

    assert response.status_code == 503
    assert response.json() == {"detail": "No se pudo verificar el usuario. Intentá de nuevo."}
    assert "db.internal" not in response.text


# --- token cache --------------------------------------------------------------


def test_second_request_with_same_token_uses_the_cache(client, monkeypatch):
    fake = fake_supabase(monkeypatch, {"activo": True, "roles": {"nombre": "admin"}})

    client.get("/api/v1/usuarios/me", headers=AUTH)
    client.get("/api/v1/usuarios/me", headers=AUTH)

    assert fake.auth.get_user.call_count == 1


def test_invalidate_user_forces_a_fresh_lookup(client, monkeypatch):
    fake = fake_supabase(monkeypatch, {"activo": True, "roles": {"nombre": "admin"}})
    client.get("/api/v1/usuarios/me", headers=AUTH)

    auth_deps.invalidate_user("user-1")
    client.get("/api/v1/usuarios/me", headers=AUTH)

    assert fake.auth.get_user.call_count == 2


def test_invalidate_user_only_drops_that_users_tokens():
    auth_deps._TOKEN_CACHE.clear()
    auth_deps._TOKEN_CACHE.set("t1", AppUser(id="user-1", email="a@example.com", rol="admin"))
    auth_deps._TOKEN_CACHE.set("t2", AppUser(id="user-1", email="a@example.com", rol="admin"))
    auth_deps._TOKEN_CACHE.set("t3", AppUser(id="user-2", email="b@example.com", rol="empleado"))

    auth_deps.invalidate_user("user-1")

    assert auth_deps._TOKEN_CACHE.get("t1") is None
    assert auth_deps._TOKEN_CACHE.get("t2") is None
    assert auth_deps._TOKEN_CACHE.get("t3").id == "user-2"
    auth_deps._TOKEN_CACHE.clear()


def test_token_cache_is_bounded_and_short_lived():
    assert auth_deps.CACHE_TTL == 60
    assert auth_deps.CACHE_MAX_ENTRIES == 1024
    assert isinstance(auth_deps._TOKEN_CACHE, TTLCache)
    assert auth_deps._TOKEN_CACHE.ttl == 60
    assert auth_deps._TOKEN_CACHE.max_entries == 1024


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_ttl_cache_returns_value_until_it_expires():
    clock = Clock()
    cache = TTLCache(max_entries=10, ttl=60, timer=clock)
    cache.set("k", "v")

    clock.now += 59
    assert cache.get("k") == "v"

    clock.now += 1
    assert cache.get("k") is None
    assert len(cache) == 0


def test_ttl_cache_evicts_expired_entries_on_insert():
    clock = Clock()
    cache = TTLCache(max_entries=10, ttl=60, timer=clock)
    cache.set("old-1", 1)
    cache.set("old-2", 2)

    clock.now += 61
    cache.set("new", 3)

    assert len(cache) == 1
    assert cache.get("new") == 3


def test_ttl_cache_evicts_oldest_entry_when_full():
    clock = Clock()
    cache = TTLCache(max_entries=3, ttl=60, timer=clock)
    for key in ("a", "b", "c"):
        clock.now += 1
        cache.set(key, key)

    cache.set("d", "d")

    assert len(cache) == 3
    assert cache.get("a") is None
    assert [cache.get(k) for k in ("b", "c", "d")] == ["b", "c", "d"]


def test_ttl_cache_never_exceeds_its_size():
    cache = TTLCache(max_entries=5, ttl=60)
    for index in range(50):
        cache.set(f"k{index}", index)

    assert len(cache) == 5


def test_ttl_cache_overwriting_a_key_renews_it():
    clock = Clock()
    cache = TTLCache(max_entries=2, ttl=60, timer=clock)
    cache.set("a", 1)
    cache.set("b", 2)
    clock.now += 30
    cache.set("a", 10)  # "b" is now the oldest entry

    cache.set("c", 3)

    assert cache.get("b") is None
    assert cache.get("a") == 10
    assert cache.get("c") == 3


def test_ttl_cache_remove_where_and_clear():
    cache = TTLCache(max_entries=5, ttl=60)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)

    cache.remove_where(lambda value: value >= 2)
    assert (cache.get("a"), cache.get("b"), cache.get("c")) == (1, None, None)

    cache.clear()
    assert len(cache) == 0
