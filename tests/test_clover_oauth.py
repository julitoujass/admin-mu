"""Clover OAuth: signed state, token endpoints, connect / callback / disconnect and their HTTP contract."""

import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import ValidationError

from app.api import deps
from app.api.auth_deps import AppUser
from app.api.deps import get_clover_connection
from app.core.config import Settings
from app.core.exceptions import PagoError
from app.integrations.clover.connection import CloverConnection
from app.integrations.clover.oauth import (
    CloverOAuthClient,
    CloverOAuthRejected,
    CloverOAuthUnavailable,
    InvalidState,
    sign_state,
    verify_state,
)
from app.main import app
from tests.fakes_clover import CIPHER, NOW, TOKEN_KEY, InMemoryCloverStore

API = "/api/v1/integraciones/clover"
ADMIN_ID = "00000000-0000-0000-0000-000000000001"
ADMIN = AppUser(id=ADMIN_ID, email="admin@example.com", rol="admin")
REDIRECT_URI = "http://localhost:8001/api/v1/integraciones/clover/callback"
SETTINGS_URL = "http://localhost:3000/dashboard/settings"
TOKEN_RESPONSE = {
    "access_token": "new-access",
    "access_token_expiration": 1795000000,
    "refresh_token": "new-refresh",
    "refresh_token_expiration": 1826000000,
}


# --- state -----------------------------------------------------------------------------------------


def test_state_round_trip_binds_the_user():
    state = sign_state(ADMIN_ID, TOKEN_KEY, NOW)

    assert verify_state(state, TOKEN_KEY, NOW + timedelta(minutes=9, seconds=59)) == ADMIN_ID
    assert ADMIN_ID not in state  # opaque in the URL (encoded), and no secret inside
    assert sign_state(ADMIN_ID, TOKEN_KEY, NOW) != state  # nonce


def test_state_expires_after_ten_minutes():
    state = sign_state(ADMIN_ID, TOKEN_KEY, NOW)

    with pytest.raises(InvalidState) as error:
        verify_state(state, TOKEN_KEY, NOW + timedelta(minutes=10))
    assert error.value.reason == "state_expirado"


@pytest.mark.parametrize("bad", [None, "", "abc", "a.b.c", "!!!.???", "e30.e30"])
def test_malformed_state_is_invalid(bad):
    with pytest.raises(InvalidState) as error:
        verify_state(bad, TOKEN_KEY, NOW)
    assert error.value.reason == "state_invalido"


def test_tampered_state_is_invalid():
    payload, signature = sign_state(ADMIN_ID, TOKEN_KEY, NOW).split(".")
    other_payload = sign_state("00000000-0000-0000-0000-000000000009", TOKEN_KEY, NOW).split(".")[0]

    for forged in (f"{other_payload}.{signature}", f"{payload}.{signature[:-2]}AA"):
        with pytest.raises(InvalidState) as error:
            verify_state(forged, TOKEN_KEY, NOW)
        assert error.value.reason == "state_invalido"


def test_state_signed_with_another_key_is_invalid():
    state = sign_state(ADMIN_ID, "another-key", NOW)

    with pytest.raises(InvalidState):
        verify_state(state, TOKEN_KEY, NOW)


# --- token endpoints ---------------------------------------------------------------------------------


class TokenServer:
    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[httpx.Request] = []
        self.client = CloverOAuthClient(
            oauth_url="https://sandbox.dev.clover.com",
            api_url="https://apisandbox.dev.clover.com/",
            app_id="TESTAPPID",
            app_secret="test-app-secret",
            transport=httpx.MockTransport(self._handle),
        )

    def _handle(self, request):
        self.requests.append(request)
        entry = self.script.pop(0)
        if isinstance(entry, Exception):
            raise entry
        status, body = entry
        return httpx.Response(status, json=body)


def test_authorize_url():
    url = TokenServer().client.authorize_url(REDIRECT_URI, "the.state")

    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://sandbox.dev.clover.com/oauth/v2/authorize"
    assert parse_qs(parts.query) == {
        "client_id": ["TESTAPPID"],
        "redirect_uri": [REDIRECT_URI],
        "response_type": ["code"],
        "state": ["the.state"],
    }
    assert "test-app-secret" not in url


