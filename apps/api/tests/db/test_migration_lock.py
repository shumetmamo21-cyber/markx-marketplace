"""Only one migration run at a time (D-091).

`alembic upgrade` takes a session-level advisory lock before it reads or
changes the schema, so a second run (a retried deploy, a second operator)
waits for the first instead of racing it, then finds nothing left to do.
"""

from __future__ import annotations

import threading
import time

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine, text

from tests.conftest import API_DIR


def _alembic() -> AlembicConfig:
    config = AlembicConfig(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    return config


def _lock_key() -> int:
    source = (API_DIR / "migrations" / "env.py").read_text()
    line = next(line for line in source.splitlines() if line.startswith("MIGRATION_LOCK_KEY"))
    return int(line.split("=")[1].strip().replace("_", ""))


def test_a_second_migration_run_waits_for_the_first(migrator_engine: Engine) -> None:
    key = _lock_key()
    finished = threading.Event()
    errors: list[BaseException] = []

    def upgrade() -> None:
        try:
            command.upgrade(_alembic(), "head")
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)
        finally:
            finished.set()

    with migrator_engine.connect() as holder:
        # Another migration run "in progress": it holds the lock.
        holder.execute(text("select pg_advisory_lock(:key)"), {"key": key})
        holder.commit()
        worker = threading.Thread(target=upgrade, daemon=True)
        worker.start()
        time.sleep(1.5)
        assert not finished.is_set(), "the second run must wait for the lock"
        holder.execute(text("select pg_advisory_unlock(:key)"), {"key": key})
        holder.commit()
    assert finished.wait(30), "the second run must go ahead once the lock is free"
    assert not errors, errors
    worker.join(5)


def test_the_lock_is_released_after_a_run(migrator_engine: Engine) -> None:
    command.upgrade(_alembic(), "head")
    with migrator_engine.connect() as connection:
        taken = connection.scalar(text("select pg_try_advisory_lock(:key)"), {"key": _lock_key()})
        assert taken is True
        connection.execute(text("select pg_advisory_unlock(:key)"), {"key": _lock_key()})
        connection.commit()


def test_migrating_an_up_to_date_database_changes_nothing(migrator_engine: Engine) -> None:
    with migrator_engine.connect() as connection:
        before = connection.scalar(text("select version_num from alembic_version"))
    command.upgrade(_alembic(), "head")
    command.upgrade(_alembic(), "head")
    with migrator_engine.connect() as connection:
        assert connection.scalar(text("select version_num from alembic_version")) == before
