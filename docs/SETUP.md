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
uv run python -m scripts.check_openapi_copy --exact openapi.json   # D-061
```

`alembic check` and `alembic upgrade head` use the `markx` database from
steps 2 and 3. They do not use the test database.

The whole suite (910 tests) takes eight to ten minutes. Never start two
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

## 4b. Demo data (laptop only)

```bash
uv run python -m scripts.seed_demo
```

Creates a demo catalogue, three demo shops with offers, delivery zones and a
demo buyer through the real API (D-056). It refuses to run unless
`MARKX_ENV` is `local`. None of it is real. It prints the demo staff
sign-in; sign-in codes for the demo phones are in the local SMS inbox.

## 4c. Everything in containers (laptop only)

Instead of steps 1 to 3 and running the API and worker by hand (D-058):

```bash
docker compose -f infra/compose/compose.yaml up --build
```

This starts PostgreSQL 17 (creating the three roles and the `markx`
database the first time) and MinIO with the buckets `markx-private` and
`markx-public` (D-090), applies the migrations, then runs the API on
`http://127.0.0.1:8000` and the worker, both keeping their files in MinIO.
Every port listens on your own machine only, and every password is a laptop
default that the API refuses on staging or production. `MARKX_PG_PORT`,
`MARKX_MINIO_PORT` and `MARKX_API_PORT` choose other ports when 5432, 9000
or 8000 are taken. `docker compose -f
infra/compose/compose.yaml down` stops it; adding `-v` also deletes its
database and uploaded files.

The web app is not in the Compose file yet: run it from `apps/web` with
`npm run dev`, as in section 6. The image holds no test tools, so the demo
data (section 4b) is loaded from `apps/api` on your machine, pointed at the
container's database:

```bash
MARKX_DATABASE_URL=postgresql+psycopg://markx_app:markx_app_dev-only@127.0.0.1:5432/markx \
  uv run python -m scripts.seed_demo
```

A worker pass or the demo data run from your machine against the Compose
stack must use the same MinIO, or the pictures they handle go to your own
folder instead: set the storage values from section 4e with
`MARKX_STORAGE_ENDPOINT_URL=http://127.0.0.1:9000`, as the journeys workflow
does.

If Docker Hub refuses pulls ("429 Too Many Requests"), build the image
from a mirror of the same Python image:
`docker build --build-arg PYTHON_IMAGE=mirror.gcr.io/library/python:3.13-slim-bookworm -t markx-api:local apps/api`.
Nothing here deploys anything.

## 4d. Back up, restore and drill (D-063)

```bash
export PGHOST=127.0.0.1 PGUSER=postgres PGPASSWORD=postgres_dev_only
# a passphrase of at least 32 characters, kept outside the repository and
# outside the backup directory
head -c 48 /dev/urandom | base64 > ~/markx-backup.key
export MARKX_BACKUP_PASSPHRASE_FILE=~/markx-backup.key

infra/backup/backup.sh markx                     # -> var/backups/markx-markx-<time>.dump.enc
infra/backup/restore.sh var/backups/<file> markx_restored   # into a NEW database only
infra/backup/drill.sh markx                      # backup, restore, compare, clean up
```

`pg_dump` refuses a server newer than itself. If your client is older than
PostgreSQL 17, use the server's own tools in its container:

```bash
export PG_DUMP="docker exec -i -e PGUSER -e PGPASSWORD markx-pg pg_dump"
export PG_RESTORE="docker exec -i -e PGUSER -e PGPASSWORD markx-pg pg_restore"
export PSQL="docker exec -i -e PGUSER -e PGPASSWORD markx-pg psql"
```

Keep the passphrase somewhere safe and separate from the backups: without
it a backup cannot be read, by anyone. On a server, a nightly cron line
such as `15 2 * * * cd /srv/markx && infra/backup/backup.sh markx
--keep-days 30` runs it; that, and the copy away from the server, are
deployment settings.

## 4e. Object storage on a laptop: MinIO (D-090)

