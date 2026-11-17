# MarkX — handoff

**Written:** 17 November 2026, at the end of the fifth AI engineering session.
**Who this is for:** the founder, and the next AI engineer.

This one file holds everything the fifth session has to say, in three parts:

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
| Latest code commits | `497fcf5` (next-best offer, problems on delivered orders, the review fix) and `cdf16c5` (search). This file's last correction is the documentation commit after `cdf16c5`; `git log -1 origin/claude/project-scaffold` shows the head |
| `main` | `617a276`, the initial commit. **Untouched. Nothing was merged into it.** |

Everything is committed and pushed. The fourth session ended at `10573b4`.
Nothing of it was deleted or rewritten.

## A.2 What the session did, in order

**First, independent verification.** The session fetched the branch, found
`10573b4` at its head (the fourth session's documentation commit, after the
`eb52d2f` you named), read the rules, the blueprint and the documents,
started PostgreSQL 17, and ran every check before changing anything:

```
uv run pytest                  ->  801 passed in 236.20s (0:03:56)
uv run ruff check .            ->  All checks passed!
uv run ruff format --check .   ->  125 files already formatted
uv run mypy markx              ->  Success: no issues found in 85 source files
uv run alembic check           ->  No new upgrade operations detected.
```

The fourth engineer's report was accurate. The second half of P10 (ready,
out for delivery, the handover code, delivered, completed, `commit_stock`,
the fee and its ledger posting, two-seller end-to-end tests) **was already
built by the fourth session**, so it was reviewed, not rebuilt.

**Second, the review.** Seller management (P6), offers and inventory (P7),
the worker, cart and checkout, and multi-seller orders were read against the
brief's checklist: the handover code reaching anyone but the signed-in buyer,
the tracking link leaking the recipient, locks out of order, stock released
or committed twice, the fee computed on the delivery fee. **One real defect
was found and fixed:** when an order was declined, cancelled by the buyer,
expired unanswered or cancelled by the overdue-hold job, its shipment was
switched to "cancelled" without writing the tracking-history row that every
other shipment change writes. A new test failed on the old code (an empty
history) and passes now. Nothing else was wrong.

**Third, the next-best offer** (blueprint C-26). When a seller declines or
stays silent, the buyer is told, for each item, the best offer in stock for
the same model from another seller, ranked exactly as the product page ranks
it for the buyer's delivery zone. The order page shows the same suggestion,
read live. Nothing is reserved; the buyer decides and buys normally.

**Fourth, problems on a delivered order** (blueprint D.17, the `disputed`
and `refunded` states):

- The buyer can **report a problem** (not received, wrong item, not as
  described, damaged, suspected fake, other) only on their own delivered
  part and only inside the 72-hour window. The part then **stops completing
  by itself**; nothing is charged and the stock stays held.
- The seller answers; the buyer can add more. Each side sees the exchange by
  role, never by person. The public tracking link shows only "disputed",
  never what the buyer wrote.
- Support, operations or the super administrator **decide**, always with a
  written reason that goes in the audit log, within a 48-hour target. "No
  action" completes the part as usual (stock leaves the shelf, the fee is
  charged). "Seller refunded" records that **the seller gave the money back
  directly**. MarkX moves no money. No fee is charged on a refunded part.
- Staff have a queue of open problems, most urgent first.

**Fifth, search** (blueprint D.8 and F.7, phase P8, on the API side). One
box takes Amharic script, Amharic typed in Latin letters, and English, and
forgives typos:

- "samsung", "ሳምሰንግ", "ሳምሱንግ", "samsang", "smsng", "galaksi", "a16",
  "SM-A165F" and "samsunk" all find the Samsung Galaxy A16 first in the
  tests; "tecno", "ቴክኖ", "tekno" and "kj5" find the Tecno.
- Results are **products, never duplicate listings**, each with the card the
  blueprint describes: the "from" price (lowest in stock), how many sellers,
  the best seller's level, whether the price is fresh.
- Filters: category (with its sub-categories), brand, condition, price
  range, seller level, in stock. Sorting: best match, price, freshness.
- Out-of-stock products sink below in-stock ones; a draft or archived
  product, or a suspended seller's offer, is never shown.
- When nothing matches: "did you mean" suggestions, and a "can't find it?
  ask for it" form that stores the request for catalogue staff.
