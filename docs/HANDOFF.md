# MarkX — handoff

**Written:** 16 November 2026, at the end of the third AI engineering session.
**Who this is for:** the founder, and the next AI engineer.

This one file holds everything the third session has to say. It is in three
parts:

- **Part A — the report for the founder.** What was verified, what was found
  and fixed, what was built, what was tested, what is not built, and the
  decisions waiting for you. Plain words.
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
| Latest code commit | `7079cb5` (cart, checkout and multi-seller orders); this file's own commit is the one after it and holds the documents plus a one-line test expectation. `git log -1` shows the latest |
| Second branch | `claude/markx-third-session-cq58yj` — an identical copy, same commits |
| `main` | `617a276`, the initial commit. **Untouched. Nothing was merged into it.** |

The second branch exists only because the tool hosting this session demanded a
branch of its own, as it did in session two. Every commit went to both. Carry
on with `claude/project-scaffold`; the other can be ignored or deleted.

Everything is committed and pushed. The commits of this session, newest first:

```
<this file>  Document the third session
7079cb5      Add cart, checkout and multi-seller orders (blueprint P9, P10)
bd835ef      Add the background worker: scheduled jobs and the outbox dispatcher
399507e      Hold a staff takedown, and lock offers in id order for bulk changes
```

The second session ended at `8df958b`. Nothing of it was deleted or
rewritten.

## A.2 What the session did, in order

**First, independent verification.** Before writing anything, the session
checked the remote branch (`8df958b`, exactly as the handoff said), confirmed
the uploaded handoff was identical to the one in the repository, read the
rules and the blueprint, installed the dependencies, started PostgreSQL 17.12
and ran every check the second session reported. All passed exactly as
claimed: 647 tests, a clean lint, 101 formatted files, clean strict type
checks over 71 files, and no difference between the code's tables and the
migrations. The second engineer's report was accurate.

**Second, a security and engineering review of P6 and P7.** The session read
the seller and offer code, the locking, the isolation tests and the database
constraints, looking for the things you asked about. The verdict: the
isolation, the document links, the staff permissions, the payout encryption
and the stock primitives are sound. Two things were not:

1. **A seller could undo a staff takedown.** If staff took a listing down
   (say, a counterfeit phone), the seller could create the same offer again
   and it came straight back, because "relist an offer I removed" and "staff
   removed this offer" shared one code path. This was a real hole in
   moderation. It is fixed: a takedown now *holds*. The seller's relist is
   refused, removing the offer first is no way round it, the database itself
   refuses to put a held offer back, and staff lift a hold deliberately with
   a reason (`restore`), after which the seller lists again. Three tests
   failed before the fix and pass after it.
2. **Two bulk operations could deadlock.** The seller's one-tap check-in and
   the job that hides stale offers each changed many rows at once in whatever
   order the database chose. Once the worker runs that job on a schedule, the
   two could collide and the seller's check-in would be the one killed. Both
   now lock the rows in a fixed order, and a test races them 200 times.

Nothing else was changed. The previous session's deadlock fix (D-027) was
read, understood and kept.

**Third, the background worker.** This is the process the blueprint calls
"System". It runs the scheduled jobs that two sessions had written and nothing
had ever called (hiding stale offers; applying a payout-account change after
its 72 hours) and a new one (expiring unanswered orders), and it sends what
sits in the outbox. It is built so that two workers can run side by side
without doing the same thing twice, a worker that dies mid-message loses
nothing, a message that fails is retried with growing delays and finally set
aside with an alert in the log, and one failing job never stops the others. A
committed message is delivered exactly once and a message from a change that
was rolled back is never delivered: that is the blueprint's own test for P2,
and it passes. On a laptop "sending to Telegram" writes a line to a file; the
real Telegram bot is not built, and the worker refuses to pretend on a real
server.

**Fourth, the cart, checkout and multi-seller orders.** This was the main
milestone. A buyer can now:

- Build a cart, with or without an account. A visitor's cart follows them
  when they sign in with a phone code. Opening the cart re-checks every price
  and every item against live data and says what changed.
- See a review step where every price, delivery fee and total is computed by
  the server, with the seller's legal name, address and return policy.
- Place the order. One checkout from two stores becomes one order for the
  buyer and one order for each seller. **Nothing the browser sends is used as
  a number.** The browser says what, how many, where and how; the server
  decides what it costs. A browser that sends a lower total is refused. The
  same submission sent twice creates one order.
