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

## D-101 Sign-in with Telegram for everyone (decision SI-1); SMS switched off; the audit's sign-in findings M2, M3, M4; saved tests for one buyer's simultaneous orders

**Founder's decision SI-1, recorded 21 November 2026:** everyone (buyers,
sellers and staff) signs in with Telegram only. SMS is kept, switched off,
as a later backup. Staff keep their existing second step on top of
Telegram. **Engineering decisions below, 21 November 2026.** Follows the
independent audit (`docs/reports/2026-11-19-independent-audit.md`, section
9 and section 17 item 10), D-089, D-093 and N-1. Product code, two
migrations (`0020`, and `0021` for the recycled-number fix in section
2a), tests, one journey and documents. **Nothing deployed;
no bot, token, SMS provider or account created; nothing sent to or
received from Telegram; no money spent.** Branch
`claude/telegram-signin-audit-fixes-q318w6`, from `main` at `b79caab` with
the complete history.

### 1. How a person signs in with Telegram, and why this way

**The choice: the bot's deep link, then Telegram's own "share my phone
number" button.** On the sign-in page the person taps **Sign in with
Telegram**, then **Open Telegram**. On a phone the link
(`https://t.me/<bot>?start=si-<token>`) opens the Telegram app directly;
the person presses **Start**; the bot answers with one button, **📱 Share my
phone number**; they press it and come back to the page, which signs them
in by itself (it asks the API every 2.5 seconds and at once when the tab
is shown again). Nothing is typed. Code: `markx/accounts/telegram_sign_in.py`
(new), routes `POST /auth/telegram/sign-in` and
`POST /auth/telegram/sign-in/check`, `GET /auth/methods`; the page:
`apps/web/src/components/TelegramSignIn.tsx`.

**Why, for Ethiopian mobile phones:**

- **No typing and no SMS.** The person never types a number or a code,
  which is where most sign-in mistakes happen on a small screen; MarkX pays
  nothing per sign-in (an SMS costs money every time, D-089).
- **The number comes from Telegram, already confirmed.** Telegram verified
  it when the account was made; the bot receives it with the account's own
  id. Deliveries need a working number; this is that number.