- Every search is logged with its result count. Catalogue staff get a report
  of searches that found nothing, and a synonym tool (for example, make
  "ሞባይል" also search "phones").
- The search index follows every change automatically: a price edit, a
  sold-out offer, a suspended seller, a renamed or archived product. The
  worker also rebuilds it all every hour as a safety net.

**Not yet proven:** the blueprint's two P8 targets, the right product in the
top three for 85% of 100 real queries, and searches under 300 ms. Both need
**real queries from you** and a real-sized catalogue; see A.6.

## A.3 The concurrency guarantee, extended

`tests/db/test_dispute_contention.py`, real threads and real database
connections:

- a problem report, the buyer's "received" and the worker's completion hit
  one delivered part at the same instant: exactly one wins, and the stock
  and fee always match the winner;
- two staff decisions and a seller's reply hit one case at once: exactly one
  decision lands, the stock is settled exactly once, and no reply slips in
  after the decision.

Neither deadlocked.

## A.4 The tests that were actually run

From `apps/api`, against PostgreSQL 17 in Docker, with the test database
rebuilt from empty and nothing else running:

```
uv run pytest                  ->  847 passed in 393.88s (0:06:33)
uv run ruff check .            ->  All checks passed!
uv run ruff format --check .   ->  134 files already formatted
uv run mypy markx              ->  Success: no issues found in 89 source files
uv run alembic check           ->  No new upgrade operations detected.
```

That is 46 tests more than the 801 inherited:

- orders (commit `497fcf5`, 815 in total at that commit): five in
  `tests/api/test_next_best_offer.py`, five in `tests/api/test_disputes.py`,
  two in `tests/db/test_dispute_contention.py`, one in
  `tests/api/test_fulfilment.py` (the review fix), and one more in the seller
  isolation sweep, which attacked the new seller route automatically;
- search: six in `tests/api/test_search_index.py`, 26 in
  `tests/api/test_search.py`.

No test was removed or weakened. Two existing tests changed their
expectations, both for a stated reason: the worker test now lists the new
hourly search job, and one checkout test that counted every outbox row
against notifications now counts the notification topic only, because search
rebuilds share the outbox (D-051). No migration was needed.

One run during the session is **not valid** and is not counted: a second
test run was started against the same test database while the full suite
ran, and the two emptied each other's tables (791 passed, 30 errors in test
set-up). Everything was run again afterwards with nothing else running: the
figure above.

## A.5 What is NOT built

- **Photos on a problem report** (waits for the image pipeline), **reviews**,
  **listing reports**, the **staff dispatch board** and the rest of P11, and
  managing commission rules (they can be charged but no route creates one).
- **The web app**, **the Telegram bot**, **CI**, seed data, containers,
  backups, alerting, deployment.
- In search: sorting by total cost to the door, filters by rating and
  delivery speed, and pages that search engines can read (they need the web
  app).
- Real outside adapters: Telegram, SMS, the bot check and the private
  document store have fakes only (F-01 still blocks onboarding a real seller).
- Release 2 money: Protected prepay, refunds through a provider, payouts.

## A.6 The decisions that need you

F-01 to F-07 are unchanged in `docs/DECISIONS.md`. D-043 (an order nobody
packs for fourteen days is cancelled) is still provisional. Two new choices
were taken provisionally, in D-050, so that engineering did not wait:

### D-050 (1) (PROVISIONAL — FOUNDER MAY CHANGE BEFORE LAUNCH) What a refund does to the stock

- **Today:** staff tick "the goods went back to the shop". If ticked, the
  units go back on sale. If not (lost, damaged, kept by the buyer), they
  leave the shop's count.
- **Other options:** always take them off the count and let the seller add
  them back; or hold returned goods for inspection before resale.
- **Blocks:** nothing. **Your approval: not needed to carry on.**

### Search needs real queries from you (not a decision, an input)

The blueprint's P8 test is a "golden set" of 100 real queries in Amharic,
English and Latin-letter Amharic, each with the product a buyer meant. Only
you can collect those (from shop owners, Telegram groups, your own typing).
A plain list of "what someone typed, which product they meant" is enough;
the next engineer turns it into a test and tunes the matching against it.

### D-050 (2) (PROVISIONAL — FOUNDER MAY CHANGE BEFORE LAUNCH) Who may decide a problem

