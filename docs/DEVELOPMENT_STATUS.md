# Development status

**Last updated:** 16 November 2026.
**Branch:** `claude/project-scaffold`
**Read this after** `AGENTS.md` and `MARKX_MASTER_BLUEPRINT.md`.

This file states what exists, what is tested and what is not. Nothing here is
aspirational. If a line says "tested", the test is in the repository and passed
on the date above.

## In one paragraph

The master blueprint is in the repository. The back-end foundation is built
and tested: the complete Release 1 database schema with its integrity rules,
sign-in for customers, sellers and staff, the permission model, delivery zones
and buyer addresses. **No marketplace feature works yet**: there is no
catalogue, seller, offer, search, cart or order *behaviour*, only their tables. **There is no web app yet.**
Nothing is deployed anywhere.

## Blueprint phase tracking

Phases are the blueprint's P1 to P16 (section L.1).

| Phase | Name | State |
| --- | --- | --- |
| P1 | Project foundation | **Partly done.** API skeleton, database pipeline and core helpers are done and tested. Web shell, CI pipeline, container setup, typed link between API and web, page-weight check and the three technical reports are **not done** |
| P2 | Database and backend foundation | **Partly done.** Schema, three database roles, error format, request IDs, structured logs are done. Worker process, outbox dispatcher, backups, alerting are **not done** |
| P3 | Authentication and roles | **Mostly done on the API side.** Phone-code sign-in, sessions, staff sign-in, Telegram signature check and the permission tables are done and tested. The real SMS and bot-check adapters, the account page and admin pages are **not done** |
| P4–P16 | Everything else | **Not started** (tables exist; no behaviour) |

## What is built and tested

All of it is in `apps/api`. Test command and result are at the end.

### Core helpers (blueprint P.1 item 5)

- **Money**: whole santim, exact arithmetic, basis-point fees rounded half up,
  "ETB 12,500" and "12,500 ብር" formatting, parsing of typed birr amounts.
- **Phone numbers**: accepts `09`, `07`, `9`, `7`, `+251`, `251` and `00251`
  forms; stores `+2519…`/`+2517…`; rejects everything else.
- **Ethiopic text**: same-sound letter merging (the four blueprint pairs match)
  and consonant skeleton keys ("silk", "selk", "slk" and ስልክ all give `slk`).
- **Order codes**: `MX-` plus six characters with no look-alikes.
- **Time-ordered UUIDs** (version 7), generated in the application.

### Database (blueprint G)

- `infra/postgres/bootstrap.sql` creates the three roles the blueprint requires
  (`markx_migrator`, `markx_app`, `markx_readonly`) and a database using the
  built-in `C.UTF-8` locale. Idempotent.
- Migration `0001`: all **63 tables** for Release 1, with 159 CHECK constraints
  and 81 foreign keys. Every "status" column accepts only its allowed values;
  money and stock columns cannot go negative; the uniqueness rules of G.8 are
  constraints (one offer per seller, variant and condition; one seller order
  per order and seller; one review per order item; and so on).
- Migration `0002`: history tables are append-only (privileges revoked from the
  app role **and** a trigger that refuses UPDATE/DELETE for every role); a
  deferred constraint trigger makes every ledger transaction balance.
- Migration `0003`: fixes a bug in `0002`'s ledger trigger (see "Lessons").
- Tested: migrations apply from an empty database; models and migrations do
  not differ; trigram matching works on Ethiopic text; no foreign key cascades
  into orders or money.
- Tested by connecting as each role and attacking with plain SQL
  (`tests/db/test_protection.py`): the application role cannot update, delete
  or truncate the audit log, and neither can the schema owner; an unbalanced
  ledger transaction is refused at commit and a balanced one commits; ledger
  entries cannot be changed after they are written; the application role
  cannot change the schema or disable a trigger; the read-only role can read
  business data, write nothing, and cannot read credentials; no MarkX role is
  a superuser. This meets blueprint P2's first completion criterion.

### API foundation

- One error format with a code, a translation key and a request ID.
- Request IDs, JSON logs, security headers.
- Anti-forgery guard on every request that changes data (custom header,
  Origin check, and a per-session CSRF token for cookie sessions).
- Health endpoint that reports the database.
- Settings store: feature switches and limits with defaults in code.
- Rate limiting kept in PostgreSQL.

### Sign-in and permissions (blueprint D.2, C, H.2)

- **Phone-code sign-in.** Six-digit code stored only as a keyed hash, five
  minute expiry, five attempts, then a 15-minute lock. Limits per number and
  per network address, a bot-check hook before any SMS, and a daily SMS budget
  that cuts off sending. The account is created at first sign-in.
- **Sessions.** Random token, only its hash stored, cookie that scripts cannot
  read, idle and absolute expiry, a new session at every sign-in, sign-out
  everywhere, a notice when another device signs in. A header-based session
  for the Telegram Mini App.
