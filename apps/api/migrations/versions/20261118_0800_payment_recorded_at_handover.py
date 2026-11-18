"""A direct payment is recorded only once the goods are handed over (D-087).

The founder's decision F-09, option 2: a seller may no longer record that the
buyer paid in advance. The service refuses it (`PAYABLE`); this trigger is the
database's half of the same rule.

It checks only the moment a payment is recorded (`paid_at` going from empty to
set, or a new row arriving with it set), never a row that already holds one.
So a part paid in advance before this rule keeps its record and can still go
ahead (dispatch, handover, completion) without error; nothing here changes or
deletes data. A table CHECK could not do that: it would refuse every later
move of such a part.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-18 08:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = '0014'
down_revision: str | None = '0013'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        create function markx_check_payment_recorded_at_handover() returns trigger
        language plpgsql as $$
        begin
          if new.paid_at is not null
             and (tg_op = 'INSERT' or old.paid_at is null)
             and new.status not in ('delivered', 'completed', 'disputed') then
            raise exception
              'a payment is recorded only once the goods are handed over, not while %',
              new.status
              using errcode = 'check_violation',
                    constraint = 'seller_orders_payment_at_handover';
          end if;
          return new;
        end
        $$
        """
    )
    op.execute(
        """
        create trigger trg_seller_orders_payment_at_handover
        before insert or update of paid_at on seller_orders
        for each row execute function markx_check_payment_recorded_at_handover()
        """
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
