from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.supabase import supabase
from typing import Annotated, List
import time

class AppUser:
    def __init__(self, id: str, email: str, rol: str):
        self.id = id
        self.email = email
        self.rol = rol

security = HTTPBearer()

_TOKEN_CACHE = {}
CACHE_TTL = 60 * 5  # 5 minutos

def get_current_user(credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]):
    token = credentials.credentials
    now = time.time()

    # Check cache first
    if token in _TOKEN_CACHE:
        cached_user, exp = _TOKEN_CACHE[token]
        if now < exp:
            return cached_user
        else:
            del _TOKEN_CACHE[token]

    try:
        # Supabase client 'get_user' verifies the token with the Supabase Auth server
        user = supabase.auth.get_user(token)
        if not user:
             raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Attach role from perfiles
        rol = "empleado"
        try:
            profile_res = supabase.table("perfiles").select("roles(nombre)").eq("id", user.user.id).single().execute()
            if profile_res.data and profile_res.data.get("roles"):
                rol = profile_res.data["roles"]["nombre"]
        except Exception:
            pass

        app_user = AppUser(id=user.user.id, email=user.user.email, rol=rol)
        _TOKEN_CACHE[token] = (app_user, now + CACHE_TTL)
        return app_user
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

class RoleChecker:
    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user = Depends(get_current_user)):
        rol = getattr(current_user, "rol", "empleado")
        if rol not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos suficientes para realizar esta acción."
            )
        return current_user
