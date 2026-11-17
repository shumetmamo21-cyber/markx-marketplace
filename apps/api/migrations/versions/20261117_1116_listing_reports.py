"""Listing reports (blueprint C-30, AD-16; D-067).

`reports` (in the schema since 0001, unused until now) gains an optional
note, a fixed list of reasons, one open report per person and target, and
CHECKs that a closed report has its time and a written note.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-17 11:16:11.840178+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0011'
down_revision: str | None = '0010'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('reports', sa.Column('note', sa.Text(), nullable=True))
    op.create_index('ix_reports_target', 'reports', ['target_type', 'target_id', 'status'], unique=False)
    op.create_index('uq_reports_open_per_reporter', 'reports', ['target_type', 'target_id', 'reporter_user_id'], unique=True, postgresql_where=sa.text("status = 'open' and reporter_user_id is not null"))
    # Alembic does not compare CHECK constraints; these mirror the model.
    op.create_check_constraint(
        op.f('ck_reports_reason_allowed'), 'reports',
        "reason in ('counterfeit', 'prohibited', 'wrong_information', 'offensive', 'fraud', "
        "'spam', 'other')",
    )
    op.create_check_constraint(
        op.f('ck_reports_note_length'), 'reports', "note is null or length(note) <= 500"
    )
    op.create_check_constraint(
        op.f('ck_reports_resolved_when_closed'), 'reports',
        "(status = 'open') = (resolved_at is null)",
    )
    op.create_check_constraint(
        op.f('ck_reports_resolution_has_note'), 'reports',
        "status = 'open' or length(btrim(resolution_note)) > 0",
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
