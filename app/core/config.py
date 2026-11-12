from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_KEY: str
    ENVIRONMENT: str = "development"
    # Comma-separated list of allowed browser origins; see `cors_origins_list`.
    CORS_ORIGINS: str = "http://localhost:3000"
    LOG_LEVEL: str = "INFO"
    # Payment terminal adapter (see app/integrations/payment_terminal). `clover` arrives in stage C.
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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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

    @property
    def payment_reconcile_backoff(self) -> tuple[float, ...]:
        return tuple(float(part) for part in self.PAYMENT_RECONCILE_BACKOFF.split(",") if part.strip())

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
