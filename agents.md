# agents.md — Contexto del Backend `admin-mu`

> **⚠️ Este archivo debe actualizarse cada vez que se modifique la API.**
> Última actualización: 2026-11-12 — Fase 5, lote 2: devoluciones parciales, configuración del negocio, stock bajo, alta de usuarios, categorías de productos, visor de auditoría y reportes netos de devoluciones

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
| Validación | Pydantic v2 (+ `email-validator` para `EmailStr`) |
| Zona horaria | `zoneinfo` + `tzdata` (America/Argentina/Buenos_Aires) |
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
PAYMENT_TERMINAL=fake
```

| Variable | Requerida | Default | Descripción |
|---|---|---|---|
| `SUPABASE_URL` | Sí | — | URL del proyecto. No puede estar vacía. |
| `SUPABASE_KEY` | Sí | — | Clave secreta (equivalente a `service_role`, omite RLS). No puede estar vacía. |
| `ENVIRONMENT` | No | `development` | Nombre del entorno. |
| `CORS_ORIGINS` | No | `http://localhost:3000` | Orígenes permitidos, separados por coma. Se expone como lista en `settings.cors_origins_list`. |
| `LOG_LEVEL` | No | `INFO` | Nivel del logging estándar configurado en `main.py`. |
| `PAYMENT_TERMINAL` | No | `fake` | Adaptador del terminal de pago: `fake` (simulado) o `clover` (Clover Cloud Pay Display). Con `clover` son obligatorias `CLOVER_APP_ID`, `CLOVER_APP_SECRET` y `CLOVER_TOKEN_KEY`. |
| `CLOVER_ENV` | No | `sandbox` | `sandbox` o `production` (región LATAM). Define los hosts de Clover. |
| `CLOVER_APP_ID` | Con `clover` | — | App ID de la app en el portal de desarrolladores de Clover. |
| `CLOVER_APP_SECRET` | Con `clover` | — | App Secret. Secreto: nunca se versiona ni se loguea. |
| `CLOVER_TOKEN_KEY` | Con `clover` | — | Clave Fernet que cifra los tokens OAuth guardados en la base (y firma el `state` de OAuth). Secreto. Se genera con `.venv\Scripts\python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| `CLOVER_REDIRECT_URI` | No | `http://localhost:8001/api/v1/integraciones/clover/callback` | URL del callback de OAuth. Debe apuntar a este backend y estar registrada en la app de Clover. |
| `CLOVER_OAUTH_URL` | No | según `CLOVER_ENV` | Host de la página de autorización (`https://sandbox.dev.clover.com` / `https://www.la.clover.com`). |
| `CLOVER_API_URL` | No | según `CLOVER_ENV` | Host del canje y la renovación de tokens (`https://apisandbox.dev.clover.com` / `https://api.la.clover.com`). |
| `CLOVER_CONNECT_URL` | No | `<CLOVER_API_URL>/connect` | Base de Cloud Pay Display. La de producción LATAM no está documentada por Clover: confirmarla con Fiserv y definirla acá. |
| `CLOVER_POS_ID` | No | `mundo-uniforme-pos` | Header `X-POS-Id` cuando la integración no tiene `pos_id` guardado. |
| `FRONTEND_URL` | No | `http://localhost:3000` | URL del POS: a dónde vuelve el navegador después del callback de OAuth. |
| `PAYMENT_FAKE_DELAY_SECONDS` | No | `3` | Segundos que `FakeTerminal` espera antes de aprobar (simula al cliente pagando). |
| `PAYMENT_RECONCILE_INTERVAL_SECONDS` | No | `60` | Intervalo del barrido de cobros sin resolver (corre también al iniciar). `0` lo desactiva (así corren los tests). |
| `PAYMENT_STALE_SECONDS` | No | `180` | Un cobro `pendiente`/`enviado`/`aprobado` sin cambios durante este tiempo se considera huérfano (timeout del cobro + margen). |
| `PAYMENT_RECONCILE_MAX_ATTEMPTS` | No | `10` | Intentos del barrido por cobro; después queda para revisión del admin. |
| `PAYMENT_RECONCILE_BACKOFF` | No | `2,5,10` | Esperas en segundos (separadas por coma) entre las consultas de la conciliación inmediata. Se expone como `settings.payment_reconcile_backoff`. |

> Los secretos de Clover no tienen default y se declaran como `SecretStr`; `Settings` usa `hide_input_in_errors=True` para que un error de validación al arrancar nunca muestre los valores. `settings.clover_oauth_url`, `clover_api_url` y `clover_connect_url` devuelven el override o el host derivado de `CLOVER_ENV`; `APP_VERSION` (`config.py`) es la versión de la API y del `User-Agent` enviado a Clover.
> `JWT_SECRET` fue eliminado: no se usaba, la validación del token la hace Supabase Auth (ver Autenticación).
> Las variables de entorno tienen prioridad sobre `.env`; los tests y CI usan valores ficticios y no requieren un `.env` real.

---

## Estructura del Proyecto

```
app/
├── main.py                        # Entry point: logging, CORS, routers, health, exception handlers y lifespan (barrido de cobros)
├── core/
│   ├── config.py                  # Settings (pydantic-settings, lee .env)
│   ├── supabase.py                # Singleton del cliente Supabase
│   ├── db_utils.py                # fetch_all (paginado interno con .range()) y single_row (resultado de RPC)
│   ├── timeutils.py               # Zona horaria de negocio (America/Argentina/Buenos_Aires) y límites del día local
│   └── exceptions.py              # Excepciones custom: CajaError, UsuarioError y PagoError (con status_code)
├── api/
│   ├── auth_deps.py               # get_current_user (token + rol + activo), RoleChecker, TTLCache e invalidate_user
│   ├── deps.py                    # Composición: get_pago_service() arma PagoService con sus adaptadores
│   └── v1/
│       └── endpoints/
│           ├── productos.py       # Rutas de productos y variantes
│           ├── caja.py            # Rutas de sesiones y movimientos de caja
│           ├── ventas.py          # Rutas de ventas
│           ├── clientes.py        # Rutas de clientes
│           ├── reportes.py        # Rutas de reportes (solo admin)
│           ├── catalogos.py       # Rutas de marcas y categorías
│           ├── usuarios.py        # Rutas de usuarios y roles (incluye el alta)
│           ├── configuracion.py   # Configuración del negocio (lectura: todos; edición: admin)
│           ├── auditoria.py       # Visor de la tabla `logs` (solo admin)
│           ├── pagos.py           # Cobros con terminal (`/pagos`) y estado de la integración (`/integraciones/terminal`)
│           └── clover.py          # OAuth de Clover (`/integraciones/clover/conectar | callback | desconectar`)
├── integrations/
│   ├── payment_terminal/
│   │   ├── port.py                # Puerto PaymentTerminal + ChargeRequest/ChargeResult/RefundResult + errores del terminal
│   │   ├── fake.py                # FakeTerminal: adaptador en memoria, con guion para tests y reglas por centavos para desarrollo
│   │   └── factory.py             # get_terminal(): elige el adaptador según PAYMENT_TERMINAL
│   └── clover/
│       ├── cloud_terminal.py      # CloverCloudTerminal: adaptador Cloud Pay Display del puerto (httpx, headers, mapeo de códigos)
│       ├── oauth.py               # CloverOAuthClient (authorize URL, canje, refresh) + state firmado (sign_state / verify_state)
│       ├── tokens.py              # TokenCipher (Fernet) + CloverTokenProvider (renovación con lock + compare-and-set)
│       ├── connection.py          # CloverConnection: conectar / callback / desconectar
│       └── wiring.py              # Arma el adaptador y sus colaboradores desde settings
├── repositories/
│   ├── supabase_pago_store.py     # Adaptador Supabase del puerto PagoStore (pagos_externos, integracion_terminal, cotizar/registrar)
│   └── supabase_clover_store.py   # Columnas OAuth de integracion_terminal: tokens cifrados, compare-and-set, conectar / desconectar
├── schemas/
│   ├── productos.py               # Pydantic models: ProductCreate/Update/Response, VariantCreate/Update/Response, StockUpdate, StockMovementResponse/ListResponse (kardex)
│   ├── caja.py                    # Pydantic models: CajaApertura, CajaMovimiento, CajaCierre, SesionCajaResponse, CajaMovimientoResponse, CajaResumenResponse
│   ├── ventas.py                  # Pydantic models: VentaCreate, VentaItem, AjusteVenta, VentaAnular, VentaResponse, VentaListResponse, VentaDetalleResponse / VentaDetalleAdminResponse
│   ├── clientes.py                # Pydantic models: ClienteCreate/Update/Response
│   ├── reportes.py                # Pydantic models: VentasTotalesReporte, ProductoTopReporte, CajaResumenReporte
│   ├── configuracion.py           # Pydantic models: ConfiguracionUpdate (parcial) / ConfiguracionResponse
│   ├── auditoria.py               # Pydantic models: AuditLogItem / AuditLogListResponse
│   ├── pagos.py                   # Pydantic models: CobroTerminalCreate, CobroIniciadoResponse, PagoResponse / PagoAdminResponse / PagoListResponse, TerminalIntegracionResponse / Update
│   ├── catalogos.py               # Pydantic models: MarcaCreate/Update/Response, CategoriaCreate/Update/Response
│   ├── common.py                  # Respuestas genéricas: OkResponse (`{"ok": true}`) y MessageResponse (`{"message": ...}`)
│   └── usuarios.py                # Pydantic models: RoleResponse, UsuarioResponse, UsuarioRoleUpdate, UsuarioActivoUpdate, MeResponse
├── services/
│   ├── producto_service.py        # Lógica de negocio de productos y variantes
│   ├── caja_service.py            # Lógica de negocio de caja
│   ├── venta_service.py           # Lógica de negocio de ventas
│   ├── cliente_service.py         # Lógica de negocio de clientes
│   ├── reporte_service.py         # Reportes: delega en las funciones SQL reporte_*
│   ├── catalogo_service.py        # CRUD de marcas y categorías
│   ├── usuario_service.py         # Lectura de perfiles/roles, alta (Auth + perfil), cambio de rol y activación (con reglas de seguridad)
│   ├── configuracion_service.py   # Lectura y edición parcial de la fila única de `configuracion`
│   ├── auditoria_service.py       # Listado paginado de `logs` con filtros y nombre del autor
│   ├── pago_ports.py              # Puerto de persistencia PagoStore + ActiveChargeExists / SaleRejected
│   ├── pago_service.py            # PagoService: orquesta cobro → venta, reembolso y conciliación (solo depende de los puertos)
│   ├── pago_reconciler.py         # Tarea asyncio del barrido periódico (start_reconciler / stop_reconciler)
│   ├── audit.py                   # `audit()` encola el log de auditoría (`AuditEvent`); `record_audit()` lo escribe en el acto (tareas en segundo plano)
│   └── log_service.py             # Auditoría: inserta en tabla `logs` (BackgroundTask)
scripts/
├── export_openapi.py              # Genera `openapi.json` (raíz) desde `app.openapi()`
├── seed_data.py                   # Carga de datos de prueba
└── get_token.py                   # Obtiene un JWT de Supabase para probar la API
tests/
├── conftest.py                    # Variables de entorno ficticias + fixtures `client` / `auth_client` (admin) / `employee_client` (empleado)
├── test_settings.py               # Settings: defaults, parseo de CORS, validaciones
├── test_health.py                 # /health y /health/ready
├── test_cors.py                   # Preflight CORS (origen permitido / desconocido)
├── fakes_pagos.py                 # InMemoryPagoStore: implementación en memoria del puerto PagoStore (CAS de estado, un cobro activo, registro idempotente)
├── test_fake_terminal.py          # FakeTerminal (guion, reglas por centavos, cancelación, ocupado) y factory
├── fakes_clover.py                # InMemoryCloverStore (fila de integración con CAS) y ScriptedOAuth
├── test_clover_terminal.py        # CloverCloudTerminal con httpx.MockTransport: headers, centavos, idempotencia, mapeo de códigos, 401 → refresh → reintento
├── test_clover_tokens.py          # Cifrado, renovación, refresh de un solo uso (CAS), fallas que deshabilitan, y el store de Supabase
├── test_clover_oauth.py           # State firmado, endpoints de token, conectar / callback / desconectar (HTTP), settings de Clover
├── test_clover_sandbox_live.py    # Suite opcional contra el sandbox (`CLOVER_SANDBOX_LIVE=1 pytest -m clover_sandbox`); excluida por defecto
├── test_pago_service.py           # PagoService con FakeTerminal: aprobado, rechazado, cancelado, ocupado, conciliación inmediata, barrido, reembolso, idempotencia
├── test_pago_store.py             # Adaptador Supabase de PagoStore: consultas, transición condicional y mapeo de errores
├── test_pagos.py                  # Endpoints /pagos e /integraciones/terminal (roles, dueño, 202, polling), MU011 y lifespan del barrido
├── fakes.py                       # FakeSupabase: cliente falso que registra las consultas y devuelve respuestas en cola (`Counted(filas, total)` simula `count="exact"`)
├── test_error_handling.py         # Mapeo de APIError (incluye códigos MU00x), 500 genérico, errores de catálogos
├── test_auth_deps.py              # get_current_user: 401 sin filtrar detalles, usuarios inactivos, TTLCache e invalidate_user
├── test_authz.py                  # Matriz de roles (403 empleado / 200 admin por ruta), costos ocultos, ids UUID inválidos → 422
├── test_usuarios.py               # /usuarios/me, cambio de rol y de `activo`: 404/400/409, auditoría e invalidación del cache
├── test_ventas.py                 # RPC registrar_venta (descuento/recargo), Idempotency-Key, validaciones, /ventas/hoy, listado, detalle y anulación
├── test_caja.py                   # Apertura (usuario del token, 409), cierre (cerrar_caja), resumen, movimientos, paginado
├── test_productos.py              # registrar_ajuste_stock, kardex, validaciones de productos/variantes, paginado interno del catálogo
├── test_clientes.py               # Validaciones, saneado de búsqueda, paginado
├── test_batch2.py                 # Lote 2: devoluciones, configuración, stock bajo, alta de usuarios, categorías de productos y visor de auditoría
├── test_audit.py                  # Helper `audit()`: serialización, eventos normalizados y evento en un endpoint
├── test_responses.py              # Formas de respuesta tipadas (delete, ajuste de stock) y mensajes 404 en español
├── test_openapi.py                # Falla si `openapi.json` no coincide con `app.openapi()`
└── test_reportes.py               # Reportes vía RPC, límite de productos-top, solo admin
.github/workflows/ci.yml           # CI: ruff + pytest en cada push / PR
openapi.json                       # Esquema OpenAPI versionado (se regenera con `python scripts/export_openapi.py`)
pyproject.toml                     # Configuración de ruff y pytest
requirements.txt                   # Dependencias de ejecución (versiones fijadas)
requirements-dev.txt               # requirements.txt + pytest, ruff
README.md                          # Instalación, ejecución, tests y lint
```

