import base64
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "1.0.0"

# Clover hosts per environment (https://docs.clover.com/dev/docs/oauth-flows-in-clover).
# `production` is the Latin America region. The Cloud Pay Display base of LATAM production is
# not documented: it is assumed to follow the sandbox layout (`<api>/connect`); override it
# with CLOVER_CONNECT_URL once Fiserv confirms it.
CLOVER_HOSTS = {
    "sandbox": {"oauth": "https://sandbox.dev.clover.com", "api": "https://apisandbox.dev.clover.com"},
    "production": {"oauth": "https://www.la.clover.com", "api": "https://api.la.clover.com"},
}


class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_KEY: str
    ENVIRONMENT: str = "development"
    # Comma-separated list of allowed browser origins; see `cors_origins_list`.
    CORS_ORIGINS: str = "http://localhost:3000"
    LOG_LEVEL: str = "INFO"
    # Payment terminal adapter (see app/integrations/payment_terminal).
    PAYMENT_TERMINAL: Literal["fake", "clover"] = "fake"
    # Seconds the fake terminal waits before approving, to mimic the customer paying.
    PAYMENT_FAKE_DELAY_SECONDS: float = Field(default=3.0, ge=0)
    # Sweep of unresolved charges: runs at startup and then every N seconds; 0 disables it.
    PAYMENT_RECONCILE_INTERVAL_SECONDS: float = Field(default=60.0, ge=0)
    # A pendiente/enviado charge not updated for this long belongs to a dead process (charge timeout + margin).
    PAYMENT_STALE_SECONDS: float = Field(default=180.0, gt=0)
    # Sweep attempts per charge before it is left for admin review.
    PAYMENT_RECONCILE_MAX_ATTEMPTS: int = Field(default=10, ge=1)
    # Waits (seconds, comma-separated) between the lookups made right after an unknown charge result.
    PAYMENT_RECONCILE_BACKOFF: str = "2,5,10"
    # Clover (PAYMENT_TERMINAL=clover). Secrets have no default and are never logged.
    CLOVER_ENV: Literal["sandbox", "production"] = "sandbox"
    CLOVER_APP_ID: str = ""
    CLOVER_APP_SECRET: SecretStr = SecretStr("")
    # Fernet key that encrypts the OAuth tokens at rest (and signs the OAuth `state`).
    CLOVER_TOKEN_KEY: SecretStr = SecretStr("")
    # Must be registered in the Clover app settings (it has to live under the app's Site URL).
    CLOVER_REDIRECT_URI: str = "http://localhost:8001/api/v1/integraciones/clover/callback"
    # Optional overrides of the hosts derived from CLOVER_ENV (blank = derived).
    CLOVER_OAUTH_URL: str = ""  # merchant authorization pages
    CLOVER_API_URL: str = ""  # token exchange and refresh
    CLOVER_CONNECT_URL: str = ""  # Cloud Pay Display (`.../connect`)
    # `X-POS-Id` sent to the device when the integration row has no `pos_id`.
    CLOVER_POS_ID: str = "mundo-uniforme-pos"
    # Where the OAuth callback sends the browser back.
    FRONTEND_URL: str = "http://localhost:3000"

    # Validation errors never echo the rejected values: they may be secrets.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    @field_validator("SUPABASE_URL", "SUPABASE_KEY")
    @classmethod
    def _must_not_be_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("PAYMENT_RECONCILE_BACKOFF")
    @classmethod
    def _backoff_must_be_numbers(cls, value: str) -> str:
        for part in value.split(","):
            if part.strip() and float(part) < 0:
                raise ValueError("waits must not be negative")
        return value

    @field_validator(
        "CLOVER_APP_ID", "CLOVER_REDIRECT_URI", "CLOVER_OAUTH_URL", "CLOVER_API_URL", "CLOVER_CONNECT_URL", "FRONTEND_URL"
    )
    @classmethod
    def _strip_text_and_trailing_slash(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @model_validator(mode="after")
    def _clover_needs_its_secrets(self):
        if self.PAYMENT_TERMINAL != "clover":
            return self
        missing = [
            name
            for name, value in (
                ("CLOVER_APP_ID", self.CLOVER_APP_ID),
                ("CLOVER_APP_SECRET", self.CLOVER_APP_SECRET.get_secret_value().strip()),
                ("CLOVER_TOKEN_KEY", self.CLOVER_TOKEN_KEY.get_secret_value().strip()),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"PAYMENT_TERMINAL=clover requires {', '.join(missing)}")
        if not _is_fernet_key(self.CLOVER_TOKEN_KEY.get_secret_value().strip()):
            # The value itself is never echoed.
            raise ValueError("CLOVER_TOKEN_KEY must be a Fernet key (see README: how to generate it)")
        return self

    @property
    def clover_configured(self) -> bool:
        """Clover is the selected terminal (its secrets were validated at startup)."""
        return self.PAYMENT_TERMINAL == "clover"

    @property
    def clover_oauth_url(self) -> str:
        return self.CLOVER_OAUTH_URL or CLOVER_HOSTS[self.CLOVER_ENV]["oauth"]

    @property
    def clover_api_url(self) -> str:
        return self.CLOVER_API_URL or CLOVER_HOSTS[self.CLOVER_ENV]["api"]

    @property
    def clover_connect_url(self) -> str:
        return self.CLOVER_CONNECT_URL or f"{self.clover_api_url}/connect"

    @property
    def payment_reconcile_backoff(self) -> tuple[float, ...]:
        return tuple(float(part) for part in self.PAYMENT_RECONCILE_BACKOFF.split(",") if part.strip())

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


def _is_fernet_key(value: str) -> bool:
    """A Fernet key is 32 url-safe base64-encoded bytes."""
    try:
        return len(base64.urlsafe_b64decode(value.encode("ascii"))) == 32
    except (ValueError, UnicodeEncodeError):
        return False


settings = Settings()
