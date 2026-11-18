# Development status

**Last updated:** 17 November 2026, tenth engineering session (the web app's
owner: the buyer's and the seller's screens — reviews and report links
(D-072), pictures and problem evidence (D-074), the rest of the seller
dashboard (D-075) — and, in a second round, every remaining screen the API
supports: the buyer's account, the next-best offer, the category page,
search suggestions, the shop's location, closing and product suggestions,
the staff's trust actions, delivery zones and catalogue setup (D-076 to
D-078)). The ninth session built every admin screen (D-069 to
D-071); a back-end-only continuation in parallel added the seller
performance figures and the weekly seller message (D-073), merged in this
session.
**Branch:** `claude/project-scaffold`. `main` holds the initial commit only
and nothing has been merged into it.
**Latest commit:** see `git log -1`; the handoff (`docs/HANDOFF.md`) names it.
**Read this after** `AGENTS.md` and `MARKX_MASTER_BLUEPRINT.md`.
`docs/HANDOFF.md` holds the last session's report in plain words, the
decisions waiting on the founder, and a ready-to-paste brief for the next
engineer.

This file states what exists, what is tested and what is not. Nothing here is
aspirational. If a line says "tested", the test is in the repository and passed
on the date above.

## In one paragraph

The master blueprint is in the repository. The back end covers the foundation
plus four business phases: the complete Release 1 database schema, sign-in,
the permission model, delivery zones, buyer addresses, the staff-curated
catalogue, seller onboarding and management (P6), seller offers and inventory
(P7), **the background worker** (part of P2), and **the cart, checkout and
multi-seller orders (P9 and P10 on the API side)**. A buyer can fill a cart,
see every price recomputed by the server, place an order that fans out into
one seller order per seller; each seller confirms or declines its own part,
packs it, dispatches it or hands it over at the counter against the buyer's
six-digit code, and records the direct payment; the part completes when the
buyer confirms or the problem window passes, at which point the stock leaves
the shelf and the fee is charged. A silent seller's order expires, a failed
delivery is retried or returned, and an order nobody packs for fourteen days
is cancelled. The buyer's order page also opens from a signed link without
sign-in, never showing the handover code. When a seller declines or stays
silent, the buyer is pointed at the next-best offer from another seller. A
buyer can report a problem inside the 72-hour window, which stops
completion; both sides add their account and staff decide, completing the
part or recording that the seller refunded the buyer directly. **Search**
finds products from one box in Amharic script, Latin-letter Amharic or
English, tolerating typos, with filters, sorting, a query log, a zero-result
report and a synonym tool for staff, and an evaluator scores it against real
queries once the founder supplies them. **The web app** (`apps/web`, Next.js)
now serves the buyer's whole journey in Amharic and English: home, search,
product with the offers table, shop page, sign-in by code, cart, checkout,
orders with the handover code, cancel, "the goods are right", "report a
problem", and the tracking page by secure link; and **the seller dashboard**:
the order inbox with the answer countdown and every fulfilment step, and the
offers list with quick price and stock edits; and **the admin dashboard**:
staff sign-in, the problem queue and decisions, the orders desk, seller
applications with documents, the search tools, and (session nine) product
proposals, invitations, listing takedowns and the audit trail. **CI** runs every API and
web check on every push. **The eighth session (back end only)** added search
throttling (D-059), per-order isolation in the completion job (D-060), a
compatible-copy rule for the API description (D-061), **product pictures and
problem photos** (D-062), **encrypted backups with a restore drill in CI**
(D-063), **self-monitoring with alerts and a daily reconciliation** (D-064)
and **the rest of the admin back end**: the audit-log viewer, switches and
risk limits, staff accounts, the dispatch board and the business dashboard
(D-065), then **reviews and ratings** (D-066), **reports on listings,
stores and reviews** (D-067), **data exports for an accountant** (D-068)
and **the seller performance page with its weekly message** (D-073).
Session nine built the admin screens for them (D-070, D-071). **Session
ten** (the web app's owner) built the buyer's and the seller's remaining
screens: reviews, ratings and report links (D-072), pictures on the product
card and page, shops' own photos and problem evidence (D-074), and the rest
of the seller dashboard, from the application to performance (D-075).
In a second round it built every remaining screen the API supports (D-077),
refused closing a store with orders in progress (D-076) and gave the
settings their Amharic descriptions (D-078). **Not built:** Telegram sign-in
and the bot (they need the bot the founder creates), deployment. Nothing is
deployed anywhere.

## Sessions so far

| Session | Commits | What it added |
| --- | --- | --- |
| 1 | `617a276` to `6f36391` | Blueprint, schema, sign-in, permissions, delivery zones, addresses, catalogue, documents. 454 tests |
| 2 | `8a6e583` to `8df958b` | Status corrections, sellers (P6), offers and inventory (P7). 647 tests |
| 3 | `399507e`, `bd835ef`, `7079cb5`, `eb52d2f` | Review fixes (a moderation bypass, lock ordering), the worker, cart and checkout (P9), multi-seller orders (P10, first half). 779 tests |
| 4 | `7c492c6`, `6582017`, `10573b4` | The second half of P10: ready, dispatch, the handover code, delivered, completed with `commit_stock` and the fee charge posted to the ledger, failed deliveries and returns, the direct payment record, the overdue-hold job, the staff orders desk's first three routes, the tracking page by secure link. 801 tests |
| 5 | `497fcf5`, `5ce4340`, `cdf16c5` and a documentation commit | Review fix (a cancelled shipment had no tracking event), the next-best offer (C-26), problems on a delivered order with staff decisions (`disputed`, `refunded`), search (P8 on the API side). 847 tests |
| 6 | `641a95b` to the head; see `docs/HANDOFF.md` | Review fix (a withdrawn product stayed findable), the founder's provisional approvals (D-053), the search evaluator (D-054), CI, the web app (D-055): the storefront and buyer journey, the seller dashboard, the admin dashboard; demo data (D-056); variant labels in the cart and offer lists. 854 API tests, 9 web unit tests, two browser journeys |
| 7 (parallel, backend only) | after `eab7c21`; see `docs/HANDOFF.md`, Part A.0 | Independent review of search, the next-best offer, disputes, seller isolation and the worker; two search fixes and an evaluator fix (D-057); containers for a laptop and a CI job that builds them (D-058). **`apps/web` not touched** |
| 8 (back end only) | `2e4944c` to `b2b674e`, then the performance commit after session nine's; see `docs/HANDOFF.md`, Part A.00 | Search throttle (D-059); completion job isolates each order (D-060); OpenAPI copy rule (D-061); pictures and problem photos, migration `0008` (D-062); backups and the restore drill (D-063); monitoring, alerts and reconciliation, migration `0009` (D-064); admin back end (D-065); a flaky contention test fixed; then reviews and ratings, migration `0010` (D-066), listing reports, migration `0011` (D-067), data exports (D-068), and the performance page and weekly seller message, migration `0012` (D-073). **`apps/web` not touched** |
| 9 (web owner, resuming) | `eab7c21`, `207aafe`, `22339ed`, `9ac3b94` and the commits after it | The founder's confirmation of the fulfilment hold (D-043, D-053); one test ported from the alternative branch; the takedown queue route `GET /admin/offers/held` (D-069); every admin screen the API supports, a role-aware admin home and menu, codes shown in words, a not-allowed page state (D-070, D-071); `e2e/admin-queues.mjs`. 935 API tests, 21 web unit tests |
| 10 (web owner) | `b2e11ce`, `1920e55`, the merge `d015261`, `ae10c83`, `326ae26`, `af02d59`, `ffa2720`; second round `822f564`, `751e2b0`, `47e9fec` and the documentation commit; see `docs/HANDOFF.md`, Part A.0000 | Reviews and report links for buyers, the shop's replies, `can_edit`/`can_reply` (D-072); thumbnails on the product card (`thumb_url`), the product page gallery, shops' photos, problem evidence (D-074); the rest of the seller dashboard and the application (D-075); then a store with open orders cannot close (D-076), every remaining screen the API supports (D-077) and the settings in Amharic (D-078); `e2e/shop-screens.mjs`, `e2e/seller-dashboard.mjs`, `e2e/setup-and-account.mjs`. 948 API tests, 33 web unit tests |

## Blueprint phase tracking

Phases are the blueprint's P1 to P16 (section L.1).

| Phase | Name | State |
| --- | --- | --- |
| P1 | Project foundation | **Mostly done.** API skeleton, database pipeline, core helpers, **the web shell, the CI pipeline (`.github/workflows/ci.yml`) and the typed link between API and web** are done. **Containers for a laptop** (`apps/api/Dockerfile`, `infra/compose/compose.yaml`; API, worker, PostgreSQL; D-058) are done and built in CI; the web app is not in Compose yet. An automated page-weight check and the three technical reports are **not done**; the page weight was measured once (D-055) |
| P2 | Database and backend foundation | **Mostly done.** Schema, three database roles, error format, request IDs, structured logs, **the worker process with the scheduler and the outbox dispatcher** are done and tested. **Encrypted backups, a scripted restore and a restore drill run in CI** (D-063); **the watch and reconciliation jobs, alerts with Telegram delivery when configured, and a worker health check** (D-064). **Not done:** error tracking (needs an account), the nightly schedule and the off-server copy (deployment), P2 criteria 3 to 5 (they need staging) |
| P3 | Authentication and roles | **Mostly done on the API side.** Phone-code sign-in, sessions, staff sign-in, Telegram signature check and the permission tables are done and tested. The real SMS and bot-check adapters, the account page and admin pages are **not done** |
| P4 | Customer storefront | **Mostly done for Release 1's buyer journey** (D-055): home, search with filters, product page with the offers table, shop page, sign-in, cart, checkout, orders, tracking. Pictures on the product card and page, reviews and report links (session ten, D-072, D-074). **Not done:** the category page as its own screen (search by category stands in), account settings and saved addresses screens, Telegram Mini App shell, server actions so changes work without script, automated browser tests in CI |
| P5 | Product catalogue | **Mostly done on the API side.** Categories, typed attributes, brands, products, variants, translations, staff create/approve/merge/archive, aliases, the restricted-goods list and seller product proposals are done and tested. **The image pipeline** (D-062): upload, metadata removal, WebP in two sizes within the D.26 budgets, rendered by the worker, moderation; criterion 3 is met by automated tests on a laptop. Pictures on the product card and page are shown (D-074). **Not done:** seed data, a real bucket and CDN adapter; merging a product that has offers is still refused (see D-026) |
| P6 | Seller onboarding and dashboard | **Done on the API side.** Application, private document upload, staff review queue, verification levels with the checks behind the badge, owner and manager members, store page, payout account, dashboard counts. The web screens (session ten, D-075): application, documents, team, store settings, legal details, payout account, overview. **Not done:** share cards and QR code, ownership transfer, closing a shop on the web, a real file-storage adapter |
| P7 | Seller listings and inventory | **Done on the API side.** Offers, price history, inventory and movements, quick edit, product proposals, the ranked offers list, the check-in, the stale-offer job **now run by the worker**, and a staff takedown that holds (D-032). The web screens: offers with quick edit (session six), add an offer and the shop's own photos (session ten). **Not done:** the seller Telegram bot, product proposals from a seller on the web |
| P8 | Search and product discovery | **Mostly done on the API side.** Search documents kept fresh through the outbox with an hourly rebuild (D-051); normalisation, letter merging and skeleton keys; prefix, sound and trigram matching; filters and sorting; suggestions and "did you mean"; the product-request form; the query log, the zero-result report and the synonym tool (D-052). **Throttled per address** (D-059). **Not done:** the two completion criteria (a golden set of 100 real queries, and timings at real size), "total cost to the door" as a sort, rating and delivery-speed filters, edge caching and pages readable by search engines (they need the web app) |
| P9 | Cart and checkout | **Done on the API side, and on the web** (cart and checkout screens, D-055). Server-side cart for visitors and signed-in buyers, delivery choice and fees per store, the priced review step, `place_order` with server re-pricing, stock reservation and idempotency. Criteria 1 to 5 are met by automated tests. **Not done:** the web screens, the legal disclosure wording (a founder input), and guest checkout as such: a visitor's cart survives signing in, but the order is placed by a signed-in account (see D-036) |
| P10 | Multi-seller orders | **Done on the API side, except the pieces listed.** Parent and seller orders, the state machine enforced by the database, status events, seller confirm and decline, the response deadline and the expiry job, buyer cancellation, notifications, shipments and payment intents; `ready`, `out_for_delivery` (seller or staff), `delivered` with the derived handover code and its five-attempt lockout, `completed` by the buyer or the worker with `commit_stock` and the fee charge, `delivery_failed`, retry, `returned`, the direct payment record, the overdue-hold cancellation. The tracking page by secure link without sign-in. The next-best offer after a decline or an expiry (D-049). Problems on a delivered order: `delivered -> disputed` by the buyer in the window, `disputed -> completed | refunded` by staff, Release 1 form with no money moved (D-050). Criteria 1, 2 and 4 are met by automated tests (`tests/api/test_fulfilment.py`, `tests/api/test_tracking.py`, `tests/api/test_disputes.py`). **Photos on a problem report** (D-062) and **reviews of completed items with the seller's reply** (D-066) exist on the API. The web screens for both, and the problem's messages and evidence photos, exist (session ten). **Not done:** photos on reviews, the bot. Criteria 3 and 5 need the bot and real buyers |
| P11 | Admin operations | **Mostly done on the API side.** The orders desk, problem cases and decisions, seller review, search tools (earlier sessions); **the audit-log viewer, switches and risk limits, staff accounts, the dispatch board, the business dashboard, picture moderation and the operations status** (D-062, D-064, D-065). **Review moderation (AD-12) and the reports queue (AD-16)** too (D-066, D-067). **Data exports for an accountant** (D-068) and **seller performance figures with the weekly message** (D-073). Session nine built their admin screens (D-070 to D-072). The seller's performance screen exists (session ten, D-075). **Not done:** the runbooks, seller statements (Release 2) |
| P12–P16 | Everything else | **Not started** (tables exist; no behaviour) |

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
- Migrations `0004` to `0007`: see the migration table at the end.
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
- **The seller order life cycle is a database fact** (migration `0007`,
  tested with plain SQL): a seller order can only be created as `placed`; a
  status change that is not an arrow of the blueprint's G.6 diagram is
  refused by a trigger; and a transaction that changes a status without
  writing the matching `order_status_events` row is refused at commit. A
  test checks that the database's move function and the code's table agree
  on all 196 pairs of states.

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

### Product catalogue (blueprint D.5, D.6, P5)

- A category tree up to three levels, with names in Amharic and English.
- Typed attributes (text, number, list of options), attached to a category as
  required, filterable or variant-defining. A category inherits the attributes
  of the categories above it.
- Products with names and descriptions in both languages, specifications
  checked against the category's rules, and variants. A product with nothing
  to choose gets one default variant, so offers always attach to a variant.
- **The database rejects a duplicate variant** (blueprint P5 criterion): a test
  inserts one with plain SQL and the unique constraint refuses it.
- Staff create, approve, archive and merge products. Only approved products
  have a public page. A merged product keeps its link, which forwards to the
  survivor, and its names become search aliases of the survivor. Merges chain.
- The restricted-goods list blocks a listing whose name or description
  contains a listed word. It matches whole words after the same normalisation
  search uses, so letter case and same-sound Amharic letters cannot slip past.
- Public, briefly cacheable routes for the category tree, a category with its
  filters, brands and a product page, each in the asked language with a
  fallback to the other.
- Permissions follow blueprint C.4 and are tested for all five staff roles.

### Sellers (blueprint D.3, D.4, C.3, C.5, P6)

Code: `markx/sellers/`, `markx/core/storage.py`, `markx/core/images.py`.
Routes: `/seller/...`, `/admin/sellers/...`, `/catalog/stores/{slug}`,
`/documents/{id}/content`.

- **Invitations.** Onboarding is invite-only (setting `sellers.invite_only`).
  Staff invite a phone number; the invitation is used once, by the account
  that owns that number, and expires after 14 days.
- **Application.** A signed-in person opens a draft application (business
  details, TIN, shop address), uploads the four document photos, adds a
  payout account and submits. Staff cannot see a draft. One application at a
  time per person; one live seller per TIN. Individual sellers are switched
  off by a setting, as the blueprint requires.
- **Documents.** Photos only (JPEG, PNG, WebP). The file is decoded and
  written out again, so a file that only claims to be a picture is refused
  and location data is removed. Files go to private storage under an
  unguessable key and are never served by path.
- **Document links.** A link works for five minutes, only for the signed-in
  person it was issued to, and only while that person is still allowed to
  see the document. Issuing a link and every view are written to the audit
  log. (P6 completion criterion 3.)
- **Staff review.** A queue paged by cursor; accept or reject each document;
  ask for more documents; approve at Level 1 or 2; reject with a reason;
  suspend and reinstate; raise or lower the level; sign off the yearly
  re-check. A level is granted only when the accepted, unexpired documents
  behind it exist: Level 2 needs identity, licence, TIN certificate, shop
  photo and a recorded shop visit. Level 3 is given only to a seller already
  at Level 2. A staff member cannot decide about a seller they belong to.
- **Database rules** (migration `0004`): a seller can be `active` or
  `suspended`, or hold a level above 0, only if its application is
  `approved`. A test attacks this with plain SQL.
- **Members.** The owner or a manager adds a manager by phone number; two
  seats on the free plan; the owner can never be removed; a member can
  leave. A removed member loses access on the next request.
- **Store page.** Name, description, policies, hours, areas, Telegram
  channel. The public page exists only for a trading seller and shows the
  level, what was checked and completed orders, and never the phone number.
- **Payout account.** The number is encrypted; only the last four digits are
  ever returned. The first account is active at once; a later change waits
  72 hours and the owner is notified. `activate_due_payout_accounts` applies
  a waiting change, and **the worker now runs it** every five minutes.
- **Seller isolation** (P6 completion criterion 2, blueprint C.5). Tested in
  `tests/api/test_seller_isolation.py`: seller A cannot read or change
  seller B through any route; B's document, member or offer id placed under
  A's own seller id is "not found"; a link signed for B does not open for A;
  another seller's id gives the same answer as an id that does not exist. One
  test walks **every** route under `/seller/{seller_id}` taken from the API
  description, so a route added later is checked without anyone remembering.
  The order routes added this session are covered by it.
- **Staff permissions** (C.4): only the super administrator and operations
  review sellers and open documents; tested for all five staff roles, a
  visitor, a customer, a seller, and a staff member signed in by phone code,
  over every `/admin/sellers` route.

### Offers and inventory (blueprint D.7, G.4, G.9, P7)

Code: `markx/offers/`. Routes: `/seller/{seller_id}/offers...`,
`/seller/{seller_id}/dashboard`, `/seller/{seller_id}/product-proposals`,
`/catalog/products/{slug}/offers`, `/catalog/stores/{slug}/offers`,
`/admin/offers/{id}/remove`, `/admin/offers/{id}/restore`.

- **Offers.** A trading seller attaches an offer to a variant of an approved
  product: price, condition, warranty, delivery options, stock. One offer
  per seller, variant and condition; **the database rejects a duplicate**
  (tested with plain SQL and with 20 simultaneous identical requests).
  Quick edit, pause, resume, remove; a removed offer listed again reuses its
  row so its history is continuous. Used goods need Level 2.
- **A staff takedown holds** (migration `0005`, D-032, found in this
  session's review): a seller cannot relist an offer that staff took down,
  not even by removing it first; a CHECK keeps a held offer `removed`
  whatever the code does; `POST /admin/offers/{id}/restore` lifts the hold.
- **Price history.** Every price change writes a row. Sending the same price
  again counts as confirming it.
- **Inventory.** Stock changes only through `markx/offers/service.py`, and
  every change writes a movement in the same transaction. The seller types
  the counted number; it cannot go below what is held for orders.
- **Stock holds.** `hold_stock`, `release_stock` and `commit_stock` are the
  conditional update of blueprint G.9. **Tested: 100 simultaneous buyers of
  the last unit, exactly one hold.** Checkout now calls `hold_stock` and
  `release_stock`; nothing calls `commit_stock` yet (completion is not built).
- **Ranked offers for a product page.** Only active offers of trading
  sellers at the launch level (`sellers.min_level_to_publish`, default 2).
  Computed on every read, never stored.
- **Freshness.** One-tap check-in confirms all live offers.
  `mark_stale_offers` hides an offer whose price was not confirmed for 14
  days, and **the worker runs it** every hour. The check-in and the job lock
  the rows they change in id order (D-033) and a test races them.
- **Product proposals.** A seller proposes a missing product; it is always
  `pending_review`, whatever the request says, and invisible until staff
  approve it.
- **One seller cannot edit another's offer** (P7 criterion 3): tested on
  every offer route, with the offer id under both seller ids.

### The worker (blueprint F.8, D.16, P2)

Code: `markx/worker/`. Command: `uv run python -m markx.worker` (`--once`
runs one pass). Decisions D-034 and D-035.

- **Scheduled jobs**, one row each in `scheduled_jobs` (migration `0006`):
  `orders.expire_unanswered` every minute, `sellers.activate_due_payout_accounts`
  every five minutes, `offers.mark_stale` every hour. A worker runs a job only
  while holding the row's lock, so two workers never run one job at once; a
  dead worker leaves the job due; a job that raises loses only its own work
  and is retried after 1, 2, 4 ... 60 minutes; three failures in a row are
  logged at CRITICAL.
- **The outbox dispatcher.** One row per transaction, claimed with
  `FOR UPDATE SKIP LOCKED`; a handler that raises is retried after 30 s, 1,
  2, 4 ... minutes up to an hour and given up after 8 attempts; a worker that
  dies mid-row leaves it pending and untouched; one bad row never blocks the
  rest. The only topic is `notify.push`: an in-app notification is passed on
  to the person's Telegram when they have linked it. **The only push adapter
  is a fake**; on a real server the factory refuses it, so nothing is ever
  pretended sent.
- Tested (22 tests, `tests/worker/test_worker.py`): a committed message is
  delivered exactly once and one from a rolled-back transaction never (P2
  completion criterion 2); retries with growing delays; two workers never
  take the same row or run the same job; eight workers deliver 120 messages
  exactly once; a crash mid-row or mid-job loses nothing; a failing handler
  or job stops nothing else. Every test calls the worker's own loop with a
  clock it controls; nothing sleeps.

### Cart, checkout and orders (blueprint D.10, D.11, G.5 to G.7, P9, P10)

Code: `markx/orders/`, `markx/payments/ledger.py`. Routes: `/cart...`,
`/checkout/quote`, `/checkout`, `/me/orders...`,
`/seller/{seller_id}/orders...`, `/admin/orders...`, `/track/{order_id}`.
Decisions D-036 to D-050.

- **The cart** lives on the server. A visitor's cart is found by a secret in
  an `HttpOnly` cookie (only its hash is stored); it moves into the person's
  own cart when they sign in. A line records the offer, the quantity and the
  price the buyer saw. Reading the cart re-checks every line against live
  data and says what changed: a new price, an item out of stock, an offer or
  seller no longer available. An offer buyers cannot see on the product page
  cannot be put in a cart either. Up to 30 lines, 20 units each.
- **The review step** (`POST /checkout/quote`) prices the cart for one
  address and one delivery choice per store, all from the database: item
  totals, the fee for the chosen method into the buyer's zone, the grand
  total, and who the buyer is buying from (legal name, shop address, return
  policy). A method is offered only if every line from that store supports
  it, because a seller order travels as one shipment.
- **`place_order`** (`POST /checkout`) runs in one transaction, exactly as
  G.5 lists: the buyer's cart row is the lock; the same idempotency key
  returns the same order; every offer is re-read with its seller under a
  lock; the price in the cart must equal the live price (else
  `price_changed`) and the total the buyer saw must equal the recomputed one
  (else `total_changed`); a member of a store cannot buy from it; the open
  order cap and the largest order value apply; stock is held **in ascending
  offer id order** with one `inventory_reservations` row per line, and one
  line short rolls everything back with the offer named (`out_of_stock`);
  then the parent order with its address snapshot, one seller order per
  seller with its own totals and response deadline, the order items with
  their own copy of the title in both languages, the variant label, the
  price and the commission rate in force, a shipment and a payment intent
  per seller order, a `placed` event per seller order, and a notification
  for every seller's order handlers and for the buyer. The cart is emptied.
- **The seller's side.** `GET /seller/{id}/orders` lists one seller's parts
  of orders, newest first with a cursor, and never another seller's lines or
  the buyer's grand total. Confirm or decline, only by a member whose role
  handles orders, only while `placed` and inside the response window. A
  decline needs a reason and gives the stock back. The seller sees the fee
  in birr before confirming.
- **The buyer's side.** `GET /me/orders` and the order page, with the
  parent's status derived from the seller orders on every read. The buyer
  cancels one seller's part while it is `placed` or `confirmed`; the stock
  returns and the seller is told.
- **Phone numbers** appear on each side only after the seller confirms, and
  disappear again if the part ends undelivered (blueprint C.5).
- **The response deadline** counts business hours in Addis Ababa time
  (settings `orders.response_window_minutes`, `orders.business_open_hour`,
  `orders.business_close_hour`): an order placed at night is due half an
  hour after the shops open. **The worker expires unanswered orders** every
  minute and releases their stock; a late seller never blocks the others.
- **Commission.** The most specific rule in force (seller, plan, category,
  default) is copied onto each line as basis points. No rule exists today,
  so every line carries 0, which is what blueprint D.19 says for direct
  orders in year one. Rules can only be inserted by hand; the admin routes
  belong to P11.
- **Tested** (`tests/api/test_cart.py`, `tests/api/test_checkout.py`,
  `tests/db/test_checkout_contention.py`, `tests/unit/test_order_rules.py`):
  the five P9 completion criteria, including **100 simultaneous checkouts of
  the last unit create exactly one order** and **fifty buyers competing for
  ten units get exactly ten**; a lowered total and a stale cart price are
  refused; the same submission twice creates one order and another buyer's
  identical key does not return it; a two-seller order, every row it writes,
  the moves each part makes on its own and the parent's derived status; every
  status change is in the log and a move outside the diagram is refused by
  both layers; the line keeps its copy when the product is renamed, the
  price changed and the offer removed; the commission rule lookup; delivery
  choices; limits; who may answer; the deadline; buyer cancellation; one
  buyer never sees another's order and one seller never sees another's
  part; the buyer's phone is hidden until confirmation. Contention: checkout
  raced against the seller's price edits and stock counts, and confirm,
  decline, cancel and expiry raced for one order, with the stock released
  at most once.
- **Fulfilment (session four).** Seller routes under
  `/seller/{seller_id}/orders/{id}/`: `ready`, `dispatch` (rider name and
  phone, optional), `handover` (the buyer's code), `delivery-failed`,
  `return`, `payment`. Buyer: `confirm-received`. Staff: `GET
  /admin/orders/{code}` (`find_orders`), `POST
  /admin/orders/seller-orders/{id}/dispatch` and `/reissue-code`
  (`intervene_in_orders`, audit-logged). Every shipment change writes a
  tracking event; the buyer's page shows the shipment timeline, the rider's
  name and phone once dispatched, and the handover code from `ready` until
  the handover; the seller's page shows attempts left and, once completed,
  the fee charged. Worker jobs: `orders.complete_after_problem_window`
  (five minutes) and `orders.cancel_overdue_fulfilment` (ten minutes,
  D-043, provisional). Completion is the only caller of `commit_stock` and
  writes `fee_charges`, with a balanced ledger posting when the fee is above
  zero. Tests (`tests/api/test_fulfilment.py`, 10;
  `tests/db/test_fulfilment_contention.py`, 4): a two-seller order placed to
  completed with both delivery modes (P10 criterion 1); five wrong codes lock
  the shipment, the right code is then refused, staff reissue and the old
  code is dead; the code never appears in a seller or staff response, nor in
  any shipment column; a failed delivery retried and returned, stock back,
  intent cancelled; out-of-order moves refused; staff dispatch and who may
  intervene; the payment recorded once with the audit row; a 3% rule charged
  at completion and posted as a balanced debit and credit; an overdue hold
  cancelled by the worker while a dispatched parcel is left alone; the stock
  trail replays exactly after every path. Contention: the right code, a
  failed handover, a return and the hold job racing for one parcel; the
  buyer, the worker and the payment record racing to complete; twenty wrong
  codes at once counting exactly five; the worker's cancellation racing the
  seller's dispatch.
- **The tracking page by secure link (D.14, D-048).** `GET
  /track/{order_id}?expires=&signature=` without sign-in: a 256-bit
  signature over the order id and a sixty-day expiry, one `404` for a forged,
  expired or retargeted link. The page is the buyer's view minus the
  handover code, the recipient's name, phones, pin and notes, and the
  actions; the seller's and rider's contact appear under the usual rules.
  The "placed" notification carries the path for the Telegram or SMS
  message; the signed-in page carries a fresh one; staff and sellers get
  none. Tests (`tests/api/test_tracking.py`, 2): the page before and after
  dispatch, in both languages, with the code shown on the signed-in page
  and absent here; a forged signature, a shifted expiry, another order's
  signature, an unknown order, a missing parameter, a link sixty-one days
  old, a link that claims to live too long.

- **Review fix (session five).** `_release_everything` cancelled waiting
  shipments with a bulk `UPDATE` and no tracking event, on decline, buyer
  cancellation, expiry and the overdue-hold job: four paths broke "every
  shipment change writes its event" (J.10). It now locks those shipments in
  id order (after the seller orders, before the stock) and cancels each
  through `_track`. Test: `test_every_cancelled_shipment_has_its_tracking_event`,
  which failed on the old code (an empty trail) and passes now.
- **The next-best offer (C-26, D-049).** On a decline or an expiry the buyer
  gets one `order.next_best_offer` notification per line that has an
  alternative: the best offer in stock for the same variant from another
  seller, by the product page's own ranking for the buyer's zone. `GET
  /me/orders/{order_id}/seller-orders/{id}/alternatives` reads it live.
  Nothing is reserved; the buyer buys through the normal checkout. Tests
  (`tests/api/test_next_best_offer.py`, 5): Beta declines and Alpha is
  suggested; Alpha stays silent and Beta is suggested; nothing when no other
  seller has the variant or the other offer is out of stock; another buyer
  gets 404 and a visitor 401.
- **Problems on a delivered order (D.17, G.6, G.7, D-050).** Buyer: `POST
  /me/orders/{order_id}/seller-orders/{id}/problem` (type and description,
  only while `delivered` and inside the window) and `.../problem/messages`.
  Seller: `POST /seller/{seller_id}/orders/{id}/problem/reply`. Staff with
  `handle_cases`: `GET /admin/orders/problems` (the queue, most urgent
  first) and `POST /admin/orders/seller-orders/{id}/resolve-problem`
  (`no_action` completes the part with stock committed and fee charged;
  `seller_refunded` marks it `refunded`, no fee, stock back on sale if
  `goods_returned`, otherwise off the count). A written reason always, an
  audit row always. The buyer's and the seller's pages carry the case and
  its messages by role; the tracking link shows only the status. Setting
  `orders.problem_decision_hours` (48). Tests (`tests/api/test_disputes.py`,
  5; `tests/db/test_dispute_contention.py`, 2): a report stops the worker's
  completion; both sides add their account; support decides; refunds with
  and without the goods returned, with the stock trail replaying exactly and
  nothing in the ledger; who may report, reply and decide (another buyer,
  another seller, finance and catalogue staff all refused); no report after
  the window. Contention: a report racing the buyer's "received" and the
  worker's completion (exactly one wins); two staff decisions and a seller
  reply racing on one case (exactly one decision, stock settled once, no
  message after the decision).

### Search (blueprint D.8, F.7, AD-07, P8)

Code: `markx/search/`. Routes: `GET /search`, `GET /search/suggest`, `POST
/product-requests`, `/admin/search/zero-results`, `/admin/search/synonyms`.
Decisions D-051 and D-052.

- **Documents.** One per approved product: names in both languages, brand,
  model, model codes, aliases and category names, normalised; the `simple`
  full-text vector; skeleton keys; category path, brand, facets (condition of
  in-stock offers, specs and variant attributes); the lowest in-stock price,
  offer and seller counts, in stock, best seller level, freshest price,
  popularity. Rebuilt through the outbox in the transaction that made the
  change (a flush listener for ORM changes, explicit calls for Core
  statements, stock only when an offer goes in or out of stock), and all of
  them hourly by the worker.
- **Queries.** Normalised like documents, expanded by synonyms, matched by
  words (prefix), sound (skeleton keys) or letters (trigrams, every word),
  ranked by match tier, stock, freshness, seller level, price, popularity.
  Filters: category with its sub-categories, brand, condition, price range,
  seller level, in stock. Sorts: relevance, price, freshness. Every first
  page logged with its count. "Did you mean" when nothing matches.
- **Tests** (`tests/api/test_search_index.py`, 6; `tests/api/test_search.py`,
  26): the document holds what a buyer can find; stock crossing zero moves
  the lowest price (and a purchase that does not empty an offer queues
  nothing); a price change, a pause and a seller suspension reach it; the
  stale job's bulk update and the bulk check-in reach it; a rename, an alias
  added and removed, and an archive reach it; the hourly rebuild repairs a
  missing document and is safe to run twice. Thirteen spellings find the
  Samsung (English, Amharic script with two vowel spellings, Latin-letter
  Amharic, no vowels, a model code, a typo only trigrams catch) and six find
  the Tecno; results are products with the card's facts; a draft is never
  found; every filter; ranking and both sorts; the query log and the
  zero-result report with its permission; "did you mean" and suggestions;
  synonyms for a whole query and for one word, with their refusals,
  permission and audit rows; the product-request form with its phone check
  and its hourly limit.

### The web app (blueprint F.1, I, P4; D-055)

Code: `apps/web`. One Next.js 16 app in strict TypeScript with Tailwind 4;
every page under `/am` or `/en`; all text in `messages/am.json` and
`messages/en.json`. Pages read the API on the server with the visitor's
cookies and never cache; changes go from the browser to `/api` on the same
origin, so the API's cookies, CSRF token and origin check apply unchanged.
API types are generated from the API's OpenAPI description.

- **Storefront:** home (search, categories, popular products, protection),
  search (filters, sorting, paging as GET forms; "did you mean"; the
  product-request form), product (versions, the offers table for the chosen
  area with delivery and total, each price's age, the seller's level, the
  best offer and why, add to cart, specifications), shop page (level and
  what was checked, member since, completed orders, offers).
- **Buyer:** sign-in by phone and code, account and sign-out, cart (groups
  by shop, quantities, price changes, unavailable lines), checkout in four
  steps (address, delivery per shop, payment, the server's priced review
  with each seller's legal details), orders and the order page (status per
  shop, the handover code and its warning, contacts, timeline, cancel,
  "the goods are right", "report a problem"), the tracking page by link.
- **Tested:** `npm run lint`, `npm run typecheck` (strict), `npm test`
  (9 Vitest tests: price and time formatting, message keys and
  placeholders equal in both languages, API errors always in words) and
  `npm run build`, all in CI. `e2e/buyer-journey.mjs` drives the whole
  journey in Chromium against the demo data, the buyer's side and the shop's
  side through their screens (including a wrong handover code), and passed
  on 17 November 2026
  (not in CI: it needs a running API with demo data). Checked by hand at
  320, 360, 768 and 1280 pixels: no page is wider than the screen.
- **Seller dashboard** (`[lang]/seller/{seller}`): the order inbox by stage
  with the answer countdown and the payout after the fee; the order page
  with accept, decline with a reason, mark as packed, send with a rider,
  enter the buyer's code (attempts left; lockout), delivery failed, goods
  back on the shelf, record the payment, answer a problem; offers with
  counts, one-tap "still right", in-place price and stock edits, pause and
  resume. Seller isolation stays the API's: every call is checked by
  `require_seller`.
- **Admin dashboard** (`[lang]/admin`): staff sign-in with password and
  authenticator; a side menu showing only what the role may do (C.4); the
  problem queue (overdue marked); the orders desk (any order by code, full
  timelines, decide a problem, dispatch, a new handover code); seller
  applications (documents through five-minute links, accept or reject each,
  approve, ask again, reject); search tools (zero results, synonyms).
  `e2e/staff-journey.mjs` runs a problem from the buyer's report to the
  staff decision and checks isolation at both layers (another shop's
  dashboard and API: 404; the admin area and API for a buyer: 403).
- **Admin queues added in session nine** (D-070): product proposals
  (approve, turn down with a note, merge into an approved product),
  invitations (invite a phone number, withdraw an open one), listing
  takedowns (find a product's live offers by its link name, take one down
  with a reason, the queue of held listings with the reason, lift a hold;
  D-069), and the audit trail over D-065's viewer (filters by kind of
  record, record, action or a family of actions; "older entries"). The menu
  comes from one table of queues and the capability that opens each; the
  admin home sends each role to its first queue; roles, review states,
  seller, document and product statuses are shown in words in both
  languages; a page the API refuses says so.
- **The rest of the admin screens** (D-071): the dashboard (the API's figures
  for 1, 7, 30 or 90 days), the dispatch board (late parts marked, each
  opening in the orders desk), operations (open alerts, scheduled jobs, the
  outbox), reviews (held first; publish or hide with a reason), reports
  (acted on or dismissed with a note), settings (each row changeable only if
  the API says so), staff accounts (create — the authenticator secret shown
  once — change a role, switch off), exports (four CSV files; a refused
  period shown in words) and pictures (every state with its thumbnail;
  upload, take down). `menu.test.ts` checks the exact screens of each of the
  five staff roles.
- `e2e/admin-queues.mjs` drives all of it in Chromium against the demo data:
  15 steps, "console errors: none": proposals, invitations, a takedown lifted and relisted, the audit trail in English and Amharic, a rider order on the dispatch board, the dashboard, operations, a held review published, a report dismissed, a setting changed and restored, a staff account created (its shown secret signs it in), re-roled and switched off, an export downloaded and a reversed period refused, a picture uploaded, rendered and taken down, every page at 360 px, and a catalogue curator who sees only its six screens.
- **Reviews and reports** (session ten, D-072): the product and shop pages
  show the API's rating totals and published reviews, ten at a time; the
  buyer rates an item on the order page while the API lists it as waiting,
  and keeps every review on `/reviews` with its state, MarkX's reason if
  hidden, the shop's reply, and a change form while the API says
  `can_edit`; the shop answers on its Reviews screen where the API says
  `can_reply`. A report link sits on every product, listing, shop and
  review, for anyone. `MyReviewOut` gained `can_edit` and `can_reply`
  (both sides in one commit).
- **Pictures** (session ten, D-074): the product card carries the first
  ready catalogue thumbnail (`ProductCardOut.thumb_url`, both sides); the
  product page shows the catalogue pictures and "Photos from shops"; a shop
  manages its own photos of each product it sells (upload, withdraw); the
  evidence photos on a problem are on the buyer's order page, the shop's
  order page and the orders desk, with uploads while the problem is open,
  and the buyer can add messages to it. Message authors are in words.
- **The rest of the seller dashboard** (session ten, D-075): an overview
  (shop and application state, what is missing, send for review, what MarkX
  checked, every screen of the role), performance (the API's figures for 7,
  30 or 90 days and the weekly messages, D-073), add an offer from the
  catalogue, store settings, team, documents behind signed links, legal
  details, payout account; and the application form on `/seller` for an
  invited person. The seller menu follows the member's capabilities
  (`seller/[sellerId]/menu.test.ts`, per role of C.3).
- `e2e/shop-screens.mjs` (14 steps) and `e2e/seller-dashboard.mjs` (11
  steps) drive all of it in Chromium against the demo data, "console
  errors: none": a purchase rated, changed, shown on both pages, answered
  by the shop and then fixed; reports signed in and out, a second one
  refused in words; a shop's photo rendered, shown and withdrawn; a problem
  with a message and photos from both sides, seen by staff and decided; a
  catalogue picture on the product page and the product card; and a new
  invited phone taken from application to an approved shop with its store
  settings on the public page, a manager added and removed, an offer
  published and the performance page. Every page at 360 px in both
  languages.
- **Demo data:** `apps/api/scripts/seed_demo.py` (D-056), laptop only.
- **Third round** (D-079 to D-081): a store page's track record (accepts
  share, typical time to accept, delivery success over 90 days), search by
  rating and seller level, a single worker pass that reports failure in its
  exit code, and the browser journeys on GitHub when asked.
- **The remaining screens** (session ten, second round, D-077): the buyer's
  account (`/account`: name and language, saved addresses, messages from
  MarkX in words, data requests, sign out on every device), the next-best
  offer on a declined or expired part, the category page (`/c/{slug}`),
  search suggestions; the shop's location with a map link, closing the shop
  (refused while orders are in progress, D-076), suggesting a product; for
  staff a shop's level and standing, delivery zones with areas and fees,
  catalogue setup and the products screens. `e2e/setup-and-account.mjs` (13
  steps) drives them all. The settings screen shows Amharic descriptions on
  the Amharic page (D-078).
- **Known gaps:** Telegram sign-in and linking (`/auth/telegram`,
  `/me/telegram`) wait for the bot. Variant
  labels ("Black · 128 GB") come from the API in the cart, the seller's
  offers and the shop's price list, built by the same code as the product
  page (`catalog.selectors.variant_labels`).

### CI (blueprint P1)

`.github/workflows/ci.yml`, on every push and pull request, on GitHub's
hosted runners: the API job (PostgreSQL 17 service, ruff, ruff format,
strict mypy, migrations with `alembic check`, the whole suite in one
session, and a check that the web app's copy of the API description is
current) and the web job (lint, strict types, unit tests, production
build, and a check that the generated API types are current). First runs:
#1 to #4 passed.

`.github/workflows/journeys.yml` (D-081) runs the six browser journeys in
Chromium against a fresh demo database, only on a push whose message
contains `[journeys]` (or, once on the default branch, from the Actions
tab). It raises the sign-in limits on its throwaway database, keeps the
screenshots and server logs for a week. Its first run is recorded in the next commit.

### The search evaluator (P8 criteria; D-054)

`uv run python -m markx.search.evaluation FILE.csv` scores real queries
against the real search and writes nothing. The template is
`apps/api/search_eval/golden_queries.template.csv`. Tests
(`tests/api/test_search_evaluation.py`, 5) use a file marked SYNTHETIC.
**No real query exists yet; the 85% target is not measured.**

### Eighth session: back end only (D-059 to D-065)

All of it under `apps/api` and `infra/`; `apps/web` was not modified.

- **Search throttle** (D-059): `/search` and `/search/suggest` count each
  request per network address and minute (settings
  `search.requests_per_ip_per_minute` 120, `search.suggestions_per_ip_per_minute`
  300); past the limit, 429 before the search runs, so nothing is logged.
- **The completion job completes each order on its own** (D-060): one
  savepoint per order, commit-time checks forced inside it; a failing order
  stays delivered and is retried, the rest complete.
- **API description** (D-061): `apps/api/openapi.json` is checked exactly;
  the web app's copy must stay true for everything it has, and may lag
  behind additions (`scripts/check_openapi_copy.py`). It caught a schema-name
  clash in this session before it reached CI.
- **Pictures** (D-062, `markx/images/`): catalogue pictures (staff) and real
  photos (sellers with an offer), cleaned at upload, rendered by the worker
  to WebP in two sizes within 30 KB and 150 KB, no metadata, moderation by
  staff; problem photos for both sides of an open problem, private, by
  five-minute link, append-only.
- **Backups** (D-063, `infra/backup/`): `backup.sh` (encrypted dump),
  `restore.sh` (new database only), `drill.sh` (backup, restore, compare,
  clean up), run by CI on the demo data.
- **Monitoring** (D-064, `markx/ops/`): `ops.watch` every five minutes and
  `ops.reconcile` daily; alerts open, persist and resolve once each, through
  the outbox, to Telegram when configured; `GET /healthz/worker` for an
  outside monitor; `GET /admin/ops/status` and `/admin/ops/alerts`.
- **Admin back end** (D-065, `markx/admin/`): the audit-log viewer, settings
  and risk limits, staff accounts, the dispatch board, the business
  dashboard.
- **Reviews and ratings** (D-066, `markx/reviews/`): one review per item of
  a completed order, by its buyer, within 60 days; suspicious ones held for
  staff; the seller's reply; staff moderation; public product and store
  review pages; rating totals per product and seller, recounted through the
  outbox and daily.
- **Reports** (D-067, `markx/reports/`): anyone flags a product, offer,
  store or review they can see; one open report per person and target;
  the staff queue; resolution as actioned or dismissed with a note, for
  every report on a target at once; reporters told the outcome.
- **Data exports** (D-068, `markx/exports/`): four CSV files for an
  accountant (fees, ledger, seller orders without buyer data, seller
  balances), whole Addis Ababa days, exact amounts, formula-safe,
  audit-logged; super administrator and finance only.
- **Seller performance** (D-073, `markx/performance/`): the performance page
  in numbers for every store member, and the weekly message: an hourly job
  stores each trading store's figures for the last Monday-to-Sunday week
  once and tells its members.

## What exists but is NOT tested

Be careful with these. They were written and never exercised.

- Models for refunds, payouts, reviews, reports and analytics: the tables
  exist and are constrained; **no service, route or test uses them**.
  `product_requests` are written and never read by a route yet.
- `fee_charges.reversal_ledger_transaction_id` and `reversed_at`: unused.
  Release 1 never charges a fee on a refunded part, so nothing is reversed
  (D-050).
- `refunds`, `payouts`, provider webhooks: tables only (Release 2).
- `stores.logo_key`, `order_items.image_key`: columns with no behaviour.
  (Earlier versions of this list named `offer_price_tiers` and
  `seller_metrics_daily`; neither table exists in the schema. D-073.)
- `TelegramAlertSender` is tested against a stand-in for Telegram's API,
  never against Telegram itself (no bot or group exists yet).
- `commission_rules`: read by checkout, never written by any route.

## What does not exist

- On the web: Telegram sign-in and linking (the bot does not exist yet).
  Every other route a person uses has its screen (D-070 to D-078); the
  remaining unused routes are the development SMS inbox, the health checks
  and the file links the API hands out.
- Photos on reviews, ratings on product cards and in search, payments beyond the direct payment record
  (Release 2: Protected prepay, refunds through a provider, payouts).
- Ownership transfer between seller members (needs the founder's decision,
  F-02).
- Store logo upload, share cards, QR code.
- The seller Telegram bot and the real push adapter: the worker delivers
  pushes to a fake.
- A real private-storage adapter (F-01), a real SMS adapter, a bot-check
  adapter.
- The reverse proxy, error tracking, the nightly backup schedule and the
  off-server copy, an outside uptime monitor, a real public-storage bucket
  and CDN. (Containers, backups, the drill and alerting exist; demo seed
  data exists for laptops only.)
- Anything on AWS. Nothing has been deployed and no cloud resource was created.

## Lessons

- **Untested code was wrong.** Migration `0002` shipped a ledger trigger that
  made every ledger insert fail. It applied cleanly and looked correct. The
  first test that inserted a ledger row found it. Treat every item under
  "exists but is NOT tested" as probably broken until a test says otherwise.
- **A race test found a deadlock that no single-request test could.**
  Editing an offer locked the offer row with `FOR UPDATE` and then the stock
  row; a buyer's hold locked the stock row and then, through the movement's
  foreign key, needed the offer row. Under 60 threads PostgreSQL killed one
  of them. Offer and seller rows are now locked with `FOR NO KEY UPDATE`
  (D-027). Write a contention test for every operation that takes two locks.
- **`now()` is the transaction's start time.** Two stock movements written
  by one transaction had the same `created_at`, so their order was a coin
  toss. Movements and status events are stamped with `clock_timestamp()`
  (D-028).
- **A review of working code found a real hole.** The relist path of
  `create_offer` was correct for a seller's own removal and wrong for a staff
  takedown; the existing tests covered each half and never the two together
  (D-032). When reviewing, look for two correct features that compose into
  one wrong one.
- **`INSERT ... ON CONFLICT DO NOTHING` waits.** It blocks behind a
  transaction that holds the conflicting row, so a worker that "registered"
  its job inside the job's own transaction made a second worker wait for the
  whole run instead of skipping it (D-035).
- **A bulk `UPDATE` locks rows in plan order.** Two of them over the same rows
  can deadlock. Select the ids `ORDER BY id FOR NO KEY UPDATE` first (D-033).
- **If the page needs to know whether someone may act, ask the API.** The
  review edit form would have needed the service's window and reply rules
  copied into the page; two booleans in the response (D-072) keep the rule
  in one place and are tested against the service's own refusals.
- **A browser journey's own `fetch` obeys `Cache-Control`.** The public
  picture list is `max-age=60`, so a check right after an upload read the
  old list. Journeys call the API with `cache: 'no-store'`.
- **`role="alert"` is not only yours.** Next.js's route announcer has it
  too; wait for the form's own message (`form [role=alert]`).
- **Make every browser journey repeatable and self-cleaning:** tag what a
  run writes, decide or undo what an interrupted run left (an open problem
  blocked the next order; a new shop's cheaper offer would have changed
  another journey's best offer), and screenshot every page when a step
  fails.
- **Two sessions on one branch can take the same decision number.** Fetch
  before choosing one; on a clash keep both entries and renumber your own
  (D-074 here).

## Known problems

- **The browser journeys use the demo phones' sign-in codes**, five per phone
  per hour (`auth.otp_per_phone_per_hour`, working as designed). The admin
  journey signs each demo phone in once per run, so about four runs fit in
  an hour; a fifth is refused until the clock hour turns.
- **The admin journey changes the demo data** (orders, reviews, reports, a
  staff account per run); it relists what it takes down. Re-seed a fresh
  database for a clean demo. So do session ten's journeys: `shop-screens`
  buys two units, writes a review and decides its own problem (staff steps
  need the demo secret), and cleans up after an interrupted run;
  `seller-dashboard` leaves one approved "Demo Journey Phones" shop per run
  with no offer.
- **A buyer's fourth review of one shop in 30 days is held for staff**
  (`reviews.hold_after_same_seller`, D-066, working as designed), so
  `shop-screens.mjs` picks the shop the demo buyer reviewed least and stops
  with that reason once all three are at the limit: about six runs per
  30 days on one database. **The session's demo database has reached that
  limit**; re-seed a fresh one before running `shop-screens.mjs` again.
- **A buyer writes at most ten reviews a day** (`reviews.per_buyer_per_day`,
  working as designed); repeated journey runs reach it with the one demo
  buyer, so `admin-queues.mjs` lifts it through the staff settings route for
  its one review and restores it at once.
- **Open question: one worker pass handled nothing.** In one run of
  `admin-queues.mjs`, `python -m markx.worker --once` ran its eight due jobs
  (all recorded as succeeded at 20:02:42) and exited without handling any of
  the 68 outbox messages that were due, none of them even attempted; the
  database logged no error. The next three passes, by hand and in the
  rerun, handled everything at once, and it did not recur. The cause is not
  known. The journey now keeps the worker's report and retries the pass up
  to three times. If it recurs, read that report: a drain that stopped on an
  exception logs "could not drain the outbox" (`markx/worker/runner.py`).
- **`setup-and-account.mjs` leaves its traces switched off**: per run one
  closed demo shop, an archived product and an archived proposal, an
  inactive "Gadgets" category, an inactive test zone, a demo brand and a
  test attribute. It switches off what an interrupted earlier run left on.
- **A staff authenticator code works once** (replay protection, working as
  designed): two staff sign-ins inside the same 30 seconds refuse the
  second. The journeys retry once with the next code.
- No failing test and no known defect in the tested code. The 801 tests of
  session four were reproduced unchanged at the start of session five before
  any code was written. One defect in session four's code was found and
  fixed (a cancelled shipment without its tracking event).
- **D-050 has two provisional parts**: what a refund does to the stock, and
  that support may decide a refund outcome alone.
- The next-best offer runs the product page's ranking once per line, inside
  the decline or expiry transaction. Fine at today's volume; the expiry job
  handles up to 200 orders a pass, so a very large batch makes that pass
  slower. Move the suggestion to the outbox if it ever shows up in timings.
- A seller who records a direct payment and later has the part refunded
  keeps the payment record as it was; the case decision is the record that
  the money went back. There is no `refunds` row in Release 1.
- A TIN is validated as exactly ten digits. That is the engineer's
  understanding of the Ethiopian format, not something the blueprint states
  (F-03).
- A rejected applicant needs a new invitation to apply again (F-05).
- All Amharic text was drafted by an AI agent. A native speaker must review it
  before launch (blueprint I.3).
- The parent order's derived status names (`awaiting_seller`, `in_progress`,
  `partly_delivered`, `completed`, `cancelled`, or the one status all parts
  share) are the engineer's; the blueprint gives only "partly delivered" as
  an example (D-038).
- **Nothing expires, completes or hides anything unless the worker is
  running.** On a laptop, start it in a second terminal (`docs/SETUP.md`).
- **D-043 is provisional.** An order still `confirmed` or `ready` fourteen
  days after confirmation is cancelled by the worker. The founder may prefer
  a staff warning; the change is one job.
- The parent order reads `completed` as soon as every part is handed over,
  even while one is still inside its problem window (D-038, D-045).
- The device fee cap per order (`cap_santim`) is not applied; no rule
  carries one and `cap_applied` is always false (D-045).
- A wrong handover code commits the attempt count inside the service
  (`db.commit()`), the same pattern as login codes. A caller that wraps
  `confirm_delivery` in a larger transaction would commit that larger
  transaction too; today's callers do not.
- **Product cards carry a picture but no rating yet** (D-074). The rating
  is on the product page (D-072); putting it on the card changes
  `ProductCardOut` on both sides again (D-061). Search does not rank or
  filter by rating yet.
- **Commit `1920e55` says D-073 in its title**; after the merge with the
  parallel back-end session, which had taken D-073 for the performance
  page, its decision is **D-074**. History was not rewritten.
- **The weekly-reports migration (`0012`, the parallel session's) names
  D-069 in its docstring**; the decision is D-073. Left as it is: applied
  migrations are not edited.
- **Alerts reach nobody but the log until the founder creates the Telegram
  group and bot** and sets `MARKX_TELEGRAM_BOT_TOKEN` and
  `MARKX_ALERT_TELEGRAM_CHAT_ID`. A dead worker is only noticed by an
  outside monitor polling `/api/v1/healthz/worker`, which is not set up.
- **Search logs and rate-limit counters are never pruned** (F-08 asks the
  founder for retention periods).
- **Decisions waiting for the founder** (`docs/DECISIONS.md`, F-01 to F-08).
  Each has a recommendation and none is implemented as policy. Only F-01, a
  private store for identity documents (and now pictures), blocks the
  launch.

## Tests executed

**Tenth session, second round** (the remaining screens, D-076 to D-078):

```text
# the recheck, on ffa2720 before any change
$ cd apps/api && uv run pytest ->  944 passed in 763.73s (0:12:43)
$ cd apps/web && npm run lint, typecheck, test, build -> clean; 29 passed; 56 pages
  GitHub Actions run #57 on ffa2720: success

# on the final tree
$ cd apps/web && npm run lint, typecheck -> clean; npm test -> 33 passed (7 files)
$ npm run gen:api -> schema.d.ts unchanged; npm run build -> 66 pages
$ check_openapi_copy --exact openapi.json and the web copy -> both match the API exactly
$ node e2e/setup-and-account.mjs -> 13 steps passed, "console errors: none"
$ node e2e/seller-dashboard.mjs  -> 11 steps passed, "console errors: none"
$ node e2e/buyer-journey.mjs     ->  6 steps passed, "console errors: none"
$ cd apps/api && uv run pytest ->  948 passed in 736.30s (0:12:16)
  ruff check, ruff format --check, mypy (123 files), alembic check -> clean
$ MARKX_DEMO_TOTP_SECRET=… node e2e/staff-journey.mjs ->  6 steps passed, "console errors: none"
$ MARKX_DEMO_TOTP_SECRET=… node e2e/admin-queues.mjs  -> 15 steps passed, "console errors: none"
  (its first run on this tree stopped at step 13: see Known problems, "one
  worker pass handled nothing")
  GitHub Actions run #63 on b12602a: success
# shop-screens.mjs was not rerun after the second round: the demo buyer is at
# the review hold limit for all three demo shops (Known problems); it passed
# 14 steps on 326ae26
```

**Tenth session** (the web app's owner), against PostgreSQL 17 in Docker,
one test run at a time:

```text
# at the start, on 09a55b0 (the run overlapped this session's first edits)
$ cd apps/api && uv run pytest ->  932 passed, 3 failed in 748.29s
  The 3 failures were the API-description checks (tests/unit/test_openapi_copy.py):
  openapi.json was regenerated on disk while the run held the old code in
  memory. They passed on the new code (19 passed with test_reviews and
  test_reports), and CI #43 had passed all 935 on 09a55b0.

# on the merged tree (d015261: this session's API changes plus the parallel
# session's performance routes and migration 0012); no API change after it
$ uv run pytest               ->  944 passed in 785.57s (0:13:05)
$ uv run ruff check .         ->  All checks passed!
$ uv run ruff format --check . ->  181 files already formatted
$ uv run mypy markx           ->  Success: no issues found in 122 source files
$ uv run alembic upgrade head ->  0011 -> 0012; alembic check: No new upgrade operations detected.
$ check_openapi_copy --exact openapi.json and the web copy -> both match the API exactly

# the web app, on the final tree
$ npm run gen:api             ->  schema.d.ts unchanged
$ npm run lint                ->  no problems
$ npm run typecheck           ->  strict tsc clean
$ npm test                    ->  29 passed (5 files: format, labels, messages,
                                  the admin menu per role, the seller menu per role)
$ npm run build               ->  56 pages
$ MARKX_DEMO_TOTP_SECRET=… node e2e/shop-screens.mjs      ->  14 steps passed, "console errors: none"
$ MARKX_DEMO_TOTP_SECRET=… node e2e/seller-dashboard.mjs  ->  11 steps passed, "console errors: none"
$ MARKX_DEMO_TOTP_SECRET=… node e2e/admin-queues.mjs      ->  15 steps passed, "console errors: none"
$ node e2e/buyer-journey.mjs                               ->  6 steps passed, "console errors: none"
  (both after this session's last change, on the same demo database; the two
  Redmi 13C listings earlier runs had left taken down were relisted first by
  their shops)
```

**Ninth session, final run** — on `b2b674e` plus this session's changes, in
CI's order, against PostgreSQL 17 in Docker with nothing else using the test
database:

```text
$ cd apps/api
$ uv sync --locked
$ uv run ruff check .         ->  All checks passed!
$ uv run ruff format --check . ->  176 files already formatted
$ uv run mypy markx           ->  Success: no issues found in 118 source files
$ uv run alembic check        ->  No new upgrade operations detected.
$ uv run pytest               ->  935 passed in 726.22s (0:12:06)
$ uv run python -m scripts.check_openapi_copy --exact openapi.json         -> openapi.json matches the API exactly.
$ uv run python -m scripts.check_openapi_copy ../web/src/lib/api/openapi.json -> ../web/src/lib/api/openapi.json matches the API exactly.

$ cd apps/web
$ npm ci && npm run gen:api   ->  schema.d.ts regenerated from the current API
$ npm run lint                ->  no problems
$ npm run typecheck           ->  strict tsc clean
$ npm test                    ->  11 passed (3 files)
$ npm run build               ->  36 pages; the four new admin routes rendered per request
$ node e2e/admin-queues.mjs   ->  7 steps passed, "console errors: none"
```

**Ninth session, second half** (the rest of the admin screens, D-071; no API
change), on the final tree:

```text
$ cd apps/api && uv run pytest ->  935 passed in 725.61s (0:12:05)
  ruff check, ruff format --check (176 files), mypy (118 files), alembic check,
  check_openapi_copy --exact and the web copy check -> all clean
$ cd apps/web
$ npm run gen:api             ->  schema.d.ts unchanged
$ npm run lint                ->  no problems
$ npm run typecheck           ->  strict tsc clean
$ npm test                    ->  21 passed (4 files: format, labels, messages, the admin menu per role)
$ npm run build               ->  54 pages
$ node e2e/admin-queues.mjs   ->  15 steps passed, "console errors: none"
```

The journey's 360-pixel check caught one real layout fault on the way: a long
setting name made the settings page 19 pixels wider than a phone; the name
now wraps.

At the start of the session, on `88d481b` before any change: 854 API tests
passed (the sixth session's figure, reproduced exactly), and the web app's
`npm ci`, lint, typecheck, 9 unit tests and build all passed. The head moved
to `b2b674e` during the session (the eighth session's back-end work); this
session's work was re-applied on top of it and every check above was run
again there.

```text
$ cd apps/api                  (the back end's latest run: head `891ac71`, on
                               top of session nine's commits up to `b2e11ce`)
$ uv run pytest               ->  943 passed in 705.61s (0:11:45)
$ uv run ruff check .         ->  All checks passed!
$ uv run ruff format --check . ->  181 files already formatted
$ uv run mypy markx           ->  Success: no issues found in 122 source files
$ uv run alembic check        ->  No new upgrade operations detected.
$ uv run python -m scripts.check_openapi_copy --exact openapi.json
                              ->  openapi.json matches the API exactly.
$ uv run python -m scripts.check_openapi_copy ../web/src/lib/api/openapi.json
                              ->  true for everything it has; 4 additions it lacks
                                  (the performance page and weekly reports)
$ infra/backup/drill.sh markx ->  DRILL PASSED (67 tables, 353 rows, demo data; at 0009)
$ docker build apps/api; docker compose -f infra/compose/compose.yaml up
                              ->  (at 0009) migrations, API and worker healthy, a picture
                                  uploaded to the API container was rendered by the
                                  worker container
```

The web app was not touched in the seventh and eighth sessions; the checks
below are the sixth session's (the ninth session's are above), and CI runs
them on every push.

```text
$ cd apps/web
$ npm run lint                ->  no problems
$ npm run typecheck           ->  strict tsc clean
$ npm test                    ->  9 passed
$ npm run build               ->  11 routes, all rendered per request
$ node e2e/buyer-journey.mjs  ->  completed, "console errors: none"
$ node e2e/staff-journey.mjs  ->  refund decided; isolation 404/403; "console errors: none"
```

The eighth session reproduced the baseline before any change: 858 passed,
lint and formatting clean (138 files), strict types over 90 files, no
migration difference, the API image built. One GitHub push run (#27) failed
on a timing-dependent contention test, fixed in `6fe1ce6` (see "Known
problems" in `docs/HANDOFF.md`, Part A.00).

Run on 17 November 2026 against PostgreSQL 17 in Docker, with nothing else
using the test database. At the start of session six, before any change:
847 passed, a clean lint, 134 formatted files, 89 typed source files, no
migration difference. GitHub Actions runs #1 to #4 on this branch passed
(both jobs once the web job existed). mypy runs in strict mode; the
application code contains no `type: ignore`; the suite treats warnings as
errors. **Never run two test sessions at once**: they share `markx_test`
(session five lost one run to that).

Recounted by the tenth session from `pytest --collect-only` (948 tests, 48 files):

| File | Tests |
| --- | --- |
| `tests/unit/test_codes.py` | 7 |
| `tests/unit/test_ethiopic.py` | 35 |
| `tests/unit/test_images.py` | 9 |
| `tests/unit/test_money.py` | 40 |
| `tests/unit/test_openapi_copy.py` | 6 |
| `tests/unit/test_order_rules.py` | 54 |
| `tests/unit/test_permissions.py` | 144 |
| `tests/unit/test_phone.py` | 31 |
| `tests/unit/test_settings_am.py` | 2 |
| `tests/db/test_checkout_contention.py` | 5 |
| `tests/db/test_dispute_contention.py` | 2 |
| `tests/db/test_fulfilment_contention.py` | 4 |
| `tests/db/test_inventory.py` | 14 |
| `tests/db/test_migrations.py` | 8 |
| `tests/db/test_protection.py` | 49 |
| `tests/api/test_addresses.py` | 17 |
| `tests/api/test_admin_takedowns.py` | 8 |
| `tests/api/test_admin_tools.py` | 6 |
| `tests/api/test_auth_otp.py` | 35 |
| `tests/api/test_auth_staff.py` | 14 |
| `tests/api/test_auth_telegram.py` | 7 |
| `tests/api/test_cart.py` | 23 |
| `tests/api/test_catalog.py` | 36 |
| `tests/api/test_checkout.py` | 21 |
| `tests/api/test_csrf.py` | 8 |
| `tests/api/test_delivery.py` | 24 |
| `tests/api/test_disputes.py` | 5 |
| `tests/api/test_exports.py` | 4 |
| `tests/api/test_fulfilment.py` | 14 |
| `tests/api/test_health.py` | 7 |
| `tests/api/test_next_best_offer.py` | 5 |
| `tests/api/test_offers.py` | 42 |
| `tests/api/test_ops.py` | 8 |
| `tests/api/test_performance.py` | 4 |
| `tests/api/test_pictures.py` | 15 |
| `tests/api/test_reports.py` | 4 |
| `tests/api/test_reviews.py` | 9 |
| `tests/api/test_search.py` | 30 |
| `tests/api/test_seller_closing.py` | 2 |
| `tests/api/test_search_evaluation.py` | 6 |
| `tests/api/test_search_index.py` | 7 |
| `tests/api/test_seller_documents.py` | 14 |
| `tests/api/test_seller_isolation.py` | 65 |
| `tests/api/test_seller_onboarding.py` | 38 |
| `tests/api/test_seller_staff_permissions.py` | 23 |
| `tests/api/test_seller_team.py` | 13 |
| `tests/api/test_tracking.py` | 2 |
| `tests/worker/test_worker.py` | 22 |
| **Total** | **948** |

Counted by `uv run pytest --collect-only -q` on the final head.

## Database migrations

| Revision | File | What it does |
| --- | --- | --- |
| `0001` | `20261116_1525_initial_schema.py` | All Release 1 tables with their constraints |
| `0002` | `20261116_1540_history_protection_and_ledger_balance.py` | Append-only history tables; ledger balance trigger |
| `0003` | `20261116_1730_fix_ledger_balance_trigger.py` | Corrects the ledger trigger of `0002` |
| `0004` | `20261116_1818_seller_onboarding.py` | `seller_invitations`; the `draft` review state; `sellers.submitted_at`, `sellers.shop_visited_at`, `seller_documents.review_note`; CHECKs that tie trading and levels to approval |
| `0005` | `20261116_2000_offer_staff_hold.py` | `offers.removed_by_staff_at` and a CHECK that keeps a held offer removed (D-032) |
| `0006` | `20261116_2010_scheduled_jobs.py` | `scheduled_jobs`: one row per scheduled job, the row a worker locks to run it (D-035) |
| `0007` | `20261116_2030_order_life_cycle.py` | The seller order state diagram as a database function and trigger; a seller order starts as `placed`; a status without its event is refused at commit (D-038) |
| `0008` | `20261117_0936_product_pictures_and_problem_photos.py` | `product_images` pipeline columns and CHECKs (status, private source, removal record); `problem_photos`, append-only for every role (D-062) |
| `0009` | `20261117_0958_operations_alerts.py` | `ops_alerts`: one open alert per key (D-064) |
| `0010` | `20261117_1056_reviews_and_rating_summaries.py` | `reviews`: the `held` state, the moderation record, length limits; `rating_summaries` (D-066) |
| `0011` | `20261117_1116_listing_reports.py` | `reports`: a note, the reason list, one open report per person and target, closing CHECKs (D-067) |
| `0012` | `20261117_1158_seller_weekly_reports.py` | `seller_weekly_reports`: one row per store and week, starting on a Monday (D-073) |

The schema has 69 tables (65 before `0008`; then `problem_photos`, `ops_alerts`, `rating_summaries`, `seller_weekly_reports`). P9 and P10 needed no new table and no migration at
all in sessions four and five: the first session's
schema already held carts, orders, seller orders, items, events, reservations,
shipments and payment intents.

## The exact next task

Two sessions may work in parallel: one owns `apps/web`, the other the back
end. Work in this order within each. Finish and push each step first.

**The web app's owner (resuming):**

1. Reproduce the checks and confirm the latest CI run passed.
2. Regenerate the API copy and types whenever the back end has added
   routes: `cd apps/api && uv run python -m scripts.export_openapi
   ../web/src/lib/api/openapi.json`, then `cd ../web && npm run gen:api`
   (D-061). Session ten did this; it was current at its last commit.
3. Every route a person uses has its screen (D-070 to D-078) except
   Telegram sign-in and linking, which wait for the bot (founder). To check
   again, compare `apps/api/openapi.json` with the `/api/v1/...` paths in
   `apps/web/src` (the handoff gives the command). A new screen gets its line
   in the admin or seller `menu.ts` and `menu.test.ts`, its words in both
   message files, and a step in one of the browser journeys.
4. The browser journeys run on GitHub when asked (D-081): push with
   `[journeys]` in the commit message after changing a screen they cover,
   and add a step to one of them for every new screen.
5. With the back end: delivery speed as a search filter and "total cost to
   the door" as a sort (D.8; they need the buyer's zone in search), and the
   Telegram Mini App shell once the bot exists. A rating on the product
   card is left out on purpose: blueprint D.9's card does not list one
   (D-080).

**The back end:**

1. F-08 once the founder answers: a retention job for search logs and
   rate-limit counters.
2. Photos on reviews (C-18), following the problem-photo pipeline (D-062).
3. Ratings in search ranking and filters (D.8), and the seller rating in
   the product page's offer ranking, as one change with the web app
   (D-061).
4. The real adapters, each behind its existing interface, once the founder
   decides where things live (F-01): object storage for pictures and
   documents, SMS, Telegram push.
5. The search golden set, only when the founder sends real queries (D-054).

Rules this session asks the next one to keep (in addition to `AGENTS.md`):

1. **Never run two test sessions at once**; they share `markx_test`.
2. **No business rule in the web app.** It shows what the API returns and
   sends the person's choices; the API checks everything again.
3. **No text in code.** Both message files, same keys; the unit test fails
   otherwise. API error codes are shown through `apiErrorText`.
4. **After an API change**, regenerate `openapi.json` and `schema.d.ts`;
   CI fails if they are stale.
5. **A Core `update()`/`insert()` on a table search watches queues the
   rebuild itself** (D-051).