---

## Autenticación y autorización

- **Mecanismo:** JWT Bearer (tokens de Supabase Auth)
- **Dependencia:** `get_current_user` en `app/api/auth_deps.py`
- **Funcionamiento:** Extrae el token del header `Authorization: Bearer <token>` y lo valida con `supabase.auth.get_user(token)` (no hay verificación local del JWT). Si el token es inválido o la validación falla, retorna 401 con el mensaje fijo `"No se pudieron validar las credenciales"`; el error real solo se loguea.
- **Rol y estado:** Después de validar el token, lee `perfiles.select("activo, roles(nombre)")` para el usuario, en **una sola consulta**.
  - Sin perfil (PostgREST `PGRST116` o respuesta vacía) o sin rol → `empleado` activo.
  - `activo = false` → **403 `"Usuario inactivo"`** en cualquier endpoint autenticado. Solo un `false` explícito desactiva.
  - Si la consulta falla por otro motivo → **503 `"No se pudo verificar el usuario. Intentá de nuevo."`** (no se puede saber si el usuario sigue activo, así que no se lo deja pasar). El error real solo se loguea.
- **`current_user`:** Es un `AppUser` propio con `id`, `email`, `rol` y `activo` (no el objeto `User` de Supabase).
- **`RoleChecker(allowed_roles)`:** Dependency que responde 403 `"No tienes permisos suficientes para realizar esta acción."` si `current_user.rol` no está en la lista. Se usa con `["admin"]` en todas las rutas marcadas con 🔒.
- **Caja:** `POST /api/v1/caja/apertura` toma el usuario de la sesión de `current_user.id` (token). Si el body trae `usuario_id`, se ignora.

### Matriz de roles (decisión de negocio)

Los roles salen de `perfiles.rol_id → roles.nombre` (`admin`, `empleado`). ✅ = permitido, 🔒 = 403.

| Recurso | Operación | empleado | admin |
|---|---|---|---|
| Ventas | `POST /ventas/` (descuento de empleado: máximo 10%), `GET /ventas/hoy`, `GET /ventas/` | ✅ | ✅ |
| Ventas | `GET /ventas/{id}` | ✅ **sin costos** | ✅ con `costo_unitario` y `total_costo` |
| Ventas | `POST /ventas/{id}/anular`, `POST /ventas/{id}/devoluciones` | 🔒 | ✅ |
| Caja | `GET /caja/estado`, `GET /caja/resumen`, `GET /caja/movimientos` (sesión actual), `POST /caja/apertura`, `POST /caja/movimiento`, `POST /caja/cierre` | ✅ | ✅ |
| Caja | `GET /caja/sesiones`, `GET /caja/sesiones/{sesion_id}/movimientos` (historial de otras sesiones) | 🔒 | ✅ |
| Productos | `GET /productos/`, `GET /productos/sku/{sku}` | ✅ **sin costos** (`precio_costo: null`) | ✅ con costos |
| Productos | `GET /productos/stock-bajo` (sin costos) | ✅ | ✅ |
| Productos | `PUT /productos/{id}/categorias`, `POST /productos/`, `PATCH /productos/{id}`, `POST /productos/variante`, `PATCH /productos/variante/{id}`, `PATCH /productos/inventario/stock`, `GET /productos/variante/{id}/movimientos` (kardex), `DELETE /productos/{id}`, `DELETE /productos/variante/{id}` | 🔒 | ✅ |
| Catálogos | `GET /catalogos/marcas`, `GET /catalogos/categorias` | ✅ | ✅ |
| Catálogos | `POST` / `PATCH` / `DELETE` de marcas y categorías | 🔒 | ✅ |
| Clientes | `GET /clientes/`, `POST /clientes/`, `PATCH /clientes/{id}` | ✅ | ✅ |
| Reportes | `GET /reportes/*` | 🔒 | ✅ |
| Usuarios | `GET /usuarios/me` | ✅ | ✅ |
| Usuarios | `GET /usuarios/`, `POST /usuarios/`, `GET /usuarios/roles`, `PATCH /usuarios/{id}/rol`, `PATCH /usuarios/{id}/activo` | 🔒 | ✅ |
| Configuración | `GET /configuracion/` | ✅ | ✅ |
| Configuración | `PATCH /configuracion/` | 🔒 | ✅ |
| Auditoría | `GET /auditoria/` | 🔒 | ✅ |
| Pagos | `POST /pagos/terminal`, `GET /integraciones/terminal` | ✅ | ✅ |
| Pagos | `GET /pagos/{id}`, `POST /pagos/{id}/cancelar` | ✅ **solo los propios** (404 si es de otro) | ✅ cualquiera |
| Pagos | `GET /pagos/`, `POST /pagos/{id}/conciliar`, `PATCH /integraciones/terminal` | 🔒 | ✅ |
| Clover | `GET /integraciones/clover/conectar`, `POST /integraciones/clover/desconectar` | 🔒 | ✅ |
| Clover | `GET /integraciones/clover/callback` | sin token: lo autentica el `state` firmado (ver "Clover") | — |

Un rol distinto de `admin` (o un usuario sin perfil) se trata como `empleado`.

### Costos ocultos para no-admin

`precio_costo` solo lo ve un admin. En `GET /productos/` y `GET /productos/sku/{sku}` el endpoint quita el campo de cada variante antes de responder, y `VariantResponse.precio_costo` es opcional, así que un empleado recibe `"precio_costo": null`. El resto de las respuestas que ve un empleado no lleva costos: `VentaResponse` y el listado `GET /ventas/` solo exponen importes de venta (nunca `total_costo`); en `GET /ventas/{id}` un empleado recibe `VentaDetalleResponse`, sin `total_costo` ni `costo_unitario` (el servicio ni siquiera pide esas columnas a la base), y las respuestas de caja, clientes y catálogos no tienen columnas de costo. Las rutas que devuelven la fila completa de una variante (alta, edición, ajuste de stock) son solo admin.

### Cache de tokens

- El `AppUser` se cachea en memoria por token en `_TOKEN_CACHE`, un `TTLCache` propio (sin dependencias nuevas): **máximo 1024 entradas, TTL de 60 s**. Al insertar se descartan primero las entradas vencidas y, si sigue lleno, las más antiguas; la memoria no puede crecer sin límite.
- Un cambio de rol o una desactivación hecha por fuera de la API (por ejemplo desde el panel de Supabase) tarda como máximo 60 s en aplicarse.
- **`invalidate_user(user_id)`** descarta las entradas cacheadas de ese usuario. La llaman `PATCH /usuarios/{id}/rol` y `PATCH /usuarios/{id}/activo`, así que esos cambios aplican en el próximo request.
- Un usuario inactivo nunca se cachea: al reactivarlo vuelve a entrar de inmediato.
- El cache es por proceso: no se comparte entre workers (con varios workers, la invalidación solo alcanza al proceso que atendió el cambio; el resto espera el TTL de 60 s).

### Ids en la URL

Los parámetros de ruta que apuntan a filas con id UUID (`productos`, `producto_variantes`, `clientes`, `sesiones_caja`, `perfiles`) están tipados como `uuid.UUID`: un id mal formado responde **422** sin llegar a PostgREST. Los servicios reciben `str(id)`. Marcas y categorías siguen usando ids enteros.

## Auditoría (`logs`)

Los endpoints de escritura registran la auditoría con un único helper, `audit()` (`app/services/audit.py`):

```python
audit(background_tasks, current_user, "CREATE", "productos", entidad_id=..., payload=..., respuesta=..., descripcion=...)
```

- Encola `LogService.registrar_log()` como `BackgroundTask`; ese método inserta en la tabla `logs` (evento, entidad, entidad_id, payload, usuario_id, estado). Si el insert falla, solo se loguea el error y no afecta la respuesta.
- `payload` y `respuesta` se pasan por `jsonable_encoder`: UUID, datetime y Decimal se serializan solos, así que se puede pasar `model_dump()` o la fila de la base tal cual.
- `evento` es un `AuditEvent` (`Literal`): `CREATE`, `UPDATE`, `DELETE`, `ADJUST_STOCK`, `OPEN_CAJA`, `CLOSE_CAJA`, `CASH_MOVEMENT`, `CREATE_SALE`, `CANCEL_SALE`, `RETURN_SALE`, `UPDATE_ROL`, `UPDATE_ACTIVO`, y los de cobros con terminal: `CHARGE_STARTED`, `CHARGE_APPROVED`, `CHARGE_FAILED`, `CHARGE_UNKNOWN`, `CHARGE_CANCELLED`, `REFUND_DONE`, `TERMINAL_SETTINGS`, y los de la cuenta de Clover: `CLOVER_CONNECTED`, `CLOVER_DISCONNECTED`. El tipo de entidad va en `entidad` (tabla afectada).
- `record_audit(usuario_id, evento, entidad, ...)` escribe el mismo registro **en el acto**, para código que corre fuera de un request (la tarea del cobro y el barrido), donde no hay `BackgroundTasks`. Nunca lanza.
- Los eventos antiguos se renombraron: `UPDATE_STOCK` → `ADJUST_STOCK`, `APERTURA_CAJA` → `OPEN_CAJA`, `CIERRE_CAJA` → `CLOSE_CAJA`, `MOVIMIENTO_CAJA` → `CASH_MOVEMENT`, `CREATE_VENTA` → `CREATE_SALE`. El resto (`CREATE`, `UPDATE`, `DELETE`, `UPDATE_ROL`, `UPDATE_ACTIVO`) se mantiene. Las filas históricas de `logs` conservan el nombre viejo.

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
| `PagoError` | `exc.status_code` (400 / 404 / 409 / 503) | Mensaje de negocio de los cobros con terminal (ver "Pagos con terminal") |
| `CajaError` | `exc.status_code` (400 por defecto) | Mensaje de negocio: 400 `No hay sesión de caja abierta.`, 409 `Ya existe una sesión de caja abierta.` |
| `UsuarioError` | `exc.status_code` (400 por defecto) | Mensaje de negocio de gestión de usuarios: 404, 400 o 409 (ver Usuarios) |
| `postgrest.APIError` código `23505` | 409 | `Conflicto: el registro ya existe` |
| `postgrest.APIError` código `23503` | 409 | `Conflicto: el registro está referenciado por otros datos` |
| `postgrest.APIError` código `PGRST116` | 404 | `Recurso no encontrado` |
| `postgrest.APIError` código `22P02` | 400 | `Dato inválido` |
| `postgrest.APIError` código `23514` (CHECK) | 400 | `Dato fuera de rango` |
| `postgrest.APIError` código `MU00x` | ver tabla siguiente | El mensaje de la base (propio, en español) |
| `postgrest.APIError` (otro código) | 500 | `Error interno del servidor` |
| `Exception` no manejada | 500 | `Error interno del servidor` |

**Códigos de negocio de la base (`MU00x`)**

Los lanzan las funciones SQL propias (`registrar_venta`, `anular_venta`, `cerrar_caja`, `registrar_ajuste_stock`, ...). Llegan como `APIError.code` y se mapean en `DB_BUSINESS_ERROR_STATUS` (`main.py`). Su `message` lo escribimos nosotros, por eso es el único caso en que el mensaje de la base se devuelve como `detail`.

| Código | HTTP Status | Significado |
|---|---|---|
| `MU001` | 400 | No hay sesión de caja abierta (también: anular una venta en efectivo de una sesión ya cerrada sin caja abierta para la devolución) |
| `MU002` | 409 | Stock insuficiente / el stock quedaría negativo |
| `MU003` | 400 | Datos de entrada inválidos |
| `MU004` | 404 | Recurso no encontrado (variante, sesión, ...) |
| `MU005` | 409 | La sesión de caja ya está cerrada |
| `MU006` | 409 | La venta ya está anulada |
| `MU007` | 403 | Descuento por encima del límite permitido para el rol (empleado: `configuracion.descuento_max_empleado`, 10% por defecto) |
| `MU008` | 409 | La venta está anulada (no se puede devolver) |
| `MU009` | 409 | La cantidad a devolver supera lo pendiente de devolver de la variante |
| `MU010` | 409 | La venta tiene devoluciones (no se puede anular; devolver lo pendiente) |
| `MU011` | 409 | El total cambió desde que se inició el cobro en el terminal (`registrar_venta_con_pago`; la venta no se registra y el cobro se reembolsa) |

