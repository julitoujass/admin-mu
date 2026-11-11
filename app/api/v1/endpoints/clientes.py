from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.api.auth_deps import get_current_user
from app.schemas.clientes import ClienteCreate, ClienteResponse, ClienteUpdate
from app.services.audit import audit
from app.services.cliente_service import ClienteService

router = APIRouter()

@router.get("/", response_model=List[ClienteResponse])
def get_clientes(
    query: Optional[str] = None,
    # Default 1000: the POS client selector filters this list in the browser.
    limit: int = Query(1000, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user = Depends(get_current_user),
):
    return ClienteService.get_clientes(query, limit, offset)

@router.post("/", response_model=ClienteResponse)
def create_cliente(cliente: ClienteCreate, background_tasks: BackgroundTasks, current_user = Depends(get_current_user)):
    result = ClienteService.create_cliente(cliente)
    audit(
        background_tasks,
        current_user,
        "CREATE",
        "clientes",
        entidad_id=str(result["id"]),
        payload=cliente.model_dump(),
        respuesta=result,
    )
    return result

@router.patch("/{id}", response_model=ClienteResponse)
def update_cliente(id: UUID, cliente_update: ClienteUpdate, background_tasks: BackgroundTasks, current_user = Depends(get_current_user)):
    cliente = ClienteService.update_cliente(str(id), cliente_update)
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    audit(
        background_tasks,
        current_user,
        "UPDATE",
        "clientes",
        entidad_id=str(id),
        payload=cliente_update.model_dump(exclude_unset=True),
        respuesta=cliente,
    )
    return cliente
