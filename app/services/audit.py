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
    "CANCEL_SALE",
    "RETURN_SALE",
    "UPDATE_ROL",
    "UPDATE_ACTIVO",
    # Terminal charges (card / QR); see app/services/pago_service.py.
    "CHARGE_STARTED",
    "CHARGE_APPROVED",
    "CHARGE_FAILED",
    "CHARGE_UNKNOWN",
    "CHARGE_CANCELLED",
    "REFUND_DONE",
    "TERMINAL_SETTINGS",
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


def record_audit(
    usuario_id: Any,
    evento: AuditEvent,
    entidad: str,
    entidad_id: Any = None,
    payload: Any = None,
    respuesta: Any = None,
    descripcion: str | None = None,
) -> None:
    """Write an audit record right now.

    For code that runs outside a request (background jobs, the reconciliation sweep),
    where there is no `BackgroundTasks` to queue on. Never raises: `LogService` logs and
    swallows database failures.
    """
    LogService.registrar_log(
        usuario_id=usuario_id,
        evento=evento,
        entidad=entidad,
        entidad_id=None if entidad_id is None else str(entidad_id),
        descripcion=descripcion,
        payload_enviado=None if payload is None else jsonable_encoder(payload),
        respuesta_recibida=None if respuesta is None else jsonable_encoder(respuesta),
    )
