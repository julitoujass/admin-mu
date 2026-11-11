# agents.md — Contexto del Backend `admin-mu`

> **⚠️ Este archivo debe actualizarse cada vez que se modifique la API.**
> Última actualización: 2026-11-11 — Fase 1 (fundaciones): dependencias, settings, CORS, health, manejo global de errores, tests, ruff y CI

---

## Descripción General

**`admin-mu`** es la API backend del sistema POS de **Mundo Uniforme**. Está construida con **FastAPI + Python** y usa **Supabase** como base de datos (PostgreSQL). No tiene ORM; todas las queries van directamente contra la Supabase Python client (`supabase-py`).

Corre en: `http://127.0.0.1:8000`
Docs interactivos: `http://127.0.0.1:8000/docs`

El frontend (`pos-mu` — Next.js) consume esta API a través de un proxy interno en `/api/python/*` para evitar CORS.

---

## Stack Tecnológico

| Capa | Tecnología |
|---|---|
| Framework | FastAPI |
| Lenguaje | Python 3.12+ |
| Base de datos | Supabase (PostgreSQL 17) |
| Cliente DB | `supabase-py` (Supabase Python Client) |
| Validación | Pydantic v2 |
| Config | `pydantic-settings` (.env) |
| Auth | Supabase Auth (JWT Bearer tokens) |
| Servidor | Uvicorn |
| Tests | pytest + FastAPI `TestClient` (httpx) |
| Lint | ruff |

Las dependencias están fijadas en `requirements.txt` (ejecución) y `requirements-dev.txt` (incluye las anteriores más pytest, httpx y ruff).

---

## Variables de Entorno (`.env`)

```env
SUPABASE_URL=https://pwzhrsdmjweoemtfkmrl.supabase.co
SUPABASE_KEY=<sb_secret_...>
ENVIRONMENT=development
CORS_ORIGINS=http://localhost:3000
LOG_LEVEL=INFO
```

| Variable | Requerida | Default | Descripción |
|---|---|---|---|
| `SUPABASE_URL` | Sí | — | URL del proyecto. No puede estar vacía. |
| `SUPABASE_KEY` | Sí | — | Clave secreta (equivalente a `service_role`, omite RLS). No puede estar vacía. |
| `ENVIRONMENT` | No | `development` | Nombre del entorno. |
| `CORS_ORIGINS` | No | `http://localhost:3000` | Orígenes permitidos, separados por coma. Se expone como lista en `settings.cors_origins_list`. |
| `LOG_LEVEL` | No | `INFO` | Nivel del logging estándar configurado en `main.py`. |

> `JWT_SECRET` fue eliminado: no se usaba, la validación del token la hace Supabase Auth (ver Autenticación).
> Las variables de entorno tienen prioridad sobre `.env`; los tests y CI usan valores ficticios y no requieren un `.env` real.

---

## Estructura del Proyecto

