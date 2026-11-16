# Architecture

How the code is organised **today**. The target architecture is in
`MARKX_MASTER_BLUEPRINT.md`, section F; this file describes what exists and
marks what does not.

## Shape

MarkX is a modular monolith (blueprint F.0): one web app, one API with a
background worker, one PostgreSQL database, behind one reverse proxy on one
domain.

| Part | State |
| --- | --- |
| API (`apps/api`) | Foundation built: schema, sign-in, permissions |
| PostgreSQL | Schema for all of Release 1, three roles |
| Web app (`apps/web`) | **Does not exist** |
| Worker | **Does not exist** |
| Reverse proxy, containers, CI | **Do not exist** |

## Repository layout

```text
MARKX_MASTER_BLUEPRINT.md   the product's single source of truth
AGENTS.md, CLAUDE.md        instructions for AI agents
apps/
  api/                      FastAPI application
    markx/
      core/                 config, database, errors, HTTP plumbing, Money,
                            phone, Ethiopic text, codes, security, rate limits,
                            settings store
      accounts/             users, login codes, sessions, staff, addresses,
                            permissions (the blueprint's C.3 and C.4 tables)
      audit/                the append-only audit log
      notifications/        outbox, in-app notifications, SMS adapter
      sellers/ catalog/ offers/ orders/ payments/ delivery/ trust/
      search/ analytics/    MODELS ONLY: tables, no behaviour yet
      main.py               the application factory
      registry.py           imports every model for Alembic and tests
    migrations/versions/    forward-only Alembic migrations
    tests/
      unit/                 pure logic, no database
      db/                   rules the database enforces by itself
      api/                  HTTP tests through the real application
infra/
  postgres/                 bootstrap.sql and bootstrap.sh: roles and database
docs/
```

## The layers in every module

Blueprint F.2 and Q.6. `accounts` is the worked example.

| File | Holds | Rule |
| --- | --- | --- |
| `models.py` | Tables and their constraints | A constraint for every integrity rule |
| `schemas.py` | Request and response shapes | Reject unknown fields |
| `service.py` | Business rules | **The only code allowed to change data** |
| `selectors.py` | Read queries | Never change data |
| `router.py` | HTTP routes | Thin: validate, call a service, shape the reply |
| `deps.py` | Who is asking | Deny by default |

The web app will hold no business rules and will never talk to the database.

## A request, end to end

1. The request-context middleware gives the request an ID, times it, and adds
   security headers to the reply.
2. `enforce_request_origin` refuses a request that changes data unless it
   carries the MarkX client header and comes from the site's own origin.
3. `get_db` opens one database transaction. It commits when the route returns
   and rolls back on any error, **before** the response is sent.
4. `get_optional_principal` reads the session token, checks it against the
   database, and checks the CSRF token for cookie sessions.
5. A `require_staff(...)` or `require_seller(...)` dependency checks the role
   against the permission tables.
6. The route calls one service function.
7. A failure becomes the single error format: a code, a translation key, an
   English message and the request ID.

A service that must remember something even though the request fails (a wrong
login code, a failed staff sign-in) commits explicitly and then raises.

## Database

- **Three roles** (blueprint F.3). `markx_migrator` owns the schema and runs
  migrations. `markx_app` is what the API uses: it reads and writes rows,
  cannot change the schema, and cannot update or delete history tables.
  `markx_readonly` reads business data and cannot read credential tables.
- **Money** is whole santim in `bigint` columns. **Time** is UTC. **Keys** are
  UUID version 7.
- **Statuses** are text with CHECK constraints.
- **History tables only grow**: `audit_log`, `order_status_events`,
  `offer_price_history`, `inventory_movements`, `tracking_events`,
  `ledger_transactions`, `ledger_entries`.
- **The ledger balances** in every transaction, checked at commit.
- The chain the schema follows (blueprint G): product, variant, offer, order
  item, seller order, order, payment, ledger.

## Outside services

Each sits behind an adapter with a fake used in tests (blueprint F.0).

| Service | Adapter | State |
| --- | --- | --- |
| SMS | `markx/notifications/sms.py` | Fake only; no provider chosen |
| Bot check | `markx/core/botcheck.py` | Fake only |
| Telegram sign-in | `markx/accounts/service.py` | Signature check built; no bot |
| Object storage, payments, couriers, AI | | Not started |

## Configuration

Environment variables only, prefixed `MARKX_` (`markx/core/config.py`). The
defaults are for a laptop. On `staging` or `production` the application
refuses to start with development secrets.

Feature switches and limits live in the `settings` table with defaults in code
(`markx/core/settings_store.py`).
