# Development status

**Last updated:** 16 November 2026, end of the second engineering session.
**Branch:** `claude/project-scaffold`. The same commits were pushed to
`claude/markx-seller-management-oag1a4`, which the second session's hosting
tool required; the two branches are identical (D-031). `main` holds the
initial commit only and nothing has been merged into it.
**Last code commit:** `0d50751` (offers and inventory). Commits after it
change documentation only, so the test results below describe the code as it
stands; `git log -1` shows the current head.
**Read this after** `AGENTS.md` and `MARKX_MASTER_BLUEPRINT.md`.
`docs/HANDOFF.md` holds the last session's report in plain words, the six
decisions waiting on the founder, and a ready-to-paste brief for the next
engineer.

This file states what exists, what is tested and what is not. Nothing here is
aspirational. If a line says "tested", the test is in the repository and passed
on the date above.

## In one paragraph

The master blueprint is in the repository. The back end now covers the
foundation plus two business phases: the complete Release 1 database schema,
sign-in, the permission model, delivery zones, buyer addresses, the
staff-curated catalogue, **seller onboarding and management (P6)** and
**seller offers and inventory (P7)**. A seller can apply, be verified by
staff, run a store page, list offers with prices and stock, and buyers' pages
can read every seller's offer for a product, ranked. **Nothing can be bought
yet**: there is no search, cart, checkout or order *behaviour*, only their
tables. **There is no web app yet.** Nothing is deployed anywhere.

## Sessions so far

| Session | Commits | What it added |
| --- | --- | --- |
| 1 | `617a276` to `6f36391` | Blueprint, schema, sign-in, permissions, delivery zones, addresses, catalogue, documents. 454 tests |
| 2 | `8a6e583`, `3239e25`, `0d50751` and the documentation commit | Status corrections, sellers (P6), offers and inventory (P7). 647 tests |

## Blueprint phase tracking

Phases are the blueprint's P1 to P16 (section L.1).

| Phase | Name | State |
| --- | --- | --- |
| P1 | Project foundation | **Partly done.** API skeleton, database pipeline and core helpers are done and tested. Web shell, CI pipeline, container setup, typed link between API and web, page-weight check and the three technical reports are **not done** |
| P2 | Database and backend foundation | **Partly done.** Schema, three database roles, error format, request IDs, structured logs are done. Worker process, outbox dispatcher, backups, alerting are **not done** |
| P3 | Authentication and roles | **Mostly done on the API side.** Phone-code sign-in, sessions, staff sign-in, Telegram signature check and the permission tables are done and tested. The real SMS and bot-check adapters, the account page and admin pages are **not done** |
| P4 | Customer storefront | **Not started** |
| P5 | Product catalogue | **Mostly done on the API side.** Categories, typed attributes, brands, products, variants, translations, staff create/approve/merge/archive, aliases, the restricted-goods list and seller product proposals are done and tested. The image pipeline, seed data and the web pages are **not done**; merging a product that has offers is still refused (see D-026) |
| P6 | Seller onboarding and dashboard | **Done on the API side.** Application, private document upload, staff review queue, verification levels with the checks behind the badge, owner and manager members, store page, payout account, dashboard counts. **Not done:** the web screens, share cards and QR code, ownership transfer, a real file-storage adapter. Blueprint completion criteria 1 to 3 are met by automated tests; criterion 4 (three pilot sellers on their own phones) needs the web app and the founder |
| P7 | Seller listings and inventory | **Done on the API side.** Offers with the one-per-seller-variant-condition rule, price history, inventory rows and movements, quick edit, product proposals, the ranked offers list for a product page, the check-in and the stale-offer job as a function. **Not done:** the seller Telegram bot, a worker to *run* the stale job, the web screens. Criteria 1 to 4 are met by automated tests; criterion 5 (pilot sellers list 50 offers) needs the web app |
| P8–P16 | Everything else | **Not started** (tables exist; no behaviour) |

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
  72 hours and the owner is notified. `activate_due_payout_accounts` is the
  job that applies a waiting change.
