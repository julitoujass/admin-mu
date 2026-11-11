from unittest.mock import MagicMock

import app.main as main


def test_root_still_works(client):
    assert client.get("/").status_code == 200


def test_health_does_not_touch_database(client, monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(main, "supabase", fake)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert fake.mock_calls == []


def test_ready_runs_one_cheap_query(client, monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(main, "supabase", fake)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    fake.table.assert_called_once_with("roles")


def test_ready_returns_503_without_error_text(client, monkeypatch):
    fake = MagicMock()
    fake.table.side_effect = RuntimeError("connection refused to db.internal:5432")
    monkeypatch.setattr(main, "supabase", fake)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "db.internal" not in response.text
