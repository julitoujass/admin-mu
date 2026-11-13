import os

# `CLOVER_SANDBOX_LIVE=1 pytest -m clover_sandbox` runs the optional live suite with the real `.env`.
LIVE_SANDBOX = os.environ.get("CLOVER_SANDBOX_LIVE") == "1"

if not LIVE_SANDBOX:
    # Dummy settings must be in place before the app (and its Supabase client) is imported.
    # Environment variables take precedence over any local .env file.
    os.environ["SUPABASE_URL"] = "http://localhost:54321"
    os.environ["SUPABASE_KEY"] = "test-key"
    os.environ["ENVIRONMENT"] = "test"
    os.environ["CORS_ORIGINS"] = "http://localhost:3000, https://pos.example.com"
    os.environ["LOG_LEVEL"] = "WARNING"
    os.environ["PAYMENT_TERMINAL"] = "fake"
    os.environ["PAYMENT_FAKE_DELAY_SECONDS"] = "0"
    # No background sweep of terminal charges while testing.
    os.environ["PAYMENT_RECONCILE_INTERVAL_SECONDS"] = "0"
    # Clover: fixed dummy values so nothing is ever taken from a local .env.
    os.environ["CLOVER_ENV"] = "sandbox"
    os.environ["CLOVER_APP_ID"] = "TESTAPPID"
    os.environ["CLOVER_APP_SECRET"] = "test-app-secret"
    os.environ["CLOVER_TOKEN_KEY"] = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
    os.environ["CLOVER_REDIRECT_URI"] = "http://localhost:8001/api/v1/integraciones/clover/callback"
    os.environ["CLOVER_OAUTH_URL"] = ""
    os.environ["CLOVER_API_URL"] = ""
    os.environ["CLOVER_CONNECT_URL"] = ""
    os.environ["CLOVER_POS_ID"] = "mundo-uniforme-pos"
    os.environ["FRONTEND_URL"] = "http://localhost:3000"

from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api import auth_deps  # noqa: E402
from app.api.auth_deps import AppUser, get_current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.services import log_service  # noqa: E402


@pytest.fixture(autouse=True)
def _no_audit_log_io(monkeypatch):
    """The audit log runs as a background task; keep it away from the network."""
    monkeypatch.setattr(log_service, "supabase", MagicMock())


@pytest.fixture
def client():
    """Unauthenticated client. Server errors are returned as responses, not raised."""
    auth_deps._TOKEN_CACHE.clear()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    auth_deps._TOKEN_CACHE.clear()


@pytest.fixture
def auth_client(client):
    """Client whose requests are authenticated as an admin user (no Supabase call)."""
    app.dependency_overrides[get_current_user] = lambda: AppUser(
        id="00000000-0000-0000-0000-000000000001", email="admin@example.com", rol="admin"
    )
    return client


@pytest.fixture
def employee_client(client):
    """Client whose requests are authenticated as a non-admin (`empleado`) user."""
    app.dependency_overrides[get_current_user] = lambda: AppUser(
        id="00000000-0000-0000-0000-000000000002", email="empleado@example.com", rol="empleado"
    )
    return client
