from datetime import datetime
from typing import Any, List, Optional, Union

from pydantic import BaseModel

from app.schemas.ventas import PersonaRef


class AuditLogItem(BaseModel):
    id: Union[int, str]
    created_at: datetime
    evento: str
    entidad: Optional[str] = None
    entidad_id: Optional[str] = None
    descripcion: Optional[str] = None
    estado: Optional[str] = None
    payload_enviado: Optional[Any] = None
    respuesta_recibida: Optional[Any] = None
    usuario: Optional[PersonaRef] = None


class AuditLogListResponse(BaseModel):
    items: List[AuditLogItem]
    # Exact number of records matching the filters, regardless of limit/offset.
    total: int
