from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from app.api.auth_deps import RoleChecker
from app.api.deps import get_clover_connection
from app.integrations.clover.connection import CloverConnection
from app.schemas.pagos import CloverConectarResponse, CloverDesconectarResponse

router = APIRouter()


@router.get("/conectar", response_model=CloverConectarResponse)
def conectar_clover(
    current_user=Depends(RoleChecker(["admin"])),
    connection: CloverConnection = Depends(get_clover_connection),
):
    """URL of Clover's authorization page; the POS sends the admin's browser there."""
    return {"authorize_url": connection.authorize_url(current_user)}


@router.get(
    "/callback",
    status_code=302,
    response_class=RedirectResponse,
    responses={302: {"description": "Redirect to the POS settings page with `?clover=ok` or `?clover=error&motivo=`"}},
)
def clover_callback(
    code: Optional[str] = Query(default=None),
    merchant_id: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    connection: CloverConnection = Depends(get_clover_connection),
):
    """Where Clover sends the browser back. No bearer token: the signed `state` authenticates it."""
    target = connection.handle_callback(code, merchant_id, state)
    return RedirectResponse(target, status_code=302, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.post("/desconectar", response_model=CloverDesconectarResponse)
def desconectar_clover(
    current_user=Depends(RoleChecker(["admin"])),
    connection: CloverConnection = Depends(get_clover_connection),
):
    return connection.disconnect(current_user)