Un código `MU` no listado se trata como cualquier otro error desconocido (500 genérico).

**Reglas:**
- El error real (código, mensaje y detalles de PostgREST, o el traceback) se registra con `logging` en el servidor y **nunca** se incluye en la respuesta, salvo el `message` de los códigos `MU00x` listados arriba.
- Los endpoints no deben devolver `str(e)` de excepciones arbitrarias. Solo se usan como `detail` los mensajes de negocio propios (`ValueError` de los servicios, `CajaError`, `UsuarioError`); cualquier otra excepción se deja propagar a los handlers globales.
- `HTTPException` y los errores de validación (422) conservan el comportamiento estándar de FastAPI.
- Las respuestas 500 del handler genérico las emite la capa externa de Starlette, por fuera de `CORSMiddleware`, por lo que no llevan headers CORS.

### CORS y logging

- `CORSMiddleware` con orígenes de `CORS_ORIGINS`, `allow_credentials=False`, métodos `GET, POST, PUT, PATCH, DELETE, OPTIONS` y headers `Authorization, Content-Type, Idempotency-Key`. Un preflight desde un origen no listado recibe 400.
- Logging estándar (`logging.basicConfig`) con el nivel de `LOG_LEVEL`.

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
| `subtotal` | numeric | default 0. Suma de `cantidad × precio_unitario` de los items, antes de descuento y recargo |
| `descuento_aplicado` | numeric | Importe del descuento (siempre un monto, aunque se haya pedido como porcentaje). `CHECK >= 0` |
| `recargo_aplicado` | numeric | Importe del recargo. `CHECK >= 0` |
| `total` | numeric | default 0.00. `total = subtotal − descuento_aplicado + recargo_aplicado` |
| `total_costo` | numeric | default 0.00 |
| `metodo_pago` | text | |
| `origen` | text | default `'Local'` |
| `estado_pago` | text | nullable, default `'Completado'` |
| `nube_orden_id` | text | nullable, integración Tiendanube |
| `notas` | text | nullable |
| `numero_cae` | bigint | nullable, para facturación AFIP |
| `idempotency_key` | text | nullable, única: clave del header `Idempotency-Key` |
| `estado` | text | `'completada'` (default) \| `'anulada'` (`CHECK`) |
| `anulada_at` | timestamptz | nullable, momento de la anulación |
| `anulada_por` | uuid | nullable, FK → `perfiles.id` (quién anuló) |
| `motivo_anulacion` | text | nullable |
| `pago_externo_id` | uuid | nullable, FK → `pagos_externos.id`, único cuando no es null: el cobro en terminal que pagó la venta |
| `created_at` | timestamptz | |

> `ventas` y `pagos_externos` se referencian mutuamente (`ventas.pago_externo_id` y `pagos_externos.venta_id`): el embed desde PostgREST nombra la FK (`pago:pagos_externos!pago_externo_id(...)`).

> `ventas` tiene **dos** FKs a `perfiles` (`usuario_id` y `anulada_por`): al embeber `perfiles` desde PostgREST hay que indicar la columna (`usuario:perfiles!usuario_id(...)`, `anulada_por:perfiles!anulada_por(...)`).

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
| `estado` | text | check: `'abierta'` \| `'cerrada'`. Un índice único parcial permite **una sola** sesión `'abierta'` |
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

#### `movimientos_stock` (kardex)
Libro de movimientos de stock. Lo escriben **solo** las funciones SQL (`registrar_venta`, `anular_venta`, `registrar_ajuste_stock`); la API únicamente lo lee.

| Columna | Tipo | Notas |
|---|---|---|
| `id` | bigint (PK) | identity |
| `variante_id` | uuid | FK → `producto_variantes.id` |
| `tipo` | text | `'venta'` \| `'anulacion'` \| `'ajuste'` \| `'devolucion'` |
| `cantidad` | integer | Delta con signo, nunca 0: negativo en una venta, positivo en una anulación o devolución, con el signo del ajuste |
| `stock_resultante` | integer | Stock de la variante después del movimiento (`>= 0`) |
| `venta_id` | uuid | nullable, FK → `ventas.id` (ventas y anulaciones) |
| `usuario_id` | uuid | nullable, FK → `perfiles.id` |
| `motivo` | text | nullable: motivo del ajuste o de la anulación |
| `created_at` | timestamptz | `now()` |

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

#### `configuracion`
Fila única (`id = 1`, `CHECK (id = 1)`); la fila inicial se insertó a mano (`supabase/data-fixes/20261112_insert_configuracion.sql`). RLS activado y acceso solo para `service_role`.

| Columna | Tipo | Notas |
|---|---|---|
| `id` | int (PK) | siempre 1 |
| `nombre_negocio` | text | not null, default `'Mundo Uniforme'` |
| `cuit`, `direccion`, `telefono`, `email`, `pie_ticket` | text | nullable |
| `descuento_max_empleado` | numeric | not null, `0..100`, default 10: límite de descuento (en % del subtotal) para empleados; lo lee `registrar_venta` |
| `updated_at` | timestamptz | `now()` |
| `updated_by` | uuid | nullable, FK → `perfiles.id` |

#### `devoluciones` / `devolucion_items`
Devoluciones parciales de una venta (solo las escribe `registrar_devolucion`).

| Tabla | Columnas |
|---|---|
| `devoluciones` | `id` uuid (PK), `venta_id` FK → `ventas.id`, `usuario_id` FK → `perfiles.id`, `motivo` text, `metodo_pago` (el de la venta), `monto` numeric `>= 0`, `sesion_caja` FK → `sesiones_caja.id` (la caja abierta al devolver, si fue en efectivo), `created_at` |
| `devolucion_items` | `id` bigint (PK), `devolucion_id` FK (cascade), `variante_id` FK → `producto_variantes.id`, `cantidad` int `> 0`, `monto` numeric `>= 0` |

#### `pagos_externos`
Un registro por intento de cobro en el terminal (migración `20261112172015_pagos_externos_terminal`). RLS activado y acceso solo para `service_role`.

| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid (PK) | `gen_random_uuid()` |
| `proveedor` | text | not null, default `'fake'` (el adaptador que hizo el cobro) |
| `external_payment_id` | text | not null, **unique**, `<= 32` caracteres; lo generamos nosotros y sirve para conciliar |
| `estado` | text | not null: `pendiente`, `enviado`, `aprobado`, `rechazado`, `cancelado`, `indeterminado`, `venta_registrada`, `error_registro`, `reembolsado` |
| `metodo_pago` | text | not null: `Tarjeta` \| `QR` |
| `monto` | numeric | not null, `> 0`: total cotizado al iniciar |
| `carrito` | jsonb | not null: `{items, cliente_id, descuento, recargo, es_admin}` para registrar la venta |
| `venta_id` | uuid | nullable, FK → `ventas.id` |
| `sesion_caja` | uuid | nullable, FK → `sesiones_caja.id` |
| `usuario_id` | uuid | nullable, FK → `perfiles.id` (quien inició el cobro) |
| `proveedor_payment_id` | text | id del pago en el proveedor (se usa para reembolsar) |
| `tarjeta_marca`, `tarjeta_ultimos4`, `codigo_autorizacion`, `tipo_ingreso` | text | `tarjeta_ultimos4` debe ser 4 dígitos |
| `cuotas` | int | nullable, `1..99` |
| `respuesta` | jsonb | respuesta del proveedor, saneada (sin datos de tarjeta) |
| `error` | text | motivo del rechazo o del error de registro |
| `intentos_conciliacion` | int | not null, default 0 |
| `created_at`, `updated_at` | timestamptz | `updated_at` cambia en cada transición de estado |

- Índice único parcial `pagos_externos_un_cobro_activo` sobre `((true)) where estado in ('pendiente','enviado','indeterminado')`: **un solo cobro en curso**; insertar otro falla con `23505` (→ 409 `Ya hay un cobro en curso`).

#### `integracion_terminal`
Fila única (`id = 1`, `CHECK (id = 1)`); se insertó a mano (`supabase/data-fixes/20261112_insert_integracion_terminal.sql`). RLS activado y acceso solo para `service_role`.

| Columna | Tipo | Notas |
|---|---|---|
| `id` | int (PK) | siempre 1 |
| `proveedor` | text | not null: `fake` \| `clover`. Refleja `PAYMENT_TERMINAL` (se actualiza en cada `PATCH`); el adaptador real lo decide la variable de entorno |
| `habilitado` | boolean | not null, default `false` |
| `merchant_id`, `device_id`, `pos_id` | text | nullable |
| `access_token_cifrado`, `refresh_token_cifrado`, `access_expira_at` | text / timestamptz | OAuth de Clover: tokens cifrados con Fernet (`CLOVER_TOKEN_KEY`) y vencimiento del access token. La API nunca los expone |
| `updated_at` | timestamptz | `now()` |
| `updated_by` | uuid | nullable, FK → `perfiles.id` |

### Funciones de base de datos

Se invocan con `supabase.rpc(nombre, params).execute()`. Toda la lógica de dinero y stock vive acá para que sea atómica (una transacción, con bloqueo de filas). Los errores de negocio se lanzan con códigos `MU00x` (ver "Health y manejo de errores").

| Función | Parámetros | Retorna | Descripción |
|---|---|---|---|
| `registrar_venta` | `p_usuario_id` uuid, `p_metodo_pago` text, `p_items` jsonb `[{variante_id, cantidad}]`, `p_cliente_id?` uuid, `p_idempotency_key?` text, `p_descuento_tipo?` text (`null` \| `'porcentaje'` \| `'monto'`), `p_descuento_valor` numeric = 0, `p_recargo_tipo?` text, `p_recargo_valor` numeric = 0, `p_es_admin` boolean = false | fila de `ventas` | Venta atómica: bloquea filas, toma precios y costos de la base, unifica variantes repetidas, descuenta stock, escribe `venta_detalle` y `movimientos_stock` (`venta`), y aplica descuento y recargo. La misma clave de idempotencia devuelve la venta original. `MU007` si un no-admin descuenta más de `configuracion.descuento_max_empleado` % |
| `registrar_devolucion` | `p_venta_id` uuid, `p_usuario_id` uuid, `p_motivo` text, `p_items` jsonb `[{variante_id, cantidad}]` | fila de `devoluciones` | Devolución parcial atómica: valida que la variante esté en la venta y que no se devuelva más de lo vendido menos lo ya devuelto, repone stock (`movimientos_stock` tipo `devolucion`) y calcula el reintegro por ítem = `precio_unitario × cantidad × total/subtotal` (descuento y recargo proporcionales). Si la venta fue en efectivo, registra un `egreso` en la caja abierta (`MU001` si no hay). `MU003` / `MU004` / `MU008` / `MU009` |
| `cotizar_venta` | `p_items` jsonb, `p_descuento_tipo?`, `p_descuento_valor` = 0, `p_recargo_tipo?`, `p_recargo_valor` = 0, `p_es_admin` boolean = false | jsonb | `{subtotal, descuento, recargo, total}` con las mismas reglas que `registrar_venta` (precios de la base, tope del empleado, stock, caja abierta) **sin escribir nada**. `MU001` / `MU002` / `MU003` / `MU004` / `MU007` |
| `registrar_venta_con_pago` | `p_pago_externo_id` uuid, `p_usuario_id` uuid, `p_metodo_pago` text, `p_items` jsonb, `p_total_esperado` numeric, `p_cliente_id?` uuid, `p_descuento_tipo?`, `p_descuento_valor` = 0, `p_recargo_tipo?`, `p_recargo_valor` = 0, `p_es_admin` boolean = false | fila de `ventas` | Llama a `registrar_venta` con la clave de idempotencia `pago:<id>` (un cobro = una venta) y guarda `ventas.pago_externo_id`. Si el total calculado difiere de `p_total_esperado` falla con `MU011` y revierte toda la venta |
| `variantes_stock_bajo` | — | setof | `(variante_id, producto_id, producto_nombre, sku, talle, color, stock_actual, stock_minimo)` de las variantes con `stock_actual <= stock_minimo`, sin costos |
| `anular_venta` | `p_venta_id` uuid, `p_usuario_id` uuid, `p_motivo` text | fila de `ventas` | Anulación atómica: devuelve el stock (`movimientos_stock` tipo `anulacion`), marca la venta como `anulada` y, si corresponde, registra el egreso de la devolución en efectivo. `MU004` / `MU006` / `MU001` / `MU003`; `MU010` si la venta ya tiene devoluciones |
| `cerrar_caja` | `p_sesion_id` uuid, `p_monto_real_efectivo` numeric, `p_observaciones` text | fila de `sesiones_caja` | Bloquea la sesión, calcula el efectivo esperado (apertura + ventas en efectivo + ingresos − egresos) y la cierra |
| `resumen_caja` | `p_sesion_id` uuid | jsonb | `{sesion_id, estado, fecha_apertura, monto_apertura, ventas_efectivo, ventas_tarjeta, ventas_qr, cantidad_ventas, ingresos, egresos, esperado_efectivo}` |
| `registrar_ajuste_stock` | `p_variante_id` uuid, `p_cantidad` int, `p_usuario_id` uuid, `p_motivo` text | fila de `producto_variantes` | Suma el delta al stock de forma atómica y lo registra en `movimientos_stock` (`ajuste`); falla con `MU002` si quedaría negativo, `MU004` si la variante no existe |
| `reporte_ventas` | `p_desde` date, `p_hasta` date | jsonb | `{total_ingresos (NETO), total_bruto, total_devoluciones, cantidad_operaciones, ventas_por_dia: [{fecha, total (neto), bruto, devoluciones, cantidad_ventas}]}`. Las devoluciones se restan en el día en que se hicieron |
| `reporte_productos_top` | `p_desde` date, `p_hasta` date, `p_limite` int = 50 | setof | `(variante_id, nombre_producto, talle, color, cantidad_vendida, ingresos_generados)`, netos de devoluciones |
| `reporte_cajas` | `p_desde` date, `p_hasta` date | jsonb | `{resumen_diario: [{fecha, sesiones_abiertas, monto_inicial_total, ventas_efectivo, ingresos, egresos, monto_real_efectivo_total, diferencia_esperado_vs_real}], diferencia_total_periodo}` |
| `obtener_productos` | `p_categoria_id?` int | setof `productos` | Productos, opcionalmente filtrados por categoría |

