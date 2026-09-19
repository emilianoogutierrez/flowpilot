import base64
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from flowpilot.limits import MIN_WORKER_LEASE_SECONDS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FLOWPILOT_", env_file=".env", extra="ignore")

    environment: Literal["development", "production", "test"] = "development"
    database_url: str = "sqlite:///./var/flowpilot.db"
    master_keys: SecretStr
    active_key_id: str = "v1"
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    public_origin: str = "http://localhost:8000"
    egress_hosts: list[str] = []
    secure_cookies: bool = False
    session_hours: int = Field(default=12, ge=1, le=72)
    max_request_bytes: int = Field(default=131072, ge=1024, le=1048576)
    max_response_bytes: int = Field(default=262144, ge=1024, le=1048576)
    lease_seconds: int = Field(default=90, ge=MIN_WORKER_LEASE_SECONDS, le=600)
    poll_seconds: float = Field(default=0.5, ge=0.05, le=10)
    max_queued_runs: int = Field(default=500, ge=1, le=10000)
    webhook_clock_skew: int = 300
    retention_days: int = Field(default=30, ge=1, le=365)
    metrics_token: SecretStr = SecretStr("")
    static_dir: Path = Path("web/dist")
    otlp_endpoint: str | None = None

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        keys = json.loads(self.master_keys.get_secret_value())
        if self.active_key_id not in keys:
            raise ValueError("The active encryption key is missing")
        for key in keys.values():
            if len(base64.urlsafe_b64decode(key)) != 32:
                raise ValueError("Encryption keys must contain 32 random bytes")
        if self.environment == "production":
            if not self.secure_cookies or not self.public_origin.startswith("https://"):
                raise ValueError("Production requires HTTPS and secure cookies")
            if not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL")
            if len(self.metrics_token.get_secret_value()) < 32:
                raise ValueError("Production requires a metrics token of at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
