import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make_settings(**overrides):
    values = {"SUPABASE_URL": "http://localhost:54321", "SUPABASE_KEY": "test-key", **overrides}
    return Settings(_env_file=None, **values)


def test_defaults(monkeypatch):
    for name in ("ENVIRONMENT", "CORS_ORIGINS", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    settings = make_settings()
    assert settings.ENVIRONMENT == "development"
    assert settings.LOG_LEVEL == "INFO"
    assert settings.cors_origins_list == ["http://localhost:3000"]


def test_cors_origins_are_parsed_from_comma_separated_string():
    settings = make_settings(CORS_ORIGINS=" http://a.test ,https://b.test,, ")
    assert settings.cors_origins_list == ["http://a.test", "https://b.test"]


@pytest.mark.parametrize("field", ["SUPABASE_URL", "SUPABASE_KEY"])
@pytest.mark.parametrize("value", ["", "   "])
def test_supabase_settings_must_not_be_empty(field, value):
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


def test_jwt_secret_is_not_a_setting():
    assert "JWT_SECRET" not in Settings.model_fields