- Los tres `reporte_*` agrupan por **fecha local de Argentina**; un parámetro de fecha `null` deja ese extremo sin límite.
- `resumen_caja`, `reporte_ventas` y `reporte_productos_top` **excluyen las ventas anuladas** (`estado = 'completada'`).
- **Funciones obsoletas, pendientes de `DROP`** (siguen existiendo en la base pero la API ya no las llama y no deben volver a usarse):
  - `crear_venta` → reemplazada por `registrar_venta` (no escribe kardex ni aplica descuento/recargo).
  - `ajustar_stock` → reemplazada por `registrar_ajuste_stock` (no escribe kardex).
  - `finalizar_cierre_caja` → reemplazada por `cerrar_caja` (tenía errores).
- La base también tiene restricciones `CHECK` (error `23514` → 400) y el índice único de sesión abierta (`23505` → 409).

---

## Endpoints de la API

### Base URL: `http://127.0.0.1:8000/api/v1`

Todos los endpoints (salvo `GET /`, `GET /health` y `GET /health/ready`) requieren `Authorization: Bearer <supabase_jwt>`. En las tablas, **Auth** indica: ✅ = cualquier usuario activo con sesión válida, 🔒 = solo admin (`RoleChecker(["admin"])`, 403 para el resto). Un usuario inactivo recibe 403 en todos.

---

### 🛍️ Productos — `/api/v1/productos`

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/` | ✅ | Lista **todo** el catálogo con sus variantes (el POS lo filtra en el cliente), ordenado por `nombre`. Query param opcional: `?categoria_id=<int>`. Sin `limit`/`offset`: el servicio pagina internamente. `precio_costo` es `null` si el usuario no es admin |
| GET | `/sku/{sku}` | ✅ | Busca un producto por SKU de variante. Retorna 404 si no existe. `precio_costo` es `null` si el usuario no es admin |
| GET | `/stock-bajo` | ✅ | Variantes con `stock_actual <= stock_minimo` (RPC `variantes_stock_bajo`), sin costos: `{ items: [{ variante_id, producto_id, producto_nombre, sku, talle, color, stock_actual, stock_minimo }], total }`. Declarada antes de cualquier ruta `/{id}` |
| PUT | `/{id}/categorias` | 🔒 | Reemplaza el conjunto de categorías del producto. Body `{ categoria_ids: int[] (0..50, sin repetidos) }` (lista vacía = quitar todas). 404 si el producto no existe, 400 si alguna categoría no existe, 422 si el body es inválido. Responde el producto (`ProductResponse`) con sus categorías. Auditoría: `UPDATE` en `productos` |
| POST | `/` | 🔒 | Crea un producto nuevo |
| PATCH | `/{id}` | 🔒 | Actualiza nombre/descripción/marca de un producto |
| POST | `/variante` | 🔒 | Crea una variante vinculada a un producto |
| PATCH | `/variante/{id}` | 🔒 | Actualiza una variante (NO incluye stock_actual) |
| PATCH | `/inventario/stock` | 🔒 | Ajusta el stock de una variante (suma/resta `cantidad`) vía RPC `registrar_ajuste_stock`, que además deja el movimiento en el kardex con el usuario del token y el `motivo`; responde la fila completa de la variante (`StockAdjustResponse`). 404 si la variante no existe (`MU004`), 409 si el stock quedaría negativo (`MU002`) |
| GET | `/variante/{id}/movimientos` | 🔒 | Kardex de una variante: `{ items, total }`, más reciente primero. Query params: `limit` (1..200, default 50) y `offset` (≥ 0). `total` es el conteo exacto de movimientos de la variante |
| DELETE | `/variante/{id}` | 🔒 | Elimina una variante. 404 si no existe, 409 si tiene ventas en `venta_detalle` |
| DELETE | `/{id}` | 🔒 | Elimina un producto con sus variantes y vínculos en `producto_categorias`. 404 si no existe, 409 si alguna variante tiene ventas |

**Schemas de entrada:**

```python
# ProductCreate
{ nombre: str (1..120), descripcion?: str (max 1000), marca_id?: int }

# ProductUpdate
{ nombre?: str (1..120), descripcion?: str (max 1000), marca_id?: int }

# VariantCreate
{ producto_id: UUID, sku?: str (max 64), talle?: str (max 20), color?: str (max 40),
  precio_venta: float >= 0, precio_costo?: float >= 0 (=0),
  stock_actual?: int >= 0 (=0), stock_minimo?: int >= 0 (=0) }

# VariantUpdate
{ sku?: str (max 64), talle?: str (max 20), color?: str (max 40),
  precio_venta?: float >= 0, precio_costo?: float >= 0, stock_minimo?: int >= 0 }
# ⚠️ stock_actual NO está en VariantUpdate (no se puede editar por PATCH de variante)

# StockUpdate
{ variante_id: UUID, cantidad: int != 0, motivo: str (1..200) }
# cantidad es un delta: negativo para reducir stock. motivo se guarda en el kardex (`movimientos_stock.motivo`) y en la auditoría (`logs`)
```

**Kardex (`GET /variante/{id}/movimientos`, `StockMovementListResponse`):**

```python
{
  items: [{ id: int, created_at, tipo: 'venta' | 'anulacion' | 'ajuste', cantidad: int (con signo), stock_resultante: int,
            venta_id: UUID | null, motivo: str | null, usuario: { id, nombre } | null }],
  total: int   # conteo exacto, independiente de limit/offset
}
```

> Los modelos de respuesta (`ProductResponse`, `VariantResponse`) no aplican estos límites, para poder listar filas cargadas antes de que existieran.
> `VariantResponse.precio_costo` es `float | null`: llega `null` para quien no es admin (ver "Costos ocultos para no-admin").
> `{id}` es un UUID: un valor mal formado responde 422.

**Notas de implementación:**
- `get_products()` usa RPC `obtener_productos` + `.select("*, variantes:producto_variantes(*), categorias:producto_categorias(categoria:categorias(id, nombre))")` para incluir variantes y categorías (el servicio aplana la tabla puente a `categorias: [{id, nombre}]`, ordenadas por nombre), y recorre el resultado con `fetch_all()` (`.range()` de a 1000 filas, hasta recibir una página vacía) para que PostgREST nunca trunque el catálogo en silencio.
- `get_product_by_sku()` primero busca la variante por SKU → obtiene `producto_id` → carga el producto completo con variantes.
- `update_stock(update, usuario_id)` llama a la RPC `registrar_ajuste_stock` (atómica, escribe el kardex). Ya no hay read-modify-write en Python.
- `get_stock_movements()` lee `movimientos_stock` con `select(..., count="exact")`, embebe `usuario:perfiles(id, nombre)` y ordena por `created_at desc, id desc`. Una variante sin movimientos (o inexistente) devuelve `{items: [], total: 0}`.
- `ProductResponse` incluye `categorias: [{ id, nombre }]` en el listado, en `/sku/{sku}` y en `PUT /{id}/categorias`; las respuestas de alta y edición de producto devuelven `[]` (no consultan la tabla puente). `ProductCreate` no recibe categorías: se asignan con `PUT /{id}/categorias`.
- `set_categories()` valida el producto y las categorías, lee las actuales y escribe solo la diferencia (borra las que sobran, inserta las nuevas) en `producto_categorias`. No es atómico: si falla a mitad de camino, el conjunto puede quedar parcialmente aplicado y se puede repetir el pedido.
- `get_low_stock()` llama a la RPC `variantes_stock_bajo` (sin paginado; PostgREST corta en su `max-rows`).

---

### 💰 Caja — `/api/v1/caja`

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/estado` | ✅ | Retorna la sesión de caja abierta (global). Retorna `null` si no hay ninguna |
| GET | `/resumen` | ✅ | Totales en vivo de la sesión abierta (RPC `resumen_caja`). Retorna `null` (200) si no hay ninguna |
| POST | `/apertura` | ✅ | Abre una nueva sesión de caja a nombre del usuario del token. 409 si ya hay una abierta |
| POST | `/movimiento` | ✅ | Registra un ingreso o egreso manual en la sesión activa. Responde `CajaMovimientoResponse` (misma forma que los listados) |
| GET | `/movimientos` | ✅ | Lista los movimientos de la sesión activa |
| POST | `/cierre` | ✅ | Cierra la sesión activa vía RPC `cerrar_caja`. Responde `SesionCajaResponse` (la sesión ya cerrada) |
| GET | `/sesiones` | 🔒 | Lista las sesiones de caja (de todos los usuarios) por `fecha_apertura` desc. Paginado: `?limit=` (default 200, 1..1000) y `?offset=` (>= 0) |
| GET | `/sesiones/{sesion_id}/movimientos` | 🔒 | Lista movimientos de una sesión específica, ordenados por `creado_en` desc. `sesion_id` mal formado → 422 |

**Schemas de entrada:**

```python
# CajaApertura
{ monto_apertura: float >= 0 }
# `usuario_id` (UUID) todavía se acepta por compatibilidad, pero se IGNORA: el dueño es el usuario del token

# CajaMovimiento
{ tipo: 'ingreso'|'egreso', monto: float > 0, motivo: str (1..200, sin espacios sobrantes) }

# CajaCierre
{ monto_real_efectivo: float >= 0, observaciones?: str (max 500) }
```

**Schemas de respuesta:**

```python
# SesionCajaResponse (estado, apertura, cierre, sesiones)
{ id, usuario_id, fecha_apertura, fecha_cierre?, monto_apertura, monto_esperado_efectivo?,
  monto_real_efectivo?, estado, observaciones? }

# CajaMovimientoResponse (POST /movimiento y listados)
{ id, sesion_id, tipo, monto, descripcion, created_at }

# CajaResumenResponse (GET /resumen)
{ sesion_id: UUID, estado: str, fecha_apertura: datetime, monto_apertura: float,
  ventas_efectivo: float, ventas_tarjeta: float, ventas_qr: float, cantidad_ventas: int,
  ingresos: float, egresos: float, esperado_efectivo: float }
# esperado_efectivo = monto_apertura + ventas_efectivo + ingresos - egresos
```

**Notas importantes:**
- **La caja es global (decisión de negocio):** hay una sola caja para todos los usuarios. `CajaService.get_sesion_activa()` devuelve la única sesión con `estado = 'abierta'`; un **índice único** en la base garantiza que no haya dos. Movimientos, cierre, resumen y ventas usan esa sesión sin importar quién la abrió.
- **Apertura:** el `usuario_id` sale del token. Si ya hay una sesión abierta responde 409 `Ya existe una sesión de caja abierta.`, tanto por la verificación previa como si dos pedidos compiten y el índice único rechaza el insert (`23505`).
- **Cierre:** `monto_esperado_efectivo` lo calcula `cerrar_caja` (apertura + ventas en efectivo + ingresos − egresos), con la sesión bloqueada. Sin sesión abierta → 400; sesión ya cerrada → 409 (`MU005`).
- `movimientos_caja` usa `motivo` y `creado_en`; `CajaMovimientoResponse` los expone como `descripcion` y `created_at` (`validation_alias`), también en la respuesta de `POST /movimiento`.

---

### 🏷️ Ventas — `/api/v1/ventas`

| Método | Path | Auth | Descripción |
|---|---|---|---|
| POST | `/` | ✅ | Crea una venta completa de forma atómica (RPC `registrar_venta`), con descuento y recargo opcionales |
| GET | `/` | ✅ | Listado paginado de ventas con filtros; devuelve `{ items, total }` |
| GET | `/hoy` | ✅ | Ventas **completadas** del día actual **en Argentina** (las anuladas no aparecen). Lista de `VentaResponse` |
| GET | `/{id}` | ✅ | Detalle de una venta con sus items. Solo un admin recibe `costo_unitario` y `total_costo`. 404 `Venta no encontrada` |
| POST | `/{id}/anular` | 🔒 | Anula una venta (RPC `anular_venta`) y devuelve su detalle |

#### `POST /` — crear venta