- **Staff sign-in.** Password hashed with Argon2id plus an authenticator code;
  the authenticator secret is encrypted; a used code cannot be replayed; five
  failures lock the account; every attempt is audit-logged; every failure
  looks the same to the caller.
- **Telegram.** Signature and timestamp of Mini App start-up data verified on
  the server; linking one Telegram identity to one account.
- **Permission tables** of blueprint C.3 and C.4, in code, with a test for
  every one of the 140 cells.

### Delivery zones and buyer addresses (blueprint D.13, AD-05, C-08, C-28)

- Staff create zones, neighbourhoods and one flat fee per delivery method per
  zone. Only the super administrator and operations may (blueprint C.4); a
  test covers all five staff roles, a customer, a visitor, and a staff member
  signed in by phone code. Every change is audit-logged with before and after.
- A public, cacheable route lists active zones, areas and fees.
- Buyers save landmark addresses with an optional map pin and second phone.
  Removing one archives it. One buyer cannot see or remove another's address,
  and gets the same "not found" as for an address that does not exist.
- Requests to see, correct or delete personal data.

## What exists but is NOT tested

Be careful with these. They were written and never exercised.

- Models for sellers, catalogue, offers, inventory, shipments, orders,
  payments, the ledger's application code, reviews, cases, search and
  analytics: the tables exist and are constrained; **no service, route or
  test uses them**.
- `markx/notifications/service.py` queues outbox rows, and **nothing drains
  the outbox**: there is no worker.

## What does not exist

- The web app (Next.js): storefront, seller dashboard, admin dashboard.
- Services and routes for sellers, catalogue, offers, inventory, search, cart,
  checkout, orders, delivery, payments, reviews, cases and admin.
- The background worker (outbox dispatch, expiry jobs, stale offers).
- Seed data.
- Docker Compose files and Dockerfiles; the reverse proxy.
- The CI pipeline (`.github/workflows`).
- Real adapters: SMS provider, bot check, object storage, Telegram bot.
- `docs/DECISIONS.md`, `docs/ARCHITECTURE.md`, `docs/SETUP.md` in their full
  form (see "Next task").
- Anything on AWS. Nothing has been deployed and no cloud resource was created.

## Lessons

- **Untested code was wrong.** Migration `0002` shipped a ledger trigger that
  made every ledger insert fail. It applied cleanly and looked correct. The
  first test that inserted a ledger row found it. Treat every item under
  "exists but is NOT tested" as probably broken until a test says otherwise.

## Known problems

- None found in the tested code. The untested items above are unknowns, not
  known-good.
- The README at the repository root is still the two-line placeholder.
- All Amharic text was drafted by an AI agent. A native speaker must review it
  before launch (blueprint I.3).

## Tests executed

```text
$ cd apps/api
$ uv run pytest           ->  418 passed
$ uv run ruff check .     ->  All checks passed!
$ uv run mypy markx       ->  Success: no issues found in 57 source files
$ uv run alembic check    ->  No new upgrade operations detected.
```

Run on 16 November 2026 against PostgreSQL 17.12 in Docker, after rebuilding
the test database from empty. mypy runs in strict mode and the application
code contains no `type: ignore`. The suite treats warnings as errors.

| File | Tests |
| --- | --- |
| `tests/unit/test_money.py` | 40 |
| `tests/unit/test_phone.py` | 31 |
| `tests/unit/test_ethiopic.py` | 35 |
| `tests/unit/test_codes.py` | 7 |
| `tests/unit/test_permissions.py` | 144 |
| `tests/db/test_migrations.py` | 8 |
| `tests/db/test_protection.py` | 41 |
| `tests/api/test_health.py` | 7 |
| `tests/api/test_auth_otp.py` | 35 |
| `tests/api/test_auth_staff.py` | 14 |
| `tests/api/test_auth_telegram.py` | 7 |
| `tests/api/test_csrf.py` | 8 |
| `tests/api/test_delivery.py` | 24 |
| `tests/api/test_addresses.py` | 17 |

No end-to-end test exists, because no web app exists.

## The exact next task

Work in this order. Finish and push each step before starting the next.

1. **Catalogue** (blueprint P5): categories, attributes, brands, products,
   variants, translations; staff create, approve, merge and archive; the
   duplicate-variant rule tested at the database.
2. **Sellers** (P6): application, staff review, verification levels, members,
   store page; a test that one seller cannot read another's data.
3. **Offers and inventory** (P7), then **search** (P8), **cart and checkout**
   (P9) and **multi-seller orders** (P10). The concurrency tests in blueprint
   P9 (100 buyers, one unit, exactly one order) are mandatory.
4. **The web app** (P4), starting with the shell at `/am` and `/en`.

Keep `ruff`, `mypy`, `alembic check` and `pytest` green at every commit.
