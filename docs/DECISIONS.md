# Engineering decisions

One entry per decision another engineer would need to know. Each entry says
whether it **follows**, **fills a gap in** or **departs from** the master
blueprint (`MARKX_MASTER_BLUEPRINT.md`). A departure always states its reason.

The blueprint asks for one file per decision under `docs/decisions/` (section
F.16). The founder's brief of 16 November 2026 asks for this single file, so
decisions live here. Split it if it grows past comfortable reading.

Status words: **Accepted** (decided and in the code; another engineer may rely
on it) and **Open** (not decided; the code either avoids the question or holds
a placeholder that is marked as such). Nothing in this file is a business
policy the founder approved unless the founder's approval is named in the
entry. Entries numbered `D-` are engineering decisions; the founder's own
decisions are at the end of this file under "Decisions that need the founder".

---

## D-001 Stack and exact versions

**Follows** blueprint N.5–N.7 (Confirmed) and P.1 item 9. **Accepted.**

Next.js, TypeScript and Tailwind CSS in front; Python with FastAPI,
SQLAlchemy and Alembic behind; PostgreSQL. Only the back end exists so far.
Versions installed and locked in `apps/api/uv.lock` on 16 November 2026:

| Part | Version |
| --- | --- |
| Python | 3.13 |
| FastAPI | 0.163.1 |
| SQLAlchemy | 2.1.8 |
| Alembic | 1.20.1 |
| Pydantic | 2.14.3 |
| psycopg | 3.3.9 |
| PostgreSQL | 17.12 |
| pytest / Ruff / mypy | 9.2.0 / 0.17.5 / 2.4.1 |

Dependencies are locked with hashes by `uv` (blueprint Q.6).

Notes for agents whose training predates these versions, all found by running
the code:

- FastAPI: a database dependency must be declared with
  `Depends(get_db, scope="function")` so it commits *before* the response is
  sent. The default scope commits after, which lets a client read stale data
  straight after a write.
- FastAPI: `include_router` no longer copies routes into `app.routes`; list
  routes through `app.openapi()["paths"]`.
- Starlette's test client now wants the `httpx2` package, not `httpx`.
- SQLAlchemy 2.1: `Row.t` is deprecated; unpack a row directly.
- Alembic: set `path_separator = os` in `alembic.ini`.

## D-002 The scaffold written before the blueprint was removed

**Follows** the blueprint. **Accepted.**

An earlier scaffold (commit `a1e1ce6`) put the data layer in Prisma and
TypeScript and business rules in a shared TypeScript package. The blueprint
confirms a Python back end and keeps every business rule in the API, so the
scaffold was removed in commit `66f14b8`, which lists what went and why.
Nothing was reused as code. Its MIT `LICENSE` file was also removed: the
repository is private and licensing is the founder's decision.

Version findings carried forward from that scaffold, for when the web app is
built: TypeScript 7 was outside the range `typescript-eslint` 8.72 supports
(use TypeScript 6.0.x until that changes); Next.js 16.4.6 with React 19.3.1
and Tailwind CSS 4.3.5 built and ran; Tailwind 4 is configured through
`@tailwindcss/postcss` and `@import "tailwindcss"`, with no config file.
Re-check all of these before relying on them.

## D-003 Pace of building

**Follows** blueprint Q.1 rule 2 after a short departure. **Accepted.**

The blueprint says to build only the current phase and to confirm six points
with the founder before writing code (Q.3). On 16 November 2026 the founder
instructed the agent to start building without waiting. Later the same day the
founder added: build in logical milestones, not one enormous unverified
implementation, and commit and push each completed piece. That is the rule
now, and it matches the blueprint: small, tested, pushed milestones.

The six Q.3 confirmations were not asked. Treat blueprint section O as still
open unless a question is marked answered.

## D-004 Synchronous database access

**Fills a gap.** **Accepted.**

The blueprint does not say whether the API uses async database access. It
uses synchronous SQLAlchemy sessions with psycopg 3; FastAPI runs each request
in a worker thread. Reason: one request is one transaction with ordinary
`try/commit/rollback` flow, which a beginner can read and which makes the
blueprint's "one transaction per critical operation" rule easy to see in the
code. Revisit only if measured load shows thread starvation.

## D-005 Keys are UUID version 7, made in the application

**Follows** blueprint G.1 ("time-ordered where the database supports it").
**Accepted.**

PostgreSQL gains `uuidv7()` only in version 18. `markx/core/ids.py` generates
version 7 UUIDs, so the schema works on PostgreSQL 16 and later.

## D-006 The database locale is the built-in C.UTF-8

**Answers** blueprint question O.34. **Accepted.**

Trigram matching decides what a "letter" is from the database's character
rules. The bootstrap script creates the database with PostgreSQL 17's
built-in `C.UTF-8` locale, which behaves the same on every host. Under it,
`show_trgm('ስልክ')` returns four trigrams and `word_similarity` finds an
Amharic word inside a phrase; a test asserts both. Do not create the database
with the plain `C` locale: trigram matching would then ignore Ethiopic text.

## D-007 Statuses are text with CHECK constraints, not enum types

**Fills a gap.** **Accepted.**

Blueprint G.8 rule 7 requires that a status column accepts only its allowed
values. Each one is a `text` column with a named CHECK. Adding a value later is
a one-line migration; a PostgreSQL enum type is harder to change.

## D-008 History is protected twice

**Follows** blueprint G.8 rules 5 and 6. **Accepted.**

The audit log, status events, price history, stock movements, tracking events
and the ledger only grow. The application's database role has no UPDATE or
DELETE privilege on them, **and** a trigger refuses both for every role,
including the schema owner. Either barrier alone would satisfy the blueprint;
both together mean a mistake in a grant or a compromised migration role still
cannot rewrite history.

## D-009 The ledger balance is checked by the database at commit

**Follows** blueprint G.8 rule 5. **Accepted.**

A deferred constraint trigger checks, at commit, that every ledger transaction
touched has at least two entries and equal debits and credits. The first
version (migration `0002`) was wrong and made every ledger insert fail;
migration `0003` corrects it. The lesson is recorded in
`docs/DEVELOPMENT_STATUS.md`: untested code was wrong.

## D-010 An order's idempotency key is unique per buyer, not globally

**Departs** from blueprint G.2, which lists a "unique idempotency key" on
orders. **Accepted.**

The same key sent again must return the same order. If the key were unique
across all buyers, a buyer who sent another buyer's key would be handed that
other buyer's order. The unique constraint is on `(buyer_user_id,
idempotency_key)`.

## D-011 Login codes and handover codes are stored as keyed hashes

**Follows** blueprint D.2 and G.2, with a stronger method. **Accepted.**

A six-digit code has only a million values, so a plain hash can be reversed by
trying them all. Codes are hashed with HMAC-SHA256 under the server's secret
key. A copy of the database alone cannot recover a code.

Login codes go straight to the SMS adapter and are never written to the outbox
or a log.

Handover codes will be *derived* from the server secret and the shipment
(`derive_numeric_code` in `markx/core/security.py`), so the buyer's page can
show the code again at any time while the database holds nothing that reveals
it. Not built yet.

## D-012 Sessions, cookies and the anti-forgery guard

**Follows** blueprint F.4 and H.2. **Accepted.**

- A session is a random 256-bit token. Only its SHA-256 is stored.
- Browsers hold it in an `HttpOnly`, `SameSite=Lax` cookie (and `Secure` on
  real servers). The Telegram Mini App sends it in an `Authorization` header,
  because cookies are unreliable in embedded web views. A token issued for one
  transport is refused on the other.
- Every request that changes data must carry the `X-MarkX-Client` header. A
  cross-site page cannot add a custom header without a CORS preflight, and the
  API answers none. `Origin` and `Sec-Fetch-Site` are checked as well.
- A cookie session must also send `X-CSRF-Token`, an HMAC of its own session
  token. One session's token does not work for another.
- Staff sessions idle out after 30 minutes and end after 12 hours.

## D-013 Staff sign-in

**Follows** blueprint H.2, which proposes the method. **Accepted.**

Argon2id for passwords, at least 12 characters. The authenticator secret is
encrypted with a key held outside the database. The last accepted time step is
stored, so one authenticator code cannot be used twice. Five failures lock the
account for 15 minutes. Every failure returns the same error, whether the phone
number is unknown, the password is wrong or the code is wrong.

**Not built:** one-time recovery codes, and a way for a super administrator to
reset another staff member's password.

## D-014 Rate limits fail safe

**Fills a gap.** **Accepted.**

Limits are fixed-window counters in PostgreSQL (blueprint F.3). Each hit is
counted on its own connection, so the count survives when the request is
rolled back. A caller whose network address cannot be determined shares one
bucket instead of skipping the limit. The address is validated before use,
because it is stored in `inet` columns.

## D-015 Skeleton keys drop glides and resolve the Latin letter c

**Departs** slightly from blueprint F.7 step 3, to make it work. **Accepted;
needs the native-speaker review the blueprint already asks for.**

The blueprint says: romanise, drop vowels and doubled letters, unify spellings
such as `ch` and `c`. Tests on real product words showed two more rules are
needed for Amharic and Latin spellings to meet:

- The glides ወ and የ (and Latin `w`, `y`) are dropped. In loanwords they spell
  a vowel sound: ራውተር is "router", ኖኪያ is "nokia".
- A plain Latin `c` is read as `s` before `e`, `i`, `y` and as `k` otherwise,
  so "tecno" meets ቴክኖ.

Known limit, with a test that documents it: English spelling that differs from
sound is not handled. "charger" (soft g) does not meet ቻርጀር. Product aliases
cover such words.

The blueprint's optional rule that merges the ኸ series into ሀ stays **off**
until a native speaker confirms it (`MERGE_KH_SERIES` in
`markx/core/ethiopic.py`).

## D-016 No real outside-service adapter exists yet

**Follows** blueprint F.0 principle 4. **Open.**

SMS and the bot check sit behind adapters, and only the fake adapters exist.
On a staging or production configuration the SMS factory raises an error
rather than silently using the fake. The configuration also refuses to start
on a real server with development secrets, without `Secure` cookies or
without an `https://` origin.