def test_exchange_code_posts_json_and_parses_the_tokens():
    server = TokenServer((200, TOKEN_RESPONSE))

    tokens = server.client.exchange_code("the-code")

    [request] = server.requests
    assert (request.method, str(request.url)) == ("POST", "https://apisandbox.dev.clover.com/oauth/v2/token")
    assert json.loads(request.content) == {
        "client_id": "TESTAPPID",
        "client_secret": "test-app-secret",
        "code": "the-code",
    }
    assert (tokens.access_token, tokens.refresh_token) == ("new-access", "new-refresh")
    assert tokens.access_expires_at == datetime.fromtimestamp(1795000000, tz=timezone.utc)


def test_refresh_posts_the_refresh_token_without_the_secret():
    server = TokenServer((200, {**TOKEN_RESPONSE, "access_token_expiration": 1795000000000}))

    tokens = server.client.refresh("old-refresh")

    [request] = server.requests
    assert str(request.url) == "https://apisandbox.dev.clover.com/oauth/v2/refresh"
    assert json.loads(request.content) == {"client_id": "TESTAPPID", "refresh_token": "old-refresh"}
    # An expiration in milliseconds is understood too.
    assert tokens.access_expires_at == datetime.fromtimestamp(1795000000, tz=timezone.utc)


@pytest.mark.parametrize(
    ("response", "error"),
    [
        ((401, {"message": "Unauthorized"}), CloverOAuthRejected),
        ((400, {"message": "Bad code"}), CloverOAuthRejected),
        ((200, {"access_token": "only-this"}), CloverOAuthRejected),
        ((200, {**TOKEN_RESPONSE, "refresh_token": ""}), CloverOAuthRejected),
        ((500, {}), CloverOAuthUnavailable),
        ((503, {}), CloverOAuthUnavailable),
        (httpx.ConnectError("down"), CloverOAuthUnavailable),
        (httpx.ReadTimeout("slow"), CloverOAuthUnavailable),
    ],
)
def test_token_endpoint_failures(response, error, caplog):
    caplog.set_level(logging.DEBUG)
    server = TokenServer(response)

    with pytest.raises(error):
        server.client.exchange_code("the-code")

    for secret in ("the-code", "test-app-secret", "only-this"):
        assert secret not in caplog.text


# --- connection (connect / callback / disconnect) ------------------------------------------------------


class Flow:
    def __init__(self, *token_script, is_admin=True, store=None):
        self.server = TokenServer(*token_script)
        self.store = store or InMemoryCloverStore(access=None, refresh=None, merchant_id=None, habilitado=False)
        self.audits = []
        self.now = NOW
        self.admin_checks = []
        self.connection = CloverConnection(
            frontend_url="http://localhost:3000/",
            audit=lambda usuario_id, evento, **kwargs: self.audits.append((usuario_id, evento, kwargs)),
            oauth=self.server.client,
            store=self.store,
            cipher=CIPHER,
            token_key=TOKEN_KEY,
            redirect_uri=REDIRECT_URI,
            is_admin=lambda user_id: self.admin_checks.append(user_id) or is_admin,
            now=lambda: self.now,
        )

    def state(self):
        url = self.connection.authorize_url(ADMIN)
        return parse_qs(urlsplit(url).query)["state"][0]


def test_authorize_url_carries_a_state_bound_to_the_admin():
    flow = Flow()

    url = flow.connection.authorize_url(ADMIN)

    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://sandbox.dev.clover.com/oauth/v2/authorize?")
    assert (query["client_id"], query["redirect_uri"]) == (["TESTAPPID"], [REDIRECT_URI])
    assert verify_state(query["state"][0], TOKEN_KEY, NOW) == ADMIN_ID