Without any setting, files go to two folders under `MARKX_STORAGE_DIR`
(`private/` and `public/`). To use object storage as a server does, run
MinIO (Compose in section 4c already does) and point the API and the worker
at it:

```bash
docker run -d --name markx-minio -p 127.0.0.1:9000:9000 \
  -e MINIO_ROOT_USER=markx-dev-only -e MINIO_ROOT_PASSWORD=markx-minio-dev-only-password \
  -e MINIO_DEFAULT_BUCKETS=markx-private,markx-public \
  bitnamilegacy/minio:2025.7.23-debian-12-r5

export MARKX_FILE_STORAGE_PROVIDER=minio
export MARKX_STORAGE_ENDPOINT_URL=http://127.0.0.1:9000
export MARKX_STORAGE_ACCESS_KEY_ID=markx-dev-only
export MARKX_STORAGE_SECRET_ACCESS_KEY=markx-minio-dev-only-password
export MARKX_STORAGE_PRIVATE_BUCKET=markx-private
export MARKX_STORAGE_PUBLIC_BUCKET=markx-public
```

MinIO no longer publishes images on Docker Hub; this is Bitnami's last
build of MinIO, used on laptops and in CI only. **MinIO is never for a real
server**: staging and production refuse it.

**The object storage tests** (`tests/storage/`) need a MinIO with those
two development keys on `127.0.0.1:9000` (the `docker run` line above; the
buckets are not needed, each run makes and removes its own). Without MinIO
they are skipped on a laptop; CI sets `MARKX_TEST_MINIO_REQUIRED=1`, which
turns a missing MinIO into a failure. `MARKX_TEST_MINIO_ENDPOINT`,
`MARKX_TEST_MINIO_ACCESS_KEY` and `MARKX_TEST_MINIO_SECRET_KEY` point them
elsewhere. Nothing in them reaches Amazon or Cloudflare.

### File storage settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `MARKX_FILE_STORAGE_PROVIDER` | `local` | `local` or `minio` (laptop and tests only), `s3` (Amazon S3) or `r2` (Cloudflare R2). Staging and production refuse `local` and `minio` |
| `MARKX_STORAGE_ENDPOINT_URL` | none | The S3 API endpoint: required for `minio` and `r2` (`https://<account id>.r2.cloudflarestorage.com`); for `s3` leave it empty to use AWS's endpoint for the region. A bare origin: no user, path, query or fragment; `https://` on real servers |
| `MARKX_STORAGE_REGION` | `us-east-1` (`auto` for `r2`) | Required for `s3`: the buckets' region |
| `MARKX_STORAGE_ACCESS_KEY_ID`, `MARKX_STORAGE_SECRET_ACCESS_KEY` | none | One key scoped to the two buckets only. **From the server's secret store only**; never AWS's own credential chain |
| `MARKX_STORAGE_PRIVATE_BUCKET` | none | Documents, picture sources, problem photos. **Never public**, and never given a public domain |
| `MARKX_STORAGE_PUBLIC_BUCKET` | none | Rendered pictures, behind the CDN. Must be a different bucket |
| `MARKX_STORAGE_SERVER_SIDE_ENCRYPTION` | `auto` | `auto` (AES256 on S3; R2 always encrypts), `AES256` or `none` |
| `MARKX_STORAGE_CONNECT_TIMEOUT_SECONDS`, `MARKX_STORAGE_READ_TIMEOUT_SECONDS` | `5`, `15` | How long to wait before an upload or a picture fails with 503 |
| `MARKX_STORAGE_MAX_OBJECT_BYTES` | `20000000` | The largest file written or read |
| `MARKX_PUBLIC_MEDIA_BASE_URL` | `/api/v1/media` | On a real server the pictures' CDN address: `https://`, on a host other than the site's (F-15) |

**Choosing the provider for real is the founder's decision (F-01)**, and so
is protecting the buckets against loss (F-14). No bucket or account has
been created.

### Copying an existing installation's files (D-090)

Only with the founder's written approval, and never automatically:

