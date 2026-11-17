# Setup

How to run and test MarkX on a laptop. Every command here was run again on
17 November 2026 by the fifth engineering session. Only the API exists so
far; there is no web app to start.

Nothing here touches AWS or any paid service.

## What you need

- **Python 3.13** and **[uv](https://docs.astral.sh/uv/)** (the Python package manager)
- **Docker**, to run PostgreSQL 17
- **psql**, the PostgreSQL command-line client

## 1. Start PostgreSQL 17

```bash
docker run -d --name markx-pg \
  -e POSTGRES_PASSWORD=postgres_dev_only \
  -e POSTGRES_INITDB_ARGS="--locale-provider=builtin --builtin-locale=C.UTF-8 --encoding=UTF8" \
  -p 127.0.0.1:5432:5432 \
  postgres:17
```

The password above is for a laptop only. The database listens on your own
machine and nowhere else.

Later, `docker start markx-pg` starts it again. After an unclean shutdown
PostgreSQL may take a few seconds before it accepts connections.

## 2. Create the roles and the database

From the repository root:

```bash
export PGHOST=127.0.0.1 PGUSER=postgres PGPASSWORD=postgres_dev_only
infra/postgres/bootstrap.sh markx
```

This creates the three roles (`markx_migrator`, `markx_app`,
`markx_readonly`) and an empty database called `markx`. It is safe to run
again. The role passwords default to development values; set
`MARKX_DB_MIGRATOR_PASSWORD`, `MARKX_DB_APP_PASSWORD` and
`MARKX_DB_READONLY_PASSWORD` to choose your own.

## 3. Install and migrate

```bash
cd apps/api
uv sync                      # installs the locked dependencies into .venv
uv run alembic upgrade head  # creates the tables
```

## 4. Run the checks

```bash
uv run pytest                # every test, against the real database
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy markx            # type checks, strict
uv run alembic check         # models and migrations must not differ
```

`alembic check` and `alembic upgrade head` use the `markx` database from
steps 2 and 3. They do not use the test database.

The whole suite (847 tests) takes five to seven minutes. Never start two
test runs at once: they share the `markx_test` database. The tests in
`tests/db/test_inventory.py` and `tests/db/test_checkout_contention.py` start
up to 100 threads against the database on purpose.

The tests use their own database, `markx_test`. Each run drops it, bootstraps
it and applies every migration from empty, so the tests need the same
PostgreSQL superuser as step 2. If yours differs, set `MARKX_TEST_PGHOST`,
`MARKX_TEST_PGPORT`, `MARKX_TEST_PGUSER` and `MARKX_TEST_PGPASSWORD`.

Expected: all tests pass and the suite prints no warnings (a warning is
treated as a failure).

## 4a. Score search against real queries (P8)

```bash
cp search_eval/golden_queries.template.csv search_eval/golden_queries.csv
# fill it in with real queries (the template explains each column), then:
uv run python -m markx.search.evaluation search_eval/golden_queries.csv
uv run python -m markx.search.evaluation search_eval/golden_queries.csv --json
```

It reads the database in `MARKX_DATABASE_URL` (the `markx` database by
default), so load the real catalogue there first and let the worker build the
search documents (`uv run python -m markx.worker --once`). It writes nothing.

## 5. Run the API

```bash
uv run uvicorn markx.main:app --host 127.0.0.1 --port 8000
```

- Health: <http://127.0.0.1:8000/api/v1/healthz>
- Interactive API description: <http://127.0.0.1:8000/api/v1/docs>

### Run the worker

In a second terminal:

```bash
uv run python -m markx.worker          # runs until Ctrl-C
uv run python -m markx.worker --once   # one pass, then exit
```

It runs the scheduled jobs (expiring unanswered orders, completing delivered
orders after the problem window, cancelling orders whose fulfilment hold ran
out, hiding stale offers, applying payout-account changes) and sends what is
waiting in the outbox. On a laptop nothing leaves
the machine: a "sent" Telegram message is a line in
`MARKX_STORAGE_DIR/dev/push-outbox.jsonl`. `scheduled_jobs` in the database
shows when each job last ran and whether it failed.

### Sign in by hand

No SMS is ever sent on a laptop. The fake SMS adapter writes the message to a
file, and a development-only endpoint reads it back.

```bash
# Ask for a code. Requests that change data must carry this header.
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/otp/request \
  -H 'Content-Type: application/json' -H 'X-MarkX-Client: web' \
  -d '{"phone":"0911234567","language":"en"}'

# Read the message that would have been sent.
curl -s 'http://127.0.0.1:8000/api/v1/dev/sms-inbox?phone=0911234567'

# Verify the code and keep the session cookie.
curl -s -c cookies.txt -X POST http://127.0.0.1:8000/api/v1/auth/otp/verify \
  -H 'Content-Type: application/json' -H 'X-MarkX-Client: web' \
  -d '{"phone":"0911234567","code":"THE-SIX-DIGITS"}'

curl -s -b cookies.txt http://127.0.0.1:8000/api/v1/me
```

The `/dev/` endpoint exists only when `MARKX_ENV` is `local` or `test`.

### Become a seller by hand

Sellers apply by invitation, and invitations come from staff, so the first
staff account is made from a Python prompt. It prints the authenticator
secret once; add it to an authenticator app.

```bash
uv run python - <<'PY'
from markx import registry
from markx.accounts import service
from markx.accounts.models import StaffRole
from markx.core.db import session_scope

with session_scope() as db:
    staff = service.create_staff(
        db, raw_phone="0911000200", name="Founder", role=StaffRole.SUPER_ADMIN,
        password="choose-a-long-password", actor_user_id=None,
    )
    print("authenticator secret:", staff.totp_secret)
PY
```

Then, in the interactive API description at `/api/v1/docs`: sign in at
`/auth/staff/sign-in`, invite a phone number at `/admin/sellers/invitations`,
sign in as that number, and follow `/seller/applications`,
`/seller/{seller_id}/documents`, `/seller/{seller_id}/payout-account` and
`/seller/{seller_id}/submit`. Uploaded photos are kept under
`MARKX_STORAGE_DIR/private`.

### Place an order by hand

With a trading seller and an offer (above): sign in as a buyer by phone code,
save an address at `/me/addresses` (it needs a delivery area, which staff
create at `/admin/delivery/zones`), then `PUT /cart/items/{offer_id}`,
`POST /checkout/quote` and `POST /checkout` with the quoted
`grand_total_santim` and a fresh `idempotency_key`. The seller answers at
`/seller/{seller_id}/orders/{seller_order_id}/confirm` or `/decline`. With
the worker running, an unanswered order expires half an hour of business
time later.

After confirming, the seller takes the part through `/ready`, `/dispatch`
(rider orders; a collection order skips this) and `/handover` with the
six-digit code the buyer reads on `GET /me/orders/{order_id}`. The seller
records the direct payment at `/payment`. The buyer closes the part at
`/me/orders/{order_id}/seller-orders/{seller_order_id}/confirm-received`, or
the worker closes it 72 hours after delivery. Staff find any order at
`/admin/orders/{code}` and issue a new handover code at
`/admin/orders/seller-orders/{seller_order_id}/reissue-code`.

## Configuration

Settings come from environment variables prefixed `MARKX_`, or from a file
named `.env` in `apps/api`. Copy `apps/api/.env.example` to start. **Never
commit `.env`.** The defaults work on a laptop with the steps above.

With `MARKX_ENV=staging` or `production`, the application refuses to start
unless real secrets, `Secure` cookies and an `https://` origin are set.

## Making a schema change

1. Edit the models.
2. `uv run alembic revision --autogenerate -m "what changed"`
3. **Read and edit the generated file.** Add anything a model cannot express.
4. `uv run alembic upgrade head`, then `uv run pytest`.

Migrations are forward-only. A mistake is fixed by a new migration.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `connection refused` on port 5432 | PostgreSQL is not running: `docker start markx-pg` |
| `the database system is starting up` | Wait a few seconds and retry |
| `role "markx_migrator" does not exist` | Step 2 was skipped |
| Every test errors with `CalledProcessError` | The tests could not reach PostgreSQL as a superuser |
| `docker: Cannot connect to the Docker daemon` | Docker is installed but not running. Start Docker Desktop, or on a bare Linux machine run `dockerd` as root |
| `alembic check` fails with `database "markx" does not exist` | Steps 2 and 3 were skipped; the tests alone do not create `markx` |