- Each seller sees only its own part, never the other seller's items or the
  buyer's grand total, and confirms or declines within the response window
  (30 minutes of business time; an order placed at night is due half an hour
  after the shops open). A decline gives the stock back. A seller that stays
  silent has its part expired by the worker and the stock returns; the other
  seller's part carries on.
- Cancel a part before it is packed.
- Phone numbers are shown to each side only after the seller confirms, and
  hidden again if the part ends undelivered, exactly as the blueprint's C.5
  says.

The order life cycle is enforced twice: the code allows only the moves in the
blueprint's diagram, and the database refuses any other move and refuses to
save a status change that has no entry in the log. A test checks the two agree
on all 196 combinations.

## A.3 The concurrency guarantee

The blueprint's own test is: *100 simultaneous purchases of the last unit
create exactly one order.* The previous session proved it for the stock hold
alone. This session proves it for the whole checkout: 100 buyers with 100
carts submit at the same instant for one unit, and exactly one order exists
afterwards; the other 99 are told the item sold out and nothing of theirs is
written. Also tested: fifty buyers competing for ten units get exactly ten;
buyers wanting one, two or three units never oversell seven; checkouts raced
against the seller changing the price and retyping the stock count; and the
seller's confirm, the seller's decline, the buyer's cancel and the clock's
expiry all racing for one order, where exactly one wins and the stock is given
back at most once. None of them deadlocked.

## A.4 The tests that were actually run

From the `apps/api` folder, against a real PostgreSQL 17.12, with the test
database rebuilt from empty:

```
uv run pytest                  ->  779 passed in 346.54s
uv run ruff check .            ->  All checks passed!
uv run ruff format --check .   ->  121 files already formatted
uv run mypy markx              ->  Success: no issues found in 84 source files
uv run alembic check           ->  No new upgrade operations detected.
```

That is 779 tests, up from the 647 this session inherited. The one commit
after `7079cb5` changes documents and one line of a worker test (it now expects
the order-expiry job among the jobs that ran), so these numbers describe the
code exactly as it stands now; they were produced after that change.

| Where | Tests |
| --- | --- |
| Pure logic: money, phone numbers, Amharic text, codes, permissions, order rules | 311 |
| What the database enforces by itself, including stock and checkout under contention | 76 |
| Sign-in, anti-forgery, health | 71 |
| Delivery zones and buyer addresses | 41 |
| Product catalogue | 36 |
| Sellers: onboarding, documents, team, staff permissions, isolation | 137 |
| Offers and inventory | 42 |
| Cart and checkout | 43 |
| The worker | 22 |

Three failures were found during the session, all by tests, all fixed before
anything was pushed, and all written up in `docs/DECISIONS.md`:

1. The moderation bypass (D-032), described above.
2. In the worker, registering a job for the first time inside the job's own
   transaction made a second worker wait for the whole run instead of
   skipping it. A test with two workers found it (D-035).
3. A test of the expiry job was wrong about its own clock, not the code.

## A.5 What is NOT built

Nothing here is hidden or half-claimed.

- **An order stops at "confirmed".** Packing, dispatch, the handover code,
  "delivered", "completed", the fee charge, failed deliveries, returns,
  disputes and refunds are not built. A confirmed order therefore holds its
  stock until it is cancelled. This is the next session's first job, and
  the blueprint's P10 criterion "a two-seller order completes end to end"
  cannot be met until it is done.
- **There is still no web app.** Everything works and is tested through the
  API; nobody can tap a button yet.
- **No search, no reviews, no problem reports, no staff orders desk, no
  dispatch board, no tracking page by link.**
- **No real outside adapter**: Telegram pushes, SMS, the bot check and the
  private document store all have fakes only (F-01 still blocks onboarding a
  real seller).
- **Commission rules can be read but not managed**: no route creates them,
  so every order line carries a zero rate, which is the blueprint's rule for
  direct orders in year one anyway.
- No seed data, containers, CI, backups, alerting or deployment. Nothing is
  deployed anywhere.
- The parent order's status words (`awaiting_seller`, `in_progress`,
  `partly_delivered`, and so on) are the engineer's choice; the blueprint
  gives only "partly delivered" as an example.
- All Amharic text was drafted by an AI; a native speaker must review it.

## A.6 The decisions that need you

The six from the second session, F-01 to F-06, are unchanged and still
waiting; `docs/DECISIONS.md` holds them in full. Nothing this session did
depended on them, and none was implemented as policy. One was added:

### F-07 Who may lift a staff takedown of a listing

- **Today:** the staff roles that may take a listing down (super
  administrator, operations, catalogue) may also lift the hold, with a
  reason that is audit-logged. Lifting publishes nothing; the seller lists
  the item again.