```
app/
├── main.py                        # Entry point: logging, CORS, routers, health y exception handlers
├── core/
│   ├── config.py                  # Settings (pydantic-settings, lee .env)
│   ├── supabase.py                # Singleton del cliente Supabase
│   └── exceptions.py              # Excepciones custom: StockError, CajaError
├── api/
│   ├── auth_deps.py               # get_current_user (valida token + rol) y RoleChecker
│   └── v1/
│       └── endpoints/
│           ├── productos.py       # Rutas de productos y variantes
│           ├── caja.py            # Rutas de sesiones y movimientos de caja
│           ├── ventas.py          # Rutas de ventas
│           ├── clientes.py        # Rutas de clientes
│           ├── reportes.py        # Rutas de reportes (solo admin)
│           ├── catalogos.py       # Rutas de marcas y categorías
│           └── usuarios.py        # Rutas de usuarios y roles
├── schemas/
│   ├── productos.py               # Pydantic models: ProductCreate/Update/Response, VariantCreate/Update/Response, StockUpdate
│   ├── caja.py                    # Pydantic models: CajaApertura, CajaMovimiento, CajaCierre, SesionCajaResponse, CajaMovimientoResponse
│   ├── ventas.py                  # Pydantic models: VentaCreate, VentaItem, VentaResponse
│   ├── clientes.py                # Pydantic models: ClienteCreate/Update/Response
│   ├── reportes.py                # Pydantic models: VentasTotalesReporte, ProductoTopReporte, CajaResumenReporte
│   ├── catalogos.py               # Pydantic models: MarcaCreate/Update/Response, CategoriaCreate/Update/Response
│   └── usuarios.py                # Pydantic models: RoleResponse, UsuarioResponse, UsuarioRoleUpdate
├── services/
│   ├── producto_service.py        # Lógica de negocio de productos y variantes
│   ├── caja_service.py            # Lógica de negocio de caja
│   ├── venta_service.py           # Lógica de negocio de ventas
│   ├── cliente_service.py         # Lógica de negocio de clientes
│   ├── reporte_service.py         # Lógica de reportes (agregaciones en memoria)
│   ├── catalogo_service.py        # CRUD de marcas y categorías
│   ├── usuario_service.py         # Lectura de perfiles/roles y cambio de rol
│   └── log_service.py             # Auditoría: inserta en tabla `logs` (BackgroundTask)
scripts/
├── seed_data.py                   # Carga de datos de prueba
└── get_token.py                   # Obtiene un JWT de Supabase para probar la API
tests/
├── conftest.py                    # Variables de entorno ficticias + fixtures `client` / `auth_client`
├── test_settings.py               # Settings: defaults, parseo de CORS, validaciones
├── test_health.py                 # /health y /health/ready
├── test_cors.py                   # Preflight CORS (origen permitido / desconocido)
├── test_error_handling.py         # Mapeo de APIError, 500 genérico, errores de catálogos
└── test_auth_deps.py              # get_current_user: 401 sin filtrar detalles
.github/workflows/ci.yml           # CI: ruff + pytest en cada push / PR
pyproject.toml                     # Configuración de ruff y pytest
requirements.txt                   # Dependencias de ejecución (versiones fijadas)
requirements-dev.txt               # requirements.txt + pytest, httpx, ruff
README.md                          # Instalación, ejecución, tests y lint
```

---

## Autenticación

- **Mecanismo:** JWT Bearer (tokens de Supabase Auth)
- **Dependencia:** `get_current_user` en `app/api/auth_deps.py`
- **Funcionamiento:** Extrae el token del header `Authorization: Bearer <token>` y lo valida con `supabase.auth.get_user(token)` (no hay verificación local del JWT). Si el token es inválido o la validación falla, retorna 401 con el mensaje fijo `"No se pudieron validar las credenciales"`; el error real solo se loguea.
- **Rol:** Después de validar el token, lee `perfiles.select("roles(nombre)")` para el usuario. Si no tiene perfil/rol o la consulta falla, el rol es `"empleado"`.
- **`current_user`:** Es un `AppUser` propio con `id`, `email` y `rol` (no el objeto `User` de Supabase).
- **Cache:** El `AppUser` se cachea en memoria por token durante 5 minutos (`_TOKEN_CACHE`). Un cambio de rol puede tardar hasta 5 min en reflejarse, y el cache no se comparte entre procesos/workers.
- **`RoleChecker(allowed_roles)`:** Dependency que responde 403 si `current_user.rol` no está en la lista. Hoy se usa solo con `["admin"]` en:
  - `/reportes/*`
  - `/usuarios/*` (excepto `/usuarios/me`)
  - `DELETE /productos/{id}` y `DELETE /productos/variante/{id}`
- El resto de los endpoints solo exige `Depends(get_current_user)` (incluidas las escrituras de catálogos).
- **⚠️ Nota caja:** El endpoint `POST /api/v1/caja/apertura` usa `datos.usuario_id` del body en lugar de `current_user.id` para determinar el usuario de la sesión.

## Auditoría (`logs`)

`LogService.registrar_log()` inserta un registro en la tabla `logs` (evento, entidad, entidad_id, payload, usuario_id, estado). Se ejecuta como `BackgroundTask` desde los endpoints de escritura de productos, caja, ventas, clientes y catálogos. Si el insert falla, solo se loguea el error y no afecta la respuesta.

