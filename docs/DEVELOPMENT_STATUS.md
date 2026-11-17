# Development status

**Last updated:** 17 November 2026, end of the fifth engineering session.
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
report and a synonym tool for staff. **Not built:** reviews, the bot, the web
app, CI. Nothing is deployed anywhere.

## Sessions so far

| Session | Commits | What it added |
| --- | --- | --- |
| 1 | `617a276` to `6f36391` | Blueprint, schema, sign-in, permissions, delivery zones, addresses, catalogue, documents. 454 tests |
| 2 | `8a6e583` to `8df958b` | Status corrections, sellers (P6), offers and inventory (P7). 647 tests |
| 3 | `399507e`, `bd835ef`, `7079cb5`, `eb52d2f` | Review fixes (a moderation bypass, lock ordering), the worker, cart and checkout (P9), multi-seller orders (P10, first half). 779 tests |
| 4 | `7c492c6`, `6582017`, `10573b4` | The second half of P10: ready, dispatch, the handover code, delivered, completed with `commit_stock` and the fee charge posted to the ledger, failed deliveries and returns, the direct payment record, the overdue-hold job, the staff orders desk's first three routes, the tracking page by secure link. 801 tests |
| 5 | see `docs/HANDOFF.md` | Review fix (a cancelled shipment had no tracking event), the next-best offer (C-26), problems on a delivered order with staff decisions (`disputed`, `refunded`), search (P8 on the API side). 847 tests |

## Blueprint phase tracking

Phases are the blueprint's P1 to P16 (section L.1).

| Phase | Name | State |
| --- | --- | --- |
| P1 | Project foundation | **Partly done.** API skeleton, database pipeline and core helpers are done and tested. Web shell, CI pipeline, container setup, typed link between API and web, page-weight check and the three technical reports are **not done** |
| P2 | Database and backend foundation | **Mostly done.** Schema, three database roles, error format, request IDs, structured logs, **the worker process with the scheduler and the outbox dispatcher** are done and tested. Backups, alerting to the founder's Telegram and error tracking are **not done**; a job that keeps failing is logged at CRITICAL and nothing reads that log yet |
| P3 | Authentication and roles | **Mostly done on the API side.** Phone-code sign-in, sessions, staff sign-in, Telegram signature check and the permission tables are done and tested. The real SMS and bot-check adapters, the account page and admin pages are **not done** |
| P4 | Customer storefront | **Not started** |
| P5 | Product catalogue | **Mostly done on the API side.** Categories, typed attributes, brands, products, variants, translations, staff create/approve/merge/archive, aliases, the restricted-goods list and seller product proposals are done and tested. The image pipeline, seed data and the web pages are **not done**; merging a product that has offers is still refused (see D-026) |
| P6 | Seller onboarding and dashboard | **Done on the API side.** Application, private document upload, staff review queue, verification levels with the checks behind the badge, owner and manager members, store page, payout account, dashboard counts. **Not done:** the web screens, share cards and QR code, ownership transfer, a real file-storage adapter |
| P7 | Seller listings and inventory | **Done on the API side.** Offers, price history, inventory and movements, quick edit, product proposals, the ranked offers list, the check-in, the stale-offer job **now run by the worker**, and a staff takedown that holds (D-032). **Not done:** the seller Telegram bot, the web screens |
| P8 | Search and product discovery | **Mostly done on the API side.** Search documents kept fresh through the outbox with an hourly rebuild (D-051); normalisation, letter merging and skeleton keys; prefix, sound and trigram matching; filters and sorting; suggestions and "did you mean"; the product-request form; the query log, the zero-result report and the synonym tool (D-052). **Not done:** the two completion criteria (a golden set of 100 real queries, and timings at real size), "total cost to the door" as a sort, rating and delivery-speed filters, edge caching and pages readable by search engines (they need the web app) |
| P9 | Cart and checkout | **Done on the API side.** Server-side cart for visitors and signed-in buyers, delivery choice and fees per store, the priced review step, `place_order` with server re-pricing, stock reservation and idempotency. Criteria 1 to 5 are met by automated tests. **Not done:** the web screens, the legal disclosure wording (a founder input), and guest checkout as such: a visitor's cart survives signing in, but the order is placed by a signed-in account (see D-036) |
| P10 | Multi-seller orders | **Done on the API side, except the pieces listed.** Parent and seller orders, the state machine enforced by the database, status events, seller confirm and decline, the response deadline and the expiry job, buyer cancellation, notifications, shipments and payment intents; `ready`, `out_for_delivery` (seller or staff), `delivered` with the derived handover code and its five-attempt lockout, `completed` by the buyer or the worker with `commit_stock` and the fee charge, `delivery_failed`, retry, `returned`, the direct payment record, the overdue-hold cancellation. The tracking page by secure link without sign-in. The next-best offer after a decline or an expiry (D-049). Problems on a delivered order: `delivered -> disputed` by the buyer in the window, `disputed -> completed | refunded` by staff, Release 1 form with no money moved (D-050). Criteria 1, 2 and 4 are met by automated tests (`tests/api/test_fulfilment.py`, `tests/api/test_tracking.py`, `tests/api/test_disputes.py`). **Not done:** reviews, photos on a problem report, the bot, the web screens. Criteria 3 and 5 need the bot and real buyers |
| P11–P16 | Everything else | **Not started** (tables exist; no behaviour) |

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