Blocked on the founder: a local SMS provider (blueprint question O.23).

## D-017 An application is a draft until it is submitted

**Fills a gap** in blueprint D.3 and G.2. **Accepted.**

The blueprint lists the seller statuses `applied`, `active`, `suspended` and
`closed`, and says the application takes about 15 minutes over several steps.
It does not say what staff see while the applicant is still uploading.
`sellers.review_state` gains the value `draft`: the seller, its owner and its
store are created at the first step, staff see nothing until the applicant
submits, and submitting is refused until the required documents and a payout
account are present. A rejected application sets `status` to `closed`, which
frees the TIN for a corrected application.

The allowed moves are written at the top of `markx/sellers/service.py`.

## D-018 Staff approval is a fact in the database

**Follows** blueprint C.5 ("levels are set by staff") with a stronger method.
**Accepted.**

Two CHECK constraints (migration `0004`): a seller is `active` or `suspended`
only if its application is `approved`, and holds a verification level above 0
only if it is `approved`. A bug in a future route cannot activate or verify a
seller that staff did not approve. A level is also granted only when the
accepted, unexpired documents behind it exist; the service checks that, and
returns the list of missing checks.

## D-019 Invitations are rows keyed on a phone number

**Fills a gap** in blueprint D.3 ("invite-only at launch"). **Accepted.**

Staff invite a phone number. The account that owns the number may then open
one application; the invitation is marked used and cannot be used again. It
expires after `sellers.invitation_valid_days` (14). Turning the setting
`sellers.invite_only` off opens applications to everyone signed in.

## D-020 Private documents: photos only, re-encoded, opened by personal links

**Follows** blueprint D.3 and F.6, with two choices of method. **Accepted**,
with one part **Open**.

- **Photos only** (JPEG, PNG, WebP), as F.6 says. The uploaded file's name
  and declared type are ignored. The picture is decoded and written out
  again at upload, which removes location data and anything hidden in the
  file. The blueprint gives this job to the worker. A document must not sit
  unchecked in storage even for a minute, so it happens in the upload
  request; the worker (built in session three) does not touch documents.
- **Links** carry an expiry time and a signature over the document, the
  viewer and the expiry. A link works for five minutes. It is not enough to
  hold the link: the same person must be signed in, and must still be
  allowed to see the document when it is opened. A leaked link is useless to
  anyone else. Issuing a link and every view are audit-logged.
- **Storage** sits behind `PrivateStorage` in `markx/core/storage.py`.
  **Open:** only the local-disk adapter exists, and it refuses to run on a
  staging or production configuration. An S3-compatible adapter is needed
  before real sellers apply; it needs the founder's decision on where
  personal data may live (blueprint O, question 1).

## D-021 Staff powers and seller powers never mix

**Follows** blueprint C.1 and C.5. **Accepted.**

A staff session (password and authenticator) is refused on every `/seller`
route; a staff member who also sells signs in to the store with a phone code,
like anyone. A staff member who belongs to a seller cannot take any staff
decision about that seller ("nobody can assign a level to themselves").

## D-022 What staff verified is frozen; ownership transfer is not built

**Fills a gap.** **Accepted**, with one part **Open**.

After an application is submitted, the owner can no longer change the legal
name, trade name, TIN, licence number or shop address: staff verified those
exact values. Only the contact phone can change. While staff ask for more
documents, the details can be corrected again. The store's link cannot change
once the store is approved, because buyers and search engines keep it.

**Open:** blueprint C.3 lets the owner transfer ownership. It is not built.
Level 1 verifies the *owner's* identity, so a transfer must decide what
happens to the level. See the open questions.

## D-023 Payout account: active at once the first time, 72 hours after that

**Follows** blueprint S-13 ("a cooling-off period on any change").
**Accepted.**

The first account is active immediately, and an applicant may correct it
freely until approval, because nothing can be paid out before then. After
approval a new account waits `sellers.payout_cooling_off_hours` (72) and the
owner is notified at once. The number is encrypted with the key held outside
the database; only the last four digits are ever returned.

Staff confirm at approval that the account is in the seller's own name
(blueprint D.3); the approval request must say so.

## D-024 A team member is added by phone number, with no acceptance step

**Fills a gap** in blueprint S-09. **Accepted.**

The owner or a manager types a phone number. If no account exists for it,
one is created; the person proves the number is theirs at their first
sign-in, as every user does. Membership gives powers and takes nothing from
the person, and they can leave at any time, so there is no accept screen.
Release 1 gives only the manager role, and two seats in total
(`sellers.starter_seats`), as blueprint D.4 says.

## D-025 Who may list and what buyers see

**Follows** blueprint D.1 and D.3, with one widening. **Accepted.**

- Only an `active` seller creates or edits offers. A suspended seller can
  still see its listings and take one down.
- A Level 1 seller can prepare offers, but buyers see only offers of sellers
  at `sellers.min_level_to_publish` (2), as the launch policy says.
- **Widening:** the blueprint says used *phones* need Level 2. The rule is
  applied to every `used` offer, in every category. It is simpler to explain
  and stricter, never looser. Say so if used goods in some category should
  be open to Level 1.

## D-026 A product that has offers still cannot be merged

**Departs** temporarily from blueprint D.5. **Open.**

Merging a duplicate product must move its offers to the survivor. That means
matching each variant of the duplicate to a variant of the survivor, and a
seller who listed both would then hold two offers for one variant, which the
database forbids. The rule for that collision is a product decision. Until it
is made, the merge is refused with a clear message. Merging a product with no
offers works.

## D-027 Lock offer and seller rows with FOR NO KEY UPDATE

**Fills a gap.** **Accepted.** Found by a test.

