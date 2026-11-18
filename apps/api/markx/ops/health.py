"""Liveness and readiness (blueprint F.12; D-091).

Two different questions, asked by different callers:

- **Liveness** (`/api/v1/healthz/live`): is this process able to answer at
  all? It touches nothing outside the process, so a database outage never
  makes a container manager restart a healthy API (a restart would not
  bring the database back, and would turn one outage into two).
- **Readiness** (`/api/v1/healthz/ready`): can this process serve real
  requests now? The database answers as the application role, the schema
  is the one this image was built for (no migration is missing or
  unknown), and both file stores answer with MarkX's keys. A reverse proxy,
  a deploy script or an outside monitor stops sending traffic, or stops a
  release, while it is not ready.

What a public caller sees is a fixed vocabulary of words ("up", "down",
"behind", ...), never an address, bucket, key, revision, error text or
path. The details go to the log, where the operator reads them.

The storage probe asks the provider at most once per `STORAGE_PROBE_TTL`,
whoever calls, so the public readiness route cannot be used to make MarkX
hammer its own storage provider.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from markx.core.config import get_config
from markx.core.db import get_engine
from markx.core.storage import (
    S3ObjectStore,
    StorageUnavailable,
    get_private_storage,
    get_public_storage,
)

logger = logging.getLogger("markx.health")

DatabaseState = Literal["up", "down"]
SchemaState = Literal["current", "behind", "ahead", "unknown"]
StorageState = Literal["up", "down", "not_used"]

# The migrations shipped with this code, next to the `markx` package.
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
STORAGE_PROBE_TTL = 15.0


@dataclass(frozen=True, slots=True)
class Readiness:
    database: DatabaseState
    schema: SchemaState
    storage: StorageState

    @property
    def ready(self) -> bool:
        return self.database == "up" and self.schema == "current" and self.storage != "down"

    def public(self) -> dict[str, str]:
        """The words a public caller may see; nothing else."""
        return {
            "status": "ready" if self.ready else "not_ready",
            "database": self.database,
            "schema": self.schema,
            "storage": self.storage,
        }


@lru_cache
def expected_schema_heads() -> frozenset[str]:
    """The migration heads this code was built with."""
    return frozenset(ScriptDirectory(str(MIGRATIONS_DIR)).get_heads())


@lru_cache
def known_revisions() -> frozenset[str]:
    return frozenset(rev.revision for rev in ScriptDirectory(str(MIGRATIONS_DIR)).walk_revisions())


def check_database(engine: Engine | None = None) -> tuple[DatabaseState, SchemaState]:
    """Whether the database answers, and whether its schema is the one this
    code expects. `behind`: a migration has not been applied yet (run the
    one-time migration step). `ahead`: the database has a revision this
    code does not know (a newer release migrated it: roll forward, or
    restore; never run old code against it)."""
    try:
        with (engine or get_engine()).connect() as connection:
            connection.execute(text("select 1"))
            try:
                applied = frozenset(
                    connection.scalars(text("select version_num from alembic_version")).all()
                )
            except Exception:
                logger.warning("readiness: the schema version could not be read", exc_info=True)
                return "up", "unknown"
    except Exception:
        logger.warning("readiness: the database does not answer", exc_info=True)
        return "down", "unknown"
    expected = expected_schema_heads()
    if applied == expected:
        return "up", "current"
    if applied - known_revisions():
        logger.error(
            "readiness: the database has a migration this release does not know",
            extra={"applied": sorted(applied), "expected": sorted(expected)},
        )
        return "up", "ahead"
    logger.warning(
        "readiness: the database is missing migrations",
        extra={"applied": sorted(applied), "expected": sorted(expected)},
    )
    return "up", "behind"


class _StorageProbe:
    """`check_reachable` on both buckets, remembered for a few seconds."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._checked_at = float("-inf")
        self._state: StorageState = "not_used"

    def reset(self) -> None:
        with self._lock:
            self._checked_at = float("-inf")

    def state(self, *, now: float | None = None) -> StorageState:
        if get_config().file_storage_provider == "local":
            return "not_used"
        moment = time.monotonic() if now is None else now
        with self._lock:
            if moment - self._checked_at < STORAGE_PROBE_TTL:
                return self._state
            self._state = _probe_storage()
            self._checked_at = moment
            return self._state


def _probe_storage() -> StorageState:
    for store in (get_private_storage(), get_public_storage()):
        if not isinstance(store, S3ObjectStore):
            continue
        try:
            store.check_reachable()
        except StorageUnavailable as exc:
            # The reason is a fixed word from the storage module; it names no
            # bucket, key or endpoint (D-090).
            logger.warning(
                "readiness: a file store does not answer",
                extra={"store": store.name, "reason": exc.reason},
            )
            return "down"
    return "up"


storage_probe = _StorageProbe()


def readiness() -> Readiness:
    database, schema = check_database()
    return Readiness(database=database, schema=schema, storage=storage_probe.state())
