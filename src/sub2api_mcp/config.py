"""Validated runtime configuration loaded only from environment inputs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

Scope = Literal[
    "sub2api:read",
    "sub2api:write",
    "sub2api:admin",
    "sub2api:actor",
]

DEFAULT_ALLOWED_HOSTS = (
    "127.0.0.1:*",
    "localhost:*",
    "[::1]:*",
    "sub2api-scheduler-mcp:*",
)


class AccessTokenConfig(BaseModel):
    """One opaque API token and its fixed authorization scopes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    token: SecretStr = Field(min_length=32, max_length=512)
    scopes: frozenset[Scope] = Field(min_length=1)


def _default_core_root() -> Path:
    return Path(__file__).resolve().parents[2] / "core"


class Settings(BaseSettings):
    """Deployment-neutral settings for the MCP process."""

    model_config = SettingsConfigDict(
        env_prefix="SUB2API_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    host: str = Field(default="127.0.0.1", min_length=1, max_length=255)
    port: int = Field(default=5310, ge=1, le=65535)
    allowed_hosts: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_HOSTS),
        min_length=1,
    )
    database_url: str = Field(
        default="postgresql://guardian:guardian@127.0.0.1:5432/guardian",
        min_length=1,
        max_length=2048,
    )
    legacy_core_root: Path = Field(default_factory=_default_core_root)

    access_tokens: list[AccessTokenConfig] = Field(min_length=1)
    sub2api_admin_key: SecretStr = Field(min_length=16, max_length=2048)
    sub2api_base_url: str = "https://zhisuanapi.cn/api/v1"
    sub2api_timeout_seconds: int = Field(default=10, ge=1, le=30)

    scheduler_enabled: bool = False
    probe_interval_seconds: int = Field(default=60, ge=10, le=86400)
    scheduler_lease_seconds: int = Field(default=120, ge=30, le=3600)

    # Deprecated compatibility inputs. Guardian ignores the legacy periodic recovery window;
    # direct conditional recovery is controlled by GuardianPolicy.enabled and durable evidence.
    recovery_enabled: bool = False
    recovery_window_start: str = "02:00"
    recovery_window_end: str = "05:00"
    recovery_max_accounts_per_run: int = Field(default=5, ge=1, le=20)

    channel_account_sweep_enabled: bool = False
    channel_account_sweep_max_accounts: int = Field(default=1000, ge=1, le=1000)
    log_account_guard_enabled: bool = False
    log_error_threshold: int = Field(default=3, ge=1, le=1000)
    slow_first_token_event_threshold: int = Field(default=3, ge=3, le=3)
    slow_first_token_ms: int = Field(default=30000, ge=1, le=600000)
    slow_first_token_window_minutes: int = Field(default=3, ge=3, le=3)

    actor_bridge_enabled: bool = False
    actor_bridge_secret: SecretStr | None = None
    actor_replay_window_seconds: int = Field(default=300, ge=30, le=900)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator(
        "actor_bridge_secret",
        mode="before",
    )
    @classmethod
    def blank_optional_values_are_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_cross_field_settings(self) -> Settings:
        token_names = [item.name for item in self.access_tokens]
        token_values = [item.token.get_secret_value() for item in self.access_tokens]
        if len(token_names) != len(set(token_names)):
            raise ValueError("access token names must be unique")
        if len(token_values) != len(set(token_values)):
            raise ValueError("access token values must be unique")

        base_url = urlsplit(self.sub2api_base_url.strip().rstrip("/"))
        if base_url.scheme != "https" or not base_url.hostname:
            raise ValueError("sub2api_base_url must be an absolute HTTPS URL")
        if base_url.username or base_url.password or base_url.query or base_url.fragment:
            raise ValueError("sub2api_base_url cannot contain credentials, query, or fragment")
        self.sub2api_base_url = self.sub2api_base_url.strip().rstrip("/")

        database_url = urlsplit(self.database_url.strip())
        if database_url.scheme not in {"postgres", "postgresql"} or not database_url.hostname:
            raise ValueError("database_url must be a postgresql:// URL")
        if not database_url.path.strip("/"):
            raise ValueError("database_url must name a database")
        self.database_url = self.database_url.strip()

        if self.actor_bridge_enabled and (
            self.actor_bridge_secret is None
            or len(self.actor_bridge_secret.get_secret_value()) < 32
        ):
            raise ValueError("actor_bridge_secret must contain at least 32 characters")
        for field_name in (
            "recovery_window_start",
            "recovery_window_end",
        ):
            try:
                datetime.strptime(getattr(self, field_name), "%H:%M")
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field_name} must use HH:MM") from exc
        return self


def load_settings() -> Settings:
    """Load required settings from the configured environment sources."""

    return Settings()  # pyright: ignore[reportCallIssue]
