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
| API (`apps/api`) | Built: schema, sign-in, permissions, delivery zones, catalogue, sellers, offers and inventory, cart, checkout, the whole seller order life cycle with problems and staff decisions, search, pictures, monitoring, the admin back end, reviews, reports, exports. Not built: Release 2 payments |
| PostgreSQL | Schema for all of Release 1 (68 tables), three roles |
| Web app (`apps/web`) | Built (D-055): the storefront and the buyer's journey, the seller dashboard's orders and offers, and the admin dashboard's queues (D-070). Not built: the admin screens for pictures, operations, settings, staff, dispatch, the dashboard, reviews and reports; the seller's application and "add an offer" screens |
| Worker (`python -m markx.worker`) | Built: scheduled jobs and the outbox dispatcher. No real push channel yet |
| Containers, CI | Built: a Compose file for a laptop (D-058) and CI on every push. **The reverse proxy and any deployment do not exist** |

## Repository layout

```text
MARKX_MASTER_BLUEPRINT.md   the product's single source of truth
AGENTS.md, CLAUDE.md        instructions for AI agents
apps/
  api/                      FastAPI application
    markx/
      core/                 config, database, errors, HTTP plumbing, Money,
                            phone, Ethiopic text, codes, security, rate limits,
                            settings store, private file storage, image checks
      accounts/             users, login codes, sessions, staff, addresses,
                            permissions (the blueprint's C.3 and C.4 tables)
      audit/                the append-only audit log
      notifications/        outbox, in-app notifications, SMS adapter
      delivery/             zones, areas, flat fees
      catalog/              categories, attributes, brands, products, variants
      sellers/              invitations, applications, documents, staff review,
                            verification levels, members, store, payout account
      offers/               offers, price history, inventory, stock holds,
                            ranking, check-in, product proposals
      orders/               cart, checkout (place_order), seller orders,
                            the G.6 state machine, response deadlines
      worker/               the background worker: scheduled jobs, outbox
      search/               search documents, matching, the evaluator
      images/               product pictures and problem photos (D-062)
      ops/                  self-checks, alerts, reconciliation (D-064)
      admin/                audit-log viewer, settings, staff accounts,
                            dispatch board, business dashboard (D-065)
      payments/ trust/      the ledger and fees; problem cases (used by orders)
      analytics/            MODELS ONLY: tables, no behaviour yet
      main.py               the application factory
      registry.py           imports every model for Alembic and tests
    migrations/versions/    forward-only Alembic migrations
    openapi.json            the API description, checked exactly (D-061)
    tests/
      unit/                 pure logic, no database
      db/                   rules the database enforces by itself, and
                            contention tests with many threads
      api/                  HTTP tests through the real application
      worker/               the worker, driven one pass at a time
  web/                      Next.js app (D-055); every page under /am or /en
    messages/               am.json and en.json: every word on screen
    src/app/[lang]/         (shop)/ storefront and buyer, seller/, admin/
    src/components/         client components; admin/StaffActions.tsx holds
                            every staff form
    src/lib/                API clients, formatting, labels for API codes
    e2e/                    browser journeys against the demo data
infra/
  postgres/                 bootstrap.sql and bootstrap.sh: roles and database
  backup/                   backup.sh, restore.sh, drill.sh (D-063)
  compose/                  API, worker and PostgreSQL on a laptop (D-058)
docs/
```

## The admin dashboard on the web

`apps/web/src/app/[lang]/admin/(desk)/`. Staff only: the layout sends any
other session to the staff sign-in. `menu.ts` is one table of queues, each
with the capability that opens it — the same capability the API checks on
every call (blueprint C.4) — and the admin home sends a person to the first
queue their role holds. A page the API refuses (403) says so in words. Codes
the API sends are shown through `codeLabel` in `src/lib/labels.ts` and the
`labels` group of both message files; `labels.test.ts` lists the API's codes
and fails if one lacks words. Every staff form is in
`src/components/admin/StaffActions.tsx` and shows the API's refusal through
`apiErrorText`. The web app decides nothing (D-070).

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

## Seller scoping

Blueprint C.5: a seller member can never read or change another seller's
data. The rule has one home.

- Every seller route lives under `/seller/{seller_id}/...` and declares
  `require_seller(capability)` from `markx/accounts/deps.py`. It loads the
  seller **through the caller's own active membership**, so a seller the
  caller does not belong to cannot be loaded at all. Another seller's id and
  an id that does not exist give the same "not found".
- A service function that takes a `Seller` trusts that the route loaded it
  this way. Anything addressed by its own id (a document, a member, an
  offer) is always queried **together with** `seller_id`.
- Membership is read on every request, so a removed member is out at once.
- Staff sessions are refused on seller routes. Staff use `/admin/...`
  routes, each behind `require_staff(capability)`.