```python
# VentaCreate
{
  items: [{ variante_id: UUID, cantidad: int (1..1000) }],   # entre 1 y 200 items
  metodo_pago: 'Efectivo' | 'Tarjeta' | 'QR',
  cliente_id?: UUID,
  descuento?: { tipo: 'porcentaje' | 'monto', valor: float >= 0 },   # porcentaje: máximo 100
  recargo?:   { tipo: 'porcentaje' | 'monto', valor: float >= 0 }    # porcentaje: máximo 100
}
# Header opcional: Idempotency-Key: <str, máx 100 caracteres>
```

- `items[].precio_unitario` todavía se acepta por compatibilidad pero se **IGNORA**; cualquier otro campo extra (p. ej. `total`) también. Precios, costos, subtotal y total salen siempre de la base.
- **Respuesta (`VentaResponse`):** `{ id, created_at, subtotal, descuento_aplicado, recargo_aplicado, total, metodo_pago, estado }`. `total_costo` nunca se expone. `descuento_aplicado` y `recargo_aplicado` son siempre **importes** (un valor `null` de filas antiguas se devuelve como `0`).

**Reglas de descuento y recargo** (las aplica la base, sobre toda la venta):
- `subtotal` = suma de `cantidad × precio_venta`. El descuento se calcula sobre el subtotal; el recargo, sobre `subtotal − descuento`. `total = subtotal − descuento_aplicado + recargo_aplicado`.
- El descuento no puede superar el subtotal (`MU003`, 400).
- **Empleado: descuento máximo de `configuracion.descuento_max_empleado` % del subtotal (10% por defecto)**, sea porcentaje o monto; por encima responde 403 (`MU007`). Un admin no tiene ese límite. El rol sale del token (`p_es_admin = current_user.rol == "admin"`), nunca del body.
- El recargo no tiene límite por rol.

**Flujo de `crear_venta()`:**
1. El endpoint lee el header `Idempotency-Key` (se recortan espacios; vacío = sin clave). Más de 100 caracteres → 400.
2. `VentaService.crear_venta()` llama a la RPC `registrar_venta` con `p_usuario_id` = usuario del token, `p_metodo_pago`, `p_items` = `[{variante_id, cantidad}]`, `p_cliente_id`, `p_idempotency_key`, `p_descuento_tipo`/`p_descuento_valor`, `p_recargo_tipo`/`p_recargo_valor` (`null`/`0` si no se envían) y `p_es_admin`.
3. La función, en una sola transacción: verifica la sesión de caja abierta, bloquea las variantes, toma `precio_venta`/`precio_costo` de la base, unifica variantes repetidas, descuenta stock, inserta `ventas`, `venta_detalle` y un movimiento `venta` por variante en `movimientos_stock`, calcula subtotal, descuento, recargo y total, y devuelve la fila de `ventas`.
4. Reintentar con la misma `Idempotency-Key` devuelve la venta original en lugar de crear otra.
5. El endpoint registra la auditoría (`CREATE_SALE`) como `BackgroundTask`.

**Errores:**

| Caso | HTTP | Origen |
|---|---|---|
| Body inválido (`metodo_pago` desconocido, sin items, `cantidad` fuera de 1..1000, UUID inválido, más de 200 items, descuento/recargo con `tipo` desconocido, `valor` negativo o porcentaje mayor a 100) | 422 | Pydantic |
| `Idempotency-Key` de más de 100 caracteres | 400 | Endpoint |
| No hay sesión de caja abierta | 400 | `MU001` |
| Datos inválidos detectados por la base (p. ej. descuento mayor al subtotal) | 400 | `MU003` |
| Descuento de un empleado mayor al 10% | 403 | `MU007` |
| Variante inexistente | 404 | `MU004` |
| Stock insuficiente | 409 | `MU002` |

#### `GET /` — listado

Query params (todos opcionales): `desde` y `hasta` (`YYYY-MM-DD`, **fechas locales de Argentina, ambas inclusive**), `metodo_pago` (`Efectivo` | `Tarjeta` | `QR`), `estado` (`completada` | `anulada`), `cliente_id` (UUID), `usuario_id` (UUID), `limit` (1..200, default 50), `offset` (≥ 0). Un valor inválido responde 422. Orden: `created_at` descendente.

```python
# VentaListResponse
{
  items: [{ id, created_at, subtotal, descuento_aplicado, recargo_aplicado, total, metodo_pago, estado,
            cliente: { id, nombre } | null, usuario: { id, nombre } | null }],
  total: int   # conteo exacto de ventas que cumplen los filtros, independiente de limit/offset
}
```

Sin el filtro `estado` el listado incluye completadas y anuladas. Nunca expone `total_costo`. Cada item agrega `total_devuelto` (suma de las devoluciones de la venta, `0` si no tiene).

#### `GET /{id}` — detalle

```python
# VentaDetalleResponse (empleado) / VentaDetalleAdminResponse (admin)
{
  ...mismos campos que un item del listado,
  motivo_anulacion: str | null, anulada_at: datetime | null, anulada_por: { id, nombre } | null,
  total_devuelto: float,
  items: [{ variante_id, sku, producto_nombre, talle, color, cantidad, cantidad_devuelta, precio_unitario, subtotal,
            costo_unitario }],   # costo_unitario: solo admin; cantidad_devuelta: unidades de esa variante ya devueltas
  devoluciones: [{ id, created_at, motivo, monto, metodo_pago, usuario: { id, nombre } | null,
                   items: [{ variante_id, cantidad, monto }] }],   # de la más antigua a la más nueva
  total_costo: float,            # solo admin
  pago: { metodo_pago, tarjeta_marca, tarjeta_ultimos4, codigo_autorizacion, cuotas, proveedor } | null
                                 # cobro en el terminal que pagó la venta (`ventas.pago_externo_id`); null si no hubo
}
```

Para un empleado las claves `costo_unitario` y `total_costo` **no están** en la respuesta (no llegan como `null`).

#### `POST /{id}/anular` — anulación (solo admin)

Body `VentaAnular`: `{ motivo: str (1..200, se recortan espacios) }`. Respuesta: el detalle de la venta ya anulada (`VentaDetalleAdminResponse`, igual que `GET /{id}` para admin). Auditoría: evento `CANCEL_SALE`.

**Reglas de anulación** (función `anular_venta`, una sola transacción):
- La venta pasa a `estado = 'anulada'` y guarda `anulada_at`, `anulada_por` (usuario del token) y `motivo_anulacion`. No se borra nada.
- El stock de cada variante vuelve y queda un movimiento `anulacion` en `movimientos_stock`.
- Una venta anulada deja de contar en `resumen_caja`, en los reportes y en `GET /ventas/hoy`.
- **Devolución en efectivo:** si la venta fue en `Efectivo` y pertenece a la sesión de caja **abierta**, basta con que deje de contar en el efectivo esperado de esa sesión. Si pertenece a una sesión **ya cerrada**, la devolución sale de la caja abierta actual: se registra un `egreso` en `movimientos_caja` por el total (motivo `Anulación venta <id corto>: <motivo>`); si no hay caja abierta responde 400 (`MU001`, "Abrí la caja para registrar la devolución en efectivo"). Las ventas con `Tarjeta` o `QR` no generan movimiento de caja.

| Caso | HTTP | Origen |
|---|---|---|
| `motivo` vacío o de más de 200 caracteres, id mal formado | 422 | Pydantic |
| No es admin | 403 | `RoleChecker` |
| Venta inexistente | 404 | `MU004` |
| La venta ya estaba anulada | 409 | `MU006` |
| Venta en efectivo de una sesión cerrada y no hay caja abierta | 400 | `MU001` |

- Una venta **con devoluciones no se puede anular** (409, `MU010`): hay que devolver lo pendiente.

#### `POST /{id}/devoluciones` — devolución parcial (solo admin)

Body `DevolucionCreate`: `{ motivo: str (1..200, se recortan espacios), items: [{ variante_id: UUID, cantidad: int 1..1000 }] (1..200) }`. Respuesta: el detalle actualizado de la venta (`VentaDetalleAdminResponse`). Auditoría: evento `RETURN_SALE` (entidad `ventas`).

**Reglas** (función `registrar_devolucion`, una sola transacción):
- Las variantes repetidas del body se unifican; cada una debe estar en la venta y la suma de lo ya devuelto más lo pedido no puede superar lo vendido (`MU009`).
- El stock vuelve y queda un movimiento `devolucion` en `movimientos_stock`.
- El reintegro de cada ítem es `precio_unitario × cantidad × total/subtotal`, o sea que el descuento y el recargo de la venta se aplican de forma proporcional. Se guarda en `devoluciones` / `devolucion_items`.
- Si la venta fue en `Efectivo`, el reintegro sale de la caja abierta como `egreso` en `movimientos_caja` (motivo `Devolución venta <id corto>: <motivo>`); sin caja abierta responde 400 (`MU001`). `Tarjeta` y `QR` no mueven la caja.
- Los reportes restan las devoluciones (ver "Reportes").

| Caso | HTTP | Origen |
|---|---|---|
| Body inválido, id mal formado | 422 | Pydantic |
| No es admin | 403 | `RoleChecker` |
| Venta inexistente | 404 | `MU004` |
| Venta anulada | 409 | `MU008` |
| Cantidad mayor a lo pendiente de devolver | 409 | `MU009` |
| Variante que no pertenece a la venta | 400 | `MU003` |
| Venta en efectivo y no hay caja abierta | 400 | `MU001` |

**Notas:**
- `GET /{id}` embebe además `devoluciones(id, created_at, motivo, monto, metodo_pago, usuario:perfiles!usuario_id(id, nombre), items:devolucion_items(variante_id, cantidad, monto))`; el servicio calcula `cantidad_devuelta` por variante y `total_devuelto`. El listado embebe solo `devoluciones(monto)` y lo suma en `total_devuelto`. Si una variante aparece en varias líneas de la misma venta, `cantidad_devuelta` repite el total de esa variante en cada línea.
- `GET /hoy` calcula "hoy" en `America/Argentina/Buenos_Aires` (`zoneinfo` + paquete `tzdata`, necesario en Windows) y filtra `estado = 'completada'`, `created_at >= medianoche local` y `< medianoche local siguiente`, expresadas en UTC. Recorre todas las páginas con `fetch_all()`, sin truncar en 1000 filas.
- `GET /` y `GET /{id}` usan embedding de PostgREST: `cliente:clientes(id, nombre)`, `usuario:perfiles!usuario_id(id, nombre)`, `anulada_por:perfiles!anulada_por(id, nombre)` e `items:venta_detalle(..., variante:producto_variantes(sku, talle, color, producto:productos(nombre)))`. El conteo del listado sale de `select(..., count="exact")`.
- `GET /hoy` está declarado antes de `GET /{id}` para que `hoy` no se interprete como un id.
- `venta_detalle.subtotal` es columna generada en DB (`cantidad * precio_unitario`).
- El campo `fecha` en `ventas` es redundante con `created_at`; las consultas filtran por `created_at`.

---

### 👤 Clientes — `/api/v1/clientes`

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/` | ✅ | Lista clientes ordenados por `nombre`. Query params opcionales: `?query=<str>` (busca por `nombre` o `dni_cuit` con ilike), `?limit=` (default 1000, 1..1000; el selector de clientes del POS filtra esta lista en el navegador) y `?offset=` (>= 0) |
| POST | `/` | ✅ | Crea un cliente nuevo |
| PATCH | `/{id}` | ✅ | Actualiza datos de un cliente. Retorna 404 si no existe, 422 si `id` no es un UUID |

**Schemas de entrada:**

```python
# ClienteCreate / ClienteUpdate
{
  nombre: str (1..120),      # requerido en Create
  dni_cuit?: str (max 20),
  email?: EmailStr,          # se valida el formato (paquete email-validator)
  telefono?: str (max 30),
  direccion?: str (max 200),
  ciudad?: str (max 80),
  tipo_iva?: 'Consumidor Final' | 'Monotributista' | 'Responsable Inscripto' | 'Exento'   # default en DB: 'Consumidor Final'
}
```

**Notas:**
- Los opcionales en blanco (`""`) se convierten a `null`: en Create no se envían, en Update limpian la columna.
- `ClienteResponse` no aplica estas validaciones, para poder listar filas anteriores.
- **Búsqueda:** el término de `?query=` se sanea antes de armar el filtro `or=(...)` de PostgREST (`sanitize_search_term`): solo quedan letras (incluidas acentuadas), dígitos, espacios y guiones; el resto se reemplaza por espacio, se colapsan los espacios y se corta a 50 caracteres. Si no queda nada, se devuelve la lista sin filtrar. Esto evita la inyección de filtros.

---

### 📊 Reportes — `/api/v1/reportes`

Todos los endpoints de reportes aceptan `?fecha_inicio=YYYY-MM-DD&fecha_fin=YYYY-MM-DD` (ambos opcionales; sin fecha, ese extremo queda sin límite).

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/ventas` | 🔒 | Ingresos **netos** de devoluciones, bruto, devoluciones, cantidad de operaciones y ventas agrupadas por día |
| GET | `/productos-top` | 🔒 | Top productos/variantes del período. Query param opcional `?limite=` (1..200, default 50) |
| GET | `/cajas` | 🔒 | Resumen de sesiones de caja por día (apertura, ventas en efectivo, ingresos, egresos, diferencia real vs esperado) |

**Schemas de respuesta:**

