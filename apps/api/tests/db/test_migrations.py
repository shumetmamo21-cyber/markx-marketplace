"""The migration test (blueprint P.3): upgrade from empty, and no difference
between the models and the migrations."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from markx.core.db import Base
from tests.conftest import API_DIR


def test_database_is_at_the_latest_revision(migrator_engine: Engine) -> None:
    script = ScriptDirectory(str(API_DIR / "migrations"))
    with migrator_engine.connect() as connection:
        current = connection.execute(text("select version_num from alembic_version")).scalar_one()
    assert current == script.get_current_head()


def test_migrations_have_one_head(migrator_engine: Engine) -> None:
    script = ScriptDirectory(str(API_DIR / "migrations"))
    assert len(script.get_heads()) == 1


def test_models_and_migrations_do_not_differ(migrator_engine: Engine) -> None:
    with migrator_engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        )
        differences = compare_metadata(context, Base.metadata)
    assert differences == [], f"models and migrations have drifted: {differences}"


def test_trigram_extension_is_enabled(migrator_engine: Engine) -> None:
    with migrator_engine.connect() as connection:
        assert connection.execute(
            text("select count(*) from pg_extension where extname = 'pg_trgm'")
        ).scalar_one() == 1


def test_database_uses_the_builtin_utf8_locale(migrator_engine: Engine) -> None:
    # Trigram matching on Ethiopic text depends on it (docs/reports).
    with migrator_engine.connect() as connection:
        provider, locale = connection.execute(
            text("select datlocprovider::text, datlocale from pg_database where datname = current_database()")
        ).one()
    assert (provider, locale) == ("b", "C.UTF-8")


def test_trigrams_exist_for_ethiopic_text(migrator_engine: Engine) -> None:
    with migrator_engine.connect() as connection:
        trigrams = connection.execute(text("select cardinality(show_trgm('ስልክ'))")).scalar_one()
        similarity = connection.execute(
            text("select word_similarity('ስልክ', 'አዲስ ስልክ ዋጋ')")
        ).scalar_one()
    assert trigrams == 4
    assert similarity == 1.0


def test_every_table_has_a_primary_key(migrator_engine: Engine) -> None:
    with migrator_engine.connect() as connection:
        missing = connection.execute(
            text(
                """
                select c.relname from pg_class c
                join pg_namespace n on n.oid = c.relnamespace
                where n.nspname = 'public' and c.relkind = 'r'
                  and not exists (select 1 from pg_constraint p where p.conrelid = c.oid and p.contype = 'p')
                """
            )
        ).scalars().all()
    assert missing == []


def test_no_foreign_key_cascades_into_orders_or_money(migrator_engine: Engine) -> None:
    """Financial tables use restricting keys (blueprint G.8 rule 3)."""
    protected = (
        "orders", "seller_orders", "order_items", "order_status_events", "payment_intents",
        "payment_attempts", "fee_charges", "ledger_transactions", "ledger_entries",
        "ledger_accounts", "shipments", "tracking_events", "inventory_movements",
        "inventory_reservations", "offer_price_history", "reviews", "dispute_cases",
    )  # fmt: skip
    with migrator_engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                select conrelid::regclass::text as child, confrelid::regclass::text as parent,
                       confdeltype::text as on_delete
                from pg_constraint where contype = 'f' and connamespace = 'public'::regnamespace
                """
            )
        ).all()
    # 'a' is NO ACTION and 'r' is RESTRICT; both refuse the delete.
    offenders = [(c, p, d) for c, p, d in rows if c in protected and d not in ("a", "r")]
    assert offenders == []
