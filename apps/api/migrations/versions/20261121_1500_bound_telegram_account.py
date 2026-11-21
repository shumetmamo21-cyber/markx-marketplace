"""Remember the Telegram account an account belongs to, for ever (D-101, P-101-6).

`users.bound_telegram_id` is the Telegram account this MarkX account belongs
to. It is set the first time any Telegram account is attached to the account
(signing in with Telegram, the bot's connection link or the Mini App) and is
never cleared: "Disconnect Telegram" clears only `telegram_id`, which carries
messages. Only the bound Telegram account may sign in to the account again,
so a stranger who is later given the same (recycled) phone number cannot
take it over.

* Unique: one Telegram account belongs to at most one MarkX account.
* `telegram_id`, when set, must be the bound account.
* A trigger refuses to change or clear it once set, for every role.
  Moving an account to another Telegram account is for support (F-24) and
  will need its own, audited, migration or tool.

Existing rows: an account connected today becomes bound to its Telegram
account. An account that disconnected before this migration has no record
of which Telegram account it had (the id was cleared and was never written
to the audit log), so it stays unbound; nothing is deployed, so no real
account is in that state.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-21 15:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0021'
down_revision: str | None = '0020'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('bound_telegram_id', sa.BigInteger(), nullable=True))
    op.execute('update users set bound_telegram_id = telegram_id where telegram_id is not null')
    op.create_unique_constraint(op.f('uq_users_bound_telegram_id'), 'users', ['bound_telegram_id'])
    op.create_check_constraint(
        op.f('ck_users_telegram_id_is_the_bound_one'),
        'users',
        'telegram_id is null or telegram_id = bound_telegram_id',
    )
    op.execute(
        """
        create function markx_keep_bound_telegram() returns trigger
        language plpgsql as $$
        begin
          if old.bound_telegram_id is not null
             and new.bound_telegram_id is distinct from old.bound_telegram_id then
            raise exception 'an account''s Telegram account is never changed or forgotten'
              using errcode = 'check_violation';
          end if;
          return new;
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_users_keep_bound_telegram
        before update of bound_telegram_id on users
        for each row execute function markx_keep_bound_telegram()
        """
    )


def downgrade() -> None:
    # Migrations are forward-only (blueprint F.3). A mistake is corrected by a
    # new migration, never by rolling the schema back.
    raise NotImplementedError("migrations are forward-only")