---

## Health y manejo de errores

Definidos en `main.py`.

### Health (sin autenticación)

| Método | Path | Respuesta |
|---|---|---|
| GET | `/health` | 200 `{"status": "ok"}`. No toca la base de datos (liveness). |
| GET | `/health/ready` | Ejecuta una consulta mínima (`roles`, `select id limit 1`). 200 `{"status": "ready"}` o 503 `{"status": "unavailable"}` (readiness). El error se loguea, no se devuelve. |

### Exception handlers globales

| Excepción | HTTP Status | `detail` |
|---|---|---|
| `StockError` | 400 | Mensaje de negocio (stock insuficiente o variante no encontrada) |
| `CajaError` | 400 | Mensaje de negocio (no hay caja abierta, o ya existe una abierta) |
| `postgrest.APIError` código `23505` | 409 | `Conflicto: el registro ya existe` |
| `postgrest.APIError` código `23503` | 409 | `Conflicto: el registro está referenciado por otros datos` |
| `postgrest.APIError` código `PGRST116` | 404 | `Recurso no encontrado` |
| `postgrest.APIError` código `22P02` | 400 | `Dato inválido` |
| `postgrest.APIError` (otro código) | 500 | `Error interno del servidor` |
| `Exception` no manejada | 500 | `Error interno del servidor` |

**Reglas:**
- El error real (código, mensaje y detalles de PostgREST, o el traceback) se registra con `logging` en el servidor y **nunca** se incluye en la respuesta.
- Los endpoints no deben devolver `str(e)` de excepciones arbitrarias. Solo se usan como `detail` los mensajes de negocio propios (`ValueError` de los servicios, `StockError`, `CajaError`); cualquier otra excepción se deja propagar a los handlers globales.
- `HTTPException` y los errores de validación (422) conservan el comportamiento estándar de FastAPI.
- Las respuestas 500 del handler genérico las emite la capa externa de Starlette, por fuera de `CORSMiddleware`, por lo que no llevan headers CORS.

### CORS y logging

- `CORSMiddleware` con orígenes de `CORS_ORIGINS`, `allow_credentials=False`, métodos `GET, POST, PUT, PATCH, DELETE, OPTIONS` y headers `Authorization, Content-Type, Idempotency-Key`. Un preflight desde un origen no listado recibe 400.
- Logging estándar (`logging.basicConfig`) con el nivel de `LOG_LEVEL`.

---|---|---|
| `StockError` | 400 | Stock insuficiente o variante no encontrada |
| `CajaError` | 400 | No hay caja abierta, o ya existe una abierta |

---

## Base de Datos (Supabase — Proyecto: `gestion`)

- **Project ID:** `pwzhrsdmjweoemtfkmrl`
- **URL:** `https://pwzhrsdmjweoemtfkmrl.supabase.co`
- **Región:** sa-east-1 (São Paulo)
- **Motor:** PostgreSQL 17

### ⚠️ RLS
Todas las tablas tienen **RLS habilitado sin políticas**: solo la clave secreta del backend (que omite RLS) puede leer o escribir. La autorización recae en el JWT validado por la API.

### Tablas

#### `productos`
| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid (PK) | `gen_random_uuid()` |
| `nombre` | text | requerido |
| `descripcion` | text | nullable |
| `imagen_principal` | text | nullable |
| `tiendanube_id` | text | nullable, integración Tiendanube |
| `marca_id` | integer | FK → `marcas.id` |
| `created_at` | timestamptz | `now()` |
| `updated_at` | timestamptz | `now()` |

#### `producto_variantes`
| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid (PK) | `gen_random_uuid()` |
| `producto_id` | uuid | FK → `productos.id` |
| `sku` | text | unique |
| `talle` | text | |
| `color` | text | nullable |
| `precio_venta` | numeric | default 0.00 |
| `precio_costo` | numeric | nullable, default 0.00 |
| `stock_actual` | integer | nullable, default 0 |
| `stock_minimo` | integer | nullable, default 5 |
| `tiendanube_variant_id` | text | nullable, integración Tiendanube |
| `updated_at` | timestamptz | `now()` |

