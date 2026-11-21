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

**Update (D-089, 18 November 2026):** the SMS side is now built as far as it
can be without a provider: the interface, a provider-independent HTTPS
adapter, delivery records, a resend cooldown and monitoring. Staging and
production now refuse to *start* with the fake SMS sender. Still blocked on
O.23 (F-11).

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
| Document storage (F-01) | Local disk on a laptop only; refuses staging and production | `get_private_storage` in `markx/core/storage.py`: one new adapter class (note of 19 November 2026: that adapter now exists, the S3 and R2 store of D-090; F-01 itself is still open) |
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

## D-059 Search is throttled per network address

**Follows** blueprint H.2 ("throttles on search"), D.8 and F.3. **Accepted.**

`GET /search` and `GET /search/suggest` count each request against the
caller's network address in the PostgreSQL rate-limit counters, in one-minute
windows, before the search runs. Past the limit the API answers 429
`rate_limited` with `retry_after_seconds`; the refused search is neither run
nor logged. The limits are settings staff can change:
`search.requests_per_ip_per_minute` (default 120) and
`search.suggestions_per_ip_per_minute` (default 300, counted apart, because
suggestions follow typing). Every first page is still logged (D.8 says
"every query is logged"), so the throttle is also the bound on what one
address can write to `search_queries` and to the zero-result report.

Not done, on purpose: no per-session limit for searches (the address limit
and the edge's bot protection cover it), and no pruning of old
`search_queries` or `rate_limit_counters` rows, because deleting data needs
the founder's approval. Both tables grow by at most one row per search, or
per address and minute. A retention period for both is listed for the
founder below (F-08).

## D-060 The completion job completes each order on its own

**Follows** G.6, G.7 and F.8 ("a job that keeps failing raises an alert").
**Accepted.**

`complete_after_problem_window` used to complete every due seller order in
one transaction, so one order that could not complete (a bug, a stock row
out of line, a deadlock) undid all of them, run after run. Each order now
completes in its own savepoint. The database's commit-time checks (the
balanced ledger and the event for every status change, all four declared
`INITIALLY DEFERRED`) are run inside that savepoint with `SET CONSTRAINTS
ALL IMMEDIATE`, then set back to deferred; without it a violation found only
at the job's commit would still undo every order. A failed order stays
`delivered`, keeps its stock held, is logged at ERROR with its id, and is
tried again on the next run. The job's result counts completed orders only.

The two expiry jobs (`expire_unanswered`, `cancel_overdue_fulfilment`) keep
one transaction for their batch: they release stock for all their orders in
one ascending offer-id pass, which is the lock order checkout relies on
(D-027), and splitting it per order would break that order. Tested by
`test_one_order_that_cannot_complete_never_blocks_the_others`, for an error
raised at once and for an unbalanced ledger posting found only at commit;
both fail on the old code, and the second fails without the
`SET CONSTRAINTS` line.

## D-061 The API description: the back end's copy is exact, the web app's may lag behind additions

**Supersedes** the CI rule of D-055 that the web app's copy must equal the
API byte for byte. **Accepted**, for as long as the back end and the web app
are built by separate sessions.

The back end now keeps its own copy, `apps/api/openapi.json`, written by
`uv run python -m scripts.export_openapi openapi.json`; CI and a test check
it exactly, so every API change appears in review. The web app's copy
(`apps/web/src/lib/api/openapi.json`) is checked by
`scripts/check_openapi_copy.py`: every path, method and schema it contains
must be unchanged in the API, and so must its top-level sections; routes and
schemas the API adds are allowed and listed. So the back end can add
endpoints without editing `apps/web`, and any change that would break the
web app's generated types still fails CI. The web app's owner regenerates its
copy (`export_openapi ../web/src/lib/api/openapi.json`, then `npm run
gen:api`) to use the additions. Changing an existing route or schema still
needs both sides in one change.

## D-062 The picture pipeline: cleaned at upload, rendered by the worker, private evidence

**Follows** blueprint F.6, D.5, D.26 (image sizes), S-06, C-16, AD-03, H.2
and the P5 criterion "images are served as small WebP files with no
location data". **Accepted.** Migration `0008`.

- **Upload.** Staff who curate the catalogue add catalogue pictures
  (`POST /admin/catalog/products/{id}/images`); a seller member who manages
  offers adds a "real photo" of a product its store has an offer on
  (`POST /seller/{seller_id}/products/{id}/photos`). The bytes are decoded
  and written out again (`sanitize_image`), so only JPEG, PNG and WebP
  pictures pass, and the camera's EXIF, including location, never reaches
  storage. Uploads are capped by `images.max_upload_bytes` (8 MB; the phone
  compresses first, S-06), read one byte past the cap and no further, and
  rate-limited. Limits per product: `images.max_catalogue_per_product` (12)
  and `images.max_real_photos_per_seller` (6), held under a per-product
  advisory lock so two uploads at once cannot both pass. Answer: 202, the
  picture `processing`.