- **Seller isolation** (P6 completion criterion 2, blueprint C.5). Tested in
  `tests/api/test_seller_isolation.py`: seller A cannot read or change
  seller B through any route; B's document, member or offer id placed under
  A's own seller id is "not found"; a link signed for B does not open for A;
  another seller's id gives the same answer as an id that does not exist. One
  test walks **every** route under `/seller/{seller_id}` taken from the API
  description, so a route added later is checked without anyone remembering.
- **Staff permissions** (C.4): only the super administrator and operations
  review sellers and open documents; tested for all five staff roles, a
  visitor, a customer, a seller, and a staff member signed in by phone code,
  over every `/admin/sellers` route.

### Offers and inventory (blueprint D.7, G.4, G.9, P7)

Code: `markx/offers/`. Routes: `/seller/{seller_id}/offers...`,
`/seller/{seller_id}/dashboard`, `/seller/{seller_id}/product-proposals`,
`/catalog/products/{slug}/offers`, `/catalog/stores/{slug}/offers`,
`/admin/offers/{id}/remove`.

- **Offers.** A trading seller attaches an offer to a variant of an approved
  product: price, condition, warranty, delivery options, stock. One offer
  per seller, variant and condition; **the database rejects a duplicate**
  (tested with plain SQL and with 20 simultaneous identical requests).
  Quick edit, pause, resume, remove; a removed offer listed again reuses its
  row so its history is continuous. Used goods need Level 2.
- **Price history.** Every price change writes a row. Sending the same price
  again counts as confirming it.
- **Inventory.** Stock changes only through `markx/offers/service.py`, and
  every change writes a movement in the same transaction. The seller types
  the counted number; it cannot go below what is held for orders.
- **Stock holds for checkout.** `hold_stock`, `release_stock` and
  `commit_stock` exist and are tested. The hold is the conditional update of
  blueprint G.9. **Tested: 100 simultaneous buyers of the last unit, exactly
  one hold.** Also tested: mixed quantities never oversell; a two-line order
  rolls back completely when one line runs out; buyers racing the seller's
  stock count keep `reserved <= on_hand`; the movement trail replays to the
  exact stock.
- **Ranked offers for a product page.** Only active offers of trading
  sellers at the launch level (`sellers.min_level_to_publish`, default 2).
  Order: in stock; price confirmed recently; delivers to the buyer's zone;
  lowest price plus cheapest delivery fee; higher seller level; most
  recently confirmed. Computed on every read, never stored. The first row is
  marked as the default with its reason.
- **Freshness.** One-tap check-in confirms all live offers.
  `mark_stale_offers` hides an offer whose price was not confirmed for 14
  days; the check-in brings it back. An offer older than 3 days is flagged
  to the seller and sinks in the ranking.
- **Product proposals.** A seller proposes a missing product; it is always
  `pending_review`, whatever the request says, and invisible until staff
  approve it.
- **Listing moderation.** Super administrator, operations and catalogue
  staff can take an offer down with a reason; the seller is notified.
- **One seller cannot edit another's offer** (P7 criterion 3): tested on
  every offer route, with the offer id under both seller ids.

## What exists but is NOT tested

Be careful with these. They were written and never exercised.

- Models for shipments, orders, payments, the ledger's application code,
  reviews, cases, search and analytics: the tables exist and are constrained;
  **no service, route or test uses them**.
- `inventory_reservations`: the table exists. Nothing writes to it yet,
  because a reservation row needs an order item. Checkout (P9) must write
  one row per order line next to each `hold_stock` call.
- `offer_price_tiers`, `seller_metrics_daily`, `product_images`,
  `stores.logo_key`: tables or columns with no behaviour.
- `markx/notifications/service.py` queues outbox rows, and **nothing drains
  the outbox**: there is no worker. Seller and offer notifications are
  written as in-app records and are readable at `/me/notifications`; nothing
  is sent by Telegram or SMS.
