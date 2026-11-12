"""Supabase adapter of the `PagoStore` port: the queries it sends and how it maps errors."""

from datetime import datetime, timezone

import pytest
from postgrest.exceptions import APIError

from app.repositories import supabase_pago_store
from app.repositories.supabase_pago_store import SupabasePagoStore
from app.services.pago_ports import ActiveChargeExists, SaleRejected
from tests.fakes import Counted, FakeSupabase

PAGO_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
USER_ID = "00000000-0000-0000-0000-000000000002"
VARIANT_A = "11111111-1111-4111-8111-111111111111"
CLIENT_ID = "44444444-4444-4444-8444-444444444444"
CART = {
    "items": [{"variante_id": VARIANT_A, "cantidad": 2}],
    "cliente_id": CLIENT_ID,
    "descuento": {"tipo": "porcentaje", "valor": 5.0},
    "recargo": None,
    "es_admin": False,
}
PAGO = {"id": PAGO_ID, "usuario_id": USER_ID, "metodo_pago": "QR", "monto": 2850.0, "carrito": CART, "estado": "aprobado"}


def api_error(code, message="boom", details=None):
    return APIError({"code": code, "message": message, "details": details, "hint": None})


@pytest.fixture
def db(monkeypatch):
    def install(*responses):
        fake = FakeSupabase(*responses)
        monkeypatch.setattr(supabase_pago_store, "supabase", fake)
        return fake

    return install


def test_quote_calls_cotizar_venta_without_writing(db):
    fake = db({"subtotal": 3000, "descuento": 150, "recargo": 0, "total": 2850})

    quote = SupabasePagoStore().quote(CART, es_admin=False)

    assert quote["total"] == 2850
    [call] = fake.queries
    assert (call.kind, call.name) == ("rpc", "cotizar_venta")
    assert call.params == {
        "p_items": [{"variante_id": VARIANT_A, "cantidad": 2}],
        "p_descuento_tipo": "porcentaje",
        "p_descuento_valor": 5.0,
        "p_recargo_tipo": None,
        "p_recargo_valor": 0,
        "p_es_admin": False,
    }


def test_quote_business_errors_are_not_translated(db):
    db(api_error("MU002", "Stock insuficiente"))

    with pytest.raises(APIError):
        SupabasePagoStore().quote(CART, es_admin=True)


def test_register_sale_uses_the_charge_as_idempotency_key_and_expected_total(db):
    fake = db([{"id": "venta-1", "total": 2850.0}])

    venta = SupabasePagoStore().register_sale(PAGO)

    assert venta == {"id": "venta-1", "total": 2850.0}
    [call] = fake.rpc_calls("registrar_venta_con_pago")
    assert call.params == {
        "p_pago_externo_id": PAGO_ID,
        "p_usuario_id": USER_ID,
        "p_metodo_pago": "QR",
        "p_items": [{"variante_id": VARIANT_A, "cantidad": 2}],
        "p_total_esperado": 2850.0,
        "p_cliente_id": CLIENT_ID,
        "p_descuento_tipo": "porcentaje",
        "p_descuento_valor": 5.0,
        "p_recargo_tipo": None,
        "p_recargo_valor": 0,
        "p_es_admin": False,
    }


def test_register_sale_rejected_by_the_database_keeps_only_business_messages(db):
    db(api_error("MU011", "El total cambió desde que se inició el cobro (3000.00 vs 2850.00)"))
    with pytest.raises(SaleRejected) as rejected:
        SupabasePagoStore().register_sale(PAGO)
    assert rejected.value.message == "El total cambió desde que se inició el cobro (3000.00 vs 2850.00)"
    assert rejected.value.code == "MU011"

    db(api_error("42P01", "relation secret_table does not exist"))
    with pytest.raises(SaleRejected) as rejected:
        SupabasePagoStore().register_sale(PAGO)
    assert rejected.value.message is None


def test_register_sale_connection_errors_are_not_a_rejection(db):
    db(ConnectionError("server disconnected"))

    with pytest.raises(ConnectionError):
        SupabasePagoStore().register_sale(PAGO)