A row inserted with a foreign key takes a key-share lock on the row it points
to. A plain `SELECT ... FOR UPDATE` blocks that. A seller editing an offer
(offer row, then stock row) and a buyer holding stock (stock row, then the
movement's foreign key to the offer row) took the two locks in opposite order
and deadlocked. `with_for_update(key_share=True)` produces `FOR NO KEY
UPDATE`, which still makes two editors wait for each other and does not block
foreign keys. Use it for every lock on `offers` and `sellers`.
`tests/db/test_inventory.py` reproduces the race with 60 threads.

Checkout must also take its stock holds in ascending offer id order, so two
orders can never wait on each other.

## D-028 Stock movements carry the wall-clock time they were written

**Fills a gap.** **Accepted.** Found by a test.

`now()` in PostgreSQL is the time the transaction began, so several movements
written by one transaction would share a timestamp and have no order.
Movements are stamped with `clock_timestamp()` and flushed one at a time.
Each is written while its stock row is locked, so the timestamps order an
offer's movements exactly.

## D-029 How offers are ranked, and what the public sees of stock

**Follows** blueprint D.7 and G.4, with two choices. **Accepted.**

The order, computed on every read: in stock first; a price confirmed within
`offers.sink_after_days` (3) before one that has sunk; when the buyer's zone
is known, offers that deliver there before collection-only ones; lowest price
plus the cheapest delivery fee to the zone; higher seller level; most
recently confirmed price.

- **Seller performance** is part of the blueprint's order. No order has ever
  been placed, so there is nothing to measure. The seller's verification
  level stands in for it until `seller_metrics_daily` is filled (P10).
- **Stock shown to buyers is capped at 5.** The blueprint's offer row shows
  "stock". An exact count lets a competitor read a rival's inventory by
  refreshing the page. Buyers see "in stock" and a number up to five.

## D-030 Stock holds are built; reservation rows wait for checkout

**Follows** blueprint G.9. **Accepted.**

`hold_stock`, `release_stock` and `commit_stock` in
`markx/offers/service.py` are the only code that moves reserved stock, and
each writes its movement. The hold is the blueprint's conditional update. The
`inventory_reservations` table needs an order item for every row, so
checkout writes those rows, one beside each hold (done in session three,
D-037). `commit_stock` is still called by nothing: completion is not built.

## D-031 Branches

**Fills a gap.** **Accepted.**

The working branch is `claude/project-scaffold`. The second session's hosting
tool also required its own branch, `claude/markx-seller-management-oag1a4`.
Every commit was pushed to both and they are identical. Continue on
`claude/project-scaffold`.

## D-032 A staff takedown holds until staff lift it

**Fills a gap** in blueprint AD-03. **Accepted.** Found in the session-three
review, with a test that failed first.

`create_offer` brings a removed offer back when the seller lists the same
variant and condition again. It did so for an offer that *staff* had taken
down, so a seller could undo a takedown for a counterfeit or stolen item with
one request. `offers.removed_by_staff_at` (migration `0005`) now records the
takedown. While it is set the seller's relist is refused with
`offer_removed_by_staff`, and a CHECK keeps a held offer `removed` whatever
the code does. Staff can also hold an offer the seller already removed, so
removing it first is no way round. `POST /admin/offers/{id}/restore` lifts the
hold; it publishes nothing, the seller lists again.

The founder may want a different rule for *who* lifts a hold or whether it
ever expires. Today: the same staff roles that may take a listing down.

## D-033 Statements that change many offers lock them in id order

**Fills a gap.** **Accepted.** Hardening; the deadlock was not reproduced.

The check-in (`confirm_offers`) and the stale-offer job (`mark_stale_offers`)
each updated many offer rows in one statement, in whatever order the query
plan produced. Two such statements over the same rows can deadlock, and once
a worker runs the job on a schedule the loser would be a seller's check-in.
Both now select the ids `ORDER BY id FOR NO KEY UPDATE` first and then update
by id. The job also skips rows that are locked: a seller editing an offer at
that instant is confirming it. `tests/db/test_inventory.py` races the two.

## D-034 The worker: one row, one transaction, at-least-once to the outside

**Follows** blueprint F.8 and D.16, and states one limit. **Accepted.**

The worker (`python -m markx.worker`) handles each outbox row in a single
transaction: lock one due row with `FOR UPDATE SKIP LOCKED`, run its handler
inside a savepoint, mark the row done, commit.

- Two workers never take the same row: the second skips a locked row.
- A worker that dies mid-row commits nothing. PostgreSQL drops its lock with
  its connection, and the row is pending again, untouched. No lease or
  time-out has to be tuned.
- A handler that raises loses its own database work, and the row waits 30
  seconds, then 1, 2, 4 ... minutes, up to an hour. After 8 attempts it is
  marked `failed` and logged at CRITICAL. Other rows are not held up.
- Everything a handler writes **to the database** happens exactly once,
  because it commits together with the row's `done`.

**The limit.** A message that leaves the server cannot join a database
transaction. If the worker dies in the instant after Telegram accepted a
message and before the commit, the row is retried and the person could see
the message twice. The choice is between that and losing a message; an order
alert seen twice is harmless and one never sent is not. Every outgoing message
carries the outbox row's id as an idempotency key, so an adapter can refuse a
repeat. **The real Telegram adapter must remember the keys it has sent**,
because Telegram's API has no such key of its own.

A handler that kills the whole process every time is never counted as an
attempt, so it would be retried forever. None exists; note it if one appears.

Only one topic exists, `notify.push`: an in-app notification is passed on to
the person's Telegram when they have linked it, and a `notifications` row
with channel `telegram` records the delivery. The only push adapter is a
fake; on a real server the factory refuses it (as D-016 does for SMS), so
messages are retried and then marked failed rather than pretended sent.

## D-035 Scheduled jobs are rows the worker locks

**Follows** blueprint F.8. **Accepted.**

`scheduled_jobs` (migration `0006`) has one row per job with the time it runs
next. A worker runs a job only while holding that row's lock, in one
transaction with the job's work, so two workers never run one job at once, a
dead worker leaves the job due, and a job that raises is retried after 1, 2,
4 ... 60 minutes without touching any other job. Three failures in a row are
logged at CRITICAL: that is the blueprint's "alert" until alerting to the
founder's Telegram exists. Jobs are listed in `markx/worker/jobs.py`.

Found by a test: the row must be created in a short transaction of its own,
and only when missing. `INSERT ... ON CONFLICT DO NOTHING` waits for a row
another transaction is updating, so creating it inside the run made the
second worker wait for the whole job instead of skipping it.

## D-036 The cart lives on the server; a visitor's cart is a hashed secret

**Follows** blueprint D.10 (C-06, C-07) with one choice of method. **Accepted.**

Blueprint P9 says the cart is "saved on the phone". The `carts` and
`cart_items` tables already existed (G.2: "server copy of the cart"), and a
server cart is what survives a dropped connection and lets the review step
re-check prices against live data. So the cart is on the server:

- A signed-in buyer has one cart, keyed on their user id.
- A visitor's cart is found by a 256-bit secret in an `HttpOnly`,
  `SameSite=Lax` cookie; only the secret's hash is stored, as for sessions.
  A made-up cookie finds nothing.
- When a visitor signs in, their lines move into their own cart and the
  anonymous cart is deleted. A line in both keeps the larger quantity.
- A line records the price the buyer saw. The cart view compares it with the
  live price and says what changed; checkout refuses a cart whose seen price
  differs from the live one until the buyer accepts the change.
- An offer buyers cannot see on the product page (paused, stale, removed, a
  seller below the publishing level, an unapproved product) cannot be put in
  a cart and gives the same "not found" as an id that does not exist.
- Up to 30 lines and 20 units per line (`MAX_QUANTITY_PER_LINE` is a CHECK).

**Guest checkout.** The blueprint asks for "guest checkout with a phone
number" and "no account wall". MarkX creates an account at the first phone
code anyway (D.2), so the order is placed by a signed-in account: the visitor
fills the cart, is asked for a phone code at checkout, and their cart follows
them. There is no separate guest order path. The web app owns making that
feel like one step.

## D-037 How `place_order` works, and what it refuses

**Follows** blueprint G.5 and G.7, with the details the blueprint leaves to
the engineer. **Accepted.**

- **Locks, in this order and never another:** the buyer's cart row (`FOR
  UPDATE`; one buyer's submissions run one at a time, so a repeat finds the
  first order), then the sellers in the cart, then the offers, both in
  ascending id with `FOR NO KEY UPDATE` (D-027), then the stock rows through
  `hold_stock`, in ascending offer id. The lines are re-read under those
  locks, so nothing can change between the check and the write.
- **Nothing from the browser is used as a number.** The request carries the
  address, a delivery method per store, the payment method, an idempotency
  key and `expected_total_santim`. That last one is the total the buyer saw
  on the review step. It is compared with the recomputed total and the order
  is refused if they differ (`total_changed`); it is never used. A request
  with a price field in it is a validation error.
- **Refusals,** all before any row is written: an empty cart; an address that
  is not the buyer's own, or whose area or zone is inactive; a line whose
  offer, seller or product is no longer available; a missing or impossible
  delivery choice; a cart price that differs from the live price; a wrong
  total; a store the buyer is a member of (`own_store`: a seller must not
  confirm its own orders or pad its figures); a total above
  `orders.max_order_value_santim`; more open orders than
  `orders.max_open_direct_orders`. One line short of stock refuses the whole
  order and names the offer; the caller's rollback undoes the holds already
  taken.
- **What is written,** in G.5's order: the parent order with the address
  snapshot and totals; a seller order per seller, the groups in ascending
  seller id, each with its own item total, delivery fee, total and response
  deadline; an order item per line with its own copy of the title in both
  languages, the variant label in both languages, condition, warranty, unit
  price, line total and commission rate; an `inventory_reservations` row per
  line expiring at the response deadline; a shipment per seller order with the
  chosen mode and fee; a payment intent per seller order (direct, pending,
  reference `MX-XXXXXX-n`); a `placed` status event per seller order; an
  in-app notification plus outbox row for each seller's order handlers (the
  roles with `handle_orders`, blueprint C.3) and for the buyer. Then the cart
  is emptied.
- **The idempotency key** is unique per buyer (D-010). A repeat returns the
  first order with status 200 instead of 201 and changes nothing.
- **Payment.** Only direct payment exists (Release 1, J.1). The intent records
  how the buyer said they would pay; MarkX holds no money.
- **After confirmation** the reservation's expiry is pushed to
  `orders.fulfilment_hold_days` (14) ahead, so the stock stays held while the
  order is packed and delivered. **Nothing acts on that expiry yet**, because
  nothing after confirmation is built. The next session decides, when it
  builds completion, whether an expired fulfilment hold is released by the
  worker (and the order cancelled), or merely flagged to staff. Both are
  defensible; the blueprint's "the worker releases expired reservations"
  (G.9) suggests the former, but releasing stock under a confirmed order the
  seller may be delivering that day is not obviously right.

## D-038 The life cycle is a database fact; the parent's status is derived

**Follows** blueprint G.6, D.11 and G.8 rule 7. **Accepted.**

`markx/orders/status.py` holds the G.6 diagram, arrow for arrow (21 arrows),
and the service moves a seller order only through `_move`, which refuses any
other move and writes the status event in the same transaction. Migration
`0007` makes the same rules a database fact: `markx_seller_order_move_allowed`
is the diagram as a SQL function; a trigger refuses a seller order not created
as `placed` and any update that is not an arrow; a deferred constraint trigger
refuses, at commit, a seller order whose status has no row in
`order_status_events`. A test checks the function and the table agree on all
196 pairs. A future route cannot skip a state or lose an event, whatever it
does.

The parent order has no status column (D.11: "derived from its seller
orders"). `derive_order_status` gives: the one status all parts share;
otherwise `awaiting_seller` while any part is `placed`; `partly_delivered`
when some parts are handed over and others are still moving; `completed` or
`cancelled` when every part has ended, by whether anything was handed over;
`in_progress` for the rest. The names are the engineer's.

## D-039 The response deadline counts business hours in Addis Ababa

**Fills a gap** in blueprint D.11 (C-09 "within the response window").
**Accepted.**

The settings `orders.response_window_minutes` (30), `orders.business_open_hour`
(8) and `orders.business_close_hour` (20) existed from session one with the
note "in business hours". `markx/orders/deadlines.py` applies them: the window
runs only while shops are open, Addis Ababa time (UTC+3 all year), so an
order placed at 23:00 is due at 08:30 the next morning, not at 23:30. Opening
hours that make no sense (close not after open) mean "always open".

`expire_unanswered_orders` runs every minute in the worker, expires `placed`
seller orders past their deadline, releases their stock, cancels their
shipment and payment intent, and tells the buyer and the seller. It skips a
seller order someone is acting on at that instant and takes it next time.

## D-040 The buyer may cancel a part while it is placed or confirmed

**Follows** blueprint G.6 (`placed -> cancelled: Buyer cancels`;
`confirmed -> cancelled: Buyer or staff cancels`). **Accepted.**

`cancel_by_buyer` acts on one seller order of the buyer's own order, from
`placed` or `confirmed` only; once the seller has marked it `ready` the buyer
goes through staff (not built). The stock returns, the shipment and intent are
cancelled, and the seller's order handlers are told. The reason is optional
and stored as `closed_reason`.

## D-041 Who sees whose phone number, and when

**Follows** blueprint C.5. **Accepted.**

`contact_visible(status, confirmed)`: both sides see each other's phone only
after the seller confirmed, and not once the part ended without a handover
(declined, expired, cancelled). The seller then sees the address snapshot's
recipient name, phones, landmark, pin and driver notes; the buyer sees the
seller's contact phone and shop address. Before that the seller sees only the
zone and area, enough to decide whether it can deliver. A seller's view of an
order never includes another seller's lines, the buyer's grand total, or the
identity of a staff member or team member in the event log (events carry a
role, never a person). The `see_buyer_contact` capability (C.3) gates the
seller's side as well; Release 1's two roles both hold it.

## D-042 The commission rate is looked up at placement and copied to the line

**Follows** blueprint D.19 and J.8. **Accepted.**

`commission_bps` finds the most specific `commission_rules` row in force at
placement for the payment kind: seller, then plan, then category, then
default; the latest `valid_from` wins within a scope. The rate is written to
`order_items.commission_bps` and never recalculated; the seller's order view
shows the resulting fee in birr. No rule exists today, so every line carries
0, which is the blueprint's rule for direct orders in year one: the zero is
true because no rule was created, not because the code assumes it. No route
writes `commission_rules` yet (P11, finance staff); a rule can only be
inserted by hand. The fee is charged when the seller order completes (D-045).

## D-043 An overdue fulfilment hold cancels the order and frees the stock

**Fills the gap** D-037 left open (blueprint G.9: "the worker releases
expired reservations"). **Accepted as PROVISIONAL — confirmed by the founder
on 17 November 2026 as the pilot policy; FOUNDER MAY CHANGE BEFORE LAUNCH.**

When a seller confirms, the stock stays held for `orders.fulfilment_hold_days`
(14). The worker job `orders.cancel_overdue_fulfilment` (every ten minutes)
finds a seller order that is still `confirmed` or `ready` when that hold
expires, cancels it as the system with reason `fulfilment_hold_expired`,
releases the stock, cancels the shipment and the payment intent, and tells the
buyer and the seller's order handlers. A part that is `out_for_delivery` or
`delivery_failed` is never touched by the hold: the goods are on the road, and
the diagram allows no cancellation from there anyway.

Why cancel rather than only warn staff: the hold exists to bound how long a
shop's stock can be tied up by an order nobody packs, and a reservation that
is released while its order stays open would break the one invariant the
stock tests enforce (reserved stock equals held reservations), so release and
cancellation have to go together. The alternative, a staff warning with the
order left open, is one setting and one job away: lengthen
`orders.fulfilment_hold_days`, or replace the job's `_move` with a
notification.

**Founder's confirmation, 17 November 2026.** The founder confirmed this as
the **provisional pilot policy**: after 14 days a part that is still
`confirmed` or `ready` is cancelled and its stock released, **subject to safe
handling of orders already out for delivery**. The job meets that condition
by construction: it selects only `confirmed` and `ready` parts, so a part
that is `out_for_delivery` or `delivery_failed` is never touched, and the
state diagram allows no cancellation from those states in any case. The test
`test_an_overdue_fulfilment_hold_cancels_the_order_and_frees_the_stock`
dispatches one part and lets the hold of the other expire: only the waiting
part is cancelled, and the parcel on the road keeps its stock held. The
founder may change the policy before launch; to do so, change
`orders.fulfilment_hold_days`, or replace the job's `_move` with a
notification to staff, and update this entry and D-053.

## D-044 The handover code is derived, compared in constant time, and locks after five

**Follows** blueprint C-15, D.13, D-011 and G.7 (`confirm_delivery`).
**Accepted.**

`handover_code(shipment)` is `derive_numeric_code("handover", shipment.id,
shipment.code_version)`: six digits from the server secret. No column holds it
and no log prints it; the buyer's own order page shows it from `ready` until
the handover (`AWAITING_HANDOVER`: `ready`, `out_for_delivery`,
`delivery_failed`), to the signed-in buyer only. The seller's views, the staff
orders desk and every list leave it out.

`confirm_delivery` compares the entered code with `hmac.compare_digest`. A
wrong code raises `handover_attempts`, and **the count is committed before
the request fails**, as login codes do (`verify_otp`), so a failed request
cannot be a free try. At `MAX_HANDOVER_ATTEMPTS` (5, also a CHECK constraint)
the shipment is locked: the right code is refused too, until staff with
`intervene_in_orders` call `reissue-code`, which raises `code_version` (the
old code is dead) and restarts the count, audit-logged with a reason. Twenty
wrong codes at the same instant count exactly five: the seller order's lock
serialises them.

A rider order is handed over only from `out_for_delivery`; a collection order
straight from `ready` (`ready -> delivered`), and it is never dispatched
(`collection_order`). Delivery sets `delivered_at` and
`problem_window_ends_at = now + orders.problem_window_hours` (72).

## D-045 Completion commits the stock and charges the fee; the ledger gets only a non-zero fee

**Follows** blueprint G.6, G.7 (`complete_seller_order`), G.9, G.10 rule 4
and J.8. **Accepted.**

`complete_seller_order` runs under the seller order's lock, from `delivered`
only, by the buyer at once (`confirm-received`) or by the worker job
`orders.complete_after_problem_window` (every five minutes) once
`problem_window_ends_at` has passed. It commits each held reservation in
ascending offer id through `markx.offers.service.commit_stock` (the only code
that lowers `on_hand`), marks the reservation `committed`, and then writes one
`fee_charges` row: item value is the seller order's goods total, the amount is
the sum over lines of `line_total × commission_bps` rounded half up to a
santim (`Money.portion_bps`), never including the delivery fee. The rate is the
one copied onto the line at placement (D-042); nothing is looked up again.
`seller_orders.commission_santim` holds the same figure and the seller's view
shows it as `fee_santim` once completed.

The ledger: `markx/payments/ledger.py` posts one balanced transaction per
charge, `fee:{seller_order_id}` as its idempotency key, debiting
`seller_receivable:{seller_id}` (an asset: what the seller owes MarkX on
direct orders) and crediting `commission_income`. Accounts are created on
first use. A zero fee posts nothing, because a ledger entry must be above zero
(G.8 rule 1) and an empty transaction is noise; the `fee_charges` row still
records that the zero was charged. The device cap per order (`cap_santim`,
J.8 "[A]") is not applied yet: no rule carries one, and `cap_applied` stays
false. The reversal on refund is for the dispute work. Nothing here moves
money (G.10 rule 1): the receivable is invoiced outside MarkX until payouts
exist.

The parent order's derived status (D-038) reads `completed` as soon as every
part has been handed over, even while one is still `delivered` and inside its
problem window. That is the rule as written in session three and tested; it
is kept, and the buyer's page shows each part's own status beside it.

## D-046 A direct payment is the seller's word, recorded with the server's time

**Follows** blueprint D.12 (Release 1). **Accepted.**

`record_direct_payment`: a member who handles orders, on the seller's own part
while it is `confirmed`, `ready`, `out_for_delivery`, `delivery_failed`,
`delivered`, `completed` or `disputed` (`PAYABLE`), once. It writes
`paid_method` and `paid_at` (the server's clock, never a time from the
browser), moves the payment intent to `succeeded` with the method and
`settled_at`, adds a `payment_attempts` row marked `recorded_by: seller`, and
audit-logs the action with the amount. The seller order's status does not move:
`paid` is the Protected-prepay state and a direct order never enters it. A
screenshot proves nothing and no redirect is involved; this is a deliberate
action by a signed-in member, kept as exactly that. Staff cannot record it
yet (P11).

## D-047 Failed deliveries, retries and returns

**Follows** blueprint G.6 and J.10. **Accepted.**

`report_delivery_failed` (`out_for_delivery -> delivery_failed`) needs a
reason, kept on the shipment and in the tracking event; the handover code
stays live for the retry. `seller_dispatch` from `delivery_failed` is the
retry: the first `dispatched_at` is kept, the failure reason cleared.
`return_to_seller` (`delivery_failed -> returned`) releases the held stock
through `_release_everything`, cancels the pending payment intent and marks
the shipment `returned`; the reason becomes `closed_reason`
(`CLOSED_WITH_REASON`). Contact details stay visible after a return, as
session three's rule already said: the two sides may still need to speak.
Staff may dispatch (`/admin/orders/seller-orders/{id}/dispatch`, for a partner
courier or on a seller's behalf) and find any order by its code
(`/admin/orders/{code}`, `find_orders`); the dispatch board itself is P11.

Every shipment change goes through `_track`, which sets the shipment's status
and writes the `tracking_events` row with a source (`seller`, `staff`,
`system`, never a person's name) in the same transaction. The shipment is
locked after the seller order with `key_share=True`: tracking events point at
it, so a plain `FOR UPDATE` would meet D-027 again.

## D-048 The tracking link: sixty days, signed, no code, no name

**Follows** blueprint D.14 and C-10. **Accepted.**

`issue_tracking_link(order)` returns
`/api/v1/track/{order_id}?expires=...&signature=...`, the signature being
`sign("order-tracking-link", order_id, expires)` at 43 characters (256 bits),
the same scheme as document links (D-021). It lives sixty days from issue:
longer than a fourteen-day hold, a delivery and a 72-hour problem window, with
time to read the message. The buyer's "placed" notification carries the path
for the Telegram or SMS message, and the signed-in order page carries a fresh
one. The staff desk and the seller views never carry it.

`GET /track/{order_id}` needs no sign-in and answers `no-store`.
`open_tracking_link` compares the signature in constant time, refuses an
expiry in the past or further ahead than any link is issued for (so a forged
"never expires" link fails even if the secret leaked once), and gives one
answer, `404 tracking_link_invalid`, for a forged, expired or retargeted link
and for an order that does not exist. `tracking_view` is the buyer's page with
four things removed: the handover code, the recipient's name, phones, pin and
notes (the address keeps only zone, area and city), the action flags
(`can_cancel`, `can_confirm_received` are false), and the link itself. The
seller's and rider's contact appear under the same rules as on the signed-in
page (D-041). Reporting a problem from the page is the dispute work.

## D-049 The next-best offer: the product page's ranking, minus the seller that failed

**Follows** blueprint C-26 and D.11. **Accepted.**

When a seller declines its part or lets it expire, `_suggest_next_best` looks,
for each line, for the best offer **in stock** for the **same variant** from
**another seller**, using `product_offers` itself (D-029) with the buyer's
delivery zone from the order's address snapshot. So the suggestion is always
the offer the product page would put first among the remaining sellers; there
is no second ranking to drift. The failed seller is left out even though its
stock has just been released. One notification per line that has an
alternative, template `order.next_best_offer`, carrying identifiers only
(order, seller order, line, variant, product slug, offer). No price is put in
the message: it may have changed by the time the buyer reads it.
`GET /me/orders/{order_id}/seller-orders/{seller_order_id}/alternatives`
reads the same suggestion live for the order page, and answers an empty list
unless the part is `declined` or `expired`.

Nothing is reserved and nothing is re-ordered automatically: the buyer
decides, and buys through the normal cart and checkout. The requested
quantity is not checked against the alternative's stock beyond "in stock",
because buyers never see a seller's exact count (D-029); checkout does the
real check.

## D-050 Problems on a delivered order: reported in the window, decided by staff, no money moved

**Follows** blueprint D.17, G.6, G.7 (`open_dispute`, `resolve_dispute`),
C-16, S-16, AD-09. **Accepted, with two provisional parts below.**

- `open_dispute`: the buyer, on their own part, only while it is `delivered`
  and before `problem_window_ends_at`. `delivered -> disputed` through
  `_move`, and one `dispute_cases` row with the problem type, the buyer's
  words and a decision due 48 hours later (`orders.problem_decision_hours`,
  the blueprint's [A] figure). The worker's completion job selects only
  `delivered` parts, so a disputed part waits for staff for as long as it
  takes. The stock stays held meanwhile.
- Each side may add to an open case (`dispute_messages`): the seller through
  `/seller/{seller_id}/orders/{id}/problem/reply` (the case becomes
  `seller_responded`), the buyer through `.../problem/messages`. Everyone
  sees authors by role, never by person. A decided case accepts nothing.
- `resolve_dispute`: staff with `handle_cases` (super admin, operations,
  support: blueprint C.4), always with a written reason, audit-logged as
  `dispute.resolve`.
  - `no_action`: `disputed -> completed` through `complete_seller_order`,
    exactly as any completion: stock committed, fee charged.
  - `seller_refunded`: `disputed -> refunded`. MarkX holds no money; this
    records that the seller returned the buyer's money directly (G.6).
- **No fee is charged on a refunded part, so there is nothing to reverse.**
  The fee is charged only at completion (D-045) and the diagram has no arrow
  from `completed` to `refunded`: a refunded part never completed.
  `fee_charges.reversal_ledger_transaction_id` therefore stays unused in
  Release 1. It is needed only if a later release lets a completed order be
  refunded, which would also need a new arrow in the diagram (a migration).
- The seller order's lock guards the case: every operation on a case takes
  the seller order row first, so the case row itself is never locked and
  nothing new enters the lock order.
- The public tracking page shows the `disputed` status and never the case
  text. Photos (C-16) wait for the image pipeline. A seller's payment record
  made before the refund stays as recorded (it was the seller's word, D-046);
  the case's decision is the record that the money went back. There is no
  `refunds` table yet; it arrives with Protected payments (Release 2).

**PROVISIONAL — FOUNDER MAY CHANGE BEFORE LAUNCH** (both are easy to change;
the founder approved both as provisional on 17 November 2026, D-053):

1. **What happens to the stock on a refund.** Staff tick "the goods went back
   to the shop" (`goods_returned`). If ticked, the held units go back on sale;
   if not (lost, damaged, kept by the buyer), they leave the shop's count.
   *Other options:* always take them off the count and let the seller add
   stock back by hand; or hold returned goods for inspection before resale.
   It is one branch in `resolve_dispute`.
2. **Who decides, and how fast.** Support staff may decide alone, including a
   refund outcome, and the target is 48 hours. The blueprint asks for a
   second approver only for money MarkX moves, which Release 1 never does.
   *Other option:* require operations or finance for a refund outcome; it is
   one line in the route's permission.

## D-051 Search documents are rebuilt through the outbox, with an hourly safety net

**Follows** blueprint F.7 step 4 and F.8 ("rebuilding search documents" is a
worker job). **Accepted.**

One `search_documents` row per approved product, derived entirely from the
catalogue and the live offers (the same visibility rules as the product page:
active offer, trading seller at the publishing level, active variant).
`rebuild_document` is idempotent and reads the database as it is when it
runs; it deletes the document of a product that is no longer approved.

A change that can alter a document writes an outbox row (`search.rebuild`,
the product id) **in the transaction that made the change**. The rebuild
therefore runs only after that change is committed and always sees it. A
comparison of `updated_at` stamps would have been simpler, but can miss a
transaction that started before a rebuild and committed after it (D-028).

Where the rows come from:

- **A SQLAlchemy `before_flush` listener** (`markx/search/service.py`)
  catches every ORM change to the columns a document is built from: offers
  (status, price, condition, price confirmation, variant, seller), products
  (status, category, brand, model, specs, merge), variants, translations,
  aliases, and sellers (status, verification level). New code that changes
  those through the ORM is covered without remembering to.
- **Explicit calls** where the ORM does not see the change: the Core upsert
  of product names, the bulk price check-in and the bulk stale-offer job.
- **Stock** queues only when an offer goes **in or out of stock**
  (`_movement` in `markx/offers/service.py`): a document holds "in stock"
  and the lowest in-stock price, so a count moving from five to four changes
  nothing. Checkouts therefore add no outbox rows in the common case.
- **`search.rebuild_all`**, hourly, rebuilds every document: it repairs
  anything a change path missed (a brand or category rename today), fills an
  empty table on first run, and keeps `popularity` (units in completed
  seller orders) current.

Search rebuild rows share the outbox with notification pushes. One test that
counted all outbox rows against notifications now counts the push topic only.

## D-052 How a query matches and ranks

**Follows** blueprint D.8 and F.7 steps 5 and 6. **Accepted; the thresholds
are starting values for the golden-set tuning P8 asks for.**

The query is normalised exactly as documents are (`normalize_text`), cut to
eight words, and expanded by staff synonyms: a synonym for the whole query or
for one of its words gives an extra wording. A product matches a wording in
one of three ways, which are also the first ranking key:

1. **words** (tier 3): every word is a prefix of a document word (`simple`
   full-text vector with `:*`);
2. **sound** (tier 2): every query skeleton is among the document's skeleton
   keys (D-015), and words without a skeleton (model numbers) still match by
   prefix;
3. **letters** (tier 1): **every** query word has `word_similarity` of at
   least 0.45 to the document. Per word, not for the whole query: tested,
   "phones samsung" matched the Tecno on "phones" alone when the whole query
   was compared.

Then: in stock, a fresh price (D-029's sink rule), the best seller level, the
lowest in-stock price, popularity, and closeness. Sorting by price or by
freshness puts that key first and keeps the rest. "Total cost to the door"
(C-03) needs the buyer's zone and the delivery rates per offer; it is not in
the document yet and is not offered as a sort. Filters: category (with its
sub-categories), brand, condition, price range, seller level, in stock.
Rating and delivery speed wait for reviews and per-offer delivery data.

Every first page of a non-empty query is logged in `search_queries` with
its result count (later pages and suggestions are not). With no result, "did
you mean" offers up to three products that match at least one word, closest
first. The empty-result product-request form (`POST /product-requests`, ten
an hour from one address) stores the request for catalogue staff. Staff with
`tune_search` read the zero-result report and manage synonyms, audit-logged.

Not verified: the P8 criteria themselves (85% of a golden set of 100 real
queries in the top three; 95% of queries under 300 ms). Both need real
queries and a real-sized catalogue. The trigram match does not use the
trigram index (it compares per word with a threshold), which is fine at
pilot scale; F.7 names the point to move to a dedicated engine.

## D-053 The founder's provisional approvals of 17 November 2026

**Recorded** on the founder's written instruction. Everything in this entry is
**PROVISIONAL — FOUNDER MAY CHANGE BEFORE LAUNCH**. None of it is a settled
legal or business requirement; no engineer may describe it as one.

**Approved as provisional:**

1. **Refunds and stock** (D-050, part 1). When staff record that a seller
   refunded a buyer, the units go back on sale **only when staff confirm the
   goods have physically returned to the shop** (`goods_returned: true`).
   Otherwise they leave the shop's count. To change it: the one branch in
   `resolve_dispute`, `markx/orders/service.py`.
2. **Who decides a problem** (D-050, part 2). Staff with `handle_cases`
   (super administrator, operations and **support**) may decide alone, with a
   **48-hour** target (`orders.problem_decision_hours`). To change who: the
   `CaseHandler` permission in `markx/orders/router.py` and the
   `HANDLE_CASES` row in `markx/accounts/permissions.py`. To change the
   target: the setting.

**Kept as documented, unchanged, and easy to change** (the founder asked that
these stay visible; their F- entries below remain open and no recommendation
was implemented):

| Item | What the code does today | Where it changes |
| --- | --- | --- |
| TIN format (F-03) | Exactly ten digits after removing spaces and dashes | `_TIN` and `_clean_tin` in `markx/sellers/service.py` |
| Seller verification for used goods (F-04) | Every `used` offer needs Level 2, in every category | `USED_GOODS_MIN_LEVEL` in `markx/offers/service.py` |
| A rejected applicant (F-05) | Needs a fresh invitation | invitation use in `markx/sellers/service.py` (D-019) |
| Ownership transfer (F-02) | Not built: no route transfers a store | to be built once decided |
| Document storage (F-01) | Local disk on a laptop only; refuses staging and production | `get_private_storage` in `markx/core/storage.py`: one new adapter class |
| Fulfilment hold (D-043) | A part still `confirmed` or `ready` 14 days after confirmation is cancelled and its stock freed; a part out for delivery is never touched. **Confirmed by the founder on 17 November 2026 as the provisional pilot policy** | the setting `orders.fulfilment_hold_days`, or the job `cancel_overdue_fulfilment` |
| Merged products' offers (F-06), lifting a takedown (F-07) | As their F- entries say | as their F- entries say |

## D-054 The search golden set: a file the founder fills, a command that scores it

**Follows** blueprint P8 completion criteria. **Accepted.**

`markx/search/evaluation.py` scores real queries against the real search, as
a buyer would run them, and writes nothing (no query is logged; the session
is rolled back). The file is CSV with four columns: `query` (exactly as
typed), `expected` (the meant product's slug, or several separated by `|`),
`kind` (`amharic`, `english`, `latin_amharic`) and `source` (where it came
from, without names or phone numbers). `apps/api/search_eval/golden_queries.template.csv`
is the empty template with instructions.

The report gives the share with a right answer in the top three, per kind,
the 95th-percentile and slowest time per search, every miss with what came
back instead, and every expected slug that names no searchable product (a
mistake in the file or the catalogue, counted as a miss and listed). **It
never calls a set valid below 100 queries**, nor one missing a kind, and
says so. Time is measured around the whole search call, so it is an upper
bound on the blueprint's "database time". Exit status 0 only when the
criteria are met on a valid set.

The tests use a file marked SYNTHETIC (`tests/fixtures/search_eval_synthetic.csv`)
to check the evaluator's arithmetic. **No real query exists in the
repository, and the 85% target has not been measured.** Real queries belong
in `search_eval/golden_queries.csv` once the founder collects them; they
carry no personal data by construction.

## D-055 The web app: one Next.js app, server-rendered, holding no business rule

**Follows** blueprint F.1, F.5, F.16, F.17 and I. **Accepted.**

`apps/web` is one Next.js app (16.4.6, React 19.3.1, TypeScript 5.9.3 in
strict mode, Tailwind CSS 4.3.5, ESLint 10 with Next's configuration,
Vitest 5.1.0), versions read from the npm registry on 17 November 2026.
TypeScript 5.9.3 rather than 7.0.2 because `openapi-typescript` declares
support for TypeScript 5 only.

- **Languages in the address.** Every page is under `/am` or `/en`;
  `src/proxy.ts` sends any other address to the language chosen last
  (cookie `markx_lang`) or Amharic. Text lives in `messages/am.json` and
  `messages/en.json`; a unit test fails if their keys or placeholders differ.
  The Amharic was drafted by an AI agent and needs a native editor (I.3).
- **Route groups.** `(shop)` holds the storefront; the seller and admin
  dashboards get their own groups under the same languages.
- **Reads on the server, never cached.** Pages are server components that
  call the API directly (`MARKX_API_ORIGIN`, default `http://127.0.0.1:8000`)
  with the visitor's cookies and `cache: "no-store"`. Cache Components is
  off. A price is never served from a cache; edge caching of public pages
  (F.1, 60 seconds) is a deployment decision for later.
- **Actions in the browser, same origin.** Changes (cart, sign-in, checkout,
  seller actions) are sent from the browser to `/api/v1/...` on the page's
  own origin; `next.config.ts` rewrites `/api/*` to the API in development,
  and the reverse proxy does it in production (F.5). So the API's own
  `HttpOnly` session cookie, CSRF token and origin check work unchanged.
  `src/lib/api/browser.ts` adds `X-MarkX-Client` and `X-CSRF-Token`.
- **Works before script.** Search, filters, paging, the variant choice and
  the delivery-area choice are plain links and GET forms. Actions that change
  data need script today; doing them as server actions so they work without
  it is a later step.
- **Types from the API.** `scripts/export_openapi.py` writes the API's
  OpenAPI description to `apps/web/src/lib/api/openapi.json`;
  `openapi-typescript` generates `schema.d.ts`; `openapi-fetch` uses it.
  CI fails if either copy is stale.
- **Design tokens** from I.3 are the Tailwind theme in `src/app/globals.css`:
  Ink, Paper, Adey, Highland (verified and protected only), Clay, Slate,
  Line; system fonts; 12-pixel cards; the tibeb line on the header and footer.
- **Page weight (F.1).** Measured on the production build on 17 November
  2026: about 138 to 142 KB of JavaScript transferred, compressed, on the
  home, search and product pages. That is the baseline the blueprint asks
  the first milestone to record; the budget is the baseline plus at most
  30 KB of page-specific script. No automated check yet.

## D-056 Demo data for a laptop, created through the real API

**Accepted.** `apps/api/scripts/seed_demo.py` (`uv run python -m
scripts.seed_demo`) fills a local database with a demo catalogue (five
phones), three delivery zones, three approved demo shops with offers, and a
demo buyer, all through the API in-process, so every rule, audit row and
search document is produced by production code. It refuses to run unless
`MARKX_ENV` is `local`, and does nothing if its staff account exists. The
shops, people, numbers and prices are made up and say so; none of it may be
loaded into staging or production. It prints the demo staff password and
authenticator secret for that laptop only.

## D-057 Review fixes in search: the typo match uses its index, rebuilds of one product take turns, repeated golden queries count once

**Follows** D-051, D-052, D-054. **Accepted.** Found in the seventh
session's independent review (a parallel backend session; the web app was
not touched).

