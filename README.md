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

`requirements.txt` contiene solo las dependencias de ejecución; `requirements-dev.txt` las incluye y agrega pytest, httpx y ruff.

## Variables de entorno

Se leen del entorno o de un archivo `.env` en la raíz del proyecto (no se versiona). Las variables del entorno tienen prioridad sobre `.env`.

| Variable | Requerida | Default | Descripción |
|---|---|---|---|
| `SUPABASE_URL` | Sí | — | URL del proyecto de Supabase. No puede estar vacía. |
| `SUPABASE_KEY` | Sí | — | Clave secreta del proyecto (omite RLS). No puede estar vacía. Nunca debe exponerse al navegador ni versionarse. |
| `ENVIRONMENT` | No | `development` | Nombre del entorno (`development`, `production`, etc.). |
| `CORS_ORIGINS` | No | `http://localhost:3000` | Orígenes permitidos por CORS, separados por coma. |
| `LOG_LEVEL` | No | `INFO` | Nivel de logging (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `PAYMENT_TERMINAL` | No | `fake` | Adaptador del terminal de pago: `fake` (simulado) o `clover` (todavía no implementado). |
| `PAYMENT_FAKE_DELAY_SECONDS` | No | `3` | Segundos que el terminal simulado espera antes de aprobar. |
| `PAYMENT_RECONCILE_INTERVAL_SECONDS` | No | `60` | Cada cuánto corre el barrido de cobros sin resolver (también al iniciar). `0` lo desactiva. |
| `PAYMENT_STALE_SECONDS` | No | `180` | Antigüedad a partir de la cual un cobro `pendiente`/`enviado` se considera huérfano. |
| `PAYMENT_RECONCILE_MAX_ATTEMPTS` | No | `10` | Intentos del barrido por cobro antes de dejarlo para revisión del admin. |
| `PAYMENT_RECONCILE_BACKOFF` | No | `2,5,10` | Esperas (segundos) entre las consultas de la conciliación inmediata. |

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
