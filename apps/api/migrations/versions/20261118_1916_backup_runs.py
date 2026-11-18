"""Backup runs: every attempt of the backup service and every restore drill (D-094).

`backup_runs` records each backup, drill and verification: when it ran, its
final status, the destination's identity (provider, host, bucket, prefix;
never a credential), whether that destination is off the server, whether
the set was verified after upload, its sizes and object counts, and a short
error code when it failed. The worker's watch reads it to alert on failed,
incomplete and stale backups and on failed or overdue drills.

The backup service writes it as the schema owner. The application role may
only read it: it cannot invent, change or remove a backup record.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-18 19:16:49.147857+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backup_runs",
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="running", nullable=False),
        sa.Column("backup_id", sa.Text(), nullable=True),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("offsite", sa.Boolean(), nullable=False),
        sa.Column("verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("database_bytes", sa.BigInteger(), nullable=True),
        sa.Column("object_count", sa.Integer(), nullable=True),
        sa.Column("object_bytes", sa.BigInteger(), nullable=True),
        sa.Column("new_objects", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column(
            "details", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at is null)",
            name=op.f("ck_backup_runs_finished_unless_running"),
        ),
        sa.CheckConstraint(
            "kind in ('backup', 'drill', 'verify')", name=op.f("ck_backup_runs_kind_allowed")
        ),
        sa.CheckConstraint(
            "not verified or status = 'succeeded'",
            name=op.f("ck_backup_runs_verified_only_if_succeeded"),
        ),
        sa.CheckConstraint(
            "status in ('running', 'succeeded', 'incomplete', 'failed', 'skipped', 'abandoned')",
            name=op.f("ck_backup_runs_status_allowed"),
        ),
        sa.CheckConstraint(
            "status not in ('failed', 'abandoned') or error_code is not null",
            name=op.f("ck_backup_runs_failure_has_a_code"),
        ),
        sa.CheckConstraint(
            "finished_at is null or finished_at >= started_at",
            name=op.f("ck_backup_runs_finished_after_start"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backup_runs")),
    )
    op.create_index(
        "ix_backup_runs_kind_started", "backup_runs", ["kind", "started_at"], unique=False
    )
    op.execute("revoke insert, update, delete, truncate on backup_runs from markx_app")


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
