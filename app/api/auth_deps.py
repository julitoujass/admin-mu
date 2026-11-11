import logging
import threading
import time
from collections import OrderedDict
from typing import Annotated, Any, Callable, List

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from postgrest.exceptions import APIError

from app.core.supabase import supabase

logger = logging.getLogger(__name__)

DEFAULT_ROLE = "empleado"
ROW_NOT_FOUND = "PGRST116"  # PostgREST: `.single()` matched no row

CACHE_TTL = 60  # seconds: role changes and deactivations apply within a minute
CACHE_MAX_ENTRIES = 1024


class AppUser:
    def __init__(self, id: str, email: str, rol: str, activo: bool = True):
        self.id = id
        self.email = email
        self.rol = rol
        self.activo = activo


class TTLCache:
    """Small thread-safe cache with a fixed size and a fixed time-to-live.

    Every entry lives `ttl` seconds from the moment it is written. Inserting
    first drops the expired entries and then, if the cache is still full, the
    oldest ones, so it never holds more than `max_entries`.
    """

    def __init__(self, max_entries: int, ttl: float, timer: Callable[[], float] = time.monotonic):
        self.max_entries = max_entries
        self.ttl = ttl
        self._timer = timer
        # key -> (value, expires_at). The TTL is constant, so insertion order is expiry order.
        self._entries: OrderedDict[Any, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if self._timer() >= expires_at:
                del self._entries[key]
                return None
            return value

    def set(self, key, value) -> None:
        with self._lock:
            now = self._timer()
            self._entries.pop(key, None)
            while self._entries and next(iter(self._entries.values()))[1] <= now:
                self._entries.popitem(last=False)
            while len(self._entries) >= self.max_entries:
                self._entries.popitem(last=False)
            self._entries[key] = (value, now + self.ttl)

    def remove_where(self, predicate: Callable[[Any], bool]) -> None:
        """Drop every entry whose value satisfies `predicate`."""
        with self._lock:
            for key in [key for key, (value, _) in self._entries.items() if predicate(value)]:
                del self._entries[key]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


security = HTTPBearer()

# token -> AppUser. Per process: it is not shared between workers.
_TOKEN_CACHE = TTLCache(max_entries=CACHE_MAX_ENTRIES, ttl=CACHE_TTL)


def invalidate_user(user_id) -> None:
    """Forget the cached sessions of a user so a role or `activo` change applies at once."""
    target = str(user_id)
    _TOKEN_CACHE.remove_where(lambda user: str(user.id) == target)


def _credentials_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _load_profile(user_id: str) -> tuple[str, bool]:
    """Role name and active flag of a user, read from `perfiles` in a single query.

    A user without a profile (or without a role) is an active `empleado`. Any
    other failure is NOT treated as "no profile": the active flag could not be
    read, so the request is refused instead of letting a deactivated user in.
    """
    try:
        res = supabase.table("perfiles").select("activo, roles(nombre)").eq("id", user_id).single().execute()
    except APIError as exc:
        if exc.code == ROW_NOT_FOUND:
            return DEFAULT_ROLE, True
        logger.error("Profile lookup failed", exc_info=True)
        raise _profile_unavailable() from None
    except Exception:
        logger.error("Profile lookup failed", exc_info=True)
        raise _profile_unavailable() from None

    data = getattr(res, "data", None)
    if not data:
        return DEFAULT_ROLE, True
    role = data.get("roles") or {}
    # Only an explicit `false` deactivates; a null flag keeps the column default (active).
    return role.get("nombre") or DEFAULT_ROLE, data.get("activo") is not False


def _profile_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="No se pudo verificar el usuario. Intentá de nuevo.",
    )


def get_current_user(credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]):
    token = credentials.credentials

    cached_user = _TOKEN_CACHE.get(token)
    if cached_user is not None:
        return cached_user

    try:
        # Supabase client 'get_user' verifies the token with the Supabase Auth server
        user = supabase.auth.get_user(token)
    except Exception:
        # Never echo the provider error to the client; it is only logged.
        logger.warning("Token validation failed", exc_info=True)
        raise _credentials_error() from None

    if not user or not getattr(user, "user", None):
        raise _credentials_error()

    rol, activo = _load_profile(user.user.id)
    if not activo:
        # Not cached, so reactivating the user takes effect immediately.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo")

    app_user = AppUser(id=user.user.id, email=user.user.email, rol=rol, activo=activo)
    _TOKEN_CACHE.set(token, app_user)
    return app_user


class RoleChecker:
    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user = Depends(get_current_user)):
        rol = getattr(current_user, "rol", DEFAULT_ROLE)
        if rol not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos suficientes para realizar esta acción."
            )
        return current_user