#### `categorias`
| Columna | Tipo | Notas |
|---|---|---|
| `id` | integer (PK) | serial |
| `nombre` | text | |
| `descripcion` | text | nullable |
| `tiendanube_id` | text | nullable |
| `created_at` | timestamptz | |

#### `producto_categorias` (tabla de relación N:M)
| Columna | Tipo | Notas |
|---|---|---|
| `producto_id` | uuid | FK → `productos.id` |
| `categoria_id` | integer | FK → `categorias.id` |

#### `marcas`
| Columna | Tipo | Notas |
|---|---|---|
| `id` | integer (PK) | serial |
| `nombre` | text | |
| `contacto_nombre` | text | nullable |
| `telefono` | text | nullable |
| `email` | text | nullable |
| `created_at` | timestamptz | |

#### `clientes`
| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid (PK) | `gen_random_uuid()` |
| `nombre` | text | |
| `email` | text | nullable, unique |
| `telefono` | text | nullable |
| `dni_cuit` | text | nullable, unique |
| `tipo_iva` | text | nullable, default `'Consumidor Final'` |
| `direccion` | text | nullable |
| `ciudad` | text | nullable |
| `created_at` | timestamptz | |

#### `ventas`
| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid (PK) | `gen_random_uuid()` |
| `cliente_id` | uuid | nullable, FK → `clientes.id` |
| `usuario_id` | uuid | nullable, FK → `perfiles.id` |
| `sesion_caja` | uuid | nullable, FK → `sesiones_caja.id` |
| `fecha` | timestamptz | `now()` |
| `total` | numeric | default 0.00 |
| `total_costo` | numeric | default 0.00 |
| `metodo_pago` | text | |
| `origen` | text | default `'Local'` |
| `estado_pago` | text | nullable, default `'Completado'` |
| `nube_orden_id` | text | nullable, integración Tiendanube |
| `notas` | text | nullable |
| `numero_cae` | bigint | nullable, para facturación AFIP |
| `created_at` | timestamptz | |

#### `venta_detalle`
| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid (PK) | `gen_random_uuid()` |
| `venta_id` | uuid | nullable, FK → `ventas.id` |
| `variante_id` | uuid | nullable, FK → `producto_variantes.id` |
| `cantidad` | integer | default 1 |
| `precio_unitario` | numeric | |
| `costo_unitario` | numeric | |
| `subtotal` | numeric | **columna generada**: `cantidad * precio_unitario` |

#### `sesiones_caja`
| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid (PK) | `gen_random_uuid()` |
| `usuario_id` | uuid | FK → `auth.users.id` |
| `fecha_apertura` | timestamptz | `now()` |
| `fecha_cierre` | timestamptz | nullable |
| `monto_apertura` | numeric | default 0 |
| `monto_esperado_efectivo` | numeric | nullable, default 0 — calculado al cierre |
| `monto_real_efectivo` | numeric | nullable — ingresado al cierre |
| `estado` | text | check: `'abierta'` \| `'cerrada'` |
| `observaciones` | text | nullable |

#### `movimientos_caja`
| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid (PK) | `gen_random_uuid()` |
| `sesion_id` | uuid | FK → `sesiones_caja.id` |
| `tipo` | text | check: `'ingreso'` \| `'egreso'` |
| `monto` | numeric | |
| `motivo` | text | |
| `creado_en` | timestamptz | `now()` — ⚠️ difiere del resto (no es `created_at`) |

#### `perfiles`
| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid (PK) | FK → `auth.users.id` |
| `nombre` | text | |
| `apellido` | text | nullable |
| `rol_id` | integer | nullable, FK → `roles.id` |
| `activo` | boolean | default true |
| `created_at` | timestamptz | |

#### `roles`
| Columna | Tipo | Notas |
|---|---|---|
| `id` | integer (PK) | serial |
| `nombre` | text | unique |
| `descripcion` | text | nullable |

