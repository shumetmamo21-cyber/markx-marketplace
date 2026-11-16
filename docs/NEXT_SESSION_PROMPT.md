# Brief for the third engineering session

This file is the assignment for the next AI engineer on MarkX. The founder can
paste the whole of section 1 onwards into a new session. It repeats nothing
that the repository does not already prove, and every command in it was run on
16 November 2026.

---

## MARKX — THIRD ENGINEERING SESSION

You are the third founding engineering AI on MarkX. Two sessions came before
you. Continue the project from its existing state; do not rebuild it.

### 1. Repository and branch

- Repository: `shumetmamo21-cyber/markx-marketplace`
- Working branch: **`claude/project-scaffold`**. Never start from `main`, and
  never merge anything into `main`.
- The second session ended at commit `582cb12a76fc9cdf348a7c54b42be10eebc0d24a`.
  Verify the real remote head yourself before you begin; it may have moved.
- The branch `claude/markx-seller-management-oag1a4` is an identical copy that
  the second session's hosting tool required. Ignore it unless your own tool
  forces a branch of its own; if it does, push every commit to both and say so.

### 2. Read these first, in this order

1. `AGENTS.md` — the rules for every AI agent here. They are not negotiable.
2. `MARKX_MASTER_BLUEPRINT.md` — the product's single source of truth, already
   in the repository root. **Do not ask the founder to upload it again and do
   not create a second copy, summary or competing blueprint.** For this
   session, sections G.5 to G.9 (orders, critical operations, integrity,
   stock), F.8 (background jobs), and the P9 and P10 phase entries in L.4 are
   the ones that matter most.
3. `docs/DEVELOPMENT_STATUS.md` — what exists, what is tested, what is not,
   and the next task. Start from it.
4. `docs/DECISIONS.md` — D-001 to D-031 are settled engineering decisions.
   F-01 to F-06 are questions the founder has not answered; **do not implement
   a recommendation from that section unless the founder tells you to in this
   session.**
5. `docs/ARCHITECTURE.md` (especially "Seller scoping" and "Stock") and
   `docs/SETUP.md`.

Then read the code and the Git history. Where a document and the code
disagree, the code is the fact and the document needs fixing.

### 3. Task one — reproduce every check before you change anything

Follow `docs/SETUP.md`. You need PostgreSQL 17 (the file has the Docker
command; on a bare Linux machine you may have to start the daemon with
`dockerd` yourself) and the three MarkX roles, which
`infra/postgres/bootstrap.sh` creates. `alembic` commands use the `markx`
database, the tests build their own `markx_test` from empty on every run.

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
environment reason, diagnose it and say exactly why. Do not hide a failure,
do not weaken a test to make it pass, and do not claim the 647 figure until
you have seen it. Fix any genuine regression before starting new work.

### 4. Task two — review what the second session built

Before adding features, review **P6 sellers** (`markx/sellers/`,
`markx/core/storage.py`, `markx/core/images.py`) and **P7 offers and
inventory** (`markx/offers/`), with their tests. Look for:

- **Security.** Can one seller reach another's data through any path the
  isolation sweep does not cover? Can a document link be reused, extended or
  replayed? Does any route trust an identifier from the body or the query
  instead of the path? Can a seller raise its own verification level or
  status by any route?
- **Correctness.** Do the status rules hold in both the service and the
  database? Does a refused request leave nothing behind?
- **Concurrency.** Which operations take two locks, and can any pair be taken
  in opposite orders? D-027 records one deadlock that a 60-thread test found;
  assume there are others.
- **Database integrity.** Is every rule in blueprint G.8 backed by a
  constraint and not only by code?
- **API quality.** Error codes, cursor paging, cacheability, and whether
  anything personal leaks into a public response.

Fix what is genuinely wrong, with a test that fails before the fix. Record
anything you decide in `docs/DECISIONS.md`. If the review finds nothing, say
so plainly and move on; that is a valid result.

### 5. Task three — the background worker

Build it before checkout, because three things already wait for it and
checkout will add a fourth. Blueprint F.8 and P2.

- One worker process in `apps/api`, started by its own command, sharing the
  application's configuration, database session and logging.
- It must run **scheduled jobs**, two of which exist, are tested, and are
  called by nothing:
  - `markx.offers.service.mark_stale_offers`
  - `markx.sellers.service.activate_due_payout_accounts`
- It must **drain the `outbox` table**: rows are written inside the
  transaction that caused them (`markx/notifications/service.py`), carry a
  topic, a payload, an attempt count and a run-after time, and nothing has
  ever read them. Deliver each through the existing adapters, mark it done,
  and leave a failed row to be retried with a growing delay.
- Requirements: one job that raises must not stop the others; a message must
  not be delivered twice; two workers running at once must not take the same
  row (`FOR UPDATE SKIP LOCKED` is in the codebase already, in
  `activate_due_payout_accounts`); a crash mid-row must not lose it.
- Tests: each of the above, driven by calling the worker's own loop once,
  never by sleeping on a clock.

Then commit, push, and update the documents.

### 6. Task four — cart, checkout and multi-seller orders (P9 and P10)

This is the session's main milestone. Blueprint G.5, G.6, G.7, G.9, D.10,
D.11 and the P9 and P10 completion criteria. The tables already exist with
their constraints: `carts`, `cart_items`, `orders`, `seller_orders`,
`order_items`, `order_status_events`, `inventory_reservations`, `shipments`.

