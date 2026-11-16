"""Fix the ledger balance trigger.

Migration 0002 attached one trigger function to two tables and chose the
transaction id with a CASE over `tg_table_name`. PL/pgSQL plans both branches
of that expression against the row type, and `ledger_transactions` has no
`transaction_id` column, so every insert into either table failed with
"record new has no field transaction_id". No ledger write could succeed.

The database-protection tests found this before any ledger code was written.
Nothing had been deployed. Migrations are forward-only (blueprint F.3), so the
correction is this new migration rather than an edit to 0002.

The check itself is unchanged: at commit, every ledger transaction touched in
the database transaction must have at least two entries and equal debits and
credits. It now lives in one helper, called by one small trigger function per
table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-16 17:30:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        create function markx_assert_ledger_balanced(txn_id uuid) returns void
        language plpgsql as $$
        declare
          debits bigint;
          credits bigint;
          entry_count integer;
        begin
          select coalesce(sum(amount_santim) filter (where direction = 'debit'), 0),
                 coalesce(sum(amount_santim) filter (where direction = 'credit'), 0),
                 count(*)
            into debits, credits, entry_count
            from ledger_entries
           where transaction_id = txn_id;

          if entry_count < 2 or debits <> credits then
            raise exception
              'ledger transaction % is not balanced: % entries, debits %, credits %',
              txn_id, entry_count, debits, credits
              using errcode = 'check_violation';
          end if;
        end
        $$
        """
    )
    # Replaces the broken body; the trigger on ledger_entries keeps pointing here.
    op.execute(
        """
        create or replace function markx_check_ledger_balanced() returns trigger
        language plpgsql as $$
        begin
          perform markx_assert_ledger_balanced(new.transaction_id);
          return null;
        end
        $$
        """
    )
    op.execute(
        """
        create function markx_check_ledger_transaction_has_entries() returns trigger
        language plpgsql as $$
        begin
          perform markx_assert_ledger_balanced(new.id);
          return null;
        end
        $$
        """
    )
    op.execute("drop trigger trg_ledger_transactions_have_entries on ledger_transactions")
    op.execute(
        """
        create constraint trigger trg_ledger_transactions_have_entries
        after insert on ledger_transactions
        deferrable initially deferred
        for each row execute function markx_check_ledger_transaction_has_entries()
        """
    )


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