- **Recommendation:** keep it for the pilot; narrow it later if a catalogue
  curator ever lifts a takedown that operations made.
- **Blocks:** nothing. **Your approval: not needed to carry on.**

And one thing you should know rather than decide: the fourteen-day hold on a
confirmed order's stock (D-037) is a placeholder whose expiry nothing acts on,
because the steps after confirmation do not exist yet. The next engineer will
decide, and record, what the worker does with it. If you have a view —
release the stock and cancel the order, or only warn staff — say so in the
brief.

## A.7 The boundaries you set, and what was done about them

- **Your AWS servers and payment bot were not touched.** No cloud resource was
  accessed, created, changed, stopped or deployed to. Nothing was deployed
  anywhere at all.
- **No paid resource was created and no charge was incurred.** Everything ran
  on this session's own temporary machine with PostgreSQL in a local container.
- **No secret was committed.** The example environment file holds placeholders
  only.
- **Nothing was merged into `main`** and no pull request was opened.
- **No data was deleted and no history rewritten.** Three new migrations add
  to the schema; none removes anything.
- **MarkX holds no money.** A payment intent records how the buyer said they
  would pay the seller directly. Nothing marks a payment as paid, from a
  browser redirect or otherwise.
- **No market, competitor, legal or regulatory research was done.**

---

# Part B — The brief for the next AI engineer

Copy everything between the two lines below, from `MARKX — FOURTH
ENGINEERING SESSION` down to `END OF BRIEF`, and paste it as the first message
of a new session. It is self-contained.

If you have answered any of the decisions F-01 to F-07, or have a view on the
fulfilment hold (A.6), add your answers at the end of the paste under a
heading such as "Founder's decisions for this session". Do not expect the AI
to guess them.

---

**MARKX — FOURTH ENGINEERING SESSION**

You are the fourth founding engineering AI on MarkX. Three sessions came
before you. Continue the project from its existing state; do not rebuild it.

**1. Repository and branch**

- Repository: `shumetmamo21-cyber/markx-marketplace`
- Working branch: **`claude/project-scaffold`**. Never start from `main`, and
  never merge anything into `main`.
- The third session's last code commit is `7079cb5`, followed by one
  documentation commit. Verify the real remote head yourself before you begin.
- The branch `claude/markx-third-session-cq58yj` is an identical copy that
  the third session's hosting tool required. Ignore it unless your own tool
  forces a branch of its own; if it does, push every commit to both and say so.

**2. Read these first, in this order**

1. `AGENTS.md` — the rules for every AI agent here. They are not negotiable.
2. `MARKX_MASTER_BLUEPRINT.md` — the product's single source of truth, already
   in the repository root. **Do not ask the founder to upload it again, and do
   not create a second copy, summary or competing blueprint.** For this
   session the parts that matter most are G.6, G.7, G.9 (the life cycle,
   the critical operations, stock), J.9 and J.10 (delivery and tracking),
   D.12 to D.14, and the P10 and P11 entries in L.4.
3. `docs/HANDOFF.md` — the third session's report and this brief.
4. `docs/DEVELOPMENT_STATUS.md` — what exists, what is tested, what is not.
   Start work from "The exact next task" at its end.
5. `docs/DECISIONS.md` — entries D-001 to D-042 are settled engineering
   decisions you may rely on. Entries F-01 to F-07 are questions the founder
   has not answered. **Do not implement an F-recommendation unless the
   founder tells you to in this session.**
6. `docs/ARCHITECTURE.md`, especially "Seller scoping", "Stock", "Orders" and
   "The worker", then `docs/SETUP.md`.

Then read the code and the Git history. Where a document and the code
disagree, the code is the fact and the document needs fixing.

**3. Task one — reproduce every check before changing anything**

Follow `docs/SETUP.md`. You need PostgreSQL 17 (that file has the Docker
command; on a bare Linux machine you may have to start the daemon with
`dockerd` yourself) and the three MarkX database roles, which
`infra/postgres/bootstrap.sh` creates.

From `apps/api`:

```bash
uv sync
uv run pytest                  # expect 779 passed, about five minutes
uv run ruff check .            # expect: All checks passed!
uv run ruff format --check .   # expect: 121 files already formatted
uv run mypy markx              # expect: no issues in 84 source files
uv run alembic upgrade head
uv run alembic check           # expect: No new upgrade operations detected.
```