- `tests/api/test_seller_isolation.py` reads the route list from the API
  description and attacks every `/seller/{seller_id}` route. **A new seller
  route is covered automatically, provided it uses `require_seller`.** A
  seller-owned resource reached by any other path needs its own test.

## Stock

Blueprint G.9. All of it is in `markx/offers/service.py`.

- Stock changes only there, and every change inserts an
  `inventory_movements` row in the same transaction.
- `hold_stock` is one `UPDATE ... WHERE on_hand - reserved >= :qty`. Two
  buyers cannot both take the last unit: the second UPDATE waits for the
  first, then finds nothing left. It returns `False`; the caller rolls back.
- `release_stock` and `commit_stock` end a hold. `set_stock` is the seller's
  count and cannot go below what is held.
- Offer and seller rows are locked with `with_for_update(key_share=True)`,
  never plain `FOR UPDATE` (see D-027: a deadlock found by a test).
- CHECK constraints on `inventory` refuse negative stock and
  `reserved > on_hand` whatever the code does.

## Orders

Blueprint G.5 to G.7. All in `markx/orders/`.

- `status.py` is the G.6 state diagram, arrow for arrow, plus the derived
  status of a parent order and the contact-visibility rule. `deadlines.py`
  turns a placement time into a response deadline in Addis Ababa business
  hours. Both are pure and unit-tested.
- `service.py` holds the critical operations: the cart, `build_quote`,
  `place_order`, `seller_respond`, `cancel_by_buyer`,
  `expire_unanswered_orders`, and after confirmation `mark_ready`,
  `seller_dispatch` / `staff_dispatch`, `confirm_delivery` (the handover
  code, D-044), `report_delivery_failed`, `return_to_seller`,
  `complete_seller_order` (stock through `_commit_held_stock`, the only
  caller of `commit_stock`, and the fee, D-045), `confirm_received`, `record_direct_payment` (D-046),
  `staff_reissue_handover_code`, the jobs
  `complete_after_problem_window` and `cancel_overdue_fulfilment` (D-043),
  the tracking link (`issue_tracking_link`, `open_tracking_link`, D-048),
  the next-best offer after a decline or an expiry (`next_best_offers`,
  D-049), and problems on a delivered order (`open_dispute`,
  `seller_reply_to_dispute`, `buyer_add_to_dispute`, `resolve_dispute`,
  D-050). A dispute case is guarded by its seller order's lock; the case
  row is never locked on its own.
  **A seller order changes status only through `_move`**, which refuses any
  move that is not an arrow and writes the status event in the same
  transaction. Migration `0007` makes the database refuse the same things, so
  a route cannot get round it. **A shipment changes only through `_track`**,
  which writes the tracking event beside it.
- **Locks are taken in one order, each kind in ascending id:** the buyer's
  cart, then sellers, then offers, then seller orders, then the seller
  order's shipment, then stock through `hold_stock`, `release_stock` and
  `commit_stock`. Sellers, offers, seller orders, shipments and payment
  intents are locked with `with_for_update(key_share=True)` (D-027).
  Reservations are locked `FOR UPDATE` when released or committed, so stock
  is given back, or taken off the shelf, at most once.
- `markx/payments/ledger.py` posts balanced ledger transactions; the fee on
  a completed seller order is its only caller today.
- Who sees what: a buyer's order is found only together with the buyer's
  id; a seller order only together with its seller's id, and it shows only
  that seller's lines (`selectors.py`). Phone numbers appear after the
  seller confirms and vanish if the part ends undelivered. The public
  tracking page (`tracking_view`) is the buyer's page minus the handover
  code, the recipient's details and the actions.
- Tests: `tests/unit/test_order_rules.py`, `tests/api/test_cart.py`,
  `tests/api/test_checkout.py`, `tests/api/test_tracking.py` (the secure
  link), `tests/api/test_fulfilment.py` (placed to
  completed for two sellers, the handover code and its lockout, failed
  deliveries and returns, the payment record, the fee and the ledger, the
  overdue hold), `tests/api/test_next_best_offer.py`,
  `tests/api/test_disputes.py`, `tests/db/test_dispute_contention.py`,
  `tests/db/test_checkout_contention.py` and
  `tests/db/test_fulfilment_contention.py` for the races (100 checkouts of
  the last unit, and every pair of operations that share locks).

## Private files

Identity and licence photos go through `PrivateStorage`
(`markx/core/storage.py`). They are never served by path. A person opens one
through `/documents/{id}/content` with a five-minute link signed for that
person, while signed in. Problem photos work the same way
(`/problem-photos/{id}/content`). Only the local-disk adapter exists.

## Pictures

Blueprint F.6, D.5, D.26; D-062. `markx/images/`. An upload is decoded and
re-encoded at once (`core/images.sanitize_image`), so the camera's metadata
never reaches storage, and kept privately as the picture's source. The
worker (`images.render`) renders WebP in two fixed sizes into
`PublicStorage` and marks the picture `ready`; only ready pictures are
listed. On a laptop the API serves public files at `/api/v1/media/...`; on a
real server they belong on the CDN's cookieless domain
(`MARKX_PUBLIC_MEDIA_BASE_URL`).