def test_callback_stores_the_encrypted_tokens_and_audits():
    flow = Flow((200, TOKEN_RESPONSE))

    target = flow.connection.handle_callback("the-code", "M123ABC", flow.state())

    assert target == f"{SETTINGS_URL}?clover=ok"
    row = flow.store.row
    assert (flow.store.access, flow.store.refresh) == ("new-access", "new-refresh")
    assert "new-access" not in row["access_token_cifrado"] and "new-refresh" not in row["refresh_token_cifrado"]
    assert row["access_expira_at"] == datetime.fromtimestamp(1795000000, tz=timezone.utc).isoformat()
    assert (row["merchant_id"], row["proveedor"], row["updated_by"]) == ("M123ABC", "clover", ADMIN_ID)
    assert row["habilitado"] is False  # enabling stays an explicit admin decision
    assert flow.admin_checks == [ADMIN_ID]
    assert flow.audits == [
        (ADMIN_ID, "CLOVER_CONNECTED", {"entidad": "integracion_terminal", "entidad_id": 1, "payload": {"merchant_id": "M123ABC"}})
    ]
    assert "new-access" not in repr(flow.audits) and "the-code" not in repr(flow.audits)


def test_callback_without_merchant_id_still_connects():
    flow = Flow((200, TOKEN_RESPONSE))

    assert flow.connection.handle_callback("the-code", None, flow.state()) == f"{SETTINGS_URL}?clover=ok"
    assert flow.store.row["merchant_id"] is None


def error_of(target):
    parts = urlsplit(target)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == SETTINGS_URL
    query = parse_qs(parts.query)
    assert query["clover"] == ["error"]
    return query["motivo"][0]


@pytest.mark.parametrize(
    ("token_response", "motivo"),
    [
        ((401, {"message": "invalid code"}), "codigo_rechazado"),
        ((500, {}), "clover_no_disponible"),
        (httpx.ConnectError("down"), "clover_no_disponible"),
    ],
)
def test_callback_token_exchange_errors(token_response, motivo, caplog):
    caplog.set_level(logging.DEBUG)
    flow = Flow(token_response)

    target = flow.connection.handle_callback("the-code", "M123", flow.state())

    assert error_of(target) == motivo
    assert flow.store.row["access_token_cifrado"] is None
    assert flow.audits == []
    assert "the-code" not in target and "the-code" not in caplog.text


def test_callback_rejects_a_bad_expired_or_missing_state_before_calling_clover():
    flow = Flow()
    state = flow.state()

    assert error_of(flow.connection.handle_callback("the-code", "M123", None)) == "state_invalido"
    assert error_of(flow.connection.handle_callback("the-code", "M123", state + "x")) == "state_invalido"
    flow.now = NOW + timedelta(minutes=11)
    assert error_of(flow.connection.handle_callback("the-code", "M123", state)) == "state_expirado"
    assert flow.server.requests == []
    assert flow.store.row["access_token_cifrado"] is None


@pytest.mark.parametrize(
    ("code", "merchant_id"),
    [(None, "M123"), ("", "M123"), ("bad code!", "M123"), ("the-code", "../../etc"), ("the-code", "M" * 33)],
)
def test_callback_rejects_malformed_parameters(code, merchant_id):
    flow = Flow()

    assert error_of(flow.connection.handle_callback(code, merchant_id, flow.state())) == "parametros"
    assert flow.server.requests == []


def test_callback_checks_the_user_is_still_an_admin():
    flow = Flow(is_admin=False)

    assert error_of(flow.connection.handle_callback("the-code", "M123", flow.state())) == "sin_permiso"
    assert flow.server.requests == []


def test_callback_never_raises_and_never_leaks(caplog):
    flow = Flow((200, TOKEN_RESPONSE))
    flow.store.save_connection = lambda *args: (_ for _ in ()).throw(RuntimeError("db down: new-access"))

    target = flow.connection.handle_callback("the-code", "M123", flow.state())

    assert error_of(target) == "error_interno"
    assert "new-access" not in target


def test_callback_without_the_integration_row():
    flow = Flow((200, TOKEN_RESPONSE))
    flow.store.save_connection = lambda *args: None

    assert error_of(flow.connection.handle_callback("the-code", "M123", flow.state())) == "sin_integracion"
    assert flow.audits == []


def test_disconnect_clears_the_tokens_disables_and_audits():
    flow = Flow(store=InMemoryCloverStore())

    result = flow.connection.disconnect(ADMIN)

    assert result == {"conectado_oauth": False, "habilitado": False}
    row = flow.store.row
    assert (row["access_token_cifrado"], row["refresh_token_cifrado"], row["access_expira_at"]) == (None, None, None)
    assert (row["merchant_id"], row["habilitado"], row["updated_by"]) == (None, False, ADMIN_ID)
    assert [(user, event) for user, event, _ in flow.audits] == [(ADMIN_ID, "CLOVER_DISCONNECTED")]