```bash
# with the MARKX_STORAGE_* values of the buckets set, and the database the
# files belong to in MARKX_DATABASE_URL:
uv run python -m scripts.copy_files_to_object_storage --from-dir ./var/storage   # dry run
uv run python -m scripts.copy_files_to_object_storage --from-dir ./var/storage \
    --execute --founder-approved                                                # copy and verify
```

It copies every file the database refers to under the same key, reads each
copy back, never deletes or changes a local file or a row, and never
overwrites an object already in a bucket. Keep the local folder until the
copy has been checked and the founder agrees it can go.

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
uv run python -m markx.worker --once   # the due jobs and every due message, then exit
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

A number can be sent one code a minute (`auth.otp_resend_cooldown_seconds`,
60 by default, D-089): asking again sooner answers `429
otp_resend_too_soon` with `retry_after_seconds`, and the sign-in page says
how many seconds are left. To try several codes quickly on a laptop, a super
administrator can set it to 0 in the admin settings, or from `apps/api`:

```bash
uv run python -c "from markx.core import settings_store
from markx.core.db import session_scope
with session_scope() as db:
    settings_store.set_setting(db, 'auth.otp_resend_cooldown_seconds', 0)"
```

Every message, fake or real, leaves a delivery record in `sms_messages`
(purpose, a keyed hash of the number, the challenge, provider, provider id,
status, error code, segments, times; never the text or the code):

```bash
psql -d markx -c "select created_at, purpose, provider, status, error_code, segments
                  from sms_messages order by created_at desc limit 5"
```

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
unless real secrets, `Secure` cookies and an `https://` origin are set. It also
refuses the fake bot check (`MARKX_BOT_CHECK_PROVIDER=fake`, D-084), so a
real server cannot start until a real bot-check adapter exists.

Security settings added by D-084:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MARKX_TRUSTED_PROXIES` (API) | `127.0.0.1,::1` | The reverse proxies whose `X-Forwarded-For` is believed: exact addresses or networks, comma-separated. On a real server, the proxy's address. `*` and catch-all networks are refused |
| `MARKX_MEDIA_ORIGIN` (web, build time) | none | The picture CDN's origin, allowed in the page's Content Security Policy |
| `MARKX_HSTS_MAX_AGE` (web, build time) | none | Sends `Strict-Transport-Security` from the web app. Set only once HTTPS works end to end; the API sends it by itself on staging and production |

The container runs uvicorn with `--no-proxy-headers`; run it the same way
behind a proxy so only `MARKX_TRUSTED_PROXIES` decides.

### The bot check: Cloudflare Turnstile (D-085)

On a laptop and in the tests nothing is needed: the API's development check
answers and the sign-in page shows no widget. Staging and production refuse
to start until Turnstile is configured.

#### Three different things: do not confuse them

| | What it means | Where it works today |
| --- | --- | --- |
| **1. Turnstile verification** | The API asked Cloudflare about the visitor's token and Cloudflare said "a person, on our site, for sign-in" | On a laptop with the local test widget (below). Not yet against a production widget |
| **2. SMS delivery** | The six-digit code reaches the person's phone | **Nowhere yet.** The provider-independent adapter exists (D-089) but no provider has been chosen, so nothing can be sent. On a laptop the code is written to the development inbox, not sent. Staging and production refuse to start without a real SMS configuration |
| **3. Complete production sign-in** | On the real domain over HTTPS: Turnstile, then the SMS, then the person types the code and is signed in | **Not possible yet:** it needs a chosen SMS provider and its wire format, a production Turnstile widget and a deployed server |

A successful Turnstile test therefore proves item 1 only.

#### The two Turnstile widgets

- **"MarkX", the local test widget** (created by the founder on 18 November
  2026). Hostname: `localhost` only. For testing on a laptop, never for
  production: staging and production refuse to start with `localhost` among
  their Turnstile hostnames, and Cloudflare refuses its tokens anywhere but
  `localhost`. Its **site key is public**: `0x4AAAAAAGGYs5bV6hfwiNJC`. Its
  **secret key stays in the Cloudflare dashboard** and is typed into the
  tester's own terminal only (below); it is not in this repository.
- **The production widget: not created yet.** Create it before launch with
  the site's real hostnames only (e.g. `markx.et`, `www.markx.et`), mode
  "Managed", pre-clearance off. It gets its own site key and secret.

#### The settings

| Setting | Value | Set on | Secret? |
| --- | --- | --- | --- |
| `MARKX_BOT_CHECK_PROVIDER` | `turnstile` | API | No |
| `MARKX_TURNSTILE_SITE_KEY` | the widget's site key | API **and** web app (same value) | No |
| `MARKX_TURNSTILE_SECRET_KEY` | the widget's secret key | **API only** | **Yes** |
| `MARKX_TURNSTILE_ALLOWED_HOSTNAMES` | e.g. `markx.et,www.markx.et`; empty means the host of `MARKX_PUBLIC_ORIGIN` (on a laptop, `localhost`) | API | No |

- **The secret key** goes only into the server's secret store or the
  tester's own terminal: never Git, a committed file, `.env.example`, the web
  app, GitHub Actions, documentation, a screenshot, email or chat. Paste it
  exactly: no quotes, spaces or line breaks.
- **Allowed hostnames** are checked when the API starts: bare names
  separated by commas. A protocol (`https://`), a path, a port (`:3000`), a
  wildcard (`*.markx.et`), an IP address, a trailing dot, an empty entry or
  a space stops the start with a message naming the entry and the problem.
