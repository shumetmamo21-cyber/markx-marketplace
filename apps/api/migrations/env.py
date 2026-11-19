"""Alembic environment.

Migrations connect as markx_migrator, the role that owns the schema. The API
connects as markx_app, which cannot change the schema.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

from markx import registry  # noqa: F401  (registers every table on Base.metadata)
from markx.core.config import get_config
from markx.core.db import Base

config = context.config
if config.config_file_name is not None:
    # Keep the application's own loggers alive when migrations run in-process.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    # Tests point migrations at their own database through this attribute.
    override = config.attributes.get("database_url")
    return override or get_config().migration_database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# One migration run at a time per database (D-091). A second `alembic
# upgrade` (a retried deploy, two operators, a container restarted by
# mistake) waits on this session-level advisory lock and then finds the
# schema already at head, instead of racing the first one. The number is
# arbitrary and fixed; nothing else in MarkX takes advisory locks.
MIGRATION_LOCK_KEY = 7_270_201_691


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        connection.execute(text("select pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
        connection.commit()
        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                compare_server_default=True,
            )
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.rollback()
            connection.execute(text("select pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY})
            connection.commit()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
