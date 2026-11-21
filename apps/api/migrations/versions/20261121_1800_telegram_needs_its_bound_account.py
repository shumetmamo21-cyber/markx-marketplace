"""An account connected to Telegram always remembers its Telegram account (D-104).

Migration 0021 added `users.bound_telegram_id` (the Telegram account an
account belongs to, never forgotten) and the rule "`telegram_id`, when set,
is the bound account": `telegram_id is null or telegram_id =
bound_telegram_id`. In SQL that rule let one state through: `telegram_id`
set and `bound_telegram_id` empty, because `x = null` is unknown, not false,
and a check constraint only refuses false. That account would be connected
to Telegram (messages go there) while MarkX remembers no Telegram account
for it, so the recycled-number protection (D-101 section 2a) would have
nothing to compare with. Found in the pull request #9 review; no part of
the program creates that state today.

The rule now says it in full: `telegram_id` is empty, or the bound account
is set and `telegram_id` is that account.

Existing rows: an account in that state (none is expected; nothing is
deployed) becomes bound to the Telegram account it is connected to, as
migration 0021 did for every connected account. If another account is
already bound to that Telegram account, the unique rule stops the migration
with an error, so a person can look: nothing is guessed.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-21 18:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = '0022'
down_revision: str | None = '0021'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        'update users set bound_telegram_id = telegram_id '
        'where telegram_id is not null and bound_telegram_id is null'
    )
    op.drop_constraint(op.f('ck_users_telegram_id_is_the_bound_one'), 'users', type_='check')
    op.create_check_constraint(
        op.f('ck_users_telegram_id_is_the_bound_one'),
        'users',
        'telegram_id is null or (bound_telegram_id is not null and telegram_id = bound_telegram_id)',
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