## Monitoring

Blueprint F.12; D-064. `markx/ops/`. `checks.py` holds the checks: each
returns findings with a stable key, run each in its own savepoint.
`service.py` turns findings into `ops_alerts` rows (one open per key) and
queues `ops.alert` messages on open and resolve; `alerts.py` sends them to
Telegram when configured, otherwise to the log. To add a check, add a
function to `WATCH` or `RECONCILE`; keep personal data out of its summary.

## The worker

Blueprint F.8. `markx/worker/`, started with `uv run python -m markx.worker`.
It shares the API's configuration, database role and logging. Any number may
run side by side; PostgreSQL decides who does what. One pass of its loop
(`runner.run_once`) does two things:

- **Scheduled jobs** (`jobs.py`). One row per job in `scheduled_jobs` says
  when it runs next. A worker runs a job only while holding that row's lock.
  A job that raises loses its own work, waits a growing delay and stops
  nothing else. To add a job, add a `Job` to `JOBS`; it must be safe to run
  twice.
- **The outbox** (`outbox.py`). One row per transaction: lock a due row with
  `FOR UPDATE SKIP LOCKED`, run the handler for its topic, mark it done,
  commit. To add a topic, add a handler to `HANDLERS`.

Tests drive the worker by calling `run_once(now)` with a clock they control.
D-034 and D-035 record the guarantees and the one limit. Topics today:
`notify.push`, `search.rebuild`, `images.render` and `ops.alert`. Jobs: order
expiry, completion after the problem window (each order in its own
savepoint, D-060), overdue holds, stale offers, payout accounts, the hourly
`search.rebuild_all`, the daily `ops.reconcile` and, last, `ops.watch`.

## Search

Blueprint D.8 and F.7. `markx/search/`. Searches are throttled per
address (D-059).

- `service.py` builds one `search_documents` row per approved product
  (`rebuild_document`) and keeps it fresh (D-051): a `before_flush` listener
  queues a `search.rebuild` outbox row whenever the ORM changes a column a
  document uses; Core statements that change those columns call
  `queue_rebuild` / `queue_for_offers` themselves; stock queues only when an
  offer goes in or out of stock. The hourly job rebuilds everything. **If you
  add a Core `update()` or `insert()` on offers, products, translations,
  aliases, variants or sellers, queue the rebuild in the same transaction.**
  Also the synonym tool and the product-request form.
- `selectors.py` answers queries (D-052): normalise, expand synonyms, match
  by words, sound or letters, filter, rank, log the query.
- Tests: `tests/api/test_search_index.py` (the document follows every kind
  of change) and `tests/api/test_search.py` (matching in three scripts,
  filters, ranking, the log, staff tools, the request form).

## Database

- **Three roles** (blueprint F.3). `markx_migrator` owns the schema and runs
  migrations. `markx_app` is what the API uses: it reads and writes rows,
  cannot change the schema, and cannot update or delete history tables.
  `markx_readonly` reads business data and cannot read credential tables.
- **Money** is whole santim in `bigint` columns. **Time** is UTC. **Keys** are
  UUID version 7.
- **Statuses** are text with CHECK constraints. Seller order moves are also
  checked by a trigger against the G.6 diagram (migration `0007`).
- **History tables only grow**: `audit_log`, `order_status_events`,
  `offer_price_history`, `inventory_movements`, `tracking_events`,
  `ledger_transactions`, `ledger_entries`, `problem_photos`.
- **The ledger balances** in every transaction, checked at commit.
- The chain the schema follows (blueprint G): product, variant, offer, order
  item, seller order, order, payment, ledger.

## Outside services

Each sits behind an adapter with a fake used in tests (blueprint F.0).

| Service | Adapter | State |
| --- | --- | --- |
| SMS | `markx/notifications/sms.py` | Fake only; no provider chosen |
| Telegram push | `markx/notifications/push.py` | Fake only; no bot |
| Bot check | `markx/core/botcheck.py` | Fake only |
| Telegram sign-in | `markx/accounts/service.py` | Signature check built; no bot |
| Private file storage | `markx/core/storage.py` | Local disk only; refused on real servers |
| Public picture storage | `markx/core/storage.py` | Local disk only; refused on real servers |
| Alerts to Telegram | `markx/ops/alerts.py` | Built; tested against a stand-in; no group or bot yet |
| Payments, couriers, AI | | Not started |

## Configuration

Environment variables only, prefixed `MARKX_` (`markx/core/config.py`). The
defaults are for a laptop. On `staging` or `production` the application
refuses to start with development secrets.

Feature switches and limits live in the `settings` table with defaults in code
(`markx/core/settings_store.py`).
