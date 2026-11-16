# MarkX — handoff

**Written:** 16 November 2026, at the end of the fourth AI engineering session.
**Who this is for:** the founder, and the next AI engineer.

This one file holds everything the fourth session has to say, in three parts:

- **Part A — the report for the founder.** What was verified, what was built,
  what was tested, what is not built, and the decisions waiting for you.
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
| Latest code commit | `6582017` (the tracking page), after `7c492c6` (the order life cycle). This file's own correction commit is the one after it; `git log -1` shows the head |
| `main` | `617a276`, the initial commit. **Untouched. Nothing was merged into it.** |

Everything is committed and pushed. The third session ended at `eb52d2f`.
Nothing of it was deleted or rewritten.

## A.2 What the session did, in order

**First, independent verification.** The session fetched the branch, found
`eb52d2f` at its head exactly as the third report said, read the rules, the
blueprint and all six documents, installed the dependencies, started
PostgreSQL 17 and ran every check the third session reported. All passed
exactly as claimed: 779 tests, a clean lint, 121 formatted files, clean strict
type checks over 84 files, and no difference between the code's tables and
the migrations. The third engineer's report was accurate.

**Second, a review of the worker and the first half of orders.** The session
read `markx/orders/` and `markx/worker/` with their tests, looking for the
things the brief listed: a buyer reaching another buyer's order, a seller
reaching another seller's part, a phone shown too early, a price or total a
browser could influence, a status without its event, stock released twice,
locks taken out of order, a worker row marked done without its work. **It
found nothing wrong.** The existing code was kept as it was, and the new work
was built on the same helpers (`_move`, `_release_everything`, the lock order).

**Third, the second half of the order life cycle (P10).** An order no longer
stops at "confirmed". The seller now:

- marks the part **ready** (packed); a collection order's buyer can come to
  the shop from this moment;
- **dispatches** it with the rider's name and phone, which the buyer then
  sees on their order page;
- enters the buyer's **six-digit handover code** at the door or the counter.
  The code is shown only on the signed-in buyer's own order page, from
  "ready" until the goods change hands. It is derived from the server's
  secret, so no table holds it and a stolen copy of the database reveals
  nothing. Five wrong codes lock the parcel: even the right code is then
  refused until MarkX staff issue a new one, with a reason that goes in the
  audit log. Twenty wrong codes typed in the same instant count exactly
  five;
- records a **failed delivery** with its reason, retries, or marks the goods
  **returned**, which puts the stock back and cancels the payment record;
- records that the buyer **paid directly** (cash, telebirr, bank transfer or
  ETHQR). This is the seller's word, stored as such with the server's time,
  exactly as the blueprint's Release 1 says. Nothing is ever marked paid from
  a browser redirect.