Report the real numbers, whatever they are. If a command fails for an
environment reason, diagnose it and say exactly why. Do not hide a failure, do
not weaken a test to make it pass, and do not claim the 779 figure until
you have seen it yourself. Fix any genuine regression before starting new work.

**4. Task two — review what the third session built**

Before adding features, review **the worker** (`markx/worker/`,
`markx/notifications/push.py`) and **orders** (`markx/orders/`), with their
tests. Look for:

- **Security.** Can one buyer reach another buyer's order, or one seller
  another seller's part, by any path? Does any seller view leak the buyer's
  phone before confirmation, another seller's lines, the grand total, or a
  person's identity in the event log? Does any route trust an identifier from
  the body or the query string instead of the path? Can a browser influence a
  price, a fee or a total by any field?
- **Correctness.** Can a seller order reach a status without its event? Can
  stock be released twice, or held without a reservation row? Is every
  refusal in `place_order` made before any row is written?
- **Concurrency.** The written lock order is cart, sellers, offers, seller
  orders, stock. Find any operation that departs from it. Decision D-027
  records the deadlock that forced `FOR NO KEY UPDATE`; D-033 the one that
  forced id-ordered bulk updates. Assume there are others.
- **The worker.** Is there any way a handler's database work can commit
  without the row being marked done, or the reverse? D-034 records the one
  known limit (a message to the outside world can, in theory, be seen twice).

Fix what is genuinely wrong, with a test that fails before the fix and passes
after it. Record anything you decide in `docs/DECISIONS.md`. If the review
finds nothing, say so plainly and move on; that is a valid result.

**5. Task three — the second half of the order life cycle (P10)**

This is the session's main milestone. An order today stops at `confirmed`.
Build the rest, in `markx/orders/service.py`, with every status change going
through `_move` (the database refuses anything else; see D-038):

- `confirmed -> ready` by the seller; the shipment becomes `ready`, with a
  `tracking_events` row (J.10). The staff dispatch board for partner
  couriers belongs to P11: for now the seller marks ready and dispatches.
- `ready -> out_for_delivery` by the seller or staff; `ready -> delivered`
  directly for shop collection, with the code.
- **The handover code** (C-15, D-011): derived from the server secret, the
  shipment id and `shipments.code_version` with `derive_numeric_code` in
  `markx/core/security.py`, so nothing in the database reveals it. The buyer
  sees it on their order page; the seller or rider enters it.
  `confirm_delivery` compares it in constant time, counts attempts up to
  `MAX_HANDOVER_ATTEMPTS` and then refuses further tries until staff reissue
  (raise `code_version`), marks `delivered` and starts the problem window
  (`orders.problem_window_hours`).
- `out_for_delivery -> delivery_failed` with a reason; retry; `returned`,
  which releases the reservation.
- `complete_seller_order`: after the problem window by the worker, or at
  once when the buyer confirms. **This is where
  `markx.offers.service.commit_stock` is finally called**: the reservation
  becomes `committed`, `on_hand` falls, and a `fee_charges` row is written
  from the lines' `commission_bps` (zero today). Do not write new stock SQL.
- The seller records a direct payment: the `payment_intents` row to
  `succeeded` with the method and time (D.12). In Release 1 this is the
  seller's word, recorded as such; never from a browser redirect.
- Decide, and record in `docs/DECISIONS.md`, what the worker does when a
  confirmed order's 14-day fulfilment hold on its stock expires (D-037
  leaves this open on purpose). Ask the founder if their brief says nothing.
- Every new seller route goes under `/seller/{seller_id}/...` with
  `require_seller(SellerCapability.HANDLE_ORDERS)`; the isolation sweep in
  `tests/api/test_seller_isolation.py` then covers it automatically. Every
  new buyer route is found together with the buyer's id.
