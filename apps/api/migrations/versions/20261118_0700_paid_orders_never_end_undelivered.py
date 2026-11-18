"""A paid seller order never ends undelivered (D-086).

A seller may record a direct payment from `confirmed` on (D.12). Until now a
part with a recorded payment could still be cancelled by the buyer or by the
overdue-fulfilment job, or marked returned, leaving the buyer's money with no
record of its way back. The service now refuses those ends and asks staff to
settle; this constraint is the database's half of the same rule.

Existing rows are checked when it is added: on a database that already holds
such a part, the upgrade stops with the constraint's name, and the part must be
looked at by a person (nothing here deletes or changes data).

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-18 07:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = '0013'
down_revision: str | None = '0012'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        op.f('ck_seller_orders_paid_order_not_ended_undelivered'),
        'seller_orders',
        "paid_at is null or status not in ('declined', 'expired', 'cancelled', 'returned')",
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