def test_when_clover_is_not_the_configured_terminal_everything_refuses():
    connection = CloverConnection(frontend_url="http://localhost:3000", audit=lambda *a, **k: None)

    for call in (connection.authorize_url, connection.disconnect):
        with pytest.raises(PagoError) as error:
            call(ADMIN)
        assert error.value.status_code == 409
    assert error_of(connection.handle_callback("the-code", "M123", "x.y")) == "no_configurado"


# --- HTTP contract -----------------------------------------------------------------------------------


@pytest.fixture
def flow(client):
    def install(*token_script, **options):
        installed = Flow(*token_script, **options)
        app.dependency_overrides[get_clover_connection] = lambda: installed.connection
        return installed

    return install


def test_conectar_and_desconectar_need_a_token(client, flow):
    flow()

    assert client.get(f"{API}/conectar").status_code in (401, 403)
    assert client.post(f"{API}/desconectar").status_code in (401, 403)


def test_conectar_and_desconectar_are_admin_only(employee_client, flow):
    installed = flow(store=InMemoryCloverStore())

    assert employee_client.get(f"{API}/conectar").status_code == 403
    assert employee_client.post(f"{API}/desconectar").status_code == 403
    assert installed.store.row["access_token_cifrado"] is not None


def test_conectar_returns_the_authorize_url(auth_client, flow):
    flow()

    response = auth_client.get(f"{API}/conectar")

    assert response.status_code == 200
    assert set(response.json()) == {"authorize_url"}
    query = parse_qs(urlsplit(response.json()["authorize_url"]).query)
    assert verify_state(query["state"][0], TOKEN_KEY, NOW) == ADMIN_ID


