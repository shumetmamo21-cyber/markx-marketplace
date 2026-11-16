# Engineering decisions

One entry per decision another engineer would need to know. Each entry says
whether it **follows**, **fills a gap in** or **departs from** the master
blueprint (`MARKX_MASTER_BLUEPRINT.md`). A departure always states its reason.

The blueprint asks for one file per decision under `docs/decisions/` (section
F.16). The founder's brief of 16 November 2026 asks for this single file, so
decisions live here. Split it if it grows past comfortable reading.

Status words: **Accepted** (in the code), **Open** (needs the founder or more
evidence).

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
  file. The blueprint gives this job to the worker; there is no worker yet
  and a document must not sit unchecked in storage, so it happens in the
  upload request.
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
checkout writes those rows, one beside each hold.

## D-031 Branches

**Fills a gap.** **Accepted.**

The working branch is `claude/project-scaffold`. The second session's hosting
tool also required its own branch, `claude/markx-seller-management-oag1a4`.
Every commit was pushed to both and they are identical. Continue on
`claude/project-scaffold`.

---

## Open questions for the founder

These need an answer before the work they gate. None blocks the next task.

1. **The blueprint's file name.** It is committed as
   `MARKX_MASTER_BLUEPRINT.md`, as instructed. Its own first lines still say
   its file name is "All In One MarkX master Blue Print.md". The content was
   not edited, to keep it byte-identical to the upload. Say so if the header
   should be updated.
2. **Blueprint section O, questions 1 to 6** are still open: where production
   personal data may live, AWS credits and region, acceptance of the Proposed
   decisions, and the founder's time.
3. **A licence for the code**, if any. None is granted today.
4. **Where may sellers' identity documents be stored?** A storage service must
   be chosen before any real seller applies (D-020). It is the same question
   as blueprint O, question 1.
5. **Ownership transfer.** When a store's owner hands it to someone else,
   should the store drop to Level 0 until the new owner's identity is
   checked, or keep its level while staff re-check? (D-022)
6. **Is an Ethiopian TIN always ten digits?** The application form refuses
   anything else.
7. **Used goods.** Level 2 is required for every used item, not only phones
   (D-025). Confirm or narrow it.
8. **Merging a product that has offers** (D-026): when one seller listed both
   duplicates, which of its two offers survives?