> Los roles se leen vía `perfiles.rol_id → roles.nombre`. Las tablas `permisos` y `rol_permisos` existen pero **no se usan** en el código.

#### `permisos`
| Columna | Tipo | Notas |
|---|---|---|
| `id` | integer (PK) | serial |
| `nombre` | text | unique |
| `descripcion` | text | nullable |

#### `rol_permisos` (tabla de relación N:M)
| Columna | Tipo | Notas |
|---|---|---|
| `rol_id` | integer | FK → `roles.id` |
| `permiso_id` | integer | FK → `permisos.id` |

#### `logs`
| Columna | Tipo | Notas |
|---|---|---|
| `id` | integer (PK) | serial |
| `evento` | text | |
| `entidad` | text | nullable |
| `entidad_id` | text | nullable |
| `descripcion` | text | nullable |
| `payload_enviado` | jsonb | nullable |
| `respuesta_recibida` | jsonb | nullable |
| `estado` | text | nullable, default `'SUCCESS'` |
| `usuario_id` | uuid | nullable, FK → `perfiles.id` |
| `created_at` | timestamptz | |

### RPCs (Funciones de Supabase)

| Función | Parámetros | Descripción |
|---|---|---|
| `obtener_productos` | `p_categoria_id?` (int) | Retorna productos filtrados por categoría |
| `finalizar_cierre_caja` | `p_sesion_id`, `p_monto_real_efectivo`, `p_observaciones` | Cierra la sesión de caja y guarda el monto real |

---

## Endpoints de la API

### Base URL: `http://127.0.0.1:8000/api/v1`

Todos los endpoints (salvo `GET /`, `GET /health` y `GET /health/ready`) requieren `Authorization: Bearer <supabase_jwt>`. En las tablas, **Auth** indica: ✅ = sesión válida, 🔒 = solo admin (`RoleChecker(["admin"])`).

---

### 🛍️ Productos — `/api/v1/productos`

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/` | ✅ | Lista todos los productos con sus variantes. Query param opcional: `?categoria_id=<int>` |
| GET | `/sku/{sku}` | ✅ | Busca un producto por SKU de variante. Retorna 404 si no existe |
| POST | `/` | ✅ | Crea un producto nuevo |
| PATCH | `/{id}` | ✅ | Actualiza nombre/descripción/marca de un producto |
| POST | `/variante` | ✅ | Crea una variante vinculada a un producto |
| PATCH | `/variante/{id}` | ✅ | Actualiza una variante (NO incluye stock_actual) |
| PATCH | `/inventario/stock` | ✅ | Ajusta el stock de una variante (suma/resta `cantidad`) |
| DELETE | `/variante/{id}` | 🔒 | Elimina una variante. 404 si no existe, 409 si tiene ventas en `venta_detalle` |
| DELETE | `/{id}` | 🔒 | Elimina un producto con sus variantes y vínculos en `producto_categorias`. 404 si no existe, 409 si alguna variante tiene ventas |

**Schemas de entrada:**

```python
# ProductCreate
{ nombre: str, descripcion?: str, marca_id?: int }

# ProductUpdate
{ nombre?: str, descripcion?: str, marca_id?: int }

# VariantCreate
{ producto_id: UUID, sku?: str, talle?: str, color?: str, precio_venta: float,
  stock_actual?: int=0, stock_minimo?: int=0, precio_costo?: float=0 }

# VariantUpdate
{ sku?: str, talle?: str, color?: str, precio_venta?: float, precio_costo?: float, stock_minimo?: int }
# ⚠️ stock_actual NO está en VariantUpdate (no se puede editar por PATCH de variante)