- **The web app** reads the site key each time the sign-in page is served:
  no rebuild is needed to change it. It never sees the secret.
- The API refuses a token that is missing, malformed, invalid, expired or
  already used, one solved on another hostname or for another action than
  `sign_in`, and any answer it cannot read; if Cloudflare cannot be reached
  within `MARKX_TURNSTILE_TIMEOUT_SECONDS` (default 5) it refuses too. No
  code is sent then.
- To check what the API loaded (the secret prints as `**********`), from
  `apps/api`: `uv run python -c "from markx.core.config import get_config;
  c=get_config(); print(c.bot_check_provider, c.turnstile_hostnames,
  c.turnstile_site_key, c.turnstile_secret_key)"`

#### Testing Turnstile on a laptop (item 1 only)

Needs a computer with this repository set up (sections 1 to 3 and 7), an
internet connection, and the founder's Cloudflare login to copy the secret
from the "MarkX" widget. A cloud session cannot do this test: the widget
must be solved by a person in a real browser on `localhost`.

1. **The API**, in one terminal:

   ```bash
   cd apps/api
   export MARKX_ENV=local MARKX_BOT_CHECK_PROVIDER=turnstile
   export MARKX_TURNSTILE_SITE_KEY=0x4AAAAAAGGYs5bV6hfwiNJC
   read -rs MARKX_TURNSTILE_SECRET_KEY && export MARKX_TURNSTILE_SECRET_KEY
   uv run uvicorn markx.main:app --host 127.0.0.1 --port 8000
   ```

   At the `read` line, paste the secret key from the Cloudflare dashboard
   and press Enter: nothing is shown, and nothing is kept in the shell's
   history or in any file. `MARKX_TURNSTILE_ALLOWED_HOSTNAMES` is not needed
   here (the laptop's origin is `http://localhost:3000`).
2. **The web app**, in a second terminal:

   ```bash
   cd apps/web
   npm run build
   MARKX_TURNSTILE_SITE_KEY=0x4AAAAAAGGYs5bV6hfwiNJC npm run start
   ```

3. Open **`http://localhost:3000/en/sign-in`** in an ordinary browser. Use
   `localhost`, not `127.0.0.1`: the widget only works on its hostname, and
   the API's anti-forgery check expects `localhost:3000`.
4. The check appears under the phone number. Type a number, wait for the
   tick, press "Send code".
5. Read the result:
   - **Turnstile verified (item 1 passed):** the page says "We sent a code",
     and the API's terminal shows no `bot check refused` line. The code is
     in the development inbox,
     `http://localhost:3000/api/v1/dev/sms-inbox?phone=0911234567` (with the
     number you typed). **No SMS reaches a phone: that is expected** (item 2
     does not exist yet).
   - **Refused:** the page says "We could not confirm you are a person", and
     the API's terminal shows `bot check refused` with a reason:
     `invalid-input-secret` (the secret was mistyped), `wrong-hostname` (the
     page was opened on another address), `unreachable` (no internet, or
     Cloudflare did not answer in time), `timeout-or-duplicate` (the token
     expired or was used twice: solve the check again).
6. **Afterwards:** close both terminals; the secret leaves with them. If you
   used an `apps/api/.env` file instead of `read`, delete it.

#### Credential rotation and the founder's security review

- **Before production launch: review the temporary Turnstile credentials
  and rotate the secret before production use.** The local "MarkX" widget is
  for testing only; production gets its own widget, whose secret is rotated
  once before launch and then lives only in the server's secret store.
- **At any time:** the founder may rotate any Turnstile secret whenever they
  wish, for their own security; no code change is needed. In the Cloudflare
  dashboard, open Turnstile, the widget, its settings, and rotate the secret
  key (or delete and re-create the widget), then put the new secret where
  the old one was and restart the API. The old secret stops working.
- **Security review at the 100th real MarkX transaction**, or earlier
  whenever the founder asks. A real transaction is a seller order completed
  on the production site; demo and test data do not count. The review:
  rotate the Turnstile secret; review the other secrets (`MARKX_SECRET_KEY`,
  `MARKX_ENCRYPTION_KEY`, database passwords, the Telegram bot token); review
  staff accounts and their authenticators; read the audit log of staff
  actions. This is a written reminder in this file and in
  `docs/DEVELOPMENT_STATUS.md`; nothing in the code fires it automatically
  yet.
- None of this is permission to put a secret in Git, a file, a document, a
  screenshot or a chat.

### SMS (D-089)

| Variable | Default | Meaning |
| --- | --- | --- |
| `MARKX_SMS_PROVIDER` | `fake` | `fake` (laptop and tests only; staging and production refuse it) or `http` |
| `MARKX_SMS_API_URL` | none | The provider's fixed sending endpoint. Must be `https://`, with no user name, password, query or fragment. Never taken from a request |
| `MARKX_SMS_API_KEY` | none | From the server's secret store only. Held as a secret: absent from logs, reprs and error messages |
| `MARKX_SMS_SENDER_ID` | none | The sender name the provider approved: at most 11 letters and digits, or a number of at most 15 digits |
| `MARKX_SMS_TIMEOUT_SECONDS` | `8` | How long to wait for the provider (more than 0, at most 30) |

With `http`, the URL, key and sender must all be set or the API does not
start. The same goes for staging and production with `fake`.

**What `http` does today.** It POSTs MarkX's own placeholder JSON (`to`,
`from`, `text`, `reference`, with the key as a bearer token) and expects a
JSON answer with `message_id`. **This is not any provider's API**: no
provider has been chosen. Do not point it at a provider; choosing one means
writing that provider's wire format first (see D-089).