```python
# VentasTotalesReporte
{ total_ingresos: float,        # NETO = total_bruto - total_devoluciones
  total_bruto: float, total_devoluciones: float,
  cantidad_operaciones: int,    # ventas completadas del período (las devoluciones no cuentan como operación)
  ventas_por_dia: [{ fecha, total (neto), bruto, devoluciones, cantidad_ventas }] }
# Las devoluciones se imputan al día en que se registraron, no al de la venta original.

# ProductoTopReporte
{ variante_id: str, nombre_producto: str, talle?: str, color?: str, cantidad_vendida: int, ingresos_generados: float }

# CajaResumenReporte
{ resumen_diario: [{ fecha, sesiones_abiertas, monto_inicial_total, ventas_efectivo, ingresos, egresos, monto_real_efectivo_total, diferencia_esperado_vs_real }], diferencia_total_periodo: float }
```

**Notas de implementación:**
- `reporte_service.py` no agrega nada en memoria: cada endpoint llama a una función SQL (`reporte_ventas`, `reporte_productos_top`, `reporte_cajas`) con `p_desde` / `p_hasta` (y `p_limite`).
- Las funciones agrupan por **fecha local de Argentina**, así que un día del reporte coincide con el día de negocio.
- Si la función devuelve `null` en una lista o total (período sin datos), el servicio responde `[]` / `0`.

---

### 📚 Catálogos — `/api/v1/catalogos`

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/marcas` | ✅ | Lista marcas ordenadas por nombre |
| POST | `/marcas` | 🔒 | Crea una marca. Los errores de base se mapean globalmente (p. ej. 409 si viola una restricción única) |
| PATCH | `/marcas/{marca_id}` | 🔒 | Actualiza una marca. 404 si no existe |
| DELETE | `/marcas/{marca_id}` | 🔒 | Elimina una marca. 404 si no existe, 400 si hay productos con esa `marca_id` |
| GET | `/categorias` | ✅ | Lista categorías ordenadas por nombre |
| POST | `/categorias` | 🔒 | Crea una categoría. Los errores de base se mapean globalmente (p. ej. 409 si viola una restricción única) |
| PATCH | `/categorias/{categoria_id}` | 🔒 | Actualiza una categoría. 404 si no existe |
| DELETE | `/categorias/{categoria_id}` | 🔒 | Elimina una categoría. 404 si no existe, 400 si tiene productos en `producto_categorias` |

**Schemas de entrada:**

```python
# MarcaCreate / MarcaUpdate (en Update todos opcionales)
{ nombre: str, contacto_nombre?: str, telefono?: str, email?: str }

# CategoriaCreate / CategoriaUpdate (en Update todos opcionales)
{ nombre: str, descripcion?: str, tiendanube_id?: str }
```

> Las escrituras de catálogos (POST / PATCH / DELETE) son solo admin; las lecturas, para cualquier usuario activo.

---

### 👥 Usuarios — `/api/v1/usuarios`

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/me` | ✅ | Devuelve `MeResponse` del usuario autenticado: `{ id, email, rol, activo }` |
| GET | `/` | 🔒 | Lista perfiles con su rol (`perfiles` + `roles(id, nombre)`), ordenados por `created_at` desc |
| POST | `/` | 🔒 | Crea un usuario: login en Supabase Auth (email confirmado) + fila en `perfiles` (activo). Body `{ email: EmailStr, password: str (8..72), nombre: str (1..80), apellido?: str (<= 80), rol_id: int }`. Responde `UsuarioCreadoResponse` (`UsuarioResponse` + `email`). 400 `El rol indicado no existe`, 409 `Ya existe un usuario con ese email`, 422 si el body es inválido |
| GET | `/roles` | 🔒 | Lista roles (`id`, `nombre`) |
| PATCH | `/{id}/rol` | 🔒 | Cambia el `rol_id` de un perfil. Responde `UsuarioResponse` con el rol nuevo |
| PATCH | `/{id}/activo` | 🔒 | Activa o desactiva un perfil. Responde `UsuarioResponse` |

**Schemas:**

```python
# MeResponse
{ id: str, email?: str, rol: str, activo: bool }

# UsuarioRoleUpdate
{ rol_id: int }

# UsuarioActivoUpdate
{ activo: bool }   # estricto: solo true / false

# UsuarioResponse
{ id: UUID, nombre: str, apellido?: str, activo: bool, roles?: { id: int, nombre: str }, created_at: datetime }
```

**Errores de `PATCH /{id}/rol`:**

| Caso | HTTP | `detail` |
|---|---|---|
| `id` mal formado o body inválido | 422 | Pydantic |
| El usuario no existe | 404 | `Usuario no encontrado` |
| `rol_id` no existe en `roles` | 400 | `El rol indicado no existe` |
| Un admin se quita a sí mismo el rol de admin | 409 | `No podés quitarte el rol de administrador` |
| El cambio dejaría cero administradores activos | 409 | `Debe quedar al menos un administrador activo` |

**Errores de `PATCH /{id}/activo`:**

| Caso | HTTP | `detail` |
|---|---|---|
| `id` mal formado o body inválido | 422 | Pydantic |
| El usuario no existe | 404 | `Usuario no encontrado` |
| Un admin se desactiva a sí mismo | 409 | `No podés desactivar tu propio usuario` |
| Se desactivaría al último administrador activo | 409 | `Debe quedar al menos un administrador activo` |

**Notas de implementación:**
- Las reglas viven en `UsuarioService.update_rol()` / `set_activo()` y se lanzan como `UsuarioError` (handler global en `main.py`).
- "Administrador activo" = perfil con `activo = true` y el rol `admin`. La verificación busca otro perfil activo con ese rol distinto del usuario afectado.
- ⚠️ La verificación del último administrador es una lectura seguida de una escritura (no es atómica): dos pedidos simultáneos podrían pasarla a la vez. Para cerrarlo haría falta una función SQL.
- Después de un cambio exitoso, el endpoint llama a `invalidate_user(id)` (el cambio aplica en el próximo request del usuario) y registra la auditoría (`UPDATE_ROL` / `UPDATE_ACTIVO`, entidad `perfiles`).
- Un usuario desactivado recibe 403 `Usuario inactivo` en toda la API.

**Alta de usuarios (`POST /`):**
- `UsuarioService.create_usuario()` valida primero el rol, después llama a `supabase.auth.admin.create_user({email, password, email_confirm: True})` con el cliente de servicio y luego inserta el perfil (`id` = id del usuario de Auth, `activo: true`). Si el insert del perfil falla, borra el usuario de Auth (`auth.admin.delete_user`) y relanza el error, para no dejar logins huérfanos.
- Email repetido: se detecta por el `code` (`email_exists` / `user_already_exists`) o por el texto del error de Auth (`already been registered`, `already registered`, ...). Cualquier otro error de Auth se deja propagar (500 genérico).
- La contraseña solo viaja a Supabase Auth: no se guarda, no se registra en logs y **no** entra en el payload de auditoría (`CREATE` en `perfiles`, `entidad_id` = id nuevo).

---

### ⚙️ Configuración — `/api/v1/configuracion`

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/` | ✅ | Devuelve la configuración del negocio (fila única). 404 si la fila no existe |
| PATCH | `/` | 🔒 | Actualización parcial; fija `updated_at = now()` y `updated_by` = usuario del token. Auditoría: `UPDATE` en `configuracion` (`entidad_id` 1) |

```python
# ConfiguracionResponse
{ id: 1, nombre_negocio: str, cuit?: str, direccion?: str, telefono?: str, email?: str, pie_ticket?: str,
  descuento_max_empleado: float, updated_at?: datetime, updated_by: { id, nombre } | null }

# ConfiguracionUpdate (todos opcionales, al menos uno)
{ nombre_negocio?: str (1..120), cuit?: str (<= 20) | null, direccion?: str (<= 200) | null, telefono?: str (<= 30) | null,
  email?: EmailStr | null, pie_ticket?: str (<= 300) | null, descuento_max_empleado?: float (0..100) }
```

- Un body vacío, `nombre_negocio: null` o `descuento_max_empleado: null` responden 422. Un texto opcional vacío o en blanco se guarda como `null`.
- `descuento_max_empleado` lo usa `registrar_venta` (reemplaza el 10% fijo): el mensaje de `MU007` incluye el porcentaje vigente.
- `get()` embebe `updated_by:perfiles!updated_by(id, nombre)`.

---

### 💳 Pagos con terminal — `/api/v1/pagos` e `/api/v1/integraciones/terminal`

Cobros con tarjeta / QR en un terminal de pago ([plan](docs/design/plan-implementacion-clover.md): etapa B = núcleo con terminal simulado; etapa C = adaptador de Clover y OAuth, ver "Clover" más abajo). El efectivo no cambia y `POST /ventas/` sigue funcionando igual: mientras la integración esté deshabilitada, el POS cobra Tarjeta/QR como siempre.

| Método | Path | Auth | Descripción |
|---|---|---|---|
| POST | `/pagos/terminal` | ✅ | Inicia un cobro. Responde **202** `{ pago_id, total, estado: "pendiente" }`; el cobro corre en segundo plano |
| GET | `/pagos/{id}` | ✅ quien lo inició o admin | Estado del cobro (para el polling del POS). Otro usuario recibe 404 |
| POST | `/pagos/{id}/cancelar` | ✅ quien lo inició o admin | Cancela un cobro en curso; devuelve el pago |
| GET | `/pagos/?estado=&limit=&offset=` | 🔒 | Listado para revisión (`indeterminado`, `error_registro`, ...) → `{ items, total }` |
| POST | `/pagos/{id}/conciliar` | 🔒 | Fuerza la conciliación de un cobro ahora |
| GET | `/integraciones/terminal` | ✅ | `{ proveedor, habilitado, conectado, conectado_oauth }` para que el POS elija el flujo. Es también el "Probar conexión" |
| PATCH | `/integraciones/terminal` | 🔒 | Habilita / deshabilita y guarda los datos del dispositivo |
| GET | `/integraciones/clover/conectar` | 🔒 | `{ authorize_url }`: página de Clover a la que el POS manda el navegador del admin |
| GET | `/integraciones/clover/callback?code=&merchant_id=&state=` | sin token | Canjea el código y redirige (302) a `{FRONTEND_URL}/dashboard/settings?clover=ok` o `?clover=error&motivo=` |
| POST | `/integraciones/clover/desconectar` | 🔒 | Borra los tokens y deshabilita la integración → `{ conectado_oauth: false, habilitado: false }` |

```python
# CobroTerminalCreate (POST /pagos/terminal): mismo body que POST /ventas/, pero metodo_pago solo "Tarjeta" | "QR"
{ items: [{ variante_id: UUID, cantidad: int }], metodo_pago: "Tarjeta" | "QR", cliente_id?: UUID,
  descuento?: { tipo, valor }, recargo?: { tipo, valor } }

# PagoResponse (GET /pagos/{id}, POST /pagos/{id}/cancelar)
{ id, estado, metodo_pago, monto: float, venta_id: UUID | null, tarjeta_marca?, tarjeta_ultimos4?, codigo_autorizacion?,
  cuotas?: int, error?: str, created_at, updated_at }

# PagoAdminResponse (items de GET /pagos/ y respuesta de POST /pagos/{id}/conciliar): PagoResponse +
{ proveedor, external_payment_id, usuario_id, intentos_conciliacion }

# TerminalIntegracionResponse (GET y PATCH /integraciones/terminal)
{ proveedor: "fake" | "clover", habilitado: bool, conectado: bool,
  conectado_oauth: bool,               # hay tokens de la cuenta del proveedor (siempre false con `fake`)
  merchant_id?, device_id?, pos_id?, updated_at? }   # estos cuatro solo se completan para admin
# `conectado` = ping al dispositivo. Con Clover solo se intenta si `conectado_oauth` es true.

