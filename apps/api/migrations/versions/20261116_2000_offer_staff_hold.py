"""A staff takedown holds (found in the session-three review).

`offers.removed_by_staff_at` records that staff took a listing down. Until
staff lift the hold the seller cannot list that variant and condition again,
and a CHECK keeps a held offer `removed` whatever the code does. Before this,
a seller could undo a takedown by simply creating the offer again.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-16 20:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('offers', sa.Column('removed_by_staff_at', sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f('ck_offers_staff_hold_means_removed'), 'offers',
        "removed_by_staff_at is null or status = 'removed'",
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3).
    raise NotImplementedError("migrations are forward-only")
