"""What the database says must exist (D-094): file references and row counts.

Both run on a plain psycopg connection, so they work on the live database
(inside the backup's exported snapshot) and on a restored copy alike.

**File references.** Every stored file a row points to:

- `seller_documents.file_key` and `problem_photos.file_key`, private;
- `product_images.source_key`, private, when set;
- the two renditions `<file_key>-320.webp` and `<file_key>-1200.webp`,
  public, once `processed_at` is set (a picture removed later keeps them).

`stores.logo_key` and `order_items.image_key` exist in the schema but
nothing writes them today; if either ever holds a value, it is counted as
an *unclassified* reference, which fails verification until this module
learns which store it lives in.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from psycopg import Connection, sql

from markx.core.storage import StoreName
from markx.images.service import MAIN_SIDE, THUMB_SIDE


@dataclass(frozen=True, slots=True, order=True)
class FileReference:
    store: StoreName
    key: str
    kind: str


def file_references(conn: Connection[Any]) -> list[FileReference]:
    refs: list[FileReference] = []
    rows: Iterable[tuple[Any, ...]] = conn.execute(
        "select file_key from seller_documents order by id"
    ).fetchall()
    refs += [FileReference("private", row[0], "seller_document") for row in rows]
    rows = conn.execute("select file_key from problem_photos order by id").fetchall()
    refs += [FileReference("private", row[0], "problem_photo") for row in rows]
    rows = conn.execute(
        "select file_key, source_key, processed_at is not null from product_images order by id"
    ).fetchall()
    for file_key, source_key, processed in rows:
        if source_key is not None:
            refs.append(FileReference("private", source_key, "picture_source"))
        if processed:
            refs.append(FileReference("public", f"{file_key}-{THUMB_SIDE}.webp", "picture_thumb"))
            refs.append(FileReference("public", f"{file_key}-{MAIN_SIDE}.webp", "picture_main"))
    return sorted(refs)


def unclassified_references(conn: Connection[Any]) -> int:
    row = conn.execute(
        "select (select count(*) from stores where logo_key is not null)"
        " + (select count(*) from order_items where image_key is not null)"
    ).fetchone()
    return int(row[0]) if row else 0


def row_counts(conn: Connection[Any]) -> dict[str, int]:
    """Every table of the public schema and its exact row count."""
    tables = [
        row[0]
        for row in conn.execute(
            "select tablename from pg_tables where schemaname = 'public' order by tablename"
        ).fetchall()
    ]
    counts: dict[str, int] = {}
    for table in tables:
        row = conn.execute(
            sql.SQL("select count(*) from {}").format(sql.Identifier("public", table))
        ).fetchone()
        counts[table] = int(row[0]) if row else 0
    return counts


def alembic_revision(conn: Connection[Any]) -> str | None:
    row = conn.execute("select version_num from alembic_version").fetchone()
    return str(row[0]) if row else None


def schema_problems(conn: Connection[Any]) -> list[str]:
    """Structural damage a restore must not have: invalid indexes and
    constraints that were never validated."""
    problems: list[str] = []
    row = conn.execute(
        "select count(*) from pg_index i join pg_class c on c.oid = i.indrelid "
        "join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'public' and not (i.indisvalid and i.indisready)"
    ).fetchone()
    if row and row[0]:
        problems.append(f"{row[0]} invalid indexes")
    row = conn.execute(
        "select count(*) from pg_constraint c join pg_namespace n on n.oid = c.connamespace "
        "where n.nspname = 'public' and not c.convalidated"
    ).fetchone()
    if row and row[0]:
        problems.append(f"{row[0]} constraints not validated")
    return problems


@dataclass(frozen=True, slots=True)
class DatabaseIdentity:
    name: str
    server_version: str
    system_identifier: str | None


def database_identity(conn: Connection[Any]) -> DatabaseIdentity:
    row = conn.execute("select current_database(), current_setting('server_version')").fetchone()
    assert row is not None
    system_identifier: str | None = None
    try:
        with conn.transaction():
            ident = conn.execute(
                "select system_identifier::text from pg_control_system()"
            ).fetchone()
            system_identifier = str(ident[0]) if ident else None
    except Exception:  # not every role may read it; the identity is then name and version
        system_identifier = None
    return DatabaseIdentity(str(row[0]), str(row[1]), system_identifier)
