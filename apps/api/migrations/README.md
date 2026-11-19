# Migrations

Forward-only Alembic migrations (blueprint F.3). Nobody changes a schema by hand.

- Create one: `make migration name="add something"` and then **read and edit it**.
- Apply: `make migrate`.
- A mistake is fixed by a new migration, not by a downgrade.