- **Render.** The clean copy is kept privately as the source and the outbox
  queues `images.render` in the same transaction. The worker renders WebP in
  two fixed sizes: a thumbnail within 320 pixels and 30 KB, a main picture
  within 1,200 pixels and 150 KB (D.26), lowering quality and then size
  until each fits, upright (the camera's rotation applied), with no EXIF,
  XMP or ICC data. Then `ready`. A source that cannot be rendered is marked
  `failed` (final, with its reason); a storage error is retried by the
  outbox.
- **Showing.** `GET /catalog/products/{slug}/images` lists ready catalogue
  pictures in order, then ready real photos of stores that may publish
  (active, at the publishing level), each with its store. A merged product
  shows its survivor's; a draft shows nothing. Public files live in public
  storage under unguessable keys. On a laptop the API serves them at
  `/api/v1/media/...` (dev tools only, immutable cache, no cookies); on a
  real server they come from the CDN's cookieless domain
  (`MARKX_PUBLIC_MEDIA_BASE_URL`), and the public storage adapter, like the
  private one, refuses to run there until a real bucket adapter exists
  (F-01).
- **Moderation.** Staff who moderate listings (super administrator,
  operations, catalogue) remove any picture with a written reason
  (`POST /admin/catalog/images/{id}/remove`); a seller withdraws its own.
  Nothing is deleted: the row keeps who, when and why, and the audit log
  has before and after.
- **Problem photos (C-16).** The buyer, and separately the seller's order
  handlers, add up to `images.max_problem_photos_per_side` (5) photos to an
  open problem. They are rendered at once to one private WebP (1,600 pixels,
  600 KB: evidence keeps detail), never shown publicly, and opened only
  through a link that works for five minutes, for the person it was issued
  to, who must still be the buyer, an order handler of that seller, or staff
  who handle cases. Staff views are audit-logged. `problem_photos` is
  append-only for every role, like the history tables.
- **Not done:** the product card and product page do not carry picture
  addresses yet, because adding them changes existing response schemas the
  web app types (D-061); the web app reads `/catalog/products/{slug}/images`
  until both sides change together. Pictures on order lines
  (`order_items.image_key`) and on reviews are not wired. No real bucket or
  CDN adapter.

## D-063 Backups: an encrypted dump, a restore that never overwrites, a drill in CI

> **Superseded by D-094** (18 November 2026) for everything but the legacy
> restore: the CBC format, `backup.sh`, `scheduled.sh` and `drill.sh` are
> gone; `restore.sh` lives on as `infra/backup/restore-legacy-cbc.sh`.

**Follows** blueprint F.13, H.2 (backups) and the P2 deliverable "a nightly
encrypted backup and a scripted restore". **Accepted.** Nothing is uploaded
anywhere; no cloud resource was created.

- `infra/backup/backup.sh DBNAME` writes `pg_dump` in custom format, owners
  and grants included, piped straight into AES-256 encryption (`openssl enc
  -aes-256-cbc -pbkdf2`, 600,000 iterations) and a SHA-256 checksum file.
  It refuses a passphrase shorter than 32 characters, or one kept inside the
  backup directory, and never writes an unencrypted dump. It deletes nothing
  unless `--keep-days N` is given, which removes only its own older backup
  files (the blueprint keeps 30 days; PROVISIONAL — FOUNDER MAY CHANGE
  BEFORE LAUNCH).
- `infra/backup/restore.sh FILE TARGET` checks the checksum, refuses if the
  target database exists, creates it with the roles exactly as
  `bootstrap.sh` does, and restores in one transaction. If the restore fails
  (a wrong passphrase, a damaged file) it removes the empty database it
  created itself, and nothing else.
- `infra/backup/drill.sh DBNAME` backs up, restores into a new
  `markx_drill_<time>` database, compares the migration version and every
  table's row count, checks that the application role still cannot change
  the audit log in the copy, reports the time taken (target: four hours),
  and drops only the drill database. CI runs it on every push against the
  demo data.
- `PG_DUMP`, `PG_RESTORE` and `PSQL` choose the client commands, so the
  server's own tools can run in its container when the local client is
  older (`pg_dump` refuses a newer server). `bootstrap.sh` honours `PSQL`
  too and now reads its SQL from standard input.
- **Encryption choice (PROVISIONAL — FOUNDER MAY CHANGE BEFORE LAUNCH):**
  `openssl enc` is on every server and needs no new tool. It does not
  authenticate the ciphertext; the checksum file and `pg_restore`'s own
  format checks catch damage, not a deliberate forgery by someone holding
  the passphrase. `age` or GnuPG would add that, at the cost of one more
  tool to install.
- **Not done:** the nightly schedule and the copy away from the server are
  host settings (a cron line or systemd timer, and object storage), decided
  with deployment; uploaded files (pictures, documents) are not in the
  database dump and need their own protection once a real bucket exists
  (F.6). Restoring staging from last night's backup (P2 criterion 3) needs
  staging.

## D-064 Monitoring: the marketplace checks itself, alerts once, and reconciles daily

**Follows** blueprint F.8 ("a job that keeps failing raises an alert"),
F.12 (health, alerts to the founder's Telegram, the daily reconciliation)
and P2. **Accepted.** Migration `0009`.

- **Two scheduled jobs.** `ops.watch` every five minutes and
  `ops.reconcile` once a day, both after every other job, the watch last.
- **What the watch looks for** (`markx/ops/checks.py`): a job that failed
  three times running; a job more than 30 minutes overdue (a stuck worker);
  outbox messages that gave up in the last week, and messages waiting more
  than 15 minutes; delivered parts still not completed 30 minutes after
  their problem window (what D-060 now lets happen to one order without
  blocking the rest); unanswered parts not expired 15 minutes after their
  deadline; parts holding stock past their fulfilment hold; problems past
  their decision time; the daily SMS budget at 80% (warning) or spent
  (critical); pictures processing for over 30 minutes. Each check runs in
  its own savepoint: a check that breaks becomes a critical alert of its
  own (`ops.check_failed:<check>`) and the others still run, because the
  watch is what reports failing jobs.
- **What the reconciliation proves:** every order equals the sum of its
  parts, every part the sum of its lines; every completed part has one fee
  charge equal to its commission, and every charged fee is in the ledger
  for that amount, with debits equal to credits overall; every offer's
  reserved stock equals its held reservations.
- **Alerts** (`ops_alerts`): one open alert per key. A new finding opens
  one and sends a message; a finding that persists touches it
  (`occurrences`, `last_seen_at`) without a second message, except when a
  warning becomes critical; an alert nobody finds any more resolves and
  sends "Resolved: ...". Rows are kept. Summaries hold counts, job names and
  order codes, never a name, phone number or address.
- **Where messages go:** through the outbox (`ops.alert`), so a delivery
  failure retries. To the founder's private Telegram group when
  `MARKX_TELEGRAM_BOT_TOKEN` and `MARKX_ALERT_TELEGRAM_CHAT_ID` are set; to
  the log at CRITICAL otherwise; on a laptop and in tests also to
  `var/storage/dev/alerts.jsonl`. The group, the bot and its token are the
  founder's to create; none exists yet.
- **For an outside uptime monitor:** `GET /api/v1/healthz` (API and
  database) and the new `GET /api/v1/healthz/worker`, which answers 503
  when no scheduled job has started for five minutes. A worker that is down
  cannot alert about itself; the outside monitor must poll this. Choosing
  and configuring that monitor is part of deployment.
- **For staff:** `GET /admin/ops/status` (open alerts, every job's last
  run and error, outbox messages not done) and `GET /admin/ops/alerts`, for
  every staff role that may find orders (super administrator, operations,
  support, finance): they show counts and order codes only.
- **Not done:** an error tracker (F.12, a free-tier service with personal
  data removed) needs an account; the cloud spending alarm belongs to the
  AWS setup the founder has not approved.

## D-065 The rest of the admin back end: audit log, switches, staff, dispatch board, dashboard

**Follows** blueprint D.18, C.4 and P11 (AD-05, AD-06, AD-13, AD-14,
AD-17). **Accepted.** No migration. The web screens are the web app's
owner's to build on these routes (D-061 lists them as additions).

| Route | What | Who (C.4) |
| --- | --- | --- |
| `GET /admin/audit-log` | The audit-log viewer: newest first, paged by id, filtered by action (a prefix ending in a dot matches a family), target, actor and time | super administrator, finance (`read_audit_log`) |
| `GET /admin/settings`, `PUT /admin/settings/{key}` | Every switch and limit with its default, value and whether this person may change it | the super administrator changes any; operations change the risk limits (AD-13) |
| `GET/POST /admin/staff`, `POST /admin/staff/{id}/role`, `POST /admin/staff/{id}/active` | Staff accounts: create (the authenticator secret is shown once), change a role, switch off and on | super administrator (`manage_staff_and_settings`) |
| `GET /admin/dispatch-board` | Parts waiting to leave a shop by rider or courier, oldest first, with the promised time and whether it is late; collection orders never appear | super administrator, operations (`intervene_in_orders`) |
| `GET /admin/dashboard?days=N` | AD-14: orders, parts by status, completed value and fees, median minutes to confirm, the share answered, delivery success, problems, live offers per product, the share of fresh prices, and the funnel from searches to orders | every role that finds orders: super administrator, operations, support, finance |

- **Risk limits** (operations may change them, C.4 "delivery zones, rates
  and risk limits"): the order value cap and open pay-at-the-door orders,
  the publishing level, the sign-in code limits and SMS budget, and the
  search throttles. Every other setting is the super administrator's.
  PROVISIONAL — FOUNDER MAY CHANGE BEFORE LAUNCH: which settings count as
  risk limits.
- **Every change is audit-logged** with before and after values: setting
  changes, staff creation, role changes, switching off and on (with the
  reason).
- **Privilege changes end sessions.** A new role or a switched-off account
  ends that person's staff sessions at once (H.2, "a new session at any
  change of privilege"). Nobody changes their own role or switches
  themselves off, and the last active super administrator can never be
  removed; staff changes take turns under an advisory lock, so two at once
  cannot leave MarkX without one.
- **No personal data on the dashboard:** counts and amounts only. The staff
  list shows a member's name and the last four digits of their phone.
- **Not done:** the problem-case log already exists (`/admin/orders/problems`);
  the reports queue (AD-16) waits for the buyer's "report a listing" form;
  review moderation (AD-12) waits for reviews; data export (C.4) and the
  weekly seller message are not built.

## D-066 Reviews and ratings: only completed orders, held when suspicious, totals in the background

**Follows** blueprint D.15, C-18, S-16, AD-12, H.4 and G.8 rule 2.
**Accepted.** Migration `0010`. The `reviews` table existed since `0001`
with no behaviour.

- **Who reviews what.** The buyer of an order item, once per item (a
  unique constraint), after its seller order is `completed` (not merely
  delivered, refunded or in dispute: D.15 "after a completed order", H.4
  "reviews only on completed orders"), for `reviews.window_days` (60)
  after completion. Nobody reviews a store they belong to, even one they
  joined after buying. Both ratings are 1 to 5; the text is optional, up to
  2,000 characters.
- **Fake-review guards** (D.15, H.4). A buyer writes at most
  `reviews.per_buyer_per_day` (10) reviews a day. A review whose text
  carries a phone number or a link (contact details that take a buyer off
  MarkX), or a buyer's review of a seller they already reviewed
  `reviews.hold_after_same_seller` (3) times in 30 days, is **held**: not
  shown, not counted, not shown to the seller, until staff publish or hide
  it. PROVISIONAL — FOUNDER MAY CHANGE BEFORE LAUNCH: the three numbers and
  the two patterns.
- **Editing.** The buyer may change the ratings and text until the seller
  replies or the window closes; the same checks run again. A review staff
  hid cannot be edited back.
- **The seller** (owner, manager and the orders role, C.3) sees its
  published and hidden reviews, without the buyer's order code, and replies
  once to a published review, rewording allowed. It cannot remove a review:
  there is no route for it.
- **Staff** who moderate reviews (super administrator, operations, support,
  catalogue: C.4) see the held queue and publish or hide any review with a
  written reason, audit-logged with before and after.
- **What the public sees** (`GET /catalog/products/{slug}/reviews`,
  `GET /catalog/stores/{slug}/reviews`): published reviews, newest first,
  "a verified buyer" with the variant, the store and the date, never a
  name, phone number or order code. A merged product's reviews show on its
  survivor's page.
- **Rating totals** (`rating_summaries`, per product and per seller: count,
  sum, how many gave each star) are derived from published reviews only.
  Every write, edit and moderation queues `reviews.recount` through the
  outbox; one recount of a subject runs at a time (an advisory lock, as for
  search, D-057); the daily `reviews.recount_all` job repairs anything.
- **Notifications:** the store's members who may reply hear of a new
  visible review (`review.received_for_seller`); the buyer hears of the
  first reply (`review.seller_replied`). The ops watch warns about held
  reviews waiting more than two days.
- **Not done:** photos on reviews (C-18 names them; the problem-photo
  pipeline of D-062 is the model to follow), ratings on the product card
  and in search ranking and filters (they change existing schemas, D-061),
  the seller rating feeding the trust level.

## D-067 Reports on listings, stores and reviews: anyone flags, staff resolve with a note

**Follows** blueprint C-30 ("a report link on every listing, review and
store"), AD-16 (the queue), C.4 and H.4. **Accepted.** Migration `0011`.
The `reports` table existed since `0001` with no behaviour.

- **Who reports what.** Anyone, signed in or not, flags a product, an
  offer, a store (by its id or its link name, as on its page) or a review,
  with a reason from a fixed list (counterfeit, prohibited, wrong
  information, offensive, fraud, spam, other) and an optional note of up to
  500 characters. Only what a buyer can see can be reported: an approved
  product, an offer that is up from an active store, an active store, a
  published review; anything else answers "not found", so the form cannot
  be used to probe for hidden things. Staff sessions are refused: staff
  act with their own tools.
- **Limits.** One open report per signed-in person and target (a unique
  index; a second tap answers `already_reported`); 10 reports an hour per
  network address and 20 a day per person. The reporter learns only that
  the report was received. A visitor's report records no identity at all.
- **The queue** (`GET /admin/reports`), for staff who "moderate reviews
  and handle reports" (C.4: super administrator, operations, support,
  catalogue): open reports oldest first, each with what its target is
  (product and store link names, a review's first words) and how many open
  reports that target has, so a much-flagged listing stands out.
- **Resolving.** Staff act with the tools that exist (take an offer down,
  hide a review, archive a product, suspend a store), then resolve the
  report as `actioned` or `dismissed` with a written note, by default for
  every open report on the same target. Audit-logged with the list of
  reports closed; every signed-in reporter is told the outcome
  (`report.resolved`). Nothing is deleted. The ops watch warns about
  reports open more than two days.
- **PROVISIONAL — FOUNDER MAY CHANGE BEFORE LAUNCH:** the reason list,
  letting visitors report without signing in, and the limits.
- **Not done:** acting on a report from the queue in one step (staff use
  the existing takedown, hide and suspend routes); a report link in the
  web app (its owner's, D-061).

## D-068 Data exports for an accountant: four CSV files, no buyer data, every export logged

**Follows** blueprint C.4 ("export data": super administrator and finance),
D.21 ("exports for an accountant"), G.10, G.11 and H.2 (data exports in the
audit log). **Accepted.** No migration.

`GET /admin/exports/{kind}?first_day=&last_day=` returns a CSV file for
whole days in Addis Ababa time (UTC+3, the same fixed zone the order
deadlines use), at most 366 days:

| Kind | One row per | What it is for |
| --- | --- | --- |
| `fees` | fee charged on a completed seller order, by completion time | MarkX's revenue in Release 1, with the seller's legal name and TIN for invoicing |
| `ledger` | ledger entry, both sides of each transaction, by posting time | the double-entry record (G.10) |
| `seller-orders` | seller order placed in the period | totals, status, the fee, how the buyer paid the seller: **no buyer name, phone or address** (G.11: an accountant needs totals, not people) |
| `seller-balances` | seller with a fee account | fees charged in the period and the balance owed at its end, read from the ledger, never recalculated (G.10 rule 5) |

- **Amounts** appear as exact birr with two decimals, made from whole santim
  with integer arithmetic ("555.00"), and as santim.
- **Spreadsheet safety.** Text a seller typed (legal name, TIN, closing
  reasons, ledger descriptions) that starts with `=`, `+`, `-`, `@`, a tab
  or a carriage return gets a leading apostrophe, so a spreadsheet shows it
  instead of running it (OWASP "CSV injection"). The file starts with a
  UTF-8 byte-order mark so Amharic names open correctly.
- **Every export is audit-logged** (`data.export`, with kind, period and
  row count) and sent with `Cache-Control: private, no-store`.
- Built in memory: fine for Release 1's volumes (a year of a pilot is
  thousands of rows). Streaming and an export history are for later.
- **Not done:** seller statements (S-14, AD-11) are Release 2; payouts and
  refunds have no rows to export in Release 1.

## D-069 The takedown queue: every listing under a staff hold, with its reason

**Follows** blueprint D.18 (AD-03), C.4 and D-032. **Accepted.**

`GET /admin/offers/held` lists the offers under a staff takedown, newest
takedown first, for `moderate_listings` (super administrator, operations,
catalogue). Each row has the store, the product and version in the asked
language, the condition, the price, when it was taken down and the reason
staff gave (read from the latest `offer.staff_remove` audit entry). A
seller's own removal is not in it. Paging by cursor (`before`, the last id of
a page); a cursor that is not a held offer (lifted since, or never one) ends
the list instead of starting it again, so a client cannot loop. It is where
`POST /admin/offers/{id}/restore` is used.

The ninth session's own audit-log route was dropped before it was pushed:
D-065's `GET /admin/audit-log` already does that job and is the one the web
app uses.

## D-070 The admin dashboard shows each role only its own queues, in words

**Follows** blueprint I.4 ("queues first"), C.4 and D-055. **Accepted.**

- **One menu table** (`apps/web/src/app/[lang]/admin/(desk)/menu.ts`): each
  queue with the capability that opens it, the same capability the API
  checks. The admin home sends a person to the first queue their role may
  open. Before this it always sent them to Problems, which catalogue and
  finance staff may not open. A role with no queue sees a sentence saying
  so; a page opened by its address that the API refuses says so too, instead
  of showing an empty list.
- **Codes in words.** Staff roles, seller statuses, review states, document
  and product statuses and actor types are shown through `codeLabel` and the
  `labels` group of both message files; a code the app does not know yet is
  shown as it is rather than hidden. A unit test lists every code the API
  defines and fails if one has no words in either language.
- **New screens**, each behind its capability: product proposals
  (`curate_catalogue`: approve, turn down with a note, or merge into an
  approved product), invitations (`review_sellers`: invite a phone number,
  withdraw an open invitation), listing takedowns (`moderate_listings`: find
  a product's live offers by its link name, take one down with a reason,
  lift a hold) and the audit trail (`read_audit_log`, over D-065's route:
  filters by kind of record, record, action or action family, and an
  "older entries" cursor). The web app holds no rule: each form sends the
  person's choice and shows the API's refusal in words.
- The Amharic text was drafted by an AI, like the rest; it needs the
  native-speaker review the blueprint already requires (I.3).

## D-071 The rest of the admin screens: read the API, act through it, refuse in words

**Follows** blueprint D.18 (AD-05, AD-06, AD-12, AD-13, AD-14, AD-16), C.4,
D-055, D-064 to D-068 and D-070. **Accepted.** No API change.

Screens added in the ninth session's second half, each behind the
capability the API checks (`menu.ts`, tested per role in `menu.test.ts`):

| Screen | Capability | What it does |
| --- | --- | --- |
| Dashboard | `find_orders` | The API's figures for 1, 7, 30 or 90 days; shares written as percentages (`formatShare`), nothing computed |
| Dispatch board | `intervene_in_orders` | Parts waiting to leave a shop, late ones marked; each opens in the orders desk, where dispatching already works |
| Operations | `find_orders` | Open alerts, scheduled jobs, the outbox, recent resolved alerts |
| Reviews | `moderate_reviews` | Held first; publish or hide with a reason |
| Reports | `moderate_reviews` | Open first, by what was reported; acted on or dismissed with a note, by default for every open report on the same thing |
| Settings | `manage_staff_and_settings` or `change_delivery_and_risk` | The API says which rows this person may change (`may_change`); the rest are shown read-only |
| Staff accounts | `manage_staff_and_settings` | Create, change a role, switch off and on; the API's refusals (your own role, the last super administrator) shown in words |
| Exports | `export_data` | Pick the days and download one of four CSV files |
| Pictures | `moderate_listings` (upload: `curate_catalogue`) | Every picture of a product in every state with its thumbnail; upload a catalogue picture (the worker renders it); take any picture down with a reason |

- **The authenticator secret of a new staff account is shown once**, on the
  screen that created it, from the API's answer; the web app does not store
  it. The browser journey proves the shown secret signs the person in.
- **A download is fetched by the page**, so a refused period comes back as
  the API's reason in words (`period_invalid`, `period_too_long`), not as raw
  JSON in a new tab. The API decides the period's limits; the page checks
  only that a date looks like a date.
- **Setting descriptions are the API's own English text** (`settings_store`),
  shown with `lang="en"` on the Amharic page too. Translating them would
  mean either duplicating the API's text in the web app or adding a
  translation to the API; neither is done yet (Known problems).
- The menu's items may now name either of two capabilities (settings).
- **Uploads** go through `sendForm` in `src/lib/api/browser.ts`: a multipart
  POST with the app's header and the session's CSRF token, the browser
  setting the boundary. The upload form shows only to roles that curate the
  catalogue; the API checks again.

## D-072 Reviews and reports on the web: the API says who may act on a review

**Follows** blueprint C-18, C-30, S-16, D.15, I.4, D-066 and D-067.
**Accepted.** One change to an existing schema, made on both sides at once
(D-061): `MyReviewOut` gains `can_edit` and `can_reply`.

- **Two new fields.** The buyer may change a review that is not hidden, has
  no reply and whose window is open; the store may reply to a published one.
  The API computed neither, so the web app would have had to copy the
  service's rules to decide when to show a form. Now `can_edit` is true only
  for the buyer reading their own review under those rules, and `can_reply`
  only for the store reading a published review; staff see both false. The
  service still checks everything on the call. Two tests fix the flags
  against the service's refusals (`review_answered`, `review_not_published`,
  `review_window_closed`).
- **Screens.** The product and shop pages show the API's totals and published
  reviews, ten at a time (`?reviews=` the last id); a review on a product
  page links to the shop it was bought from. The buyer rates an item on the
  order page while the API lists it as waiting (`/me/reviews/pending`), and
  on `/reviews` sees everything they wrote with its state, MarkX's reason if
  it was hidden, and the shop's reply. The shop has a Reviews screen with
  one reply per review that it may reword.
- **Report links** sit on the product, on every listing, on the shop page and
  on every review, for anyone, signed in or not. The form sends the target
  and a reason; the API limits and de-duplicates (`already_reported`, shown
  in words).
- **The seller menu is role-aware** (`seller/[sellerId]/menu.ts`, tested per
  role in `menu.test.ts` against blueprint C.3), as the admin menu is
  (D-070). The seller entry opens the first screen the member's role allows,
  not always Orders.

## D-073 The performance page and the weekly seller message: numbers, once a week, never twice

**Follows** blueprint D.4 ("performance is shown in numbers, not
adjectives"), S-17, S-26, K.5 ("a weekly performance message showing the
orders MarkX brought") and P11. **Accepted.** Migration `0012`.

- **The figures** (`markx/performance/service.py`), for one store and one
  period: orders received (placed in the period) and what became of them
  (confirmed, declined, left unanswered, cancelled by the buyer), the share
  confirmed and the median minutes to confirm; what happened in the period
  from the status events (delivered, failed deliveries and the share
  delivered, completed and their value, problems reported, refunds); new
  published reviews and their average; the store's rating totals; and the
  offers that need attention (active, prices to confirm, low stock). No
  buyer is named.
- **The performance page** (S-17): `GET /seller/{seller_id}/performance?days=N`
  (1 to 90, default 30), for every member of the store (C.3).
- **The weekly message** (S-26): the hourly `sellers.weekly_report` job
  finds the last complete week, Monday to Sunday in Addis Ababa time, and
  for every trading store that existed during it and has no report yet,
  stores the figures in `seller_weekly_reports` (one row per store and
  week: a second run sends nothing) and tells the store's members
  (`seller.weekly_report`, with the week, the orders received, completed
  and their value). A suspended or closed store gets none. It is switched
  by `sellers.weekly_report_enabled`. Up to 200 stores per run; the next
  run continues. Past weeks: `GET /seller/{seller_id}/weekly-reports`.
- The message reaches a store's members through the notification list now,
  and through Telegram once the bot exists (D-034); its wording is the web
  app's and the bot's, in both languages.
- **Correction:** earlier status notes listed a `seller_metrics_daily`
  table. No such table exists in the schema; the figures are computed from
  the orders, events and reviews when asked, which is fast enough at
  Release 1's volumes. A daily metrics table that drives ranking and trust
  level (D.21) is for later.

## D-074 Pictures on the web: the card's thumbnail, the gallery, shops' photos, problem evidence

**Follows** blueprint D.5, D.9, F.6, S-06, C-16, D-062. **Accepted.** One
change to an existing schema, both sides at once (D-061): `ProductCardOut`
gains `thumb_url`.

- **The product card** (D.9: "photo, name, from ETB, ...") carries the
  thumbnail of the product's first ready catalogue picture, or null.
  `images.selectors.first_thumbnails` finds them for a page of cards in one
  query (`DISTINCT ON`). A shop's real photo never becomes the card's
  picture; a picture taken down gives way to the next. The card loads it
  lazily and shows no box when there is none, so the text never waits.
- **The product page** shows the first catalogue picture large and the rest
  as thumbnails, each a link to its main size, then "Photos from shops"
  with the shop's name. Only ready pictures with both sizes are shown.
- **The shop's photos** of a product it sells: a screen per product, linked
  from every offer, with every photo in every state, an upload and a
  withdraw button (not offered once a photo is down). The API decides who may
  add, how many and of what (`no_offer_for_product`, `too_many_images`).
- **Problem evidence** on the buyer's order page, the shop's order page and
  the orders desk: the photos both sides added, each behind the link the API
  signed for the person reading (a staff role without `handle_cases` gets
  none, as the API refuses); an upload and, for the buyer, a message form
  while the problem is not `resolved`, the same state test the shop's reply
  form already used. Message authors are shown in words (`labels.author`),
  not as codes.
- Uploads go through `PhotoUpload`, which uses `sendForm` (D-071).


## D-075 The rest of the seller dashboard: the API's answers, the member's choices

**Follows** blueprint I.4, I.5, C.2, C.3, D.3, S-05, S-13, S-26 and D-073
(the performance figures). **Accepted.** No API change.

Screens, each behind the capability the API checks (`seller/[sellerId]/menu.ts`,
tested per role in `menu.test.ts`):

| Screen | Capability | What it does |
| --- | --- | --- |
| Overview | any member | Shop and application state in words, level, role, MarkX's note, what is still missing (the API's `missing` list, linked to the screen that fixes each), the send-for-review button, today's offer counts, what MarkX checked, every screen the role opens |
| Performance | `see_performance` | The API's figures for 7, 30 or 90 days and the weekly messages it sent (D-073) |
| Add an offer | `manage_offers` | Search the catalogue, pick the product and version, then condition, price, stock, warranty and delivery |
| Store settings | `edit_store` | Name, link, about, hours, areas, returns, Telegram; shown on the public shop page |
| Team | `manage_staff` | Members with their roles; add by phone; remove (not offered for the owner) |
| Documents | `change_legal_details` | Every document with MarkX's decision and note; upload a photo of one; open one behind a link the API signs for this member |
| Legal details | `change_legal_details` | The owner's legal details, until they are sent for checking |
| Payout account | `change_payout_account` | The accounts by their last four digits and state; add one |

And `/seller` for someone without a shop: the application form when the API
says they may apply (`/seller/eligibility`: invite-only at launch), otherwise
how to get an invitation. A new application lands on the overview.

- **Where the page still tests a state** it does what the existing problem
  forms do: it shows the send button only to an owner while the shop is
  `applied` and the application `draft` or `needs_documents`, and no remove
  button on the owner's row. The API refuses anything else
  (`application_not_editable`, `owner_cannot_be_removed`) and the refusal is
  shown in words. A `can_submit` flag would remove even that; not added.
- **Roles offered for the team** are the four the API's schema accepts; the
  API gives only `manager` today and says so (`role_not_available`). There
  is no route that lists the roles available now.
- **Defaults are the API's.** The low-stock warning is prefilled from the
  default the API's description declares (`OfferIn.low_stock_threshold`),
  read on the server, not a number in the web app.
- **The phone's bottom bar** holds the overview and up to three work screens
  (`primary`); every other screen is on the overview and in the wide menu.
- **Not built:** product proposals from a seller (`POST
  /seller/{id}/product-proposals` needs the category's attribute options for
  its variants), closing the shop, and a map pin for the shop's location.

## D-076 A store with orders in progress cannot close

**Fills a gap in** blueprint G.1 and C.3 (the owner may close a store, which
is archived, never deleted). **Accepted**, as a safety rule the founder may
change.

Closing was allowed at any time, but a closed store can no longer act on its
orders (`require_seller` refuses it): a buyer with an order placed,
confirmed, packed, on the way, delivered inside its problem window, failed
or disputed would be left with nobody to finish it. `close_seller` now
refuses with `open_orders_remain` (and the count in `details`) while any of
the store's seller orders is in one of those states; declined, expired,
cancelled, returned, completed and refunded orders do not count. The store
row is locked first, and checkout locks the same row before it places an
order, so no order slips in between the count and the close. Two tests
(`tests/api/test_seller_closing.py`).

## D-077 The remaining screens: account, staff setup, trust actions, proposals, categories

**Follows** blueprint I.4, I.5, C-08, C-26, H.5, D.5, D.6, D.8, D.13, AD-01,
AD-02, AD-05, S-05. **Accepted.** No API change except D-076.

A comparison of every API route with the routes the web app calls showed
these had no screen, and the tenth session's earlier report was wrong to say
otherwise. Now:

| Screen | Who | What it does |
| --- | --- | --- |
| Account (`/account`) | a signed-in person | Name and message language; saved addresses (add, remove); messages from MarkX in words with a link to what each is about, the ten newest shown; data requests (a copy, a correction, deletion; H.5); sign out on every device |
| The next-best offer | the buyer | On a part the shop declined or let expire, the best offer from another shop for each line, added to the cart in one tap (C-26) |
| Category page (`/c/{slug}`) | anyone | Breadcrumbs, subcategories and the category's products as cards; filters stay on search |
| Search suggestions | anyone | Product names as links while typing two letters or more; the plain form still works without script |
| Shop location | the owner | Latitude and longitude, typed or from the phone, before the application is sent (legal details lock after); the public shop page links to OpenStreetMap |
| Close the shop | the owner | Behind a confirmation; refused in words while orders are in progress (D-076) |
| Suggest a product | `propose_products` | The same product form staff use; the API makes it a proposal staff review |
| Level and standing | `review_sellers` | Set the verification level with a reason, record the re-check, suspend, reinstate; the checks behind the level shown |
| Delivery zones | `change_delivery_and_risk` | Zones, their areas (switched on and off), and each zone's fee and promised time per way of delivering |
| Catalogue setup | `curate_catalogue` | Categories (add, rename, reorder, switch off), attributes with options, which attribute a category uses and how, brands, the goods not allowed |
| Products | `curate_catalogue` | Every product by state; a new product from its category's details and versions; one product's text, versions, search names and links to its pictures and listings |

- **Notifications** are shown from their template's words
  (`src/lib/notifications.ts`, tested against every template the API sends,
  including the two a condition chooses); an unknown template reads as a
  generic line, never a code.
- **One product form** (`ProductForm`) serves staff and shops; a category's
  version-defining details become the version lines, the rest its details.
  A new version may leave a detail the other versions leave empty
  (`variants_inconsistent` otherwise).
- **Where a page tests a state** (the standing actions by the shop's status,
  the close section by capability), the API refuses anything else in words.
- `e2e/setup-and-account.mjs` drives all of it (13 steps) and tidies the demo
  data it creates.

## D-078 Setting descriptions in Amharic

**Follows** blueprint I.1 (two languages, equal quality). **Accepted.** One
change to an existing schema, both sides at once (D-061): `SettingOut` gains
`description_am`.

The admin settings screen showed each setting's English description on the
Amharic page too (D-071). The Amharic text lives in the API beside the
settings (`markx/core/settings_am.py`), so a description and its translation
change in one place; `tests/unit/test_settings_am.py` fails if a setting has
no Amharic description, if one names no setting, or if one is not written in
Ethiopic script. The screen shows the description in the page's language.
Drafted by an AI agent; a native speaker must review them with every other
Amharic text (blueprint I.3).

## D-079 A single worker pass reports failure in its exit code

**Fills a gap in** blueprint F.8 (the worker). **Accepted.**

`python -m markx.worker --once` exited 0 even when every due job failed and
the outbox could not be drained (found with the database stopped: ten
"could not run scheduled job" errors, then "worker pass finished" and exit
0). Whoever ran it — a browser journey, a scheduler, a container check —
could not tell. The pass report now carries `drain_error`, and `ok` is true
only when every due job ran and the outbox was drained; `--once` exits 1
otherwise and logs the failed jobs and the drain error. A message that
failed and will be retried is the outbox working, not a failed pass. The
long-running worker (`run_forever`) is unchanged. One test.

This did not explain the one pass in the admin journey that seemed to handle
none of the due messages: there was no failure to report. D-082 found the
cause.

## D-080 The store page's track record, and search by rating and seller level

**Follows** blueprint D.4 and I.5 (a store page shows "confirmation speed,
delivery success and rating") and D.8 (filters include "seller level and
rating"). **Accepted**; the 90-day window is the engineer's and the founder
may change it.

- **Track record.** `PublicStoreOut` gains `figures_days` (90),
  `confirmation_share`, `median_minutes_to_confirm` and
  `delivery_success_share`, from the same figures as the store's own
  performance page (D-073), each null while there is nothing to count. The
  store page shows them in words; under a minute reads "within a minute".
  The rating was already there (D-072).
- **Search.** `GET /search` gains `min_rating` (1 to 5): the product's
  average from its published reviews, written as `rating_sum >= min_rating
  * review_count`; a product nobody rated is left out while the filter is
  on. The search page offers "4 stars and up" and "3 stars and up", and the
  seller level filter the API already had (`min_level`).
- **Not done:** delivery speed as a filter and "total cost to the door" as a
  sort (D.8). Both need the buyer's delivery zone in search, which the
  search documents do not hold.
- **Not done on purpose:** a rating on the product card. Blueprint D.9 lists
  the card's facts (photo, name, "from" price, sellers, best seller level,
  freshness) and a rating is not one of them.

Additive changes (D-061): one test each (`test_performance.py`,
`test_reviews.py`).

## D-081 The browser journeys run on GitHub when asked

*Superseded in part by D-084: they now run on every code push, against Compose.*

**Follows** blueprint P1 (automated checks) and the boundary "no paid
resources". **Accepted.**

`.github/workflows/journeys.yml` runs all six browser journeys in Chromium
on GitHub's free hosted runners against a fresh demo database: PostgreSQL
17 as a service, the roles and migrations, `seed_demo` (its staff secret
masked in the log and handed to the journeys), the API and the production
web build started in the background, then one step per journey, the
screenshots and both server logs kept for a week. It takes about a quarter
of an hour, so it does not run on every push: only on a push whose commit
message contains `[journeys]`, or from the Actions tab once the file is on
the default branch (GitHub starts manual workflows only from there).
Playwright is installed without being saved as a dependency of the web app.

The six journeys sign the demo buyer in more often in one hour than the
API's limit against attackers allows (five codes a phone; found when the
last journey was refused in a local rehearsal on a fresh database). The
job raises `auth.otp_per_phone_per_hour` to 30 and `auth.otp_per_ip_per_hour`
to 200 on its throwaway database, through `settings_store` before the API
starts; the limits themselves are tested in `tests/api/test_auth_otp.py`.

Every push still starts the workflow; without `[journeys]` its one job is
skipped. The first tagged run was cancelled while it built the web app,
because the next push (a documentation commit) joined the same concurrency
group, which cancels runs in progress. The group's name now ends in whether
the run will really work (`true` or `false`), so an ordinary push can only
cancel another empty run.

## D-082 `--once` handles every due message; a pass sends what its jobs queued

**Fixes** the "one worker pass handled nothing" question (session ten).
**Accepted.**

The pass did not handle nothing. The database shows it handled exactly 100
messages, the oldest, from 18:01 to 19:31:12, in about a second
(`finished_at` 20:02:42 to 20:02:43), and stopped: a pass drains at most one
batch of 100 (`DEFAULT_BATCH`). About 30 minutes of journeys without a
worker had queued 168; the 68 newest stayed, the journey's picture among
them. The first look counted only the 68 left (attempts 0) and wrongly
concluded the pass had done nothing.

The running worker is right to work in batches: a pass with a full batch
starts the next at once, and between batches the scheduled jobs (an
unanswered order expires every minute) keep their times under a backlog.
A single pass started by hand, a script or a scheduler is different: who
starts `--once` expects the work done. So:

* `python -m markx.worker --once` handles every message due when the drain
  starts, however many batches that is (`run_once(outbox_limit=None)`,
  `drain(limit=None)`). That ends: each row is handled once per drain and
  left done, failed, or due again only later than the drain's time.
  `seed_demo` does the same. The running worker keeps its batches.
* A pass now decides what is due when its jobs have finished, not when it
  began. A message a job queues is stamped with the database's time inside
  the job, after the pass began, so it waited for the next pass: found when
  replaying the glitch, where `ops.watch` opened a backlog alert whose message
  stayed pending. It now goes out in the same pass. A `now` passed in (the
  tests move time) is used for both, as before.

Replayed on a copy of a demo database: 246 messages waiting 35 minutes and
the same eight jobs due; one `--once` handled 247 (the 246 and the alert
`ops.watch` opened), none left; before the fix it stopped at 100. Two tests,
each failing on the old code: 220 waiting messages, of which one pass of the
running worker handles 100 and `--once` the other 120; and a message a job
queues goes out in the same pass. The admin journey is back to one worker
pass for its picture, without the retries added while the cause was unknown.

## D-083 Provisional answers to F-01 to F-08, until the founder decides

**The founder's request** (18 November 2026): "For F-01 to F-08 fill with
your intelligence guess, but comment with it must change for real live."
**Accepted as PROVISIONAL.** Every answer below is the engineer's guess
(the recommendation already written under each item). **Each must be
confirmed or changed by the founder before MarkX goes live.** Each is marked
in the code with `PROVISIONAL (F-0n, D-083)` where it lives, and
`tests/unit/test_provisional_decisions.py` fails if a marker disappears;
when the founder decides one, it becomes a `D-` entry, and its marker and
test line go.

| Item | Provisional answer | What it changed |
| --- | --- | --- |
| F-01 identity documents | A private, encrypted Cloudflare R2 bucket, no public access, the existing five-minute signed links | Nothing yet: the account must be created by the founder (a paid service, Ethiopian personal data). Until then a real environment still refuses to store a document. Marked in `core/storage.py` |
| F-02 transfer of ownership | The store drops to Level 0; its business documents stay accepted; the new owner supplies an identity document | Nothing yet: transfer is not built. The rule waits beside `TRANSFER_OR_CLOSE` in `accounts/permissions.py` |
| F-03 TIN length | Exactly ten digits, as today; staff check it against the licence | Nothing; marked at `_TIN` in `sellers/service.py`. Check one real licence |
| F-04 used items | Every used item needs Level 2, in every category, as today | Nothing; marked at `USED_GOODS_MIN_LEVEL` |
| F-05 rejected applicant | Needs a fresh invitation, as today | Nothing; marked at `reject_application` |
| F-06 merging products with offers | When built: the survivor's offer stays, the other is removed (not deleted), both prices audited, the seller told | Nothing yet: merging a product with offers is still refused. Marked in `merge_product` |
| F-07 lifting a takedown | The three roles that take listings down may lift the hold, with a reason, as today | Nothing; marked at `ListingModerator` |
| F-08 retention | Search logs 180 days; rate-limit counters one day after their window could end | **New:** the daily job `retention.prune` (`markx/ops/retention.py`) and two staff-adjustable settings, `retention.search_queries_days` (180) and `retention.rate_limit_counters_days` (1), both described as PROVISIONAL on the settings screen in both languages. It deletes only those two tables, writes the counts to the audit log when it deleted anything, and is refused nothing by the database (neither table is protected). A rate limit may no longer use a window longer than a day (`ratelimit.LONGEST_WINDOW`), so the job never deletes a count in use. Five tests |

Nothing in this entry creates an account, a cloud resource or a cost.

## D-084 Security fixes and CI hardening from the independent audit (P0-1, P0-2)

**Follows** blueprint H (security), F.1 and D.26 (page weight) and the
pipeline of section Q ("a secret scan, a dependency audit and the
page-weight check on every change"). **Accepted.** The audit report itself
(`MARKX_INDEPENDENT_AUDIT_OPUS55.md`) was not in the repository; the
findings were taken from the founder's brief and each was confirmed in the
code before it was fixed.

**SEC-1, sign-in open redirect (high).** The sign-in page accepted any
`next` that started with one `/`. Browsers read `/\evil.example` and
`/<tab>/evil.example` as `//evil.example`, another site, and Next.js
decodes `%5C` to `\` before the page sees it. One helper,
`apps/web/src/lib/safe-next.ts`, now decides: it looks through up to three
layers of percent-encoding, refuses backslashes, control characters and
anything not starting with exactly one `/`, then requires the URL parser to
keep the address on the site. The page uses it, and `SignInForm` checks
again before it navigates. 31 unit tests (`safe-next.test.ts`), including
`/\host`, `/%5Chost`, `//host`, `%2F%2Fhost`, tab and newline forms; the old
check sent two of them off the site.

**SEC-2, the fake bot check on a real server (high).** The fake accepts
every token, even none, and was the only adapter, on every environment.
Now staging and production refuse to start while
`MARKX_BOT_CHECK_PROVIDER` is `fake` (the same validator that refuses
development secrets), and `get_bot_check()` hands a real server a check
that refuses everyone, so a misconfigured server sends no code rather than
one to a robot. Laptops and tests keep the fake. Consequence, stated
plainly: **no real server can start until a real bot-check adapter
(Cloudflare Turnstile is the candidate) is built and configured**, just as
no code can be sent there until a real SMS adapter exists.

**SEC-3, forwarded headers (medium).** uvicorn trusted `X-Forwarded-For`
from `127.0.0.1` only. In a container the reverse proxy is another address,
so every visitor would have looked like the proxy and shared one
rate-limit bucket (one attacker could stop everyone's sign-in); the obvious
"fix", `FORWARDED_ALLOW_IPS=*`, would let anyone choose their address. The
API now reads forwarded headers itself, through uvicorn's
`ProxyHeadersMiddleware` as the outermost layer, believing only
`MARKX_TRUSTED_PROXIES` (exact addresses or networks; default loopback;
`*` and catch-all networks refused at start-up). The nearest untrusted
address in the chain wins, so a visitor cannot prepend one. The image runs
uvicorn with `--no-proxy-headers` so nothing else reads them; CI checks it.
On a real server set `MARKX_TRUSTED_PROXIES` to the proxy's address.

**SEC-5, security headers (medium).** API responses now carry
`Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (they
are data, never pages; the laptop-only docs page is left alone) and, only on
staging and production, `Strict-Transport-Security: max-age=31536000`.
That is safe there because those environments already refuse to start
without an `https://` origin and secure cookies; `includeSubDomains` and
`preload` are not sent, because they bind every subdomain and belong with
the founder's domain decision. The web app sends a CSP limited to its own
origin (plus `MARKX_MEDIA_ORIGIN`, the picture CDN, when set), `nosniff`,
`X-Frame-Options: DENY`, a referrer policy, a permissions policy and
`Cross-Origin-Opener-Policy`. Its scripts still allow `'unsafe-inline'`:
Next.js writes small inline start-up scripts, and a nonce per request would
make every page dynamic, a performance change to measure separately. The
web app sends HSTS only when `MARKX_HSTS_MAX_AGE` is set at build time. All
six browser journeys passed under the new CSP with no console errors.

**SEC-6, anti-forgery exemptions (low).** Two prefixes were exempt
(`/api/v1/webhooks/` and anything starting `/api/v1/telegram/webhook`),
though no webhook exists, so any route later added under them would have
skipped the guard. Exemptions are now exact paths (`CSRF_EXEMPT_PATHS`,
empty today); a test fails if an exempt path is not a real route.

**CI (P0-2).** A new `security` job in `ci.yml`: Gitleaks 8.28.0
(checksum-verified) over the whole history with `.gitleaks.toml` (all
default rules; only lines labelled dev-only or test-only are excused);
`pip-audit` over the locked environment, development tools included; and
`npm audit` through `.github/scripts/npm-audit-gate.mjs`. That gate fails
on any high or critical advisory in production dependencies, and in
development dependencies unless the exact advisory is reviewed in
`.github/security/npm-audit-allowlist.json` with a reason and an expiry
date (expired entries fail). One entry today: picomatch ReDoS
GHSA-fc5q-39xc-vjpf, which reaches only vitest, vite and eslint, has no
fixed version (4.0.7 is the newest), and is in nothing sent to browsers
(production audit: 0 advisories). It expires on 31 December 2026.

`journeys.yml` replaces D-081's "only when asked": the journeys run on
**every push that changes `apps/`, `infra/` or the workflow** (a
documents-only push does not start them), against **PostgreSQL, the
migrations and the API from Compose**, built from the same Dockerfile. The
seed and the journeys' single worker passes run on the runner (they need
development tools the image leaves out), so `infra/compose/compose.ci.yaml`
gives the API container the runner's picture folder and user. Compose's
always-running worker is not started: it would race the journeys' "Being
prepared" checks. Playwright is now a pinned development dependency of the
web app (`playwright` 1.63.0). Any failing step fails the run. Cost: about
six minutes of the private repository's free Actions minutes per code push.

**Page weight.** `apps/web/e2e/page-weight.mjs` runs first in the journeys
job: it loads five pages as a first-time phone visitor and counts the
compressed bytes transferred before images. Measured on 18 November 2026:
script 142 to 147 KB on every page; before images 157 KB (home) to 195 KB
(product page, which prefetches the pages it links to). **The 150 KB
target of D.26 is not met.** As F.1 directs, the ceiling follows the
measurement: script at most 170 KB (the framework's ~140 KB plus F.1's
30 KB) and 210 KB before images, so pages cannot get heavier unnoticed.
Closing the gap (link prefetching, the RSC payload) is open work.

Nothing in this entry deploys anything, creates an account or costs money.

## D-085 The bot check is Cloudflare Turnstile, verified on the server

**Follows** blueprint D.2 and H.3 (a bot check before any SMS; Turnstile is
the blueprint's candidate) and closes the gap D-084 left open (SEC-2).
**Accepted by the founder** (18 November 2026). **Built and tested against
stand-ins only: not yet against Cloudflare**, because the keys do not exist
yet. Not production-ready until the check in `docs/SETUP.md` has passed with
the real keys.

**Server** (`markx/core/botcheck.py`, `TurnstileBotCheck`). For every
sign-in code it POSTs the token, the secret key and the caller's address
(form-encoded) to Siteverify,
`https://challenges.cloudflare.com/turnstile/v0/siteverify`, and accepts
only an answer with HTTP 200, a JSON object whose `success` is literally
`true`, a `hostname` among the allowed ones (default: the host of
`MARKX_PUBLIC_ORIGIN`) and `action` equal to `sign_in`. Everything else is
refused, and nothing is sent: a missing, blank, over-long (more than 2048
characters) or non-ASCII token without asking Cloudflare; Cloudflare's
"no" (`invalid-input-response` for a forged token, `timeout-or-duplicate`
for an expired or already-used one, any other code, or none); an error
status; a body that is not JSON, not an object or larger than 64 KB; a
timeout (5 seconds by default) or any network failure (fail closed). A
token is redeemed by Cloudflare once, so a reused token is refused by
Cloudflare's own answer; MarkX keeps no list of its own. The log records
the reason and Cloudflare's error codes, never the token, the secret or the
address. Only the standard library is used (`urllib`, as the Telegram
alerts do); no new dependency.

**Configuration** (`markx/core/config.py`). `MARKX_BOT_CHECK_PROVIDER` is
`fake` or `turnstile`. With `turnstile`, `MARKX_TURNSTILE_SECRET_KEY` (held
as a `SecretStr`, so it is absent from reprs, dumps and error messages) and
`MARKX_TURNSTILE_SITE_KEY` must both be set, or the API does not start.
Staging and production refuse `fake` (D-084) and refuse Cloudflare's
published test keys (`1x0000…`, `2x0000…`, `3x0000…`), which pass or fail
everyone. A laptop may use them.

**Web** (`TurnstileWidget.tsx`, `SignInForm.tsx`, the sign-in page). When
the web app runs with `MARKX_TURNSTILE_SITE_KEY` (the public key, read per
request), the phone step loads Cloudflare's script explicitly, renders the
widget with the action `sign_in`, refuses to send until it is solved
(saying so in words), sends the token as `bot_token` (the field the API
already had: no API change), and asks for a fresh token after every
attempt. Without the key (a laptop) nothing changes. The page's security
policy now allows `https://challenges.cloudflare.com` for scripts and
frames, and nothing else from Cloudflare. Two new messages in both
languages; the Amharic wants a native speaker's review like the rest.
Coordination: no other session had touched `apps/web` since the tenth
session's last commit; the changes are additions to three files.

**Tests.** `tests/api/test_turnstile.py`: Siteverify replaced by a function
and by a real HTTP server on 127.0.0.1, covering the cases above, a reused
token, a slow Cloudflare (timeout), a refused connection, error statuses,
and the secret, the token and the address never being logged. The sign-in
route end to end with Turnstile on. `apps/web/e2e/turnstile-widget.mjs`, in
the browser journeys: every request to `challenges.cloudflare.com` is
answered by a stand-in, and the page's security policy, the refusal before
solving, the token reaching the API, a fresh token per attempt and a
refused token are all checked. Cloudflare is never contacted by any test.

**Not verified here.** Cloudflare's documentation site could not be reached
from the session that built this (its network does not allow it), so the
contract above (the URL, the form fields, `success`, `hostname`, `action`,
`error-codes`, the 2048-character limit, the test keys' prefix, the widget's
`render`/`reset`/`remove` and callbacks, the two CSP directives) is
Cloudflare's long-standing published one, not re-read today. The check with
the real keys in `docs/SETUP.md` confirms it.

**Update, 18 November 2026 (second round, at the founder's request).**
- *Hostnames are checked at start-up.* `MARKX_TURNSTILE_ALLOWED_HOSTNAMES`
  takes bare hostnames separated by commas; a protocol, path, port,
  wildcard, IP address, trailing dot, empty entry, space or invalid label
  stops the start with a message naming each bad entry and its problem.
  Before, `https://markx.et` was accepted and then refused every sign-in.
  Staging and production also refuse `localhost` (and `*.localhost`), so a
  local test widget cannot be used there.
- *The founder's local test widget* "MarkX" (hostname `localhost`) exists.
  Its public site key is in `docs/SETUP.md` and allowed by `.gitleaks.toml`
  as public; its secret key is in no file. A test with it proves Turnstile
  verification only: SMS delivery does not exist yet, so a complete
  production sign-in is not possible (see `docs/SETUP.md`, "Three different
  things").
- *Credentials:* the temporary credentials are reviewed and the secret
  rotated before production use; the founder may rotate any Turnstile secret
  at any time; a founder security review is due at the 100th real
  transaction (a seller order completed on the production site) or earlier
  on request. It is a written reminder, not an automatic alert: an
  automatic one would need a way to record that the review was done (the
  alerts close only when their condition clears), which is a separate task.
- *A flaky test fixed:* `test_a_link_cannot_be_extended_or_forged` forged a
  document-link signature by replacing its last two characters with "AA",
  which left a genuine signature unchanged about once in a thousand runs
  (CI #95 on `fbaf46c`). Its forgeries now always differ from the genuine
  link; the verification code is unchanged.

## D-086 Order and payment integrity (the audit's P0-3)

**Follows** blueprint D.12, D.15, D.19, G.6, G.10, J.5 and S-26, and the
audit's P0-3 findings, each confirmed in the code first. **Accepted.** No
money moves, no provider is connected, no data is deleted.

**1. A part with a recorded payment never ends undelivered without staff.**
A seller may record a direct payment from `confirmed` on (`PAYABLE`; a
transfer before delivery is allowed). Three paths could still end such a
part with the buyer's money recorded as received and nothing recording its
way back: the buyer's cancel (from `confirmed`), the overdue-fulfilment job
(`confirmed`, `ready`) and "returned" (`delivery_failed`). All three now
refuse a part with `paid_at` set (`order_paid_contact_support`,
`paid_order_needs_staff`; the job simply skips it), and migration `0013`
adds `ck_seller_orders_paid_order_not_ended_undelivered`, so the database
refuses a paid part ending `declined`, `expired`, `cancelled` or `returned`
whatever code tries. The part keeps its state and its stock; the buyer's
page no longer offers "Cancel" on it. A new watch check,
`paid_orders_waiting`, tells staff by order code when a paid part has passed
its fulfilment hold (`orders.paid_past_hold`) or has waited a day after a
failed handover (`orders.paid_delivery_failed`); `orders.stuck_hold` no
longer counts paid parts (it means "the job is failing"). **How staff then
settle such a part is the founder's decision F-09**: today they can ask the
shop to deliver (the part can still be dispatched) but have no button to
close it with the money returned. Nothing invents a refund.

**2. A store cannot tell which buyer wrote a review.** The store's review
list and reply answer withheld the order code and id but returned
`order_item_id`, the id of the order line, which the store's own order
pages list beside the buyer's name and phone. It is now null for the store
(`MyReviewOut.order_item_id` may be null; the web app's copy and types
changed in the same commit, D-061). The buyer and staff still see it. "From
a verified buyer" rests on the review's existence (only a completed line's
buyer can write one), not on a link the store can follow. Left as is: the
review's time and the product and variant, which the public page shows too;
a store with very few orders may still guess.

**3. The weekly report and the performance page.** `orders_cancelled_by_buyer`
counted every cancelled part, including those the system cancelled because
the store let the fulfilment hold run out, and the web page labelled the
number "Cancelled by the buyer". It now counts only the buyer's
cancellations (from the status event's actor), and
`orders_cancelled_unfulfilled` counts the system's, shown as "Cancelled: not
sent in time". Weekly reports already stored keep the old meaning. The
weekly job made every store's report in one transaction, so one store's
error undid every report of the run and blocked them all; each store now
has its own savepoint, as D-060 does for orders.

**4. When an action reads the clock.** An action a person starts on a seller
order reads the clock once it holds the order (`resolve_dispute`,
`cancel_by_buyer`, `confirm_received`, `record_direct_payment`). Read
before, an action that waited behind another was stamped before the action
that came first ("cancelled" before "confirmed": a history the life cycle
does not allow). Kept as they were, on purpose: the three scheduled jobs
(the time decides what is due, and they skip locked rows rather than wait,
so they never act on a stale clock), and the two deadline checks a person is
entitled to (`seller_respond`, `open_dispute`: the button was pressed in
time; anything that came first changed the status, so the request then
fails cleanly). Each fix has a test that fails on the old code.

**5. Commission and the ledger: found, not changed.** Fees are zero by
design: blueprint D.19 gives direct orders a zero rate in year one, and no
`commission_rules` row exists, so `commission_bps` returns 0 and the ledger
receives nothing (D-045 posts only non-zero fees). What is missing before any
fee can be charged: (a) a staff tool to create versioned rules (today only a
hand-written database row, D-042); (b) **the per-order cap is stored on a
rule but never applied** (`cap_santim` is unused and `fee_charges.cap_applied`
is always false), so a capped rule would over-charge sellers: it must be
copied onto the order line at placement and applied at completion before any
capped rule exists; (c) fee reversal on a refund (the columns exist; no path
needs it while a completed part cannot be refunded); (d) invoicing and
collecting what sellers owe on direct orders (the receivable account exists,
with no invoice); (e) seller statements (S-14) and payouts and settlement
(J.7, Release 2). The rates, caps and the moment fees start are the
founder's decision F-10. Exports for an accountant (D-068) and the daily
fee-to-ledger reconciliation (D-064) already exist.

## D-087 A direct payment is recorded only once the goods are handed over (F-09)

**The founder's decision** (18 November 2026) on F-09: option 3, in stages.
**Decided.**

**Now: option 2.** A seller may record that the buyer paid directly only
from the handover on: `PAYABLE` is `delivered`, `completed` and `disputed`.
At `placed`, `confirmed`, `ready`, `out_for_delivery` and `delivery_failed`
the service refuses with `payment_not_recordable` ("only once the goods are
handed over"), leaving the payment intent untouched. Migration `0014` adds
the database's half: `trg_seller_orders_payment_at_handover` refuses
`paid_at` going from empty to set (or a new row arriving with it) while the
status is not one of those three. It checks only the moment of recording, so
a part paid in advance before this rule keeps its record and still goes
ahead to completion (a table CHECK could not allow that). The web app's copy
of the list (`SellerOrderActions.tsx`) shows "Record the payment" only from
the handover on, and the refusal's words in both languages explain why.
A transfer the buyer makes before delivery is simply recorded at the
handover. This also makes advance-payment scams harder, as blueprint D.12
prefers ("at the door after inspecting the goods").

**What D-086 still does.** Its guards (no buyer cancel, overdue cancel or
"returned" of a paid part; the database constraint; the staff alert) stay,
for parts paid in advance before this rule. No new part can reach them.

**Not built, by the founder's instruction: option 1.** No refund process,
and staff cannot mark money as returned. **A requirement for Protected
checkout (Release 2):** before an order whose payment was captured can be
closed without delivery, staff must be able to record a refund and verify
it (J.5: its own record, linked to a case or a return, never above the
amount captured, a second approver above a set amount, ledger entries
posted), and only then may the order end. Until then, a part paid in
advance before D-087 that cannot go ahead waits for staff, who are alerted
(D-086).

## D-088 Commission fees stay at zero; what must exist before any fee (F-10)

**The founder's decision** (18 November 2026) on F-10. **Decided.**

Direct-order fees stay at zero for the first year, as blueprint D.19 and
K.2 specify. No commission rule is created, and no rate, cap, invoice or
payout policy is invented. Nothing in the code changes: with no
`commission_rules` row, `commission_bps` returns 0, every completed part
gets a zero `fee_charges` row, and the ledger receives nothing (D-045).

**Mandatory before any commission is enabled:**

1. **Apply the per-order cap.** `commission_rules.cap_santim` is stored but
   never used, and `fee_charges.cap_applied` is always false (D-086). A
   capped rule would therefore over-charge sellers. The cap must be copied
   onto the order line at placement with the rate (so a later change never
   alters a past order, J.8) and applied at completion, with tests.
2. **A staff tool for versioned rules** (today only a hand-written row,
   D-042), audit-logged, never overwriting a rule in force.
3. **The seller sees the fee in birr before confirming** each order: already
   shown (`estimated_fee_santim`); check it again once rates are non-zero.
4. **Fee reversal on a refund** (G.10 rule 4, J.5): the columns exist
   (`fee_charges.reversal_ledger_transaction_id`, `reversed_at`); no path
   needs them while a completed part cannot be refunded.
5. **Invoicing and collecting** what sellers owe on direct orders, if direct
   fees are ever charged: the receivable account exists
   (`seller_receivable:<seller>`), with no invoice.
6. **Seller statements** from the ledger (S-14, G.10 rule 5), and **payouts
   and settlement** (J.7), which come with Protected checkout.
7. The founder's rates and caps (K.2's ranges are assumptions, [A]).

Already in place: the rules table with its scopes and validity dates, the
rate copied onto each line at placement (D-042), the fee charged at
completion and posted to a balanced ledger (D-045), the accountant's exports
(D-068) and the daily fee-to-ledger reconciliation (D-064).

## D-089 The SMS foundation, provider-independent

**Follows** blueprint D.2, F.0 (principle 4, adapters), F.9, F.12 and H.3,
and closes the part of D-016 that does not need a provider. **Built and
tested against stand-ins and a local HTTPS server only. No provider has
been chosen, contacted or configured (blueprint O.23), and no real SMS has
been sent.** The founder's brief of 18 November 2026 is the specification;
the earlier SMS audit it refers to was not in the repository, so its points
were taken from the brief and each was checked against the code first
(as D-084 did).

**What was there before.** `SmsSender.send(phone, text) -> None`, the fake
only; `get_sms_sender()` raised on staging and production at the moment of
sending, but the configuration let those servers *start* with the fake. A
code could be requested again at once (only the hourly limits stopped it).
Nothing recorded whether a message went out.

**The interface** (`markx/notifications/sms.py`). `send(phone, text, *,
reference) -> SmsResult` (the provider's message id, the number of segments,
the status) or `SmsSendError` with a provider-independent code and a status:
`failed` when nothing was sent, `unknown` when the provider may have taken
it. `reference` is the delivery record's id, so a provider that accepts a
client reference can be matched later. The fake keeps writing to the
development inbox, now returns `fake-<reference>` as its id, and every
existing journey and test that reads the inbox works unchanged.

**Configuration** (`markx/core/config.py`). `MARKX_SMS_PROVIDER` is `fake`
or `http`; `MARKX_SMS_API_URL` (a fixed `https://` endpoint with no user
name, password, query or fragment), `MARKX_SMS_API_KEY` (a `SecretStr`),
`MARKX_SMS_SENDER_ID` (at most 11 letters and digits, or a number of at
most 15 digits: the SMS standard's limits, not a provider's) and
`MARKX_SMS_TIMEOUT_SECONDS` (8, more than 0 and at most 30). With `http` all
three must be set or the API does not start. **Staging and production now
refuse to start with `fake`**, as they do with the fake bot check (D-084);
`get_sms_sender()` still refuses it there as a second barrier.

**The HTTPS adapter** (`HttpSmsSender`, standard library only). HTTPS only,
to the configured endpoint only; redirects are refused, not followed (one
would carry the key elsewhere), and the response socket is closed when one
is refused; the timeout is the configured one; at most 16 KB of the answer
is read; **one attempt per message, never an automatic retry** (a retried
login code is a second paid message and a second code in flight). The
number is normalised again at the boundary (`to_e164`, with
`national_format` for a provider that wants `09…`); anything but an
Ethiopian mobile number is refused before sending. Error mapping: 400, 404,
405, 409, 413, 415, 422 `invalid_request`; 401, 403 `auth_failed`; 429
`rate_limited`; 5xx `provider_unavailable`; other statuses
`unexpected_status` (all `failed`); a refused connection, DNS or TLS failure
`connection_failed` (`failed`); a timeout `timeout`, and a 2xx answer that is
not JSON, has no usable `message_id`, or is larger than 16 KB
`malformed_response` / `response_too_large` (all `unknown`: the provider
may have sent it). Logs and errors carry the code, the status, the HTTP
status and the record's id only: never the text, the code inside it, the
key, the number or the provider's body (which may echo the text).

**What is deliberately not invented.** What a provider's request and answer
look like is not known until one is chosen, so it is isolated in one small
`SmsWireFormat` (build the request; read the message id).
`NeutralJsonWire`, the only one, is **MarkX's own placeholder** (`to`,
`from`, `text`, `reference` as JSON, the key as a bearer token, `message_id`
back), not any provider's API. Choosing a provider means writing its wire
format from its documentation and tests for it; nothing else here changes.

**Segments.** `count_segments`: GSM-7 (with the extension table counting
two) 160 in one, 153 per part; anything else UCS-2, 70 and 67, counted in
UTF-16 units (an emoji is two). Amharic is always UCS-2. Both login-code
texts are one segment (tested). More than six segments is refused before
sending.

**Delivery records** (migration `0015`, a new table `sms_messages`; nothing
existing changed). Purpose (`login_code` or `notification`), `phone_ref` (an
HMAC-SHA256 of the number under the server secret, never the number), the
challenge or notification id (plain references, not foreign keys, so a
record never stands in the way of removing either), provider, provider
message id, status (`pending`, `accepted`, `failed`, `unknown`, and
`delivered`/`undelivered` reserved for delivery reports), error code,
segments, `created_at`, `updated_at`, `completed_at`, `delivered_at`. **No
column for the text or the code**, and the database refuses a malformed
record (purpose and reference must agree; a failure needs its error code;
`phone_ref` must be 32 bytes). The record is committed with the challenge
before the message is sent, then updated with the outcome. No row is ever
deleted: retention is the founder's decision (F-12).

**The resend cooldown.** `auth.otp_resend_cooldown_seconds`, 60 by default
(0 to 3600, a risk limit operations may change). Too early answers `429
otp_resend_too_soon` with `retry_after_seconds` (and `Retry-After`), and the
sign-in page says, in English or Amharic, how many seconds are left. It is
checked after the bot check and the lock, and before the hourly limits, so
an early request does not use up the hour; a transaction-level advisory lock
per number makes simultaneous requests wait for each other, so only one
sends (tested with four at once). It counts every earlier code except one
the provider certainly did not take (`failed`), so a person can retry at
once after a clear failure, and a timeout (which may have been sent) waits.
Unchanged: the bot check, the hourly limits per number and per address, the
daily budget, the five-minute expiry, the five attempts and the 15-minute
lock.

**Monitoring** (the worker's watch, `markx/ops/checks.py`). `sms.failures`
(critical): of the last hour's finished attempts, the share that failed or
went unconfirmed reached `sms.failure_alert_percent` (20) with at least
`sms.failure_alert_min_messages` (5); it names counts per error code, never a
number. `sms.unfinished` (warning): messages of the last day still
`pending` or `unknown` after `sms.unfinished_alert_minutes` (15). Without
delivery reports `accepted` is the last word MarkX gets, so it counts as
final; with a webhook it would not (`AWAITING_FINAL`). `sms.budget` is
unchanged. No balance check: there is no provider to ask.

**Tests.** `tests/api/test_sms_adapter.py` (segments, number formats, the
stand-in for every status and failure, a real HTTPS server on 127.0.0.1 with
a throwaway certificate for success, 400, 401, 403, 429, 500, 503, a
timeout, a refused connection, an oversized and a malformed answer, a
redirect and an untrusted certificate; redaction of the key, the code and
the number in logs and errors; the start-up checks).
`tests/api/test_sms_cooldown.py` (the cooldown, records without text or
code, failures recorded, the database's constraints, both monitoring
checks). `apps/web/e2e/sign-in-cooldown.mjs` in the journeys, end to end.
Test helper: `ApiClient.sign_in` lets the cooldown pass first (a test that
signs one number in twice is a person coming back later), and three
existing tests that ask for a second code do the same; the journeys
workflow sets the cooldown to 0 for its throwaway database, as it already
raised the hourly limits.

**Not done, by instruction.** No provider chosen or contacted, no account,
no delivery-report webhook, no purge of old challenges or records, no
change to Turnstile, nothing deployed. SMS for notifications has its
purpose and record but no sender yet (the outbox has no SMS channel).

## D-090 Object storage: one interface, local folders, MinIO, Amazon S3 and Cloudflare R2

**Follows** blueprint F.6 ("S3-compatible object storage behind an
adapter", a public bucket for pictures behind the CDN, a private bucket for
documents), G.11 (documents are "Sensitive"), H.2 and H.3, and closes the
engineering half of D-020's **Open** part. **Built and tested against a
local MinIO server only. No Amazon or Cloudflare account was created,
contacted or configured; no document was copied anywhere.** Which provider
holds sellers' documents is still the founder's F-01: nothing here makes
that choice.

**What was there before.** `PrivateStorage.put(key, data)` and `get`, and
`PublicStorage.put(key, data, content_type)` and `get`, each with one
local-disk adapter that raised on staging and production at the moment of
use. A real server could *start* with them; it then failed every document
upload and every picture.

**The interface** (`markx/core/storage.py`, `ObjectStore`): `put(key, data,
content_type)`, `get`, `head` (size, content type, last modified),
`exists`, `delete`, `signed_url(key, expires_in)`. `PrivateStorage` and
`PublicStorage` remain its names at the call sites, so the features that
store files (seller documents, picture sources and renderings, problem
photos) changed only to pass the content type they already knew. The
factories `get_private_storage()` and `get_public_storage()` choose the
adapter from `MARKX_FILE_STORAGE_PROVIDER`:

| Provider | Adapter | Where it is allowed |
| --- | --- | --- |
| `local` | `LocalObjectStore`: `private/` and `public/` under `MARKX_STORAGE_DIR` | Laptop and tests (the default) |
| `minio` | `S3ObjectStore`, path-style, no encryption header | Laptop, Compose and tests |
| `s3` | `S3ObjectStore`, virtual-hosted, `ServerSideEncryption=AES256` | Any; the region is required |
| `r2` | `S3ObjectStore`, path-style, region `auto`, R2 encrypts by itself | Any; the endpoint must be `https://<account>.r2.cloudflarestorage.com` |

**The SDK** is the AWS SDK for Python, `boto3` (with `boto3-stubs[s3]` for
the strict type checks; both in `uv.lock`, both audited by `pip-audit` in
CI). It is maintained by AWS and is the client Cloudflare and MinIO
themselves document for their S3 APIs. One client per configuration is
shared by the two stores. It is built with MarkX's own keys only, never
the AWS credential chain (environment variables, `~/.aws`, instance
metadata), because the founder's other AWS resources must never be reached
by accident (AGENTS.md section 2), and with the endpoint always given, so an
`AWS_ENDPOINT_URL` variable cannot send files elsewhere (both tested).
Timeouts are 5 s to connect and 15 s to read, with one retry, so a dead
provider fails a request in seconds. MarkX sends its own Content-MD5 on
every write (S3, R2 and MinIO all check it) and compares a single-part
object's ETag with the MD5 of what it reads; the SDK's newer default
checksums are turned off because not every S3-compatible service accepts
them.

**Configuration** (`markx/core/config.py`): `MARKX_STORAGE_ENDPOINT_URL`
(a bare `http(s)://` origin, no user, path, query or fragment),
`MARKX_STORAGE_REGION`, `MARKX_STORAGE_ACCESS_KEY_ID` and
`MARKX_STORAGE_SECRET_ACCESS_KEY` (both `SecretStr`, absent from logs, reprs
and validation errors), `MARKX_STORAGE_PRIVATE_BUCKET` and
`MARKX_STORAGE_PUBLIC_BUCKET` (3 to 63 lowercase letters, digits and
hyphens, **and two different buckets**), the two timeouts,
`MARKX_STORAGE_MAX_OBJECT_BYTES` (20 MB) and
`MARKX_STORAGE_SERVER_SIDE_ENCRYPTION` (`auto`, `AES256` or `none`). A
missing or malformed value stops the start with a message naming it.
**Staging and production now refuse to start** with `local` or `minio`
(MinIO is a laptop and test stand-in; files on the server's own disk are
lost with it and have no backup of their own, F.6), with an `http://`
storage endpoint, or with a `MARKX_PUBLIC_MEDIA_BASE_URL` that is not an
`https://` address on a host other than the site's (F.6: "a separate
cookieless domain"). The factories still refuse local storage there as a
second barrier.

**Security rules, kept and added.**

- **Documents and problem photos stay behind the API's own links.** The
  five-minute link signed for one signed-in person, the check that the
  person may *still* see the file when it is opened, and the audit row for
  every view (D-020, D-062) are unchanged: the API reads the object and
  answers with its bytes. **No bucket address, object key or provider link
  is ever given to a browser for a private file.** A provider's presigned
  link would work for anyone who holds it, which is exactly what D-020's
  identity-bound links exist to prevent, so `signed_url` exists in the
  interface (for operations, capped at five minutes, refused by the local
  adapter) and **no route uses it**. Tested: the link is the API's, a
  stranger, a visitor and staff without the capability are refused, a
  demoted staff member's unexpired link stops working, expiry still applies,
  and an anonymous request for the object, the bucket or its listing gets
  403 from MinIO.
- **Only pictures are stored.** Every store, whatever the caller checked
  before, refuses a content type other than JPEG, PNG or WebP, bytes that
  are not what the declared type says (from their signature), an empty file
  and anything over the size limit, and refuses to *read* an object over
  the limit. The upload checks before it (decode and re-encode, metadata
  stripped, `images.max_upload_bytes`, `sellers.document_max_bytes`) are
  unchanged and still run first. Keys are generated by the server, carry no
  personal data, cannot be guessed, and must match the same strict pattern
  as before, on every operation.
- **The two buckets.** Private objects are written with `Cache-Control:
  no-store`; rendered pictures with `public, max-age=31536000, immutable`
  and `image/webp`. MarkX never sets an access list on an object: whether
  the public bucket is readable through the CDN is the bucket's own setting.
  On a laptop both MinIO buckets are private and the API serves pictures
  itself (`/api/v1/media`, dev tools only, as before).
- **Failures name nothing.** Any provider failure becomes
  `StorageUnavailable`: a 503 `storage_unavailable` ("Files cannot be stored
  or read right now"), logged with the store, the operation and the
  provider's error code only (no key, bucket, endpoint or credential, and
  the SDK's own exception is not chained into the traceback). A missing
  object stays "not found"; a missing *bucket* is an outage, never "not
  found". An upload that cannot be stored leaves no row and no audit entry;
  a render that cannot reach the store stays `processing` and the outbox
  retries it.
- **The watch** (`markx/ops/checks.py`, `file_storage`, every five
  minutes): `storage.unreachable:private` / `:public` (critical) when a
  bucket does not answer with MarkX's keys, and
  **`storage.private_bucket_public`** (critical) when a one-pixel canary,
  `ops/privacy-canary.png`, written to the private bucket can be read
  without credentials. On R2 the S3 endpoint always asks for credentials,
  so this check cannot see a public `r2.dev` or custom domain on the
  private bucket; that setting must simply never be turned on.

**MinIO for tests and Compose.** MinIO no longer publishes images on Docker
Hub (`minio/minio` is gone there, and `quay.io` is not reachable from the
building session), so the image is Bitnami's last build of MinIO
2025.7.23, `bitnamilegacy/minio:2025.7.23-debian-12-r5`, pinned by digest
in `infra/compose/compose.yaml` and `.github/workflows/ci.yml`. It is a
frozen image used only on laptops and in CI, never on a server. If it ever
disappears, any S3-compatible test server will do; only the image line
changes. The Compose file now runs MinIO with the buckets `markx-private`
and `markx-public`, and the API and worker use it; the browser journeys on
GitHub therefore store every document, picture and problem photo in MinIO.
CI starts MinIO beside PostgreSQL for the API tests and sets
`MARKX_TEST_MINIO_REQUIRED=1`, so a missing MinIO fails the run instead of
skipping its tests; on a laptop without MinIO those tests skip.

**Moving existing files** (`scripts/copy_files_to_object_storage.py`). Not
run by anyone, and never by itself. It reads the database's references
(seller documents, picture sources, both renderings of every rendered
picture, problem photos), reads each file from a local `MARKX_STORAGE_DIR`,
and copies it into the configured buckets under the **same key**, so every
row keeps pointing at its file. A dry run by default; `--execute` writes and
then reads each copy back to compare it. It never deletes or changes a
local file, never changes a row, and never overwrites an object already in
a bucket (one with the same key and different bytes is reported "in the
way"). `--execute` also requires `--founder-approved`, because it copies
sellers' identity documents to a provider: that flag is given only with the
founder's written approval (F-01). Its report names rows by database id,
never by file key. Today there is nothing to move: no real document has
ever been uploaded (F-01).

**Tests.** `tests/storage/`: `test_object_store.py` (the contract on both
the local folders and MinIO: round trips for each picture type, delete,
missing objects, refused types, lying bytes, unsafe keys on every operation,
size limits on write and read, cache headers, two separate buckets, the
checksum, signed links that expire after one second and never live more than
five minutes, anonymous readers refused, wrong secret, unknown key, missing
bucket, a closed port and a server that never answers, each failing in
seconds and naming no key, bucket, endpoint or secret in the error or in any
field of any log record); `test_storage_config.py` (what each provider needs,
what a real server refuses, each provider's endpoint, region, addressing and
encryption, AWS environment variables ignored, switching providers by
configuration alone); `test_storage_on_minio.py` (the real API and worker on
MinIO: documents, their links and their permissions, pictures through the
worker into the public bucket and back through the media route, problem
photos, an upload and an opening while the store is away, a render that
waits for the store and then finishes, and the three watch findings);
`test_copy_tool.py` (dry run, copy, verify, never overwrite, missing and
lying files, every table's references, the founder's flag, end to end).
Each new protection was also checked the other way: the rules were taken
out one at a time (the byte check, the missing-bucket rule, the fixed
endpoint, the privacy canary, logging the provider's error text, MinIO on a
real server, one bucket for both, the re-check at opening, the private
cache header) and each time a test failed.

**Not done, by instruction.** No account, bucket, CDN or DNS name created;
nothing deployed; no real document uploaded or copied; no automatic copy;
nothing deleted. Not built: the buckets' own backups (versioning or
replication, F.6 "the buckets need their own protection"; F-14), the CDN in front of the public bucket and its domain (F-15), the
store logo and order-line pictures (columns without behaviour, as before).

## D-091 The production deployment foundation: one server, Compose, nginx, prepared and rehearsed, not deployed

**Follows** blueprint F.0 and F.13 (containers, one reverse proxy on one
domain, Compose on one small server, secrets outside the repository, one
command to deploy and one to roll back, nightly encrypted dumps), F.12
(health), F.16 (`infra/` holds the proxy configuration; `docs/runbooks/`),
H.2 and M.3. **Nothing was deployed, bought or created**: no server,
domain, certificate, bucket or account. The founder asked for the
foundation only, on 18 November 2026.

**What was built** (details: `docs/DEPLOYMENT.md`):

- **Images.** The API image is pinned to Python 3.13.18 and starts uvicorn
  without a `Server` header and with a 20-second graceful shutdown. A new
  web image (`apps/web/Dockerfile`): three stages, Next.js's standalone
  server only (`MARKX_NEXT_OUTPUT=standalone` at build time; `npm run
  build` and `next start` elsewhere are unchanged), the `node` user, no
  sources or development tools. Both accept an optional `build_ca` BuildKit
  secret for builders behind a TLS-inspecting proxy, never written into a
  layer.
- **`infra/production/compose.yaml`**, separate from the laptop file:
  proxy, web, API, worker (also the scheduler, D-035), PostgreSQL 17.12
  with data checksums, a backup service and a `migrate` step in its own
  profile. Four networks: `edge` (the proxy only, the only published
  ports), `frontend` (proxy, web, API; internal, a fixed subnet that becomes
  `MARKX_TRUSTED_PROXIES`), `backend` (API, worker, migrations, backups,
  PostgreSQL; internal), `egress` (API and worker only). Unprivileged users,
  read-only root file systems, no capabilities, `no-new-privileges`,
  `init`, memory limits for a 2 GB server, log rotation. Settings come from
  root-only files in `/etc/markx`, one per service, so the web app never
  sees a database password and only the migration step has the schema
  owner's.
- **nginx** (`nginxinc/nginx-unprivileged:1.28.2-alpine`; `infra/production/nginx/`):
  HTTP to HTTPS on the one configured hostname, certificate challenges,
  unknown names refused at the handshake, TLS 1.2 and 1.3 with
  forward-secret ciphers, HSTS once, `/api/v1/dev/`, the docs and the API
  description hidden, 1 MB bodies except the five upload routes (21 MB),
  generous edge rate limits, `X-Forwarded-For` set (never appended), JSON
  access logs with paths only, Docker's resolver so recreated containers
  are found. Cloudflare in front is prepared, not enabled.
- **Health** (`markx/ops/health.py`): liveness and readiness separated;
  readiness checks the schema against the shipped migration head and both
  file stores, in fixed words. `python -m markx.ops.preflight`. The worker's
  heartbeat file and `--check-heartbeat`. The web app's `/healthz`.
- **Migrations**: an advisory lock in `migrations/env.py`; one runner.
- **`infra/production/deploy.sh`**: `check`, `deploy RELEASE` (build,
  preflight, backup, migrate, preflight, start, verify), `rollback
  RELEASE` (no migration), `backup`, `status`.
- **`infra/production/rehearsal/rehearse.sh`**, run by CI: the whole stack
  on the runner with throwaway settings and MinIO.
- Runbooks: `docs/runbooks/`.

**Configuration rules added for staging and production** (the existing
rules of D-084, D-085, D-089 and D-090 stay): `MARKX_ENCRYPTION_KEY` must be
a well-formed Fernet key (it failed only at first use before);
`MARKX_TRUSTED_PROXIES` must be set explicitly (behind a proxy the default
made every visitor one address); `MARKX_LOG_LEVEL` must not be `DEBUG`, and
an unknown level is refused everywhere; `MARKX_PUBLIC_ORIGIN` must be a bare
origin. A real server without an alert destination says so at start-up
(a warning, not a refusal: the founder has no alert group yet). The web
container refuses to start on staging or production without its settings
(`apps/web/deploy/check-env.mjs`).

**Defects found and fixed on the way** (each with a test that fails on the
old code):

1. **A refused start-up printed part of the raw configuration**, a database
   password included (pydantic's `input_value`). `hide_input_in_errors`.
2. **Every page's server-side search counted as one visitor**: the web
   server called the API from its own address, so behind a proxy the whole
   site would share one search limit (120 a minute, D-059). The web server
   now passes the single address the proxy set, and the request id
   (`apps/web/src/lib/api/forwarded.ts`); the API believes it only from the
   proxy network.
3. **`bootstrap.sh` reset every role's password to the laptop default on a
   re-run without the variables**, which `restore.sh` does: a restore on a
   real cluster would have stopped the API and left `dev-only` passwords on
   production roles. A password is now reset only when its variable is
   given; laptops, CI and the tests behave as before.
4. **A missing bucket made the storage watch fail instead of alert**
   (D-090): S3 answers a `HEAD` on a missing bucket with a bare 404, which
   the adapter read as a missing file. `check_reachable` now reports it as
   an outage (`NoSuchBucket`).
5. Readiness on a database no migration had touched said `unknown`; it is
   `behind`, so the first deploy's preflight accepts it.

**Choices, and the alternatives not taken:**

- **nginx, not Caddy or Traefik.** Caddy's automatic certificates need the
  public domain and Let's Encrypt from the first start, and would sit
  awkwardly with Cloudflare's origin certificates if the founder chooses
  Cloudflare (M.2); nginx with mounted files works with either. Traefik
  adds a dynamic configuration nobody here needs.
- **Images built on the server from the commit**, no registry: one server,
  no paid registry, and the commit is the release name. A registry and
  signed images belong to a second server or CI deployments.
- **The worker is the scheduler**; no separate cron container (D-035
  already makes a second worker safe).
- **Readiness refuses a newer schema** unless `MARKX_ALLOW_NEWER_SCHEMA`
  acknowledges a compatible rollback: running old code on a schema it does
  not know should be a decision, not an accident.
- **The edge limits are generous** because Ethiopian mobile carriers put
  many users behind one address; the API's limits stay the precise ones.

**Not done, on purpose or because it needs the founder**: any deployment;
off-server copies of the dumps (F-16); backups of stored files (F-14, still
open); the certificate tool and the domain (F-17); an outside uptime
monitor and error tracking (F-18); zero-downtime deploys (one copy of each
service; the web server does not drain on SIGTERM); the host's firewall,
updates and spending alarm. F-01, F-14 and F-15 stay open.

---

## D-092 Notifications that survive a missing provider: delivery records, Telegram and SMS adapters, the deadline reminder

**Follows** blueprint D.11, D.16, F.8, F.9 and F.12, and the independent
read-only audit of 18 November 2026, which named seller notifications the
most important remaining functional blocker. **Built and tested against
fakes and stand-ins only. No Telegram bot exists, no SMS provider is chosen,
nothing was sent to Telegram or to any SMS provider, and notification SMS is
OFF by default.** Seller notifications remain a **launch blocker** until at
least one real channel is connected and tested (N-1).

**The defect fixed first.** `push.get_push_sender()` raised `RuntimeError`
on staging and production. Every notification for a person with a linked
Telegram therefore failed its `notify.push` outbox row eight times over
about four hours and ended `failed`, a CRITICAL log line and an
`outbox.failed` alert per message, while nothing recorded *why* the person
was never told. Now it returns `None` when no provider is configured, and
the delivery is recorded `unavailable` with the reason
`telegram_provider_not_configured`; the outbox row is `done` at once.
Configuration: `MARKX_TELEGRAM_PUSH_PROVIDER` is `none`, `fake` or
`bot_api`; unset means `fake` on a laptop and in tests and `none` on a real
server; a real server refuses `fake`; `bot_api` needs
`MARKX_TELEGRAM_BOT_TOKEN`; a real server with `none` starts and says so in a
start-up warning.

**The delivery record.** `notification_deliveries` (migration `0016`): one
row per notification and outside channel (unique), with status `sending`,
`retrying`, `accepted`, `failed`, `unknown`, `skipped` or `unavailable`, a
reason (required by the database for every outcome but `accepted` and
`sending`), the provider, its message id, the SMS attempt's record id,
attempts and times. **Never the text, a phone number or a Telegram id.** The
`notifications` row with channel `telegram` that D-034 wrote on success is
still written (with the outcome), for compatibility.

**The adapters.** Telegram: `PushSender` keeps its interface
(`send(*, telegram_id, template, params, language, idempotency_key)`), now
returning a `PushResult` or raising `PushSendError` with a
provider-independent code and a status (`failed` or `unknown`).
`BotApiPushSender` calls the Bot API's `sendMessage` over HTTPS with the
standard library (no redirects, a timeout, a bounded answer, one attempt),
reusing the SMS adapter's transport; the token is part of the address, so the
address is never logged. 400, 403 (the person blocked the bot), 401/404,
429, 5xx, a timeout, a refused connection and an unreadable 2xx answer are
mapped and tested **against stand-ins only**. SMS: the existing D-089
interface, `SmsPurpose.NOTIFICATION`, `record_message` and `send_recorded`;
no competing SMS code.

**Texts** (`notifications/texts.py`). Short English and Amharic texts for 18
order alerts, each at most two SMS segments. The only placeholder allowed is
`{code}`, filled only with a real order code (`is_order_code`); anything else
is refused (`UnsafeText`). No name, phone number, address, handover code,
price or product ever leaves the server; a parametrised test renders every
text with a buyer's name, phone, landmark and handover code in the
parameters and checks none appears. Other templates go to Telegram as a
generic "You have a new message from MarkX" line and never by SMS.

**Who receives what.** Seller order alerts go to `_order_handlers`: active
members whose role has HANDLE_ORDERS (owner, manager, orders), unchanged. At
delivery time `recipient_may_receive` checks again that the person is still
an active member with that capability, of a store that is not closed, and
that the order is that store's; otherwise `skipped`,
`recipient_not_authorized`. Inactive accounts are skipped too.

**SMS rules.** Only order alerts. `notifications.sms_enabled` (off; a super
administrator's setting, audited) must be on. With
`notifications.sms_only_without_telegram` (on) SMS goes only to a person
Telegram cannot reach: not linked, or no push provider. Its own daily budget
`notifications.sms_daily_budget` (200) in the bucket `sms:notification:daily`
— the sign-in codes keep `auth.sms_daily_budget` and `sms:daily`, so neither
can spend the other's (tested both ways). A per-person limit
(`notifications.sms_per_person_per_hour`, 6) and a per-number cooldown
(`notifications.sms_cooldown_seconds`, 120) under an advisory lock per
number. A message refused by any of them is `skipped` with its reason; the
in-app message stays.

**Delivery semantics: not exactly-once, said plainly.** A message that
leaves the server cannot join a database transaction, so a local row alone
cannot make delivery exactly-once. That needs the provider to refuse a
repeated request by a key. **Telegram's Bot API has no idempotency key or
client message id for `sendMessage`** (engineering knowledge of the Bot
API; the documentation host was not reachable from this session's network,
so it was not re-read on 18 November 2026 — check it again when the bot is
built). **No SMS provider is chosen (F-11)**, so whether one supports a
client reference that deduplicates is unknown; the adapter already sends the
record id as `reference`, so a provider that honours one could be used
without changing this design. Until then:

- Each attempt is committed as `sending` *before* the provider is called and
  its outcome right after, in short transactions of their own; the worker's
  own transaction holds only the outbox row. An attempt interrupted between
  the two is visible to the next one.
- **Telegram is at-least-once** (as D-034): an interrupted attempt is sent
  again, and the delivery keeps the reason `interrupted` even once accepted.
  A crash after Telegram took the message and before MarkX stored that shows
  the message twice; a test proves exactly that and that both carry the same
  idempotency key.
- **SMS is at-most-once**: an interrupted attempt becomes `unknown`
  (`interrupted`) and is never sent again, nor is a timeout or an unreadable
  2xx answer. A second SMS is a second paid message, the in-app message is
  always there, and the monitoring reports every unknown delivery. The cost:
  a crash just before the provider was called looks the same and loses that
  SMS (tested, and reported).
- A failure that certainly sent nothing and may pass (Telegram 429, 5xx, a
  refused connection, a timeout; SMS `rate_limited`, `provider_unavailable`,
  `connection_failed`) raises `DeliveryRetry`, so the outbox row is retried
  after its growing delay. A failure that will not pass (a wrong key, a
  blocked bot, a bad number) is `failed` at once. After six attempts
  (`MAX_DELIVERY_ATTEMPTS`, fewer than the outbox's eight) the delivery is
  `failed` or `unknown` and the row ends `done`: the record says what
  happened, not a given-up outbox row. A worker that keeps dying mid-send is
  now bounded too: its attempts are counted in the committed record.
- Each SMS attempt has its own `sms_messages` record (D-089).

**Order events.** The audit's names map onto existing templates, which are
not renamed (the web app and stored notifications use them):

| Audit's event | Template(s) |
| --- | --- |
| `order.placed_for_seller` | `order.placed_for_seller` |
| `order.approaching_response_deadline` | **new**, to the store's order handlers |
| `order.confirmed` | `order.seller_confirmed` |
| `order.declined` | `order.seller_declined` (+ `order.next_best_offer`) |
| `order.expired` | `order.seller_did_not_answer` (buyer), `order.expired_unanswered` (store) |
| `order.dispatched` | `order.out_for_delivery`; `order.ready_for_collection` for collection |
| `order.delivered` | `order.delivered` |
| `order.completed` | `order.completed`, `order.completed_for_seller` |
| `order.problem_reported` | `order.problem_reported`, `order.problem_reported_for_seller` |
| `dispute.decided` | **new** `dispute.decided` / `dispute.decided_for_seller` when staff decide "no action"; a refund keeps `order.refunded` / `order.refunded_for_seller` |

**The reminder.** `orders.remind_approaching_deadline`, a job every minute
after the expiry: a seller order still `placed` whose deadline is within
`orders.response_reminder_minutes` (10) and not passed, and that was placed
more than that before its deadline. Locked as the expiry locks it and
re-checked under the lock; `seller_order_reminders` (primary key: order and
kind) makes "once" a database rule, in the same transaction as the
notifications. Confirmed, declined, cancelled and expired orders are never
reminded (tested).

**Monitoring** (`ops/checks.py`, in the five-minute watch):
`notifications.delivery_failures` (critical: at least
`notifications.failure_alert_min`, 3, failed or unknown deliveries in the
last hour, counted by channel and reason), `notifications.sms_budget`
(warning at 80%, critical when spent; says sign-in codes are unaffected),
`notifications.channel_unavailable` (warning: deliveries with no provider in
the last day) and `notifications.stale` (warning: `sending` or `retrying`
for longer than `notifications.stale_alert_minutes`, 30). No phone number or
Telegram id in any of them. The existing `outbox.*` and `sms.*` checks are
unchanged.

**Web.** Words in both languages for the three new templates; the
notifications test lists them.

**Tests** (`tests/api/test_notification_delivery.py`, 72 cases, plus
additions to existing tests): the production configuration without a
provider; `unavailable`, `skipped` and `accepted` records; SMS off by
default and on through the switch; Telegram-first; who is told and the
check again at delivery; every text in both languages free of personal
data and within two segments; the Bot API adapter's mapping against
stand-ins; both budgets independently; cooldown and hourly limit; the
reminder once, never for answered, cancelled, expired or too-late orders,
and from the worker; failures opening an alert; stale deliveries; Telegram
retries to an explicit `failed`; simulated crashes before and after the
provider accepted, for Telegram and for SMS; an SMS timeout never retried;
an SMS outage retried with a record per attempt; no channel delivered twice
by later passes; no text or number in the records or logs.

**Changed existing tests** (strengthened or kept current, none weakened):
the worker's list of jobs gains the reminder; the preflight test read the
head revision as the literal `0015` and now reads the real head; the
production start-up warning test now expects the push warning too, and its
fully configured server sets `bot_api` and still has no warning; the dispute
test also expects `dispute.decided` and `dispute.decided_for_seller`.

**Not done, by instruction.** No bot created, no Telegram or SMS account, no
provider chosen, nothing sent, nothing deployed, no paid service. Retention
of delivery records is not set (as F-12). Delivery reports (webhooks) do not
exist, so `accepted` is the last word.

## D-093 Connecting a person's Telegram: a one-time link through the bot, a secret-checked webhook, off by default

**Follows** blueprint D.2 ("one Telegram identity per account"), D.16, F.4,
the route `/telegram/webhook` of section F, and D-092's next task. **Built and
tested locally and in CI only. No bot exists, no webhook is registered,
nothing was sent to or received from Telegram, and the feature is OFF by
default everywhere.** Seller notifications remain a launch blocker (N-1).
Protocol, settings and activation steps: `docs/runbooks/telegram-linking.md`.

**Why a bot link, not the existing route alone.** `POST /me/telegram`
links from a Mini App's start-up data, which Telegram signs with the bot
token; it is secure, but it only works inside Telegram's Mini App, which is
not built. A seller on the website needs a way to prove control of a
Telegram account from a phone's browser. Telegram's deep link
(`t.me/<bot>?start=<payload>`) sends the bot `/start <payload>` *from* the
account that opened it, and Telegram, not the person, states who sent it.
So the payload is a one-time token MarkX made for the signed-in account,
and the webhook links the sender of that token. The Login Widget was
considered and not used: it needs the bot's domain set with BotFather and a
third-party script on our page (the CSP allows none), and gives nothing the
deep link does not.

**The token.** `secrets.token_urlsafe(32)` (256 bits, 43 characters that
Telegram allows in a start parameter). Only `HMAC-SHA256(MARKX_SECRET_KEY,
token)` is stored (`telegram_link_tokens.token_hash`, exactly 32 bytes by
constraint), with the account, the session that asked, the expiry
(`MARKX_TELEGRAM_LINK_TTL_MINUTES`, 10 by default) and how it ended. One
pending link per account (partial unique index); asking again revokes the
earlier one. Any use ends it, linked or refused, so a replay is "not valid".
At completion the account must still be active and the asking session not
signed out or expired. The token is returned once, in the creating
response, and never logged, audited or shown again.

**One Telegram account, one MarkX account.** `users.telegram_id` was already
unique. Completion locks the user row (`FOR NO KEY UPDATE`, D-027) and takes
an advisory lock per Telegram id (`0x4D585447`, "MXTG"), so two accounts
linking one Telegram account at once serialise; the unique constraint inside
a savepoint is the backstop. An account already connected must disconnect
before connecting another (409 `telegram_already_connected`). Locks are taken
in one order everywhere: the user's row, then their links, then the
Telegram account's advisory lock. The first version locked the link before
the user during completion; a person asking for a new link at the moment
Telegram confirmed the old one deadlocked (found in review, reproduced by a
contention test that failed on that order and passes now).

**Not leaking who is linked.** A refused link says the same thing whatever
the reason, in the bot and on the page ("could not be connected; if it is
connected to another MarkX account, disconnect it there first"). The
existing Mini App route said "linked to another number"; it now gives one
message for both refusals and keeps its code `telegram_already_linked` (its
existing test is unchanged and a new one checks the messages match).

**The webhook.** `POST /api/v1/telegram/webhook` checks
`X-Telegram-Bot-Api-Secret-Token` in constant time before reading the body
(401; 429 after 30 refusals an hour per address), accepts at most 64 KiB of
JSON with a positive integer `update_id`, records each update id once
(`telegram_updates`; a repeat answers `{"ok": true}`), and acts only on
`message` in a private chat from a person whose chat id is the sender's id,
whose text is exactly `/start` or `/start <payload>`. Everything else is
acknowledged and ignored, so Telegram does not resend it and nothing
changes. 20 attempts an hour per Telegram account (keyed by a hash of the
id, so the rate-limit table does not hold Telegram ids). The bot's answer
travels in the webhook response (`{"method": "sendMessage", ...}`), so
linking makes no outbound call to Telegram. The path is the first entry in
`CSRF_EXEMPT_PATHS` (SEC-6): the parametrised test that listed it among
paths that must *not* be exempt now lists `/api/v1/telegram/webhook/`
instead, and `test_every_exempt_path_is_an_exact_existing_route` now reads
the API's routes from the OpenAPI paths, because `app.routes` lists the
`/api/v1` router as one nested entry and the test had been passing without
looking at any API route.

**The switch.** `MARKX_TELEGRAM_LINKING_ENABLED` (default `false`) with
`MARKX_TELEGRAM_BOT_USERNAME` and `MARKX_TELEGRAM_WEBHOOK_SECRET` (SecretStr,
32 to 256 characters), all three required together or the API refuses to
start; staging and production also refuse a webhook secret containing
`dev-only`, `test-only` or `change-me`. Off: the link is 503
`telegram_linking_unavailable`, the webhook 404 (it does not exist), the Mini
App link 503 too, and the page offers no button. **Disconnecting always
works.** Environment variables rather than a `settings` row because turning
it on needs the secret and the bot, which are server configuration, and a
staff switch could not supply them.

**Notifications.** Linking only sets `users.telegram_id`; it sends nothing.
A message reaches Telegram only while `MARKX_TELEGRAM_PUSH_PROVIDER` is
`bot_api` (D-092); the status's `telegram_messages_on` says whether any
provider carries messages, so the page never implies messages that are not
sent. Connecting does not resend anything recorded `skipped` or
`unavailable` before; disconnecting makes the next delivery `skipped` /
`no_telegram_linked`. A manual resend is a separate task.

**Schema (migration `0017`).** `telegram_link_tokens`, `telegram_updates`,
`users.telegram_linked_at` (set exactly when `telegram_id` is, by a new
constraint; existing linked rows were given their `updated_at`) and
`users.telegram_unlinked_at` (so the page can say "disconnected"). Two test
helpers that arrange a linked person by writing `telegram_id` directly now
set `telegram_linked_at` too; no assertion changed. Retention: update ids
after 7 days, links 30 days after creation, in `retention.prune`, as fixed
periods (neither table is a record anyone reads later).

**Who may do it.** Every route acts on the caller's own account; none takes
another person's id. Starting a link needs a customer session (a staff
session gets 403 `customer_session_required`). Store owners cannot see or
change a team member's connection, and no store screen shows one. The audit
log records `telegram.link_requested`, `telegram.linked` (method
`bot_link` or `mini_app`), `telegram.link_refused` (reason) and
`telegram.unlinked`, never a token or Telegram id.

**The web app.** The account page's "Telegram messages" section shows every
state; while a link waits it polls `GET /me/telegram` every three seconds and
when the tab regains focus, and announces "Telegram is connected." in a
live region. The link opens with `rel="noopener noreferrer"`, and only a
`https://t.me/<name>?start=<token>` link is ever shown. The seller overview
has a card with the person's own state and a link to the section.

**Not done.** No bot, no `setWebhook`, no real message; the reply-in-response
form and the update shapes are as known when written and must be re-read
against Telegram's documentation when the bot is connected. No staff tool
to disconnect someone; no Telegram sign-in on the web; no resend of old
notifications; the bot's texts need a native speaker's review.

## D-094 Off-server backup and disaster recovery: signed, encrypted sets of the database and the files, provider-independent, not connected

**Follows** blueprint F.6 ("the buckets need their own protection"), F.13
and H.2 (a nightly encrypted dump away from the server, a monthly restore
drill, 24 hours of loss and 4 hours to restore at most), G.11 ("encrypted
before they leave the database host"), H.7 (a restore drill before launch).
**Replaces** the backup part of D-063 and the backup service of D-091.
**Built and tested locally and in CI against PostgreSQL 17 and MinIO only.
No destination, bucket, account or key exists for a real server; nothing was
uploaded anywhere outside this machine and CI; MarkX has NO off-server backup
until the founder's decisions F-16, F-19 and F-20 are made and the
activation steps in `docs/runbooks/backup-and-restore.md` are done.**

**What the audit said, checked against the code** (`infra/backup/*.sh` at
`866a184`):

| Finding | Verified |
| --- | --- |
| Dumps stay on the same server | **True.** `scheduled.sh` wrote to `MARKX_BACKUP_HOST_DIR` only; nothing copied them away |
| AES-256-CBC without authentication | **True.** `openssl enc -aes-256-cbc -pbkdf2`; the `.sha256` beside the file catches accidents, not someone who changes both |
| The key on the same host | **True.** `/etc/markx/backup.key`, beside the database passwords; the same passphrase decrypts every dump |
| Stored files not backed up | **True.** F-14 open; no code copied either bucket |
| Failures not brought to a person | **True.** Only an `unhealthy` container and a log line; the watch knew nothing of backups |
| Restore testing does not prove database-plus-file recovery | **True.** `drill.sh` restored the database only and compared row counts |

**The design** (`apps/api/markx/backup/`, `python -m markx.backup`):

- **A backup set** is the dump and every stored file, taken together, with a
  signed manifest written last. Nothing is a recovery point until that
  manifest exists, verifies and says `complete`. Layout, steps and the
  operator's view: the runbook.
- **Consistency.** One REPEATABLE READ transaction exports its snapshot;
  `pg_dump --snapshot` dumps that instant, and the same transaction reads
  every table's row count and every file reference. Files are listed after
  the snapshot. Because uploads write the file before the row commits and
  nothing deletes stored files (D-062, D-090), every referenced file exists
  by then; a missing one makes the set `incomplete` (refused by a restore
  by default, alerted). **A future feature that deletes files must delete
  the row first.**
- **Dump checks.** Exit status; a custom-format archive; `pg_restore
  --list` reads the table of contents and finds every table of the
  snapshot, `alembic_version`'s data included. The plaintext streams into
  the encryption and `pg_restore --list` and is never written to disk.
  Credentials travel only in the child's PG* environment, never an argument;
  the child gets no MARKX_* or AWS_* variable.
- **Encryption: public-key, authenticated (MXB2).** X25519 + HKDF-SHA256 to
  a per-file key, AES-256-GCM in 1 MiB chunks with the STREAM nonce (counter
  and last-chunk flag), the header authenticated in every chunk, from the
  `cryptography` library already in use. **Why public-key:** the server
  must encrypt every night but should not be able to decrypt; with a
  symmetric key on the server, the server's compromise or loss is the
  backups' too. The server holds only the recipient's public key; the
  **recovery key** (private) is kept off the server by the founder (F-19).
  Because the public key lets anyone encrypt, authorship comes from an
  **Ed25519-signed manifest** recording every piece's SHA-256; a restore
  checks the hash, decrypts the whole piece once without using it, and only
  then writes. `age` was considered (same construction, but one more
  binary and a second format to verify); GnuPG (heavier, harder to use
  correctly). A cloud key service was not invented: none exists, and the
  founder chooses custody.
- **Never the application's keys.** `MARKX_SECRET_KEY` and
  `MARKX_ENCRYPTION_KEY` are not read by `markx.backup.crypto` (a test
  says so). Keys are separate files made by `keygen`, labelled by kind so a
  public key cannot be loaded as a private one; private key files readable
  by others are refused; `keygen` never overwrites.
- **Files.** Both buckets are listed (read-only by construction: the
  source interface has `list` and `open` only), each object encrypted to a
  blob named by an HMAC of its content (keyed by the signing key, so a name
  reveals nothing). Unchanged objects (same size and ETag) are not read
  again; existing blobs are not uploaded again; an interrupted run's blobs
  are reused by the next. The encrypted index keeps each file's store,
  key, size, SHA-256 and type: private files are restored only to the
  private target. Symbolic links and unsafe keys in a folder source are
  skipped and counted, never followed.
- **Destinations.** One interface (`destination.py`): `S3Destination` for
  any S3-compatible bucket (S3, R2; MinIO in tests) with its own
  credentials, never the machine's; `LocalDestination` for a laptop. Every
  upload is verified by size and a full read-back hash. A failed multipart
  upload is aborted; parts left by a killed process are aborted after a day.
  The destination is refused if it lists without credentials. Errors are
  `DestinationUnavailable` (retried) or `DestinationError` (a setting);
  neither carries a credential.
- **Refusals on staging and production** (`config.py`): a destination that
  is `local` or `minio`, or not https; a backup bucket that is a file
  bucket; and, for the service, file stores read from a folder or MinIO,
  the file stores' key reused for backups, no explicit retention, no keys,
  no release. MinIO is never reported off-server.
- **Restore** (`restore.py`): into a NEW database (refuses one that exists,
  the source's own name, a system database, a confirmation that does not
  repeat it) and EMPTY file targets that are not the live buckets. Then it
  checks the migration version, every table's row count against the
  snapshot's, invalid indexes and unvalidated constraints, the audit log's
  protection, every file's checksum after reading it back, every database
  reference against the restored files, and that the private target cannot
  be read anonymously. A failed database restore drops only the database
  it created.
- **Drill** (`drill.py`): backup, deep verification, restore into a new
  database and disposable targets (MinIO buckets in CI; a temporary folder
  on a server, so no bucket is bought), comparison, then seven injected
  faults on a copy under a separate prefix (a changed dump byte, a cut index,
  a missing manifest, an edited manifest, a missing blob, a wrong recovery
  key, and a restore of an altered set that must create nothing). It
  removes only what it created and records the result.
- **Concurrency.** A PostgreSQL advisory lock and a file lock; a second run
  is `skipped`. Runs left `running` by a dead process are marked
  `abandoned` by the next one.
- **Failures** never delete anything at the destination: the last good set
  stays. The attempt's folder (encrypted pieces, tool output, a report
  with the error and its trace, kept on the server only) moves to
  `failed/`. Transient failures are retried by the service (3 attempts,
  10 then 20 minutes apart by default); each attempt is its own record.
- **Retention** (`retention.py`): founder-set days and minimum sets, the
  newest complete set always kept, only this service's signed manifests
  trusted, blobs collected only when unneeded and older than 48 hours, and
  none at all if a kept set's blob list cannot be checked.
- **Monitoring.** Migration `0018`: `backup_runs`, written by the backup
  service as the schema owner; the application role may read it only (a
  test). The worker's watch adds `backup.failed`, `backup.incomplete`,
  `backup.stale` (no verified **off-server** set within 26 hours, or none
  ever), `backup.drill_failed` and `backup.drill_overdue` (35 days), on
  staging and production (`MARKX_BACKUP_MONITORING`). **An alert generated
  is not an alert received:** it reaches a person only once the Telegram
  alert group is configured (F-18); until then, the log.
- **Deployment.** The API image gains a `backup` stage (the same code plus
  PostgreSQL 17.12's client tools copied from the `postgres:17.12-bookworm`
  image; the default `postgres:17.12` tag is now Debian trixie, whose C
  library the bookworm-based Python image lacks). The Compose `backup`
  service runs `python -m markx.backup serve` as uid 999, read-only root,
  on the backend and egress networks, with the public and signing keys
  mounted and the recovery key absent; `deploy.sh check` refuses a recovery
  key in `/etc/markx`; `deploy.sh` takes a set before every migration.
- **Old format.** `backup.sh`, `scheduled.sh` and `drill.sh` are removed:
  no new CBC dump is ever made. `restore.sh` is kept as
  `restore-legacy-cbc.sh` so a dump in the old format never becomes
  unreadable. MarkX was never deployed, so no real dump in that format
  exists; one on a laptop can be restored and backed up again in MXB2.

**Tested** (commands and results in `docs/DEVELOPMENT_STATUS.md`): 33
encryption and signature tests (every size across chunk boundaries, a bit
changed anywhere, truncation at every boundary, extension, chunks swapped,
dropped or repeated, a foreign header, wrong keys, key rings, legacy files,
key files), 16 configuration tests, 11 retention tests, 16 monitoring tests,
22 PostgreSQL-and-MinIO recovery tests (a full database-and-file recovery
from data made through the API, incremental runs, a missing file, a source
file that does not match its ETag, a key rotation, an unmigrated database, a failed,
empty or foreign dump, an unreachable destination, an interrupted backup
resumed, overlapping runs, a dead run, a public or missing bucket, a
read-back mismatch, an aborted multipart upload, path and link escapes,
every restore refusal, tampering at the destination, a wrong key, the drill
and a failed drill); the CI drill on the demo data; the drill inside the
built `backup` image; and the production rehearsal.

**Not done, and not claimed:** no real destination, bucket, key or alert
channel; no restore on a real server; no measurement of the 4-hour target
on real data volumes; no object lock or versioning on a backup bucket (part
of F-16); files larger than memory are streamed for backup but a restore
reads one file into memory (MarkX stores pictures of at most 20 MB); the
weekly copy to the founder's drive (blueprint F.13) is the founder's choice
of destination and is not automated (a second destination can be a second
`backup` service with another `backup.env`).

## D-095 How the founder works with Claude: the planning Project, the mobile app, branches and reports

**The founder's decisions** (19 November 2026). **Decided.** They concern
how work is asked for, done and reported; they change no code and no
product rule.

(a) A separate Claude Project is the architect and planning hub, and
ChatGPT no longer writes prompts.

(b) The founder works only from the Claude mobile app. Claude Code pushes
its own branches, and `main` changes only on a merge the founder approves.

(c) Each task comes as one prompt in plain words.

(d) Every report is also given as one Markdown file to download.

**Where it is applied:** `AGENTS.md` section 4 (every session starts from
the latest `main` and works on its own new branch; never merge into `main`
without the founder's written approval) and section 4a (the founder's
working rules, including updating `docs/DEVELOPMENT_STATUS.md`,
`docs/DECISIONS.md` and `docs/HANDOFF.md` at the end of every session
before reporting); `CLAUDE.md`. Until this decision every session worked on
`claude/project-scaffold`, which was merged into `main` through pull
request #1 on 19 November 2026.

## D-096 Backup trust hardening: the server cannot delete a backup, an object lock, verified reuse, drills and restores away from the server

**Engineering decision, 19 November 2026** (the independent audit's BK-1,
BK-2, BK-3, BK-6, BK-7 and BK-17; `docs/reports/2026-11-19-independent-audit.md`
sections 3 to 6, 17 and 20). **Built and tested with PostgreSQL 17.12 and
MinIO only. Nothing is connected; no account, bucket or key exists.**
Several parts are **PROVISIONAL**: listed at the end, each for the founder.

**What changed, and why.**

- **BK-1. The server can no longer delete backups.** The backup service
  (`run`, `serve`) only adds, reads and lists; its key is given no delete
  right. `serve` no longer applies retention after each set. Retention is
  `python -m markx.backup prune`, which refuses to run on staging and
  production: it runs on a separate machine with its own key that may
  delete. It removes every version of an object (so space is really freed
  on a versioned bucket and no delete marker is left), leaves what an
  object lock still holds and says so, leaves a set whole when its manifest
  is still locked, and also removes objects already hidden behind a delete
  marker once they are older than the retention period (never what a kept
  set needs). It trusts only the signer PUBLIC key it is given and takes no
  lock: a running backup is protected by the 48-hour blob grace period.
  **The alternative**, the storage provider's own expiry ("lifecycle")
  rules, is documented in the runbook: simpler, but they delete by age
  alone, without knowing which sets are complete or which blobs a kept set
  still needs, so they must never expire objects under `objects/`.
- **BK-1. Object lock.** On staging and production the backup bucket must
  have S3 Object Lock in COMPLIANCE mode with a default retention of at
  least `MARKX_BACKUP_OBJECT_LOCK_MIN_DAYS` (30); `serve` refuses to start
  otherwise (`destination.py`, `check_access`). Every object the server
  writes is checked to be locked after its upload. A blob that a new set
  reuses has its lock lengthened (COMPLIANCE never allows shortening, and
  the server's key cannot), so every object of the newest set stays locked
  at least the minimum period. A laptop and the tests ask for the same
  check with `MARKX_BACKUP_REQUIRE_OBJECT_LOCK=1`.
- **BK-3. A damaged upload is never reused.** The blob ledger
  (`blob-ledger-<keys>.json` in the working folder) records each blob whose
  full read-back matched: its encrypted size, the SHA-256 of its encrypted
  bytes and the destination's own fingerprint (ETag) right after the check.
  A later run reuses a blob only when the destination lists it with that
  size and that ETag; otherwise it uploads it again, over it (the server
  cannot delete it, so "treat it as never uploaded" is the fix). A blob
  whose check fails is dropped from the ledger at once; even an interrupted
  run keeps the ledger. Every index entry now records its blob's
  `ciphertext_bytes` and `ciphertext_sha256`; `verify` checks each blob's
  size without decrypting, and `verify --deep` reports a blob uploaded
  again since a set (its bytes differ, it still decrypts to the file). A
  set is written `complete` only when every one of its blobs passed in
  this run or is unchanged since it did (`files.verified_blobs`).
- **BK-2. Drills and restores never run on the server.** `verify`,
  `restore`, `drill` and `prune` refuse to run when `MARKX_ENV` is staging
  or production: the recovery key must never come to the server. `drill
  --from-destination` is the monthly drill on a separate, throwaway
  recovery machine: it takes no backup, reads the newest complete set (or
  `--set`) with the bucket's READ-ONLY key, restores it into a temporary
  folder and a throwaway PostgreSQL, and puts a LOCAL copy of the set
  through the seven injected faults, so it never writes to or deletes from
  the bucket. `infra/backup/recovery-host.sh` starts that PostgreSQL: the
  pinned 17.12 image, `--network none`, reached through a Unix socket only,
  no secret. The drill's report is entered on the server with `python -m
  markx.backup record-drill --report FILE`, which checks that the set it
  names exists and verifies, so `backup.drill_overdue` keeps working.
- **BK-6. A restore cannot harm the recovery machine.** `pg_restore` runs
  logged in as `markx_migrator` (the owner), never the superuser, and the
  restored copy is checked as `markx_migrator` and `markx_app`. A `SET
  ROLE` would not do: the archive could `RESET ROLE`. The superuser only
  checks the target is new, runs bootstrap.sh (our own SQL) and drops a
  database the restore made. Proved by a test: a forged, correctly signed
  set whose restore runs `COPY ... TO PROGRAM` runs it as the superuser and
  is refused as the owner. Found while doing it: bootstrap.sh's default
  privileges would have given `markx_app` UPDATE and DELETE on every table
  the owner creates during the restore (the archive's grants only add), so
  the audit log would have lost its protection. The restore now clears
  those default privileges in the new, empty database first; the archive
  restores the source's own at its end. A test compares every table's
  owner and grants with the source's. Sets made after a suspected break-in
  on the server must not be trusted (runbook).
- **BK-7. A restore never resets a password.** When the MarkX roles
  already exist on the target PostgreSQL, the restore never passes
  `MARKX_DB_*_PASSWORD` to bootstrap.sh, and refuses to run when they are
  given. It logs in with `MARKX_RESTORE_OWNER_PASSWORD` and
  `MARKX_RESTORE_APP_PASSWORD` (else bootstrap's defaults, right on a
  throwaway container). The BK-2 refusal alone does not cover this: a
  machine with `MARKX_ENV` unset could still point `PGHOST` at production.
  The production rehearsal's drill now passes those login passwords
  instead of the reset ones.
- **BK-17. Least privilege in the tests and CI.** `infra/backup/minio-least-privilege.sh`
  makes five MinIO users (development values only): the server's backup
  key (add, read, list, lengthen a lock, abort its own uploads; no delete),
  the recovery machine's key (read and list), the retention key (read, list,
  delete every version), the file stores' reader, and a key for the drill's
  own `markx-drill-*` buckets. The tests' file buckets are named
  `markx-test-files-*` so the reader's policy can name them (MinIO matches a
  wildcard at the end of a bucket name only). CI's PostgreSQL service and
  client tools are pinned to `postgres:17.12`.

**Not done here, recorded for later.** Moving manifest signing off the
server (a co-signer away from it) would stop a compromised server from
forging sets (audit 3B, BK-6's optional part); it is a later option with
an operating cost, not built. Still open from the backup findings: BK-4
(alerts that work without the server), BK-5 (an off-server escrow of the
application secrets), BK-8 to BK-16 and BK-18; scheduled deep verification
(BK-11) is not built either.

**PROVISIONAL, for the founder to confirm.**

- **P-096-1. An object lock is required on staging and production**
  (`config.py`, `object_lock_required`). It costs storage: nothing can be
  removed before its lock ends, so the bucket holds at least the lock
  period of sets. Confirm with F-16.
- **P-096-2. COMPLIANCE mode, not GOVERNANCE** (`destination.py`,
  `_checked_lock`). Nobody, not even the account owner, can delete a
  locked object early; a mistake costs storage until the lock ends. Confirm
  with F-16.
- **P-096-3. The minimum lock is 30 days** (`MARKX_BACKUP_OBJECT_LOCK_MIN_DAYS`,
  the blueprint's backup period, H.2). Confirm with F-16 and F-20.
- **P-096-4. The bucket's default retention should be the minimum plus 14
  days** (44), so that a reused blob's lock is lengthened about once every
  two weeks instead of every night (each lengthening is one request per
  blob). A runbook recommendation, not enforced. Confirm with F-16.
- **P-096-5. Retention is run by hand, monthly, at the drill**, from the
  recovery machine with the retention key (`prune`, dry run first), rather
  than by the provider's expiry rules. Confirm with F-20.
- **P-096-6. The recovery machine is the recovery-key holder's own laptop**
  by default; a free CI runner works the same way (CI does it on every
  push with test keys), but holding the real recovery key in a CI system
  is a custody choice for F-19.
- **Cloudflare R2 is NOT VERIFIED.** R2 has its own "bucket locks"; whether
  they answer the S3 object-lock calls this code makes, whether a per-object
  lock can be lengthened there, and how R2 answers a delete of a locked
  object are all UNKNOWN. Nothing contacted R2. If R2 does not answer the
  S3 call, the service refuses an R2 bucket on staging and production, by
  design. To test once F-16 is decided (runbook, "To test on the real
  provider").

**Where:** `apps/api/markx/backup/` (`config.py`, `destination.py`,
`runner.py`, `retention.py`, `database.py`, `restore.py`, `drill.py`,
`__main__.py`); tests `apps/api/tests/storage/test_backup_trust.py`,
`apps/api/tests/unit/test_backup_commands.py` and the least-privilege
fixtures in `apps/api/tests/storage/test_backup_recovery.py`;
`infra/backup/minio-least-privilege.sh`, `infra/backup/recovery-host.sh`;
`.github/workflows/ci.yml`; `infra/production/rehearsal/rehearse.sh`;
`docs/runbooks/backup-and-restore.md`; `docs/DEPLOYMENT.md`;
`infra/production/env/backup.env.example`.

## D-097 Checks run once per change, documents-only changes skip the heavy jobs, a narrower secret-scan allow-list

**Engineering decision, 20 November 2026.** CI configuration, the
secret-scan settings, `.gitignore` and documents only: **no product code
changed, nothing was deployed, no account was created, no money was spent.**

**The problem.** `ci.yml` ran on `push` (every branch) and on
`pull_request`. A push to a branch with an open pull request therefore
started the full CI twice (pull request #4: runs 144 and 145 on `adf128a`,
146 and 147 on `3085cc7`, 148 and 149 on `f7df3ec`). The concurrency group
was `ci-${{ github.ref }}`, which is `refs/heads/<branch>` for the push and
`refs/pull/<n>/merge` for the pull request: two different groups, so
neither run could cancel the other.

**What changed, and why.**

- **One run per change (`ci.yml`).** CI runs on pushes to `main`, on pull
  requests and by hand (`workflow_dispatch`). A push to a branch without a
  pull request no longer runs it: open a pull request or start it by hand.
- **Grouped by pull request number.** Runs of one pull request share the
  group `ci-pr-<number>` with `cancel-in-progress`, so a newer push cancels
  the older run of that pull request. Every other run (main, by hand) has a
  group of its own (`ci-run-<run id>`) and is never cancelled. **Not by
  branch name**: on a public repository a fork's pull request may come from
  a branch also called `main`, and a branch-named group would let it cancel
  main's runs.
- **Documents-only changes skip the heavy jobs.** A new first job, "What
  changed (documents only?)", compares the change with its base (a pull
  request: its base commit; a push to main: the commit before the push;
  `git diff --no-renames`, so a file moved into `docs/` also counts where it
  left). A change is documents only when every changed file ends in `.md`
  and is outside `apps/`, `infra/` and `.github/`. Then API, Web app,
  Containers and the Production stack rehearsal are skipped. Anything it
  cannot decide (started by hand, a new branch, a base it cannot find, an
  empty comparison) counts as code: every job runs. **The Security job
  (Gitleaks, pip-audit, npm audit) always runs**, documents included,
  because a document can leak a secret as easily as code.
- **Documents a test or check reads.** Searched before writing the rule:
  no test, script, Dockerfile or workflow reads the text of any `.md` file
  (they are only named in comments and messages, e.g.
  `docs/runbooks/rollback.md` in `deploy.sh`; `test_provisional_decisions.py`
  reads code under `markx/`, not `docs/DECISIONS.md`). The one reader is
  Gitleaks, which always runs. The `.md` files inside `apps/`
  (`apps/web/AGENTS.md`, `apps/api/migrations/README.md`) are inside the
  images' build folders, so they count as code. The rule keeps a list,
  `read_by_checks`, for any document a check reads in future.
- **A single "CI result" job** runs last, always. It passes only when "What
  changed" and Security passed and each heavy job passed (code change) or
  was skipped (documents-only change). A failure, a cancellation, or a
  heavy job skipped on a code change fails it. A documents-only pull request
  therefore shows a passing result instead of waiting.
- **A code change still runs every job it ran before**: API (with both
  recovery drills), Web app, Security, Containers and the Production stack
  rehearsal. Nothing in those jobs changed.
- **Browser journeys (`journeys.yml`)** run on pull requests and on pushes
  to `main` that touch `apps/`, `infra/` or the workflow (the same file
  filters as before), and by hand on any branch. A pull request's runs
  share the group `journeys-pr-<number>` (by number, never by branch name),
  so a newer push cancels the older run of that pull request: one run per
  push. A run on main has its own group (`journeys-main-<run id>`), so a
  newer run never cancels it, running or waiting; started by hand on
  another branch, a newer run of that branch supersedes the older. A push
  to a branch without a pull request does not start them.
- **Changed before merging, at the founder's request (20 November 2026).**
  The first version of this pull request ran the journeys only on `main`
  and by hand. The founder withdrew that instruction: a pull request that
  changes the screens could then be merged before they ran. They start by
  themselves on such pull requests again, as described above.
- **W-1, the secret-scan allow-list (`.gitleaks.toml`).** The independent
  audit (section 9: "Gitleaks line-level allowlist can hide real secrets")
  found that `regexTarget = "line"` ignored a whole line containing
  `dev-only`, `test-only` or `not-a-real-secret`, so a real key with a
  "dev-only" comment beside it was never reported. The allow-lists now test
  each pattern against the value Gitleaks found (`regexTarget = "secret"`),
  and the three exact values (the development encryption key, the tests'
  Fernet key, the public Turnstile test site key) are anchored with `^...$`.
  Proved in a throwaway repository: a random key on a line commented
  `# dev-only` was hidden by the old file and is reported by the new one;
  `markx-dev-only-token-...` and the development key are still allowed.
  Over the whole history (every branch and pull request) the new file finds
  nothing.
- **`.gitignore`** ignores `*.pem` and `*.key` (TLS, backup and signing
  keys). No tracked file matched either pattern.

**The whole-history secret scan (20 November 2026).** Every branch and
every pull request's commits fetched (8 branches, pull requests #1 to #4;
140 commits, 4 of them merges). Gitleaks 8.28.0 and TruffleHog 3.90.0 from
their GitHub releases, checksums verified.

- Gitleaks, default rules only, config kept outside the repository: 7
  findings, all `generic-api-key`, all one of two labelled values: base64
  of `test-only-not-a-real-key-32bytes` (the tests' Fernet key, 6) and of
  `dev-only-encryption-key-32bytes!` (the development key in
  `markx/core/config.py`, which staging and production refuse, 1). **Not
  secrets.**
- Gitleaks with the repository's `.gitleaks.toml`, old and new: no leaks.
  Gitleaks reported 135 commits scanned where Git has 136 non-merge
  commits; two of them only delete lines and cannot add a secret. Which
  one Gitleaks did not count: UNKNOWN.
- TruffleHog (`--no-verification`, so no candidate value was sent to any
  provider): 0 verified, 2 unverified, both the test URL
  `https://user:pass@...example` in tests that check such addresses are
  refused. **Not secrets.**

**Not verified.** Whether `main` has branch protection with required
checks: UNKNOWN (no tool here reads it). Either way: GitHub counts a skipped
job as passed, and "CI result" gives one name to require. The
documents-only path ran locally against real commits; it runs on GitHub
only once a documents-only pull request or push to main exists.

**On GitHub (pull request #5, `ec64a85`):** the branch push started no
run; opening the pull request started one, CI 151, which passed every job
(What changed found code, so all ran, the production rehearsal included);
Browser journeys 28, started by hand on the branch, passed. The next
commit (`65d1669`, documents) started one run again, CI 152, which passed
every job. The commit that makes the journeys start on pull requests
again (`45f4f35`): CI 153 and Browser journeys 29 passed. (Added by D-098:)
merged into `main` on 20 November 2026 as `d01fef7`; CI 154 and Browser
journeys 30 passed on `main` there.

**Where:** `.github/workflows/ci.yml`, `.github/workflows/journeys.yml`,
`.gitleaks.toml`, `.gitignore`; `docs/SETUP.md` and `docs/ARCHITECTURE.md`
(the journeys and CI triggers).

## D-098 One staff conflict-of-interest check for every staff decision (H1); phone numbers in any digits (B-3)

**Engineering decision, 20 November 2026.** Follows the blueprint (C.5:
nobody decides their own case; P.1: one stored form of a phone number).
Product code, tests and documents. **Nothing deployed, no account created,
no money spent.** Branch `claude/staff-conflict-phone-fixes-qkiixq`, from
`main` at `d01fef7`.

### H1: staff conflict of interest

**The problem (independent audit, §8, §9, §11; earlier finding b).** The
check `_refuse_own_seller` (`sellers/service.py`) was used only by seller
verification. A member of staff who belonged to a store could still decide
its disputes, hide or publish its reviews, take its offers down or restore
them, close reports about it, dispatch its orders and reissue its handover
codes; a member of staff who placed an order could do the same to their own
order (reissuing one's own handover code resets the lock after wrong
codes). A refused attempt was not recorded anywhere.

**What changed.** One shared check, `refuse_conflict` in
`markx/trust/conflict.py`. Each staff action calls it as soon as it has
found the thing it acts on and before it changes anything. It refuses:

- an active member of any store concerned (`conflict_of_interest`, the
  existing code and message: "You belong to this seller, so another staff
  member must decide.");
- the buyer of the order concerned (`conflict_own_order`: "You placed this
  order, so another staff member must handle it.");
- the author of the review or report concerned (`conflict_own_submission`:
  "You wrote this yourself, so another staff member must handle it.").

Each refusal is HTTP 403 and is written to the audit log as
`staff.conflict_refused` (the actor, the thing, `after.attempted` the
action, `after.reason` `own_store`, `own_order` or `own_submission`, and
the store). The row is written in its own short transaction
(`session_scope`, as `notifications/delivery.py` does), because the
request itself fails and rolls back. The web app shows the two new codes
in English and Amharic (`apps/web/messages/*.json`; the Amharic wording,
like the rest, awaits a native editor). `_refuse_own_seller` now calls the
shared check, so seller verification behaves as before and its refusals are
recorded too.

**Every staff action covered** (19):

| Action (route under `/admin`) | Store checked | Also refused |
| --- | --- | --- |
| Seller: request documents, approve, reject, verification level, recheck, suspend, reinstate (`/sellers/{id}/...`) | the seller | (already checked before D-098; now recorded) |
| Seller document review (`/sellers/{id}/documents/{doc}/review`) | the seller | (already checked; now recorded) |
| Offer takedown, restore (`/offers/{id}/remove`, `/restore`) | the offer's seller | |
| Staff dispatch (`/orders/seller-orders/{id}/dispatch`) | the seller order's seller | the order's buyer |
| Reissue handover code (`.../reissue-code`) | the seller order's seller | the order's buyer |
| Resolve a problem (dispute) (`.../resolve-problem`) | the seller order's seller | the order's buyer |
| Moderate a review, publish or hide (`/reviews/{id}/moderate`) | the reviewed seller | the review's author |
| Resolve a report, one or all on its target (`/reports/{id}/resolve`) | the store of the reported offer, store or review; for a product, the store that proposed it | every reporter of the reports closed, and the author of a reported review (P-098-2) |
| **Not in the audit's list:** remove a picture (`/catalog/images/{id}/remove`) | the store whose real photo it is (none for a catalogue picture) | |
| **Not in the audit's list:** approve, archive (reject), merge a product (`/catalog/products/{id}/...`) | the store that proposed or owns it (both products of a merge) | |

**Searched and not covered, with the reason.** Every mutating route behind
`require_staff` was listed from the routers. The rest decide nothing about
a particular store, order, offer or review: categories, attributes,
brands, creating catalogue products and pictures, restricted terms,
delivery zones and rates, search synonyms, settings, staff accounts
(`/admin/staff`), exports (reading), opening a seller's document (reading,
a five-minute link), and seller invitations (an invitation names a phone
number, not a store; approving the application it leads to is checked).
Editing the text, variants or aliases of a product a store proposed is not
checked either: it is editing, not a decision, and the approval is checked.
Whether the founder wants those checked too: a question, not decided here.

**PROVISIONAL, for the founder to confirm.**

- **P-098-1. No override.** When no other member of staff can act (for
  example only one person holds the role), the case waits. There is no
  "act anyway" path, by instruction. The question is F-21 below
  (`markx/trust/conflict.py`).
- **P-098-2. Whoever filed a report may not close it**, nor a report about
  their own review, so a member of staff cannot report a rival store and
  then action the report (`markx/reports/service.py`). The safest default;
  the founder may prefer to allow it.

**Proof.** `tests/api/test_staff_conflict.py`, 22 tests: for each action
above the insider (a store member, or the order's buyer, or the author) is
refused with the right code and message, the attempt is in the audit log
with its reason, nothing changed, and an unrelated member of staff is then
allowed; a refusal asked twice is recorded twice; someone removed from the
team is no longer refused. With the check switched off, 22 of 23 tests
(these and the existing `test_a_staff_member_cannot_decide_about_their_own_store`)
fail; the one that passes is the "left the team" test, as it should.

**One existing test changed, not weakened.** Three tests in
`tests/db/test_dispute_contention.py` decided disputes with
`Actor(type="staff", user_id=<the buyer's id>)` ("any real user id will do
here"): the buyer deciding their own dispute, which D-098 now refuses. They
now act as the bazaar's own member of staff (`_staff`); every assertion is
unchanged, and all four tests in the file pass.

### B-3: phone numbers with non-English digits

**The problem.** `markx/core/phone.py` checked the last eight digits with
`\d`, which in Python matches a decimal digit of any script, while every
phone column's database check accepts only `0` to `9`. A number such as
`09١١٢٣٤٥٦٧` (the first two digits plain, the rest Arabic-Indic) passed the
check and the database refused it: a server error (500), at sign-in,
addresses, applications, team members, product requests and the rider's
phone. A number typed entirely in another script was refused with the
ordinary message, which is not helpful either.

**Choice: convert, not refuse** (the friendlier option). Before the number
is read, every decimal digit (Unicode category Nd: Arabic-Indic, Persian,
Devanagari, Bengali, full-width and the rest) becomes the ASCII digit it
stands for; the pattern now says `[0-9]`, so nothing else can reach the
database. Characters that are not decimal digits are refused as before with
"Enter an Ethiopian mobile number" (422): the Ethiopic numerals ፩ to ፱ (no
zero; not used for phone numbers), superscripts, letters. Every place that
reads a phone number goes through `normalize_phone` (searched): code
sign-in, staff sign-in, staff accounts, seller invitations, addresses
(`phone`, `phone2`), seller applications and contact phone, team members,
product requests, the rider's phone (seller and staff dispatch), the SMS
sender (`to_e164`, `phone_reference`) and the development SMS inbox. The
last raised an unhandled error for any bad number; it now answers 422. The
web app does not check phone numbers itself (searched), so nothing changed
there.

**Proof.** `tests/unit/test_phone.py` (new cases; a test builds
`0911234567` in every decimal-digit script Unicode has and checks the
result against the database's own pattern); `tests/api/test_phone_digits.py`,
45 tests, at every entry point above, in Arabic-Indic, Persian, full-width
and the mixed form, each with an Ethiopic-numeral refusal. Run against the
old `phone.py`, these tests fail with the database's check violations on
`users`, `otp_challenges`, `shipments` and `product_requests`.

### Documents

The documents said pull request #5 was not merged, and called the D-096
fixes "on the D-096 branch". Both are merged: #4 as `773bbb6`, #5 as
`d01fef7` (20 November 2026; CI 154 and Browser journeys 30 passed on
`main` at `d01fef7`). Corrected in `docs/DEVELOPMENT_STATUS.md` and
`docs/HANDOFF.md`.

**Where:** `apps/api/markx/trust/conflict.py` (new), the staff services in
`sellers`, `offers`, `orders`, `reviews`, `reports`, `images`, `catalog`;
`apps/api/markx/core/phone.py`, `apps/api/markx/main.py`;
`apps/web/messages/en.json`, `am.json`; the tests named above.

## D-099 Order life-cycle hardening: stalled deliveries go to staff (M6), limits on unanswered holds and a cancellation cool-down (H2), the commission cap applied; a phone-digit test for sign-in limits

**Engineering decision, 20 November 2026.** Follows the independent audit
(`docs/reports/2026-11-19-independent-audit.md`, section 8 and section 17
item 8), D-086, D-087 and D-088. Product code, one migration (`0019`),
tests and documents. **Nothing deployed, no account created, no money
spent, no commission rule created.** Branch
`claude/order-lifecycle-hardening-1djdof`, from `main` at `c70b338` with
the complete history.

### M6: parts on the road or after a failed handover never expired

**The problem (audit §8, confirmed in the code first).** The overdue job
(`cancel_overdue_fulfilment`, D-043) covers only `confirmed` and `ready`. A
part `out_for_delivery` or `delivery_failed` that the shop never moved on
kept its held stock and one of the buyer's open-order places for ever, and
nobody was told. Only the shop can move a part out of these two states.

**What changed** (`markx/orders/stalled.py`, new; `orders/service.py`
`open_order_count`; `ops/checks.py` `stalled_deliveries`):

- Each state has a time limit, counted from the moment the part last
  entered it (its latest status event), so a retry starts the clock again.
  A part on the road is never called stalled before its own promised
  delivery time (rates allow up to 720 hours).
- Once the limit passes, the operations watch reports the part to staff by
  order code: `orders.stalled_on_the_road` and
  `orders.stalled_after_failed_handover` (warnings). Staff follow it up with
  the shop through the orders desk. The part keeps its status; the buyer and
  the shop still see it and can still act (the buyer's code still works, the
  shop can still record a failure, a retry or the return).
- It stops counting against the buyer's open orders. **Safe:** the buyer
  cannot move it on, and no goods, stock or money move. A part that the shop
  returns becomes final and frees the place anyway, so a buyer who refuses
  at the door gains nothing from this.
- **Its stock is never released by the system, and the part is never
  ended by it.** The goods are with a rider, the buyer or somewhere unknown:
  releasing the hold could sell a unit the shop no longer has. A paid part
  must never end undelivered without staff (D-086); since D-087 a payment
  can only be recorded from the handover on, so only a part paid before
  D-087 can be in these states with a payment. The stock comes back when the
  shop records the return (`return_to_seller`) once the goods are on the
  shelf, or leaves the shelf for good when the part completes. Only the
  shop's own stock is held, and only by the shop's inaction: a buyer cannot
  keep a part in either state.
- A paid part after a failed handover is left out of the new check: it is
  already reported a day after the failure by `orders.paid_delivery_failed`
  (D-086), so staff are not told twice.

**Not built:** a staff button that closes a stalled part or releases its
stock (P-099-7 below). Staff can already dispatch on a shop's behalf and
reissue the handover code (D-065, D-098).

### H2: a rival could keep a shop's stock held

**The problem (audit §8, §9, confirmed).** Every order holds its units at
once, until the shop answers or the response window passes. One buyer
could hold up to 20 units of an offer with a single unanswered order (the
cart's line limit), and order, cancel and order again with no limit. The
only bound was three open orders per buyer.

**What changed** (`place_order` in `orders/service.py`, under the buyer's
cart lock, so two checkouts of one buyer cannot both pass):

- **Per offer and per shop:** the units one buyer's unanswered (`placed`)
  parts may hold: at most 5 of one offer and 10 of one shop, all its offers
  together. Refusals: `unconfirmed_offer_limit` and
  `unconfirmed_store_limit` (409), with the limit in the details. A part
  the shop confirmed or declined, or that expired, no longer counts.
- **Cool-down:** a buyer who cancelled 3 orders within 24 hours may not
  place another until the oldest of those is 24 hours old
  (`cancellation_cooldown`, 409, `order_again_at` in the details). Only the
  buyer's own cancellations count; an order counts once however many of its
  parts were cancelled; a shop's decline or an expiry never counts, so a
  shop cannot use declines to block a buyer.
- The web app shows the three refusals in English and Amharic
  (`apps/web/messages/*.json`; the Amharic awaits a native editor, like the
  rest).

**Why per buyer, not one limit for all buyers together (a choice for the
founder to confirm, P-099-3/4).** A limit on how much of an offer all
unanswered orders together may hold would refuse every other buyer once a
rival filled it: it would make blocking a shop's online sales cheaper, not
harder. Per-buyer limits never stop one buyer because of another. Several
accounts working together are bounded by the same limits on each account
(5 units of an offer, 10 of a shop, 3 open orders, 3 cancellations a day),
and each account needs its own verified phone number (D.2). The shop can
also decline suspicious orders, which frees the stock at once. What this
does not stop: many accounts with many phone numbers. A buyer reliability
score (blueprint D.10, Release 2) is the further step; not built.

### The commission cap was stored but never applied

**The problem (audit §11, D-086 §5, D-088 item 1, confirmed).**
`commission_rules.cap_santim` was never read and `fee_charges.cap_applied`
was always false: a capped rule would have charged its full rate.

**What changed.** Applied, not refused:

- Migration `0019` adds `order_items.commission_rule_id` and
  `order_items.commission_cap_santim`, with two checks: a cap is never
  negative, and a capped line names its rule. Both are empty on every
  existing line (no rule exists, D-088); nothing is changed or deleted.
- At placement the line copies the rule and its cap with the rate
  (`commission_rate`, which replaces `commission_bps`), so a later rule
  never changes a placed order (J.8).
- One calculation, `markx/payments/fees.py` `seller_order_fee`, used for
  the estimate the shop sees before confirming and for the fee charged at
  completion: each line's share at its rate, then each rule's cap on the sum
  of the part's lines under that rule. `cap_applied` is now set.
- **Reading of "cap per order"** (blueprint: "an optional cap per order"):
  per seller's part (the thing a shop is charged for), per rule. This is the
  stricter reading for the shop: two phones in one part under a 500 birr cap
  pay 500 birr, not 1,000. The founder may read it differently when setting
  caps (F-10); the code then changes in one function.
- **Commission stays at zero (D-088).** No rule was created; with no rule
  the fee is zero, nothing is copied and nothing reaches the ledger, as
  before. D-088's other mandatory items (a staff tool for rules, fee reversal,
  invoicing, statements, payouts) are still not built.

### Phone numbers in other digits: sign-in limits (pull request #6 review)

A saved test, `tests/api/test_phone_digit_limits.py`, proves that typing the
same number in Arabic-Indic, Persian, full-width or mixed digits is never a
way around: the resend cool-down, the hourly code limit per number, the lock
after five wrong codes (in every style, the right code included), the staff
lock after five failed sign-ins, and the checks that one number is one
account, one staff member (`staff_exists`), one open invitation
(`invitation_exists`) and one team member (`already_member`). No product
code changed for it: D-098 already keys every limit on the stored number.
The test fails with the phone code from before D-098 (8 of 8) and passes on
`main`.

### PROVISIONAL values (THE FOUNDER MUST CONFIRM OR CHANGE THEM BEFORE MARKX GOES LIVE)

Each is a setting in `markx/core/settings_store.py` (the one place), marked
`PROVISIONAL (P-099-n)` there, in its description on the admin settings
screen, and checked by `test_the_new_limits_are_provisional_settings`. Staff
can change each one in the settings screen, audit-logged.

| | Setting | Value | Why this value |
| --- | --- | --- | --- |
| P-099-1 | `orders.out_for_delivery_limit_hours` | 48 hours, never less than the part's promised delivery time | A rider delivery in town is promised within a day (the test zones use 24 hours); two days leaves room for a late rider or a busy day before staff are troubled |
| P-099-2 | `orders.delivery_failed_limit_hours` | 72 hours | A retry or a return normally follows within a day or two; three days covers a weekend. Unpaid parts only; paid ones are already reported after one day (D-086) |
| P-099-3 | `orders.max_unconfirmed_units_per_offer` | 5 units | A household buys one or two of an item; five covers a family or a small office. A buyer who needs more orders them once the shop confirms |
| P-099-4 | `orders.max_unconfirmed_units_per_seller` | 10 units | Two full offers' worth from one shop before it answers; ordinary baskets are far smaller |
| P-099-5 | `orders.cancellations_before_cooldown` | 3 orders | One or two cancellations a day (a changed address, a better price) are ordinary; a third in a day is not |
| P-099-6 | `orders.cancellation_cooldown_hours` | 24 hours | The same day: an abuser is limited to three cancel-and-reorder rounds a day per account |
| P-099-7 | (a rule, not a setting) | A stalled part keeps its stock until the shop records the return or the handover | Releasing it could sell goods the shop no longer has; F-22 asks whether staff should get a button |

**How an honest buyer is affected.** Not at all in ordinary buying. They
meet a limit only by ordering more than 5 of one item or 10 items from one
shop before the shop has answered (they wait for the shop's confirmation,
usually under 30 business minutes, then order the rest), or by cancelling a
third order within a day (they wait until the first of those is a day old).
Each refusal says so in their language, and nothing is held for a refused
order. A buyer whose delivery stalled is helped: that order no longer takes
one of their three open-order places.

**Proof.** Every test below fails on `main` at `c70b338` and passes here,
except the four marked "guard", which check that nothing ordinary changed
and pass on both:

- M6: `tests/api/test_stalled_deliveries.py`, 8 tests (8 fail on the old
  code: no check, and the stalled part still refuses the buyer's next order
  with `too_many_open_orders`).
- H2: `tests/api/test_stock_hold_limits.py`, 7 tests (4 fail on the old
  code: 6 units accepted, a fourth order accepted after three cancellations;
  3 guards: other buyers unaffected, a confirmed or declined order frees the
  units, an ordinary buyer is never paused).
- Cap: `tests/unit/test_fees.py`, 7 tests (the module is new);
  `tests/api/test_commission_cap.py`, 5 tests (4 fail on the old code: the
  fee charged was 1,185 birr instead of the 500 birr cap, and the rule and
  its cap were not copied onto the line; 1 guard: an uncapped rule charges
  as before).
- Phone digits: `tests/api/test_phone_digit_limits.py`, 8 tests (8 fail with
  the phone code from before D-098).

No existing check or test was weakened, removed or changed.

**Where:** `apps/api/markx/orders/stalled.py`, `markx/payments/fees.py`
(new); `markx/orders/service.py`, `selectors.py`, `models.py`;
`markx/ops/checks.py`; `markx/core/settings_store.py`, `settings_am.py`;
`migrations/versions/20261120_0900_commission_cap_on_order_lines.py`;
`apps/web/messages/en.json`, `am.json`; the tests named above.

## D-100 Frontend resilience: one safe way to call the API, "try again", error pages in both languages, a network-cut journey, axe in the journeys

**Engineering decision, 20 November 2026.** Follows the independent audit
(`docs/reports/2026-11-19-independent-audit.md`, section 10 and section 17
item 9) and known defect **e** in `docs/DEVELOPMENT_STATUS.md`. The website,
its tests, the browser-journeys workflow and documents only. **The API is
not changed. Nothing deployed, no account created, no money spent.** Branch
`claude/frontend-resilience-errors-g4z33c`, from `main` at `fae2514` with
the complete history.

### The problem (checked in the code first)

Every browser call used `browserApi` (openapi-fetch) or `sendForm`, and
about 20 components awaited them without a `try`. When the connection
dropped, `fetch` threw, the code after the `await` never ran, and the
button or form stayed disabled for good with no message. **Seen on `main`
(`fae2514`) in Chromium:** after "Add to cart" with the browser offline,
the button still read "Adding…" and was disabled 20 seconds later, and
still 5 seconds after the connection came back; no message. A crash's
plain "Internal Server Error" or a proxy's HTML 502 page gave the generic
"something went wrong" at best. There was no `error.tsx` or
`global-error.tsx`: a page whose server render failed showed Next.js's
unlocalized default page.

### What changed

- **One safe call** (`src/lib/api/browser.ts`). `browserApi` keeps the same
  typed client and the same header middleware (the `X-MarkX-Client` header
  and the CSRF token are sent exactly as before; their code is unchanged).
  Around it: every method is guarded and **never throws**; a call is given
  up after **30 seconds** (uploads **120 seconds**, both PROVISIONAL), the
  time limit also covering a body that stops halfway; a failure becomes one
  of two codes shaped like the API's own errors: `network_unavailable` (no
  connection, time-out, unreadable answer) and `server_unavailable` (an
  answer of 500 or more that does not carry the API's error code: a proxy
  page, a crash). The API's own refusals, its 5xx ones included
  (`storage_unavailable`), pass through unchanged. `sendForm` (photos,
  documents) and a new `getSafely` (the staff CSV download) follow the same
  rules. `isConnectionProblem(code)` tells the two apart from refusals.
- **One notice** (`src/components/Resilience.tsx`, `ProblemNotice`). For a
  connection or server failure it shows the shared words ("No connection.
  Check your internet, then try again." / "MarkX could not answer just now.
  Please try again in a moment.", and their Amharic) and a **"Try again"**
  button; inside a form the button sends the form again with what the
  person typed, elsewhere it repeats the call. For the API's own refusals
  it shows the component's words as before, without the button (trying
  again would not help). The alert stays a `<p role="alert">`, so screen
  readers and the journeys read the same element as before.
- **Every part of the website that calls the server uses them** (22
  component files, 104 calls to the server):
  add to cart; the cart (reading it and each change, which keeps the cart
  on screen when a change does not get through); checkout (reading the
  cart, review, place order, new address); the buyer's order buttons and
  problem report; problem messages; reviews; reports; product requests;
  photo uploads and withdrawals; account forms and "sign out everywhere";
  sign out (a connection failure now keeps the person on the page instead
  of sending them home still signed in; any answer from the API leads home
  as before); buyer and staff sign-in; the Telegram connection; the shop's
  check-in, offer rows, order actions, review replies, every seller form
  and opening a document; the product form; every staff form, the staff
  account form, document links, synonym removal and the CSV export. The
  search box's suggestions already caught failures and stay silent by
  design. Four places that used to fail **without any message** now say
  so: the shop's check-in, staff document links, synonym removal and
  checkout's cart reading.
- **Placing an order twice is impossible by retrying.** Checkout keeps its
  idempotency key across "try again" (a new key only after a new review),
  and the API returns the existing order for the same key (G.5). The
  journey proves it with the answer lost after the server took the order.
- **Error pages** in the page's language, never showing the error (no
  message, code, digest or stack): `app/[lang]/error.tsx` (the whole site
  under a language, and a section frame that fails), `(shop)/error.tsx`
  (inside the shop's header and footer), `admin/error.tsx` and
  `admin/(desk)/error.tsx`, `seller/error.tsx` and
  `seller/[sellerId]/error.tsx`. Each has "Try again" (Next.js `retry()`,
  which fetches the section again) and a way back (home, the seller area
  or the staff area), and says "You seem to be offline" when the browser
  knows it is. `app/global-error.tsx` replaces the root layout when even it
  fails: both languages, Amharic first, like the 404 page.
- **The words** live in both message files (`apiErrors.network_unavailable`,
  `apiErrors.server_unavailable`, `errors.tryAgain`, `errors.retrying`,
  `errors.pageTitle`, `errors.pageLead`, `errors.offlineLead`,
  `errors.goSeller`, `errors.goAdmin`); the root layout hands them to every
  page once. `global-error.tsx` cannot read the message files (they would
  go into every page's script), so `src/lib/fallback-text.ts` holds a copy
  that a unit test keeps identical to the message files. The Amharic is
  the engineer's; a native editor has not reviewed it (as for all Amharic
  text, audit §10).

### Tests

- `src/lib/api/browser.test.ts` (14 tests): a dropped connection, a request
  that hangs, a body that stops halfway, a proxy page, a crash's text, an
  unreadable success, the API's own refusals kept, success unchanged, and
  the app header and CSRF token still sent on a change and not on a read;
  the same for uploads and the CSV download.
- `src/components/error-pages.test.ts` (26 tests): every section's error
  page in both languages, with try again and the right way back, without
  the error's message, digest or stack; the whole-site page; the notice;
  the copy of the words equal to the message files.
- `e2e/network-recovery.mjs`, in the browser-journeys workflow after the
  other purchase journeys: add to cart offline; a proxy's 502 page on the
  cart; "Place order" offline (nothing placed); the answer lost after the
  server took the order; "Try again" shows that same order and exactly one
  new order exists; then the API is stopped by the journey itself: the
  error page in English and Amharic with no details, the API started
  again, "Try again" shows the page. The shop then declines the test order
  (a buyer's cancellation would count towards the D-099 cool-down).
  **Against `main` it fails at step 1** (no message; the button stuck).

### Accessibility check in the journeys (axe)

`axe-core` 4.14.0 (released 5 October 2026, no dependencies, pinned
exactly; the newer 4.14.1 was four days old and not taken) runs through
`e2e/a11y.mjs` against the WCAG 2.1 A and AA rules on every page the new
journey visits, the notices and error pages included, and on the main
public pages in both languages; any violation fails the journey. It found
two problems on every storefront page, both fixed: the header's MarkX link
had a label different from its own words (`label-content-name-mismatch`;
the label is removed and the drawn X gets screen-reader text, so it still
reads "MarkX"), and the search field pointed to a suggestion list that was
not there (`aria-valid-attr-value`; now only while the list is shown).
**For later:** the 404 page for an address that matches no route has no
`lang` on its `<html>` (axe `html-has-lang`). Next.js serves it without the
app's layout; the fix (`global-not-found.js`) needs an experimental Next.js
setting, so it is not done here. The other journeys do not yet call the
check; adding it to them is a small follow-up.

### Limits (UNKNOWN or not covered)

- When the connection is lost **while moving to another page**, Next.js
  falls back to a full page load and the browser shows its own offline
  page; only a service worker (PWA, not built) could change that.
- The 30- and 120-second limits are PROVISIONAL; how they suit real
  Ethiopian mobile networks is UNKNOWN until measured.
- A change that reached the server but whose answer was lost is reported
  as "no connection". Trying again is safe for checkout (idempotency key);
  for other actions the API answers the second attempt with its usual
  refusal if the first one already took effect (for example "already
  confirmed"), which the notice then shows.

**Files:** `apps/web/src/lib/api/browser.ts`, `browser.test.ts`;
`src/lib/fallback-text.ts`; `src/components/Resilience.tsx`,
`error-pages.test.ts` and the 22 component files above; the seven error pages;
`src/app/[lang]/layout.tsx`; `SiteHeader.tsx`, `Wordmark.tsx`,
`SearchBox.tsx`; `messages/en.json`, `am.json`; `e2e/network-recovery.mjs`,
`e2e/a11y.mjs`; `package.json`, `package-lock.json` (axe-core);
`.github/workflows/journeys.yml` (one step).

## Decisions that need the founder

**F-01 to F-08 have PROVISIONAL answers (D-083), given at the founder's
request on 18 November 2026: the engineer's guess, which the founder must
confirm or change before MarkX goes live. F-09 and F-10 (raised in D-086)
were decided on 18 November 2026: see D-087 and D-088. F-11 to F-13
(D-089, SMS), F-14 and F-15 (D-090, file storage), F-16 to F-18 (D-091,
deployment), F-19 and F-20 (D-094, backups) and N-1 (D-092, notification
channels) are open and have no provisional answer: the code does the most cautious thing until the founder
decides. F-21 (D-098, staff conflict of interest) has a PROVISIONAL answer
(P-098-1, no override) that the founder must confirm or change. D-099
(order life-cycle hardening) sets seven PROVISIONAL values, P-099-1 to
P-099-7, listed in D-099, and raises F-22, which has a PROVISIONAL answer
(P-099-7). F-23 (raised 20 November 2026, product editing by staff whose
own shop proposed the product) is OPEN with no provisional answer.** Treat this list as part of the launch
checklist. Each item says what the code does, what the engineer recommends
(now the provisional answer) and why, what it blocks, and whether the
founder's approval is required. When the founder decides one, it becomes a
`D-` entry above, this item is removed, and its `PROVISIONAL` marker in the
code and its line in `tests/unit/test_provisional_decisions.py` go.

### F-01 Where sellers' identity documents are stored

- **Provisional answer (D-083):** Cloudflare R2, private and encrypted. Not created: the founder must create the account and confirm before going live.

- **Today (D-090):** the adapters exist for Amazon S3 and Cloudflare R2 (and
  MinIO for laptops and tests), chosen by `MARKX_FILE_STORAGE_PROVIDER`, and a
  real server refuses to start without one of `s3` or `r2`. **No account or
  bucket exists, nothing was configured, and no document has ever left a
  laptop.** Deciding F-01 is now configuration, not code: create the two
  buckets (private for documents, public for pictures), a key scoped to
  them alone, and set the `MARKX_STORAGE_*` values on the server. Copying
  any existing file needs the founder's written approval
  (`scripts/copy_files_to_object_storage.py --execute --founder-approved`).
- **Recommendation:** a private, S3-compatible bucket at Cloudflare R2:
  server-side encryption on, no public access, reached only through the
  existing five-minute signed links. (Written before D-090: "the adapter
  interface does not change, so it is one new class". It is now built.) The blueprint already records R2 as an alternative with
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

- **Provisional answer (D-083):** yes, back to Level 0, business documents kept. Applies when transfer is built; confirm before going live.

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

- **Provisional answer (D-083):** ten digits, as today. Confirm against a real licence before going live.

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

- **Provisional answer (D-083):** every used item, as today. Confirm before going live.

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

- **Provisional answer (D-083):** yes, as today. Confirm before going live.

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

- **Provisional answer (D-083):** the survivor's offer stays. Applies when the merge path is built; confirm before going live.

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

- **Provisional answer (D-083):** the three moderating roles, as today. Confirm before going live.

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

### F-08 How long search logs and rate-limit counters are kept

- **Provisional answer (D-083), implemented:** 180 days and one day, as settings, deleted daily by `retention.prune`. Confirm or change the periods before going live.

- **Before D-083:** kept for ever. `search_queries` gains one row per first
  page of a search (bounded per address by D-059); `rate_limit_counters`
  gains one row per address and window. Nothing deleted either, because
  deleting data needs the founder's written approval (`AGENTS.md`); the
  founder's request of 18 November 2026 gave it, provisionally.
- **Recommendation (PROVISIONAL — FOUNDER MAY CHANGE BEFORE LAUNCH):** keep
  search queries 180 days (enough for two seasons of the zero-result
  report; they hold no name or phone number, but may hold a signed-in
  buyer's id), and delete rate-limit counters a day after their window ends.
  A worker job would do both, and its first run would be reported.
- **Reason:** blueprint H.2 asks that retention periods are set; both tables
  otherwise grow without limit once real traffic arrives.
- **Blocks:** nothing before launch.
- **Founder's approval required: yes**, because it deletes rows.

### F-11 Which SMS provider (blueprint O.23)

- **Today:** none. The adapter is ready (D-089); no real server can start
  without one, so **no production sign-in by SMS is possible**.
- **What the founder decides:** the provider, from its price per message,
  sender-name approval for "MarkX" (and how long it takes), delivery
  reports, a test account, where it processes numbers (blueprint section M:
  nothing leaves Ethiopia with a local provider), and its API documentation.
- **Then the engineer:** writes its `SmsWireFormat` and tests from that
  documentation, configures the four `MARKX_SMS_*` values on the server, and
  tests one real message to the founder's own phone with the founder's
  permission.
- **Founder's approval required: yes** (cost, contract, personal data).

### F-12 What a delivery record keeps about the number, and for how long

- **Today (D-089):** a keyed hash of the number only, and records are never
  deleted. That is the most protective choice and loses nothing yet: support
  can find a number's records by hashing the number they are given.
- **Options:** (a) keep the hash only (today); (b) also keep the masked
  number (`+2519••••4567`) for support screens; (c) keep the whole number,
  like `otp_challenges` does. Separately, a retention period (for example 90
  days, then a daily job deletes older records), as F-08 did for search logs.
- **Blocks:** nothing before launch; retention should be set before real
  traffic.
- **Founder's approval required: yes** (personal data; deleting rows).

### F-13 SMS counting and cooldown details

- **Today (D-089):** the daily budget counts messages, not segments (a login
  code is one segment, so they agree today); the cooldown is 60 seconds and
  is not started by a message the provider certainly refused; the alert
  thresholds are 20% of at least 5 messages in an hour, and 15 minutes
  without a final status.
- **Options:** count segments in the budget once longer SMS notifications
  exist (each segment is billed); a longer cooldown, or a growing one after
  each resend. All are settings or a small change.
- **Founder's approval required: no** for the thresholds; **yes** for the
  budget's unit, which is a spending rule.

### N-1 Which channel carries order alerts: Telegram, SMS or both

- **Today (D-092):** both are built and tested against fakes, **neither is
  connected**. No bot exists (`MARKX_TELEGRAM_PUSH_PROVIDER` is `none` on a
  real server); no SMS provider is chosen (F-11) and
  `notifications.sms_enabled` is OFF. Every alert is in the in-app list
  only. **This is a launch blocker:** a seller who does not keep the
  dashboard open misses new orders, and an unanswered order expires in 30
  business minutes.
- **What the founder decides:** (a) Telegram only (free per message; needs
  the bot, and each seller links Telegram once); (b) SMS only (reaches every
  phone; each alert costs one or two messages; needs F-11 and a budget);
  (c) both, SMS as the fallback for people Telegram cannot reach (what the
  code does when both are on, `notifications.sms_only_without_telegram`), or
  SMS to everyone. Also: the daily notification SMS budget (200 by default)
  and whether buyers get SMS too or only sellers (today: every order alert
  in `texts.ORDER_TEXTS`, buyers included).
- **Then the engineer:** for Telegram, the bot's webhook and linking button
  on the web, `MARKX_TELEGRAM_PUSH_PROVIDER=bot_api`, re-reading the Bot API
  documentation; for SMS, F-11's wire format; then one real alert to the
  founder's own phone with permission, and the activation steps in
  `docs/DEPLOYMENT.md`.
- **Also open:** the duplicate-or-loss trade-off (D-092: Telegram may repeat
  after a crash, SMS may be lost after a crash, never repeated), retention of
  delivery records (with F-12), and a native speaker's review of the Amharic
  texts (blueprint I.3).
- **Founder's approval required: yes** (cost, accounts, personal data).

### F-14 How the stored files are protected against loss (blueprint F.6)

- **Today (D-094):** the backup service copies every stored object of both
  buckets, encrypted, into each backup set, with the database dump of the
  same moment, and restores them into new buckets with every checksum
  verified. **Tested against MinIO only; not connected** (it needs F-16's
  destination). Nothing else protects a file deleted or changed in a live
  bucket between two sets.
- **Still to decide:** whether to also turn on object versioning (S3) or a
  second scheduled copy (R2 has no versioning) on the live buckets, which
  would protect files changed between two nightly sets. Each costs storage.
- **Founder's approval required: yes** (a paid setting and where copies of
  personal documents may live; together with F-16).

### F-15 The pictures' own domain (blueprint F.6)

- **Today (D-090):** a real server refuses to start unless
  `MARKX_PUBLIC_MEDIA_BASE_URL` is an `https://` address on a host other
  than the site's. The web app needs the same origin in `MARKX_MEDIA_ORIGIN`
  (its security policy) at build time.
- **Options:** a subdomain such as `media.markx.et` on the CDN in front of
  the public bucket (R2's custom domain, or CloudFront for S3). The private
  bucket must never get a public domain.
- **Founder's approval required: yes** (DNS and the CDN account).

---

### F-16 Where the backup sets are kept off the server (blueprint H.2, F.13)

- **Today (D-094):** the backup service is built for any S3-compatible
  bucket (Amazon S3 or Cloudflare R2), refuses anything that is not off the
  server on staging and production, and is tested against MinIO. **No
  provider, account or bucket is chosen or created; MarkX has no off-server
  backup.**
- **Since D-096 (PROVISIONAL, to confirm here):** staging and production
  require S3 Object Lock in COMPLIANCE mode on the backup bucket, at least
  30 days, and refuse to start without it; the server's key cannot delete.
  This costs storage for the lock period. Cloudflare R2's own bucket locks
  are NOT VERIFIED with this code: test them before choosing R2.
- **To decide:** the provider (AWS S3 or Cloudflare R2), the bucket's
  location (backups hold personal data: blueprint O.1), confirming the
  object lock, its mode and its period (P-096-1 to P-096-4), and the
  spending. Also whether the blueprint's weekly copy to an
  encrypted drive the founder holds is kept (a second destination).
- **Blocks:** the controlled launch should not start without an off-server
  set, a passed drill and an alert channel (F-18). **Founder's approval
  required: yes** (a paid bucket; where copies of personal data live).

### F-17 The site's domain, its certificate and whether Cloudflare is in front

- **Today (D-091):** the proxy answers on one hostname (`MARKX_SITE_HOSTNAME`)
  with a certificate from `/etc/markx/tls`; the examples use
  `markx.example.invalid`. Nothing is registered.
- **Options:** Let's Encrypt with certbot on the server (the challenge path
  is ready), or Cloudflare in front with an origin certificate (blueprint
  M.2: Proposed), which also needs the real-address snippet and a firewall
  that admits Cloudflare only (`docs/runbooks/tls-certificates.md`). Whether
  `www.` exists and redirects. Whether HSTS later includes subdomains.
- **Founder's approval required: yes** (the domain, DNS, a Cloudflare
  account). Together with F-15 (the picture domain).

### F-18 An outside uptime monitor and error tracking (blueprint F.12)

- **Today:** `/api/v1/healthz/ready`, `/healthz/live` and `/healthz/worker`
  exist for a monitor; none is set up, and a failed nightly dump shows only
  as an unhealthy container. No error tracker.
- **Options:** a free uptime monitor polling the three endpoints and the
  certificate's expiry, alerting the founder's Telegram group; an error
  tracker on a free tier with personal data removed before sending.
- **Founder's approval required: yes** (accounts; error tracking sends data
  out).

### F-19 Who holds the backup recovery key, and where (D-094)

- **Today:** the backups are encrypted to a recovery key whose private half
  never goes on the server. No real key has been made.
- **To decide:** who holds it (the founder, and a second trusted person for
  when the founder is unavailable: blueprint H.6), in which two separate
  places (for example a password manager with emergency access, and an
  encrypted USB key or a sealed printed copy in a safe), and the yearly
  rotation. **Losing every copy makes every backup unreadable, for ever.**
  Keeping it beside the server's passwords would not protect against losing
  both.
- **Founder's approval required: yes.**

### F-20 How long backups are kept (D-094)

- **Today:** staging and production refuse to start the backup service
  without `MARKX_BACKUP_RETENTION_DAYS` (0 keeps everything) and
  `MARKX_BACKUP_RETENTION_MIN_SETS`; a laptop keeps 7 days and 3 sets. The
  newest complete set is never deleted. The blueprint says 30 days (H.2);
  that is not chosen here.
- **Since D-096:** retention no longer runs on the server. It is `prune`,
  run away from the server with its own delete key (PROVISIONAL P-096-5:
  by hand, monthly, at the drill), and it cannot remove anything before
  its object lock ends.
- **To decide:** the days and the minimum number of sets, with the legal
  retention of the personal data in them (the founder's own checks) and
  the storage cost; who runs retention and how often (P-096-5).
- **Founder's approval required: yes.**

### F-21 What happens when no other member of staff can act on a conflicted case (D-098)

- **Today (PROVISIONAL P-098-1):** a member of staff is refused any staff
  action on a store they belong to, an order they placed, or a review or
  report they wrote, and there is no override. If nobody else can act, the
  case waits (a dispute's decision date passes; a takedown or report stays
  open).
- **To decide:** whether that is acceptable for the pilot (for example by
  making sure two people hold each staff role), or whether a second
  person's approval, or the founder's, should be able to unblock it. No
  override is built until the founder decides.
- **Founder's approval required: yes.**

### F-22 Whether staff may close a stalled delivery or release its stock (D-099)

- **Today (PROVISIONAL P-099-7):** a part out for delivery or after a
  failed handover past its time limit is reported to staff and stops taking
  one of the buyer's open-order places, but keeps its status and its stock
  until the shop records the handover or the return. Staff follow it up
  with the shop; they have no button to end it or release its stock.
- **To decide:** whether staff should be able to record "the goods are back
  at the shop" (releasing the stock) or "lost" on a shop's behalf, and with
  what evidence; and the six time limits and caps P-099-1 to P-099-6.
- **Founder's approval required: yes.**

### F-23 May staff edit a product their own shop proposed? (OPEN)

**OPEN.** "May a staff member edit the text, variants, aliases or pictures
of a product their own shop proposed? Today they can. Editing is not
deciding, but product pages are shared by every seller."

- **Today (checked in the code, 20 November 2026):** the D-098 check
  (`_refuse_own_proposal` in `markx/catalog/service.py`) refuses such a
  staff member only for approving, archiving and merging the product.
  Changing its text (`update_product_text`), adding variants
  (`add_variant`), adding or removing aliases (`add_alias`,
  `remove_alias`) and adding catalogue pictures (`add_catalogue_image` in
  `markx/images/service.py`) have no such check; removing a picture checks
  only the shop that took it, and a catalogue picture has none. Every
  change is in the audit log.
- **To decide:** whether these edits should also be refused for a member
  of the proposing shop (as decisions are), allowed but shown to another
  member of staff, or left as they are. Nothing is changed until the
  founder decides.
- **Founder's approval required: yes.**

## Open questions carried over from session 1

1. **The blueprint's file name.** It is committed as
   `MARKX_MASTER_BLUEPRINT.md`, as instructed. Its own first lines still say
   its file name is "All In One MarkX master Blue Print.md". The content was
   not edited, to keep it byte-identical to the upload. On 18 November 2026
   the founder confirmed that "All In One MarkX master Blue Print.md" is the
   blueprint's correct name; the repository's copy keeps its file name until
   the founder asks for anything else.
2. **Blueprint section O, questions 1 to 6** are still open: where production
   personal data may live, AWS credits and region, acceptance of the Proposed
   decisions, and the founder's time. F-01 above is the same question as O.1
   and is the one that now has a deadline.
3. **A licence for the code**, if any. None is granted today.