1. **The typo tier scanned every document.** `word_similarity(word,
   search_text) >= 0.45` cannot use an index, and because it is OR-ed with
   the word and sound tiers, every search fell back to reading the whole
   `search_documents` table. It is now written `word <% search_text` with
   `pg_trgm.word_similarity_threshold` set to `LETTER_MATCH` for the
   transaction (`set_config(..., true)`), which the existing trigram GIN
   index answers. Same rule, same threshold (pg_trgm compares with `>=`;
   checked). Measured once, on a throwaway table of 50,000 **synthetic**
   rows on a development container: 322 ms before, 41 ms after, for the
   three-tier condition alone. That is a laptop measurement of the
   condition, not the P8 timing criterion, which still needs real data at
   real size. Test: `test_a_typo_match_is_answered_by_the_trigram_index`
   (fails on the old form).
2. **Two rebuilds of one product could leave a stale price.** A rebuild
   that read the offers before a change committed could write after the
   rebuild queued by that change, keeping the old "from" price until the
   hourly job (two workers, or the hourly job against the outbox).
   `rebuild_document` now takes a transaction-scoped advisory lock on the
   product first (`pg_advisory_xact_lock(0x4D585352, hashtext(id))`), so
   the second rebuild waits and then reads the committed state. Test:
   `test_a_rebuild_that_read_older_offers_never_writes_last` forces exactly
   that interleaving and fails without the lock.