# TerminalIntegracionUpdate (PATCH): todos opcionales, al menos uno; texto vacío = null
{ habilitado?: bool, device_id?: str (<= 64), pos_id?: str (<= 64) }
```

**Errores**

| Caso | Status | `detail` |
|---|---|---|
| Integración deshabilitada | 409 | `La integración con el terminal está deshabilitada` |
| Ya hay un cobro `pendiente` / `enviado` / `indeterminado` | 409 | `Ya hay un cobro en curso` |
| Cotización rechazada por la base (`cotizar_venta`) | 400 / 404 / 409 / 403 | mensaje de `MU001` / `MU003` / `MU004` / `MU002` / `MU007` |
| Total a cobrar `<= 0` | 400 | `El total a cobrar debe ser mayor a 0` |
| `metodo_pago: "Efectivo"` u otro body inválido | 422 | validación |
| Pago inexistente o de otro usuario (no admin) | 404 | `Pago no encontrado` |
| El terminal no responde al cancelar | 503 | `No se pudo cancelar el cobro en el terminal` |
| `PATCH` con `habilitado: true` y Clover sin cuenta conectada | 409 | `Conectá la cuenta del terminal antes de habilitarlo` |
| `conectar` / `desconectar` con `PAYMENT_TERMINAL` distinto de `clover` | 409 | `Clover no es el terminal configurado (PAYMENT_TERMINAL)` |

**Estados de `pagos_externos.estado`**

- `pendiente`: creado y cotizado; todavía no se envió al terminal.
- `enviado`: el terminal está cobrando (hasta ~135 s).
- `aprobado`: el terminal aprobó; falta registrar la venta (estado de paso).
- `venta_registrada`: **final**. La venta existe (`venta_id`) y quedó vinculada (`ventas.pago_externo_id`).
- `rechazado`: **final**. Rechazado por el terminal, terminal ocupado (`Terminal ocupado`), solicitud inválida, o el terminal no registra el cobro. No se cobró.
- `cancelado`: **final**. Cancelado en el dispositivo o desde el POS.
- `indeterminado`: no se sabe si se cobró (timeout, error de red). Se concilia; **nunca se vuelve a cobrar**.
- `error_registro`: se cobró pero la base rechazó la venta (`MU011` total distinto, `MU002` sin stock, `MU001` caja cerrada, ...). Se reembolsa en el acto; si el reembolso no se confirma queda en este estado para revisión del admin (`error` termina en `reembolso no confirmado: revisar en el terminal`).
- `reembolsado`: **final**. Se cobró, no se pudo registrar la venta y se devolvió el total (`error` conserva el motivo).

Transiciones: `pendiente → enviado → aprobado → venta_registrada`; `aprobado → error_registro → reembolsado`; `enviado → rechazado | cancelado | indeterminado`; `indeterminado → aprobado | rechazado | cancelado`; `pendiente → cancelado` (cancelado antes de enviarse) y `pendiente | enviado | indeterminado → rechazado` (barrido). Los estados `pendiente`, `enviado` e `indeterminado` ocupan el único "cobro en curso" (índice único parcial).

**Arquitectura (hexagonal)**

- **Puerto del terminal** — `app/integrations/payment_terminal/port.py`: `PaymentTerminal` (`ping`, `status`, `charge`, `find_by_external_id`, `cancel_current`, `refund`, `show_welcome`), `ChargeRequest`, `ChargeResult` (`APPROVED | DECLINED | CANCELLED | UNKNOWN`), `RefundResult`, y los errores `TerminalBusy`, `TerminalUnavailable`, `TerminalBadRequest`. Montos en centavos. Adaptadores: `fake.py` (`FakeTerminal`) y `app/integrations/clover/cloud_terminal.py` (`CloverCloudTerminal`); `factory.py::get_terminal()` elige según `PAYMENT_TERMINAL`.
- **Puerto de persistencia** — `app/services/pago_ports.py`: `PagoStore` (+ `ActiveChargeExists`, `SaleRejected`). Adaptador: `app/repositories/supabase_pago_store.py`.
- **Aplicación** — `app/services/pago_service.py::PagoService` (instanciable, sin `@staticmethod`): solo conoce los dos puertos. No importa `supabase` ni nada de un proveedor: de Clover solo sabe, por el flag genérico `requires_oauth`, que el proveedor necesita una cuenta conectada (tokens en la fila de integración) antes de hacer ping o habilitarse.
- **Composición** — `app/api/deps.py::get_pago_service()` arma el servicio una vez por proceso; los endpoints lo reciben con `Depends` (los tests lo reemplazan con `app.dependency_overrides`).

**Cómo corre**

1. `POST /pagos/terminal` (dentro del request): verifica que la integración esté habilitada → `cotizar_venta` → inserta el pago `pendiente` con el carrito (`items`, `cliente_id`, `descuento`, `recargo`, `es_admin`), `monto` = total, `external_payment_id` (uuid4 hex, 32 caracteres), `sesion_caja` y `usuario_id` → agenda `ejecutar_cobro` con `BackgroundTasks` (corre en el threadpool después de enviar la respuesta) → 202.
2. `ejecutar_cobro(pago_id)` (segundo plano): `pendiente → enviado` y `terminal.charge(...)`. Aprobado → guarda marca, últimos 4, autorización, cuotas y la respuesta saneada → `registrar_venta_con_pago` → `venta_registrada`. Rechazado / cancelado → estado final. Resultado desconocido (o terminal inalcanzable) → `indeterminado` y **conciliación inmediata**: hasta 3 consultas `find_by_external_id` con esperas de `PAYMENT_RECONCILE_BACKOFF`. Al final siempre `show_welcome()` (sus errores se ignoran).
3. **Barrido** (`conciliar_pendientes`): lo lanza el `lifespan` de `main.py` al iniciar y cada `PAYMENT_RECONCILE_INTERVAL_SECONDS` (`app/services/pago_reconciler.py`: tarea asyncio que ejecuta la función síncrona en un hilo). Toma los `indeterminado` y los `pendiente` / `enviado` / `aprobado` sin cambios hace más de `PAYMENT_STALE_SECONDS`, suma `intentos_conciliacion` y los resuelve con `find_by_external_id` (los `aprobado` reintentan el registro de la venta). Tras `PAYMENT_RECONCILE_MAX_ATTEMPTS` deja de tomarlos y loguea un warning: quedan para el admin (`GET /pagos/?estado=indeterminado`, `POST /pagos/{id}/conciliar`).

**Reglas que no se rompen**

- **Nunca se cobra dos veces el mismo pago:** solo el proceso que gana `pendiente → enviado` llama a `charge`; un resultado desconocido se resuelve consultando, no cobrando de nuevo.
- **Transiciones condicionales:** todo cambio de estado es `update ... where id = ? and estado = <esperado>` (`PagoStore.transition`); si no afecta filas, otro proceso ya lo movió y el actual se detiene. Así conviven la tarea del cobro, el barrido, el admin y varios workers.
- **Una sola venta por cobro:** `registrar_venta_con_pago` usa el id del pago como clave de idempotencia.
- **Reembolso solo ante un rechazo definitivo de la base** (`SaleRejected`). Si el registro falla por conexión (resultado desconocido) se reintenta una vez y, si sigue fallando, el pago queda `aprobado` para el barrido: reembolsar ahí podría dejar una venta sin cobro. El reembolso no se reintenta a ciegas.
- **Si el terminal contesta que no conoce el cobro** (`find_by_external_id` → `None`): un `pendiente` / `enviado` / `indeterminado` solo pasa a `rechazado` cuando su último cambio supera `PAYMENT_STALE_SECONDS`; antes de eso se sigue esperando.
- **Datos de tarjeta:** solo se guardan marca y últimos 4. `pagos_externos.respuesta` se sanea (`sanitize_provider_response`: descarta claves con pinta de dato sensible y enmascara números de 12 a 19 dígitos). La auditoría solo lleva marca y últimos 4 (ni siquiera el código de autorización).
- **Cancelar:** un pago `pendiente` pasa directo a `cancelado` (todavía no llegó al terminal); uno `enviado` llama a `terminal.cancel_current()` y el estado final lo decide el cobro. En cualquier otro estado solo devuelve el pago.

**Auditoría:** `CHARGE_STARTED`, `CHARGE_APPROVED`, `CHARGE_FAILED` (rechazo o error de registro), `CHARGE_UNKNOWN`, `CHARGE_CANCELLED`, `REFUND_DONE` (entidad `pagos_externos`), `CREATE_SALE` (entidad `ventas`, al registrar la venta del cobro) y `TERMINAL_SETTINGS` (entidad `integracion_terminal`). Como la tarea corre fuera de un request, se escriben con `record_audit()` (misma tabla `logs`, escritura directa).

**Probarlo con el terminal simulado** (`PAYMENT_TERMINAL=fake`, el default)

1. Con un token de admin: `PATCH /api/v1/integraciones/terminal` con `{ "habilitado": true }`.
2. Con la caja abierta: `POST /api/v1/pagos/terminal` y consultar `GET /api/v1/pagos/{pago_id}` cada segundo.
3. El resultado depende de los centavos del total (usar un recargo por monto para forzarlos):
   - cualquier total → **aprobado** a los ~3 s (VISA terminada en 4242) y venta registrada;
   - total terminado en **`.13`** → **rechazado**;
   - total terminado en **`.99`** → **indeterminado**: las 3 primeras consultas siguen sin respuesta, así que queda para el barrido (o para `POST /pagos/{id}/conciliar`), que lo aprueba y registra la venta;
   - `POST /pagos/{id}/cancelar` durante la espera → **cancelado**.
4. El estado del terminal simulado vive en memoria del proceso: usar un solo worker de uvicorn en desarrollo.

#### Clover (`PAYMENT_TERMINAL=clover`)

Adaptador **Cloud Pay Display**: backend → API cloud de Clover (`<CLOVER_CONNECT_URL>/v1/...`, OAuth v2) → dispositivo. Todo vive en `app/integrations/clover/` y `app/repositories/supabase_clover_store.py`; `PagoService` no cambia.

**Puesta en marcha (sandbox)**

1. Generar `CLOVER_TOKEN_KEY`: `.venv\Scripts\python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
2. `.env`: `PAYMENT_TERMINAL=clover`, `CLOVER_ENV=sandbox`, `CLOVER_APP_ID`, `CLOVER_APP_SECRET`, `CLOVER_TOKEN_KEY`.
3. Registrar en la app de Clover la URL de redirección `http://localhost:8001/api/v1/integraciones/clover/callback` (= `CLOVER_REDIRECT_URI`; el backend debe escuchar en ese puerto).
4. Como admin, en el POS: Configuración → conectar Clover (`GET /integraciones/clover/conectar` → abrir `authorize_url`).
5. Guardar la serie del dispositivo (`PATCH /integraciones/terminal { device_id }`).
6. "Probar conexión": `GET /integraciones/terminal` → `conectado_oauth: true` y `conectado: true`. Después, `PATCH { habilitado: true }`.

**OAuth** (`oauth.py`, `connection.py`)

- `conectar` arma `<oauth host>/oauth/v2/authorize?client_id=&redirect_uri=&response_type=code&state=`. El `state` es `base64url(payload).base64url(HMAC-SHA256)` con `{u: id del admin, e: vencimiento (10 min), n: nonce}`; la clave del HMAC se deriva de `CLOVER_TOKEN_KEY`. No hay tabla nueva.
- `callback` no lleva bearer (es un redirect del navegador): valida el `state`, verifica que ese usuario siga siendo admin activo, canjea el código (`POST <api host>/oauth/v2/token` con JSON `{client_id, client_secret, code}`), guarda los tokens **cifrados** + `merchant_id` + `access_expira_at` + `proveedor = 'clover'` y audita `CLOVER_CONNECTED`. No cambia `habilitado`. Siempre responde 302 al POS; `motivo` es uno de: `state_invalido`, `state_expirado`, `parametros`, `sin_permiso`, `codigo_rechazado`, `clover_no_disponible`, `sin_integracion`, `no_configurado`, `error_interno`.
- `desconectar` pone en null los tokens y `merchant_id`, `habilitado = false` y audita `CLOVER_DISCONNECTED` (no revoca nada del lado de Clover).

**Tokens** (`tokens.py`)

- `CloverTokenProvider.get_access_token()` lee la fila en cada llamada y renueva si el access token vence en 5 minutos o menos (`POST <api host>/oauth/v2/refresh` con `{client_id, refresh_token}`).
- El refresh token es de **un solo uso**: dentro del proceso las renovaciones van con un lock; entre procesos, el par nuevo se guarda con un compare-and-set sobre `refresh_token_cifrado` (`update ... where refresh_token_cifrado = <el gastado>`). Quien pierde relee la fila y usa lo que guardó el otro; lo mismo si Clover rechaza un refresh token que otro proceso acaba de gastar.
- Si Clover **rechaza** la renovación (o los tokens no se pueden descifrar con la clave actual): `habilitado = false` y `TerminalUnavailable("Reconectá Clover desde Configuración")`. Si Clover no responde (red, 5xx) solo se informa el error y se reintenta en la próxima llamada.
- Los tokens, el secreto y los códigos nunca se loguean ni van a la auditoría.

**Adaptador** (`cloud_terminal.py`)

- Headers en cada llamada: `Authorization: Bearer`, `X-Clover-Device-Id` (`device_id` de la fila), `X-POS-Id` (`pos_id` de la fila o `CLOVER_POS_ID`), `User-Agent: MundoUniformePOS/<versión>`, `X-Clover-Timeout`; en los POST de cobro y reembolso, `Idempotency-Key` (cobro: el `external_payment_id`; reembolso: `refund-<payment_id>-<centavos|full>`). Cliente `httpx` propio, HTTP/1.1.

| Operación | Llamada | Timeout (Clover / HTTP) |
|---|---|---|
| `charge` | `POST /v1/payments` `{amount (centavos), externalPaymentId, final: true}` | 120 s / 150 s |
| `find_by_external_id` | `GET /v1/payments/external/{id}` | 15 s / 25 s |
| `refund` | `POST /v1/payments/{id}/refunds` `{fullRefund: true}` o `{amount}` | 60 s / 75 s |
| `cancel_current` | `POST /v1/device/cancel` | 10 s / 15 s |
| `status` | `GET /v1/device/status` | 10 s / 15 s |
| `show_welcome` | `POST /v1/device/welcome` (los 4xx se ignoran) | 10 s / 15 s |
| `ping` | `GET /v1/device/ping` → `connected` (503 = ocupado = conectado) | — / 5 s |

| Respuesta | Cobro | Resto |
|---|---|---|
| 200 | `payment.result`: `SUCCESS` → aprobado; `FAIL` / `VOIDED` → rechazado; cualquier otro (o sin `payment`) → desconocido | resultado |
| 209 | cancelado | reembolso: fallido |
| 400 | `TerminalBadRequest` (no se cobró) | `TerminalBadRequest` |
| 401 | se renueva el token y se reintenta **una** vez (misma `Idempotency-Key`); si vuelve a fallar, `TerminalUnavailable` | igual |
| 503 | `TerminalBusy` (no se cobró) | `TerminalBusy` (reembolso) / ocupado |
| 500, 504, otros códigos, timeout, corte de red | **desconocido** → conciliación; nunca se reintenta el cobro | `TerminalUnavailable` (reembolso: desconocido) |