# StockUpdate
{ variante_id: UUID, cantidad: int, motivo: str }
# cantidad puede ser negativo para reducir stock
```

**Notas de implementación:**
- `get_products()` usa RPC `obtener_productos` luego hace `.select("*, variantes:producto_variantes(*)")` para incluir variantes.
- `get_product_by_sku()` primero busca la variante por SKU → obtiene `producto_id` → carga el producto completo con variantes.
- `update_stock()` verifica que el nuevo stock no sea negativo antes de actualizar. Lanza `StockError` si hay problema. ⚠️ Usa read-modify-write (select + update), no es atómico.
- `ProductCreate`/`ProductResponse` no incluyen categorías: la tabla `producto_categorias` solo se lee (filtro `?categoria_id=`) y se limpia al borrar un producto; no hay endpoint para asignar categorías.

---

### 💰 Caja — `/api/v1/caja`

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/estado` | ✅ | Retorna la sesión de caja abierta (global). Retorna `null` si no hay ninguna |
| POST | `/apertura` | ✅ | Abre una nueva sesión de caja. Usa `usuario_id` del body |
| POST | `/movimiento` | ✅ | Registra un ingreso o egreso manual en la sesión activa. Sin `response_model`: devuelve la fila cruda (`motivo`, `creado_en`) |
| GET | `/movimientos` | ✅ | Lista los movimientos de la sesión activa |
| POST | `/cierre` | ✅ | Cierra la sesión activa vía RPC `finalizar_cierre_caja` |
| GET | `/sesiones` | ✅ | Lista todas las sesiones de caja (todas, no solo del usuario) ordenadas por fecha desc |
| GET | `/sesiones/{sesion_id}/movimientos` | ✅ | Lista movimientos de una sesión específica, ordenados por `creado_en` desc |

**Schemas de entrada:**

```python
# CajaApertura
{ monto_apertura: float, usuario_id: UUID }

# CajaMovimiento
{ tipo: 'ingreso'|'egreso', monto: float, motivo: str }

# CajaCierre
{ monto_real_efectivo: float, observaciones?: str }
```

**⚠️ Notas importantes:**
- `monto_esperado_efectivo` en `sesiones_caja` lo calcula la RPC `finalizar_cierre_caja`, no la API Python.
- `movimientos_caja.creado_en` (no `created_at`) → el schema `CajaMovimientoResponse` mapea con `Field(validation_alias='creado_en')`.
- **La caja es global:** `CajaService.get_sesion_activa()` ignora el `usuario_id` y devuelve la primera sesión con `estado = 'abierta'`. Solo puede haber una sesión abierta en todo el sistema; intentar abrir otra lanza `CajaError`. Movimientos, cierre y ventas usan esa misma sesión sin importar qué usuario la abrió.

---

### 🏷️ Ventas — `/api/v1/ventas`

| Método | Path | Auth | Descripción |
|---|---|---|---|
| POST | `/` | ✅ | Crea una venta completa (verifica stock, inserta venta + detalle, descuenta stock) |
| GET | `/hoy` | ✅ | Retorna todas las ventas creadas hoy (filtra por `created_at >= hoy`) |

**Schema de entrada:**

```python
# VentaCreate
{
  items: [{ variante_id: UUID, cantidad: int, precio_unitario: float }],
  metodo_pago: str,
  cliente_id?: UUID
}
```

**Flujo interno de `crear_venta()`:**
1. Verifica que haya una sesión de caja abierta (global) → `CajaError` si no.
2. Para cada item: verifica stock disponible y lee `precio_costo` → `StockError` si insuficiente. Calcula subtotal y `costo_unitario`.
3. Calcula `total_costo` como suma de `costo_unitario × cantidad`.
4. Inserta en `ventas` (con `usuario_id`, `sesion_caja`, `total`, `total_costo`, `metodo_pago`, `cliente_id`).
5. Inserta cada item en `venta_detalle` con su `costo_unitario`.
6. Descuenta stock de `producto_variantes` por cada item.

**⚠️ Notas:**
- El descuento de stock se hace en dos queries por item (select + update), sin transacción: race condition con ventas concurrentes, y una falla a mitad de camino deja la venta parcialmente aplicada.
- `GET /hoy` calcula "hoy" con la fecha local del servidor, no con una zona horaria explícita.
- `venta_detalle.subtotal` es columna generada en DB (`cantidad * precio_unitario`), no se envía desde la API.
- El campo `fecha` en `ventas` es redundante con `created_at`; la query de "hoy" filtra por `created_at`.

---