- **Light on slow networks.** No third-party script or frame is loaded
  (the page's Content-Security-Policy allows none); the waiting page sends
  a small request every 2.5 seconds.
- **It survives the browser being closed in the background.** Low-memory
  Android phones often reload a tab when the person comes back from another
  app. The browser's half of the sign-in is an HttpOnly cookie, so a
  reloaded page carries on where it was.
- **Considered and not used:** the Telegram Login Widget (a script and
  frame from telegram.org, the bot's domain set with BotFather, and on a
  phone it asks the person to type their number and confirm in Telegram:
  more steps, and it does not give MarkX the number); the Mini App alone
  (works only inside Telegram; its route stays, with M4 fixed); SMS (off,
  by SI-1).
- **UNKNOWN:** how many MarkX customers have Telegram installed; how the
  link behaves in every Ethiopian Android browser and in Telegram Desktop.
  Not measured; nothing here was tried on a real phone or with a real bot.

**What protects it.**

- **Two secrets.** The link's token (256 bits) and a second 256-bit
  secret that only the browser that started holds, in an HttpOnly cookie
  sent only to the two sign-in routes (`markx_tg_sign_in`, path
  `/api/v1/auth/telegram/sign-in`). Only keyed hashes of both are stored
  (`telegram_sign_ins.token_hash`, `.browser_hash`, 32 bytes by
  constraint). A copied link alone signs nobody in, and only the browser
  holding the secret can collect the session, **once** (row lock; four
  simultaneous collections give one session, tested).
- **Telegram says who.** The webhook (D-093: secret header, update ids
  once, private chats with people only) accepts `/start si-<token>` from
  one Telegram account; a second account opening the same link is told it
  is not valid. A shared contact is accepted only when its `user_id` is the
  sender's own id and it is not forwarded; otherwise the bot asks again.
- **Short and single.** Each link works once and for
  `auth.telegram_sign_in_minutes` (10, PROVISIONAL P-101-1), start to
  finish; a new start in the same browser, or a new link opened by the same
  Telegram account, ends the earlier one. 60 starts an hour per address
  (P-101-2) and 20 bot attempts an hour per Telegram account.
- **The residual risk, said plainly: a forwarded link.** Someone who sends
  their own sign-in link to a victim ("open this") and gets the victim to
  press Start *and* share their number would sign the sender's browser in
  to the victim's account. The bot's message therefore says, in Amharic and
  English, to continue only if they started signing in themselves; the
  person is told in the app of every new sign-in (`auth.new_sign_in`, as
  with SMS codes); the link lives ten minutes. A matching code shown on both
  screens would reduce this further at the cost of one more step: **F-25**.
- **UNKNOWN, to re-read when the bot is connected:** the exact shape of
  Telegram's `contact` message and of `reply_markup` in a webhook reply
  were written from what is known of the Bot API; this session did not
  reach Telegram's documentation. The runbook says to check before
  activation.

**Switched on with the bot.** Signing in with Telegram uses the same bot,
webhook and secret as connecting Telegram (D-093) and is on exactly when
`MARKX_TELEGRAM_LINKING_ENABLED` and its two values are set (still OFF by
default everywhere). With SMS off and the bot off, nobody can sign in, and
the page says so ("Signing in is not available right now") instead of
offering a button that fails.

**Staff.** Staff sign in with Telegram like everyone (a customer session,
with no staff powers), then the staff page asks for their **existing
second step**, the password and the authenticator code
(`POST /auth/staff/step-up`, `StaffStepForm.tsx`); no phone number is
typed: it comes from the signed-in account. The Telegram session is
replaced by a short staff session (unchanged lifetimes). Replayed codes are
refused as before; five failures lock the staff account (only the person
holding that Telegram account can get this far, so this lock cannot be
used by an outsider). The old way (phone, password and code without
Telegram) is **refused while SMS is switched off** (403
`staff_telegram_required`, the same for every number; PROVISIONAL
P-101-8), so a Telegram-only server has no way around Telegram; it stays
for when SMS is switched back on, and on a laptop.

### 2. The confirmed phone number, and changing Telegram account or number

An account is made only once Telegram has confirmed the number, so every
account signed in this way has a confirmed number. It must be an Ethiopian
mobile number (`+2519…` or `+2517…`, `core/phone.py`); anything else is
refused with "MarkX needs an Ethiopian mobile number". One number is one
account; one Telegram account is one account (both unique in the
database). **PROVISIONAL P-101-6, the rules when something changes** (T is
the Telegram account, P the number Telegram confirmed):

| Situation | What happens | Why |
| --- | --- | --- |
| An account has both T and P | That account signs in | The normal case |
| Neither exists | A new account with P and T | A new person |
| An account has P and has **never had any** Telegram account (made by SMS before SI-1, by an invitation, or by staff for a new staff member) | T is connected to it; it signs in with its history, and belongs to T from then on | Telegram has just confirmed P belongs to this person, as an SMS code did |
| An account has P and a **different** Telegram account, **connected or disconnected** | **Refused**; the page says to sign in with that Telegram account or contact support | Ethiopian numbers are recycled: a new owner of an old number must not take over the old owner's account, orders or shop. Support decides (F-24). See section 2a |
| The account T belongs to was disconnected from Telegram | It signs in, and Telegram is connected again | Only T can; disconnecting stops messages, nothing more |
| The account with T has another number, and P belongs to nobody | The account's number becomes P; recorded in the audit log (masked numbers) and told to the person in the app (`auth.phone_changed`) | The same person changed number; deliveries need the current one, and Telegram confirmed it |
| The account with T has another number and P belongs to a second account | **Refused** | One number, one account; support decides |
| The account is blocked or deleted | Refused | As before |

Locks: the users' rows (ascending id), then the Telegram account's advisory
lock (D-093's order), then one per number; the unique constraints inside
savepoints are the backstop. Two Telegram accounts sharing new numbers at
the same moment make two accounts (tested).

### 2a. A recycled number never takes over an account (rule P-101-6, fixed after the independent review of pull request #9)

**The defect.** An independent review of pull request #9 found that
"Disconnect Telegram" made MarkX forget which Telegram account an account
had. Person A signs in with Telegram, then disconnects; later the phone
company gives A's old number to a stranger, who signs in with Telegram and
the row "an account has P and no Telegram" put the stranger into A's
account, with A's orders, addresses and shop.

**The rule now applied (the founder's rule P-101-6: a recycled number must
never take over someone else's account), recorded 21 November 2026:**

- Once an account has had a Telegram account, MarkX **always remembers
  which one**, even after "Disconnect Telegram". Disconnecting only stops
  messages.
- **Only that same Telegram account may sign in to it again.** Any other
  Telegram account bringing the same number is refused
  (`phone_on_other_telegram`) and told to contact support (F-24, later).
- An account that has **never** had any Telegram account (made by an
  invitation, by staff, or by SMS before SI-1) may still be claimed by the
  first Telegram sign-in with its number, as before.

**How.** A new column `users.bound_telegram_id` (migration `0021`), the
Telegram account the account belongs to. It is set the first time **any**
Telegram account is attached, by any of the three ways (signing in with
Telegram, the bot's connection link, the Mini App), and is never cleared:
"Disconnect Telegram" clears only `telegram_id`, which carries messages.
The database backs it three times: it is unique (one Telegram account
belongs to at most one MarkX account), `telegram_id` when set must equal
it (a CHECK), and a trigger refuses to change or clear it once set, for
every role. Existing connected accounts were bound to their Telegram
account by the migration. **UNKNOWN for real data, and irrelevant today:**
an account that disconnected before `0021` has no record of its Telegram
account (the id was cleared and was never written to the audit log), so it
would stay unbound; nothing is deployed, so no real account is in that
state.

**Every other way a different Telegram account could reach an existing
account, searched in the sign-in and account code, and closed the same
way:**

1. **Connected by the bot's link or the Mini App, then disconnected** (not
   signed in with Telegram at all). Same takeover; closed because those
   ways bind too.
2. **"Connect Telegram" with a different Telegram account after a
   disconnect** (bot link or Mini App). It would have bound the account to
   a second Telegram account, which could then sign in. Now refused (the
   link ends `failed`/`already_connected`; the Mini App answers 409
   `telegram_already_linked`, the same words as every refusal). Only the
   account's own Telegram account can be connected again.
3. **A remembered Telegram account connected to, or signing in to, a
   second MarkX account** after disconnecting from the first. Refused
   (`telegram_in_use`; signing in with the second account's number is
   `phone_in_use`).
4. **Found on the way, not a takeover but a split:** a person who
   disconnected and then changed number signed in with their own Telegram
   account and got a new, empty account. Now the lookup by Telegram uses the
   remembered account, so they reach their own account and the number
   follows (as section 2 says for connected accounts); their old number is
   free for its next owner, who gets a new account of their own.

Checked and not a way in: Mini App sign-in (`POST /auth/telegram`) finds
only a *connected* Telegram account, so after a disconnect it answers
`telegram_not_linked` for everyone; collecting a sign-in (`check`) uses
the account chosen when Telegram confirmed it; staff and team-member
creation make accounts with no Telegram account. **Outside this rule, said
plainly:** signing in by SMS code (switched off by SI-1) proves only the
number, so a stranger with a recycled number could sign in by SMS if SMS is
switched back on. That is the SMS backup's own question, not changed here;
it should be decided with F-24 before SMS returns.

**A refused sign-in does not reconnect anything.** When the account's own
Telegram account signs in with a new number that belongs to someone else,
the sign-in is refused and Telegram stays disconnected (tested).

**Website words changed** (English and Amharic, native review still
pending): the connection page no longer says "disconnect it first to
connect another" or "disconnect it there first", which would no longer
work; it says a MarkX account can only be connected to the Telegram
account it first used and to contact MarkX support to change it.

**Tests:** `tests/api/test_telegram_recycled_number.py`, 13 tests. The
first, `test_a_recycled_number_cannot_take_over_an_account_after_disconnect`,
plays exactly the review's steps (A has a shop and an address, signs in
with Telegram, disconnects; a stranger brings the number with another
Telegram account): **on the branch before the fix (`b89aeff`) it fails
because the bot answers the stranger "✅ You are signed in"**; after the
fix the stranger is refused with `phone_on_other_telegram`, gets no
session and no account, and A still signs in. On `b89aeff` 12 of the 13
fail (the takeover, the bot-link and Mini App ways, the second Telegram
account connected, the remembered account reaching a second account, the
split account, and the database guards); one guard passes on both (no
answer names the Telegram account). Web: one test that the refusal's words
say to contact support, in both languages. **No existing check or test was
weakened, removed or changed.**

### 3. SMS switched off

`MARKX_SMS_PROVIDER` takes a third value, **`off`**: no login code and no
notification SMS is sent, and no provider is needed. **A real server may
start with SMS off; it still refuses the fake sender** (unchanged check,
unchanged tests) and still needs every provider setting when SMS is `http`.
Switching SMS off relaxes nothing else (tested: the fake bot check, the
fake push sender and insecure cookies are still refused). With SMS off,
`POST /auth/otp/request` and `/auth/otp/verify` answer 403 `sms_sign_in_off`
before anything is counted or sent; notification SMS are recorded
`skipped`/`sms_disabled`; `get_sms_sender()` refuses as a last barrier.
The SMS code is all kept: switching it back on is choosing a provider
(F-11) and setting `http`. `infra/production/env/api.env.example` now says
`off`. On a laptop and in the tests the default stays `fake`, so every
existing journey and test runs unchanged; the new journey runs the API with
`off`.

### 4. M4: Telegram start-up data accepted once, for minutes

Mini App start-up data was accepted for an hour and any number of times.
Now: **five minutes** (`auth.telegram_init_data_max_age_seconds`, 300,
PROVISIONAL P-101-3, at most the old hour), and a sign-in with it **marks it
used**: a keyed hash of Telegram's signature goes into
`telegram_init_data_uses` (committed at once in its own transaction), and
the same data again is 403 `telegram_data_used`, however its fields are
ordered. It is used up only by a sign-in that succeeds, so a person whose
Telegram is not linked yet can link it and then sign in with the same
start-up. Linking keeps the shorter window but not single use (it needs a
MarkX session already, and linking the same Telegram account again
changes nothing; two existing tests rely on that and are unchanged).
Rows are deleted after two days by `retention.prune`.

### 5. M3: no staff lock-out by an outsider, no telling which numbers are staff

Before, five wrong passwords for a staff member's number locked the
account for 15 minutes for everyone, repeatable for ever, and a locked
account answered 429 `staff_locked` where any other number answered 401:
an outsider could lock staff out and find staff numbers. Now, on the
phone-and-password way: failures lock that staff account **only for the
network address they came from** (`auth.staff_failures_before_lock` 5,
`auth.staff_lock_minutes` 15, PROVISIONAL P-101-4), counted in the
rate-limit table; **a lock answers exactly like a wrong password** (401
`staff_credentials_invalid`, no details, no `Retry-After`, the same
password-hashing work); an unknown number, a wrong password and a lock
cannot be told apart. Because one guesser can now spread over many
addresses, **10 failures on one staff account within an hour, from any
addresses, alert the founder** (`staff.sign_in_failures`, a warning, staff
id only; `auth.staff_failure_alert_per_hour`, PROVISIONAL P-101-5). The
existing per-address limit (30 attempts in 15 minutes) is unchanged. With
SMS off this way is closed anyway (P-101-8), and the Telegram way cannot
be reached by an outsider at all.

**Two existing assertions changed, and why it is not weaker.**
`tests/api/test_auth_staff.py::test_five_failures_lock_the_staff_account`
and `tests/api/test_phone_digit_limits.py::test_five_failed_staff_sign_ins_in_mixed_digit_styles_lock_the_account`
expected the lock to answer 429 `staff_locked`. That answer *is* finding
M3 (it tells a stranger the number is staff). They now expect 401
`staff_credentials_invalid`; the lock itself is checked as before (the
right password and code are still refused while it holds), and the first
test's line that ends the lock also clears the per-address counters, where
the lock now lives. Nothing else in either test changed.

### 6. M2: no one person, number or address can spend the SMS budget

For when SMS is switched on again. Before, one daily budget (500) was the
only daily limit, so anyone with enough numbers and addresses could spend
it and stop everyone's codes. Now each code also counts against three
**daily shares of the budget**: per phone number 2% (10 codes a day; one
number is one account, which is the only "person" MarkX knows before
sign-in), per network address 5% (25) and per network 10% (50: the same
first three parts of an IPv4 address, or the same /64 of IPv6, so hopping
addresses inside one connection does not help) (PROVISIONAL P-101-7). A
share is never smaller than one hour's allowance under the hourly limit,
so a small budget cannot lock an honest person out of a retry. A refused
share answers 429 `sms_share_spent` and does not touch the budget. **The
shared budget stays the final limit** (503 `sms_budget_spent`), and the
worker's existing `sms.budget` check warns at 80% and is critical at 100%
(tested). **Why per network is generous:** many Ethiopian mobile customers
reach the internet through one shared address (carrier-grade NAT; how many
per address is UNKNOWN), so a strict per-address share would refuse honest
people who happen to share one.

### 7. Saved tests from the pull request #7 review

`tests/db/test_buyer_limit_contention.py` (23 tests): two checkouts of one
buyer at the same moment, through the API, make one order; two orders of
one buyer at the same moment, from two browsers changing the same cart,
never pass the per-offer limit, the per-shop limit or the open-order
limit together (each run five times); an expired order counts for neither
unit limit, takes no open-order place and never starts the cancellation
cool-down. **They pass on `main`:** the protection already existed (D-099);
the tests save the proof. Checked by breaking the code on purpose: without
the unit-limit check the per-shop race fails every round and the per-offer
race fails in some rounds; counting expired orders makes all three expiry
tests fail. **Found on the way:** removing only the buyer's cart lock does
not make them fail, because the shop and offer locks taken next serialise
the same orders (`AGENTS.md` lock order); the cart lock is the first of two
barriers, not the only one.

### PROVISIONAL values (THE FOUNDER MUST CONFIRM OR CHANGE THEM BEFORE MARKX GOES LIVE)

The limits are settings in `markx/core/settings_store.py` (the one place),
each marked `PROVISIONAL (P-101-n)` there and on the admin settings screen
(in Amharic too), checked by
`tests/api/test_sign_in_abuse.py::test_the_new_limits_are_provisional_settings`;
staff can change them, audit-logged. The two rules are marked in the code
where they live (checked by `test_the_rules_are_marked_provisional_where_they_live`).

| | Setting or rule | Value | Why this value |
| --- | --- | --- | --- |
| P-101-1 | `auth.telegram_sign_in_minutes` | 10 minutes | Long enough to open Telegram, press Start and share the number on a slow phone and network; short enough that a forgotten or forwarded link soon stops working. The same as a connection link (D-093) |
| P-101-2 | `auth.telegram_sign_ins_per_ip_per_hour` | 60 | A Telegram sign-in costs nothing to send, and many customers share one mobile address; the limit only protects the database |
| P-101-3 | `auth.telegram_init_data_max_age_seconds` | 300 seconds | A Mini App sends its start-up data as it opens; five minutes allows a slow network and a phone clock a little wrong, instead of the hour before (M4) |
| P-101-4 | `auth.staff_failures_before_lock`, `auth.staff_lock_minutes`; the lock per address | 5 failures, 15 minutes, per address | The values staff had before; only who is locked changes (the address that failed, not the account) |
| P-101-5 | `auth.staff_failure_alert_per_hour` | 10 in an hour | Twice what locks one address: a person mistyping does not reach it; a guess spread over addresses does |
| P-101-6 | (a rule) changing Telegram account or number | The table in section 2, and section 2a: an account that ever had a Telegram account belongs to it for good, even after "Disconnect Telegram" | Telegram's confirmation is trusted for a new number on the same Telegram account; never for moving a number or an account to another Telegram account, because numbers are recycled |
| P-101-7 | `auth.sms_daily_share_per_phone_percent`, `..._per_ip_percent`, `..._per_network_percent` | 2%, 5%, 10% of the daily budget, never under one hour's allowance | 10 codes a day is far more than one honest person needs; an address and a network get more because customers share them (CGNAT); 20 networks would be needed to spend the whole budget |
| P-101-8 | (a rule) staff without Telegram | Refused while SMS is off; allowed (with M3's fixes) when SMS is on again | SI-1 means no way around Telegram; when SMS is back as the backup, staff need a backup too |

**How an honest person is affected.** A buyer or seller taps one button,
presses Start and Share in Telegram, and is signed in; they type nothing.
Someone without Telegram cannot sign in while SMS is off (the page tells
them to install Telegram). A person who changed their number signs in as
before and their MarkX number follows; a person who got a new Telegram
account for an old number is asked to contact support. Staff do one extra
step they already knew. Nobody honest meets the M2 or M3 limits.

### Tests

Each new test fails on `main` at `b79caab` and passes here, except the
guards, which pass on both (they check that nothing that should stay the
same changed):

- Items 1 and 2: `tests/api/test_telegram_sign_in.py`, 32 tests (all fail
  on `main`: the feature does not exist). Uses `tests/telegram_play.py`,
  which plays Telegram through the webhook with the test-only secret.
- Items 3 to 6: `tests/api/test_sign_in_abuse.py`, 37 tests: 28 fail or
  error on `main`, 9 guards pass on both (the fake sender still refused;
  switching SMS on still needs every setting; the budget still the final
  limit and its alert; shares scale; failures still audited; linking again
  harmless).
- Item 7: `tests/db/test_buyer_limit_contention.py`, 23 tests: pass on both
  (see section 7 for how they were shown to catch a breach).
- Web: `src/lib/telegram-sign-in.test.ts`, 3 tests.
- Browser journey: `apps/web/e2e/telegram-sign-in.mjs`, in the journeys
  workflow with the API recreated with SMS `off` and test-only bot values:
  a new person at 360 px signs in with Telegram (played through the
  webhook) and places an order; a foreign number is refused in English and
  Amharic; the staff page asks for Telegram first; axe on each page.
- Changed: the two assertions in section 5. No other existing check or
  test was weakened, removed or changed.

**Not done:** no bot, no real message, no real phone; the matching-code
step (F-25); a staff tool to move a number between Telegram accounts
(F-24); sign-in from inside the Mini App with the contact step; a native
speaker's review of the new Amharic (website and bot).

## D-102 Telegram finished for orders: alerts with buttons, the seller bot's inbox and commands, buyer updates, the weekly message

**Date:** 21 November 2026. **Branch:** `claude/markx-telegram-pr9-completion-nneqom`,
from `main` at `fe4546f` (pull request #9 merged after an independent
review). **Blueprint:** S-07, S-24, S-26, C-10, D.16, S-08. **Nothing
deployed; no bot, token or account; nothing sent to or received from
Telegram; no SMS; no money.** Everything is behind the switches that already
exist: the webhook exists only with Telegram linking on (D-093), and
messages leave only with a push provider configured (D-092). No migration.

### What a seller and a buyer now get in Telegram

1. **New-order alert with buttons (D.16, S-07).** "MarkX: new order
   MX-…. Tap Accept or Decline below before the deadline." with ✅ Accept,
   ✖ Decline, 📥 Orders waiting and "Open in MarkX". **The reminder before
   the order expires** (the existing job, `orders.response_reminder_minutes`,
   10 minutes, D-092) now says so with the same buttons. Sent once (its
   database row) and in the person's language.
2. **The order inbox in the bot (S-07).** `/orders` (or the 📥 button)
   lists up to 10 orders with a next step, the soonest deadline first:
   waiting for an answer (with minutes left), accepted (to pack), paid (to
   pack), packed (to send), delivery failed (to send again). Each opens a
   card with the buttons its state allows: Accept / Decline (then one of
   three reasons), 📦 Packed and ready, 🛵 On its way. A pressed button turns
   the message into the result ("✅ You accepted order MX-…") and the next
   step. A collection order and an order on its way say: enter the buyer's
   handover code **in MarkX, never here** (D-044).
3. **Commands (S-24, S-08).** `/help`, `/orders`, `/offers` (the store's
   listings: a six-character reference, product, price, available stock,
   "price to confirm" or "paused"), `/price REF AMOUNT` (birr, up to two
   decimals), `/stock REF COUNT`, `/checkin` (every live listing is still
   right today). `/start` alone shows the commands to a connected person.
4. **Order updates to buyers (C-10).** Every update the buyer already got
   in the app now has its own words in Telegram, in English and Amharic
   (before, eight of them said only "You have a new message from MarkX"):
   placed, accepted, declined, not answered, another shop has it, packed, ready to collect, on
   its way, delivery failed, returned, delivered, payment recorded, new
   handover code, completed, problem received, shop answered, decision,
   refunded, cancelled. Each has a button: the "order placed" message
   opens the **secure tracking link** made for it (no sign-in, never the
   handover code, D.14); later ones open the order page, which asks the
   buyer to sign in.
5. **The weekly message (S-26).** "MarkX weekly report, week from
   2026-11-16: 4 orders received, 3 accepted, 2 completed. 1 of your prices
   need checking: send /checkin if they are all still right." with a ✔ All
   still right button. Before, Telegram said only "You have a new message".

### The rules, and how each is kept

- **The same permissions as the website, checked again on the server at
  every press.** The website's seller check is now one function,
  `accounts.deps.seller_membership` (an active member of a store that is
  not closed, whose role holds the capability, blueprint C.3); every
  `/seller/{seller_id}/...` route and every bot action call it. Then the
  bot calls the very service function the website's button calls
  (`orders.seller_respond`, `mark_ready`, `seller_dispatch`,
  `offers.update_offer`, `set_stock`, `confirm_offers`), which locks the
  row and checks the order's state, deadline and the store's status. So:
  only `owner`, `manager` and `orders` answer and move orders; only
  `owner`, `manager` and `catalogue` change prices, stock and the
  check-in; any member lists offers. Another store's order answers "That
  order was not found." exactly like a missing one. Nothing in a button or
  a command is trusted: a button carries an action and an order id only.
- **Who is pressing.** The webhook secret proves the call is Telegram's
  (D-093); Telegram proves the sender. The sender must be the Telegram
  account **connected now** to an **active** account (`users.telegram_id`).
  A disconnected one (remembered in `bound_telegram_id`, D-101 section 2a)
  or a blocked account is told how to connect and can do nothing. Groups,
  channels, bots and someone else's chat are ignored. A stranger's unknown
  command stays ignored (D-093).
- **Never twice, never lost after a restart.** Each Telegram update's id is
  stored in the same transaction as what it changed (`telegram_updates`,
  D-093). A press Telegram delivers again (after a restart, a timeout or an
  answer lost on the way back) changes nothing a second time, and is
  answered with the *current* state of what was pressed, so the seller
  still sees the outcome. Messages MarkX starts itself are written to the
  outbox with the change that caused them, so a restart never loses one,
  and a delivery recorded as `accepted` is never sent again (D-092). **The
  one case left, said plainly:** if the worker dies in the instant between
  Telegram accepting a message and MarkX recording it, MarkX cannot know
  and sends it again, marked as a possible duplicate (at-least-once,
  D-034, unchanged): Telegram offers no way to refuse a repeat, and an
  order alert seen twice is safer than one never seen.
- **Every new text in English and Amharic**, the person's language
  (Amharic unless they chose English). A test checks every key and that
  both languages fill the same fields. Native review of the Amharic:
  **UNKNOWN** (not done).
- **Nothing personal leaves the server.** Notification texts still carry
  only the order code (D-092); the weekly one adds only its week and whole
  counts, each checked (`texts.render_telegram`). The bot's own answers name
  only the order code, its state, its number of items and minutes left,
  and, for listings, the store's own public listing. Never a buyer's name,
  phone number or address, never the handover code, never what a buyer
  ordered (F-26).
- **The weekly message is re-checked when it is sent:** only to an active
  member who may still see the store's performance, of a store that is not
  closed (before, someone who had left the store still received it).

### PROVISIONAL values and rules

| # | What | Value | Why |
| --- | --- | --- | --- |
| P-102-1 | Bot presses and commands per Telegram account | 120 an hour, then silence for the hour | A busy shop answers a few dozen orders a day; the limit only stops a runaway script |
| P-102-2 | Decline reasons in the bot | Three: "Out of stock", "The price has changed", "Cannot deliver to this area in time", stored in the seller's language | The website takes free text (at least 3 characters); in Telegram a button is quicker and always passes that rule |
| P-102-3 | Orders in one inbox message | 10, the soonest deadline first, then "…and N more: open MarkX" | Fits a phone screen and Telegram's message limit |
| P-102-4 | Listings shown by `/offers` | 20 | The same reason |
| P-102-5 | Buyer's buttons | The "order placed" message opens the secure tracking link; the others the signed-in order page | The tracking link was made for exactly that message (D.14); a newer one is not issued per message |
| P-102-6 | What the bot shows about an order | Code, state, items, minutes left; not the products, prices or buyer (**replaced by D-104:** the product names are shown, F-26) | The D-092 rule for anything that leaves the server; see F-26 |
| P-102-7 | Weekly message in Telegram | Counts only: received, accepted, completed, prices to confirm; no money | Earnings are the store's own, but money figures stay inside MarkX until the founder says otherwise |
| P-102-8 | Handover in the bot | Not offered: the code is entered on the website only; "On its way" from the bot records no rider name or number (the website can add them) | The handover code is never stored, logged or shown outside MarkX (D-044); Telegram keeps every message |
| P-102-9 | A listing's reference | The last six characters of its id, for example `4F2A9C` | Random in a UUIDv7, so short and almost never alike; if two of one person's listings ever match, the bot says it found none and the website still works |

Each is marked in the code where it lives. **The engineer's guesses; the
founder must confirm or change them before MarkX goes live.**

### What changed in the code

- `markx/telegram_bot/` (new): `service.py` (the inbox, the buttons, the
  commands), `keyboards.py` (buttons), `texts.py` (the bot's words).
- `markx/accounts/deps.py`: `seller_membership`, the one seller check, now
  shared; `load_seller_context` calls it (no change for the website).
- `markx/accounts/telegram_link.py`: button presses and bot commands go to
  the bot; a repeated update is answered with the current state.
- `markx/notifications/push.py`: `send(..., reply_markup=None)`; the fake
  also records the buttons and the words a real bot would send.
- `markx/notifications/texts.py`: `TELEGRAM_TEXTS` and `render_telegram`
  (Telegram only: SMS still uses `ORDER_TEXTS` alone, so no new paid SMS).
- `markx/notifications/delivery.py`: the buttons; the weekly message's
  recipient check.
- `markx/performance/service.py`: the weekly notification also carries
  `orders_confirmed` and `prices_to_confirm`.
- The webhook's description (both copies of `openapi.json`).
- `docs/runbooks/telegram-linking.md`: `allowed_updates` must include
  `callback_query` (with `message` alone every button would do nothing);
  a new step 9 for the bot.

### Tests

`tests/api/test_telegram_bot.py`, 24 tests. On `main` at `fe4546f`, with
only this file added, it cannot load (the bot does not exist); with the new
imports replaced by stand-ins, **all 24 fail** for the missing behaviour:
the webhook answers nothing to a press or a command (`{"ok": true}`),
alerts carry no buttons, buyer updates never move on because the seller
cannot press, Telegram's words do not exist, and the weekly message reaches
someone who left the store. They cover: the alert and its buttons; the
reminder, once, after repeated runs; accept, ready, on its way; decline
with a reason, the stock back; **refusals in the bot: the `catalogue` and
`finance` roles, another store, a member removed after the alert, a
disconnected and a blocked Telegram account, a closed store, too late,
already answered, a forbidden move, a collection order**; a press and a
price change delivered twice (once); the commands and the website's limits
(no zero price, no stock below what open orders hold); the `orders` role
may not change prices; a stranger and malformed updates; the buyer's
updates in Amharic with their buttons (the tracking link opens); the weekly
message's words, once, and not to someone who left; every text in both
languages; only codes, dates and whole numbers in a Telegram text; every
button within Telegram's 64 bytes; and every order message the order code
sends (27, read from the code itself) has its own Telegram words.

No existing test or check was weakened, removed or changed.

**Not done or not verified:** a real bot and a real phone (UNKNOWN: the Bot
API shapes in the runbook, step 9, and how Telegram shows a pressed button
without `answerCallbackQuery`); a native speaker's review of the Amharic;
the website does not show anything new (none was needed); the bot cannot
answer a reported problem or record a direct payment (the website does);
staff alerts in Telegram are not part of this.

## D-103 Server readiness: certificate install, renewal and expiry alert; rollback by prefix with the backup service; no half-working site after a failed deployment; images by digest, CPU and process limits, fixed user ids

**21 November 2026.** From `main` at `9b3658f` (pull request #10 merged
after an independent review). Answers the infrastructure defects of the
independent audit of 19 November 2026 (`docs/reports/2026-11-19-independent-audit.md`,
section 13). **No server exists; nothing was deployed, no domain,
certificate authority, account or paid resource was used.** Every fix is
proven in the production rehearsal on GitHub's machines
(`infra/production/rehearsal/rehearse.sh`) and, for the alert, by tests.

### 1. The certificate can no longer expire silently

The audit: "Certificate renewal missing: certificates will silently
expire." The runbook named a deploy hook that did not exist.

- **The install step** (`deploy.sh certificate install DIR`): checks the
  new pair first (it parses, the key is the certificate's own, it names
  `MARKX_SITE_HOSTNAME`, at least one more day of validity) and refuses it
  otherwise; writes both files with the owners `deploy.sh check` requires
  (root 644; uid 101, 400), renames them over the old ones, then the proxy
  tests its configuration and reloads **without a restart**; if it refuses,
  the previous pair is put back. `certificate temporary` makes a 7-day
  self-signed one for the very first start.
- **Automatic renewal**: `MARKX_TLS_RENEWAL=certbot` makes `certificate
  issue` get a Let's Encrypt certificate (HTTP challenge, the path the proxy
  already serves) with `deploy.sh certificate install-renewed` as certbot's
  deploy hook, and `certificate renew` run `certbot renew`.
  `certificate install-timer` installs a systemd timer
  (`infra/production/systemd/`) that runs `renew` twice a day at a random
  minute, catching up after a boot. **Off by default** (`MARKX_TLS_RENEWAL=none`):
  there is no domain (F-17). With renewal off the timer still runs the check.
- **The alert before expiry, independent of renewal**: the worker's watch
  has a new check, `tls_certificate` (`markx/ops/checks.py`). The production
  Compose file mounts the proxy's certificate folder read-only into the
  worker (`MARKX_TLS_CERTIFICATE_FILE`); the check reads the first
  certificate of `fullchain.pem` and raises `tls.certificate_expiring`
  21 days before expiry (warning), critical in the last 7 days and once
  expired, and `tls.certificate_unreadable` when it cannot be read. It goes
  through the existing alert channel (the founder's Telegram group once it
  exists, the log until then), once, again on escalation, and resolves when
  a renewed certificate is in place. The folder is mounted, not the file,
  so a renamed-in renewal is seen; the private key in it (uid 101, mode 400)
  is unreadable to the worker (uid 999, no capabilities), which the
  rehearsal checks. `deploy.sh certificate check` (exit 1 inside the
  warning time) and `deploy.sh check` (refuses an expired certificate, a
  foreign key or another hostname; warns inside the warning time) say the
  same on the server.

### 2. Rollback uses the image prefix and rolls back the backup service

The audit: rollback hard-coded `markx/`, ignoring `MARKX_IMAGE_PREFIX`, and
left the backup service on the newer release. `deploy.sh` now reads
`MARKX_IMAGE_PREFIX` (an exported value wins, as it does for Compose),
checks that **all three** images of the release (`api`, `web`, `backup`)
exist, starts the API, worker, web app and proxy (waited for) and then the
backup service (not waited for: it reports healthy only once a set newer
than 26 hours exists, which is not the rollback's to decide), and verifies.
The whole rehearsal now runs with `MARKX_IMAGE_PREFIX=markx-rehearsal`.

### 3. A failed check after the migration never leaves a half-working site

The audit: "A failed post-migration verify leaves the system half-up"
(before this, `up` replaced the worker with the new release even when its
API never became ready). Now, after the migration, any failure of the new
release's preflight, its start or the readiness checks goes to recovery:

1. **Back to the last working release** (the last `deploy`, `rollback` or
   `auto-rollback` in `releases.log`; a failed release is never recorded)
   when its images are present **and its own preflight accepts the
   migrated database**. Every service, the backup service included, runs it
   again, verified; `releases.log` says `auto-rollback`; `deploy` exits 1.
2. **Otherwise a safe stop**: the API, the worker and the web app are
   stopped (PostgreSQL and the backup service keep running; the proxy
   answers 502 or 504), `MARKX_CONFIG_DIR/deploy-halted` (mode 600) records the
   failed and the last working release, and the script prints the three
   ways out in order: roll forward; only for a backward-compatible migration
   `MARKX_ALLOW_NEWER_SCHEMA=true` and `rollback`; only with the founder's
   written approval a restore from the backup taken just before. `status`
   and `check` show the stop; a successful `deploy` or `rollback` ends it.

Recovery never sets `MARKX_ALLOW_NEWER_SCHEMA` itself: whether a migration
is backward-compatible is a person's judgement (`docs/runbooks/rollback.md`).
Since the review fix (section 5 below) it also never *reads* it: it checks
the old release with the setting forced off. A failed migration changes
nothing (PostgreSQL runs it in one transaction) and `deploy` now says so.

### 4. Containers

- **Digests**: PostgreSQL 17.12, nginx-unprivileged 1.28.2, and the Python
  3.13.18, PostgreSQL 17.12-bookworm and Node.js 22.23.5 base images are
  pinned to the digest of their multi-platform index, besides their tag,
  in the production and laptop Compose files, both Dockerfiles and CI.
  `infra/check-image-pins.sh` (new CI step) refuses a tag alone.
- **CPU and process limits** next to the memory limits, on every service
  and the migration step (`MARKX_*_CPUS`, `MARKX_*_PIDS`). PROVISIONAL
  (P-103-2): no CPU limit above 1.0, so every service starts on a one-CPU
  server (a limit above the server's CPU count stops a container from
  starting); process limits 64 to 256.
- **User ids set in the Dockerfiles**: the API, worker and backup images
  create `markx` as uid and gid 999 explicitly (`ARG MARKX_UID`, checked at
  build) and run as `999:999`; the web image checks that the base image's
  `node` user is 1000:1000 and runs as `1000:1000`. CI and the rehearsal
  check the ids.

### 5. The founder's rule: go back to an older release only when it truly accepts the database

**Added on 21 November 2026, after an independent review of pull request
#11 at `9d0c888`.** The defect it found: the compatible rollback told the
operator to switch on `MARKX_ALLOW_NEWER_SCHEMA` and to switch it off "with
the next deploy", but nothing made sure of that, and the rehearsal itself
ended with it on. Left on, the next failed deployment's automatic return
asked the old release whether it accepted the database; the setting made
it say yes to any newer database, and `deploy.sh` started old code against
an unchecked change and reported it as "verified". That can lose data.

**The rule (the founder's):** return to an older release only when it truly
accepts the database. `MARKX_ALLOW_NEWER_SCHEMA` exists for one thing only:
an operator, for one compatible rollback, vouching that a newer database's
migrations are backward-compatible with that release. It never decides
anything by itself. So:

1. **The automatic return checks the old release with the setting forced
   off**, whatever `api.env`, a Compose file or anything else says
   (`preflight_strict` in `deploy.sh`: the old release's preflight with
   `docker compose run -e MARKX_ALLOW_NEWER_SCHEMA=false`, which wins over
   every settings file and works with every release, including one built
   before this rule). A database newer than the old release is refused and
   the deployment stops safely. After starting the old release it also
   checks that the running API reports the schema as `current`; anything
   else is stopped as well.
2. **A deployment refuses to start while the setting is on**, before it
   builds, backs up or migrates anything, with the message "MARKX_ALLOW_NEWER_SCHEMA
   is on in …/api.env (left from a compatible rollback). A deployment never
   runs with it on. Remove that line …, then run deploy again. Nothing was
   changed." Any value but an explicit false (`0`, `off`, `f`, `false`,
   `n`, `no`) counts as on. **And the new release refuses it itself**,
   wherever it is set: `deploy.sh` runs every preflight of the new release
   with `--deploying`, which fails while the setting is on
   (`markx/ops/preflight.py`).
3. **Other ways closed the same way** (found while looking for any other
   way an old release could be started against a database it does not
   truly accept):
   - **A rollback by hand with the setting left on.** `deploy.sh rollback
     RELEASE` now also checks the release with the setting forced off. If
     the database is newer than that release, it starts nothing unless the
     operator vouches **twice**: `MARKX_ALLOW_NEWER_SCHEMA=true` in
     `api.env` (which the release needs to stay ready) **and**
     `--accept-newer-schema` on the command line. A setting left on from an
     earlier rollback is no longer enough.
   - **The backup service in a safe stop.** When the deployment failed
     before the new release started, the old release's backup service kept
     running against the migrated database; an older backup may not know a
     new table of file references. The safe stop now restarts the backup
     service as the release that migrated the database.
   - **`deploy.sh backup` after a safe stop** ran the last *working*
     release's backup image, which is the older one. It now uses the
     release that migrated the database (`failed_release` in
     `deploy-halted`) unless `MARKX_RELEASE` names another.
   - `check` and `status` warn while the setting is on; `rollback` reminds
     the operator to remove it.
4. **Not changed, and why** (UNKNOWN whether the founder wants more): during
   every deployment the running release keeps serving while the migration
   runs, until the new release replaces it. That is the normal window of a
   deploy without downtime, it does not *start* an older release, and it
   relies on migrations being written so the running code still works
   (`docs/runbooks/migrations.md`). Closing it would mean stopping the site
   for every deployment: the founder's decision, not this fix's.

The way out of a safe stop for a compatible migration is now: add
`MARKX_ALLOW_NEWER_SCHEMA=true` to `api.env`, run `deploy.sh rollback
<release> --accept-newer-schema`, and **remove the line again before the
next deploy** (which refuses until it is gone).

**Proof.** New `tests/deployment/test_deploy_newer_schema.py` (17 tests)
runs the real `deploy.sh` against a stand-in for `docker`, and
`tests/deployment/test_preflight_and_worker_heartbeat.py` has 3 new tests
of `--deploying`. On `9d0c888` all 20 new tests except 2 fail (the 2 that
pass check that what must still work does: a rollback to a release that
accepts the database, and a backup with no safe stop); with only a line
added to let the old script be loaded by the tests, the reviewer's case
still fails there with "rehearsal… running again, verified", the defect
itself. The rehearsal's new checks (section "the setting left on"): the
setting alone never decides a rollback; `deploy` refuses while it is on and
changes nothing; `check` warns; the new release refuses it when it is set
outside `api.env`; **the reviewer's case** (a database carrying a later
change, the setting on for every container, a failed update of a release
made before this rule): the automatic return checks the old release with
the setting forced off, refuses and stops safely, with the backup service
running as the release that migrated; then a roll forward (schema
`current`); and **the rehearsal ends with the setting off** (not in
`api.env`, not in the running API or worker). No existing test or check was
weakened or removed; the existing compatible-rollback check now also
passes `--accept-newer-schema`.

### PROVISIONAL values (the engineer's guess; the founder confirms or changes them before going live)

- **P-103-1**: the certificate warning starts 21 days before expiry
  (`MARKX_TLS_WARN_DAYS`, 8 to 90), critical in the last 7.
- **P-103-2**: the CPU and process limits above, for a server whose size is
  not chosen yet (blueprint M.3 says 2 GB of memory; the CPU count is
  UNKNOWN).
- **P-103-3**: renewal twice a day at a random minute (03:00 and 15:00
  UTC plus up to an hour).

### Settings left for the founder (switched off or unset)

- `MARKX_TLS_RENEWAL` (`none`) and `MARKX_ACME_EMAIL` (unset): F-17, the
  domain and how its certificate is made.
- `MARKX_TLS_WARN_DAYS`, `MARKX_*_CPUS`, `MARKX_*_PIDS`: defaults above.

### Tests

- `tests/api/test_tls_certificate_watch.py`, 7 tests: nothing checked
  without a file; quiet with time left; a warning with the date; critical
  in the last week and once expired; the first certificate of the chain
  counts; a missing or broken file is critical; through the scheduled
  watch: one alert, sent again only when critical, resolved after renewal.
  All 7 fail on `9b3658f` (the check does not exist; through the scheduled
  watch no alert is raised at all).
- The rehearsal's new checks (each listed in "Tests executed",
  `docs/DEVELOPMENT_STATUS.md`): limits, user ids and digests of every
  container; the worker reads the certificate but not its key; the alert
  opens for the rehearsal's 2-day certificate and resolves after a new one;
  a certificate for another host and one with a foreign key refused, the
  old one still served; install served without a proxy restart, with the
  required modes; renewal off says so, `issue` refuses; renewal on, through
  a stand-in for certbot, installs via the deploy hook; the timer's units
  accepted by `systemd-analyze verify`; rollback of every service by
  prefix, and refused when the backup image is missing; a broken release
  after its migration: back on the last working release, every service,
  never recorded as deployed; a broken release with a newer migration: the
  safe stop, its record, `status`, 502 or 504 from the proxy, the old release still refused, then
  the documented way out (`schema: ahead`).
- No existing test or check was weakened or removed. Two existing
  rehearsal checks now ask more: the rollback check also requires the
  worker's and the backup service's images, under the prefix; `deploy.sh
  check` also checks the certificate itself.

### Not done or not verified

- A real server, domain, certificate authority and certbot (UNKNOWN: Let's
  Encrypt's real challenge from outside; the rehearsal uses a stand-in).
- Where alerts reach a person: the Telegram alert group does not exist yet,
  so an expiry alert reaches the log only (as every other alert today).
- A visitor-facing maintenance page during a safe stop (the proxy answers
  502 or 504), zero-downtime deploys, log shipping: unchanged from the audit.

## D-104 Three small fixes after pull request #11: product names in the seller bot (F-26), the review confirmation that vanished, a connected account always remembers its Telegram account

21 November 2026. Branch `claude/markx-pr11-review-fixes-3uf2ts`, from
`main` at `7093e6c` (pull request #11 merged after an independent review;
see `docs/DEVELOPMENT_STATUS.md`). One migration (0022). Nothing deployed;
no server, domain, account, bot, SMS or paid resource.

### 1. F-26, decided by the founder: the seller bot names the products

The founder chose option (b) without quantities: **product names only, never
any buyer detail**, in English and Amharic, shortened sensibly when long.

- **Where:** every Telegram message about one of the store's orders (the
  new-order alert, the reminder before it expires, and the others: expired,
  cancelled, problem reported, completed, ...), and the bot's `/orders`
  inbox and an order's card. A line of its own under the words:
  "Products: Samsung Galaxy A16" / "ምርቶች፦ ሳምሰንግ ጋላክሲ A16".
- **What:** the names the order line copied when the buyer ordered
  (`order_items.title_en`, `title_am`; never live catalogue text), in the
  reader's language, the other language if that one is empty. No quantity,
  price, variant, buyer name, phone number, address or handover code.
- **Shortened** (`markx/telegram_bot/products.py`, one rule for every
  message): control characters and line breaks become spaces, so a name is
  one line of plain text (Telegram is sent no formatting mode); each name at
  most 40 characters, cut at a word near the end, with "…"; the same product
  twice is named once; at most three names, then "and N more" / "እና ሌሎች N".
- **Only to whom it may go:** the names are read when the message is sent,
  and only for a person `recipient_may_receive` already let through (an
  active member who handles that store's orders, of a store that is not
  closed, about one of that store's orders). They are never stored with the
  notification and never go into an SMS (`render` still takes the order
  code alone). `render_telegram` takes them only on a store's order message
  (an `order.` template with a seller order), only as one plain line of at
  most 200 characters, and fills them in last and alone, so a name that
  looks like `{code}` stays text.
- **Changed from D-102:** P-102-6 ("not the products") is replaced by this.
  The test comment that said "no product" now says "the order code and the
  product names"; its assertions (no buyer name, no price) are unchanged.

### 2. "Your review is saved" vanished: a website bug, not a slow test

The browser journey "Reviews, reports, pictures and problem evidence"
failed now and then (four times so far, by the founder's count), waiting
30 seconds for "Your review is saved". Checked for this record: 18 November
locally (`docs/DEVELOPMENT_STATUS.md`), Browser journeys #44 first attempt
(the pull request #10 review's report) and #46 first attempt (its log: step
4, the order page, right after the order was completed). Which run the
fourth was: UNKNOWN (not checked).

**The cause**, seen in the browser with a probe on the old site: after
"Send review" the form showed the message and asked for a page refresh.
The refreshed order page no longer offers the item just rated, so the
item's form was removed, and the message with it. The message appeared
and was removed about 75 milliseconds later, for good. The journey passed
only when its check happened to fall inside that moment; a real buyer
mostly never saw the confirmation at all. The same happened on "Your
reviews" for an item rated from its list.

**The fix (the website):** a small holder, `ReviewNotices`, around each
list of items to rate (the order page, and the list on "Your reviews").
The form gives it the message; the holder sits outside the items, so the
refresh that removes the rated item leaves it, and the message, in place.
A form without a holder (changing a review, which stays on the page) shows
the message itself, as before. No timeout was lengthened, no retry or skip
added.

**The proof:** the journey now also waits until the rated item has gone
and requires the confirmation to be still there. On the old site that check
failed 3 runs out of 3; on the fixed site the journey, run on its own, passed **20 times out of
20 in a row** (36 to 43 seconds each, each on a fresh demo database
prepared as the journeys workflow does).

### 3. The database refuses a connected account with no remembered Telegram account

Found in the pull request #9 review. Migration 0021's rule, `telegram_id is
null or telegram_id = bound_telegram_id`, let one state through:
`telegram_id` set and `bound_telegram_id` empty, because comparing with an
empty value is "unknown" in SQL, not "false", and a check constraint only
refuses "false". No part of the program creates that state. Migration 0022
states the rule in full: `telegram_id is null or (bound_telegram_id is not
null and telegram_id = bound_telegram_id)`, under the same name. An
existing row in that state (none is expected; nothing is deployed) is bound
to the Telegram account it is connected to first, as migration 0021 did; if
another account is already bound to it, the migration stops with an error
rather than guess.

Two test helpers (`tests/api/test_notification_delivery.py`,
`tests/worker/test_worker.py`) set `telegram_id` alone, which is that very
state; they now also set the remembered account, as every way of
connecting does. No assertion changed.

### PROVISIONAL values

| # | What | Value | Why |
| --- | --- | --- | --- |
| P-104-1 | The longest product name a Telegram message shows | 40 characters, cut at a word, then "…" | About one line of a phone screen |
| P-104-2 | Product names shown for one order | 3, then "and N more" | Most orders have one or two lines; the inbox shows up to 10 orders in one message |

**The engineer's guesses; the founder must confirm or change them before
MarkX goes live.**

### What changed in the code

- `apps/api/markx/telegram_bot/products.py` (new): the names of an order,
  cleaned and shortened.
- `apps/api/markx/telegram_bot/service.py`, `texts.py`: the inbox and the
  order card show the names.
- `apps/api/markx/notifications/delivery.py`, `texts.py`: the store's order
  messages get the names, at sending time, for an allowed recipient only.
- `apps/api/migrations/versions/20261121_1800_telegram_needs_its_bound_account.py`
  (0022) and `markx/accounts/models.py`: the rule in full.
- `apps/web/src/components/ReviewForm.tsx` (`ReviewNotices`), the order
  page and "Your reviews"; `apps/web/e2e/shop-screens.mjs`: the new check.

### Tests

- F-26: seven new tests in `tests/api/test_telegram_bot.py` (section 7b);
  all seven fail on the old code (the alert and the inbox carried no
  names; the rest need the new rule). One of them checks that a full inbox
  (10 orders) with the longest names still fits Telegram's 4096
  characters.
- The review confirmation: the new journey check (above).
- The database rule: three new tests in
  `tests/api/test_telegram_recycled_number.py`; the two that try the
  forbidden state (for the API's role and the migrations' role) fail on the
  old rule ("did not raise").
- Full results: `docs/DEVELOPMENT_STATUS.md`, "Tests executed", 21 November
  2026 (D-104).

## D-105 Backups finished before any real data: alerts that work without the server (BK-4), a safe copy of the server's secrets (BK-5), and the pull request #4 review notes RN-1 to RN-5

21 November 2026. Branch `claude/backup-audit-findings-0icpm4`, from `main`
at `9daaf57` with the complete history. **Built and tested with PostgreSQL
17.12, MinIO, local containers and stand-ins only. Nothing deployed; no
account, monitor, Telegram group, bucket, server or paid resource; nothing
was sent to Telegram or to any monitoring service.** The audit's findings:
`docs/reports/2026-11-19-independent-audit.md` sections 3H, 3F, 5 and 6.
The review notes: the independent review of pull request #4 (its comment of
19 November 2026); RN-1 is its note 1, RN-2 and RN-3 its note 2, RN-4 its
note 3, RN-5 its note 4. **No item labelled "BT" exists in the repository's
documents** (the task named "the BT items"); what that meant is UNKNOWN,
and D-096 with its PROVISIONAL items P-096-1 to P-096-6 was read instead.

Each finding was first checked against the code at `9daaf57`: all seven
were still true (BK-4: alerts only on the server, no channel; BK-5: no
copy of the secrets; RN-1: verify, restore and the drill read the current
version only; RN-2: `rm -rf "$SOCKET_DIR"` and `docker rm -f "$NAME"`
unchecked; RN-3: `chmod 777` on the socket folder; RN-4: a long socket path
raised `psycopg.OperationalError` out of the drill; RN-5: `passed = report
["passed"] is True`).

### 1. BK-4: alerts that still work if the server is lost

- **The outside heartbeat** (`markx/backup/heartbeat.py`): after each
  VERIFIED, complete set the backup service calls
  `MARKX_BACKUP_HEARTBEAT_URL` (a plain GET, no data). An outside monitor
  expects it daily and alerts the founder when it stops: the dead man's
  switch the audit asked for. Treated as a secret (`SecretStr`: never
  logged, printed or recorded; only its host name is shown); https on
  staging and production; a user name or password in it is refused. Two
  tries; a failure is recorded in the run (`heartbeat: failed:http_500`) and
  never fails the set; an incomplete or failed set sends nothing.
  `python -m markx.backup heartbeat [--send]` says whether it is on and can
  call it once. **Off until F-18**: unset, the service says so at start-up.
- **Alerts without the database** (`markx/ops/notify.py`): `test` sends a
  test alert to the staff Telegram group through the bot and exits 0 only
  when the group accepted it; with alerts off it says "NOT DELIVERED TO ANY
  PERSON" and exits 1. `send` sends one operational alert. Both use the
  same sender as the worker's watch (`ops.alerts.get_alert_sender`), not the
  outbox, so they work while the database or the worker is down.
- **The container watch** (`deploy.sh watch`, `infra/production/systemd/
  markx-watch.{service,timer}`, every 5 minutes; `deploy.sh watch
  install-timer`): postgres, api, worker, web, proxy and backup must be
  running and not `unhealthy`. One that is unhealthy, stopped, restarting,
  paused or missing for `MARKX_CONTAINER_ALERT_MINUTES` (compose.env, 5 to
  720) alerts the group ONCE (from a throwaway container of the worker's
  image, so it works with the worker down), and once more when it is fine;
  an undelivered alert is tried again at the next run; a `compose run`
  container is not the service. The unit fails while a container is bad,
  so `systemctl --failed` shows it. It cannot see the whole server or
  Docker gone: that is the heartbeat's job.
- **`deploy.sh alert-test [--send-heartbeat]`**: the test alert and the
  heartbeat's state; fails unless the group accepted the alert.
- **Not done:** the audit's "second channel" (e-mail or SMS) is the outside
  monitor's own alerting, chosen with F-18; MarkX sends no e-mail. No
  real monitor or Telegram group was contacted: whether a message reaches
  a phone is UNKNOWN until F-18.

### 2. BK-5: a safe copy of the server's secrets

- **The secrets copy** (`markx/backup/escrow.py`; `python -m markx.backup
  escrow-secrets`, `open-secrets`; `deploy.sh escrow-secrets`): one file
  holding `api.env` (with `MARKX_SECRET_KEY` and `MARKX_ENCRYPTION_KEY`),
  `postgres.env` (the four database passwords), `migrate.env`,
  `backup.env`, `web.env`, `compose.env`, the backup signing and public
  keys, and the certificate's `privkey.pem` and `fullchain.pem`.
- **Never in plain form:** `deploy.sh` reads the files as root and pipes
  them as a tar stream (never a file) into the backup image, which keeps
  them in memory, encrypts them with MXB2 to the recovery key's PUBLIC half
  (the server can make a copy and never open one), and signs the envelope
  with the backup signing key (Ed25519). Only names and sizes are printed or
  readable; the file is mode 600, owner 999. It refuses without `api.env`
  and its two keys, without `postgres.env` and its four passwords, with an
  example value left in, with a link or anything but a regular file, and
  with a recovery key in any file.
- **Where it is kept:** written to `/var/backups/markx/escrow/` and put in
  the backup bucket under `escrow/` (read back; held by the object lock;
  retention never touches `escrow/`). The founder keeps a copy with the
  recovery key (F-19); the runbook says how from a phone only: the file is
  sent to the founder, who stores it in the same two places as the recovery
  key and never has to open it.
- **Opening it** needs the recovery key, so `open-secrets` refuses staging
  and production (BK-2), like a restore: `--check` lists and verifies,
  `--out DIR` writes a new private folder (700, files 600) for a new
  server. A copy written again in the bucket is read from its original
  version (RN-1).
- **The drill step the audit asked for** (`drill --from-destination
  --secrets FILE | --secrets-from-destination --staff-phone PHONE`, password
  in `MARKX_DRILL_STAFF_PASSWORD`): after the restore passed, (a) the copy
  opens with the recovery key and the server's signature, and holds both
  keys; (b) every staff authenticator secret in the restored copy decrypts
  with the copied `MARKX_ENCRYPTION_KEY`; (c) **a staff member signs in to
  the restored copy**: the real API (`uvicorn markx.main:app`) is started on
  127.0.0.1 against the restored database as `markx_app`, with only the two
  copied keys from the server (secrets in its environment only), and the
  sign-in goes through `POST /api/v1/auth/staff/sign-in` with the password
  and the code the authenticator shows, asked for at that moment (a code
  lasts 30 seconds; a restore longer); (d) injected: another server's
  `MARKX_ENCRYPTION_KEY` must open none of the staff secrets. The drill
  passes only if all four do.
- **An honest limit:** the drill signs in by phone, password and code
  (`/auth/staff/sign-in`). On a real server that route is refused while SMS
  is off (P-101-8) and staff sign in with Telegram, then password and code
  (`/auth/staff/step-up`); both check the password and the code with the
  same function (`_check_staff_credentials`), which is what the copied key
  decides. The drill's API runs with `MARKX_ENV=local` and the fake SMS
  sender so the route is open; it contacts nothing.
- **What it cannot prove:** that the copied `MARKX_SECRET_KEY` is the old
  server's. Nothing stored depends on it alone (the handover codes are
  derived, never stored). A stale copy shows only as different handover
  codes and dead signed links. Hence: a new copy after any rotation
  (`docs/runbooks/secret-rotation.md`).

### 3. RN-1: an overwritten backup file

- **Reading older locked copies** (`markx/backup/copies.py`): verify,
  restore and the drill read the dump, the index and the blob list by the
  SHA-256 the signed manifest records, and each blob by the file's SHA-256
  in the index: the current version first, then each older version, newest
  first. A set's manifest is the OLDEST version that verifies (a set writes
  it once, so a later different one is someone else's), so an overwritten
  manifest neither breaks nor hides a set (`newest_complete_set`,
  `record-drill`). The drill's injection copy is taken from the versions
  the set verified from. Each object read from an older version, and each
  piece of the set with two different versions or hidden by a delete
  marker, is reported: `WARN ... written again after the set was made`,
  `facts.overwritten`, the drill report's `overwritten`.
- **The alert:** the backup service (each set) lists the versions under
  `sets/` and compares each blob it checked with its ledger (another size
  or ETag = someone else wrote it), and records `overwritten` and
  `overwrite_check` in the run; `record-drill` records the drill's list.
  The watch's new `backup_overwrites` check raises `backup.overwritten`
  (critical) while any backup run or drill in the last 30 days found one,
  and `backup.overwrite_check_unavailable` (warning) when the server's key
  cannot list versions. The same bytes stored twice (an upload the client
  retried) are not an overwrite.
- **Keys:** the server's key needs `s3:ListBucketVersions`; the recovery
  machine's read-only key `s3:ListBucketVersions` and `s3:GetObjectVersion`
  (`infra/backup/minio-least-privilege.sh`, runbook step 3). Neither can
  delete. Without them, the report says the older copies could not be
  listed and only current versions are used.
- **Not verified:** whether S3 and R2 report versions and ETags as MinIO
  does (runbook, "To test on the real provider", item 8).

### 4. RN-2 and RN-3: the recovery script

`infra/backup/recovery-host.sh` now:

- deletes a socket folder only when it carries the script's mark
  (`.markx-recovery-socket`), is a real folder (not a link) and belongs to
  the user; `start` refuses a folder that holds anything else; a relative
  path, a path with `.` or `..`, and `/` are refused;
- removes a container only when it carries the label `markx.recovery=1`,
  which `start` sets; another container of the same name is left alone;
- keeps the socket folder **private**: the folder is mode 700, and the
  socket lives in its `run` subfolder, the only part the container sees
  (the image's start-up opens the permissions of the folder it is given:
  measured, `3777`; it cannot reach the folder around it). PostgreSQL runs
  as the invoking user (`--user`, with its data in a folder it makes); as
  root, as the image's own user. Checked by hand: as an ordinary user the
  owner connects and another user cannot.

### 5. RN-4: a socket path too long

A Unix socket path holds at most 107 bytes on Linux. `drill` checks
`PGHOST/.s.PGSQL.<port>` first and reports FAILED with the reason;
`recovery-host.sh start` refuses such a folder; any `psycopg.Error` in the
drill or the restore (a PostgreSQL that does not answer) is now a FAILED
report too, and the drill's cleanup never raises.

### 6. RN-5: record-drill checks the report

`drill.report_problems` (used by `record-drill`) does not believe the
report's `passed`. A report counts as a passed drill only when: its restore
is of the set it names; every restore check is present (14, by name) and
passed; the six faults every drill injects, plus the blob fault when the set
holds files, were all tried and refused, and no unknown one is named; the
secrets step, when it ran, passed with its injected fault; and the restored
set's time, database name, file count and row count are the signed
manifest's. Otherwise it is recorded as a FAILED drill (`drill_report_not
_a_pass` when the report claimed PASSED; exit 1), so the watch alerts.
**Limit:** a report is not signed by the recovery machine (the server holds
nothing to check such a signature against); someone who can run
`record-drill` on the server and knows the set's facts could still write a
consistent false report. Signing drill reports is a later option.

### PROVISIONAL values, for the founder to confirm

- **P-105-1** One heartbeat call per verified set; the runbook recommends
  the monitor expect one a day with about 3 hours' grace (an alert within
  about 27 hours of the last good set). Confirm with F-18.
- **P-105-2** A container alerts after 15 minutes unhealthy, stopped or
  missing (`MARKX_CONTAINER_ALERT_MINUTES`), the watch every 5 minutes.
- **P-105-3** `backup.overwritten` stays open 30 days after the last run
  that saw an overwrite, so a quiet night does not resolve it unseen.
- **P-105-4** What the secrets copy holds (the list in section 2).
- **P-105-5** A copy of the secrets is also kept in the backup bucket,
  locked, besides the founder's; old copies are never deleted by retention
  (a restore of an old set needs the secrets of its time). Confirm with F-19.
- **P-105-6** A drill report counts only with every injected fault tried
  and refused; the secrets step is checked when it ran but not yet required
  (no copy exists before F-19). Once F-19 is done it should be required.

### Changed

`apps/api/markx/backup/` (`copies.py`, `escrow.py`, `heartbeat.py`,
`staff_sign_in.py` new; `__main__.py`, `config.py`, `destination.py`,
`drill.py`, `restore.py`, `runner.py`), `apps/api/markx/ops/` (`notify.py`
new; `checks.py`), `infra/backup/recovery-host.sh`,
`infra/backup/minio-least-privilege.sh`, `infra/production/deploy.sh`,
`infra/production/systemd/markx-watch.{service,timer}` (new),
`infra/production/env/{api,backup,compose}.env.example`,
`infra/production/rehearsal/rehearse.sh`, `.github/workflows/ci.yml`,
`docs/runbooks/backup-and-restore.md`, `docs/runbooks/secret-rotation.md`.
No migration; no API change (the OpenAPI copies are unchanged).

### Tests

New: `tests/unit/test_backup_d105.py` (29), `tests/deployment/
test_d105_scripts.py` (17), `tests/storage/test_backup_rn.py` (5),
`tests/storage/test_backup_d105.py` (4). The RN tests use only names that
exist on `main`: against `main`'s code all 22 of them fail by assertion or
by the old traceback (run in a worktree of `9daaf57` with only the new test
files); the BK-4 and BK-5 files cannot import there (new features). Every
path the recovery-script tests give stays inside the test's own folder, so
running them against the old script harms nothing (see
`docs/DEVELOPMENT_STATUS.md` for why that mattered). No existing test,
check or rehearsal check was removed or loosened. Results: `docs/
DEVELOPMENT_STATUS.md`, "Tests executed", 21 November 2026 (D-105).

## D-106 Five Release 1 features: the Ethiopian calendar and clock (C-05), order again (C-19), the price-history chart (C-21), a shop's own logo (S-03), a shop's own customers (S-11)

22 November 2026. Branch `claude/sharp-albattani-dp65ad`, from `main` at
`6378764` with the complete history (`6378764` is the merge of pull request
#13, reviewed and merged by this session first: section 0). Pull request
**#14** (https://github.com/shumetmamo21-cyber/markx-marketplace/pull/14). **Follows** the
blueprint: D.1 and I.7 (C-05), D.10 and D.27 (C-19), D.7 and I.5 (C-21),
D.4 and I.5 (S-03, S-11). **No migration**: `stores.logo_key` and
`offer_price_history` exist since `0001`. **Nothing deployed; no account,
server, bucket, bot or paid resource.** Business choices are safe defaults
marked PROVISIONAL (below); every new word is in English and Amharic.

### 0. Before this work: pull request #13 reviewed and merged

Pull request #13 (D-105, backups: BK-4, BK-5, RN-1 to RN-5) was reviewed
read-only at its head `ad774aa` (not changed, commented on or pushed to):
the code, the four new test files, the CI and rehearsal changes (additions
only: no existing test or check removed, loosened or changed), and the
full suite locally with PostgreSQL 17.12 and MinIO, `MARKX_TEST_MINIO_REQUIRED=1`
and `MARKX_TEST_BACKUP_REQUIRED=1`: **2126 passed, 0 failed, 0 skipped**
(26 min 11 s). GitHub on `ad774aa`: CI #180 (8 of 8 jobs) and Browser
journeys #56 passed. **Verdict: no problem that must be fixed first.**
Merged with a normal merge pinned to `ad774aa`: `6378764`; its branch kept.
Main's own runs on `6378764`: see "Tests executed" in
`docs/DEVELOPMENT_STATUS.md`.

Two observations, **not blockers** (both need a full break-in on the server,
which the runbook already says makes everything made after it untrusted),
left for a later backup session:

- **R13-1** `open-secrets --out` writes every file name a validly signed
  secrets copy lists, with nothing checking it is one of the expected names
  (`escrow.ITEMS`). A copy signed with the server's signing key that names
  `../outside.txt` writes a file outside the chosen folder on the recovery
  machine (a probe with test-only keys did; `x` mode means it can create
  files, never replace one). Suggested fix: refuse any name outside
  `ITEMS` in `open_escrow` and `write_items`.
- **R13-2** After a suspected break-in at time T the runbook says to trust no
  backup set made after T, but says nothing of secrets copies, and
  `open-secrets --from-destination` takes the newest copy. Suggested fix: the
  same rule for copies in the runbook (choose one made before T with
  `--name`).

### 1. C-05: the Ethiopian calendar and clock, wherever a date or a time is shown

- **The web app**: `src/lib/ethiopian.ts` converts a Gregorian day to the
  Ethiopian calendar by arithmetic (Julian day numbers; the leap year is the
  year before one divisible by four), so the server and the phone always
  agree and no browser's calendar support is relied on. Its month names and
  the four parts of the day are CLDR's Amharic words (the same data Node and
  the browsers carry). `formatDateTime`, which every date and time on the site
  goes through, now writes Amharic as **"13 ኅዳር 2019 (22 ኖቬም 2026) ጥዋት 3:30"**:
  the Ethiopian date, the Gregorian date in brackets (blueprint I.7), then the
  Ethiopian clock, where 9:30 in the morning is 3:30, after its part of the day
  (በሌሊት 6:00 to 11:59 is midnight to 5:59; ጥዋት 12:00 to 5:59 is 6:00 to 11:59;
  ከሰዓት 6:00 to 11:59 is noon to 5:59 pm; በምሽት 12:00 to 5:59 is 6 pm to
  11:59 pm). English is unchanged ("22 Nov 2026, 09:30").
- A new `formatDate` does the same for a calendar day the API sends as
  `YYYY-MM-DD` ("7 ኅዳር 2019 (16 ኖቬም 2026)"), now used where such a day was
  shown as it came: a document's expiry, a shop's yearly re-check (seller
  overview and staff page), a weekly report's first day. A relative time
  ("3 hours ago") and the countdown in minutes have no calendar and stay as
  they were.
- **The API**: the one place it writes a date into words itself, the weekly
  Telegram message (S-26), names its week in Amharic as
  "7 ኅዳር 2019 (2026-11-16)" (`markx/core/ethiopian.py`, the same arithmetic);
  English as before. A week date that does not exist is now refused like any
  other unsafe value (it had only to look like a date).
- **Checked**: every day from 1 January 1900 to 31 December 2100 (73,414
  days) against ICU's Ethiopian calendar in Node, month names included; the
  part-of-day words against ICU's Amharic for every hour.

### 2. C-19: order again in one tap

- `POST /api/v1/me/orders/{order_id}/reorder` (`orders.service.reorder`):
  every item of one of the buyer's own orders goes back in their cart, the
  same shop's same offer, through `set_cart_item`, so every cart rule holds
  (the offer must still be on sale from a trading shop at the publishing
  level; 30 lines; 1 to 20 each). **The cart holds today's price**; the reply
  gives today's price and the price paid side by side. An item whose offer is
  no longer on sale, or that does not fit a full cart, is left out and named,
  with its product's page when that is shown (another shop may sell it).
  Another buyer's order and one that does not exist give the same "not
  found"; staff sessions are refused, as everywhere in shopping.
- The order page has an **Order again** button (`ReorderButton`): one tap and
  the buyer is on the cart. When a price changed since, or an item could not
  go back, the page first says so ("now ETB 19,000 (you paid ETB 18,500)") with
  a link to the cart. The cart re-checks prices and stock as always (D.10).

### 3. C-21: the price-history chart on a product page

- `GET /api/v1/catalog/products/{slug}/price-history?variant_id=`
  (`offers.selectors.price_history`): for one version (the first active one
  without `variant_id`) and each condition, the **lowest price day by day**
  over the last 90 days, from the prices already recorded
  (`offer_price_history`: every offer's first price and every change).
  Drawn from the offers a buyer can see today, the same ones the offers table
  lists; an offer counts from the day it was made, at its price at the end of
  each day in Addis Ababa (today: now). Each series holds only the days its
  lowest price changed, with today's, the lowest and the highest. **Nothing
  is stored**: like the best offer, it is read, never kept.
- The product page draws it on the server (`PriceHistoryChart`, plain SVG,
  no script, readable without JavaScript): one small step chart per
  condition, so a line is never told apart by its colour alone; the highest
  and lowest prices on the axis; today's, the lowest and the highest in words;
  a native tooltip on each step; every value in a table under "Show the prices
  as a table". The line colour (`#2a78d6`) passes the colour checks of the
  data-visualisation method against the white card (contrast 3:1 or more);
  Highland green and Clay stay for their own meanings (I.3). Price-drop alerts
  are Release 2 (D.27).

### 4. S-03: a shop uploads its own logo

- `POST /api/v1/seller/{seller_id}/store/logo` (a JPEG, PNG or WebP as the
  multipart field `file`) and `DELETE` the same path, both for the roles that
  edit the store page (owner and manager, C.3). The upload is checked like
  every picture (`images.clean_upload`: the upload limit, the bytes must be
  a picture), decoded and drawn again so nothing but its pixels survives (no
  camera metadata), fitted inside 256 pixels and written as one WebP file of
  at most 40 KB in the public store, under an unguessable key with no
  personal data (`markx/sellers/logos.py`). The old logo's file stays (no
  feature deletes a file). Both are audited (`store.logo_set`,
  `store.logo_removed`).
- `StoreOut` and `PublicStoreOut` carry `logo_url` (null without one). The
  store settings page shows it with an upload and a remove button; the public
  shop page shows it beside the name.
- **The backup and the copy tool know a logo is a file to keep.** Before,
  `backup/references.py` counted any `stores.logo_key` as an *unclassified*
  reference, which makes every backup set incomplete: a shop's first logo
  would have stopped complete backups. A logo is now a public file reference
  (`store_logo`), and `scripts/copy_files_to_object_storage.py` copies it.

### 5. S-11: a shop's own customers

- `GET /api/v1/seller/{seller_id}/customers?q=&limit=` for the roles that
  see buyers' contacts (owner, manager, orders; C.3), under `require_seller`,
  so the isolation test attacks it like every seller route.
- **Only what the shop's own order pages already show it**: built from its
  seller orders whose buyer details are visible now (`contact_visible`:
  confirmed by the shop, not ended without delivery), grouped by the phone
  number those pages show. A buyer's account is never named or linked;
  nothing from another shop, and nothing the order page would hide (an order
  not yet confirmed, or one that ended undelivered, adds nothing). Each
  customer: the name and area of their latest order, their phone, how many
  orders and how many completed, the first and last order times, and links
  to their latest orders. Newest first; a name or at least three digits of a
  phone number finds one.
- The seller dashboard has a **Customers** screen (menu: the same roles), its
  explanation in both languages.

### PROVISIONAL values, for the founder to confirm

- **P-106-1** In Amharic, every date is written Ethiopian first with the
  Gregorian date in brackets, and every time on the Ethiopian clock after
  its part of the day, always, with no switch; English is Gregorian. The
  exact words and order are for the native editor's review (blueprint I.3).
- **P-106-2** The price chart looks back 90 days, from the offers on sale
  today, at each day's closing price in Addis Ababa, one chart per condition.
- **P-106-3** Order again: a line already in the cart keeps the larger of its
  quantity and the order's (tapping twice never doubles anything); any of the
  buyer's orders, whatever its state, can be ordered again; the buyer goes
  straight to the cart unless a price changed or an item could not go back.
- **P-106-4** The customer list groups by the phone number shown, names each
  customer's latest 5 orders, shows 200 at a time (500 at most) and is for the
  roles that see buyers' contacts.
- **P-106-5** A logo is drawn within 256 pixels and 40 KB as WebP; a shop may
  send 20 an hour.

### Not built

- Staff cannot take a single shop's logo down (they can suspend the shop,
  or act on a report about the store, C-30); a logo moderation queue like
  the pictures' (AD-03) would be the next step if one is ever needed.
- The logo is shown on the shop's page only, not on offer rows or cards.
- The chart has no offers that are paused or removed today (their history
  is kept and could be added); the customer list has no export.
- The Amharic words of all five features wait for the native editor, like
  every other Amharic text (I.3).

### Changed

`apps/api/markx/core/ethiopian.py` (new), `markx/notifications/texts.py`,
`markx/orders/` (`service.py`, `selectors.py`, `router.py`, `schemas.py`),
`markx/offers/` (`selectors.py`, `router.py`, `schemas.py`),
`markx/sellers/` (`logos.py` new, `service.py`, `router.py`, `schemas.py`),
`markx/backup/references.py`, `scripts/copy_files_to_object_storage.py`,
both OpenAPI copies and the web app's types; `apps/web/src/lib/`
(`ethiopian.ts`, `price-chart.ts` new; `format.ts`, `api/types.ts`),
`src/components/` (`PriceHistoryChart.tsx`, `ReorderButton.tsx`,
`seller/StoreLogo.tsx` new), the product, order, public store, store
settings, seller overview, documents, performance and staff seller pages,
`seller/[sellerId]/customers/page.tsx` (new), the seller menu, both message
files, the buyer and seller-dashboard journeys.

### Tests

- New, all failing on the old code (a checkout of `6378764` with only the new
  test files): `tests/api/test_d106_release1_features.py` (16 tests: 16 of 16
  fail), `tests/unit/test_ethiopian_calendar.py` (16 tests; the module does
  not exist there), and in the web app `src/lib/ethiopian.test.ts` and
  `src/lib/price-chart.test.ts` (new modules), 4 new cases in
  `src/lib/format.test.ts` (3 of them fail on the old `format.ts`; the fourth
  guards the English that must not change).
- Changed: `src/app/[lang]/seller/[sellerId]/menu.test.ts` lists the new
  Customers screen for the owner, the manager and the orders role (each
  role's exact screens are still checked; nothing was removed).
- The journeys: the buyer journey checks the chart on the product page, the
  shop's customer list after it accepts, and "Order again" to the cart; the
  seller-dashboard journey uploads a logo and sees it on the public page, and
  checks the Customers screen at 360 pixels in both languages.

## D-107 Five Release 1 features: the total to the door and delivery speed in search (C-03), a gate photo on an address (C-08), lite mode (C-12), photos made smaller on the phone (S-06), share cards and a QR code (S-10)

22 November 2026. Branch `claude/release-1-five-features-g0sl7o`, from `main`
at `e1849be` (the merge of pull request #14) with the complete history; no
other pull request was open. **Follows** the blueprint: D.8 and D.27 (C-03),
D.10, G.2 and the `addresses` table (C-08), D.1 and I.1 (C-12), F.6 (S-06),
D.4, B and E.2 (S-10). **One migration (0023).** **Nothing deployed; no
account, server, bucket, bot or paid resource.** Business choices are safe
defaults marked PROVISIONAL (below); every new word is in English and
Amharic.

### 1. C-03: the total to the door and delivery speed in search

- `GET /api/v1/search` takes `zone` (a delivery zone's code),
  `max_delivery_hours` (1 to 720) and `sort=total`. With a zone the reply's
  new `delivered` list gives, for each result on the page that is delivered
  there, the **cheapest price plus delivery fee to the door**
  (`total_santim`) and the fastest promised time (`fastest_hours`);
  `zone_code` says which zone. `sort=total` orders by that total (products
  nobody delivers there come last; a paid placement never changes it, D.9);
  `max_delivery_hours` keeps only products delivered there within that time,
  and then the total is the cheapest way to have it in time. `sort=total` or
  a speed without a zone is refused (`zone_required`): a total or a time is
  never guessed for a buyer who has not said where.
- **Computed on every read, never stored** (like the best offer, D.7), from
  exactly the offers the product page lists: active, in stock, from a
  trading shop at the publishing level, on an active version. The total on a
  card is the product page's own total for that zone (tested). Collection at
  the shop is not delivery to the door and counts for neither.
- The product card schema is unchanged (an existing test checks it field by
  field); the totals are a separate list on the search reply.
- The search page has "Deliver to" (the areas) and "Delivery speed" (within
  24, 48 or 72 hours) and the sort "Lowest total to my door"; each card then
  says "ETB 11,350 to your door" and "Arrives within 24 hours", or "Not
  delivered to your area". Without an area, the page asks for one.

### 2. C-08: a photo of the buyer's gate on an address

- `POST /api/v1/me/addresses/{id}/gate-photo` (a JPEG, PNG or WebP as
  `file`) adds or replaces it; `DELETE` the same path removes it from the
  address. `AddressOut.gate_photo_url` is a five-minute link for the buyer.
- **Stored privately, like problem photos** (`markx/images/gate_photos.py`):
  the upload is checked like every picture (`clean_upload`: the upload limit,
  the bytes must be a picture), decoded and written again as WebP within
  1,200 pixels and 300 KB, so nothing but its pixels survives (**no camera
  metadata, no location**), into private storage under an unguessable key.
  Migration 0023: `gate_photos` is append-only (a trigger refuses UPDATE and
  DELETE; the application role has neither), and `addresses.gate_photo_id`
  has a foreign key on (photo, owner), so the database refuses an address
  holding another buyer's photo. A replaced or removed photo's file stays:
  each order keeps the photo's id in its address snapshot, so an order
  always shows the photo it was placed with.
- **Only the people delivering that order see it.** Opened only through a
  five-minute link signed for the viewer (and, for a shop, the order), and
  the viewer must still be allowed when the file is fetched: the buyer who
  took it; or an active member of the order's shop in a role that handles
  orders **and** sees buyers' contacts (owner, manager, orders; C.3), while
  the shop is delivering it to the door: from its confirmation until the
  goods change hands (confirmed, paid, ready, out for delivery, delivery
  failed), by the shop's rider or the partner courier, **never for
  collection at the shop**. **Staff never see it** (they do not deliver; the
  dispatch board shows no address), nor does another shop (the isolation
  test attacks the new route automatically). Every view by a shop is audited
  (`gate_photo.viewed`); setting and removing are audited too.
  `SellerOrderOut.has_gate_photo` says when the shop's link
  (`GET /seller/{id}/orders/{id}/gate-photo`) will answer.
- The backup and the copy tool know gate photos are private files to keep
  (`gate_photo`), as D-106 learnt with the logo.
- The account page has the photo under each saved address (upload, see,
  remove, made smaller on the phone first); the shop's order page shows "The
  buyer's gate" with "Do not save or share it."

### 3. C-12: lite mode

- A remembered choice (`markx_lite` cookie) set by a plain link in the
  footer, "Lite mode (smaller pictures)", which works without JavaScript: the
  switch route sets it and goes back to the page it came from (the path of
  the Referer, judged by `safeNext`, never another site). **Without a
  choice, the phone's own data-saver setting decides** (`Save-Data: on`).
- In lite mode: no photos on product cards; the product page shows one small
  picture (the 320-pixel thumbnail, at most 30 KB) instead of the large one,
  and its picture strips (more pictures, shops' photos) become plain links.
  There was already no carousel anywhere (D.1).

### 4. S-06: photos made smaller on the phone

- Every photo upload (a shop's real photos and logo, problem evidence, the
  gate photo, staff catalogue pictures) is drawn again on the phone before
  it is sent (`src/lib/shrink-photo.ts`): upright, within 1,600 pixels (the
  server's largest size, so nothing it keeps is lost), JPEG at quality 0.82,
  a PNG or WebP as WebP (transparency kept). Drawing it again also leaves the
  location and camera data behind. A photo already within the size and under
  400 KB, anything that is not a picture, and anything the browser cannot
  draw are sent unchanged; the smaller file is sent only if it is smaller.
- **The server's own checks are unchanged**: its size limit, that the bytes
  are a picture, the metadata stripping and its own sizes (D-062).
- Sellers' identity and licence documents are **not** shrunk: staff must be
  able to read them.

### 5. S-10: share cards and a QR code for a shop and its products

- The shop page and the product page each have a "Share" link to a share
  page (`/[lang]/s/{slug}/share`, `/[lang]/p/{slug}/share`); the shop's own
  store settings page shows the same panel once its public page exists. The
  panel: the link, Telegram's own share page (`t.me/share/url`), the **QR
  code** (an SVG picture from `/[lang]/s|p/{slug}/qr`, or `?download=1` to
  save and print), and **two share cards** saved as PNG: 1200 × 630 for a
  Telegram post and 1080 × 1920 for TikTok or a story. A card shows the
  wordmark, the name, the shop's level and "Verified on MarkX" from Level 2
  (or the product's lowest price and number of shops), the QR code, "Scan to
  open on MarkX" and the address, in the page's language.
- The QR code is MarkX's own small encoder (`src/lib/qr.ts`: byte mode,
  error correction level M, versions 1 to 10, the lowest-penalty mask),
  written here because no QR package is installed and adding one was not
  allowed in this session. Its parts are checked against the standard's own
  published values (the format strings of level M, the version strings of
  versions 7 to 10, the Reed-Solomon worked example), and every code is read
  back by a separate reader in the test (mask, zigzag, error correction by
  evaluating each block, the bytes), versions 3 to 10. **Not checked with a
  phone camera** (no camera here): a scan with a real phone is the first
  thing to do on the test device.
- The cards are drawn on the phone, on the share page only, with Noto Sans
  Ethiopic Bold (`apps/web/assets/fonts`, the SIL Open Font License, from
  the npm package `@fontsource/noto-sans-ethiopic` 5.3.0, files unchanged,
  checksums in its README), so Amharic is drawn the same on every phone; the
  font is fetched only when a card is made.
- The QR code and the link use the site's public address
  (`MARKX_PUBLIC_ORIGIN`, which the production web server already refuses
  to start without), never the request's Host header. The journeys workflow
  now sets the same value the Compose API has.

### Page weight (blueprint D.26): what was tried and why the design changed

Main's product page was already 208.9 KB against its 210 KB ceiling. The
first version (cards drawn on the server by `next/og`, the share panel and a
link preview on the product page) measured 215.7 KB. Found by bisecting
builds: `next/og` loads its renderer as an asynchronous module, which makes
Turbopack add 0.45 KB of start-up script to **every** page, wherever it is
used; and the link-preview tags were repeated in every prefetched product
and shop page. So the cards are drawn on the phone, the share panel is on
its own page, and there is no link-preview picture (Telegram shows the
page's title). **The ceiling was not changed.** Result, same machine, same
demo data: product 209.2 KB (main 208.9), its script identical to main's
(156.9 KB).

### 6. A CI failure on this pull request, and its cause: the off-server drill's stand-in code was a replay

CI on `9869524` (the documents-only commit) failed in one step, the
off-server recovery drill: every restore check passed, then "a staff member
signs in to the restored copy" was refused (HTTP 401,
`staff_credentials_invalid`). The same code had passed on `590bee9`. **The
cause is in the D-105 drill harness, not in this pull request's features.**
The demo data signs its staff member in with an authenticator code, so the
database remembers that 30-second step (`staff_members.totp_last_step`, the
guard that refuses a replayed code); the backup made seconds later carries
it into the restored copy; the drill's stand-in authenticator
(`MARKX_DRILL_STAFF_TOTP_SECRET`, CI and the rehearsal only) then computed
the code of the current step, and when that was still the same step the API
rightly refused it as a replay. Whether it failed depended on where the
30-second boundary fell (here the seed signed in at about 14:10:05 and the
drill at about 14:10:18). The existing test never signs in before the
backup, so it could not see this.

**Fix:** `markx.backup.__main__.fresh_code` makes the stand-in wait for the
next 30-second step before reading its code, as a person reading their
phone after the restore would (at most about 31 seconds). The sign-in and
every check on it are exactly as before; the replay guard is untouched; a
person typing a code is not affected. **Proof:** the new
`tests/storage/test_d107_drill_fresh_code.py` reproduces CI's order (a
sign-in, a backup and the drill inside one step): it **fails on the old
line** ("DRILL FAILED", the same refusal) and passes with the fix, with a
unit test of the waiting itself.

### PROVISIONAL values, for the founder to confirm

- **P-107-1** Search: the speed choices are within 24, 48 and 72 hours; only
  delivery to the door (the shop's rider, the partner courier) counts for the
  total and the speed, never collection; with a speed chosen, the total is
  the cheapest way to have it in time; without an area the page asks for one.
- **P-107-2** A gate photo is kept within 1,200 pixels and 300 KB as WebP;
  one per address; a replaced one's file is kept for the orders placed with
  it.
- **P-107-3** The shop sees the gate photo from its confirmation until the
  goods change hands (confirmed, paid, ready, out for delivery, delivery
  failed), only by rider or courier, only for the owner, manager and orders
  roles; staff never.
- **P-107-4** A buyer may send 20 gate photos an hour.
- **P-107-5** Photos on the phone: within 1,600 pixels, JPEG quality 0.82,
  PNG and WebP as WebP; left alone within 1,600 pixels and 400 KB;
  documents never.
- **P-107-6** Lite mode turns on by itself with the phone's data saver and is
  otherwise off; the choice is remembered a year.
- **P-107-7** The share cards: 1200 × 630 and 1080 × 1920, with the name,
  the level ("verified" from Level 2) or the lowest price and number of
  shops, the QR code and the address; no link-preview picture.

### Not built

- The shareable **price list** of S-10 (blueprint D.4) was not asked for in
  this task and is not built.
- No link-preview picture when a link is pasted into Telegram (page weight,
  above); the cards are saved and posted instead.
- The gate photo is added from the account page (saved addresses), not in
  the checkout's new-address form.
- The QR code has not been scanned with a real phone (above).
- The Amharic words of all five features wait for the native editor (I.3).

### Changed

API: `markx/search/` (`selectors.py`, `router.py`, `schemas.py`),
`markx/images/gate_photos.py` (new), `markx/images/` (`router.py`,
`schemas.py`), `markx/accounts/` (`models.py`, `router.py`, `schemas.py`),
`markx/orders/` (`service.py`, `selectors.py`, `schemas.py`),
`markx/backup/references.py`, `scripts/copy_files_to_object_storage.py`,
migration `0023`, both OpenAPI copies, `markx/backup/__main__.py` (the
drill's stand-in code, section 6). Web: `src/lib/` (`lite.ts`,
`lite-server.ts`, `shrink-photo.ts`, `qr.ts`, `qr-file.ts`, `share.ts`,
`share-data.ts` new; `api/types.ts`, the generated schema),
`src/components/` (`ShareCards.tsx`, `SharePanel.tsx` new; `ProductCard`,
`PhotoUpload`, `AccountForms`, `SiteFooter`, `admin/StaffActions`), the
search, home, product, shop, account, seller order and store settings
pages, the lite switch, QR and share routes (new), both message files,
`assets/fonts` (new), `e2e/release1-d107.mjs` (new) and its step in
`.github/workflows/journeys.yml`.

### Tests

- **New, all failing on the old code**: `tests/api/test_d107_release1_features.py`
  (16 tests). On `e1849be` the file cannot be imported (`GatePhoto` is new);
  with that one import guarded in a throwaway copy, **16 of 16 fail** (for
  example `sort` "should be 'relevance', 'price' or 'freshness'", and
  `validation_failed` instead of `zone_required`). The web app's
  `src/lib/lite.test.ts`, `shrink-photo.test.ts`, `qr.test.ts` and
  `share.test.ts` test new modules, which do not exist on the old code.
- **No existing test or check was changed, loosened or removed.** The page
  weight ceilings are as they were. The journeys workflow gained one step
  and one job-wide value (`MARKX_PUBLIC_ORIGIN`, the address the share links
  need); every existing step is unchanged.
- The new journey (`e2e/release1-d107.mjs`), run here against the demo data:
  totals to the door lowest first (ETB 11,350, 11,850, 13,050, 18,050,
  46,150); without an area the page asks for one; lite mode on and off,
  remembered, and on by itself with Save-Data; both cards saved at exactly
  1200 × 630 and 1080 × 1920; an 18.0 MB 3000 × 2000 picture sent as a
  1,027 KB WebP (random noise, the worst case for compression); the buyer
  sees their gate photo; the shop sees it only after accepting. It cancels
  nothing: a first version did, and that started the demo buyer's
  cancellation cooldown (D-099) for the journeys after it, so it now runs
  after every journey that places an order and leaves its order accepted.

## D-108 Guest checkout (C-07) and limits for new accounts (AD-13), as the founder decided

24 and 25 November 2026. Branch `claude/lucid-babbage-38jzfq`, from `main`
at `5794234` (the merge of pull request #15) with the complete history; no
pull request was open. **Follows** the blueprint D.2, D.10, D.22, H.3 and
H.4 (C-07, AD-13), as the founder decided them for sign-in by Telegram only
(SI-1). **One migration (0024).** **Nothing deployed; no account, server,
bot, SMS, bucket or paid resource; nothing sent to Telegram or by SMS.**
Business choices are safe defaults marked PROVISIONAL (P-108-1 to
P-108-8, below); every new word is in English and Amharic.

### 0. The founder's decisions

**C-07 (the task, 24 November 2026).** Sign-in is Telegram only, so a buyer
without Telegram, or anyone while Telegram is blocked, may order as a guest
with a name, a delivery address and a phone number. The number is not
confirmed, so a guest order must never open, join or reveal an existing
account that has that number. Pay at the door only. The existing buying
limits and the bot check apply to guests, counted per phone number and per
network address. The guest gets the secure tracking link and nothing more.
The seller sees exactly what they see for a signed-in buyer.

**AD-13 (the task).** Order-value caps, pay-at-the-door eligibility and caps
for brand-new accounts, as the blueprint describes; guests always count as
brand-new.

**Two answers given during the work (24 November 2026):**

1. *Strict caps for every new account would have made existing tests fail*
   (every test buyer, and the demo buyer of the browser journeys, is a
   brand-new account; existing tests have one place an order of ETB 197,650
   and hold three open orders), and the task forbids changing any existing
   test. **The founder chose: guests get the strict caps from the first
   day; signed-in accounts count as new for 0 days until the founder sets
   the value in the admin settings screen (30 recommended).** Both are
   built and tested.
2. *"Pay at the door only": may a guest collect at the shop?* **The founder
   chose delivery to the door only; a setting lets operations allow
   collection later** (`guest_checkout.shop_collection`, off).

### 1. What this changes in earlier decisions, said plainly

- **Blueprint C-07 and D.2** say "the account is created at the first
  order", and D.10 "the phone number is verified before the first order";
  B.3 has the guest's number "confirmed by code or by Telegram". Since SI-1
  there is no code to confirm it with, and the founder's rule is the
  opposite: **no account is created and the number is not confirmed.** The
  blueprint is left as it is (one source, byte for byte); this record is the
  change.
- **D-036** ("there is no separate guest order path; the order is placed by
  a signed-in account") is replaced for guests: there is now a guest path.
- **D-048** ("the tracking link never shows the handover code") still holds
  for every signed-in buyer's order (its test is unchanged). **For a guest's
  order the link shows the code** (P-108-7), section 6.
- **D-010** (an idempotency key is unique per buyer): for a guest, per
  browser.

### 2. What a guest experiences

1. A visitor fills a cart as before. "Continue to checkout" leads to the
   sign-in page, which now ends with **"No Telegram, or Telegram not
   working? Order as a guest"** (a link: the sign-in page still has no
   phone field when SMS is off, as the Telegram journey checks).
2. `/[lang]/checkout/guest`: name, phone number for the delivery, area,
   landmark, rider's notes; "No account is made, and MarkX does not check
   this number". Each shop's part is **delivered to the door** (the shop's
   rider or a partner courier); collection is not offered. Payment: cash,
   telebirr, bank transfer or ETHQR, **at the door**. "As a guest you pay at
   the door, for orders up to ETB 50,000." Review (the shop's legal name,
   address, return policy, every total, C-27), the bot check (Turnstile,
   when the site has a key), **Place order**.
3. The answer: **"Your order MX-… is placed. Save this link now. It is the
   only way to follow your order and to see your handover code: MarkX cannot
   send it to you again."**, the link, "Open your order page", "Copy the
   link". No session, no account, no sign-in.
4. The order page by the link: the timeline, the shop's phone once it
   confirms, the rider once on the way, **the handover code from "ready"
   until the handover**, with "Give this code only after you have inspected
   the goods", and "You ordered as a guest. This link is the only way back
   to your order: keep it." No action: no cancelling, no "the goods are
   right", no problem report, no review. The problem window passes and the
   part completes by itself. (**Changed by D-109:** a guest may cancel a
   shop's part from the link before the shop answers, F-28.)
5. Refusals are words in the guest's language: above ETB 50,000, one open
   order per number, too many guest orders from one connection, collection
   chosen, guest checkout switched off, a signed-in browser, the bot check.

### 3. Never open, join or reveal the account that has the number

A guest order belongs to **no account**: `orders.buyer_user_id` is empty
and the order carries `guest_phone` (the number as typed, normalised, not
confirmed). Nothing in the guest path looks an account up by that number
(it reads only the caller's own session, to send a signed-in person to
their own checkout):

- **Not opened:** no session, no cookie but the cart's, `/me` stays 401.
- **Not joined:** no user row is made or found; the order is in no
  account's list; signing in later with that number (by the account holder,
  or by a new person: a new, empty account) brings none of it; **the
  account's orders never count against the guest's limits, and guest orders
  never count against the account's** (both ways tested: a guest with the
  number of an account holding an open order still orders, which a shared
  count of one open order would have refused, and so revealed); no message
  goes to the account about it (`_notify_buyer` and the next-best offer do
  nothing for a guest order).
- **Not revealed:** every answer is the same whether the number has an
  account or not. The test places one guest order with an account's number
  and one with an unused number and compares the answers and the tracking
  pages: identical but for the order's own identifiers, and neither holds
  the account's name, address, order code or id.
- The database holds it: `ck_orders_one_buyer` (an account or a guest,
  never both, never neither).

### 4. Pay at the door only

- The guest request has no field for a payment mode (an extra field is a
  422); the order is a direct order, paid to the shop at the handover (D-087:
  a payment is recorded only from the handover on). **The database refuses a
  guest order paid any other way** (`ck_orders_guest_pays_at_the_door`), so
  Protected prepayment (Release 2) can never reach a guest by mistake.
- Delivery to the door only: a part chosen for collection is refused
  (`guest_collection_unavailable`), at the review step and at placing, until
  operations switch `guest_checkout.shop_collection` on (the founder's
  decision). A shop that only offers collection cannot be ordered from as a
  guest.

### 5. The buying limits and the bot check, per number and per address

`place_guest_order`, in this order, all before any stock is held:

- the repeat test (section 6), then the guest's details checked as a saved
  address is (Ethiopian mobile number, active area, a whole map pin or
  none);
- **the bot check:** Turnstile with its own action, `guest_checkout`, so a
  token solved for signing in is refused, and the other way round; before
  anything is counted or held;
- **30 guest checkouts an hour per number** (as for an account) and
  `guest_checkout.attempts_per_ip_per_hour` (30) per network address;
- advisory locks on the number, then the address (after the browser's cart,
  before sellers and offers), so two browsers cannot slip under a limit
  together (tested five times each);
- the order value cap `orders.max_order_value_santim` and a guest's own
  (section 8);
- open orders: `orders.max_open_direct_orders` (3) and the new-buyer cap
  (1) **per number**, and `guest_checkout.max_open_orders_per_ip` (3) **per
  network address**, each over guest orders only;
- units waiting for a shop's answer (D-099): 5 of an offer and 10 of a shop
  **per number and per address**, with the existing settings;
- the cancellation cool-down counts a buyer's own cancellations; a guest
  cannot cancel, so it never applies.

The order never keeps the network address: only a keyed hash of it
(`guest_network_hash`, HMAC with the server's secret), enough to count. The
hourly try counters are keyed on the number and the address themselves,
like every other rate limit (`checkout:guest:phone:…`,
`checkout:guest:ip:…`), and deleted a day after their hour (F-08).
Refusals per address say nothing about whose orders they are.

### 6. The tracking link and nothing more

(**Changed by D-109:** and one action, cancelling a shop's part before the
shop answers, F-28.)

- The answer to placing is exactly `{order_code, tracking_path,
  tracking_expires_at}` (sixty days, D-048), `no-store`. Nothing is sent to
  the guest afterwards: no Telegram, no SMS, no in-app message; **the
  number is never used to send anything**, since it may be someone else's.
- **The handover code on a guest's link (PROVISIONAL P-108-7).** Without it
  a guest could never receive the goods: only the buyer's code closes a
  delivery (C-15). The blueprint's own D.14 has the page "that opens from a
  secure link without signing in" show "the handover code with a warning to
  share it only at handover"; D-048 left the code off the link only because
  a signed-in buyer's link travels by Telegram or SMS and the buyer has
  their signed-in page. A guest's link is handed to nobody but the browser
  that placed the order. The code shows from `ready` until the handover, as
  on the signed-in page; the shop's views, the staff desk and every list
  still leave it out.
- The same submission sent again from the same browser returns the same
  order (200), **before the bot check**, whose one-time token the first
  attempt used; the key is unique per browser
  (`uq_orders_guest_browser_idempotency_key`, on the SHA-256 of the cart's
  secret, as the cart row keeps it), so another browser's identical key gets
  its own order and never the first's link.

### 7. The shop sees exactly what it sees for a signed-in buyer

Both kinds of order are written by one helper, `_write_order`, with the
same address copy: the shop's views read only that copy, so a guest's
order looks the same in the list, the detail, the customer list (S-11) and
the alerts. Tested: a signed-in buyer's order and a guest's with the same
details give the same JSON for the shop, before and after accepting, but
for the identifiers and times. `is_guest` is on the buyer's, the tracking
and the staff views only (staff, for pattern review), never the shop's.

### 8. AD-13: limits for brand-new buyers

- **Who is brand-new:** a guest, always; a signed-in account while it is
  younger than `risk.new_account_days` (0 until the founder sets it;
  recommended 30), counted from when the account was created (P-108-8).
- **Order-value cap:** a brand-new buyer pays at the door for orders up to
  `risk.new_account_max_order_value_santim` (ETB 50,000); everyone else up
  to `orders.max_order_value_santim` (ETB 300,000, unchanged).
- **Caps:** at most `risk.new_account_max_open_orders` (1) open
  pay-at-the-door orders at a time; everyone else 3 (unchanged).
- **Pay-at-the-door eligibility:** in Release 1 paying at the door is the
  only way to pay, so an order outside a brand-new buyer's limits is not
  eligible and is refused, saying why (`new_buyer_order_too_large`,
  `new_buyer_too_many_open_orders`, with the limit in the details); nothing
  is held for it. When Protected prepayment exists (Release 2) such an order
  could be offered prepayment instead; a guest never.
- All are risk limits operations may change (C.4), audit-logged.

### 9. On the web

`/[lang]/checkout/guest` (`GuestCheckout.tsx`, `lib/guest-checkout.ts`),
the sign-in page's link, the handover code and the guest note on the
tracking page, the Turnstile widget's action, and the words in both
message files. The guest page's own refusals are in its own section
(`guest.errors`), not in the shared `apiErrors`: the product page carries
the shared section whole, and D-107 left it about 1 KB under its ceiling.

### 10. PROVISIONAL values (THE FOUNDER MUST CONFIRM OR CHANGE THEM BEFORE MARKX GOES LIVE)

Settings in `markx/core/settings_store.py`, each marked `PROVISIONAL
(P-108-n)` there and in Amharic on the admin settings screen; the three
rules marked where they live; all checked by
`tests/api/test_d108_new_account_limits.py`. Operations may change every
setting; each change is audit-logged.

| | Setting or rule | Value | Why this value |
| --- | --- | --- | --- |
| P-108-1 | `risk.new_account_days` | 0 days (recommended 30); **replaced by D-109:** 30 days, the founder's decision (F-27) | The founder's choice: no existing test changes, and the founder decides when signed-in accounts get the caps. 30 days covers a first order's delivery and problem window several times |
| P-108-2 | `risk.new_account_max_order_value_santim` | ETB 50,000 | Accessories and most entry and mid-range phones fit; a flagship phone or a laptop on a first order, to an address nobody confirmed, waits for Telegram sign-in or an older account |
| P-108-3 | `risk.new_account_max_open_orders` | 1 | One order out at the door at a time until the buyer has received one; a prankster cannot send three shops' riders at once |
| P-108-4 | `guest_checkout.max_open_orders_per_ip` | 3 | The existing per-buyer value, counted per address as the founder asked. **Many customers may share one mobile address (UNKNOWN how many); raise this first if honest guests are refused, above all while Telegram is blocked** |
| P-108-5 | `guest_checkout.attempts_per_ip_per_hour` | 30 | The existing per-buyer checkout rate, per address |
| P-108-6 | (a rule) per-number and per-address counts | The existing values: 3 open orders, 5 units of an offer and 10 of a shop waiting for an answer, 30 checkouts an hour per number; the address exact, kept as a keyed hash; no cool-down (a guest cannot cancel; **changed by D-109:** a guest may cancel, so the cool-down counts per number and per address, P-109-1) | The founder's "counted per phone number and per network address", with the existing limits |
| P-108-7 | (a rule) the handover code on a guest's link | From `ready` until the handover, as on the signed-in page | Section 6: otherwise a guest cannot receive the goods |
| P-108-8 | (a rule) an account's age | From `users.created_at`; a completed order does not end it sooner | What "how long an account counts as new" says; an account made by an invitation counts from then |

The founder's decisions, not provisional: `guest_checkout.enabled` (on;
operations may switch it off in an abuse wave, orders already placed carry
on) and `guest_checkout.shop_collection` (off).

**How an honest person is affected.** A buyer with Telegram: not at all
until the founder sets P-108-1. A guest: one order at a time, up to ETB
50,000, delivered to the door and paid there; they must keep the link. A
shop: nothing new to learn.

### 11. Not built, and what remains risky

- **A lost link cannot be sent again.** MarkX has no confirmed way to reach
  a guest; sending the link to the typed number (when SMS returns) could
  send a stranger the order and its code. The page says so plainly (F-28).
- **A guest cannot cancel, confirm receipt, report a problem or review**
  ("nothing more"). Someone who changes their mind refuses at the door; a
  problem goes to the shop by phone (F-28).
- **Many guests behind one mobile address** may meet P-108-4 (F-29).
- **A shop could place guest orders to itself** to add completed orders to
  its record; it needs a number and an address per open order, the bot
  check and a real handover. The orders desk's answer marks a guest's order
  (`is_guest`; checked by hand on 25 November 2026, no test pins it), but
  the desk's screen does not show the mark yet; no automatic check is built.
- **A guest may type someone else's number**: the shop calls a stranger.
  Nothing joins the stranger's account, and nothing is sent to the number.
- **A guest's details live in the order** like any buyer's (orders are
  never deleted); a guest has no account page for data requests (C-28).
- The Amharic words await the native editor, as all Amharic does (I.3).
- Not tested against Cloudflare itself (as D-085); the guest page's widget
  is exercised only without a site key on this machine.

### 12. Tests

- **New, every one failing on `main` at `5794234`:**
  `tests/api/test_d108_guest_checkout.py` (22),
  `tests/api/test_d108_new_account_limits.py` (6),
  `tests/db/test_d108_guest_limit_contention.py` (11, two races run five
  times each and ten guests at once): **39 of 39 fail** on the old code (the
  routes answer 404, `place_guest_order` and the settings do not exist).
  Web: `src/lib/guest-checkout.test.ts` (21), which cannot load on the old
  code (its module is new). The browser journey
  `apps/web/e2e/guest-checkout.mjs`, added to the journeys workflow after
  the D-107 journey: a guest orders at 360 px, keeps the link, the shop
  accepts and sends it, the link shows the code, the shop hands over with
  it; axe on every page, English and Amharic.
- The test the founder asked for by name:
  `test_a_guest_using_the_number_of_an_existing_account_sees_nothing_of_it`.
- **No existing test or check was changed, loosened or removed**; the
  journeys workflow gained one step; every existing step is unchanged.

### 13. Changed

API: `markx/orders/` (`models.py`, `service.py`, `selectors.py`,
`schemas.py`, `router.py`), `markx/core/` (`botcheck.py`,
`settings_store.py`, `settings_am.py`), `markx/admin/service.py` (the risk
limits), migration `0024`, both OpenAPI copies. Web: `src/components/`
(`GuestCheckout.tsx` new, `TurnstileWidget.tsx`), `src/lib/`
(`guest-checkout.ts` new, `session.ts`, the generated schema), the guest
checkout page (new), the sign-in and tracking pages, both message files,
`e2e/guest-checkout.mjs` (new) and its step in
`.github/workflows/journeys.yml`. Documents: this entry, `AGENTS.md` (the
lock order), `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_STATUS.md`,
`docs/HANDOFF.md`.

## D-109 F-27 and F-28, decided by the founder: new accounts have the limits for their first 30 days; a guest may cancel before the shop answers

Branch `claude/lucid-babbage-38jzfq`, continued from `main` at `e06bd83`
(the merge of pull request #16, D-108, on the founder's written approval of
25 November 2026, without the independent review, the founder's decision;
`main` passed CI #191 and Browser journeys #67 on it). One small pull
request into `main`; the founder approved its merge in advance, a normal
merge pinned to its last commit, once every check on that commit passes.
**No migration. Nothing deployed; no server, account, bot, SMS, bucket or
paid resource.**

### 0. The founder's decisions (25 November 2026)

1. **F-27:** brand-new signed-in accounts get the new-buyer limits for their
   first 30 days. P-108-1 is 30.
2. **F-28:** a guest may cancel their own order from the tracking link, but
   only before the shop answers. The held stock is released at once. After
   the shop answers, there is no cancel button. Every message in English and
   Amharic.

The rules as before: no test or check weakened or removed; new tests fail on
the old code and pass on the new.

### 1. F-27: 30 days

- `risk.new_account_days` defaults to **30** (it was 0). Its description,
  in both languages, now says it is the founder's decision (F-27), not
  PROVISIONAL. Operations may still change it (0 to 365) in the settings
  screen; each change is audit-logged.
- An account made less than 30 days ago (`is_brand_new`) pays at the door
  only for orders up to ETB 50,000 (P-108-2) and holds one open
  pay-at-the-door order at a time (P-108-3); from day 30 on, the ordinary
  limits (ETB 300,000, three open orders). A guest always counts as new.
  P-108-8 (an account's age counts from its creation; a completed order does
  not end it sooner) is unchanged and still PROVISIONAL.
- **At the launch** every account is new, so for the first month nobody who
  signs in can pay at the door for more than ETB 50,000 at once or hold two
  open orders (F-27's warning). Operations can lower the days at once if
  that holds honest buyers back.

### 2. F-27, the existing tests and the browser journeys

**Measured:** the whole suite with only the default changed to 30: **74 of
the 2,219 tests fail** (2,145 pass). Nearly all sign a test account in a
moment before it orders, then place an order above ETB 50,000 (the shared
test shop's two-shop order is ETB 55,050) or hold several open orders, to
test other rules: stock limits, two-shop orders, deliveries, reviews, the
dashboard, the races. The 30 days refuse those orders at checkout, as they
should. Three ways were weighed:

- (a) **chosen:** the tests written before D-109 run with the days at 0, as
  when they were written;
- (b) refused: every test account made a year old: it would change what
  other tests read about accounts (the dashboard counts new accounts by when
  they were made);
- (c) refused: the 74 tests edited one by one: the largest change, to tests
  that check other rules.

So `tests/conftest.py` gains **one autouse fixture that stores
`risk.new_account_days = 0` at the start of every test**, unless the test
carries the marker `founders_new_account_days`, which runs it with the
shipped 30 days. Each of the 74 runs unchanged and checks exactly what it
checked. The three new test files carry the marker. The code ships 30; the
fixture sets only the test database.

**Existing tests changed because the founder's decisions changed what they
assert** (each stays at least as strict):

- `tests/api/test_d108_new_account_limits.py::test_the_new_buyer_limits_are_provisional_settings`:
  P-108-1 is no longer required to be PROVISIONAL with 0 days; it is now
  required to be the founder's decision in both languages, with 30 days.
  P-108-2 to P-108-5 must still be PROVISIONAL. The module's docstring says
  why.
- `tests/api/test_d108_guest_checkout.py::test_a_guest_orders_with_a_name_an_address_and_a_phone_and_gets_only_the_tracking_link`
  and `::test_a_guest_has_no_way_to_act_on_the_order`: on a guest's order
  the shop has not answered, `can_cancel` must now be true (F-28); every
  other check is unchanged, and "no other action" (no "the goods are right",
  no problem report, no signed-in route) still holds.

No other existing test changed.

**The browser journeys.** Their demo buyer (0911000950) is made by the
demo data a moment before they run, and orders in seven of them; with 30
days it would be refused. The demo data (`scripts/seed_demo.py`, DEMO data
only) now makes the demo buyer a customer of 90 days. An account a journey
makes itself (the Telegram sign-in's) gets the 30 days like any new buyer;
it orders one phone, under ETB 50,000. No journey step changed for F-27.

### 3. F-28: a guest cancels from the link

- **What a guest sees.** On the tracking page of a guest's order, each
  shop's part still waiting for the shop's answer (`placed`) shows **"Cancel
  this part"**, with "You can cancel this shop's part until the shop
  answers. Its goods go back on sale at once." The button asks once more:
  "Cancel your order from {shop}? The shop is told at once, and this cannot
  be undone." **"Yes, cancel it"** or "Keep my order". The page then shows
  the part cancelled, with no button. Everything in Amharic too.
- **The API:** `POST /api/v1/track/{order_id}/seller-orders/{seller_order_id}/cancel`,
  with the tracking link's own `expires` and `signature`
  (`service.cancel_by_guest`). It:
  - opens the link as the page does: a forged or expired link gets 404
    `tracking_link_invalid`, another order's part 404 `order_not_found`;
  - refuses a signed-in buyer's order (409 `order_cannot_be_cancelled`):
    their link still never acts (D-048); they cancel from their own page as
    before;
  - locks the shop's part as the shop's answer locks it, and refuses unless
    it is still `placed` (409 `order_cannot_be_cancelled`): once the shop
    has accepted or declined, or the order expired unanswered, there is no
    button and the API refuses;
  - moves the part to `cancelled` as the buyer's own cancellation, by no
    account (reason `cancelled_by_buyer`), **releases its stock in the same
    transaction**, cancels its waiting shipment, and tells the shop's people
    with `order.cancelled_by_buyer`: the same words as for a signed-in
    buyer, so the shop's view stays the same (C-07);
  - answers with the link's page, `no-store`.
- Like every request that changes something, it needs the MarkX app's header
  and the site's own origin (H.2).
- The lock order is that of every cancellation: the seller order, then the
  stock.

### 4. The cancellation cool-down counts for guests (PROVISIONAL P-109-1)

D-108 left the cool-down off for guests "since a guest cannot cancel". Now a
guest can, so **the cool-down (D-099: three cancelled orders within 24
hours, P-099-5 and P-099-6) counts for guests per phone number and per
network address**, as every other buying limit does (D-108, P-108-6). Per
number: `cancellation_cooldown`, the accounts' own words. Per address:
`guest_network_cooldown`, "Several guest orders from your connection were
cancelled recently, so guest orders from it are paused for a while. Try
again later, or sign in with Telegram." (a guest refused for an address
they share may have cancelled nothing). An account's cancellations never
count against a guest with its number, nor a guest's against the account
(D-108, section 3). The values are the existing ones: PROVISIONAL **P-109-1**,
to be confirmed before going live, since many customers may share one
mobile address (F-29).

### 5. What this changes in earlier decisions, said plainly

- **D-108, section 2 item 4 and section 6** ("nothing more", "no
  cancelling"): a guest now has one action, cancelling a shop's part before
  the shop answers.
- **D-108, P-108-1:** 30 days, the founder's decision; no longer
  PROVISIONAL.
- **D-108, P-108-6** ("no cool-down, a guest cannot cancel"): the cool-down
  counts per number and per address (P-109-1).
- **D-048** holds for every signed-in buyer: their link never acts.

### 6. PROVISIONAL values (THE FOUNDER MUST CONFIRM OR CHANGE THEM BEFORE MARKX GOES LIVE)

| | Setting or rule | Value | Why this value |
| --- | --- | --- | --- |
| P-109-1 | (a rule) the cancellation cool-down for guests | Per phone number and per network address, with the existing values: three cancelled orders within 24 hours (P-099-5, P-099-6) | The founder's "the existing buying limits apply to guests, counted per phone number and per network address" (C-07); without it a guest could place and cancel without end, and the shop is told each time. **Raise it, or P-099-5, if honest guests behind one mobile address are refused (F-29)** |

The rule is marked `PROVISIONAL P-109-1` where it lives
(`markx/orders/service.py`, `place_guest_order`).

### 7. Not built, and what remains risky

- **A tracking link passed on** (forwarded in a chat) lets whoever holds it
  cancel the order before the shop answers. The link is the guest's only
  key (C-07); the second question guards against a slip of the finger, not
  against a person holding the link.
- A guest gives no reason when cancelling (a signed-in buyer may); the shop
  sees a buyer's cancellation either way.
- A guest still cannot confirm receipt, report a problem or review; F-28's
  options (c) and (d) were not chosen.
- Guests behind one shared mobile address (F-29) may now also meet the
  address's cool-down.
- The new Amharic words await the native editor, as all Amharic does.
- The local journey run left out the Telegram and Turnstile steps (they
  restart the API or the web app with other settings); CI runs them.

### 8. Tests

- **New:** `tests/api/test_d109_guest_cancel.py` (7),
  `tests/api/test_d109_new_account_days.py` (4) and
  `tests/db/test_d109_guest_cancel_contention.py` (10: two races, five
  rounds each): 21 API and database tests, run with the shipped 30 days;
  **21 of 21 fail on the old code** (`e06bd83`, with only the new test files
  and the new `tests/conftest.py`): the route answers 404, and
  `cancel_by_guest`, the 30 days and the P-109-1 mark do not exist there.
- **The whole suite on this branch: 2,242 passed, 0 failed, 0 skipped**
  (2,219 and the 23 new tests of that moment; the age cases were then
  joined into one test with the same checks, and the P-109-1 mark test was
  added; those files: 11 passed). Details: "Tests executed" in
  `docs/DEVELOPMENT_STATUS.md`, D-109.
- **Web:** `src/lib/guest-cancel.test.ts` (10). On the old code it cannot
  load (its module is new); with only its new module copied in, 8 of the 10
  still fail, because the words do not exist there; the other two check the
  module's own rule and a message that already existed. All web unit tests:
  229 in 23 files (219 in 22 before); lint, types and the production build
  pass; page weight unchanged (the product page 209.3 KB of its 210 KB).
- **The browser journeys on this machine,** in CI's order on a fresh demo
  database (the API, the demo data, the production build, Chromium): the
  seller dashboard, buyer, staff, admin, shop screens, setup and account,
  network cut, resend cooldown, the D-107 features, and the guest journey
  with its new step 8 all passed; axe found nothing; no console errors. Not
  run here: the Telegram and Turnstile steps, which restart the API or the
  web app with other settings; CI runs them.
- **Existing tests:** three changed, as section 2 says; none weakened or
  removed; the 74 run with 0 days, exactly as written.

### 9. Changed

API: `markx/orders/` (`service.py`, `selectors.py`, `router.py`),
`markx/core/` (`settings_store.py`, `settings_am.py`),
`scripts/seed_demo.py` (the demo buyer's age), both OpenAPI copies;
`tests/conftest.py` (the fixture and its marker), three new test files and
the two D-108 test files above. Web: `src/components/GuestCancel.tsx`
(new), `src/lib/guest-cancel.ts` and its test (new), the tracking page,
both message files, the generated schema, `e2e/guest-checkout.mjs`. CI: a
comment in `.github/workflows/journeys.yml`. Documents: this entry, F-27
and F-28 marked decided, D-108's PROVISIONAL table,
`docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_STATUS.md`, `docs/HANDOFF.md`.

## D-110 C-27: the notice before ordering (a PROVISIONAL draft); the outside review of pull requests #14 to #17

26 November 2026. Branch `claude/markx-prelaunch-review-c27-x5sizp`, from
`main` at `b6f0429` (the merge of pull request #17) with the complete
history. **Follows** the blueprint D.10 and C-27 ("before the order is
placed, a review step shows ... the dispute route"). **No migration.
Nothing deployed; no server, account, bot, SMS, bucket or paid resource.**

### 0. The task

Two parts, from the founder, before MarkX's first real users:

1. **An outside review, read-only,** of what pull requests #14, #15, #16
   and #17 changed (they were merged without an independent review). Its
   findings are in `docs/reports/2026-11-26-prs-14-17-prelaunch-review.md`:
   **one DEFECT** (R17-1, below) and notes. Nothing was changed for it.
2. **C-27:** a short notice the buyer sees before placing an order, in
   English and Amharic: who sells, paying at the door, checking the goods
   before paying, how to raise a problem. The founder has not written it,
   so the words are a plain draft, PROVISIONAL (P-110-1), kept in one place.

### 1. Where the words live: `apps/api/markx/orders/notice.py`

- **One file, both languages,** side by side in `TEXT`. The founder changes
  the words there and nowhere else; `VERSION` changes with them.
- **The server fills two placeholders:** `{sellers}`, the legal names of the
  shops in the order, from the review step's own figures; `{hours}`, the
  setting `orders.problem_window_hours` (72), so the notice never promises a
  different time than the order page allows. One pass of replacement: a
  legal name holding braces is shown as written, and a test proves it (an
  earlier draft of this code, replacing one placeholder after the other,
  would have changed such a name).
- **Why the API and not the web app's message files:** one file for both
  languages instead of two; the figures in it (the shops, the hours) are the
  server's; the Telegram bot or any later channel can show the same words.
- **The review step carries it:** `QuoteOut.notice` (`OrderNoticeOut`:
  `version`, `provisional`, `title`, `points`), on both
  `POST /checkout/quote` and `POST /checkout/guest/quote`, which take `lang`
  now (Amharic by default, as every route). No extra request, so the notice
  cannot fail to load while the rest of the review step works.
- **The last point depends on who buys.** A signed-in buyer reports a
  problem from the order page within the window; **a guest cannot** (the
  tracking page offers no report, D-108), so the guest's notice says so and
  tells the guest to check everything at the door. Saying the opposite
  would promise a way that does not exist.

### 2. What a buyer sees

On step 4 ("Review and place the order") of both checkouts, between "What
happens next" and the "Place order" button: a box titled **"Before you
place your order"** / **"ትዕዛዝዎን ከማስገባትዎ በፊት"** with four points. "Place
order" stays disabled unless the notice has a title and a point
(`noticeReady`, `src/lib/order-notice.ts`). The word "PROVISIONAL" is not
shown to buyers; the API's answer says `provisional: true` and the code and
these documents mark it.

### 3. The draft (P-110-1, PROVISIONAL, for the founder to replace)

English:

1. You are buying from {sellers}. Each shop sells its own goods and is
   responsible for them. MarkX connects you with the shop: it does not sell
   the goods and never holds your money.
2. You pay the shop when you receive your order, in the way you chose. Do
   not pay anyone before the goods are in front of you.
3. Check the goods before you pay: that they are what you ordered, that
   they work and that nothing is damaged. Give your handover code only
   after you have checked them. If something is wrong, do not pay and do
   not give the code.
4. Signed in: If there is a problem after you receive the goods, report it
   from your order page within {hours} hours. MarkX staff look at it with
   the shop.
   Guest: As a guest you cannot report a problem on MarkX after the goods
   are handed over, so check everything at the door. Until the shop
   answers, you can cancel from your order page; once it confirms, its
   phone number is shown there.

Amharic (for the native editor's check): exactly as in `notice.py`.

### 4. Tests

- `tests/api/test_d110_order_notice.py` (9): both checkouts, both
  languages, the shops' legal names (two shops joined with "and" / "እና"),
  the problem window following its setting, the guest's own last point,
  Amharic by default, the same keys and placeholders in both languages, a
  legal name with braces. **On `b6f0429` all 9 fail** (the review step has
  no notice; the module does not exist): "Tests executed", 26 November 2026.
- `apps/web/src/lib/order-notice.test.ts` (2): the points shown, and "Place
  order" offered only with a notice. It cannot load on `b6f0429` (the
  module is new).
- The browser journeys: the buyer journey and the guest journey now check
  the notice's four points before "Place order".
- **No existing test or check was changed or weakened.** `quote_out` takes
  the database, the language and whether the buyer is a guest; its only two
  callers are the two quote routes.

### 5. R17-1, the review's DEFECT, not fixed here (the task said read-only)

The production nginx (`infra/production/nginx/templates/markx.conf.template`,
the location "The five routes that take a file") lets only five upload
routes send more than 1 MB (`client_max_body_size 1m` in `nginx.conf`). The
two upload routes added by pull requests #14 and #15, a shop's logo
(`POST /api/v1/seller/{id}/store/logo`) and a gate photo
(`POST /api/v1/me/addresses/{id}/gate-photo`), are not in it, so behind
nginx a file over about 1 MB is refused with 413 before the API sees it,
while the API accepts 8 MB. The phone usually shrinks a photo first (S-06),
but sends the original when it cannot. No test runs uploads through nginx.
**Suggested fix:** add `me/addresses/[^/]+/gate-photo` and
`seller/[^/]+/store/logo` to that location's pattern and say "seven". The
founder decides when; it is a one-line change.

### 6. PROVISIONAL values

| Id | Value | Why |
| --- | --- | --- |
| P-110-1 | The notice's words (section 3), in English and Amharic | The founder has not written C-27; a plain draft keeps checkout honest until then |
| P-110-2 | The notice is shown, not recorded: the order does not store which `VERSION` the buyer saw | Recording it needs a migration and the founder's view on whether it is needed legally (F-30) |

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
own shop proposed the product) is OPEN with no provisional answer. SI-1
(sign-in with Telegram for everyone, SMS off as a backup) was decided on
21 November 2026: see D-101, which sets eight PROVISIONAL values and rules,
P-101-1 to P-101-8, and raises F-24 and F-25 (OPEN; recommendations
given). D-103 (server readiness) sets three PROVISIONAL values, P-103-1 to
P-103-3, and leaves certificate renewal off until F-17 is decided. D-105 (backups) sets six PROVISIONAL values, P-105-1 to P-105-6, D-106 (five Release 1 features) five, P-106-1 to P-106-5, and D-107 (five more Release 1 features) seven, P-107-1 to P-107-7. D-108 (guest checkout C-07 and limits for new accounts AD-13, decided by the founder) sets eight, P-108-1 to P-108-8, and raises F-27 to F-29. F-27 and F-28 were decided by the founder on 25 November 2026 (D-109, which makes P-108-1 the founder's 30 days and sets one PROVISIONAL value, P-109-1); F-29 is OPEN (a recommendation given).** Treat this list as part of the launch
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

- **Today:** none. The adapter is ready (D-089). Since SI-1 (D-101) SMS is
  switched off (`MARKX_SMS_PROVIDER=off`) and people sign in with Telegram;
  a provider is needed only to switch SMS back on as the backup.
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
- **Since D-103:** the install step, renewal with certbot on a timer and the
  watch's expiry alert are built and rehearsed. Deciding F-17 is then
  configuration: `MARKX_TLS_RENEWAL=certbot` and `MARKX_ACME_EMAIL` for
  Let's Encrypt, or `none` with a Cloudflare origin certificate installed
  by `deploy.sh certificate install` (`docs/runbooks/tls-certificates.md`).

### F-18 An outside uptime monitor and error tracking (blueprint F.12)

- **Today:** `/api/v1/healthz/ready`, `/healthz/live` and `/healthz/worker`
  exist for a monitor; none is set up, and a failed nightly dump shows only
  as an unhealthy container. No error tracker.
- **Options:** a free uptime monitor polling the three endpoints and the
  certificate's expiry, alerting the founder's Telegram group; an error
  tracker on a free tier with personal data removed before sending.
- **Since D-105 (built, off):** the backup service calls an outside
  heartbeat address after each verified set (`MARKX_BACKUP_HEARTBEAT_URL`);
  the container watch and `deploy.sh alert-test` send to the staff Telegram
  group (`MARKX_ALERT_TELEGRAM_CHAT_ID`). **To decide:** which monitor
  receives the heartbeat (and alerts by a second channel, such as e-mail),
  and the alert group; then `deploy.sh alert-test --send-heartbeat` and a
  test alert confirmed on the phone. PROVISIONAL P-105-1, P-105-2.
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
- **Since D-105:** the **secrets copy** (`deploy.sh escrow-secrets`: the
  application keys, the database passwords, the certificate key, encrypted
  to the recovery key) is kept in the same two places as the recovery key,
  and a copy is also kept, locked, in the backup bucket (PROVISIONAL
  P-105-5). The runbook says how to keep it from a phone only. Also to
  decide: which staff member signs in at each monthly drill (it needs their
  password and the code on their phone at that moment).
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

### F-24 Who may move a phone number to another Telegram account, and how (D-101)

- **Today (P-101-6):** never automatically. A person whose number is on a
  MarkX account tied to another Telegram account (connected or, since the
  fix in D-101 section 2a, disconnected) is refused and told to contact
  support; **no staff tool exists** to move it, so support cannot yet help
  them. The database refuses to change `users.bound_telegram_id` once set
  (migration `0021`'s trigger), so the tool will need its own migration
  that allows exactly an audited move.
- **Why:** Ethio telecom and Safaricom recycle numbers; the new owner of an
  old number must not get the old owner's account, orders or shop.
- **Options:** (a) staff move it after checking identity (a staff tool,
  audited, perhaps with a waiting period and a message to the old Telegram
  account first); (b) the person makes a new account with a new number;
  (c) automatic after a waiting period with no answer from the old
  Telegram account.
- **Engineer's recommendation:** (a), with a 72-hour wait and a message to
  the old account, built before launch.
- **Founder's approval required: yes** (account ownership, support process).

### F-25 Whether a Telegram sign-in also shows a matching code (D-101)

- **Today:** no. The bot warns, in both languages, to continue only if the
  person started signing in themselves; the link lives ten minutes and
  works once; every new sign-in is told in the app.
- **Option:** the page shows two digits and the bot asks the person to
  press the matching one of three buttons. It makes a forwarded-link trick
  (D-101, section 1) much harder, for one more tap for everyone.
- **Engineer's recommendation:** not before launch; decide once real
  sign-in numbers and any abuse are seen.
- **Founder's approval required: yes** (one more step for every person).

### F-26 May the seller bot show what was ordered? (D-102)

- **Today (P-102-6):** no. An order in the bot shows its code, state,
  number of items and minutes left. To see the products, the seller taps
  "Open in MarkX".
- **Why:** the rule for everything that leaves the server (D-092): a
  Telegram message sits on Telegram's servers. A seller deciding in the
  bot whether to accept would decide faster knowing what was ordered.
- **Options:** (a) keep it as it is; (b) show the product names and
  quantities (the buyer's name, number and address never); (c) (b) plus
  the price.
- **Engineer's recommendation:** (b) before launch: the products are the
  store's own public listings, and a seller who cannot see them will open
  the website for every order anyway.
- **Founder's approval required: yes** (what leaves MarkX).
- **Decided (21 November 2026):** the founder chose product names only,
  never any buyer detail, in both languages, shortened when long. Built in
  D-104 section 1.

### F-27 How long a signed-in account counts as new (D-108, P-108-1)

- **Today:** 0 days, the founder's choice of 24 November 2026: no signed-in
  account has the new-buyer limits (ETB 50,000 at the door, one open order);
  every guest has them. Operations set `risk.new_account_days` in the admin
  settings screen; it takes effect at once, audit-logged.
- **To decide:** when to switch it on, and for how long; whether a completed
  order should end it sooner (today it does not, P-108-8).
- **Engineer's recommendation:** 30 days once real buyers arrive. At the
  launch every account is new, so for the first month nobody could buy a
  flagship phone or a laptop at the door: weigh that against the pilot.
- **Founder's approval required: yes.**
- **Decided by the founder (25 November 2026):** brand-new signed-in
  accounts get the new-buyer limits for their first 30 days; P-108-1 is 30.
  Whether a completed order should end it sooner was not decided (P-108-8
  stays: it does not). Built in D-109, sections 1 and 2.

### F-28 What a guest may do besides follow the link (D-108)

- **Today:** nothing ("nothing more"): no cancelling, no "the goods are
  right", no problem report, no review, and a lost link cannot be sent
  again (MarkX has no confirmed way to reach a guest).
- **Options:** (a) as today; (b) cancel from the link while the shop has not
  answered, which frees the shop's stock sooner; (c) report a problem from
  the link; (d) send the link to the typed number once SMS returns, which
  could reach a stranger.
- **Engineer's recommendation:** (a) for the pilot; (b) is the first worth
  adding. Not (d).
- **Founder's approval required: yes.**
- **Decided by the founder (25 November 2026):** (b). A guest may cancel
  their own order from the tracking link, but only before the shop answers;
  the held stock is released at once; after the shop answers there is no
  cancel button; every message in English and Amharic. (c) and (d) were not
  chosen. Built in D-109, sections 3 and 4.

### F-29 Guests who share one mobile address (D-108, P-108-4 and P-108-5)

- **Today:** at most 3 open guest orders and 30 guest checkouts an hour per
  network address, the existing limits as the founder asked. How many
  customers share one address on Ethio telecom and Safaricom is UNKNOWN.
- **Risk:** while Telegram is blocked, everyone orders as a guest, and one
  shared address could refuse honest guests for days (an open order counts
  until its problem window ends).
- **Nothing counts these refusals yet:** the request log shows only that
  `/api/v1/checkout/guest` answered 409, not which limit refused it; a
  count per refusal would be a small addition.
- **Engineer's recommendation:** raise P-108-4 at once if Telegram is
  blocked, and add that count before the launch. Operations can change both
  values in the settings screen.
- **Founder's approval required: yes**, for the values.

### F-30 The words of the notice before ordering (C-27; D-110, P-110-1 and P-110-2)

- **Today:** a plain draft by the engineering session, in English and
  Amharic, in `apps/api/markx/orders/notice.py`, marked PROVISIONAL.
- **Needed from the founder:** the final words (and a check that they say
  nothing a lawyer would not allow); the native editor's check of the
  Amharic; whether MarkX has a support contact a guest can use after the
  handover (UNKNOWN today: none is in the code, so the draft offers none);
  and whether each order should record which version of the notice the
  buyer saw (P-110-2, a small migration).
- **Also from the review (D-110 section 5):** when to fix R17-1, the
  production upload limit for logos and gate photos.
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
