"""The commission rule and its cap per order, copied onto each order line (D-099).

`commission_rules.cap_santim` was stored but never applied (independent
audit, section 11; D-086, D-088 item 1). A line now keeps the rule its rate
came from and that rule's cap, copied at placement like the rate (D-042,
J.8), so the fee at completion can apply the cap and a later change to the
rule never alters a past order.

Both columns are empty on every existing line: no commission rule exists
(D-088), so no existing line had a rate, a rule or a cap. Nothing is changed
or deleted.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-20 09:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0019'
down_revision: str | None = '0018'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'order_items',
        sa.Column('commission_rule_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column('order_items', sa.Column('commission_cap_santim', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        op.f('fk_order_items_commission_rule_id_commission_rules'),
        'order_items',
        'commission_rules',
        ['commission_rule_id'],
        ['id'],
        ondelete='RESTRICT',
    )
    op.create_check_constraint(
        op.f('ck_order_items_commission_cap_non_negative'),
        'order_items',
        'commission_cap_santim is null or commission_cap_santim >= 0',
    )
    op.create_check_constraint(
        op.f('ck_order_items_commission_cap_has_rule'),
        'order_items',
        'commission_cap_santim is null or commission_rule_id is not null',
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