### 👤 Clientes — `/api/v1/clientes`

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/` | ✅ | Lista clientes. Query param opcional: `?query=<str>` (busca por `nombre` o `dni_cuit` con ilike) |
| POST | `/` | ✅ | Crea un cliente nuevo |
| PATCH | `/{id}` | ✅ | Actualiza datos de un cliente. Retorna 404 si no existe |

**Schemas de entrada:**

```python
# ClienteCreate / ClienteUpdate
{
  nombre: str,           # requerido en Create
  dni_cuit?: str,
  email?: str,
  telefono?: str,
  direccion?: str,
  ciudad?: str,
  tipo_iva?: str         # default en DB: 'Consumidor Final'
}
```

---

### 📊 Reportes — `/api/v1/reportes`

Todos los endpoints de reportes aceptan `?fecha_inicio=YYYY-MM-DD&fecha_fin=YYYY-MM-DD` (ambos opcionales).

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/ventas` | 🔒 | Total de ingresos, cantidad de operaciones y ventas agrupadas por día |
| GET | `/productos-top` | 🔒 | Top productos/variantes por ingresos generados en el período |
| GET | `/cajas` | 🔒 | Resumen de sesiones de caja por día (apertura, ingresos, egresos, diferencia real vs esperado) |

**Schemas de respuesta:**

```python
# VentasTotalesReporte
{ total_ingresos: float, cantidad_operaciones: int, ventas_por_dia: [{ fecha, total, cantidad_ventas }] }

# ProductoTopReporte
{ variante_id: str, nombre_producto: str, talle?: str, color?: str, cantidad_vendida: int, ingresos_generados: float }

# CajaResumenReporte
{ resumen_diario: [{ fecha, sesiones_abiertas, monto_inicial_total, ingresos, egresos, monto_real_efectivo_total, diferencia_esperado_vs_real }], diferencia_total_periodo: float }
```

**⚠️ Notas de implementación:**
- `obtener_top_productos()` hace múltiples queries en cadena y agrega en memoria. Para producción con volumen alto debería convertirse en una RPC de Supabase.
- `obtener_top_productos()` consulta `venta_detalle` y `producto_variantes` (bug de nombres de tabla ya resuelto).
- Los rangos de fecha se comparan como timestamps sin zona horaria.

---

### 📚 Catálogos — `/api/v1/catalogos`

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/marcas` | ✅ | Lista marcas ordenadas por nombre |
| POST | `/marcas` | ✅ | Crea una marca. Los errores de base se mapean globalmente (p. ej. 409 si viola una restricción única) |
| PATCH | `/marcas/{marca_id}` | ✅ | Actualiza una marca. 404 si no existe |
| DELETE | `/marcas/{marca_id}` | ✅ | Elimina una marca. 404 si no existe, 400 si hay productos con esa `marca_id` |
| GET | `/categorias` | ✅ | Lista categorías ordenadas por nombre |
| POST | `/categorias` | ✅ | Crea una categoría. Los errores de base se mapean globalmente (p. ej. 409 si viola una restricción única) |
| PATCH | `/categorias/{categoria_id}` | ✅ | Actualiza una categoría. 404 si no existe |
| DELETE | `/categorias/{categoria_id}` | ✅ | Elimina una categoría. 404 si no existe, 400 si tiene productos en `producto_categorias` |

**Schemas de entrada:**

```python
# MarcaCreate / MarcaUpdate (en Update todos opcionales)
{ nombre: str, contacto_nombre?: str, telefono?: str, email?: str }

# CategoriaCreate / CategoriaUpdate (en Update todos opcionales)
{ nombre: str, descripcion?: str, tiendanube_id?: str }
```

> Las escrituras de catálogos no están restringidas a admin.

---

### 👥 Usuarios — `/api/v1/usuarios`

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/me` | ✅ | Devuelve `{ id, email, rol }` del usuario autenticado (sin `response_model`) |
| GET | `/` | 🔒 | Lista perfiles con su rol (`perfiles` + `roles(id, nombre)`), ordenados por `created_at` desc |
| GET | `/roles` | 🔒 | Lista roles (`id`, `nombre`) |
| PATCH | `/{id}/rol` | 🔒 | Cambia el `rol_id` de un perfil. 404 si no existe |

