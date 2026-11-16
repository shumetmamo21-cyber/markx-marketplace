"""Database engine, session factory and the declarative base.

PostgreSQL is the referee (blueprint F.0): constraints carry stable names so
the application can tell which rule a rejected write broke.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache

from sqlalchemy import CheckConstraint, DateTime, Engine, MetaData, create_engine, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from markx.core.config import get_config
from markx.core.ids import uuid7

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def in_check(column: str, values: Iterable[str], name: str | None = None) -> CheckConstraint:
    """A CHECK that a text column holds one of the allowed values (blueprint G.8 rule 7)."""
    allowed = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} in ({allowed})", name=name or f"{column}_allowed")


class UUIDPrimaryKey:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Timestamps(CreatedAt):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


@lru_cache
def get_engine() -> Engine:
    config = get_config()
    return create_engine(
        config.database_url,
        pool_size=config.db_pool_size,
        max_overflow=config.db_max_overflow,
        pool_pre_ping=True,
        connect_args={"options": "-c timezone=UTC -c statement_timeout=15000"},
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """One unit of work: commit on success, roll back on any error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
