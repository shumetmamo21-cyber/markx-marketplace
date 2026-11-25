"""Guest checkout (C-07; D-108): an order whose buyer is a guest, not an account.

Sign-in is Telegram only (decision SI-1), so a buyer without Telegram, or
anyone while Telegram is blocked, may order as a guest with a name, a
delivery address and a phone number. The number is NOT confirmed, so a
guest order belongs to no account: `orders.buyer_user_id` may now be empty,
and then the order carries the guest's number instead (`guest_phone`), for
the buying limits counted per number. It also carries two keyed hashes,
never the values themselves: of the network address the order came from
(the limits counted per address) and of the browser's cart secret (which
scopes the order's idempotency key to the browser that sent it).

The database holds the rules a guest order must keep:

* exactly one buyer, an account or a guest (`ck_orders_one_buyer`);
* the guest's number in international form;
* a guest pays at the door only: a direct order, never a prepaid one
  (`ck_orders_guest_pays_at_the_door`);
* both hashes present, 32 bytes each, exactly when the buyer is a guest;
* one order per browser and idempotency key.

Existing rows: every order has an account as its buyer, so every check
holds and nothing is changed or deleted.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-24 10:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHONE_PATTERN = r"^\+251[79][0-9]{8}$"


def upgrade() -> None:
    op.alter_column("orders", "buyer_user_id", existing_type=sa.UUID(), nullable=True)
    op.add_column("orders", sa.Column("guest_phone", sa.Text(), nullable=True))
    op.add_column("orders", sa.Column("guest_network_hash", sa.LargeBinary(), nullable=True))
    op.add_column("orders", sa.Column("guest_browser_hash", sa.LargeBinary(), nullable=True))
    op.create_check_constraint(
        op.f("ck_orders_one_buyer"), "orders", "(buyer_user_id is null) <> (guest_phone is null)"
    )
    op.create_check_constraint(
        op.f("ck_orders_guest_phone_international_format"),
        "orders",
        f"guest_phone is null or guest_phone ~ '{PHONE_PATTERN}'",
    )
    op.create_check_constraint(
        op.f("ck_orders_guest_pays_at_the_door"),
        "orders",
        "guest_phone is null or payment_mode = 'direct'",
    )
    op.create_check_constraint(
        op.f("ck_orders_guest_keys_with_guest"),
        "orders",
        "(guest_phone is null) = (guest_network_hash is null) "
        "and (guest_phone is null) = (guest_browser_hash is null)",
    )
    op.create_check_constraint(
        op.f("ck_orders_guest_key_lengths"),
        "orders",
        "(guest_network_hash is null or octet_length(guest_network_hash) = 32) "
        "and (guest_browser_hash is null or octet_length(guest_browser_hash) = 32)",
    )
    op.create_index(
        "uq_orders_guest_browser_idempotency_key",
        "orders",
        ["guest_browser_hash", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("guest_browser_hash is not null"),
    )
    op.create_index(
        "ix_orders_guest_phone",
        "orders",
        ["guest_phone"],
        unique=False,
        postgresql_where=sa.text("guest_phone is not null"),
    )
    op.create_index(
        "ix_orders_guest_network_hash",
        "orders",
        ["guest_network_hash"],
        unique=False,
        postgresql_where=sa.text("guest_network_hash is not null"),
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
