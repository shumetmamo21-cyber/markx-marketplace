"""The background worker's schedule (blueprint F.8, P2).

`scheduled_jobs` holds one row per scheduled job: when it runs next and how
its last run went. A worker runs a job only while holding the row's lock.
The outbox needed no change: its table has been in the schema since 0001.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-16 20:10:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('scheduled_jobs',
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('next_run_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_succeeded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_result', sa.Integer(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('consecutive_failures', sa.Integer(), server_default='0', nullable=False),
    sa.CheckConstraint('consecutive_failures >= 0', name=op.f('ck_scheduled_jobs_consecutive_failures_non_negative')),
    sa.PrimaryKeyConstraint('name', name=op.f('pk_scheduled_jobs'))
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