Settings in the admin screens (or `settings_store`):
`auth.otp_resend_cooldown_seconds` (60), `sms.failure_alert_percent` (20),
`sms.failure_alert_min_messages` (5) and `sms.unfinished_alert_minutes`
(15). The worker's watch raises `sms.failures` when that share of the last
hour's attempts failed or went unconfirmed, and `sms.unfinished` for messages
of the last day with no final status after that many minutes; `sms.budget`
is unchanged.

**Testing it.** `uv run pytest tests/api/test_sms_adapter.py
tests/api/test_sms_cooldown.py` drives the adapter with a stand-in and with
a real HTTPS server on 127.0.0.1 (a throwaway certificate made by the test);
no provider is contacted. `node e2e/sign-in-cooldown.mjs` checks the
cooldown message in a browser; the API must run with the cooldown above 0.

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

## 7. Run the web app

Needs Node.js 22 (20.9 at the least). With the API running on port 8000:

```bash
cd apps/web
npm ci
npm run dev            # http://localhost:3000, redirects to /am
```

The browser talks to one origin: `/api/...` is passed to the API
(`MARKX_API_ORIGIN`, default `http://127.0.0.1:8000`), so sign-in cookies and
the CSRF check work as in production. The checks CI runs:

```bash
npm run lint
npm run typecheck      # generates the route types, then strict tsc
npm test               # Vitest unit tests
npm run build
```

