# Migrations

Alembic, forward only (AGENTS.md: "migrations are forward-only"; no
downgrade is ever run on a server).

- **One runner.** Only the `migrate` service (profile `migrate`) runs
  `alembic upgrade head`, and only `deploy.sh` starts it, once per release,
  after a fresh backup. The API, the worker and the web app never migrate;
  the API's own settings hold the schema owner's name without its password.
- **One at a time.** `migrations/env.py` takes a PostgreSQL advisory lock
  before reading the schema. A second run waits, then finds nothing to do
  (**Tested**: `tests/db/test_migration_lock.py`; the rehearsal starts two at
  once).
- **Readiness follows the schema.** A release whose migrations have not run
  is `behind` and not ready; a release older than the database is `ahead`
  and not ready unless a rollback was acknowledged (`rollback.md`).

## Before a release with a new migration

1. Read the migration. Does it lock a busy table for long (a new index
   without `CONCURRENTLY`, a column with a volatile default, a constraint
   checked against every row)? Then deploy at a quiet hour, and say so in
   the release notes.
2. Is it **backward-compatible**: can the previous release run against the
   migrated schema? Adding a table, a nullable column or an index usually
   is; renaming or dropping a column, or a new trigger that refuses what the
   old code writes, is not. Write the answer in the release notes; the
   rollback runbook needs it.
3. CI ran it from empty (`alembic upgrade head`, `alembic check`) and the
   whole suite on it. The rehearsal ran it on a fresh database.

## Running it by hand (only if deploy.sh cannot)

```bash
infra/production/deploy.sh backup
docker compose -f infra/production/compose.yaml --env-file /etc/markx/compose.env \
  --profile migrate run --rm migrate
```

`MARKX_RELEASE` must name the release being migrated to.

## If a migration fails

Each upgrade runs in one transaction: a failed migration leaves the schema
as it was. Read the error in the output, keep the old release running (it
is still ready), fix the migration in a new commit, and deploy again. Never
edit the `alembic_version` table by hand.

## If a migration ran and was wrong

Do not run a downgrade. Write a new forward migration that corrects it. If
data was damaged, `backup-and-restore.md`, "Recovering the database".
