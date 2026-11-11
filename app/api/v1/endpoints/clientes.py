from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.auth_deps import get_current_user
from app.schemas.clientes import ClienteCreate, ClienteResponse, ClienteUpdate
from app.services.cliente_service import ClienteService
from app.services.log_service import LogService

router = APIRouter()

@router.get("/", response_model=List[ClienteResponse])
def get_clientes(query: Optional[str] = None, current_user = Depends(get_current_user)):
    return ClienteService.get_clientes(query)

@router.post("/", response_model=ClienteResponse)
def create_cliente(cliente: ClienteCreate, background_tasks: BackgroundTasks, current_user = Depends(get_current_user)):
    result = ClienteService.create_cliente(cliente)
    background_tasks.add_task(
        LogService.registrar_log,
        usuario_id=current_user.id,
        evento="CREATE",
        entidad="clientes",
        entidad_id=str(result["id"]),
        payload_enviado=cliente.model_dump(),
        respuesta_recibida=result
    )
    return result

@router.patch("/{id}", response_model=ClienteResponse)
def update_cliente(id: str, cliente_update: ClienteUpdate, background_tasks: BackgroundTasks, current_user = Depends(get_current_user)):
    cliente = ClienteService.update_cliente(id, cliente_update)
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente not found")
    background_tasks.add_task(
        LogService.registrar_log,
        usuario_id=current_user.id,
        evento="UPDATE",
        entidad="clientes",
        entidad_id=id,
        payload_enviado=cliente_update.model_dump(exclude_unset=True),
        respuesta_recibida=cliente
    )
    return cliente