- Tests: a two-seller order end to end, placed to completed (P10 criterion
  1); a wrong handover code `MAX_HANDOVER_ATTEMPTS` times locks the shipment
  and a right one after that is refused; `commit_stock` reduces on-hand and
  the movement trail replays to the exact stock
  (`tests/bazaar.py::assert_stock_is_consistent` does that check); a
  contention test for every new operation that takes two locks (delivery
  against cancellation, completion against a dispute, the worker's completion
  against the buyer's).

Then commit, push, and update the documents.

**6. Task four — the tracking page, then the next-best offer**

- The buyer's order page by a secure link that needs no sign-in (D.14): a
  signed link over the order id and an expiry, as the document links do
  (`markx/sellers/service.py`, `issue_document_link`), showing only what the
  buyer needs and **never the handover code without sign-in**.
- When a seller declines or expires, suggest the next-best offer for the same
  variant from the ranked list (C-26): a selector, then a notification
  template carrying the offer id.

**7. If time remains: search (P8) and CI**

- `search_documents` rebuilt by a worker job when an offer's price, stock or
  status changes, queued through the outbox (a new topic and handler in
  `markx/worker/outbox.py`). Read blueprint F.7 and D-015 first.
- `.github/workflows`: the five commands on every push with a PostgreSQL 17
  service container. Nothing paid.

**8. How to work**

- **Small, verifiable milestones.** Build one thing, test it, commit it, push
  it, and verify the push. Work left only in your own workspace is lost when
  your session ends.
- **Schema first:** if a migration is needed, write it with its constraints
  first, then database tests, then services, then routes. Migrations are
  forward-only. P10's second half may need none: `shipments`,
  `tracking_events`, `fee_charges` and `payment_intents` already exist.
- A test for every permission boundary and every integrity rule. Money is
  whole santim through the `Money` type, never floating point.
- Keep `pytest`, `ruff check`, `ruff format`, `mypy` and `alembic check` green
  at every commit.
- **Do not delete or rewrite working code in order to give it a different
  shape.** The layering — models, schemas, service, selectors, router, deps —
  is the blueprint's. If you are certain a departure is better, write the
  reason in `docs/DECISIONS.md` first, then make it.
- Read the installed version's documentation before using a framework feature;
  your training may predate it. `docs/DECISIONS.md` D-001 lists the versions
  and the surprises found so far. The test suite treats warnings as errors.
- Do not repeat market, competitor, legal or regulatory research. The founder
  does that personally.

**9. Boundaries that do not bend**

- Never touch the founder's existing AWS resources: not the "Copy" server,
  not the "test" server, not the payment bot. Create no cloud resource, deploy
  nothing, buy nothing, change no DNS.
- Commit no secret. `.env.example` holds placeholders only.
- Never merge into `main`, and open no pull request unless the founder asks.
- Do not delete data, drop tables or rewrite Git history.
- MarkX never holds customers' money, and a payment is never marked as paid
  from a browser redirect.

**10. Finish with a report and living documents**

Update `docs/DEVELOPMENT_STATUS.md` so that the fifth engineer can continue
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
| P2 Database and backend foundation | Mostly done. Schema, three database roles, error format, request IDs, logs, **the worker**. No backups, no alerting beyond the log |
| P3 Authentication and roles | Done on the API side and tested. Real SMS and bot-check providers still missing |
| P4 Customer storefront | Not started |
| P5 Product catalogue | Done on the API side and tested. Image pipeline and seed data missing |
| P6 Seller onboarding | Done on the API side and tested. Web screens, share cards, QR code and ownership transfer missing |
| P7 Seller listings and inventory | Done on the API side and tested. Seller Telegram bot missing. A staff takedown now holds |
| P8 Search | Not started. The tables exist |
| **P9 Cart and checkout** | **Done on the API side and tested**, all five criteria. Web screens missing |
| **P10 Multi-seller orders** | **First half done and tested**: placement, confirm, decline, expiry, cancellation, the state machine in the database. **Not done:** everything after confirmation, the tracking page, the next-best offer, the bot |
| P11 onwards | Not started |

**Numbers:** 779 tests pass. 65 database tables. Seven migrations,
`0001` to `0007`. 84 application source files, all strictly typed.

**Written, tested, and called by nothing yet** — the next session's raw
material: `commit_stock`, `derive_numeric_code`, `shipments.code_version`,
`MAX_HANDOVER_ATTEMPTS`, the `tracking_events` and `fee_charges` tables, and
the reservation's fulfilment expiry.

**Traps already paid for, so nobody pays twice:** a plain `FOR UPDATE` on an
offer deadlocks against a stock movement's foreign key (D-027); PostgreSQL's
`now()` is the transaction's start time (D-028); a FastAPI database dependency
needs `scope="function"` (D-001); a bulk `UPDATE` locks rows in plan order
(D-033); `INSERT ... ON CONFLICT DO NOTHING` waits behind a row another
transaction holds (D-035); two correct features can compose into one wrong one
(D-032).

**Waiting on the founder:** seven decisions, F-01 to F-07 in
`docs/DECISIONS.md`, F-01 to F-06 repeated in full in the second session's
report (in Git history at `8df958b`, `docs/HANDOFF.md`) and F-07 in Part A.6
of this file. Only F-01, a private store for identity documents, blocks the
launch — and it blocks nothing in the next session's work.