3. **Repeated golden queries counted towards the 100.** A file of four
   queries repeated 25 times was called a valid set. Rows whose queries
   normalise alike run the same search, so they now count once towards
   validity (`distinct_queries` in the report; each repeat is named in the
   notes). All rows are still scored. The arithmetic test now uses 100
   distinct SYNTHETIC queries; a new test shows repeats count once.

Reviewed with no defect found: dispute opening, messages and decisions
(seller-order lock, buyer and seller scoping, no fee on a refund, payment
intents cancelled on both refund paths), the next-best offer (buyer-scoped,
only for declined or expired parts, the failing seller excluded), seller
isolation (`require_seller`, `_own_seller_order` on every seller order
action), and the worker's outbox and job locking.

Noted, not changed: `GET /search` writes one `search_queries` row per first
page and has no rate limit; a flood of searches grows that table. A limit
or sampling is a product decision for later (blueprint D.8 asks for every
query to be logged).

## D-058 Containers for a laptop: one API image, a Compose file, nothing deployed

**Follows** blueprint P1 ("container setup") and F. **Accepted.** No cloud
resource, registry or deployment was created; the founder's AWS was not
touched.

- **One image for the API and the worker** (`apps/api/Dockerfile`):
  `python:3.13-slim-bookworm`, dependencies from `uv.lock` exactly
  (`uv sync --locked --no-dev`; uv 0.11.32 from PyPI), the code and the
  migrations, run as the unprivileged user `markx`, no test tools inside, a
  health check on `/api/v1/healthz`. The default command is the API; the
  worker is `python -m markx.worker`, migrations `alembic upgrade head`. No
  secret is baked in: configuration is `MARKX_*` at run time. The base image
  is a build argument (`PYTHON_IMAGE`) so a mirror of the same image can be
  used when Docker Hub limits pulls.