- The two scheduled functions `offers.service.mark_stale_offers` and
  `sellers.service.activate_due_payout_accounts` are tested, and **nothing
  calls them on a schedule**: there is no worker.

## What does not exist

- The web app (Next.js): storefront, seller dashboard, admin dashboard.
- Services and routes for search, cart, checkout, orders, shipments,
  payments, reviews, cases and the admin settings pages.
- Ownership transfer between seller members (needs the founder's decision,
  see `docs/DECISIONS.md`, open questions).
- Store logo upload, share cards, QR code (they belong with the web app and
  the public image pipeline).
- The seller Telegram bot (bot commands and the daily freshness prompt).
- A real private-storage adapter. Only the local-disk adapter exists, and it
  refuses to run on a staging or production configuration.
- The background worker (outbox dispatch, expiry jobs, stale offers).
- Seed data.
- Docker Compose files and Dockerfiles; the reverse proxy.
- The CI pipeline (`.github/workflows`).
- Real adapters: SMS provider, bot check, object storage, Telegram bot.
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
  toss. Movements are stamped with `clock_timestamp()` (D-028).

## Known problems

- No failing test and no known defect in the tested code. The existing 454
  tests were reproduced unchanged at the start of session 2 before any code
  was written, and still pass.
- A TIN is validated as exactly ten digits. That is the engineer's
  understanding of the Ethiopian format, not something the blueprint states.
  The founder should confirm it before real sellers apply.
- A rejected applicant needs a new invitation to apply again. That follows
  from "an invitation is used once"; say so if it should be different.
- All Amharic text was drafted by an AI agent. A native speaker must review it
  before launch (blueprint I.3).
- **Six questions are waiting for the founder** (`docs/DECISIONS.md`, F-01 to
  F-06). Each has a recommendation and none is implemented as policy. Only
  **F-01, a private store for identity documents, blocks the launch**: a real
  seller cannot be onboarded until it exists, because the only file-storage
  adapter refuses to run on a real server. F-03 (the ten-digit TIN rule) can
  turn a legitimate pilot seller away. The other four block nothing that the
  next task touches.

## Tests executed

```text
$ cd apps/api
$ uv run pytest               ->  647 passed in 217.31s
$ uv run ruff check .         ->  All checks passed!
$ uv run ruff format --check . ->  101 files already formatted
$ uv run mypy markx           ->  Success: no issues found in 71 source files
$ uv run alembic check        ->  No new upgrade operations detected.
```

Run on 16 November 2026 against PostgreSQL 17.12 in Docker, after rebuilding
the test database from empty. At the start of the session, before any change,
the same commands gave 454 passed, a clean lint, 62 source files without type
issues and no migration difference: the first session's report was accurate.
mypy runs in strict mode and the application code contains no `type: ignore`.
The suite treats warnings as errors. The inventory tests were run three times
in a row after the deadlock fix, 13 of 13 each time.

| File | Tests |
| --- | --- |
| `tests/unit/test_money.py` | 40 |
| `tests/unit/test_phone.py` | 31 |
| `tests/unit/test_ethiopic.py` | 35 |
| `tests/unit/test_codes.py` | 7 |
| `tests/unit/test_permissions.py` | 144 |
| `tests/db/test_migrations.py` | 8 |
| `tests/db/test_protection.py` | 49 |
| `tests/db/test_inventory.py` | 13 |
| `tests/api/test_health.py` | 7 |
| `tests/api/test_auth_otp.py` | 35 |
| `tests/api/test_auth_staff.py` | 14 |
| `tests/api/test_auth_telegram.py` | 7 |
| `tests/api/test_csrf.py` | 8 |
| `tests/api/test_delivery.py` | 24 |
| `tests/api/test_addresses.py` | 17 |
| `tests/api/test_catalog.py` | 36 |
| `tests/api/test_seller_onboarding.py` | 38 |
| `tests/api/test_seller_documents.py` | 14 |
| `tests/api/test_seller_isolation.py` | 45 |
| `tests/api/test_seller_staff_permissions.py` | 23 |
| `tests/api/test_seller_team.py` | 13 |
| `tests/api/test_offers.py` | 39 |