- **Today:** support staff may decide alone, including a refund outcome,
  with a 48-hour target (the blueprint's assumed figure). No money moves in
  Release 1, so the blueprint's second approver for money does not apply.
- **Other option:** require operations or finance for a refund outcome. It is
  one line.
- **Blocks:** nothing. **Your approval: not needed to carry on.**

## A.7 The boundaries you set, and what was done about them

- **Your AWS servers and payment bot were not touched.** No cloud resource
  was accessed, created, changed or deployed to.
- **No paid resource was created.** Everything ran in this session's own
  temporary machine with PostgreSQL in a local container.
- **No secret was committed.**
- **Nothing was merged into `main`** and no pull request was opened.
- **No data was deleted and no history rewritten.** No migration was added.
- **MarkX holds no money.** A refund is the record that the seller paid the
  buyer back.
- **No market, competitor, legal or regulatory research was done.** Nothing
  in the code claims a legal requirement.

---

# Part B — The brief for the next AI engineer

Copy everything from `MARKX — SIXTH ENGINEERING SESSION` down to `END OF
BRIEF` and paste it as the first message of a new session. It is
self-contained. If you have answered any of F-01 to F-07, or want D-043 or
D-050 changed, add your answers at the end under "Founder's decisions for
this session".

---

**MARKX — SIXTH ENGINEERING SESSION**

You are the sixth founding engineering AI on MarkX. Continue the project from
its existing state; do not rebuild it.

**1. Repository and branch**

- Repository: `shumetmamo21-cyber/markx-marketplace`
- Working branch: **`claude/project-scaffold`**. Never start from `main`, and
  never merge anything into `main`.
- The fifth session's code commits are `497fcf5` (orders) and `cdf16c5`
  (search), with documentation commits `5ce4340` between them and one after
  `cdf16c5`.
  Verify the real remote head yourself (`git fetch origin
  claude/project-scaffold && git log -3 FETCH_HEAD`).

**2. Read these first, in this order**

1. `AGENTS.md`, the rules for every AI agent here. They are not negotiable.
2. `MARKX_MASTER_BLUEPRINT.md`, the single source of truth. **Do not ask the
   founder to upload it again, and do not create a second copy or summary.**
   For this session: L.4 (the phase list: P1's CI, then P4), D.8 and F.7
   (to review search).
3. `docs/HANDOFF.md` (this file).
4. `docs/DEVELOPMENT_STATUS.md`. Start from "The exact next task" at its end.
5. `docs/DECISIONS.md`. D-001 to D-050 are engineering decisions you may rely
   on; **D-043 and parts of D-050 are provisional**. F-01 to F-07 are open:
   **do not implement an F-recommendation unless the founder says so in this
   session.** For a new founder-level question, choose a reversible
   assumption, label it `PROVISIONAL — FOUNDER MAY CHANGE BEFORE LAUNCH` in
   `docs/DECISIONS.md`, and keep going.
6. `docs/ARCHITECTURE.md` ("Seller scoping", "Stock", "Orders", "The
   worker"), then `docs/SETUP.md`.

Where a document and the code disagree, the code is the fact.

**3. Task one: reproduce every check before changing anything**

PostgreSQL 17 in Docker (on a bare Linux machine start `dockerd` yourself),
then from the repository root `PGHOST=127.0.0.1 PGUSER=postgres
PGPASSWORD=postgres_dev_only infra/postgres/bootstrap.sh markx`. From
`apps/api`:

```bash
uv sync
uv run pytest                  # expect 847 passed, five to seven minutes
uv run ruff check .            # expect: All checks passed!
uv run ruff format --check .   # expect: 134 files already formatted
uv run mypy markx              # expect: no issues in 89 source files
uv run alembic upgrade head
uv run alembic check           # expect: No new upgrade operations detected.
```

Report the real numbers. Do not weaken a test. Fix a genuine regression
before new work. **Never start a second test run while one is going**: both
use the `markx_test` database and wreck each other.

**4. Task two: review what the fifth session built**

`next_best_offers`, `_suggest_next_best`, `_commit_held_stock`,
`open_dispute`, `seller_reply_to_dispute`, `buyer_add_to_dispute`,
`resolve_dispute` and the changed `_release_everything` in
`markx/orders/service.py`; `next_best_offer` in `markx/offers/selectors.py`;
`_problems`, `buyer_alternatives`, `staff_open_problems` and the changed
`tracking_view` in `markx/orders/selectors.py`; with the three new test
files. Look for a case's text reaching the tracking link or another seller,
a refunded part that is ever charged or completes later, stock settled
twice, and a lock taken out of the written order. Then review `markx/search/`
(D-051, D-052): a Core `update()`/`insert()` on a watched table that does not
queue a rebuild, a query that matches too much or too little, a filter that
lets through a draft, archived or suspended seller's product. Fix what is
wrong with a test that fails first; if nothing is wrong, say so.

**5. Task three: the search golden set, if the founder sent queries**

Turn each "typed / meant" pair into a parametrised test case, measure how
many put the meant product in the top three, and tune `LETTER_MATCH` in
`markx/search/selectors.py`. If no queries came, skip this; do not invent
them and call them real.

**6. Task four: CI**, then **the web app (P4)**

`.github/workflows`: the five commands on every push with a PostgreSQL 17
service container. Nothing paid. Then the web shell at `/am` and `/en`.

**7. How to work**

- Small, verifiable milestones: build, test, commit, push, verify the push.
- Schema first if a migration is needed; migrations are forward-only.
- A test for every permission boundary and integrity rule. Money is whole
  santim through `Money`.
- Keep the five checks green at every commit.
- Do not replace working code to change its shape; record a better
  departure in `docs/DECISIONS.md` first.
- Read the installed version's documentation before using a framework
  feature. The suite treats warnings as errors.

**8. Boundaries that do not bend**

- Never touch the founder's existing AWS resources. Create no cloud
  resource, deploy nothing, buy nothing, change no DNS.
- Commit no secret. Never merge into `main`; open no pull request unless
  asked. Do not delete data, drop tables or rewrite Git history.
- MarkX never holds customers' money; nothing is marked paid from a browser
  redirect.

**9. Finish with a report and living documents**

Update `docs/DEVELOPMENT_STATUS.md`, `docs/DECISIONS.md`,
`docs/ARCHITECTURE.md`, `docs/SETUP.md` and `AGENTS.md` wherever they stop
being true, and rewrite `docs/HANDOFF.md` for your successor. Report to the
founder in plain words: what changed, which commands you ran and what they
printed, what you could not verify, and what needs a decision.

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
| P8 Search | **Mostly done on the API side**: the index kept fresh, matching in three scripts with typos, filters, sorting, suggestions, "did you mean", the request form, the query log, the zero-result report, synonyms. **Not done:** the golden-set and speed criteria, cost-to-the-door sort, rating and delivery-speed filters, search-engine pages |
| P9 Cart and checkout | Done on the API side and tested. Web screens missing |
| **P10 Multi-seller orders** | **Done on the API side**: placement to completion in both delivery modes, the handover code, failed deliveries, returns, the payment record, the fee and the ledger, the tracking link, **the next-best offer, and problems with staff decisions (`disputed`, `refunded`)**. **Not done:** photos on a problem, reviews, the bot, the web screens |
| P11 Admin operations | Five routes: find an order, dispatch, reissue a handover code, the open-problems queue, decide a problem. The rest not started |
| P12 onwards | Not started. The ledger posting helper exists |

**Numbers:** 847 tests pass. 65 database tables. Seven migrations, `0001` to
`0007`; none added in sessions four or five. 89 application source files,
all strictly typed.

**Traps already paid for, so nobody pays twice:** a plain `FOR UPDATE` on a
row other rows point at deadlocks against the inserts that point at it
(D-027; shipments too, D-047); PostgreSQL's `now()` is the transaction's
start time (D-028); a FastAPI database dependency needs `scope="function"`
(D-001); a bulk `UPDATE` locks rows in plan order (D-033), **and skips the
history row a service helper would write (the fifth session's fix)**;
`INSERT ... ON CONFLICT DO NOTHING` waits behind a row another transaction
holds (D-035); two correct features can compose into one wrong one (D-032);
a failed request's attempt count survives only if the service commits it
itself (D-044); the parent order reads `completed` once every part is handed
over (D-045); a dispute case is guarded by its seller order's lock, never
its own (D-050); a Core statement on a table search watches must queue the
rebuild itself (D-051); two test runs at once share one database and wreck
each other.

**Waiting on the founder:** F-01 to F-07 in `docs/DECISIONS.md`, and a view
on the provisional D-043 and D-050. Only F-01, a private store for identity
documents, blocks the launch, and it blocks nothing in the next session's
work.