- **`infra/compose/compose.yaml`**: PostgreSQL 17 with the built-in C.UTF-8
  locale; on an empty volume `initdb.sh` runs `infra/postgres/bootstrap.sh`,
  so the roles are the same as everywhere else; a one-shot `migrate` service
  (as `markx_migrator`); then the API and the worker (as `markx_app`). Every
  port is bound to 127.0.0.1. **The web app is left out on purpose**: it was
  being built by another session at the time, and adding it is a small,
  separate step for whoever owns `apps/web`.
- **CI** gains a `containers` job: the Compose file is valid, the image
  builds, runs as `markx`, holds no pytest, and loads the API, the worker
  and alembic.
- **Verified on 17 November 2026** in a development container: the image
  built; `compose up` brought PostgreSQL to healthy, the migrations exited 0,
  the API reported `{"status":"ok","database":"up"}`, the worker ran all six
  jobs, the demo data loaded from the host, and a typo search ("samsnug")
  found the Samsung Galaxy A16 through the worker-built index. The stack was
  then removed with its throwaway volumes.

---

## Decisions that need the founder

**Nothing below is implemented as policy.** Each item says what the code does
today, what the engineer recommends and why, what it blocks, and whether the
founder's approval is required. An engineer may implement a recommendation only
after the founder says so in writing; the answer then becomes a `D-` entry
above and this item is removed.