To use routes the API has added, refresh the web app's copy of its
description and types. CI fails if the types do not match the copy, or if the
copy says anything the API no longer does; a copy that merely lacks newer
routes passes (D-061):

```bash
cd apps/api && uv run python -m scripts.export_openapi ../web/src/lib/api/openapi.json
cd ../web && npm run gen:api
```

### Replay the journeys in a browser

With the API on port 8000 filled by the demo data (section 4b) and the web
app on port 3000 (`npm run build && npm run start`, or `npm run dev`), from
`apps/web`. They use the Chromium that Playwright finds, and they change the
demo data, so run them on a laptop only:

```bash
node e2e/buyer-journey.mjs     # the buyer's whole journey and the shop's side
MARKX_DEMO_TOTP_SECRET=SECRET node e2e/staff-journey.mjs  # a problem decided by staff
MARKX_DEMO_TOTP_SECRET=SECRET node e2e/admin-queues.mjs  # proposals, invitations,
                               # takedowns, the audit trail, a curator's own menu
MARKX_DEMO_TOTP_SECRET=SECRET node e2e/shop-screens.mjs  # reviews, reports, pictures,
                               # problem evidence; staff steps need the secret
MARKX_DEMO_TOTP_SECRET=SECRET node e2e/seller-dashboard.mjs  # a new shop from its
                               # application to its first offer
MARKX_DEMO_TOTP_SECRET=SECRET node e2e/setup-and-account.mjs  # staff setup, trust
                               # actions, the buyer's account, proposals, closing
```

Each wants the authenticator secret that `seed_demo` printed and computes
the code itself (`staff-journey.mjs` still accepts a current six-digit code
as `MARKX_DEMO_TOTP`) (a code works once: two staff
sign-ins inside 30 seconds make the second wait for the next code). The
journeys run `uv run python -m markx.worker --once` from `apps/api` where a
step needs the worker (pictures, rating totals). Each prints one line per
step and ends with "console errors: none". They sign demo phones in by code,
and the API allows five codes per phone per clock hour and one a minute
(D-089); a refused code (`rate_limited`) means waiting for the next hour,
and `otp_resend_too_soon` a minute. Before replaying several journeys in a
row, set `auth.otp_per_phone_per_hour` to 30, `auth.otp_per_ip_per_hour` to
200 and `auth.otp_resend_cooldown_seconds` to 0, as the journeys workflow
does (the commands are in `.github/workflows/journeys.yml`, step "Room for
every journey's sign-ins"). `node e2e/sign-in-cooldown.mjs` needs the
cooldown above 0 again. Give a folder as the last
argument to keep screenshots (`seller-dashboard.mjs` also keeps one of every
page when a step fails).

Playwright is a development dependency of the web app (`npm ci` installs
it); `npx playwright install chromium` fetches its browser once.

`node e2e/turnstile-widget.mjs` checks the sign-in widget with Cloudflare
replaced by a stand-in; start the web app with
`MARKX_TURNSTILE_SITE_KEY=test-only-site-key` first (D-085).

`node e2e/page-weight.mjs` checks the page weight of five pages against the
ceilings of D-084 and exits 1 when one is over (production build only).

On GitHub the page-weight check and the same journeys run on every push that
changes code (`apps/`, `infra/` or the workflow), against PostgreSQL, the
migrations and the API started from Compose with a fresh demo database
(`infra/compose/compose.ci.yaml` shares the picture folder with the runner),
or from the Actions tab once the workflow is on the default branch. A failing
journey fails the run, which keeps its screenshots and server logs for a
week (D-081, D-084).
