PREFLIGHT_HEADERS = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "Authorization, Content-Type, Idempotency-Key",
}


def test_preflight_from_allowed_origin(client):
    response = client.options("/api/v1/ventas/", headers={"Origin": "https://pos.example.com", **PREFLIGHT_HEADERS})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://pos.example.com"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in response.headers


def test_preflight_from_unknown_origin_is_rejected(client):
    response = client.options("/api/v1/ventas/", headers={"Origin": "https://evil.example.com", **PREFLIGHT_HEADERS})

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_preflight_with_disallowed_header_is_rejected(client):
    response = client.options(
        "/api/v1/ventas/",
        headers={
            "Origin": "https://pos.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Custom-Header",
        },
    )

    assert response.status_code == 400


def test_simple_request_from_unknown_origin_gets_no_cors_headers(client):
    response = client.get("/health", headers={"Origin": "https://evil.example.com"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
