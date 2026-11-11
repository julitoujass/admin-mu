import pytest

from app.api.auth_deps import AppUser, get_current_user
from app.main import app
from app.services import reporte_service
from tests.fakes import FakeSupabase

SALES_REPORT = {
    "total_ingresos": 4500.5,
    "cantidad_operaciones": 3,
    "ventas_por_dia": [
        {"fecha": "2026-11-10", "total": 1500.5, "cantidad_ventas": 1},
        {"fecha": "2026-11-11", "total": 3000, "cantidad_ventas": 2},
    ],
}
TOP_ROW = {
    "variante_id": "11111111-1111-4111-8111-111111111111",
    "nombre_producto": "Remera",
    "talle": "M",
    "color": None,
    "cantidad_vendida": 5,
    "ingresos_generados": 7500,
}
CASH_DAY = {
    "fecha": "2026-11-11",
    "sesiones_abiertas": 1,
    "monto_inicial_total": 1000,
    "ventas_efectivo": 3000,
    "ingresos": 500,
    "egresos": 250,
    "monto_real_efectivo_total": 4200,
    "diferencia_esperado_vs_real": -50,
}
CASH_REPORT = {"resumen_diario": [CASH_DAY], "diferencia_total_periodo": -50}


def use_db(monkeypatch, *responses):
    fake = FakeSupabase(*responses)
    monkeypatch.setattr(reporte_service, "supabase", fake)
    return fake


def test_sales_report_comes_from_rpc(auth_client, monkeypatch):
    db = use_db(monkeypatch, SALES_REPORT)

    response = auth_client.get("/api/v1/reportes/ventas?fecha_inicio=2026-11-01&fecha_fin=2026-11-11")

    assert response.status_code == 200
    assert len(db.queries) == 1
    assert (db.queries[0].kind, db.queries[0].name) == ("rpc", "reporte_ventas")
    assert db.queries[0].params == {"p_desde": "2026-11-01", "p_hasta": "2026-11-11"}
    assert response.json() == {
        "total_ingresos": 4500.5,
        "cantidad_operaciones": 3,
        "ventas_por_dia": [
            {"fecha": "2026-11-10", "total": 1500.5, "cantidad_ventas": 1},
            {"fecha": "2026-11-11", "total": 3000.0, "cantidad_ventas": 2},
        ],
    }


def test_sales_report_without_dates_is_unbounded(auth_client, monkeypatch):
    db = use_db(monkeypatch, {"total_ingresos": None, "cantidad_operaciones": 0, "ventas_por_dia": None})

    response = auth_client.get("/api/v1/reportes/ventas")

    assert db.queries[0].params == {"p_desde": None, "p_hasta": None}
    assert response.json() == {"total_ingresos": 0.0, "cantidad_operaciones": 0, "ventas_por_dia": []}


def test_top_products_report_comes_from_rpc_with_default_limit(auth_client, monkeypatch):
    db = use_db(monkeypatch, [TOP_ROW])

    response = auth_client.get("/api/v1/reportes/productos-top?fecha_inicio=2026-11-01")

    assert response.status_code == 200
    assert (db.queries[0].kind, db.queries[0].name) == ("rpc", "reporte_productos_top")
    assert db.queries[0].params == {"p_desde": "2026-11-01", "p_hasta": None, "p_limite": 50}
    assert response.json() == [{**TOP_ROW, "ingresos_generados": 7500.0}]


def test_top_products_limit_is_forwarded(auth_client, monkeypatch):
    db = use_db(monkeypatch, [])

    response = auth_client.get("/api/v1/reportes/productos-top?limite=200")

    assert response.json() == []
    assert db.queries[0].params["p_limite"] == 200


@pytest.mark.parametrize("limite", [0, 201, "abc"])
def test_top_products_limit_bounds(auth_client, monkeypatch, limite):
    db = use_db(monkeypatch)

    response = auth_client.get(f"/api/v1/reportes/productos-top?limite={limite}")

    assert response.status_code == 422
    assert db.queries == []


def test_cash_report_comes_from_rpc_and_includes_cash_sales(auth_client, monkeypatch):
    db = use_db(monkeypatch, CASH_REPORT)

    response = auth_client.get("/api/v1/reportes/cajas?fecha_fin=2026-11-11")

    assert response.status_code == 200
    assert (db.queries[0].kind, db.queries[0].name) == ("rpc", "reporte_cajas")
    assert db.queries[0].params == {"p_desde": None, "p_hasta": "2026-11-11"}
    body = response.json()
    assert body["diferencia_total_periodo"] == -50.0
    assert body["resumen_diario"] == [
        {
            "fecha": "2026-11-11",
            "sesiones_abiertas": 1,
            "monto_inicial_total": 1000.0,
            "ventas_efectivo": 3000.0,
            "ingresos": 500.0,
            "egresos": 250.0,
            "monto_real_efectivo_total": 4200.0,
            "diferencia_esperado_vs_real": -50.0,
        }
    ]


def test_cash_report_with_no_sessions(auth_client, monkeypatch):
    use_db(monkeypatch, {"resumen_diario": None, "diferencia_total_periodo": None})

    response = auth_client.get("/api/v1/reportes/cajas")

    assert response.json() == {"resumen_diario": [], "diferencia_total_periodo": 0.0}


@pytest.mark.parametrize("path", ["ventas", "productos-top", "cajas"])
def test_reports_are_admin_only(client, monkeypatch, path):
    db = use_db(monkeypatch)
    app.dependency_overrides[get_current_user] = lambda: AppUser(
        id="00000000-0000-0000-0000-000000000002", email="empleado@example.com", rol="empleado"
    )

    response = client.get(f"/api/v1/reportes/{path}")

    assert response.status_code == 403
    assert db.queries == []
