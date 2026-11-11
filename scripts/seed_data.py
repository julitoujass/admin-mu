import os
import sys

sys.path.append(os.getcwd())


from app.core.supabase import supabase


def seed():
    print("Seeding data...")

    # 1. Categorias
    print("Inserting Categorias...")
    cat_uniformes = {"nombre": "Uniformes", "descripcion": "Ropa de trabajo"}
    cat_accesorios = {"nombre": "Accesorios", "descripcion": "Complementos"}
    
    res_cat = supabase.table("categorias").insert([cat_uniformes, cat_accesorios]).execute()
    cats = res_cat.data
    print(f"Inserted {len(cats)} categorias.")

    # 2. Marcas (Assuming table exists and has 'nombre')
    print("Inserting Marcas...")
    marca_ombu = {"nombre": "Ombu"}
    marca_pampero = {"nombre": "Pampero"}
    
    # Check if marcas table exists/works by trying to insert
    try:
        res_marca = supabase.table("marcas").insert([marca_ombu, marca_pampero]).execute()
        marcas = res_marca.data
        print(f"Inserted {len(marcas)} marcas.")
    except Exception as e:
        print(f"Skipping Marcas (might not exist or error): {e}")
        marcas = []

    # 3. Productos
    print("Inserting Productos...")
    prod_pantalon = {
        "nombre": "Pantalon Cargo",
        "descripcion": "Pantalon de trabajo reforzado",
        "marca_id": marcas[0]["id"] if marcas else None
    }
    prod_camisa = {
        "nombre": "Camisa Grafa",
        "descripcion": "Camisa de trabajo manga larga",
        "marca_id": marcas[1]["id"] if len(marcas) > 1 else None
    }

    res_prod = supabase.table("productos").insert([prod_pantalon, prod_camisa]).execute()
    prods = res_prod.data
    print(f"Inserted {len(prods)} productos.")

    # Link Products to Categories (producto_categorias)
    # Assuming table exists: producto_id, categoria_id
    if cats and prods:
        print("Linking Products to Categories...")
        links = [
            {"producto_id": prods[0]["id"], "categoria_id": cats[0]["id"]},
            {"producto_id": prods[1]["id"], "categoria_id": cats[0]["id"]}
        ]
        try:
            supabase.table("producto_categorias").insert(links).execute()
        except Exception as e:
             print(f"Skipping Category Links: {e}")

    # 4. Variantes
    print("Inserting Variantes...")
    variantes = []
    
    # Pantalon variants
    if prods:
        p_id = prods[0]["id"]
        variantes.append({
            "producto_id": p_id,
            "sku": "PAN-001-40",
            "talle": "40",
            "precio_venta": 15000,
            "stock_actual": 10,
            "stock_minimo": 2
        })
        variantes.append({
            "producto_id": p_id,
            "sku": "PAN-001-42",
            "talle": "42",
            "precio_venta": 15000,
            "stock_actual": 5,
            "stock_minimo": 2
        })

    # Camisa variants
    if len(prods) > 1:
        c_id = prods[1]["id"]
        variantes.append({
            "producto_id": c_id,
            "sku": "CAM-002-L",
            "talle": "L",
            "precio_venta": 12000,
            "stock_actual": 20,
            "stock_minimo": 5
        })

    if variantes:
        res_var = supabase.table("producto_variantes").insert(variantes).execute()
        print(f"Inserted {len(res_var.data)} variantes.")

    # 5. Clientes
    print("Inserting Clientes...")
    cliente_juan = {
        "nombre": "Juan Perez",
        "dni_cuit": "20123456789",
        "email": "juan@example.com",
        "telefono": "1122334455",
        "direccion": "Calle Falsa 123",
        "tipo_iva": "Consumidor Final"
    }
    cliente_empresa = {
        "nombre": "Empresa SA",
        "dni_cuit": "30112233445",
        "email": "contacto@empresa.com",
        "telefono": "1199887766",
        "direccion": "Av. Siempre Viva 742",
        "tipo_iva": "Responsable Inscripto"
    }

    res_cli = supabase.table("clientes").insert([cliente_juan, cliente_empresa]).execute()
    print(f"Inserted {len(res_cli.data)} clientes.")

    print("Seeding complete!")

if __name__ == "__main__":
    seed()