### F-01 Where sellers' identity documents are stored

- **Today:** `markx/core/storage.py` has one adapter, local disk, and it
  raises on a `staging` or `production` configuration (D-020). No document has
  ever left a laptop.
- **Recommendation:** a private, S3-compatible bucket at Cloudflare R2:
  server-side encryption on, no public access, reached only through the
  existing five-minute signed links. The adapter interface does not change, so
  it is one new class. The blueprint already records R2 as an alternative with
  10 GB free and no download fees (F.6, marked [V]). If the founder would
  rather keep one provider, a private S3 bucket in the isolated MarkX AWS
  account (blueprint M.3) is equally correct and costs a little more.
- **Reason:** documents are the most sensitive data MarkX holds (G.11,
  "Sensitive"). They need a store that is private by default, encrypted, and
  separate from the public image bucket. Either option satisfies that; R2
  keeps the bill near zero while the pilot is small.
- **Blocks:** not development. **It blocks any real seller applying**, and so
  the controlled launch.
- **Founder's approval required: yes.** It is a paid account, a choice about
  where Ethiopian personal data lives, and the same question as blueprint O,
  question 1.

### F-02 Whether a transfer of ownership drops the seller to Level 0

- **Today:** transfer is not built (D-022). Nothing depends on the answer.
- **Recommendation:** yes, drop to Level 0 on transfer, and keep the business
  documents (licence, TIN certificate, shop photo) accepted, because they
  belong to the business and not to the person. The new owner then supplies
  one identity document and staff restore Level 2. Offers vanish from buyers'
  pages automatically while the level is below `sellers.min_level_to_publish`,
  so no extra mechanism is needed.