## What exists but is NOT tested

Be careful with these. They were written and never exercised.

- Models for refunds, payouts, reviews, reports and analytics: the tables
  exist and are constrained; **no service, route or test uses them**.
  `product_requests` are written and never read by a route yet.
- `fee_charges.reversal_ledger_transaction_id` and `reversed_at`: unused.
  Release 1 never charges a fee on a refunded part, so nothing is reversed
  (D-050).
- `refunds`, `payouts`, provider webhooks: tables only (Release 2).
- `offer_price_tiers`, `seller_metrics_daily`, `product_images`,
  `stores.logo_key`: tables or columns with no behaviour.
- `commission_rules`: read by checkout, never written by any route.

## What does not exist

- The web app (Next.js): storefront, cart and checkout screens, seller
  dashboard, admin dashboard.
- Reviews, listing reports (C-30), photos on a problem report,
  the staff dispatch board and the rest of P11, payments beyond the direct
  payment record (Release 2: Protected prepay, refunds through a provider,
  payouts).
- Ownership transfer between seller members (needs the founder's decision,
  F-02).
- Store logo upload, share cards, QR code.
- The seller Telegram bot and the real push adapter: the worker delivers
  pushes to a fake.
- A real private-storage adapter (F-01), a real SMS adapter, a bot-check
  adapter.
- Seed data, Docker Compose files and Dockerfiles, the reverse proxy, the CI
  pipeline, backups, alerting, error tracking.
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

## Known problems

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
- **Decisions waiting for the founder** (`docs/DECISIONS.md`, F-01 to F-07).
  Each has a recommendation and none is implemented as policy. Only F-01, a
  private store for identity documents, blocks the launch.

## Tests executed

```text
$ cd apps/api
$ uv run pytest               ->  847 passed in 393.88s (0:06:33)
$ uv run ruff check .         ->  All checks passed!
$ uv run ruff format --check . ->  134 files already formatted
$ uv run mypy markx           ->  Success: no issues found in 89 source files
$ uv run alembic check        ->  No new upgrade operations detected.
```

Run on 17 November 2026 against PostgreSQL 17 in Docker, after rebuilding
the test database from empty. At the start of session five, before any
change, the same commands gave 801 passed in 236.20s, a clean lint, 125
formatted files, 85 typed source files and no migration difference: the
fourth session's report was accurate. mypy runs in strict mode and the
application code contains no `type: ignore`. The suite treats warnings as
errors. Whole-suite runs in session five: 801 at the start; 814, then 815
after the order work (commit `497fcf5`); one run that is **not valid**
(791 passed, 30 errors in test set-up) because a second test run was
started against the same test database while it ran: the two truncated
each other's tables; then 847 with nothing else running, the figure above.
**Never run two test sessions at once**: they share `markx_test`.

