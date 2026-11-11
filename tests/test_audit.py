from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import get_args
from uuid import UUID

from fastapi import BackgroundTasks

from app.api.v1.endpoints import productos
from app.services import log_service
from app.services.audit import AuditEvent, audit
from app.services.log_service import LogService

USER = SimpleNamespace(id="00000000-0000-0000-0000-000000000001")
VARIANT_ID = "11111111-1111-4111-8111-111111111111"


def queued(tasks: BackgroundTasks):
    assert len(tasks.tasks) == 1
    task = tasks.tasks[0]
    return task.func, task.kwargs


def test_event_names_are_the_normalized_set():
    assert set(get_args(AuditEvent)) == {
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
    }


def test_audit_queues_the_log_service_with_the_user_id():
    tasks = BackgroundTasks()

    audit(tasks, USER, "DELETE", "productos", entidad_id=UUID(VARIANT_ID))

    func, kwargs = queued(tasks)
    assert func == LogService.registrar_log
    assert kwargs["usuario_id"] == USER.id
    assert kwargs["evento"] == "DELETE"
    assert kwargs["entidad"] == "productos"
    assert kwargs["entidad_id"] == VARIANT_ID
    assert kwargs["payload_enviado"] is None
    assert kwargs["respuesta_recibida"] is None


def test_audit_serializes_payloads_to_json_safe_values():
    tasks = BackgroundTasks()
    moment = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)

    audit(
        tasks,
        USER,
        "UPDATE",
        "productos",
        entidad_id=VARIANT_ID,
        payload={"id": UUID(VARIANT_ID), "price": Decimal("10.50")},
        respuesta={"at": moment, "nested": [UUID(VARIANT_ID)]},
        descripcion="note",
    )

    _, kwargs = queued(tasks)
    assert kwargs["payload_enviado"] == {"id": VARIANT_ID, "price": 10.5}
    assert kwargs["respuesta_recibida"] == {"at": moment.isoformat(), "nested": [VARIANT_ID]}
    assert kwargs["descripcion"] == "note"


def test_endpoint_audits_with_the_normalized_event(auth_client, monkeypatch):
    calls = []
    monkeypatch.setattr(productos, "audit", lambda *args, **kwargs: calls.append((args, kwargs)))
    row = {"id": VARIANT_ID, "producto_id": VARIANT_ID, "precio_venta": 1, "stock_actual": 3}
    monkeypatch.setattr(productos.ProductService, "update_stock", lambda update: row)

    response = auth_client.patch(
        "/api/v1/productos/inventario/stock",
        json={"variante_id": VARIANT_ID, "cantidad": 2, "motivo": "recount"},
    )

    assert response.status_code == 200
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[2] == "ADJUST_STOCK"
    assert args[3] == "producto_variantes"
    assert kwargs["entidad_id"] == VARIANT_ID


def test_endpoint_writes_the_normalized_event_to_the_logs_table(auth_client, monkeypatch):
    monkeypatch.setattr(productos.ProductService, "delete_product", lambda product_id: True)

    response = auth_client.delete(f"/api/v1/productos/{VARIANT_ID}")

    assert response.status_code == 200
    insert = log_service.supabase.table.return_value.insert
    assert insert.call_args.args[0]["evento"] == "DELETE"