No end-to-end test exists, because no web app exists.

## Database migrations

| Revision | File | What it does |
| --- | --- | --- |
| `0001` | `20261116_1525_initial_schema.py` | All Release 1 tables with their constraints |
| `0002` | `20261116_1540_history_protection_and_ledger_balance.py` | Append-only history tables; ledger balance trigger |
| `0003` | `20261116_1730_fix_ledger_balance_trigger.py` | Corrects the ledger trigger of `0002` |
| `0004` | `20261116_1818_seller_onboarding.py` | `seller_invitations`; the `draft` review state; `sellers.submitted_at`, `sellers.shop_visited_at`, `seller_documents.review_note`; CHECKs that tie trading and levels to approval |

The schema has 64 tables. P7 needed no migration: the first session's schema
already held offers, price history, inventory and movements.

## The exact next task

Work in this order. Finish and push each step before starting the next.

1. **A background worker** (blueprint F.8, part of P2), small and first,
   because three things already wait for it: `offers.service.mark_stale_offers`,
   `sellers.service.activate_due_payout_accounts`, and the outbox. Build one
   process that runs scheduled functions and drains `outbox`, with a test that
   a job which raises does not stop the others. Then checkout's expiry jobs
   have a home.
2. **Cart and checkout (P9) and multi-seller orders (P10).** This is the next
   business milestone. Read blueprint G.5, G.6, G.7 and G.9 first.
   - `place_order` in one transaction: read every offer again with its
     seller, recompute prices and delivery fees on the server, call
     `offers.service.hold_stock` for each line **in ascending offer id
     order**, write an `inventory_reservations` row per line, write the
     parent order, one seller order per seller, the items with their copied
     name and price, a shipment per seller order and status events. If any
     hold returns `False`, roll everything back and name the item.
   - The idempotency key is unique per buyer (D-010).
   - `seller_respond`: confirm, or decline and `release_stock`.
   - The expiry job releases holds whose deadline passed.
   - Mandatory test (blueprint P9): 100 buyers, one unit, **exactly one
     order**. The hold itself is already proven; prove the whole order.
   - Lock offer and seller rows with `with_for_update(key_share=True)` only
     (D-027), and add a contention test for each two-lock operation.
   - Add every new `/seller/{seller_id}/...` route under the existing
     `require_seller` dependency; the isolation sweep then covers it.
3. **Search (P8)** can overlap: `search_documents` should be rebuilt when an
   offer's price, stock or status changes; queue that through the outbox.
4. **The web app (P4)**, starting with the shell at `/am` and `/en`, then the
   seller application and dashboard screens that P6 and P7 are waiting for.
5. **CI** (`.github/workflows`): run the five commands above on every push.
   It needs a PostgreSQL 17 service container and nothing paid.

Keep `ruff`, `mypy`, `alembic check` and `pytest` green at every commit.

`docs/HANDOFF.md`, Part B, holds the same assignment written as a brief that
can be handed straight to the next engineer, with the commands, the files to
read and the traps found so far.

Three rules the second session asks the next one to keep, because each was
paid for with a failure:

1. **Reproduce the checks before changing anything** and report the real
   numbers. The first session's figures were accurate; that was worth
   knowing, and it took four minutes.
2. **Write a contention test for every operation that takes two locks.** One
   found a deadlock that no single-request test could (D-027).
3. **Do not replace working code to change its shape.** The architecture is
   the blueprint's: models, schemas, service, selectors, router, deps. If a
   departure is genuinely better, record it in `docs/DECISIONS.md` with its
   reason, then make it.
