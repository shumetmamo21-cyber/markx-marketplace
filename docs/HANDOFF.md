# MarkX — handoff

**Written:** 16 November 2026, at the end of the second AI engineering session.
**Who this is for:** the founder, and the next AI engineer.

This one file holds everything the second session has to say. It is in three
parts:

- **Part A — the report for the founder.** What was done, what was tested,
  what is not built, and the six decisions waiting for you. Plain words.
- **Part B — the brief for the next AI engineer.** A block you can copy and
  paste straight into a new session. It needs nothing else.
- **Part C — the state of the project on one page**, for either of you.

Nothing in this file is new work. It describes what is in the repository and
what the tests actually printed.

---

# Part A — Report for the founder

## A.1 Where the work is

| | |
| --- | --- |
| Repository | `shumetmamo21-cyber/markx-marketplace` |
| Working branch | `claude/project-scaffold` |
| Commit this report describes | `5b41677` (this file's own commit is the one after it; `git log -1` shows the latest) |
| Second branch | `claude/markx-seller-management-oag1a4` — an identical copy, same commits |
| `main` | `617a276`, the initial commit. **Untouched. Nothing was merged into it.** |

The second branch exists only because the tool hosting this session demanded a
branch of its own. Every commit went to both, and they hold byte-for-byte the
same files. Carry on with `claude/project-scaffold`; the other can be ignored
or deleted whenever you like.

Everything is committed and pushed. Nothing is left in a temporary workspace.
The five commits of this session, newest first:

```
<this file>  Finalise the handoff into one document
5b41677      Finalise the session-two handoff
582cb12      Document the second session: sellers, offers and inventory
0d50751      Add seller offers and inventory (blueprint P7)
3239e25      Add seller onboarding and management (blueprint P6)
8a6e583      Correct two outdated statements in the development status
```

The previous session ended at `6f36391`, which is the commit the independent
audit inspected. Nothing of it was deleted or rewritten: its 454 tests were
re-run unchanged before any new code was written, and they still pass.

## A.2 What the session did, in order

**First, it checked that what already existed was healthy.** Before writing
anything, it installed the dependencies and ran every check the previous
session reported. All of them passed exactly as that session claimed: 454
tests, a clean lint, clean strict type checks, and no difference between the
code's tables and the migrations. The first engineer's report was accurate.

**Second, it corrected the two false statements in the status document** that
the audit found. The documents it said were missing were in fact complete, and
the README was no longer a placeholder. Both lines were checked against the
files and removed.

**Third, it built seller management (the blueprint's phase P6).** A seller can
now go the whole way from an invitation to a verified, trading store:

- Staff invite a phone number. Onboarding is invitation-only, as the blueprint
  requires, and an invitation is used once, by the person who owns that number.
- The applicant fills in the business details, uploads photographs of the
  owner's identity document, the business licence, the TIN certificate and the
  shop, adds the account they want to be paid into, and submits. Staff see
  nothing until it is submitted.
- Staff then work a queue: look at each document, accept or reject it, ask for
  better ones, approve at verification Level 1 or Level 2, reject with a
  reason, suspend, reinstate, raise or lower the level, and sign off the yearly
  re-check. A level is granted only when the accepted documents behind it
  actually exist, so the badge never claims something nobody checked.
- Identity documents are held privately. They are never served by a web
  address anybody can guess. A member of staff opens one through a link that
  works for five minutes, only for the person it was issued to, and only while
  that person is still allowed to see it. Issuing a link and every single view
  are written to the audit log, which cannot be edited or deleted by anyone.
- Every photograph is decoded and written out again when it arrives, which
  removes the location data a phone camera adds and refuses a file that only
  pretends to be a picture.
- The store page, the owner and manager roles with two seats, and the payout
  account are all built. The account number is encrypted; only its last four
  digits are ever shown again, and a change to it waits 72 hours while the
  owner is told, so a stolen session cannot quietly redirect money.

**Fourth, it built seller offers and stock (phase P7).** This is the heart of
MarkX — many sellers competing on one product page:

- A seller attaches an offer to one version of an approved product, with its
  own price, condition, warranty, delivery options and stock. One offer per
  seller, per version, per condition; the database itself refuses a second.
- Every price change is recorded, so the price history chart has its data.
- Stock can only move through one piece of code, and every movement leaves a
  row explaining it. Nothing can change stock behind its back.
- The product page lists every seller's live offer, ranked afresh each time it
  is read: in stock first, then a recently confirmed price, then offers that
  deliver to the buyer's own area, then the lowest price plus delivery, then
  the better-verified seller. The "best offer" is never stored as a fact, which
  is what the blueprint asks for.
- The one-tap check-in, the job that hides an offer whose price has not been
  confirmed for a fortnight, the shareable store price list, a seller's request
  for a missing product to be added, and staff taking a listing down are all
  built.

## A.3 The security requirement you set

> One seller must never access another seller's private information or
> operations without explicit authorization.

This is enforced in the backend and proved by 45 tests in one file. They are
written as attacks, with seller A always the attacker:

- A cannot read or change anything of B's, through any route.
- B's document, team member or offer identifier placed under A's *own* seller
  identifier comes back as "not found".
- A link signed for B does not open for A, even if A has the link.
- Another seller's identifier gives a reply that is identical, character for
  character, to the reply for an identifier that does not exist, so A cannot
  even learn that B exists.
- A team member who is removed loses access on their very next request.
- A person who belongs to two sellers gets only the powers of their role in
  each one.

One of those tests reads the list of every route in the running application and
attacks each one under `/seller/...` automatically. That means a route added in
a future session is checked even if nobody remembers to write a test for it.

Staff permissions are tested too, across all five staff roles, a visitor, a
customer, a seller, and a member of staff who signed in with a phone code
instead of a password: only the super administrator and operations can review
sellers or open documents, exactly as the blueprint's table says. A member of
staff who happens to own a shop cannot take any staff decision about that shop.

## A.4 The tests that were actually run

From the `apps/api` folder, against a real PostgreSQL 17.12, with the test
database rebuilt from empty:

```
uv run pytest                  ->  647 passed in 217 seconds
uv run ruff check .            ->  All checks passed!
uv run ruff format --check .   ->  101 files already formatted
uv run mypy markx              ->  Success: no issues found in 71 source files
uv run alembic check           ->  No new upgrade operations detected.
```

That is 647 tests, up from the 454 this session inherited: 193 new ones. The
commits after the last code commit changed only documents, so these numbers
describe the code exactly as it stands now.

| Where | Tests |
| --- | --- |
| Pure logic: money, phone numbers, Amharic text, codes, permissions | 297 |
| What the database enforces by itself, including stock under contention | 70 |
| Sign-in, anti-forgery, health | 71 |
| Delivery zones and buyer addresses | 41 |
| Product catalogue | 36 |
| Sellers: onboarding, documents, team, staff permissions, isolation | 133 |
| Offers and inventory | 39 |

Two failures were found during the session, both in the new code, both found by
tests, both fixed before anything was pushed:

1. **A deadlock.** When a seller edited an offer while buyers were holding its
   stock, the database killed one of them. Two pieces of code were taking the
   same two locks in opposite orders. A test with sixty simultaneous threads
   reproduced it; the locks were changed to a gentler kind that cannot collide
   this way, and the test was run three times over to be sure.
2. **Stock movements with no order.** Several movements written in one go all
   carried the same timestamp, so their order was a coin toss. They now carry
   the real clock time of the moment each was written.

Both are written up in `docs/DECISIONS.md` so the next engineer does not
rediscover them the hard way.

## A.5 What is NOT built

Nothing here is hidden or half-claimed.

- **A buyer still cannot buy anything.** There is no search, no cart, no
  checkout and no order behaviour — only the tables waiting for them. This is
  the next session's main job.
- **There is no web app.** Everything built so far is the backend, which a
  website or app talks to. A seller cannot yet apply from a phone screen,
  because there is no screen; the steps work and are tested through the API.
- **There is no background worker.** Three things are written, tested and
  called by nothing: the job that hides stale offers, the job that applies a
  payout-account change after its 72 hours, and the outbox that holds messages
  waiting to be sent. Until the worker exists, no message leaves the server.
  This is why the next session builds it first.
- **Document storage is local only.** The code refuses to run with it on a real
  server, deliberately. See decision F-01 below: this is the one thing that
  must be settled before a real seller can apply.
- **No pipeline for product photographs, no seed data, no containers, no CI,
  no deployment.** Nothing is deployed anywhere.
- Ownership transfer between seller members, the seller Telegram bot, share
  cards and the QR code are not built.
- Merging two duplicate products is still refused when either has offers; see
  decision F-06.
- All the Amharic text in the system was drafted by an AI. A native speaker
  must read it before launch.
- The rule that an Ethiopian TIN has exactly ten digits is the engineer's
  assumption, not something the blueprint states. See decision F-03.

## A.6 The six decisions that need you

Each one below says what the code does today, what the engineer recommends,
why, what it blocks, and whether your approval is required. **None of them has
been implemented as policy.** They are written the same way in
`docs/DECISIONS.md` as entries F-01 to F-06, so the next AI will find them and
will not quietly decide them for you.

### F-01 Where sellers' identity documents are stored

- **Today:** there is one way to store files — the hard disk of whichever
  machine is running — and the code deliberately refuses to start with it on a
  real server. No document has ever left a laptop.
- **Recommendation:** a private Cloudflare R2 bucket, encrypted, with no public
  access, reached only through the five-minute links that already exist. The
  blueprint already notes R2 as an option with 10 GB free and no download
  charges. If you would rather keep everything with one provider, a private S3
  bucket inside the isolated MarkX AWS account is equally correct and costs a
  little more.
- **Why:** identity documents are the most sensitive thing MarkX will ever
  hold. They need a store that is private by default and separate from public
  product images. Either option does that; R2 keeps the bill near zero while
  the pilot is small.
- **Blocks:** not the next session's work. **It blocks onboarding a real
  seller, and therefore the controlled launch.**
- **Your approval: required.** It is a paid account, and a decision about where
  Ethiopian personal data physically lives. It is the same question as the
  blueprint's own unresolved question 1.

### F-02 Whether handing a store to a new owner drops it to Level 0

- **Today:** transfer of ownership is not built, so nothing depends on this.
- **Recommendation:** yes — drop to Level 0, but keep the business documents
  (licence, TIN, shop photo) accepted, since they belong to the business and
  not to the person. The new owner then supplies one identity document and
  staff restore Level 2.
- **Why:** Level 1 means "the owner's identity was checked", and Level 2 is
  built on top of it. After a transfer that sentence is no longer true, and the
  badge would be claiming something nobody verified. Trust is the product.
- **The cost you should weigh:** while the level is below the publishing
  threshold the store's offers disappear from buyers' pages. If that is too
  harsh, the alternative is to keep the level for a short grace period, say
  seven days, with the re-check due inside it.
- **Blocks:** nothing, as long as transfer stays unbuilt. It blocks building it.
- **Your approval: required**, but not urgent.

### F-03 Whether an Ethiopian TIN always has exactly ten digits

- **Today:** the application form accepts exactly ten digits and rejects
  anything else. That rule came from the engineer, not from the blueprint, and
  it is flagged as an assumption in the status document.
- **Recommendation:** look at one or two real licences and confirm the length.
  If it varies, loosen the rule to between nine and thirteen digits and let
  staff reject a wrong number at review, where the licence is in front of them
  anyway.
- **Why:** a rule stricter than reality turns a legitimate seller into "you
  cannot apply", and you would only ever learn of it as a seller who gave up.
  The real check is the human one against the document, which happens either
  way.
- **Blocks:** not development. **It can turn away a real pilot seller.**
- **Your approval: required**, and it is the cheapest of the six to answer: one
  glance at a real TIN.

### F-04 Whether every used item needs Level 2, or only used phones

- **Today:** every item sold as used needs Level 2, in every category. The
  blueprint says this of used phones.
- **Recommendation:** leave it as it is for the pilot. Phones are the launch
  wedge, so the wider rule costs nothing today, and it is stricter rather than
  looser. It can be narrowed later, per category, if a category needs it.
- **Why:** the rule exists because of counterfeit and stolen goods, and nothing
  about a used laptop makes it safer than a used phone. Widening a restriction
  is safe; relaxing one needs evidence.
- **Blocks:** nothing.
- **Your approval: not needed to carry on.** Worth deciding before MarkX opens
  categories beyond phones and accessories.

### F-05 Whether a rejected applicant needs a fresh invitation

- **Today:** yes. An invitation is used once, so a rejected applicant cannot
  reopen an application unless staff issue another invitation.
- **Recommendation:** keep it. Staff can issue a new invitation in a single
  step, so an applicant rejected for something fixable is let back in on
  purpose rather than automatically.
- **Why:** onboarding is invitation-only precisely so that staff decide who is
  in the queue. An invitation that survives rejection lets someone loop through
  the queue unchecked, which is the cheap way to abuse this.
- **Note for staff:** when a photograph is merely poor, "request documents"
  keeps the application open. Rejection is for when the answer is no.
- **Blocks:** nothing.
- **Your approval: not required.** It follows from the blueprint's own rule. It
  is written down so you can overrule it.

### F-06 What happens to a seller's two offers when two products are merged

- **Today:** merging a duplicate product is refused if either product has any
  offers, with a clear message. Merging a product with no offers works and is
  tested.
- **Recommendation:** when the merge is built, match each version of the
  duplicate to a version of the survivor, move the offers across, and where one
  seller ends up holding two offers for the same version and condition, **keep
  the one that was already on the surviving product** and remove the other.
  Record both prices in the audit log and tell that seller, so they can re-list
  if they preferred the other terms.
- **Why:** the survivor's page is the one buyers are already looking at, so
  keeping its offer changes nothing a buyer has seen. Keeping whichever was
  cheaper would silently move a price the seller set, and MarkX should never
  change a seller's price without being told to. Removing rather than deleting
  keeps the price history and any order pointing at the offer.
- **Blocks:** nothing now. It blocks tidying up duplicate products once sellers
  are live, so it is wanted before the pilot catalogue collects them.
- **Your approval: required**, because the rule decides which of a seller's
  listings survives.

## A.7 The boundaries you set, and what was done about them

- **Your AWS servers and payment bot were not touched.** No cloud resource was
  accessed, created, changed, stopped or deployed to. Nothing was deployed
  anywhere at all.
- **No paid resource was created and no charge was incurred.** Everything ran
  on this session's own temporary machine with PostgreSQL in a local container.
- **No secret was committed.** The example environment file holds placeholders
  only, and the code refuses to start on a real server with development
  secrets.
- **Nothing was merged into `main`** and no pull request was opened.
- **No data was deleted and no history rewritten.** Migrations only go
  forwards; the fourth migration adds to the third.
- **No market, competitor, legal or regulatory research was done.** That stays
  yours.

---

# Part B — The brief for the next AI engineer

Copy everything between the two lines below, from `MARKX — THIRD ENGINEERING
SESSION` down to `END OF BRIEF`, and paste it as the first message of a new
session. It is self-contained: it names the repository, the branch, the files
to read and the commands to run, so the next engineer needs nothing from this
conversation.

If you have answered any of the six decisions above, add your answers at the
end of the paste, under a heading such as "Founder's decisions for this
session". Do not expect the AI to guess them.

---

**MARKX — THIRD ENGINEERING SESSION**

You are the third founding engineering AI on MarkX. Two sessions came before
you. Continue the project from its existing state; do not rebuild it.

**1. Repository and branch**

- Repository: `shumetmamo21-cyber/markx-marketplace`
- Working branch: **`claude/project-scaffold`**. Never start from `main`, and
  never merge anything into `main`.
- The second session ended at commit `5b41677` plus one documentation commit.
  Verify the real remote head yourself before you begin.
- The branch `claude/markx-seller-management-oag1a4` is an identical copy that
  the second session's hosting tool required. Ignore it unless your own tool
  forces a branch of its own; if it does, push every commit to both and say so.

**2. Read these first, in this order**

1. `AGENTS.md` — the rules for every AI agent here. They are not negotiable.
2. `MARKX_MASTER_BLUEPRINT.md` — the product's single source of truth, already
   in the repository root. **Do not ask the founder to upload it again, and do
   not create a second copy, summary or competing blueprint.** For this session
   the parts that matter most are G.5 to G.9 (orders, critical operations, data
   integrity, stock), F.8 (background jobs), and the P9 and P10 entries in L.4.
3. `docs/HANDOFF.md` — the second session's report and this brief.
4. `docs/DEVELOPMENT_STATUS.md` — what exists, what is tested, what is not.
   Start work from it.
5. `docs/DECISIONS.md` — entries D-001 to D-031 are settled engineering
   decisions you may rely on. Entries F-01 to F-06 are questions the founder
   has not answered. **Do not implement an F-recommendation unless the founder
   tells you to in this session.**
6. `docs/ARCHITECTURE.md`, especially "Seller scoping" and "Stock", then
   `docs/SETUP.md`.

Then read the code and the Git history. Where a document and the code
disagree, the code is the fact and the document needs fixing.

**3. Task one — reproduce every check before changing anything**

Follow `docs/SETUP.md`. You need PostgreSQL 17 (that file has the Docker
command; on a bare Linux machine you may have to start the daemon with
`dockerd` yourself) and the three MarkX database roles, which
`infra/postgres/bootstrap.sh` creates. The `alembic` commands use the `markx`
database; the tests build their own `markx_test` from empty on every run.

From `apps/api`:

```bash
uv sync
uv run pytest                  # expect 647 passed, about 4 minutes
uv run ruff check .            # expect: All checks passed!
uv run ruff format --check .   # expect: 101 files already formatted
uv run mypy markx              # expect: no issues in 71 source files
uv run alembic upgrade head
uv run alembic check           # expect: No new upgrade operations detected.
```

Report the real numbers, whatever they are. If a command fails for an
environment reason, diagnose it and say exactly why. Do not hide a failure, do
not weaken a test to make it pass, and do not claim the 647 figure until you
have seen it yourself. Fix any genuine regression before starting new work.

**4. Task two — review what the second session built**

Before adding features, review **P6 sellers** (`markx/sellers/`,
`markx/core/storage.py`, `markx/core/images.py`) and **P7 offers and
inventory** (`markx/offers/`), together with their tests. Look for:

- **Security.** Can one seller reach another's data by any path the isolation
  sweep does not cover? Can a document link be reused, extended or replayed?
  Does any route trust an identifier from the body or the query string instead
  of the path? Can a seller raise its own verification level or status?
- **Correctness.** Do the status rules hold in both the service layer and the
  database? Does a refused request leave nothing behind?
- **Concurrency.** Which operations take two locks, and can any pair be taken
  in opposite orders? Decision D-027 records one deadlock that a sixty-thread
  test found; assume there are others.
- **Database integrity.** Is every rule in blueprint G.8 backed by a
  constraint, and not only by code?
- **API quality.** Error codes, cursor paging, cacheability, and whether
  anything personal leaks into a public response.

Fix what is genuinely wrong, with a test that fails before the fix and passes
after it. Record anything you decide in `docs/DECISIONS.md`. If the review
finds nothing, say so plainly and move on; that is a valid result.

**5. Task three — the background worker**

Build this before checkout, because three things already wait for it and
checkout will add a fourth. Blueprint F.8 and P2.

- One worker process in `apps/api`, started by its own command, sharing the
  application's configuration, database session and logging.
- It must run **scheduled jobs**, two of which already exist, are tested, and
  are called by nothing:
  - `markx.offers.service.mark_stale_offers`
  - `markx.sellers.service.activate_due_payout_accounts`
- It must **drain the `outbox` table**. Rows are written inside the transaction
  that caused them (see `markx/notifications/service.py`), carry a topic, a
  payload, an attempt count and a run-after time, and nothing has ever read
  them. Deliver each through the existing adapters, mark it done, and leave a
  failed row to be retried after a growing delay.
- Requirements: one job that raises an error must not stop the others; a
  message must not be delivered twice; two workers running at once must not
  take the same row (`FOR UPDATE SKIP LOCKED` is already used in
  `activate_due_payout_accounts`); a crash in the middle of a row must not
  lose it.
- Tests for each of those, driven by calling the worker's own loop once, never
  by sleeping on a clock.

Then commit, push, and update the documents.

**6. Task four — cart, checkout and multi-seller orders (P9 and P10)**

This is the session's main milestone. Blueprint G.5, G.6, G.7, G.9, D.10, D.11
and the P9 and P10 completion criteria. The tables already exist with their
constraints: `carts`, `cart_items`, `orders`, `seller_orders`, `order_items`,
`order_status_events`, `inventory_reservations`, `shipments`.

- **Cart** held on the server, for a signed-in buyer or an anonymous token,
  recording the offer, the quantity and the price the buyer saw.
- **`place_order`, in one transaction**, exactly as G.5 lists it: re-read every
  offer with its seller, refuse anything not active, recompute every price,
  delivery fee and total on the server, hold the stock for each line, write the
  parent order with its address snapshot, one `seller_orders` row per seller,
  the `order_items` each with their own copy of the name, price and commission
  rate, a shipment per seller order, a status event per seller order, and the
  outbox messages. Nothing the browser sends is trusted.
- **Use the stock functions that already exist** —
  `markx.offers.service.hold_stock`, `release_stock` and `commit_stock`. Do not
  write new stock SQL. Take the holds **in ascending offer id order**, so two
  orders can never wait on each other, and write one `inventory_reservations`
  row beside each hold. That table was deliberately left empty for you, because
  a reservation needs an order item (decision D-030).
- If any line cannot be held, roll the whole order back and tell the buyer
  which item ran out.
- The idempotency key is unique **per buyer**, not globally (decision D-010):
  the same key sent twice returns the same order.
- **`seller_respond`:** only a member with the right role, only from the
  `placed` state; a decline or an expiry releases the stock.
- The seller order life cycle in G.6 is the only set of moves allowed, and
  every move writes a status event in the same transaction.
- The seller's response deadline and the reservation expiry are jobs for the
  worker you have just built.

**The concurrency guarantee must survive.** `tests/db/test_inventory.py`
already proves that 100 simultaneous buyers of the last unit produce exactly
one hold. Keep that test passing, and add the blueprint's own version of it:
**100 simultaneous checkouts of the last unit create exactly one order.** Lock
`offers` and `sellers` rows with `with_for_update(key_share=True)` only
(decision D-027), and add a contention test for every operation that takes two
locks.

Every new seller route goes under `/seller/{seller_id}/...` with the existing
`require_seller` dependency; the isolation sweep in
`tests/api/test_seller_isolation.py` then covers it automatically. A buyer's
order must be unreachable by another buyer, and a seller must see only its own
part of an order, with the buyer's phone number visible only after that seller
confirms (blueprint C.5).

**7. How to work**

- **Small, verifiable milestones.** Build one thing, test it, commit it, push
  it, and verify the push. Work left only in your own workspace is lost when
  your session ends.
- **Schema first:** the migration with its constraints, then database tests,
  then services, then routes.
- A test for every permission boundary and every integrity rule. Money is whole
  santim through the `Money` type, never floating point.
- Keep `pytest`, `ruff check`, `ruff format`, `mypy` and `alembic check` green
  at every commit. Migrations are forward-only.
- **Do not delete or rewrite working code in order to give it a different
  shape.** The layering — models, schemas, service, selectors, router, deps —
  is the blueprint's. If you are certain a departure is better, write the
  reason in `docs/DECISIONS.md` first, then make it.
- Read the installed version's documentation before using a framework feature;
  your training may predate it. `docs/DECISIONS.md` D-001 lists the versions
  and the surprises found so far. The test suite treats warnings as errors.
- Do not repeat market, competitor, legal or regulatory research. The founder
  does that personally.

**8. Boundaries that do not bend**

- Never touch the founder's existing AWS resources: not the "Copy" server, not
  the "test" server, not the payment bot. Create no cloud resource, deploy
  nothing, buy nothing, change no DNS.
- Commit no secret. `.env.example` holds placeholders only.
- Never merge into `main`, and open no pull request unless the founder asks.
- Do not delete data, drop tables or rewrite Git history.
- MarkX never holds customers' money, and a payment is never marked as paid
  from a browser redirect.

**9. Finish with a report and living documents**

Update `docs/DEVELOPMENT_STATUS.md` so that the fourth engineer can continue
from GitHub with no conversation history: what you completed, what is
incomplete, the real test results with their commands, known problems, every
migration, the branch and latest commit, and the exact next task. Update
`docs/DECISIONS.md`, `docs/ARCHITECTURE.md`, `docs/SETUP.md` and `AGENTS.md`
wherever they stop being true, and rewrite `docs/HANDOFF.md` for your
successor.

Then report to the founder in plain words: what changed, which commands you
ran and what they really printed, what you could not verify, and what needs a
decision. The founder owns the product and is not a professional programmer;
you own engineering quality.

**END OF BRIEF**

---

# Part C — The project on one page

| Blueprint phase | State |
| --- | --- |
| P1 Project foundation | Partly done. API skeleton, database pipeline, core helpers. No web shell, no CI, no containers |
| P2 Database and backend foundation | Partly done. Schema, three database roles, error format, request IDs, logs. **No worker, no backups, no alerting** |
| P3 Authentication and roles | Done on the API side and tested. Real SMS and bot-check providers still missing |
| P4 Customer storefront | Not started |
| P5 Product catalogue | Done on the API side and tested. Image pipeline and seed data missing |
| **P6 Seller onboarding** | **Done on the API side and tested.** Web screens, share cards, QR code and ownership transfer missing |
| **P7 Seller listings and inventory** | **Done on the API side and tested.** Seller Telegram bot and the worker that runs the stale job missing |
| P8 Search onwards | Not started. The tables exist |

**Numbers:** 647 tests pass. 64 database tables. Four migrations, `0001` to
`0004`. 71 application source files, all strictly typed.

**Written, tested, and called by nothing yet** — the next session's raw
material: `mark_stale_offers`, `activate_due_payout_accounts`, the `outbox`
table, the `inventory_reservations` table, and `hold_stock` / `release_stock` /
`commit_stock`.

**Traps already paid for, so nobody pays twice:** a plain `FOR UPDATE` on an
offer deadlocks against a stock movement's foreign key (D-027); PostgreSQL's
`now()` is the transaction's start time, so several rows written together share
it (D-028); a FastAPI database dependency needs `scope="function"` to commit
before the response is sent (D-001).

**Waiting on the founder:** six decisions, F-01 to F-06 in
`docs/DECISIONS.md`, repeated in full in Part A.6 of this file. Only F-01, a
private store for identity documents, blocks the launch — and it blocks nothing
in the next session's work.
