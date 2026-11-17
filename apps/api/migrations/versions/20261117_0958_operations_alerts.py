"""Operations alerts (blueprint F.8, F.12; D-064).

`ops_alerts` records what the scheduled checks found wrong: one open alert
per key, touched while the problem lasts, resolved when it is gone, and
kept afterwards as the record of what went wrong and for how long.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-17 09:58:26.228717+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0009'
down_revision: str | None = '0008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('ops_alerts',
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('severity', sa.Text(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('occurrences', sa.Integer(), server_default='1', nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint("severity in ('warning', 'critical')", name=op.f('ck_ops_alerts_severity_allowed')),
    sa.CheckConstraint("source in ('watch', 'reconcile')", name=op.f('ck_ops_alerts_source_allowed')),
    sa.CheckConstraint('occurrences >= 1', name=op.f('ck_ops_alerts_occurrences_positive')),
    sa.CheckConstraint('resolved_at is null or resolved_at >= first_seen_at', name=op.f('ck_ops_alerts_resolved_after')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ops_alerts'))
    )
    op.create_index('ix_ops_alerts_first_seen', 'ops_alerts', ['first_seen_at'], unique=False)
    op.create_index('uq_ops_alerts_open_key', 'ops_alerts', ['key'], unique=True, postgresql_where=sa.text('resolved_at is null'))


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