| File | Tests |
| --- | --- |
| `tests/unit/test_money.py` | 40 |
| `tests/unit/test_phone.py` | 31 |
| `tests/unit/test_ethiopic.py` | 35 |
| `tests/unit/test_codes.py` | 7 |
| `tests/unit/test_permissions.py` | 144 |
| `tests/unit/test_order_rules.py` | 54 |
| `tests/db/test_migrations.py` | 8 |
| `tests/db/test_protection.py` | 49 |
| `tests/db/test_inventory.py` | 14 |
| `tests/db/test_checkout_contention.py` | 5 |
| `tests/db/test_fulfilment_contention.py` | 4 |
| `tests/db/test_dispute_contention.py` | 2 |
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
| `tests/api/test_seller_isolation.py` | 56 |
| `tests/api/test_seller_staff_permissions.py` | 23 |
| `tests/api/test_seller_team.py` | 13 |
| `tests/api/test_offers.py` | 42 |
| `tests/api/test_cart.py` | 22 |
| `tests/api/test_checkout.py` | 21 |
| `tests/api/test_fulfilment.py` | 11 |
| `tests/api/test_tracking.py` | 2 |
| `tests/api/test_next_best_offer.py` | 5 |
| `tests/api/test_disputes.py` | 5 |
| `tests/api/test_search_index.py` | 6 |
| `tests/api/test_search.py` | 26 |
| `tests/worker/test_worker.py` | 22 |

No end-to-end test exists, because no web app exists.

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

The schema has 65 tables. P9 and P10 needed no new table and no migration at
all in sessions four and five: the first session's
schema already held carts, orders, seller orders, items, events, reservations,
shipments and payment intents.

## The exact next task

Work in this order. Finish and push each step before starting the next.

1. **Reproduce the checks** (the five commands above) and report the real
   numbers. Then review what the fifth session built: `next_best_offers`
   and `_suggest_next_best`, `open_dispute` to `resolve_dispute` and
   `_commit_held_stock` in `markx/orders/service.py`; `next_best_offer` in
   `markx/offers/selectors.py`; `_problems`, `buyer_alternatives` and
   `staff_open_problems` in `markx/orders/selectors.py`; with
   `tests/api/test_next_best_offer.py`, `tests/api/test_disputes.py` and
   `tests/db/test_dispute_contention.py`. Look for: a case's text reaching
   the tracking link or another seller; a refunded part that is ever charged
   a fee or completes later; stock released or committed twice; a dispute
   operation that locks out of the written order.
2. **Review search** (`markx/search/`, D-051, D-052): a change path that
   alters a document without queueing a rebuild (look for Core `update()` /
   `insert()` on the watched tables), a query that matches too much or too
   little, a filter that leaks a product a buyer may not see (a draft, an
   archived product, a suspended seller's offer). Then build the golden set
   the P8 criteria need: the founder supplies real queries; write them as a
   test with the expected product, and tune `LETTER_MATCH` against it.
3. **CI** (`.github/workflows`): the five commands on every push with a
   PostgreSQL 17 service container. Nothing paid.
4. **The web app (P4)**, starting with the shell at `/am` and `/en`, then the
   storefront, cart and checkout screens, the seller's order screens and the
   "report a problem" screen.
5. **The rest of P11**: the dispatch board, commission rules managed by
   finance (`change_fees`), the problem-case log with evidence.

Keep `ruff`, `mypy`, `alembic check` and `pytest` green at every commit.

`docs/HANDOFF.md`, Part B, holds the same assignment written as a brief that
can be handed straight to the next engineer.

Six rules the fifth session asks the next one to keep:

1. **Reproduce the checks before changing anything** and report the real
   numbers.
2. **A seller order changes status only through `_move`**, a shipment only
   through `_track` (cancellations included, since session five), both in
   `markx/orders/service.py`. Stock moves only through
   `markx/offers/service.py`; `commit_stock` only from `_commit_held_stock`.
3. **Take locks in the written order** (`cart -> sellers -> offers -> seller
   orders -> shipment -> stock`, each in ascending id), with
   `with_for_update(key_share=True)` for sellers, offers, seller orders,
   shipments and payment intents, and write a contention test for every
   operation that takes two locks. A dispute case is guarded by its seller
   order's lock.
4. **The handover code is derived, never stored, never logged**, and shown
   only on the signed-in buyer's page while a handover is awaited (D-044).
5. **MarkX moves no money in Release 1.** A refund is the record that the
   seller paid the buyer back; no fee is charged on a refunded part.
6. **Do not replace working code to change its shape.** If a departure is
   genuinely better, record it in `docs/DECISIONS.md` with its reason first.