def test_callback_needs_no_bearer_token_and_redirects_to_the_pos(client, flow):
    installed = flow((200, TOKEN_RESPONSE))

    response = client.get(
        f"{API}/callback",
        params={"code": "the-code", "merchant_id": "M123", "state": installed.state(), "client_id": "TESTAPPID"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == f"{SETTINGS_URL}?clover=ok"
    assert response.headers["cache-control"] == "no-store"
    assert installed.store.access == "new-access"


@pytest.mark.parametrize(
    "params",
    [{}, {"code": "the-code"}, {"code": "the-code", "state": "forged.state"}, {"state": "x" * 2000}],
    ids=["nothing", "no-state", "forged", "oversized"],
)
def test_callback_errors_also_redirect_without_secrets(client, flow, params):
    installed = flow()

    response = client.get(f"{API}/callback", params=params, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(f"{SETTINGS_URL}?clover=error&motivo=")
    assert "the-code" not in location
    assert installed.server.requests == []


def test_desconectar(auth_client, flow):
    installed = flow(store=InMemoryCloverStore())

    response = auth_client.post(f"{API}/desconectar")

    assert response.status_code == 200
    assert response.json() == {"conectado_oauth": False, "habilitado": False}
    assert installed.store.row["refresh_token_cifrado"] is None


def test_with_the_fake_terminal_the_real_wiring_refuses(auth_client, client):
    deps.get_clover_connection.cache_clear()

    assert auth_client.get(f"{API}/conectar").status_code == 409
    assert auth_client.get(f"{API}/conectar").json() == {
        "detail": "Clover no es el terminal configurado (PAYMENT_TERMINAL)"
    }
    response = client.get(f"{API}/callback", params={"code": "c", "state": "s.s"}, follow_redirects=False)
    assert response.headers["location"] == f"{SETTINGS_URL}?clover=error&motivo=no_configurado"
    deps.get_clover_connection.cache_clear()


def test_real_wiring_with_clover_builds_a_working_connection(monkeypatch):
    from app.integrations.clover import wiring

    monkeypatch.setattr(deps.settings, "PAYMENT_TERMINAL", "clover")
    deps.get_clover_connection.cache_clear()
    try:
        connection = deps.get_clover_connection()
        assert connection.configured
        url = connection.authorize_url(ADMIN)
        assert url.startswith("https://sandbox.dev.clover.com/oauth/v2/authorize?client_id=TESTAPPID&")
        assert wiring.USER_AGENT == "MundoUniformePOS/1.0.0"
    finally:
        deps.get_clover_connection.cache_clear()


def test_is_active_admin_reads_the_profile(monkeypatch):
    profiles = {"a": ("admin", True), "b": ("empleado", True), "c": ("admin", False)}
    monkeypatch.setattr(deps.auth_deps, "_load_profile", lambda user_id: profiles[user_id])

    assert deps._is_active_admin("a") is True
    assert deps._is_active_admin("b") is False
    assert deps._is_active_admin("c") is False
    assert deps._is_active_admin("missing") is False  # lookup failure = not an admin


# --- settings ------------------------------------------------------------------------------------------


def make_settings(**overrides):
    base = {"SUPABASE_URL": "http://localhost", "SUPABASE_KEY": "key", "_env_file": None}
    return Settings(**{**base, **overrides})


def test_clover_settings_defaults_for_the_sandbox():
    settings = make_settings()

    assert (settings.PAYMENT_TERMINAL, settings.CLOVER_ENV) == ("fake", "sandbox")
    assert settings.clover_oauth_url == "https://sandbox.dev.clover.com"
    assert settings.clover_api_url == "https://apisandbox.dev.clover.com"
    assert settings.clover_connect_url == "https://apisandbox.dev.clover.com/connect"
    assert settings.CLOVER_REDIRECT_URI == REDIRECT_URI
    assert settings.FRONTEND_URL == "http://localhost:3000"
    assert settings.CLOVER_POS_ID == "mundo-uniforme-pos"
    assert settings.clover_configured is False


def test_clover_production_is_latam_and_urls_can_be_overridden():
    settings = make_settings(CLOVER_ENV="production")
    assert settings.clover_oauth_url == "https://www.la.clover.com"
    assert settings.clover_api_url == "https://api.la.clover.com"
    assert settings.clover_connect_url == "https://api.la.clover.com/connect"

    settings = make_settings(
        CLOVER_ENV="production",
        CLOVER_CONNECT_URL="https://cloud.example.com/connect/",
        CLOVER_API_URL="https://api.example.com/",
        CLOVER_OAUTH_URL=" https://www.example.com ",
        FRONTEND_URL="https://pos.example.com/",
    )
    assert settings.clover_connect_url == "https://cloud.example.com/connect"
    assert settings.clover_api_url == "https://api.example.com"
    assert settings.clover_oauth_url == "https://www.example.com"
    assert settings.FRONTEND_URL == "https://pos.example.com"


def test_secrets_have_no_default_and_do_not_show_in_repr(monkeypatch):
    for name in ("CLOVER_APP_ID", "CLOVER_APP_SECRET", "CLOVER_TOKEN_KEY"):
        monkeypatch.delenv(name, raising=False)
    settings = make_settings()
    assert settings.CLOVER_APP_ID == ""
    assert settings.CLOVER_APP_SECRET.get_secret_value() == ""
    assert settings.CLOVER_TOKEN_KEY.get_secret_value() == ""

    settings = make_settings(CLOVER_APP_SECRET="s3cret-value", CLOVER_TOKEN_KEY=TOKEN_KEY)
    assert "s3cret-value" not in repr(settings) and TOKEN_KEY not in repr(settings)


def test_payment_terminal_clover_requires_its_secrets():
    complete = {
        "PAYMENT_TERMINAL": "clover",
        "CLOVER_APP_ID": "APP",
        "CLOVER_APP_SECRET": "secret",
        "CLOVER_TOKEN_KEY": TOKEN_KEY,
    }
    assert make_settings(**complete).clover_configured is True

    for missing in ("CLOVER_APP_ID", "CLOVER_APP_SECRET", "CLOVER_TOKEN_KEY"):
        with pytest.raises(ValidationError) as error:
            make_settings(**{**complete, missing: " "})
        assert missing in str(error.value)

    with pytest.raises(ValidationError) as error:
        make_settings(**{**complete, "CLOVER_TOKEN_KEY": "not-a-fernet-key"})
    assert "Fernet" in str(error.value)
    assert "not-a-fernet-key" not in str(error.value)

    with pytest.raises(ValidationError):
        make_settings(CLOVER_ENV="staging")