- **Reason:** Level 1 means "the owner's identity was checked" and Level 2
  builds on it (C.6). After a transfer that sentence is no longer true, and
  the badge would be claiming something nobody verified. Trust is the product
  (D.3).
- **Cost the founder should weigh:** the store goes dark to buyers until staff
  finish the re-check. If that is unacceptable, the alternative is to keep the
  level for a fixed grace period (seven days is a reasonable figure) with the
  re-check due inside it, and drop to Level 0 if it passes unanswered.
- **Blocks:** neither development nor launch, as long as transfer stays
  unbuilt. It blocks building transfer.
- **Founder's approval required: yes**, but not urgently.

### F-03 Whether an Ethiopian TIN always has exactly ten digits

- **Today:** the application form accepts exactly ten digits and rejects
  everything else (`_TIN` in `markx/sellers/service.py`). That came from the
  engineer, not from the blueprint, and it is recorded as a known limitation
  in `docs/DEVELOPMENT_STATUS.md`.
- **Recommendation:** the founder checks one or two real licences and confirms
  the length. If it turns out to vary, relax the rule to 9 to 13 digits and
  let staff reject a wrong number at review, where the licence document is in
  front of them anyway.
- **Reason:** a format rule that is stricter than reality turns a legitimate
  seller into "you cannot apply", and the founder would only learn of it as a
  seller who gave up. The real control is the staff check against the
  document, which happens either way.
- **Blocks:** not development. **It can block real pilot sellers** if ten is
  wrong.
- **Founder's approval required: yes**, and it is the cheapest of these to
  answer: one glance at a real TIN.

### F-04 Whether every used item needs Level 2, or only used phones

- **Today:** every offer with condition `used` needs Level 2, in every
  category (D-025). The blueprint says it of used phones.
- **Recommendation:** keep it as it is for the pilot. The launch wedge is
  phones, so the wider rule costs nothing today, and it is stricter rather
  than looser. Narrow it later, if a category needs it, by making the minimum
  level a setting per category.
- **Reason:** counterfeits and stolen goods are the risk the rule exists for
  (D.22, H.4), and nothing about a used laptop makes it safer than a used
  phone. Widening a restriction is safe; relaxing one needs evidence.
- **Blocks:** neither.
- **Founder's approval required: not to continue.** A decision is wanted
  before MarkX opens categories beyond phones and accessories.

### F-05 Whether a rejected applicant needs a fresh invitation

- **Today:** yes. An invitation is used once (D-019), so a rejected applicant
  cannot reopen an application without staff issuing another one.
- **Recommendation:** keep it. Staff can issue a new invitation in one
  request, so an applicant who was rejected for a fixable reason (a blurred
  photo, a name mismatch) is let back in deliberately rather than
  automatically.
- **Reason:** onboarding is invite-only precisely so that staff decide who is
  in the queue (D.3). An invitation that survives rejection lets an applicant
  loop through the queue unchecked, which is the cheap abuse path here.
- **Note:** staff ask for better documents with "request documents" instead of
  rejecting, which keeps the application open. Rejection should be used when
  the answer is no, not when a document is poor.
- **Blocks:** neither.
- **Founder's approval required: no.** It follows from the blueprint's
  invite-only rule. It is written here so the founder can overrule it.

### F-06 What happens to a seller's two offers when products are merged

- **Today:** merging a product that has any offers is refused with a clear
  message (D-026). Merging a product with no offers works and is tested.
- **Recommendation:** when the merge path is built, map each variant of the
  duplicate onto a variant of the survivor, move the offers, and where one
  seller ends up with two offers for the same variant and condition, **keep
  the offer that was already on the surviving product** and remove the other.
  Write an audit entry holding both prices and notify that seller so they can
  re-list if they preferred the other terms.
- **Reason:** the survivor's page is the one buyers are already looking at, so
  keeping its offer changes nothing a buyer has seen. Keeping the cheaper of
  the two instead would silently move a price the seller set, and MarkX never
  changes a seller's price without being told to. Removing rather than
  deleting keeps the price history and any order that points at the offer.
- **Blocks:** not development now. It blocks tidying duplicates once sellers
  are live, so it is wanted before the pilot catalogue collects them.
- **Founder's approval required: yes**, because the rule decides which of a
  seller's listings survives.

### F-07 Who may lift a staff takedown of a listing

- **Today:** any staff member who may take a listing down (super
  administrator, operations, catalogue) may also lift the hold, with a
  reason, through `POST /admin/offers/{id}/restore` (D-032). The seller
  then lists the item again with today's price and stock; nothing is
  published by the restore itself. A hold never expires on its own.
- **Recommendation:** keep it as it is for the pilot, and read the audit log
  for `offer.staff_restore` now and then. Narrow it later (to operations and
  the super administrator only, or to two different staff members) if a
  catalogue curator ever lifts a takedown operations made.
- **Reason:** the three roles that moderate listings are the three that know
  why a listing came down. A second-approver rule is right for money (C.5)
  and heavy for a relist.
- **Blocks:** nothing.
- **Founder's approval required: no.** It is written here so the founder can
  overrule it.

---

## Open questions carried over from session 1

1. **The blueprint's file name.** It is committed as
   `MARKX_MASTER_BLUEPRINT.md`, as instructed. Its own first lines still say
   its file name is "All In One MarkX master Blue Print.md". The content was
   not edited, to keep it byte-identical to the upload. Say so if the header
   should be updated.
2. **Blueprint section O, questions 1 to 6** are still open: where production
   personal data may live, AWS credits and region, acceptance of the Proposed
   decisions, and the founder's time. F-01 above is the same question as O.1
   and is the one that now has a deadline.
3. **A licence for the code**, if any. None is granted today.
