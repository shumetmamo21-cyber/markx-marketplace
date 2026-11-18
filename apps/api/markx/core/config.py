"""Runtime configuration, read from environment variables only.

Secrets never live in the repository. `.env.example` lists every variable;
real values are set in the host's secret store or a protected env file.
"""

from __future__ import annotations

import base64
import ipaddress
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]

# Values that are acceptable on a laptop and must never reach a real server.
_DEV_ONLY_MARKER = "dev-only"


class Config(BaseSettings):
    # hide_input_in_errors (D-091): a refused start-up names the settings that
    # are wrong, never their values; without it pydantic prints part of the
    # raw configuration, passwords included, into the container's log.
    model_config = SettingsConfigDict(
        env_prefix="MARKX_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

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

    # The reverse proxies whose X-Forwarded-For and X-Forwarded-Proto headers
    # are believed (SEC-3, D-084): comma-separated addresses or networks, such
    # as "10.0.0.5" or "172.18.0.0/16". A request from any other peer keeps its
    # own address, whatever headers it sends, so a visitor cannot pick the
    # address the rate limits count. Empty trusts no one; "*" is refused.
    trusted_proxies: str = "127.0.0.1,::1"

    storage_dir: Path = Path("./var/storage")
    # Where browsers load product pictures from (F.6): on a real server the
    # CDN's own cookieless domain; on a laptop the API's media route.
    public_media_base_url: str = "/api/v1/media"

    # Where uploaded files live (blueprint F.6; D-090): sellers' identity and
    # licence documents, picture sources and problem photos in the PRIVATE
    # bucket, rendered product pictures in the PUBLIC bucket behind the CDN.
    #   local  folders under MARKX_STORAGE_DIR; a laptop and the tests only
    #   minio  a MinIO server; a laptop, Compose and the tests only
    #   s3     Amazon S3 (or another S3 endpoint given in MARKX_STORAGE_ENDPOINT_URL)
    #   r2     Cloudflare R2 (MARKX_STORAGE_ENDPOINT_URL is the account's endpoint)
    # Staging and production refuse local and minio. Which provider holds the
    # documents for real is the founder's decision F-01; nothing here makes it.
    file_storage_provider: Literal["local", "minio", "s3", "r2"] = "local"
    # The S3 API endpoint. Required for minio and r2; for s3 leave it empty to
    # use AWS's own endpoint for the region.
    storage_endpoint_url: str | None = None
    # minio: any (default us-east-1); s3: the buckets' region (required); r2: auto.
    storage_region: str | None = None
    # One access key for both buckets, scoped to them alone. From the host's
    # secret store only. Both are SecretStr, so neither reaches a log, a repr
    # or a validation error. There is deliberately no fallback to AWS's own
    # credential chain (environment, ~/.aws, instance metadata): MarkX never
    # picks up credentials that were not made for it (AGENTS.md section 2).
    storage_access_key_id: SecretStr | None = None
    storage_secret_access_key: SecretStr | None = None
    storage_private_bucket: str | None = None
    storage_public_bucket: str | None = None
    storage_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    storage_read_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    # The largest object MarkX writes or reads. Uploads are capped lower by
    # their own settings (images.max_upload_bytes, sellers.document_max_bytes).
    storage_max_object_bytes: int = Field(default=20_000_000, gt=0, le=100_000_000)
    # Encryption at rest requested on every write. "auto" asks S3 for AES256
    # and leaves R2 (which always encrypts) and MinIO (which needs its own key
    # service for it) to their defaults.
    storage_server_side_encryption: Literal["auto", "AES256", "none"] = "auto"

    # SMS (D-089). "fake" writes to the development inbox and is for a laptop
    # and the tests only; staging and production refuse it. "http" is the
    # provider-independent HTTPS adapter (markx/notifications/sms.py): it
    # needs every MARKX_SMS_* value below, or the API does not start. No
    # provider has been chosen yet (blueprint O.23).
    sms_provider: Literal["fake", "http"] = "fake"
    # The provider's fixed sending endpoint: an https:// URL set by the
    # operator, never taken from a request. Checked at start-up.
    sms_api_url: str | None = None
    # From the host's secret store only. SecretStr keeps it out of logs,
    # reprs and validation errors.
    sms_api_key: SecretStr | None = None
    # The sender name or number the provider has approved for MarkX.
    sms_sender_id: str | None = None
    # How long to wait for the provider before giving up (fail closed). A
    # login code is never retried automatically.
    sms_timeout_seconds: float = Field(default=8.0, gt=0, le=30)
    # The bot check before any SMS (blueprint D.2, H.3; D-085). "fake" is for a
    # laptop and the tests only and is refused on staging and production;
    # "turnstile" is Cloudflare Turnstile, verified on the server.
    bot_check_provider: Literal["fake", "turnstile"] = "fake"
    # The Turnstile secret key: from the host's secret store only, never a
    # file in the repository. SecretStr keeps it out of logs, reprs and
    # validation errors.
    turnstile_secret_key: SecretStr | None = None
    # The public site key, which the sign-in page also needs. Not a secret.
    turnstile_site_key: str | None = None
    # The hostnames Turnstile must report the token was solved on, as bare
    # names separated by commas ("markx.et,www.markx.et"): no protocol, path,
    # port or wildcard; checked at start-up. Empty means the host of
    # MARKX_PUBLIC_ORIGIN.
    turnstile_allowed_hostnames: str = ""
    # How long to wait for Cloudflare before refusing (fail closed).
    turnstile_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    telegram_bot_token: str | None = None
    # The founder's private Telegram group for alerts (blueprint F.12; D-064).
    # With the bot token set, alerts go there; otherwise to the log.
    alert_telegram_chat_id: str | None = None
    # Who carries notifications to people's Telegram (D-092). "none": nobody;
    # every Telegram delivery is recorded `unavailable` and the in-app list
    # still has the message. "fake" writes to a development file and is for a
    # laptop and the tests only; staging and production refuse it. "bot_api"
    # is the adapter for Telegram's Bot API (markx/notifications/push.py),
    # which needs MARKX_TELEGRAM_BOT_TOKEN. Unset means "fake" on a laptop and
    # in the tests and "none" on a real server: no bot exists yet.
    telegram_push_provider: Literal["none", "fake", "bot_api"] | None = None
    telegram_push_timeout_seconds: float = Field(default=8.0, gt=0, le=30)
    # Connecting a person's Telegram to their MarkX account (D-093): the
    # one-time link `POST /me/telegram/link`, the bot's webhook
    # `POST /telegram/webhook` and the Mini App's `POST /me/telegram`. OFF by
    # default: no bot exists yet, and switching this on is the founder's
    # decision. Disconnecting always works, whatever this says.
    telegram_linking_enabled: bool = False
    # The bot's public username, without the @ (it ends in "bot"). Only used
    # to build the t.me link; required when linking is on. Not a secret.
    telegram_bot_username: str | None = None
    # The secret Telegram repeats in the X-Telegram-Bot-Api-Secret-Token
    # header of every webhook call (set with setWebhook's secret_token): 32 to
    # 256 letters, digits, "_" and "-". From the host's secret store only;
    # required when linking is on.
    telegram_webhook_secret: SecretStr | None = None
    # How long a connection link stays usable, in minutes.
    telegram_link_ttl_minutes: int = Field(default=10, ge=2, le=30)

    totp_issuer: str = "MarkX"

    # Session lifetimes, in minutes.
    customer_session_idle_minutes: int = 60 * 24 * 30
    customer_session_max_minutes: int = 60 * 24 * 90
    staff_session_idle_minutes: int = 30
    staff_session_max_minutes: int = 60 * 12

    # How long the worker rests between passes when nothing is waiting.
    worker_poll_seconds: float = 5.0
    # A code rollback (docs/runbooks/rollback.md; D-091): an older release
    # finds a schema a newer release migrated, which readiness reports as
    # "ahead" and refuses. Set to true ONLY for a rollback to a release the
    # newer release's notes call compatible with its migrations; remove it
    # when rolling forward again.
    allow_newer_schema: bool = False
    # A file the running worker touches after every pass (D-091), so a
    # container check can tell a live loop from a hung one without a
    # database. Unset: no file is written (a laptop, the tests).
    worker_heartbeat_file: Path | None = None

    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def _log_level_is_a_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"MARKX_LOG_LEVEL must be one of {', '.join(_LOG_LEVELS)}")
        return level

    @field_validator("trusted_proxies")
    @classmethod
    def _trusted_proxies_are_exact(cls, value: str) -> str:
        for item in _split(value):
            try:
                network = ipaddress.ip_network(item, strict=True)
            except ValueError as exc:
                raise ValueError(
                    f"MARKX_TRUSTED_PROXIES: {item!r} is not an address or network"
                ) from exc
            if network.prefixlen == 0:
                raise ValueError(f"MARKX_TRUSTED_PROXIES: {item!r} would trust every caller")
        return value

    @field_validator("turnstile_allowed_hostnames")
    @classmethod
    def _turnstile_hostnames_are_bare(cls, value: str) -> str:
        if not value.strip():
            return ""
        entries = [entry.strip() for entry in value.split(",")]
        problems = [
            f"{entry!r} {problem}"
            for entry in entries
            if (problem := _hostname_problem(entry)) is not None
        ]
        if problems:
            raise ValueError(
                "MARKX_TURNSTILE_ALLOWED_HOSTNAMES must list bare hostnames separated by "
                "commas, such as markx.et,www.markx.et: " + "; ".join(problems)
            )
        return ",".join(entry.lower() for entry in entries)

    @property
    def turnstile_hostnames(self) -> list[str]:
        configured = [h.lower() for h in _split(self.turnstile_allowed_hostnames)]
        if configured:
            return configured
        host = urlsplit(self.public_origin).hostname
        return [host.lower()] if host else []

    @model_validator(mode="after")
    def _turnstile_needs_its_keys(self) -> Config:
        if self.bot_check_provider != "turnstile":
            return self
        problems: list[str] = []
        secret = self.turnstile_secret_key.get_secret_value() if self.turnstile_secret_key else ""
        if not secret.strip():
            problems.append("MARKX_TURNSTILE_SECRET_KEY must be set")
        if not (self.turnstile_site_key or "").strip():
            problems.append("MARKX_TURNSTILE_SITE_KEY must be set")
        if not self.turnstile_hostnames:
            problems.append(
                "MARKX_TURNSTILE_ALLOWED_HOSTNAMES or MARKX_PUBLIC_ORIGIN must name a host"
            )
        local = [h for h in self.turnstile_hostnames if _is_local_hostname(h)]
        if self.is_real_environment and local:
            # A widget for localhost is for testing on a laptop only (D-085).
            problems.append(
                f"{', '.join(local)} is for local testing only; staging and production "
                "need the site's real hostnames and their own Turnstile widget"
            )
        if self.is_real_environment and _is_turnstile_test_key(secret, self.turnstile_site_key):
            # Cloudflare's published test keys pass or fail every visitor.
            problems.append("the Turnstile keys must be real keys, not Cloudflare's test keys")
        if problems:
            raise ValueError("Turnstile bot check: " + "; ".join(problems))
        return self

    @field_validator("sms_api_url")
    @classmethod
    def _sms_url_is_a_fixed_https_endpoint(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        problem = _sms_url_problem(value.strip())
        if problem is not None:
            raise ValueError(f"MARKX_SMS_API_URL {problem}")
        return value.strip()

    @field_validator("sms_sender_id")
    @classmethod
    def _sms_sender_id_is_valid(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        # The SMS standard allows an alphanumeric sender of at most 11
        # characters, or a number of at most 15 digits.
        if not (_SENDER_NAME.fullmatch(value) or _SENDER_NUMBER.fullmatch(value)):
            raise ValueError(
                "MARKX_SMS_SENDER_ID must be at most 11 letters and digits (such as MarkX) "
                "or a number of at most 15 digits"
            )
        return value

    @model_validator(mode="after")
    def _sms_needs_its_settings(self) -> Config:
        if self.sms_provider != "http":
            return self
        problems: list[str] = []
        if not self.sms_api_url:
            problems.append("MARKX_SMS_API_URL must be set")
        key = self.sms_api_key.get_secret_value() if self.sms_api_key else ""
        if not key.strip():
            problems.append("MARKX_SMS_API_KEY must be set")
        if not self.sms_sender_id:
            problems.append("MARKX_SMS_SENDER_ID must be set")
        if problems:
            raise ValueError("SMS provider: " + "; ".join(problems))
        return self

    @model_validator(mode="after")
    def _bot_api_needs_the_token(self) -> Config:
        if self.telegram_push_provider == "bot_api" and not (self.telegram_bot_token or "").strip():
            raise ValueError(
                "Telegram push provider: MARKX_TELEGRAM_BOT_TOKEN must be set for bot_api"
            )
        return self

    @field_validator("telegram_bot_username")
    @classmethod
    def _bot_username_is_a_bot_username(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip().removeprefix("@")
        if not _BOT_USERNAME.fullmatch(value):
            raise ValueError(
                "MARKX_TELEGRAM_BOT_USERNAME must be the bot's username without the @: "
                "5 to 32 letters, digits and underscores, ending in 'bot'"
            )
        return value

    @field_validator("telegram_webhook_secret")
    @classmethod
    def _webhook_secret_is_a_valid_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return None
        # Telegram accepts 1 to 256 of these characters; MarkX asks for at
        # least 32, so it cannot be guessed. The value is never printed.
        if not _WEBHOOK_SECRET.fullmatch(value.get_secret_value()):
            raise ValueError(
                "MARKX_TELEGRAM_WEBHOOK_SECRET must be 32 to 256 letters, digits, '_' and '-'"
            )
        return value

    @model_validator(mode="after")
    def _telegram_linking_needs_its_settings(self) -> Config:
        if not self.telegram_linking_enabled:
            return self
        problems: list[str] = []
        if not self.telegram_bot_username:
            problems.append("MARKX_TELEGRAM_BOT_USERNAME must be set")
        secret = self.telegram_webhook_secret
        if secret is None:
            problems.append("MARKX_TELEGRAM_WEBHOOK_SECRET must be set")
        elif self.is_real_environment and _looks_like_a_placeholder(secret.get_secret_value()):
            problems.append(
                "MARKX_TELEGRAM_WEBHOOK_SECRET must be a real random secret, not a "
                "development or test value"
            )
        if problems:
            raise ValueError("Telegram linking: " + "; ".join(problems))
        return self

    @property
    def telegram_linking_ready(self) -> bool:
        """Linking is switched on and has what it needs (the validator above
        refuses to start otherwise; this is the one place code asks)."""
        return bool(
            self.telegram_linking_enabled
            and self.telegram_bot_username
            and self.telegram_webhook_secret is not None
        )

    @field_validator("storage_endpoint_url")
    @classmethod
    def _storage_endpoint_is_a_bare_origin(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        problem = _endpoint_problem(value.strip())
        if problem is not None:
            raise ValueError(f"MARKX_STORAGE_ENDPOINT_URL {problem}")
        return value.strip().rstrip("/")

    @model_validator(mode="after")
    def _object_storage_needs_its_settings(self) -> Config:
        if self.file_storage_provider == "local":
            return self
        problems: list[str] = []
        provider = self.file_storage_provider
        for name, bucket in (
            ("MARKX_STORAGE_PRIVATE_BUCKET", self.storage_private_bucket),
            ("MARKX_STORAGE_PUBLIC_BUCKET", self.storage_public_bucket),
        ):
            if not bucket:
                problems.append(f"{name} must be set")
            elif not _BUCKET_NAME.fullmatch(bucket):
                problems.append(
                    f"{name} must be 3 to 63 lowercase letters, digits and hyphens, "
                    "starting and ending with a letter or digit"
                )
        if (
            self.storage_private_bucket
            and self.storage_private_bucket == self.storage_public_bucket
        ):
            # Blueprint F.6: documents never share a bucket with public pictures.
            problems.append("the private and the public bucket must be two different buckets")
        for name, secret in (
            ("MARKX_STORAGE_ACCESS_KEY_ID", self.storage_access_key_id),
            ("MARKX_STORAGE_SECRET_ACCESS_KEY", self.storage_secret_access_key),
        ):
            if secret is None or not secret.get_secret_value().strip():
                problems.append(f"{name} must be set")
        endpoint = self.storage_endpoint_url
        if provider in ("minio", "r2") and not endpoint:
            problems.append(f"MARKX_STORAGE_ENDPOINT_URL must be set for {provider}")
        if provider == "r2" and endpoint:
            host = (urlsplit(endpoint).hostname or "").lower()
            if not host.endswith(".r2.cloudflarestorage.com"):
                problems.append(
                    "MARKX_STORAGE_ENDPOINT_URL for r2 must be the account's "
                    "https://<account id>.r2.cloudflarestorage.com endpoint"
                )
        if provider == "s3" and not (self.storage_region or "").strip():
            problems.append("MARKX_STORAGE_REGION must be set for s3, e.g. eu-central-1")
        if problems:
            raise ValueError("File storage: " + "; ".join(problems))
        return self

    @property
    def storage_region_name(self) -> str:
        if self.storage_region and self.storage_region.strip():
            return self.storage_region.strip()
        return "auto" if self.file_storage_provider == "r2" else "us-east-1"

    @property
    def trusted_proxy_list(self) -> list[str]:
        return _split(self.trusted_proxies)

    @property
    def push_provider(self) -> str:
        """The Telegram push provider in effect (D-092)."""
        if self.telegram_push_provider is not None:
            return self.telegram_push_provider
        return "none" if self.is_real_environment else "fake"

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
        elif _endpoint_problem(self.public_origin) is not None:
            problems.append(
                "MARKX_PUBLIC_ORIGIN must be the bare origin the browser sees, such as "
                "https://markx.example, with no path, query or trailing text"
            )
        # D-091: column encryption fails at the first use of a malformed key
        # (a staff sign-in, a payout account), long after start-up.
        if not _is_fernet_key(self.encryption_key):
            problems.append(
                "MARKX_ENCRYPTION_KEY must be a Fernet key (44 characters of URL-safe "
                "base64; see .env.example for the command that makes one)"
            )
        # D-091: behind a reverse proxy the default (127.0.0.1) would make every
        # visitor share the proxy's address, so one busy minute would throttle
        # the whole country's sign-ins and searches. It must be said on purpose.
        if "trusted_proxies" not in self.model_fields_set:
            problems.append(
                "MARKX_TRUSTED_PROXIES must be set explicitly to the reverse proxy's "
                "address or network (docs/DEPLOYMENT.md)"
            )
        # D-091: debug logs may carry more than the production log rules allow.
        if self.log_level == "DEBUG":
            problems.append("MARKX_LOG_LEVEL must not be DEBUG on a real server")
        # SEC-2 (D-084): the fake bot check accepts any token, even none.
        if self.bot_check_provider == "fake":
            problems.append("MARKX_BOT_CHECK_PROVIDER must be a real bot check, not the fake")
        # D-092: the fake push sender writes messages to a file, not to Telegram.
        if self.telegram_push_provider == "fake":
            problems.append(
                "MARKX_TELEGRAM_PUSH_PROVIDER must be none or bot_api on a real server, "
                "not the fake"
            )
        # D-089: the fake SMS sender writes codes to a file instead of a phone.
        if self.sms_provider == "fake":
            problems.append("MARKX_SMS_PROVIDER must be a real SMS provider, not the fake")
        # D-090: files on the server's own disk are lost with the server and
        # have no backup of their own (F.6); MinIO here is a laptop and test
        # stand-in. Which real provider holds the documents is F-01.
        if self.file_storage_provider in ("local", "minio"):
            problems.append(
                "MARKX_FILE_STORAGE_PROVIDER must be real object storage (s3 or r2), "
                f"not {self.file_storage_provider}"
            )
        elif self.storage_endpoint_url and not self.storage_endpoint_url.startswith("https://"):
            problems.append("MARKX_STORAGE_ENDPOINT_URL must be an https:// endpoint")
        # F.6: pictures come from their own cookieless domain, never the site's.
        media = urlsplit(self.public_media_base_url)
        site_host = urlsplit(self.public_origin).hostname
        if media.scheme != "https" or not media.hostname:
            problems.append(
                "MARKX_PUBLIC_MEDIA_BASE_URL must be the picture CDN's https:// address"
            )
        elif media.hostname == site_host:
            problems.append(
                "MARKX_PUBLIC_MEDIA_BASE_URL must be on its own domain, not the site's, "
                "so pictures are served without the site's cookies"
            )
        if problems:
            raise ValueError("unsafe configuration for a real environment: " + "; ".join(problems))
        return self

    def startup_warnings(self) -> list[str]:
        """What a real server can run without but should not, in words, for the
        log at start-up (D-091). Never a value, only the setting's name."""
        if not self.is_real_environment:
            return []
        warnings: list[str] = []
        if not (self.telegram_bot_token and self.alert_telegram_chat_id):
            warnings.append(
                "alerts reach only the log: set MARKX_TELEGRAM_BOT_TOKEN and "
                "MARKX_ALERT_TELEGRAM_CHAT_ID once the founder's alert group exists"
            )
        if self.push_provider == "none":
            warnings.append(
                "no Telegram push provider: notifications reach the in-app list only, and "
                "every Telegram delivery is recorded as unavailable (D-092); seller order "
                "alerts need a real channel before launch"
            )
        if self.telegram_linking_enabled and self.push_provider == "none":
            warnings.append(
                "Telegram linking is on but no Telegram push provider is configured: "
                "people can connect Telegram, yet nothing is sent to it (D-093)"
            )
        return warnings


_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _is_fernet_key(value: str) -> bool:
    try:
        decoded = base64.urlsafe_b64decode(value.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return False
    return len(decoded) == 32 and len(value) == 44


def _is_turnstile_test_key(secret: str, site_key: str | None) -> bool:
    """Cloudflare's documented dummy keys look like "1x0000…AA": a digit, "x",
    then a run of zeros. Real keys start "0x" instead."""
    return any(
        len(key) > 6 and key[0] in "123" and key[1] == "x" and key[2:8] == "000000"
        for key in (secret, site_key or "")
    )


# Telegram bot usernames: 5 to 32 characters, ending in "bot" (any case).
_BOT_USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,28}[Bb][Oo][Tt]")
_WEBHOOK_SECRET = re.compile(r"[A-Za-z0-9_-]{32,256}")


def _looks_like_a_placeholder(secret: str) -> bool:
    lowered = secret.lower()
    return any(marker in lowered for marker in (_DEV_ONLY_MARKER, "test-only", "change-me"))


_SENDER_NAME = re.compile(r"[A-Za-z0-9]{1,11}")
_SENDER_NUMBER = re.compile(r"\+?[0-9]{1,15}")


def _sms_url_problem(url: str) -> str | None:
    """Why a URL is not a fixed HTTPS endpoint, in words; None when it is one."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "is not a valid URL"
    if parts.scheme != "https":
        return "must start with https://"
    if not parts.hostname:
        return "must name a host"
    if parts.username or parts.password:
        return "must not carry a user name or password; the key goes in MARKX_SMS_API_KEY"
    if parts.query or parts.fragment:
        return "must not carry a query or fragment; a key never goes in a URL"
    if port is not None and not 0 < port < 65536:
        return "has an invalid port"
    if any(character.isspace() for character in url):
        return "contains a space"
    return None


# S3 bucket names without dots, which would break HTTPS with virtual-hosted
# addressing.
_BUCKET_NAME = re.compile(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]")


def _endpoint_problem(url: str) -> str | None:
    """Why a URL is not a bare http(s) origin, in words; None when it is one."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "is not a valid URL"
    if parts.scheme not in ("https", "http"):
        return "must start with https:// (or http:// for MinIO on a laptop)"
    if not parts.hostname:
        return "must name a host"
    if parts.username or parts.password:
        return "must not carry a user name or password; the keys have their own settings"
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        return "must be the endpoint only, with no path, query or fragment"
    if port is not None and not 0 < port < 65536:
        return "has an invalid port"
    if any(character.isspace() for character in url):
        return "contains a space"
    return None


_HOSTNAME_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def _hostname_problem(entry: str) -> str | None:
    """Why an entry is not a bare hostname, in words; None when it is one."""
    if not entry:
        return "is empty (two commas in a row, or a comma at the start or end)"
    if "://" in entry:
        return "includes a protocol; write only the hostname, e.g. markx.et"
    if "/" in entry or "?" in entry or "#" in entry:
        return "includes a path; write only the hostname, e.g. markx.et"
    if "*" in entry:
        return "is a wildcard; list each hostname instead, e.g. markx.et,www.markx.et"
    if any(character.isspace() for character in entry):
        return "contains a space"
    try:
        ipaddress.ip_address(entry.strip("[]"))
    except ValueError:
        pass
    else:
        return "is an IP address; use a hostname such as markx.et or localhost"
    if ":" in entry:
        return "includes a port; write the hostname without :port"
    if entry.endswith("."):
        return "ends with a dot"
    host = entry.lower()
    if len(host) > 253 or not all(_HOSTNAME_LABEL.match(label) for label in host.split(".")):
        return (
            "is not a valid hostname (letters, digits, hyphens and dots only; "
            "write an Amharic domain in its xn-- form)"
        )
    return None


def _is_local_hostname(host: str) -> bool:
    return host == "localhost" or host.endswith(".localhost")


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@lru_cache
def get_config() -> Config:
    return Config()
