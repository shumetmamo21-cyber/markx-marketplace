"""Rules the database enforces by itself (blueprint F.3, G.8).

These tests bypass the application on purpose. They connect as each of the
three roles and try to break a rule with plain SQL, because a rule that only
application code enforces is not a rule.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from markx.audit import service as audit
from markx.core.db import get_engine
from markx.core.ids import uuid7

APPEND_ONLY = (
    "audit_log",
    "order_status_events",
    "offer_price_history",
    "inventory_movements",
    "tracking_events",
    "ledger_transactions",
    "ledger_entries",
)


def _audit_row(db: Session) -> None:
    audit.record(
        db, actor_type="system", actor_user_id=None, action="test.event",
        target_type="thing", target_id="1", before={"a": 1}, after={"a": 2},
    )  # fmt: skip
    db.commit()


# ------------------------------------------------------------------ audit log


def test_the_application_role_can_add_audit_rows(db: Session) -> None:
    _audit_row(db)
    assert db.execute(text("select count(*) from audit_log")).scalar_one() == 1


@pytest.mark.parametrize(
    "statement",
    [
        "update audit_log set action = 'rewritten'",
        "delete from audit_log",
        "truncate audit_log",
    ],
)
def test_the_application_role_cannot_rewrite_the_audit_log(db: Session, statement: str) -> None:
    """Blueprint P2: the database refuses an update or delete of an audit row
    by the application role."""
    _audit_row(db)
    with get_engine().connect() as connection, pytest.raises(ProgrammingError) as excinfo:
        connection.execute(text(statement))
    assert "permission denied" in str(excinfo.value)
    assert db.execute(text("select action from audit_log")).scalar_one() == "test.event"


@pytest.mark.parametrize(
    "statement", ["update audit_log set action = 'x'", "delete from audit_log"]
)
def test_not_even_the_schema_owner_can_rewrite_the_audit_log(
    db: Session, migrator_engine: Engine, statement: str
) -> None:
    _audit_row(db)
    with migrator_engine.connect() as connection, pytest.raises(DBAPIError) as excinfo:
        connection.execute(text(statement))
    assert "append-only" in str(excinfo.value)
    assert db.execute(text("select action from audit_log")).scalar_one() == "test.event"


@pytest.mark.parametrize("table", APPEND_ONLY)
def test_history_tables_grant_no_update_or_delete_to_the_application(
    migrator_engine: Engine, table: str
) -> None:
    with migrator_engine.connect() as connection:
        privileges = set(
            connection.execute(
                text(
                    "select privilege_type from information_schema.role_table_grants "
                    "where grantee = 'markx_app' and table_name = :table"
                ),
                {"table": table},
            ).scalars()
        )
    assert privileges == {"SELECT", "INSERT"}


@pytest.mark.parametrize("table", APPEND_ONLY)
def test_every_history_table_has_the_append_only_trigger(
    migrator_engine: Engine, table: str
) -> None:
    with migrator_engine.connect() as connection:
        triggers = (
            connection.execute(
                text(
                    "select tgname from pg_trigger where tgrelid = cast(:table as regclass) "
                    "and not tgisinternal and tgname like '%append_only'"
                ),
                {"table": table},
            )
            .scalars()
            .all()
        )
    assert triggers == [f"trg_{table}_append_only"]


# --------------------------------------------------------------------- ledger


def _account(connection, code: str) -> uuid.UUID:  # type: ignore[no-untyped-def]
    account_id = uuid7()
    connection.execute(
        text(
            "insert into ledger_accounts (id, code, kind, name) values (:id, :code, 'asset', :code)"
        ),
        {"id": account_id, "code": code},
    )
    return account_id


def _post(connection, entries: list[tuple[uuid.UUID, str, int]]) -> uuid.UUID:  # type: ignore[no-untyped-def]
    txn_id = uuid7()
    connection.execute(
        text(
            "insert into ledger_transactions (id, idempotency_key, kind, reference_type, reference_id) "
            "values (:id, :key, 'test', 'test', :id)"
        ),
        {"id": txn_id, "key": str(txn_id)},
    )
    for account_id, direction, amount in entries:
        connection.execute(
            text(
                "insert into ledger_entries (id, transaction_id, account_id, direction, amount_santim) "
                "values (:id, :txn, :account, :direction, :amount)"
            ),
            {
                "id": uuid7(),
                "txn": txn_id,
                "account": account_id,
                "direction": direction,
                "amount": amount,
            },
        )
    return txn_id


def test_a_balanced_ledger_transaction_commits() -> None:
    with get_engine().begin() as connection:
        a, b = _account(connection, "a"), _account(connection, "b")
        _post(connection, [(a, "debit", 265_000), (b, "credit", 265_000)])
    with get_engine().connect() as connection:
        assert connection.execute(text("select count(*) from ledger_entries")).scalar_one() == 2


def test_a_split_across_three_accounts_commits() -> None:
    # Blueprint G.10: goods 2,500 + delivery 150 at a 7% fee.
    with get_engine().begin() as connection:
        held = _account(connection, "buyer_funds_held")
        seller = _account(connection, "seller_payable")
        fee = _account(connection, "commission_income")
        delivery = _account(connection, "delivery_payable")
        _post(
            connection,
            [
                (held, "debit", 265_000),
                (seller, "credit", 232_500),
                (fee, "credit", 17_500),
                (delivery, "credit", 15_000),
            ],
        )


@pytest.mark.parametrize(
    "entries",
    [
        [("debit", 100), ("credit", 99)],  # one santim out
        [("debit", 100), ("debit", 100)],  # no credit side
        [("debit", 100)],  # a single entry
        [],  # no entries at all
    ],
)
def test_an_unbalanced_ledger_transaction_is_refused_at_commit(
    entries: list[tuple[str, int]],
) -> None:
    connection = get_engine().connect()
    transaction = connection.begin()
    a, b = _account(connection, "a"), _account(connection, "b")
    _post(
        connection,
        [((a, b)[i % 2], direction, amount) for i, (direction, amount) in enumerate(entries)],
    )
    with pytest.raises(IntegrityError) as excinfo:
        transaction.commit()
    assert "is not balanced" in str(excinfo.value)
    connection.close()
    with get_engine().connect() as check:
        assert check.execute(text("select count(*) from ledger_transactions")).scalar_one() == 0
        assert check.execute(text("select count(*) from ledger_entries")).scalar_one() == 0


def test_ledger_amounts_must_be_positive() -> None:
    with get_engine().connect() as connection:
        connection.begin()
        a, b = _account(connection, "a"), _account(connection, "b")
        with pytest.raises(IntegrityError) as excinfo:
            _post(connection, [(a, "debit", 0), (b, "credit", 0)])
        assert "amount_positive" in str(excinfo.value)


def test_a_ledger_entry_cannot_be_changed_after_it_is_written(migrator_engine: Engine) -> None:
    with get_engine().begin() as connection:
        a, b = _account(connection, "a"), _account(connection, "b")
        _post(connection, [(a, "debit", 500), (b, "credit", 500)])
    for engine, expected in ((get_engine(), "permission denied"), (migrator_engine, "append-only")):
        for statement in (
            "update ledger_entries set amount_santim = 1",
            "delete from ledger_entries",
        ):
            with engine.connect() as connection, pytest.raises(DBAPIError) as excinfo:
                connection.execute(text(statement))
            assert expected in str(excinfo.value)


def test_a_ledger_idempotency_key_is_used_once() -> None:
    with get_engine().begin() as connection:
        a, b = _account(connection, "a"), _account(connection, "b")
        txn_id = _post(connection, [(a, "debit", 500), (b, "credit", 500)])
    with get_engine().connect() as connection:
        connection.begin()
        with pytest.raises(IntegrityError) as excinfo:
            connection.execute(
                text(
                    "insert into ledger_transactions (id, idempotency_key, kind, reference_type, reference_id) "
                    "values (:id, :key, 'test', 'test', :id)"
                ),
                {"id": uuid7(), "key": str(txn_id)},
            )
        assert "uq_ledger_transactions_idempotency_key" in str(excinfo.value)


# ---------------------------------------------------------------------- roles


def test_the_application_role_cannot_change_the_schema() -> None:
    for statement in (
        "create table sneaky (id int)",
        "drop table users",
        "alter table users add column backdoor text",
        "drop trigger trg_audit_log_append_only on audit_log",
        "alter table audit_log disable trigger all",
    ):
        with get_engine().connect() as connection, pytest.raises(ProgrammingError):
            connection.execute(text(statement))


def test_the_readonly_role_reads_business_data_but_writes_nothing(readonly_engine: Engine) -> None:
    with readonly_engine.connect() as connection:
        assert connection.execute(text("select count(*) from products")).scalar_one() == 0
        assert connection.execute(text("select count(*) from orders")).scalar_one() == 0
    for statement in (
        "insert into brands (id, slug, name) values (gen_random_uuid(), 'x', 'X')",
        "update users set name = 'x'",
        "delete from products",
    ):
        with readonly_engine.connect() as connection, pytest.raises(ProgrammingError) as excinfo:
            connection.execute(text(statement))
        assert "permission denied" in str(excinfo.value)


@pytest.mark.parametrize(
    "table", ["sessions", "otp_challenges", "otp_locks", "staff_members", "seller_payout_accounts"]
)
def test_the_readonly_role_cannot_read_credentials(readonly_engine: Engine, table: str) -> None:
    with readonly_engine.connect() as connection, pytest.raises(ProgrammingError) as excinfo:
        connection.execute(text(f"select * from {table} limit 1"))
    assert "permission denied" in str(excinfo.value)


def test_no_role_is_a_superuser_or_can_create_databases(migrator_engine: Engine) -> None:
    with migrator_engine.connect() as connection:
        rows = connection.execute(
            text(
                "select rolname, rolsuper, rolcreatedb, rolcreaterole from pg_roles where rolname like 'markx_%'"
            )
        ).all()
    assert len(rows) == 3
    assert all(
        not (superuser or createdb or createrole) for _, superuser, createdb, createrole in rows
    )


# ------------------------------------------------- column and table constraints


def test_stock_can_never_go_negative_or_be_over_reserved(migrator_engine: Engine) -> None:
    """Blueprint G.8 rule 1 and G.9: the inventory row itself refuses bad numbers."""
    with migrator_engine.connect() as connection:
        constraints = set(
            connection.execute(
                text(
                    "select conname from pg_constraint where conrelid = 'inventory'::regclass and contype = 'c'"
                )
            ).scalars()
        )
    assert {
        "ck_inventory_on_hand_non_negative",
        "ck_inventory_reserved_non_negative",
        "ck_inventory_reserved_within_on_hand",
    } <= constraints


def test_a_phone_number_must_be_in_international_form(db: Session) -> None:
    for bad in ("0911234567", "+251811234567", "+25191123456", "911234567", "+14155550100"):
        with pytest.raises(IntegrityError) as excinfo:
            db.execute(
                text("insert into users (id, phone) values (:id, :phone)"),
                {"id": uuid7(), "phone": bad},
            )
        assert "phone_international_format" in str(excinfo.value)
        db.rollback()
    db.execute(text("insert into users (id, phone) values (:id, '+251911234567')"), {"id": uuid7()})
    db.commit()


def test_one_account_per_phone_number(db: Session) -> None:
    db.execute(text("insert into users (id, phone) values (:id, '+251911234567')"), {"id": uuid7()})
    with pytest.raises(IntegrityError) as excinfo:
        db.execute(
            text("insert into users (id, phone) values (:id, '+251911234567')"), {"id": uuid7()}
        )
    assert "uq_users_phone" in str(excinfo.value)


def test_status_columns_accept_only_their_allowed_values(db: Session) -> None:
    """Blueprint G.8 rule 7."""
    with pytest.raises(IntegrityError) as excinfo:
        db.execute(
            text("insert into users (id, phone, status) values (:id, '+251911234567', 'godmode')"),
            {"id": uuid7()},
        )
    assert "ck_users_status_allowed" in str(excinfo.value)
