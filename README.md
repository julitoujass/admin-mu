# admin-mu

API backend del sistema POS de **Mundo Uniforme**. Está construida con FastAPI y usa Supabase (PostgreSQL + Auth) a través de `supabase-py`, sin ORM. El frontend que la consume es `pos-mu` (Next.js).

La documentación completa (arquitectura, tablas, endpoints, convenciones y limitaciones conocidas) está en [agents.md](agents.md).

## Requisitos

- Python 3.12
- Un proyecto de Supabase y su clave secreta (equivalente a `service_role`)

## Instalación

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements-dev.txt
```

`requirements.txt` contiene solo las dependencias de ejecución (incluye `httpx` y `cryptography`, que usa el adaptador de Clover); `requirements-dev.txt` las incluye y agrega pytest y ruff.

## Variables de entorno

Se leen del entorno o de un archivo `.env` en la raíz del proyecto (no se versiona). Las variables del entorno tienen prioridad sobre `.env`.

| Variable | Requerida | Default | Descripción |
|---|---|---|---|
| `SUPABASE_URL` | Sí | — | URL del proyecto de Supabase. No puede estar vacía. |
| `SUPABASE_KEY` | Sí | — | Clave secreta del proyecto (omite RLS). No puede estar vacía. Nunca debe exponerse al navegador ni versionarse. |
| `ENVIRONMENT` | No | `development` | Nombre del entorno (`development`, `production`, etc.). |
| `CORS_ORIGINS` | No | `http://localhost:3000` | Orígenes permitidos por CORS, separados por coma. |
| `LOG_LEVEL` | No | `INFO` | Nivel de logging (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `PAYMENT_TERMINAL` | No | `fake` | Adaptador del terminal de pago: `fake` (simulado) o `clover` (Clover Cloud Pay Display). Con `clover` son obligatorias `CLOVER_APP_ID`, `CLOVER_APP_SECRET` y `CLOVER_TOKEN_KEY`. |
| `CLOVER_ENV` | No | `sandbox` | `sandbox` o `production` (región LATAM). Define los hosts de Clover. |
| `CLOVER_APP_ID` | Con `clover` | — | App ID de la app en el portal de desarrolladores de Clover. |
| `CLOVER_APP_SECRET` | Con `clover` | — | App Secret. Secreto: nunca se versiona ni se loguea. |
| `CLOVER_TOKEN_KEY` | Con `clover` | — | Clave Fernet que cifra los tokens OAuth guardados en la base (y firma el `state` de OAuth). Secreto. Ver "Clover" más abajo para generarla. |
| `CLOVER_REDIRECT_URI` | No | `http://localhost:8001/api/v1/integraciones/clover/callback` | URL del callback de OAuth. Debe apuntar a este backend y estar registrada en la app de Clover. |
| `CLOVER_OAUTH_URL` | No | según `CLOVER_ENV` | Host de la página de autorización (`https://sandbox.dev.clover.com` / `https://www.la.clover.com`). |
| `CLOVER_API_URL` | No | según `CLOVER_ENV` | Host del canje y la renovación de tokens (`https://apisandbox.dev.clover.com` / `https://api.la.clover.com`). |
| `CLOVER_CONNECT_URL` | No | `<CLOVER_API_URL>/connect` | Base de Cloud Pay Display. La de producción LATAM no está documentada por Clover: confirmarla con Fiserv y definirla acá. |
| `CLOVER_POS_ID` | No | `mundo-uniforme-pos` | Header `X-POS-Id` cuando la integración no tiene `pos_id` guardado. |
| `FRONTEND_URL` | No | `http://localhost:3000` | URL del POS: a dónde vuelve el navegador después del callback de OAuth. |
| `PAYMENT_FAKE_DELAY_SECONDS` | No | `3` | Segundos que el terminal simulado espera antes de aprobar. |
| `PAYMENT_RECONCILE_INTERVAL_SECONDS` | No | `60` | Cada cuánto corre el barrido de cobros sin resolver (también al iniciar). `0` lo desactiva. |
| `PAYMENT_STALE_SECONDS` | No | `180` | Antigüedad a partir de la cual un cobro `pendiente`/`enviado` se considera huérfano. |
| `PAYMENT_RECONCILE_MAX_ATTEMPTS` | No | `10` | Intentos del barrido por cobro antes de dejarlo para revisión del admin. |
| `PAYMENT_RECONCILE_BACKOFF` | No | `2,5,10` | Esperas (segundos) entre las consultas de la conciliación inmediata. |

## Clover (cobros con tarjeta / QR en el Clover Mini)

Pasos para dejar funcionando el **sandbox**:

1. Generar la clave que cifra los tokens y guardarla en `.env` como `CLOVER_TOKEN_KEY` (si se pierde o se cambia, hay que volver a conectar la cuenta):

   ```bash
   .venv\Scripts\python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

2. En `.env`: `PAYMENT_TERMINAL=clover`, `CLOVER_ENV=sandbox`, `CLOVER_APP_ID` y `CLOVER_APP_SECRET` (los de la app en el portal de desarrolladores de Clover).
3. En la configuración de la app en Clover (REST Configuration), registrar como Site URL / URL de redirección la de este backend: `http://localhost:8001/api/v1/integraciones/clover/callback`. Tiene que coincidir con `CLOVER_REDIRECT_URI` y con el puerto en el que corre uvicorn (`uvicorn app.main:app --reload --port 8001`); si se usa otro puerto o dominio, cambiar ambas.
4. Reiniciar el backend. Si falta alguna variable, no arranca y dice cuál.
5. En el POS, como admin: **Configuración → Terminal de pago → Conectar Clover**. El navegador va a Clover, se autoriza la app y vuelve a `/dashboard/settings?clover=ok` (o `?clover=error&motivo=...`).
6. Cargar la **serie del dispositivo** (la que muestra el Clover Mini; es el header `X-Clover-Device-Id`).
7. **Probar conexión** (`GET /api/v1/integraciones/terminal` → `conectado: true`) y recién entonces **habilitar** la integración.

Si Clover rechaza la renovación del token, la integración se deshabilita sola y hay que repetir los pasos 5 y 7. Para producción: `CLOVER_ENV=production`, las credenciales de producción, `CLOVER_REDIRECT_URI` y `FRONTEND_URL` con HTTPS, y `CLOVER_CONNECT_URL` con la URL que confirme Fiserv.

Suite opcional contra el sandbox (no corre en CI ni en `pytest -q`; solo lee: ping, estado y una búsqueda): `CLOVER_SANDBOX_LIVE=1 pytest -m clover_sandbox`. Usa el `.env` real, con la cuenta conectada y la serie cargada.

## Ejecución

```bash
uvicorn app.main:app --reload
```

- API: http://127.0.0.1:8000
- Documentación interactiva: http://127.0.0.1:8000/docs
- Health: `GET /health` (proceso vivo) y `GET /health/ready` (verifica la conexión a la base)

## Tests y lint

```bash
pytest -q        # tests (no usan la red ni requieren un .env real)
ruff check .     # lint

# Regenera openapi.json (esquema versionado; sirven valores ficticios, sin red)
SUPABASE_URL=https://example.supabase.co SUPABASE_KEY=sb_secret_dummy python scripts/export_openapi.py
```

Un test falla si `openapi.json` quedó desactualizado respecto de la API. Los mismos comandos corren en CI (`.github/workflows/ci.yml`) en cada push y pull request.
