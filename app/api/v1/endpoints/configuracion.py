from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.auth_deps import RoleChecker, get_current_user
from app.schemas.configuracion import ConfiguracionResponse, ConfiguracionUpdate
from app.services.audit import audit
from app.services.configuracion_service import SETTINGS_ID, ConfiguracionService

router = APIRouter()

NOT_FOUND = "Configuración no encontrada"


@router.get("/", response_model=ConfiguracionResponse)
def get_configuracion(current_user=Depends(get_current_user)):
    row = ConfiguracionService.get()
    if not row:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return row


@router.patch("/", response_model=ConfiguracionResponse)
def update_configuracion(
    update: ConfiguracionUpdate,
    background_tasks: BackgroundTasks,
    current_user=Depends(RoleChecker(["admin"])),
):
    changes = update.model_dump(exclude_unset=True)
    row = ConfiguracionService.update(changes, current_user.id)
    if not row:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    audit(
        background_tasks,
        current_user,
        "UPDATE",
        "configuracion",
        entidad_id=SETTINGS_ID,
        payload=changes,
        respuesta=row,
    )
    return row