- **Cart** on the server, for a signed-in buyer or an anonymous token, holding
  the offer, the quantity and the price the buyer saw.
- **`place_order`, one transaction**, exactly as G.5 lists it: re-read every
  offer with its seller, refuse anything not active, recompute every price,
  delivery fee and total on the server, then hold stock for each line, write
  the parent order with its address snapshot, one `seller_orders` row per
  seller, the `order_items` with their own copy of the name, price and
  commission rate, a shipment per seller order, a status event per seller
  order, and the outbox messages. Nothing from the browser is trusted.
- **Use the stock functions that already exist** —
  `markx.offers.service.hold_stock`, `release_stock`, `commit_stock`. Do not
  write new stock SQL. Take holds **in ascending offer id order** so two
  orders can never wait on each other, and write one
  `inventory_reservations` row beside each hold (D-030: the table was left
  for you because a reservation needs an order item).
- If any line cannot be held, roll the whole order back and tell the buyer
  which item ran out.
- The idempotency key is unique **per buyer**, not globally (D-010): the same
  key sent again returns the same order.
- **`seller_respond`**: only a member with the right role, only from
  `placed`; a decline or an expiry releases the stock.
- The seller order life cycle in G.6 is the only set of moves allowed, and
  every move writes a status event in the same transaction.
- The response deadline and the reservation expiry are jobs for the worker
  you just built.

**The concurrency guarantee must survive.** `tests/db/test_inventory.py`
already proves that 100 simultaneous buyers of the last unit produce exactly
one hold; keep that test passing and add the blueprint's own version of it:
**100 simultaneous checkouts of the last unit create exactly one order.**
Lock `offers` and `sellers` rows with `with_for_update(key_share=True)` only
(D-027), and add a contention test for every operation that takes two locks.

Every new seller route goes under `/seller/{seller_id}/...` with the existing
`require_seller` dependency; the isolation sweep in
`tests/api/test_seller_isolation.py` then covers it automatically. A buyer's
order must be unreachable by another buyer, and a seller must see only its own
part of an order, with the buyer's phone number visible only after it confirms
(blueprint C.5).

### 7. How to work

- **Small, verifiable milestones.** Build one thing, test it, commit it, push
  it. Verify the push. Work left only in your workspace is lost.
- **Schema first:** migration with its constraints, then database tests, then
  services, then routes.
- A test for every permission boundary and every integrity rule. Money is
  whole santim through the `Money` type, never floating point.
- Keep `pytest`, `ruff`, `ruff format`, `mypy` and `alembic check` green at
  every commit. Migrations are forward-only.
- **Do not delete or rewrite working code in order to give it a different
  shape.** The layering (models, schemas, service, selectors, router, deps) is
  the blueprint's. If you are sure a departure is better, write the reason in
  `docs/DECISIONS.md` first, then make it.
- Read the installed version's documentation before using a framework feature;
  your training may predate it. `docs/DECISIONS.md` D-001 lists the versions
  and the surprises found so far. The suite treats warnings as errors.
- Do not repeat market, competitor, legal or regulatory research. The founder
  does that personally.

### 8. Boundaries that do not bend

- Never touch the founder's existing AWS resources: not the "Copy" server, not
  the "test" server, not the payment bot. Create no cloud resource, deploy
  nothing, buy nothing, change no DNS.
- Commit no secret. `.env.example` holds placeholders only.
- Never merge into `main`; open no pull request unless the founder asks.
- Do not delete data, drop tables or rewrite Git history.
- MarkX never holds customers' money, and a payment is never marked paid from
  a browser redirect.

### 9. Finish with a report and a living document

Update `docs/DEVELOPMENT_STATUS.md` so the fourth engineer can continue from
GitHub with no conversation history: what you completed, what is incomplete,
the real test results and commands, known problems, every migration, the
branch and latest commit, and the exact next task. Update
`docs/DECISIONS.md`, `docs/ARCHITECTURE.md`, `docs/SETUP.md` and `AGENTS.md`
where they stop being true, and rewrite this brief for your successor.

Then report to the founder in plain words: what changed, which commands you
ran with their real output, what you could not verify, and what needs a
decision. The founder owns the product and is not a professional programmer;
you own engineering quality.

---

## What the second session hands you, in one page

| Phase | State |
| --- | --- |
| P1, P2 | Foundation built; **no worker, no CI, no containers** |
| P3 | Sign-in, sessions, staff sign-in, permissions: done and tested |
| P5 | Catalogue done on the API side; images and seed data missing |
| P6 | Sellers: application, documents, staff review, levels, members, store, payout account. Done and tested |
| P7 | Offers and inventory, ranking, check-in, stale job, proposals, moderation. Done and tested |
| P8 onwards | Not started; tables exist |

- 647 tests pass. 64 tables. Four migrations, `0001` to `0004`.
- Ready for you and called by nothing: `mark_stale_offers`,
  `activate_due_payout_accounts`, the `outbox` table,
  `inventory_reservations`, `hold_stock` / `release_stock` / `commit_stock`.
- Traps already paid for: `FOR UPDATE` on an offer deadlocks against a stock
  movement's foreign key (D-027); `now()` is the transaction's start time, so
  several rows written in one transaction share it (D-028); a FastAPI database
  dependency needs `scope="function"` to commit before the response (D-001).
- Six questions wait for the founder in `docs/DECISIONS.md`, F-01 to F-06.
  Only F-01, a private store for identity documents, blocks the launch, and it
  blocks nothing in this session's work.
