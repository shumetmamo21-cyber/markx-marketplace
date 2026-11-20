"""The backup service's own settings (D-094), from MARKX_BACKUP_* variables.

They are read by the backup service and the restore tool only, never by the
API or the worker, which never hold a backup credential or key. The source
file stores are read with their own MARKX_BACKUP_SOURCE_* credentials, which
should be read-only (docs/DEPLOYMENT.md): the backup never writes to them.

Every command on staging and production refuses a destination that is not
off-server object storage (`local`, `minio`) or not https://, and a backup
bucket that is also a file bucket. The backup service (`run`, `serve`,
`prune`) also refuses, through `service_problems()`:

- file stores read from a folder or MinIO, or over plain http;
- the file stores' own access key reused for the backup destination;
- no explicit retention (`MARKX_BACKUP_RETENTION_DAYS`, 0 meaning "never
  delete"), because how long backups are kept is the founder's decision;
- a missing public key or signing key, or an unnamed release.

A restore needs none of the service's settings: an operator's machine needs
the destination's (read) credentials, the recovery key and the signer key.

**Object lock (BK-1).** On staging and production the backup bucket must have
S3 Object Lock in COMPLIANCE mode with a default retention of at least
`MARKX_BACKUP_OBJECT_LOCK_MIN_DAYS`; the service refuses to start otherwise
(`destination.py`). PROVISIONAL: requiring it costs storage for the lock
period once a real bucket exists, and the period itself is the founder's to
confirm with F-16 and F-20 (docs/DECISIONS.md, D-096). A laptop and the tests
ask for it with MARKX_BACKUP_REQUIRE_OBJECT_LOCK=1.

A laptop and the tests may use a folder or MinIO; a folder on the same
machine is reported as NOT off-server in every record and manifest.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from markx.core.storage import ObjectStorageSettings

_BUCKET_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")

# Local and test defaults only; a real server must say its own.
LOCAL_RETENTION_DAYS = 7
LOCAL_RETENTION_MIN_SETS = 3


class BackupConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MARKX_BACKUP_",
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    env: Literal["local", "test", "staging", "production"] = Field(
        default="local", validation_alias=AliasChoices("MARKX_ENV")
    )
    # The release being run, recorded in every manifest.
    release: str = Field(default="unknown", validation_alias=AliasChoices("MARKX_RELEASE"))

    # -- the database (connection: the PG* variables, as the schema owner) -----------
    database: str = "markx"
    # The client commands; a laptop with an older client can run the server's
    # own in a container, e.g. "docker exec -i -e PGHOST -e PGUSER -e PGPASSWORD markx-pg pg_dump".
    pg_dump_command: str = "pg_dump"
    pg_restore_command: str = "pg_restore"
    psql_command: str = "psql"

    # -- the keys (docs/runbooks/backup-and-restore.md, "Keys") -----------------
    # The recipient's PUBLIC key: the server can encrypt, never decrypt.
    public_key_file: Path | None = None
    # Signs manifests and names blobs. Secret, mode 600, on the server.
    signing_key_file: Path | None = None

    # -- where the sets go ---------------------------------------------------------
    #   local  a folder (MARKX_BACKUP_DESTINATION_DIR); a laptop and tests only
    #   minio  a MinIO server; a laptop, Compose and tests only
    #   s3     Amazon S3 or another S3-compatible endpoint, over https
    #   r2     Cloudflare R2, over https
    # Which provider and where is the founder's decision (F-16); none is chosen.
    destination: Literal["local", "minio", "s3", "r2"] = "local"
    destination_dir: Path = Path("./var/backup-destination")
    destination_endpoint_url: str | None = None
    destination_region: str | None = None
    destination_bucket: str | None = None
    # Everything goes under this prefix in the bucket, e.g. "markx/production".
    destination_prefix: str = "markx"
    destination_access_key_id: SecretStr | None = None
    destination_secret_access_key: SecretStr | None = None
    destination_connect_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    destination_read_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    destination_retries: int = Field(default=3, ge=0, le=10)

    # -- where the stored files are read from (read-only) ----------------------
    source_provider: Literal["local", "minio", "s3", "r2"] = "local"
    source_dir: Path = Path("./var/storage")
    source_endpoint_url: str | None = None
    source_region: str | None = None
    source_private_bucket: str | None = None
    source_public_bucket: str | None = None
    source_access_key_id: SecretStr | None = None
    source_secret_access_key: SecretStr | None = None

    # -- this server's working folder ----------------------------------------------
    # Holds the set being made, the last few verified sets as a local copy, and
    # the evidence of failed attempts. A local copy is NOT an off-server backup.
    work_dir: Path = Path("./var/backups")
    local_keep_sets: int = Field(default=2, ge=0, le=60)
    failed_evidence_keep: int = Field(default=10, ge=1, le=100)

    # -- schedule and retries ----------------------------------------------------------
    hour_utc: int = Field(default=23, ge=0, le=23)
    retry_attempts: int = Field(default=3, ge=1, le=10)
    retry_delay_seconds: int = Field(default=600, ge=1, le=21_600)
    # The container's health check: a verified off-server set this recent.
    max_age_hours: int = Field(default=26, ge=1, le=24 * 14)

    # -- retention: the founder decides (F-20); defaults exist on a laptop only ------
    # Days a complete set is kept; 0 keeps every set forever. Required on a real server.
    retention_days: int | None = Field(default=None, ge=0, le=3650)
    # The newest this many verified sets are never deleted, whatever their age.
    retention_min_sets: int | None = Field(default=None, ge=1, le=365)
    # A blob no kept set needs is removed only after this long, so a backup
    # running at the same moment can never lose a blob it just uploaded.
    blob_grace_hours: int = Field(default=48, ge=24, le=24 * 30)

    # -- object lock (BK-1): PROVISIONAL, the founder confirms with F-16 ----------------
    # Always required on staging and production; this asks for it anywhere else.
    require_object_lock: bool = False
    # The bucket's default COMPLIANCE retention must be at least this many days,
    # and every object of the newest set stays locked at least this long.
    # PROVISIONAL: 30 days, the blueprint's backup period (H.2); F-16 and F-20.
    object_lock_min_days: int = Field(default=30, ge=1, le=3650)

    @property
    def is_real_environment(self) -> bool:
        return self.env in ("staging", "production")

    @property
    def object_lock_required(self) -> bool:
        """PROVISIONAL (F-16): always on staging and production."""
        return self.is_real_environment or self.require_object_lock

    @property
    def offsite(self) -> bool:
        """Whether the destination is away from this server. A folder never is,
        and neither is MinIO here: it is a laptop and test stand-in."""
        return self.destination in ("s3", "r2")

    @property
    def effective_retention_days(self) -> int:
        if self.retention_days is not None:
            return self.retention_days
        return LOCAL_RETENTION_DAYS

    @property
    def effective_retention_min_sets(self) -> int:
        if self.retention_min_sets is not None:
            return self.retention_min_sets
        return LOCAL_RETENTION_MIN_SETS

    @property
    def destination_identity(self) -> str:
        """Names the destination without any secret: provider, host, bucket, prefix."""
        if self.destination == "local":
            return f"local:{self.destination_dir.resolve()}"
        host = urlsplit(self.destination_endpoint_url or "").hostname or "aws"
        return f"{self.destination}:{host}/{self.destination_bucket}/{self.destination_prefix}"

    def destination_settings(self) -> ObjectStorageSettings:
        assert self.destination != "local"
        assert self.destination_access_key_id
        assert self.destination_secret_access_key
        assert self.destination_bucket
        return ObjectStorageSettings(
            provider=self.destination,
            endpoint_url=self.destination_endpoint_url,
            region=_region(self.destination, self.destination_region),
            access_key_id=self.destination_access_key_id.get_secret_value(),
            secret_access_key=self.destination_secret_access_key.get_secret_value(),
            # The backup bucket is the only bucket of this connection.
            private_bucket=self.destination_bucket,
            public_bucket=self.destination_bucket,
            connect_timeout=self.destination_connect_timeout_seconds,
            read_timeout=self.destination_read_timeout_seconds,
            retries=self.destination_retries,
            # The sets are encrypted before they leave; S3 adds its own on top.
            server_side_encryption="auto",
        )

    def source_settings(self) -> ObjectStorageSettings:
        assert self.source_provider != "local"
        assert self.source_access_key_id
        assert self.source_secret_access_key
        assert self.source_private_bucket
        assert self.source_public_bucket
        return ObjectStorageSettings(
            provider=self.source_provider,
            endpoint_url=self.source_endpoint_url,
            region=_region(self.source_provider, self.source_region),
            access_key_id=self.source_access_key_id.get_secret_value(),
            secret_access_key=self.source_secret_access_key.get_secret_value(),
            private_bucket=self.source_private_bucket,
            public_bucket=self.source_public_bucket,
            read_timeout=self.destination_read_timeout_seconds,
        )

    @model_validator(mode="after")
    def _check(self) -> BackupConfig:
        problems: list[str] = []
        prefix = self.destination_prefix
        if (
            not prefix
            or prefix.startswith("/")
            or prefix.endswith("/")
            or ".." in prefix.split("/")
        ):
            problems.append(
                "MARKX_BACKUP_DESTINATION_PREFIX must be a relative path like markx/production"
            )
        elif not all(c.isalnum() or c in "-_/." for c in prefix):
            problems.append(
                "MARKX_BACKUP_DESTINATION_PREFIX may hold letters, digits, - _ . and / only"
            )
        if self.destination != "local":
            if not self.destination_bucket or not _bucket_ok(self.destination_bucket):
                problems.append("MARKX_BACKUP_DESTINATION_BUCKET must be a valid bucket name")
            if not (self.destination_access_key_id and self.destination_secret_access_key):
                problems.append(
                    "MARKX_BACKUP_DESTINATION_ACCESS_KEY_ID and _SECRET_ACCESS_KEY must be set: "
                    "the backup never falls back to the machine's own credentials"
                )
            if self.destination in ("minio", "r2") and not self.destination_endpoint_url:
                problems.append(
                    f"MARKX_BACKUP_DESTINATION_ENDPOINT_URL must be set for {self.destination}"
                )
            if self.destination == "s3" and not (self.destination_region or "").strip():
                problems.append("MARKX_BACKUP_DESTINATION_REGION must be set for s3")
            if self.destination_endpoint_url and not _bare_origin(self.destination_endpoint_url):
                problems.append(
                    "MARKX_BACKUP_DESTINATION_ENDPOINT_URL must be a bare http(s) origin"
                )
        if self.source_provider != "local":
            for name, value in (
                ("MARKX_BACKUP_SOURCE_PRIVATE_BUCKET", self.source_private_bucket),
                ("MARKX_BACKUP_SOURCE_PUBLIC_BUCKET", self.source_public_bucket),
            ):
                if not value or not _bucket_ok(value):
                    problems.append(f"{name} must be a valid bucket name")
            if not (self.source_access_key_id and self.source_secret_access_key):
                problems.append(
                    "MARKX_BACKUP_SOURCE_ACCESS_KEY_ID and _SECRET_ACCESS_KEY must be set"
                )
            if self.source_provider in ("minio", "r2") and not self.source_endpoint_url:
                problems.append(
                    f"MARKX_BACKUP_SOURCE_ENDPOINT_URL must be set for {self.source_provider}"
                )
        if self.destination != "local" and self.destination_bucket in (
            self.source_private_bucket, self.source_public_bucket,
        ):  # fmt: skip
            problems.append(
                "the backup bucket must be its own bucket, never the documents' or the pictures'"
            )
        if self.require_object_lock and self.destination == "local":
            problems.append(
                "MARKX_BACKUP_REQUIRE_OBJECT_LOCK needs object storage: a folder has no object lock"
            )
        if problems:
            raise ValueError("Backup settings: " + "; ".join(problems))
        if self.is_real_environment:
            self._check_real_environment()
        return self

    def _check_real_environment(self) -> None:
        problems: list[str] = []
        if self.destination in ("local", "minio"):
            problems.append(
                "MARKX_BACKUP_DESTINATION must be off-server object storage (s3 or r2), not "
                f"{self.destination}: a backup on the same server is lost with the server"
            )
        elif not (self.destination_endpoint_url or "https://").startswith("https://"):
            problems.append("MARKX_BACKUP_DESTINATION_ENDPOINT_URL must be https://")
        if problems:
            raise ValueError(
                "unsafe backup settings for a real environment: " + "; ".join(problems)
            )

    def service_problems(self) -> list[str]:
        """What the backup SERVICE (run, serve, prune) needs on a real server,
        beyond what every command needs. A restore on an operator's machine
        needs none of it: only the destination, the recovery key and the signer."""
        if not self.is_real_environment:
            return []
        problems: list[str] = []
        if self.source_provider in ("local", "minio"):
            problems.append("MARKX_BACKUP_SOURCE_PROVIDER must be s3 or r2 on a real server")
        elif not (self.source_endpoint_url or "https://").startswith("https://"):
            problems.append("MARKX_BACKUP_SOURCE_ENDPOINT_URL must be https://")
        if (
            self.destination_access_key_id
            and self.source_access_key_id
            and self.destination_access_key_id.get_secret_value()
            == self.source_access_key_id.get_secret_value()
        ):
            problems.append(
                "the backup destination needs its own access key, not the file stores' key"
            )
        if self.retention_days is None or self.retention_min_sets is None:
            problems.append(
                "MARKX_BACKUP_RETENTION_DAYS and MARKX_BACKUP_RETENTION_MIN_SETS must be set "
                "explicitly (the founder's retention decision; 0 days keeps everything)"
            )
        if self.public_key_file is None:
            problems.append("MARKX_BACKUP_PUBLIC_KEY_FILE must name the recipient public key")
        if self.signing_key_file is None:
            problems.append("MARKX_BACKUP_SIGNING_KEY_FILE must name the signing key")
        if self.release == "unknown":
            problems.append("MARKX_RELEASE must name the release being run")
        return problems


def _region(provider: str, region: str | None) -> str:
    if region and region.strip():
        return region.strip()
    return "auto" if provider == "r2" else "us-east-1"


def _bucket_ok(name: str) -> bool:
    return (
        3 <= len(name) <= 63 and set(name) <= _BUCKET_CHARS and name[0] != "-" and name[-1] != "-"
    )


def _bare_origin(url: str) -> bool:
    try:
        parts = urlsplit(url)
        _ = parts.port
    except ValueError:
        return False
    return (
        parts.scheme in ("http", "https")
        and bool(parts.hostname)
        and parts.path in ("", "/")
        and not parts.query
        and not parts.fragment
        and not parts.username
        and not parts.password
    )


@lru_cache
def get_backup_config() -> BackupConfig:
    return BackupConfig()