- `find_by_external_id` devuelve `None` **solo** ante un "no existe" definitivo (404, o 400 cuyo `message` dice "not found"); cualquier falla transitoria lanza `TerminalUnavailable`, porque el servicio rechaza un cobro vencido cuando el terminal contesta que no lo conoce. Clover no documenta cómo informa un pago inexistente: el test `test_unknown_external_id_is_a_definitive_not_found` de la suite de sandbox lo verifica.
- De la tarjeta solo se leen marca (`cardType`), últimos 4, `authCode` y `entryType`; las cuotas se buscan en cualquier clave `*installments*` / `*cuotas*` de la respuesta. La respuesta guardada no incluye `first6`, titular, tokens ni vencimiento, y nada del cuerpo se loguea.
- Sin serie de dispositivo no se envía nada (`TerminalBadRequest`: el cobro queda `rechazado`).

**Verificado en la documentación de Clover vs. supuesto**

- Verificado: hosts de OAuth por entorno (sandbox: `sandbox.dev.clover.com` / `apisandbox.dev.clover.com`; LATAM: `www.la.clover.com` / `api.la.clover.com`), cuerpos y respuesta de `/oauth/v2/token` y `/oauth/v2/refresh`, refresh token de un solo uso, rutas, headers, cuerpos, respuestas y códigos HTTP de las siete operaciones de arriba (base sandbox `https://apisandbox.dev.clover.com/connect`).
- Supuesto (confirmar en sandbox / con Fiserv): la base de Cloud Pay Display en producción LATAM (`https://api.la.clover.com/connect`, por eso existe `CLOVER_CONNECT_URL`); que las expiraciones vienen en segundos (se aceptan milisegundos); la forma del "pago no encontrado"; dónde vuelven las cuotas; que `VOIDED` equivale a no cobrado; y que Clover devuelve `state` y `merchant_id` juntos en el callback (`merchant_id` es opcional para nosotros).

---

### 🔎 Auditoría — `/api/v1/auditoria`

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/` | 🔒 | Lista la tabla `logs`, del más nuevo al más viejo (`created_at desc, id desc`) |

Query params (todos opcionales): `desde`, `hasta` (fechas locales de Argentina, ambas inclusivas), `evento` (<= 64), `entidad` (<= 64), `usuario_id` (UUID), `limit` (1..200, default 50), `offset` (>= 0, default 0).

```python
# AuditLogListResponse
{ items: [{ id, created_at, evento, entidad?, entidad_id?, descripcion?, estado?, payload_enviado?, respuesta_recibida?,
            usuario: { id, nombre } | null }],
  total: int }   # total exacto de los registros que cumplen los filtros
```

- `AuditoriaService.listar()` lee `logs` con `count="exact"` y busca los nombres en `perfiles` con una segunda consulta (`in_`), sin depender de una FK de `logs`.
- Los payloads pueden contener datos de negocio: por eso el visor es solo admin. Las contraseñas nunca se auditan.

---

## Discrepancias / Bugs Conocidos

| # | Módulo | Estado | Descripción |
|---|---|---|---|
| 1 | `reporte_service.py` | ✅ **Resuelto** | `obtener_top_productos()` consultaba `venta_items`/`variantes`. Corregido a `venta_detalle`/`producto_variantes`. |
| 2 | `venta_service.py` | ✅ **Resuelto** | `total_costo` ahora se calcula como suma de `costo_unitario × cantidad` y se persiste en `ventas`. |
| 3 | `venta_service.py`, `producto_service.py` | ✅ **Resuelto** | El descuento de stock no era atómico. Ahora `crear_venta()` y `update_stock()` usan funciones SQL (hoy `registrar_venta` y `registrar_ajuste_stock`) (una transacción, con bloqueo de filas). |
| 4 | `schemas/caja.py` | ✅ **Resuelto** | `CajaMovimientoResponse` migrado a Pydantic v2 `model_config`. Serialización de `creado_en→created_at` y `motivo→descripcion` verificada. |
| 5 | `schemas/productos.py` | ✅ **Aclarado** | El campo `color` SÍ existe en `producto_variantes`. El comentario era incorrecto. |
| 6 | `caja_service.py` | ✅ **Por diseño (confirmado)** | La caja es global: una única sesión abierta para todos los usuarios, garantizada por un índice único. |
| 7 | `endpoints/caja.py` | ✅ **Resuelto** | `POST /caja/apertura` tomaba `usuario_id` del body. Ahora usa `current_user.id` e ignora el del body. |
| 8 | `endpoints/caja.py` | ✅ **Resuelto** | `POST /caja/movimiento` ahora usa `CajaMovimientoResponse` (`descripcion`/`created_at`), igual que los listados. |
| 9 | `auth_deps.py` | ✅ **Resuelto** | El cache de tokens no tenía límite y duraba 5 min. Ahora es un `TTLCache` acotado (1024 entradas, 60 s) con `invalidate_user()` al cambiar rol o estado. Sigue siendo por proceso (no se comparte entre workers). |
| 10 | `productos` | ℹ️ Falta feature | No hay forma de asignar categorías a un producto vía API. |
| 11 | `venta_service.py` | ✅ **Resuelto** | `crear_venta()` confiaba en `precio_unitario` y en el total enviados por el cliente. Ahora los precios salen de la base (RPC `registrar_venta`) y hay idempotencia por header `Idempotency-Key`. |
| 12 | `caja_service.py` | ✅ **Resuelto** | El cierre usaba la RPC `finalizar_cierre_caja`, que tenía errores. Ahora usa `cerrar_caja`. |
| 13 | `venta_service.py`, `reporte_service.py` | ✅ **Resuelto** | "Hoy" usaba la fecha local del servidor y los reportes comparaban timestamps sin zona horaria. Ahora todo se calcula con la fecha local de Argentina. |
| 14 | `cliente_service.py` | ✅ **Resuelto** | El término de búsqueda se interpolaba sin sanear en el filtro `or=(...)` de PostgREST (inyección de filtros). |
| 15 | `reporte_service.py` | ✅ **Resuelto** | Los reportes agregaban en memoria con varias consultas, expuestas al tope de 1000 filas. Ahora son funciones SQL. |
| 16 | varios listados | ✅ **Resuelto** | PostgREST truncaba en 1000 filas sin avisar. `GET /productos/` y `GET /ventas/hoy` paginan internamente; `GET /clientes/` y `GET /caja/sesiones` aceptan `limit`/`offset`. |
| 17 | `caja_service.py` | ℹ️ Menor | `GET /caja/movimientos` y `GET /caja/sesiones/{id}/movimientos` no paginan: una sesión con más de 1000 movimientos se truncaría. |
| 18 | varios endpoints | ✅ **Resuelto** | Las escrituras de productos, variantes, stock y catálogos, y el historial de sesiones de caja, solo exigían sesión válida. Ahora son solo admin (ver "Matriz de roles"). |
| 19 | `endpoints/productos.py` | ✅ **Resuelto** | `precio_costo` se devolvía a cualquier usuario. Ahora solo lo ve un admin. |
| 20 | `auth_deps.py` | ✅ **Resuelto** | `perfiles.activo` no se consultaba: un usuario desactivado seguía operando. Ahora recibe 403 `Usuario inactivo`. |
| 21 | `endpoints/usuarios.py` | ✅ **Resuelto** | `PATCH /usuarios/{id}/rol` no validaba el rol, permitía que un admin se quitara su propio rol o dejara el sistema sin administradores, y no dejaba auditoría. No había forma de desactivar un usuario por API. |
| 22 | varios endpoints | ✅ **Resuelto** | Los ids UUID de la URL eran `str`: un valor mal formado llegaba a PostgREST (error `22P02`). Ahora se validan como `uuid.UUID` (422). |
| 23 | `usuario_service.py` | ℹ️ Menor | La verificación del último administrador activo no es atómica (lectura + escritura). |
| 24 | base de datos | ℹ️ Pendiente | Las funciones `crear_venta`, `ajustar_stock` y `finalizar_cierre_caja` quedaron obsoletas y siguen en la base hasta que se haga el `DROP`. |
| 25 | `pago_service.py` | ℹ️ Pendiente (etapa D) | Anular o devolver una venta cobrada con el terminal todavía **no reembolsa** en el dispositivo: `anular_venta` / `registrar_devolucion` solo actualizan la base. |
| 26 | `integrations/payment_terminal` | ✅ **Resuelto** (etapa C) | Existe el adaptador `CloverCloudTerminal` (`PAYMENT_TERMINAL=clover`). El estado de `FakeTerminal` sigue siendo por proceso (un solo worker en desarrollo). |
| 27 | `integrations/clover` | ℹ️ Pendiente | Falta validarlo contra el sandbox real (suite `clover_sandbox`). La URL cloud de producción LATAM es un supuesto (`CLOVER_CONNECT_URL`). No se usa el endpoint `/oauth/v2/recovery`: si se pierde un refresh token hay que reconectar. |
| 28 | `integrations/clover` | ℹ️ Menor | El `state` de OAuth no es de un solo uso (no hay tabla): es válido 10 minutos; el código de Clover sí es de un solo uso. `GET /integraciones/terminal` hace un ping a Clover en cada consulta (sin cache). Un 401 persistente durante un cobro lo deja `indeterminado` hasta que se reconecte y se concilie. |

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

# Suite opcional contra el sandbox de Clover (usa el .env real; no corre por defecto ni en CI)
CLOVER_SANDBOX_LIVE=1 pytest -m clover_sandbox

# Lint
ruff check .
ruff check --fix .   # aplica solo los arreglos seguros

# Regenerar openapi.json (sin red; sirven valores ficticios)
SUPABASE_URL=https://example.supabase.co SUPABASE_KEY=sb_secret_dummy python scripts/export_openapi.py
```

CI (`.github/workflows/ci.yml`) ejecuta `ruff check .` y `pytest -q` en cada push y pull request.

---

## Convenciones del Código

1. **Sin ORM:** Todas las queries usan `supabase-py` directamente contra las tablas/RPCs.
2. **Servicios estáticos:** Los servicios son clases con `@staticmethod` (no hay instancias). Excepción: `PagoService` recibe sus puertos por constructor (terminal y persistencia) y se arma en `app/api/deps.py`; no importa `supabase`.
3. **`model_dump(exclude_none=True)`** en Creates para no enviar campos nulos a Supabase.
4. **`model_dump(exclude_unset=True)`** en Updates para solo enviar los campos que el cliente mandó.
5. **`mode='json'`** en la creación de variantes para serializar UUID4 como string.
6. **Errores de negocio:** los de dinero y stock los lanza la base con códigos `MU00x` (llegan como `APIError`); los de caja detectados en Python se lanzan como `CajaError`. Ambos se capturan globalmente en `main.py`.
7. **Sin fugas de detalles internos:** no devolver `str(e)` de excepciones no controladas; ver "Health y manejo de errores".
8. **Dinero y stock en la base:** toda operación que mueva plata o stock se hace en una función SQL atómica (ver "Funciones de base de datos"), nunca con lecturas y escrituras separadas desde Python. Los precios nunca se toman del cliente.
9. **Listados completos:** si un endpoint debe devolver todo, usar `fetch_all()` (`app/core/db_utils.py`) con un `.order()` determinístico; si no, exponer `limit`/`offset`.
10. **Entrada vs. respuesta:** las validaciones (longitudes, rangos, `Literal`, `EmailStr`) van en los modelos de entrada; los de respuesta quedan sin restricciones.
11. **Zona horaria:** los cálculos de "día" usan `app/core/timeutils.py` (Argentina), nunca la hora local del servidor.
12. **TDD:** todo comportamiento nuevo lleva su test en `tests/` (los servicios o el cliente `supabase` se reemplazan con mocks o con `tests/fakes.py::FakeSupabase`; `get_current_user` con `app.dependency_overrides`).
13. **Autorización:** toda ruta nueva se agrega a la "Matriz de roles" y a `tests/test_authz.py`. Lo que solo puede hacer un admin usa `Depends(RoleChecker(["admin"]))`; nunca se confía en que el frontend oculte la opción.
14. **Ids UUID en la URL:** tiparlos como `uuid.UUID` y pasar `str(id)` al servicio.
15. **Auditoría:** toda escritura llama a `audit()` con un `AuditEvent` (o a `record_audit()` si corre fuera de un request); no se usa `background_tasks.add_task(LogService...)` directo. Un evento nuevo se agrega al `Literal` y a esta documentación.
16. **Respuestas tipadas:** todo endpoint declara `response_model` (también los DELETE: `OkResponse` / `MessageResponse` de `schemas/common.py`); no se devuelven dicts sueltos ni `JSONResponse` a mano.
17. **Mensajes 404 en español** y consistentes: `Producto no encontrado`, `Variante no encontrada`, `Cliente no encontrado`, `Marca no encontrada`, `Categoría no encontrada`, `Usuario no encontrado`.
18. **OpenAPI versionado:** al cambiar rutas o modelos, regenerar `openapi.json` con `python scripts/export_openapi.py`; `tests/test_openapi.py` falla si quedó desactualizado (así lo detecta CI).
