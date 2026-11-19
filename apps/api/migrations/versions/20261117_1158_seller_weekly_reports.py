"""Seller weekly reports (blueprint S-26, K.5; D-069).

`seller_weekly_reports` keeps each store's weekly performance message as it
was sent: one row per store and week (Monday, Addis Ababa time), which is
also what makes sending them safe to run twice.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-17 11:58:09.613055+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0012'
down_revision: str | None = '0011'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('seller_weekly_reports',
    sa.Column('seller_id', sa.UUID(), nullable=False),
    sa.Column('week_start', sa.Date(), nullable=False),
    sa.Column('figures', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('extract(isodow from week_start) = 1', name=op.f('ck_seller_weekly_reports_week_starts_on_monday')),
    sa.ForeignKeyConstraint(['seller_id'], ['sellers.id'], name=op.f('fk_seller_weekly_reports_seller_id_sellers'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_seller_weekly_reports')),
    sa.UniqueConstraint('seller_id', 'week_start', name=op.f('uq_seller_weekly_reports_seller_id_week_start'))
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
