from typing import Any, Literal

from fastapi import BackgroundTasks
from fastapi.encoders import jsonable_encoder

from app.services.log_service import LogService

AuditEvent = Literal[
    "CREATE",
    "UPDATE",
    "DELETE",
    "ADJUST_STOCK",
    "OPEN_CAJA",
    "CLOSE_CAJA",
    "CASH_MOVEMENT",
    "CREATE_SALE",
    "UPDATE_ROL",
    "UPDATE_ACTIVO",
]


def audit(
    background_tasks: BackgroundTasks,
    user: Any,
    evento: AuditEvent,
    entidad: str,
    entidad_id: Any = None,
    payload: Any = None,
    respuesta: Any = None,
    descripcion: str | None = None,
) -> None:
    """Queue an audit record (table `logs`) to be written after the response is sent.

    Payloads are converted to JSON-safe values (UUID, datetime, Decimal, ...) here,
    so callers can pass `model_dump()` output or database rows as they are.
    """
    background_tasks.add_task(
        LogService.registrar_log,
        usuario_id=user.id,
        evento=evento,
        entidad=entidad,
        entidad_id=None if entidad_id is None else str(entidad_id),
        descripcion=descripcion,
        payload_enviado=None if payload is None else jsonable_encoder(payload),
        respuesta_recibida=None if respuesta is None else jsonable_encoder(respuesta),
    )
