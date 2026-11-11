import pytest

from app.api.v1.endpoints import clientes, productos
from app.services import catalogo_service, producto_service
from tests.fakes import FakeSupabase

PRODUCT_ID = "77777777-7777-4777-8777-777777777777"
VARIANT_ID = "11111111-1111-4111-8111-111111111111"
FULL_VARIANT_ROW = {
    "id": VARIANT_ID,
    "producto_id": PRODUCT_ID,
    "sku": "REM-001",
    "talle": "M",
    "color": "Azul",
    "precio_venta": 1500.0,
    "precio_costo": 600.0,
    "stock_actual": 7,
    "stock_minimo": 2,
    "tiendanube_variant_id": None,
    "updated_at": "2026-11-11T12:00:00+00:00",
}


def test_stock_adjustment_keeps_the_full_row_shape(auth_client, monkeypatch):
    monkeypatch.setattr(producto_service, "supabase", FakeSupabase(FULL_VARIANT_ROW))

    response = auth_client.patch(
        "/api/v1/productos/inventario/stock",
        json={"variante_id": VARIANT_ID, "cantidad": 1, "motivo": "Recuento"},
    )

    assert response.status_code == 200
    assert response.json() == FULL_VARIANT_ROW


@pytest.mark.parametrize("path", [f"/productos/{PRODUCT_ID}", f"/productos/variante/{VARIANT_ID}"])
def test_product_deletes_answer_ok(auth_client, monkeypatch, path):
    monkeypatch.setattr(productos.ProductService, "delete_product", lambda product_id: True)
    monkeypatch.setattr(productos.ProductService, "delete_variant", lambda variant_id: True)

    response = auth_client.delete(f"/api/v1/{path.lstrip('/')}")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_catalog_deletes_answer_a_message(auth_client, monkeypatch):
    monkeypatch.setattr(catalogo_service.CatalogoService, "delete_marca", lambda marca_id: True)
    monkeypatch.setattr(catalogo_service.CatalogoService, "delete_categoria", lambda categoria_id: True)

    marca = auth_client.delete("/api/v1/catalogos/marcas/1")
    categoria = auth_client.delete("/api/v1/catalogos/categorias/1")

    assert marca.json() == {"message": "Marca eliminada correctamente"}
    assert categoria.json() == {"message": "Categoría eliminada correctamente"}


@pytest.mark.parametrize(
    ("method", "path", "service", "method_name", "body", "message"),
    [
        ("GET", "/productos/sku/NOPE", productos.ProductService, "get_product_by_sku", None, "Producto no encontrado"),
        ("PATCH", f"/productos/{PRODUCT_ID}", productos.ProductService, "update_product", {"nombre": "x"}, "Producto no encontrado"),
        ("DELETE", f"/productos/{PRODUCT_ID}", productos.ProductService, "delete_product", None, "Producto no encontrado"),
        ("PATCH", f"/productos/variante/{VARIANT_ID}", productos.ProductService, "update_variant", {"talle": "L"}, "Variante no encontrada"),
        ("DELETE", f"/productos/variante/{VARIANT_ID}", productos.ProductService, "delete_variant", None, "Variante no encontrada"),
        ("PATCH", f"/clientes/{PRODUCT_ID}", clientes.ClienteService, "update_cliente", {"nombre": "x"}, "Cliente no encontrado"),
    ],
)
def test_not_found_messages_are_in_spanish(auth_client, monkeypatch, method, path, service, method_name, body, message):
    monkeypatch.setattr(service, method_name, lambda *args, **kwargs: None)

    response = auth_client.request(method, f"/api/v1{path}", json=body)

    assert response.status_code == 404
    assert response.json() == {"detail": message}