**Schemas:**

```python
# UsuarioRoleUpdate
{ rol_id: int }

# UsuarioResponse
{ id: UUID, nombre: str, apellido?: str, activo: bool, roles?: { id: int, nombre: str }, created_at: datetime }
```

> No hay endpoints para crear/desactivar usuarios: el alta se hace en Supabase Auth y el perfil en `perfiles`.

---

## Discrepancias / Bugs Conocidos

| # | Módulo | Estado | Descripción |
|---|---|---|---|
| 1 | `reporte_service.py` | ✅ **Resuelto** | `obtener_top_productos()` consultaba `venta_items`/`variantes`. Corregido a `venta_detalle`/`producto_variantes`. |
| 2 | `venta_service.py` | ✅ **Resuelto** | `total_costo` ahora se calcula como suma de `costo_unitario × cantidad` y se persiste en `ventas`. |
| 3 | `venta_service.py`, `producto_service.py` | ⚠️ Pendiente | El descuento de stock no es atómico (select + update separados, sin transacción). Aplica a `crear_venta()` y a `update_stock()`. |
| 4 | `schemas/caja.py` | ✅ **Resuelto** | `CajaMovimientoResponse` migrado a Pydantic v2 `model_config`. Serialización de `creado_en→created_at` y `motivo→descripcion` verificada. |
| 5 | `schemas/productos.py` | ✅ **Aclarado** | El campo `color` SÍ existe en `producto_variantes`. El comentario era incorrecto. |
| 6 | `caja_service.py` | ⚠️ Por diseño / revisar | La caja es global: `get_sesion_activa()` ignora `usuario_id`. |
| 7 | `endpoints/caja.py` | ⚠️ Pendiente | `POST /caja/apertura` toma `usuario_id` del body en vez de `current_user.id`: un cliente puede abrir la caja a nombre de otro usuario. |
| 8 | `endpoints/caja.py` | ℹ️ Menor | `POST /caja/movimiento` no tiene `response_model` y devuelve `motivo`/`creado_en`, a diferencia de los listados (`descripcion`/`created_at`). |
| 9 | `auth_deps.py` | ℹ️ Menor | El cache de tokens (5 min) demora la aplicación de cambios de rol y no se comparte entre workers. |
| 10 | `productos` | ℹ️ Falta feature | No hay forma de asignar categorías a un producto vía API. |

---

## Comandos de Desarrollo

```bash
# Desde c:\Proyectos\Personal\admin-mu
.\.venv\Scripts\activate
uvicorn app.main:app --reload
# → http://127.0.0.1:8000
# → Docs: http://127.0.0.1:8000/docs

# Instalar dependencias (ejecución + desarrollo)
pip install -r requirements-dev.txt

# Tests (no usan la red ni requieren un .env real)
pytest -q

# Lint
ruff check .
ruff check --fix .   # aplica solo los arreglos seguros
```

CI (`.github/workflows/ci.yml`) ejecuta `ruff check .` y `pytest -q` en cada push y pull request.

---

## Convenciones del Código

1. **Sin ORM:** Todas las queries usan `supabase-py` directamente contra las tablas/RPCs.
2. **Servicios estáticos:** Los servicios son clases con `@staticmethod` (no hay instancias).
3. **`model_dump(exclude_none=True)`** en Creates para no enviar campos nulos a Supabase.
4. **`model_dump(exclude_unset=True)`** en Updates para solo enviar los campos que el cliente mandó.
5. **`mode='json'`** en la creación de variantes para serializar UUID4 como string.
6. **Errores de negocio** se lanzan como `StockError` o `CajaError` y son capturados globalmente en `main.py`.
7. **Sin fugas de detalles internos:** no devolver `str(e)` de excepciones no controladas; ver "Health y manejo de errores".
8. **TDD:** todo comportamiento nuevo lleva su test en `tests/` (los servicios o el cliente `supabase` se reemplazan con mocks; `get_current_user` con `app.dependency_overrides`).