def test_insert_maps_the_single_active_charge_index_to_a_domain_error(db):
    row = {"estado": "pendiente", "external_payment_id": "e" * 32}
    fake = db([{"id": PAGO_ID, **row}])
    assert SupabasePagoStore().insert_pago(row)["id"] == PAGO_ID
    assert fake.table_calls("pagos_externos")[0].args_of("insert") == [(row,)]

    db(api_error("23505", 'duplicate key value violates unique constraint "pagos_externos_un_cobro_activo"'))
    with pytest.raises(ActiveChargeExists):
        SupabasePagoStore().insert_pago(row)

    db(api_error("23505", 'duplicate key value violates unique constraint "pagos_externos_external_payment_id_key"'))
    with pytest.raises(APIError):
        SupabasePagoStore().insert_pago(row)

    db(api_error("23514", "check constraint"))
    with pytest.raises(APIError):
        SupabasePagoStore().insert_pago(row)


def test_transition_is_a_compare_and_set_on_the_state(db):
    fake = db([{"id": PAGO_ID, "estado": "enviado"}], [])
    store = SupabasePagoStore()

    assert store.transition(PAGO_ID, "pendiente", "enviado") == {"id": PAGO_ID, "estado": "enviado"}
    assert store.transition(PAGO_ID, "pendiente", "rechazado", error="x") is None  # no row matched

    first, second = fake.table_calls("pagos_externos")
    assert first.args_of("eq") == [("id", PAGO_ID), ("estado", "pendiente")]
    [(values,)] = first.args_of("update")
    assert values["estado"] == "enviado"
    assert datetime.fromisoformat(values["updated_at"]).tzinfo is not None
    [(values,)] = second.args_of("update")
    assert (values["estado"], values["error"]) == ("rechazado", "x")


def test_set_attempts_does_not_touch_updated_at(db):
    fake = db([])

    SupabasePagoStore().set_attempts(PAGO_ID, 3)

    [query] = fake.table_calls("pagos_externos")
    assert query.args_of("update") == [({"intentos_conciliacion": 3},)]
    assert query.args_of("eq") == [("id", PAGO_ID)]


def test_get_pago_and_open_session(db):
    db([{"id": PAGO_ID}], [], [{"id": "session-1"}], [])
    store = SupabasePagoStore()

    assert store.get_pago(PAGO_ID) == {"id": PAGO_ID}
    assert store.get_pago(PAGO_ID) is None
    assert store.open_session_id() == "session-1"
    assert store.open_session_id() is None


def test_list_is_paginated_newest_first_without_cart_or_raw_response(db):
    fake = db(Counted([{"id": PAGO_ID}], 7))

    items, total = SupabasePagoStore().list_pagos("error_registro", limit=10, offset=20)

    assert (items, total) == ([{"id": PAGO_ID}], 7)
    [query] = fake.table_calls("pagos_externos")
    [(columns,)] = query.args_of("select")
    assert "carrito" not in columns and "respuesta" not in columns
    assert query.args_of("eq") == [("estado", "error_registro")]
    assert query.args_of("range") == [(20, 29)]

    fake = db(Counted([], 0))
    SupabasePagoStore().list_pagos(None, limit=50, offset=0)
    assert fake.queries[0].args_of("eq") == []


def test_sweep_candidates_are_unknown_charges_plus_stale_ones(db):
    fake = db([{"id": "unknown"}], [{"id": "stale"}])
    cutoff = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)

    rows = SupabasePagoStore().list_for_sweep(cutoff, max_attempts=10)

    assert rows == [{"id": "unknown"}, {"id": "stale"}]
    unknown, stale = fake.table_calls("pagos_externos")
    assert unknown.args_of("eq") == [("estado", "indeterminado")]
    assert unknown.args_of("lt") == [("intentos_conciliacion", 10)]
    assert stale.args_of("in_") == [("estado", ["pendiente", "enviado", "aprobado"])]
    assert stale.args_of("lt") == [("updated_at", cutoff.isoformat()), ("intentos_conciliacion", 10)]


def test_integration_row_read_and_update(db):
    fake = db([{"id": 1, "habilitado": False}], [{"id": 1, "habilitado": True}], [])
    store = SupabasePagoStore()

    assert store.get_integration() == {"id": 1, "habilitado": False}
    assert store.update_integration({"habilitado": True}, USER_ID) == {"id": 1, "habilitado": True}
    assert store.get_integration() is None

    update = fake.table_calls("integracion_terminal")[1]
    [(values,)] = update.args_of("update")
    assert values["habilitado"] is True
    assert values["updated_by"] == USER_ID
    assert "updated_at" in values
    assert update.args_of("eq") == [("id", 1)]