The buyer sees the delivery timeline, the rider's contact once the parcel is
on its way, the code with no one else able to read it, and a button to say
"received". The part then **completes** at once; otherwise the worker
completes it 72 hours after delivery. **Completion is the moment stock leaves
the shelf**: the units held since checkout are committed through the one
piece of code that lowers stock on hand, the movement trail records it, and
the fee is charged. Today every fee is zero because no commission rule exists
(the blueprint's rule for direct orders in year one). When a rule does exist,
the fee is computed on the goods only, never on the delivery fee, written to
`fee_charges`, and posted to the ledger as a balanced debit and credit: what
the seller owes MarkX against commission income. A test proves it with a 3%
rule: 37,000 birr of goods gives a fee of 1,110 birr, the 150 birr rider fee
left out.

Staff gained the first three routes of the orders desk: find any order by
its code and read every part's full timeline, dispatch a parcel (for a
partner courier, or on a seller's behalf), and issue a new handover code.
The dispatch board itself is P11.

**Fourth, the worker.** Two new scheduled jobs: completing delivered orders
after the problem window, and cancelling an order that a seller confirmed but
never packed within fourteen days (the stock returns to sale; both sides are
told). The second is a placeholder decision; see A.6.

**Fifth, the tracking page by secure link** (the blueprint's D.14). The
"order placed" message now carries a link that opens the order page without
signing in: the timeline of every part, the expected time, the seller's and
the rider's contact once allowed, the items and the totals. It cannot be
guessed (a 256-bit signature), it dies after sixty days, and it leaves out
the handover code, the recipient's name and phones, and every button. A
forged, expired or borrowed link gets the same "not found" as an order that
does not exist.

## A.3 The concurrency guarantee, extended

Every new operation was raced against its rivals with real threads and real
database connections, in `tests/db/test_fulfilment_contention.py`:

- the right code, "nobody home", "take it back" and the worker's hold check
  all hit one parcel at once: every move stays inside the blueprint's
  diagram, and the stock is given back at most once;
- the buyer's "received", the worker closing the window and the seller
  recording the payment race to complete one part: exactly one completion,
  one fee charge, the stock committed exactly once;
- twenty wrong codes at the same instant: exactly five count;
- the worker's fourteen-day cancellation races the seller's dispatch: either
  the order was cancelled first and the stock is back, or the parcel got on
  the road first and the stock stays held. Never both.

None of them deadlocked. The shipment row is locked the same careful way the
offer rows are (D-027), because tracking events point at it.

## A.4 The tests that were actually run

From the `apps/api` folder, against a real PostgreSQL 17 in Docker, with the
test database rebuilt from empty:

```
uv run pytest                  ->  801 passed in 290.38s (0:04:50)
uv run ruff check .            ->  All checks passed!
uv run ruff format --check .   ->  125 files already formatted
uv run mypy markx              ->  Success: no issues found in 85 source files
uv run alembic check           ->  No new upgrade operations detected.
```

That is 801 tests, 22 more than the 779 this session inherited: ten in
`tests/api/test_fulfilment.py`, four in
`tests/db/test_fulfilment_contention.py`, two in `tests/api/test_tracking.py`,
and six in the seller isolation sweep, which attacks every new seller route
automatically. One existing test changed its expectation: the worker test
now lists the two new jobs among the jobs that ran. No test was weakened. No migration was needed: the tables for
shipments, tracking events, fee charges and the ledger existed since the
first session and were waiting for this code.

Two mistakes were found during the session, both in the new tests themselves
(a miscount of tracking events; an order code made up with a letter the code
alphabet excludes), both fixed before anything was pushed. No defect was
found in existing code.

## A.5 What is NOT built

- **Disputes and refunds.** The states exist in the diagram and the database,
  and the fee reversal column exists; no route enters them. A buyer who has a
  problem inside the 72-hour window has no button yet, on either page.
- **The next-best offer** when a seller declines, reviews, problem reports,
  the staff dispatch board, the bot, search, the web app. No real outside
  adapter: Telegram, SMS, the bot check and the private document store have
  fakes only (F-01 still blocks onboarding a real seller).
- Commission rules can be charged but not managed: no route creates one.
- The device fee cap per order is not applied; no rule carries one.
- No seed data, containers, CI, backups, alerting or deployment.

## A.6 The decisions that need you

F-01 to F-07 are unchanged and still waiting in `docs/DECISIONS.md`. One
decision was taken provisionally because engineering could not wait:

### D-043 (PROVISIONAL — FOUNDER MAY CHANGE BEFORE LAUNCH) What happens when a seller confirms an order and then never packs it

- **Today:** fourteen days after confirmation (the setting
  `orders.fulfilment_hold_days`), a part that is still "confirmed" or
  "ready" is cancelled by the worker, the stock goes back on sale, and the
  buyer and the seller are told. A parcel already with a rider is never
  touched.
- **Why:** the hold exists so that a shop's stock cannot be tied up for ever
  by an order nobody packs, and the blueprint says the worker releases
  expired reservations. Stock cannot be released while the order stays open
  without breaking the stock bookkeeping, so release and cancellation go
  together.
- **The other option:** warn staff and leave the order open. It is one job
  away. You can also simply lengthen the setting.
- **Blocks:** nothing. **Your approval: not needed to carry on.**

## A.7 The boundaries you set, and what was done about them

- **Your AWS servers and payment bot were not touched.** No cloud resource
  was accessed, created, changed, stopped or deployed to.
- **No paid resource was created.** Everything ran on this session's own
  temporary machine with PostgreSQL in a local container.
- **No secret was committed.** The example environment file holds placeholders
  only.
- **Nothing was merged into `main`** and no pull request was opened.
- **No data was deleted and no history rewritten.** No migration was added.
- **MarkX holds no money.** A payment record is the seller's statement;
  nothing marks a payment as paid from a browser redirect.
- **No market, competitor, legal or regulatory research was done.**

---

# Part B — The brief for the next AI engineer

Copy everything between the two lines below, from `MARKX — FIFTH ENGINEERING
SESSION` down to `END OF BRIEF`, and paste it as the first message of a new
session. It is self-contained.

If you have answered any of the decisions F-01 to F-07, or want D-043
changed, add your answers at the end of the paste under a heading such as
"Founder's decisions for this session".

---

**MARKX — FIFTH ENGINEERING SESSION**

You are the fifth founding engineering AI on MarkX. Four sessions came before
you. Continue the project from its existing state; do not rebuild it.

**1. Repository and branch**

- Repository: `shumetmamo21-cyber/markx-marketplace`
- Working branch: **`claude/project-scaffold`**. Never start from `main`, and
  never merge anything into `main`.
- The fourth session's code commits are `7c492c6` (the order life cycle)
  and `6582017` (the tracking page), followed by one documentation commit.
  Verify the real remote head yourself before you begin (`git log -1
  origin/claude/project-scaffold`).

**2. Read these first, in this order**

1. `AGENTS.md` — the rules for every AI agent here. They are not negotiable.
2. `MARKX_MASTER_BLUEPRINT.md` — the product's single source of truth. **Do
   not ask the founder to upload it again, and do not create a second copy,
   summary or competing blueprint.** For this session: D.14 and C-10 (the
   tracking page), C-26 (the next-best offer), G.6 and G.7 (`open_dispute`,
   `resolve_dispute`), F.7 and D-015 for search, P8 and P11 in L.4.
3. `docs/HANDOFF.md` — this file.
4. `docs/DEVELOPMENT_STATUS.md` — what exists, what is tested, what is not.
   Start work from "The exact next task" at its end.
5. `docs/DECISIONS.md` — D-001 to D-048 are settled engineering decisions you
   may rely on; **D-043 is provisional** and the founder may change it. F-01
   to F-07 are open. **Do not implement an F-recommendation unless the
   founder tells you to in this session.**
6. `docs/ARCHITECTURE.md`, especially "Seller scoping", "Stock", "Orders" and
   "The worker", then `docs/SETUP.md`.

Then read the code and the Git history. Where a document and the code
disagree, the code is the fact and the document needs fixing.

**3. Task one — reproduce every check before changing anything**

Follow `docs/SETUP.md`. You need PostgreSQL 17 (Docker; on a bare Linux
machine start `dockerd` yourself, and if Docker Hub rate-limits the pull,
retry it a minute later) and the three MarkX database roles, which
`infra/postgres/bootstrap.sh` creates.

From `apps/api`:

```bash
uv sync
uv run pytest                  # expect 801 passed, three to six minutes
uv run ruff check .            # expect: All checks passed!
uv run ruff format --check .   # expect: 125 files already formatted
uv run mypy markx              # expect: no issues in 85 source files
uv run alembic upgrade head
uv run alembic check           # expect: No new upgrade operations detected.
```

Report the real numbers, whatever they are. Do not hide a failure, do not
weaken a test to make it pass, and do not claim the 801 figure until you have
seen it yourself (the count is 801 only if the five checks below printed
it; see A.4). Fix any genuine regression before starting new work.

**4. Task two — review what the fourth session built**

Review the fulfilment half of `markx/orders/service.py` (from the comment
`# -- fulfilment` to the end, the tracking link included),
`markx/payments/ledger.py`, the new parts of `markx/orders/selectors.py`,
`schemas.py` and `router.py`, with `tests/api/test_fulfilment.py`,
`tests/api/test_tracking.py` and `tests/db/test_fulfilment_contention.py`.
Look for:

- **The handover code.** Can it reach anyone but the signed-in buyer, through
  any response (the tracking page above all), log line, notification
  parameter or error detail? Is it shown outside `ready`,
  `out_for_delivery`, `delivery_failed`?
- **The tracking link.** Does the page leak the recipient's name or phone,
  or anything a stranger with the link should not have? Is the link itself
  ever written to a log or an audit row?
- **Correctness.** Can a shipment change status without a `tracking_events`
  row? Can a part be completed or returned twice? Can `commit_stock` be
  reached with nothing held? Does the wrong-code `db.commit()` inside
  `confirm_delivery` commit anything it should not?
- **Concurrency.** The written lock order is cart, sellers, offers, seller
  orders, shipment, stock. Find any operation that departs from it.
- **Money.** Is the fee ever computed on the delivery fee, or recomputed
  from a rule instead of the line's `commission_bps`?

Fix what is genuinely wrong, with a test that fails before the fix and passes
after it. If the review finds nothing, say so plainly and move on.

**5. Task three — the next-best offer**

When a seller declines or expires, suggest the next-best offer for the same
variant from the ranked list (C-26): a selector over the product page's
ranking in `markx/offers/selectors.py`, excluding the seller that failed,
then a notification template to the buyer carrying the offer id, tested with
the bazaar's two sellers (Beta declines, Alpha's offer is suggested, and the
reverse).

**6. Task four — disputes and refunds, Release 1 form**

`delivered -> disputed` by the buyer inside the problem window (the worker
must then not complete it); `disputed -> completed | refunded` by staff with
`intervene_in_orders`, audit-logged. On refund, reverse the fee charge into
`fee_charges.reversal_ledger_transaction_id` with a balanced posting, and
record that the seller returns the money directly (MarkX holds none). Every
move through `_move`; contention tests for completion against a dispute.

**7. If time remains: search (P8), then CI**

**8. How to work**

- **Small, verifiable milestones.** Build one thing, test it, commit it, push
  it, and verify the push.
- **Schema first** if a migration is needed; migrations are forward-only.
- A test for every permission boundary and every integrity rule. Money is
  whole santim through the `Money` type.
- Keep `pytest`, `ruff check`, `ruff format`, `mypy` and `alembic check`
  green at every commit.
- **Do not delete or rewrite working code in order to give it a different
  shape.** If a departure is better, write the reason in `docs/DECISIONS.md`
  first.
- Read the installed version's documentation before using a framework
  feature. The test suite treats warnings as errors.
- Do not repeat market, competitor, legal or regulatory research.

**9. Boundaries that do not bend**

- Never touch the founder's existing AWS resources. Create no cloud resource,
  deploy nothing, buy nothing, change no DNS.
- Commit no secret. Never merge into `main`; open no pull request unless
  asked. Do not delete data, drop tables or rewrite Git history.
- MarkX never holds customers' money; a payment is never marked as paid from
  a browser redirect.

**10. Finish with a report and living documents**

Update `docs/DEVELOPMENT_STATUS.md`, `docs/DECISIONS.md`,
`docs/ARCHITECTURE.md`, `docs/SETUP.md` and `AGENTS.md` wherever they stop
being true, and rewrite `docs/HANDOFF.md` for your successor. Then report to
the founder in plain words: what changed, which commands you ran and what they
really printed, what you could not verify, and what needs a decision.

**END OF BRIEF**

---

# Part C — The project on one page

| Blueprint phase | State |
| --- | --- |
| P1 Project foundation | Partly done. API skeleton, database pipeline, core helpers. No web shell, no CI, no containers |
| P2 Database and backend foundation | Mostly done. Schema, three database roles, error format, request IDs, logs, the worker. No backups, no alerting beyond the log |
| P3 Authentication and roles | Done on the API side and tested. Real SMS and bot-check providers missing |
| P4 Customer storefront | Not started |
| P5 Product catalogue | Done on the API side and tested. Image pipeline and seed data missing |
| P6 Seller onboarding | Done on the API side and tested. Web screens, share cards, QR code and ownership transfer missing |
| P7 Seller listings and inventory | Done on the API side and tested. Seller Telegram bot missing |
| P8 Search | Not started. The tables exist |
| P9 Cart and checkout | Done on the API side and tested. Web screens missing |
| **P10 Multi-seller orders** | **Done on the API side** from placement to completion, both delivery modes, with the handover code, failed deliveries, returns, the payment record, the fee and the ledger posting, and the tracking page by secure link. **Not done:** the next-best offer, disputes and refunds, reviews, the bot |
| P11 Admin operations | Three routes exist: find an order by code, dispatch, reissue a handover code. The rest not started |
| P12 onwards | Not started. The ledger posting helper exists |

**Numbers:** 801 tests pass. 65 database tables. Seven migrations, `0001`
to `0007`; none added this session. 85 application source files, all
strictly typed.

**Traps already paid for, so nobody pays twice:** a plain `FOR UPDATE` on a
row other rows point at deadlocks against the inserts that point at it
(D-027; shipments too, D-047); PostgreSQL's `now()` is the transaction's start
time (D-028); a FastAPI database dependency needs `scope="function"` (D-001);
a bulk `UPDATE` locks rows in plan order (D-033); `INSERT ... ON CONFLICT DO
NOTHING` waits behind a row another transaction holds (D-035); two correct
features can compose into one wrong one (D-032); a failed request's attempt
count survives only if the service commits it itself (D-044); the parent
order's derived status reads `completed` once every part is handed over
(D-045).

**Waiting on the founder:** F-01 to F-07 in `docs/DECISIONS.md`, and a view
on the provisional D-043. Only F-01, a private store for identity documents,
blocks the launch, and it blocks nothing in the next session's work.
