import httpx
from supabase.lib.client_options import SyncClientOptions

from app.core.config import settings
from supabase import Client, create_client

# Reads are safe to repeat; writes (POST/PATCH/DELETE, including RPCs that create sales)
# are not, because the server may have applied them before the connection dropped.
_RETRYABLE_METHODS = {"GET", "HEAD", "OPTIONS"}


class ReadRetryTransport(httpx.BaseTransport):
    """Retries a read once when a pooled connection was closed by the server.

    Supabase closes idle keep-alive connections; the next request sent over that
    socket fails with RemoteProtocolError ("Server disconnected") before any
    response. Repeating an idempotent read on a fresh connection is safe.
    """

    def __init__(self, inner: httpx.BaseTransport):
        self._inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            return self._inner.handle_request(request)
        except (httpx.RemoteProtocolError, httpx.ReadError):
            if request.method not in _RETRYABLE_METHODS:
                raise
            return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


def build_http_client() -> httpx.Client:
    # HTTP/1.1 with a short keep-alive: a long-lived shared HTTP/2 connection was
    # being closed by Supabase and every request multiplexed on it failed.
    inner = httpx.HTTPTransport(
        http2=False,
        retries=1,  # connection-establishment errors only
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=15),
    )
    return httpx.Client(
        transport=ReadRetryTransport(inner),
        timeout=httpx.Timeout(60.0, connect=10.0),
        follow_redirects=True,
    )


supabase: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_KEY,
    options=SyncClientOptions(httpx_client=build_http_client()),
)
