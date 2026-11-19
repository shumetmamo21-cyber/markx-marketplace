"""History protection, the balanced ledger and role restrictions.

Rules from blueprint G.8 that a column constraint cannot express:

* Rule 5: the ledger is append-only and balanced in every transaction.
* Rule 6: the audit log is insert-only, and the application's database role
  cannot update or delete its rows.
* History tables only grow (G.1).

Each rule is enforced twice on purpose. The application role loses the UPDATE
and DELETE privileges, and a trigger refuses both for every role, the schema
owner included. A correction is always a new row.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16 15:40:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_TABLES = (
    "audit_log",
    "order_status_events",
    "offer_price_history",
    "inventory_movements",
    "tracking_events",
    "ledger_transactions",
    "ledger_entries",
)

# Tables that hold credentials or sensitive account data. The analysis role
# has no reason to read them.
HIDDEN_FROM_READONLY = (
    "sessions",
    "otp_challenges",
    "otp_locks",
    "staff_members",
    "seller_payout_accounts",
)


def upgrade() -> None:
    op.execute(
        """
        create function markx_forbid_change() returns trigger
        language plpgsql as $$
        begin
          raise exception 'table "%" is append-only: % is not allowed', tg_table_name, tg_op
            using errcode = 'insufficient_privilege';
        end
        $$
        """
    )
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"""
            create trigger trg_{table}_append_only
            before update or delete on {table}
            for each row execute function markx_forbid_change()
            """
        )
        op.execute(f"revoke update, delete, truncate on {table} from markx_app")

    # Debits equal credits in every ledger transaction. The check is deferred to
    # commit, so the entries of one transaction can be inserted one by one.
    op.execute(
        """
        create function markx_check_ledger_balanced() returns trigger
        language plpgsql as $$
        declare
          txn_id uuid := case tg_table_name
                           when 'ledger_entries' then new.transaction_id
                           else new.id
                         end;
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
          return null;
        end
        $$
        """
    )
    op.execute(
        """
        create constraint trigger trg_ledger_entries_balanced
        after insert on ledger_entries
        deferrable initially deferred
        for each row execute function markx_check_ledger_balanced()
        """
    )
    # A transaction with no entries at all is also unbalanced.
    op.execute(
        """
        create constraint trigger trg_ledger_transactions_have_entries
        after insert on ledger_transactions
        deferrable initially deferred
        for each row execute function markx_check_ledger_balanced()
        """
    )

    for table in HIDDEN_FROM_READONLY:
        op.execute(f"revoke all on {table} from markx_readonly")


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
