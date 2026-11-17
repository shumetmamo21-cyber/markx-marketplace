"""Runtime configuration, read from environment variables only.

Secrets never live in the repository. `.env.example` lists every variable;
real values are set in the host's secret store or a protected env file.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]

# Values that are acceptable on a laptop and must never reach a real server.
_DEV_ONLY_MARKER = "dev-only"


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MARKX_", env_file=".env", extra="ignore")

    env: Environment = "local"

    # The API connects as the least-privileged application role. Migrations
    # connect separately, as the role that owns the schema.
    database_url: str = "postgresql+psycopg://markx_app:markx_app_dev-only@127.0.0.1:5432/markx"
    migration_database_url: str = (
        "postgresql+psycopg://markx_migrator:markx_migrator_dev-only@127.0.0.1:5432/markx"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 10

    # Signs CSRF tokens, tracking links, handover codes and document links.
    secret_key: str = Field(default=f"{_DEV_ONLY_MARKER}-secret-key-change-me-0123456789abcdef")
    # Fernet key for column encryption (staff TOTP secrets, payout account numbers).
    encryption_key: str = Field(default="ZGV2LW9ubHktZW5jcnlwdGlvbi1rZXktMzJieXRlcyE=")

    # The single public origin the browser sees (web app and API share it).
    public_origin: str = "http://localhost:3000"
    cookie_secure: bool = False

    storage_dir: Path = Path("./var/storage")
    # Where browsers load product pictures from (F.6): on a real server the
    # CDN's own cookieless domain; on a laptop the API's media route.
    public_media_base_url: str = "/api/v1/media"

    # Where identity and licence documents are kept. Only the local-disk
    # adapter exists; it is refused on real servers (see markx/core/storage.py).
    file_storage_provider: Literal["local"] = "local"

    sms_provider: Literal["fake"] = "fake"
    bot_check_provider: Literal["fake"] = "fake"
    telegram_bot_token: str | None = None
    # The founder's private Telegram group for alerts (blueprint F.12; D-064).
    # With the bot token set, alerts go there; otherwise to the log.
    alert_telegram_chat_id: str | None = None

    totp_issuer: str = "MarkX"

    # Session lifetimes, in minutes.
    customer_session_idle_minutes: int = 60 * 24 * 30
    customer_session_max_minutes: int = 60 * 24 * 90
    staff_session_idle_minutes: int = 30
    staff_session_max_minutes: int = 60 * 12

    # How long the worker rests between passes when nothing is waiting.
    worker_poll_seconds: float = 5.0

    log_level: str = "INFO"

    @property
    def is_real_environment(self) -> bool:
        return self.env in ("staging", "production")

    @property
    def dev_tools_enabled(self) -> bool:
        """Dev-only helpers (the fake SMS inbox) exist only on a laptop or in tests."""
        return self.env in ("local", "test")

    @model_validator(mode="after")
    def _refuse_dev_secrets_on_real_servers(self) -> Config:
        if not self.is_real_environment:
            return self
        problems: list[str] = []
        if _DEV_ONLY_MARKER in self.secret_key or len(self.secret_key) < 32:
            problems.append("MARKX_SECRET_KEY must be a real secret of at least 32 characters")
        if self.encryption_key == "ZGV2LW9ubHktZW5jcnlwdGlvbi1rZXktMzJieXRlcyE=":
            problems.append("MARKX_ENCRYPTION_KEY must not be the development key")
        if _DEV_ONLY_MARKER in self.database_url or _DEV_ONLY_MARKER in self.migration_database_url:
            problems.append("database passwords must not be the development passwords")
        if not self.cookie_secure:
            problems.append("MARKX_COOKIE_SECURE must be true")
        if not self.public_origin.startswith("https://"):
            problems.append("MARKX_PUBLIC_ORIGIN must be an https:// origin")
        if problems:
            raise ValueError("unsafe configuration for a real environment: " + "; ".join(problems))
        return self


@lru_cache
def get_config() -> Config:
    return Config()
