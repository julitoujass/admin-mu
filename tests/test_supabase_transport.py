import httpx
import pytest

from app.core.supabase import ReadRetryTransport, build_http_client


class FlakyTransport(httpx.BaseTransport):
    """Fails the first request with a dropped connection, then answers 200."""

    def __init__(self):
        self.calls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.calls == 1:
            raise httpx.RemoteProtocolError("Server disconnected", request=request)
        return httpx.Response(200, json={"ok": True}, request=request)


def test_get_is_retried_once_after_a_dropped_connection():
    inner = FlakyTransport()
    client = httpx.Client(transport=ReadRetryTransport(inner))

    response = client.get("https://example.supabase.co/rest/v1/ventas")

    assert response.status_code == 200
    assert inner.calls == 2


def test_post_is_never_retried_because_it_may_have_been_applied():
    inner = FlakyTransport()
    client = httpx.Client(transport=ReadRetryTransport(inner))

    with pytest.raises(httpx.RemoteProtocolError):
        client.post("https://example.supabase.co/rest/v1/rpc/registrar_venta", json={})

    assert inner.calls == 1


def test_get_is_retried_only_once():
    class AlwaysDropped(httpx.BaseTransport):
        calls = 0

        def handle_request(self, request):
            AlwaysDropped.calls += 1
            raise httpx.RemoteProtocolError("Server disconnected", request=request)

    client = httpx.Client(transport=ReadRetryTransport(AlwaysDropped()))

    with pytest.raises(httpx.RemoteProtocolError):
        client.get("https://example.supabase.co/rest/v1/ventas")

    assert AlwaysDropped.calls == 2


def test_shared_client_uses_http1_and_short_keepalive():
    client = build_http_client()

    assert isinstance(client._transport, ReadRetryTransport)
    pool = client._transport._inner._pool
    assert pool._http2 is False
    assert pool._keepalive_expiry is not None and pool._keepalive_expiry <= 30
