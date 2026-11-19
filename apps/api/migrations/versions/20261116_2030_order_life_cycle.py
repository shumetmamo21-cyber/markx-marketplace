"""The seller order life cycle, enforced by the database (blueprint G.6, G.8).

Checkout and seller orders (P9, P10) needed no new table: the first migration
already holds carts, orders, seller orders, items, status events, reservations
and shipments. This migration adds what a table definition cannot say.

* `markx_seller_order_move_allowed(from, to)`: the state diagram of G.6.
* A trigger refuses a seller order that is not created as `placed`, and any
  status change that is not an arrow in that diagram, whatever the code does.
* A deferred constraint trigger refuses to commit a seller order whose current
  status has no row in `order_status_events`: every move is in the log.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-16 20:30:00+00:00
"""

from collections.abc import Sequence

from alembic import op


revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        create function markx_seller_order_move_allowed(from_status text, to_status text)
        returns boolean language sql immutable as $$
          select (from_status, to_status) in (
            ('placed', 'confirmed'), ('placed', 'declined'), ('placed', 'expired'),
            ('placed', 'cancelled'),
            ('confirmed', 'ready'), ('confirmed', 'paid'), ('confirmed', 'expired'),
            ('confirmed', 'cancelled'),
            ('paid', 'ready'), ('paid', 'refunded'),
            ('ready', 'out_for_delivery'), ('ready', 'delivered'), ('ready', 'cancelled'),
            ('out_for_delivery', 'delivered'), ('out_for_delivery', 'delivery_failed'),
            ('delivery_failed', 'out_for_delivery'), ('delivery_failed', 'returned'),
            ('delivered', 'completed'), ('delivered', 'disputed'),
            ('disputed', 'completed'), ('disputed', 'refunded')
          )
        $$
        """
    )
    op.execute(
        """
        create function markx_check_seller_order_move() returns trigger
        language plpgsql as $$
        begin
          if tg_op = 'INSERT' then
            if new.status <> 'placed' then
              raise exception 'a seller order starts as placed, not %', new.status
                using errcode = 'check_violation',
                      constraint = 'seller_orders_starts_placed';
            end if;
          elsif new.status is distinct from old.status
                and not markx_seller_order_move_allowed(old.status, new.status) then
            raise exception 'a seller order cannot move from % to %', old.status, new.status
              using errcode = 'check_violation',
                    constraint = 'seller_orders_move_allowed';
          end if;
          return new;
        end
        $$
        """
    )
    op.execute(
        """
        create trigger trg_seller_orders_move
        before insert or update of status on seller_orders
        for each row execute function markx_check_seller_order_move()
        """
    )
    # Checked at commit, so the status and its event can be written in either
    # order inside one transaction.
    op.execute(
        """
        create function markx_check_seller_order_has_event() returns trigger
        language plpgsql as $$
        begin
          if not exists (
            select 1
              from seller_orders s
              join order_status_events e on e.seller_order_id = s.id and e.to_status = s.status
             where s.id = new.id
          ) then
            raise exception 'seller order % has no status event for its status', new.id
              using errcode = 'check_violation',
                    constraint = 'seller_orders_status_has_event';
          end if;
          return null;
        end
        $$
        """
    )
    op.execute(
        """
        create constraint trigger trg_seller_orders_status_has_event
        after insert or update of status on seller_orders
        deferrable initially deferred
        for each row execute function markx_check_seller_order_has_event()
        """
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3).
    raise NotImplementedError("migrations are forward-only")
