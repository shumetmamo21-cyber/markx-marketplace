# MarkX — handoff

**Written:** 17 November 2026, during the sixth AI engineering session, and
kept current at each pushed milestone.
**Who this is for:** the founder, and the next AI engineer (Opus Max).

- **Part A — the report for the founder.**
- **Part B — the brief for the next AI engineer**, ready to paste.
- **Part C — the project on one page.**

Nothing here is new work. It describes what is in the repository and what
the checks actually printed.

---

# Part A.0 — A parallel backend session (17 November 2026)

While the web-app session was paused, a second session worked on the
back end only. **It did not touch `apps/web`** (no page, component, route,
style, dependency or configuration there), and the API's OpenAPI
description did not change, so the web app's generated types are still
current. It worked on `claude/project-scaffold` on top of `eab7c21`.

| Commit | What |
| --- | --- |
| `37ed483` | Search review fixes (D-057): the typo match now uses its trigram index instead of reading every document (322 ms down to 41 ms on 50,000 synthetic rows, the condition alone); two rebuilds of one product take turns, so a stale "from" price can no longer be written last; the golden-set evaluator counts a repeated query once towards the 100. A new test for each, each shown to fail without its fix |
| `1db65c5` | Containers for a laptop (D-058): one image for the API and the worker, `infra/compose/compose.yaml` with PostgreSQL 17, migrations, API and worker, and a CI job that builds them. Nothing deployed |

Reviewed with no defect found: disputes, the next-best offer, seller
isolation, the worker's job and outbox locking. Noted for later: `GET
/search` logs every first page and has no rate limit.

Checks run (from `apps/api`, with no other test run active):
`uv run pytest` -> **858 passed** in 518 s; `ruff check` clean; `ruff
format --check` 138 files formatted; `mypy markx` no issues in 90 files;
`alembic check` no difference. The container stack was brought up and
checked end to end, then removed. **No real search query exists yet; the
85% target is still unmeasured.**

---

# Part A — Report for the founder

## A.1 Where the work is

| | |
| --- | --- |
| Repository | `shumetmamo21-cyber/markx-marketplace` |
| Working branch | `claude/project-scaffold` |
| Latest head | see `git log -1 origin/claude/project-scaffold`; the commits of this session are listed in A.2 |
| `main` | `617a276`, the initial commit. **Untouched.** |
| Other branches | `claude/markx-engineering-p10-daa24c`, `claude/markx-seller-management-oag1a4`, `claude/markx-third-session-cq58yj`: kept, not touched |
| Pull request | #1 exists for this branch (not opened in this session). Nothing was merged |

## A.2 What this session did, in order (each step pushed)

1. **Verification.** The head was `7580cf0` as reported. All five checks
   passed before any change: **847 tests**, clean lint, 134 formatted
   files, strict types over 89 files, no migration difference.
2. **Review of search and disputes** (`641a95b`). One real defect: a
   product staff archived or merged stayed findable in search until the
   worker rebuilt its index entry, minutes at most but long enough to show
   a withdrawn item. Search now checks the product's own status on every
   query. A new test failed before the fix and passes after. Disputes, order
   fulfilment and the permission checks were read again: nothing wrong.
3. **Your provisional approvals** (`641a95b`, D-053), recorded as
   *PROVISIONAL — FOUNDER MAY CHANGE BEFORE LAUNCH*: returned stock goes
   back on sale only when staff confirm the goods are physically back at
   the shop; support staff may decide problems alone within 48 hours. The
   TIN, used-goods, rejected-applicant, ownership-transfer, document-storage
   and fulfilment-hold rules are listed with the exact place each one lives
   in the code, so each is a small change.
4. **The search golden set** (`6a8d9ea`, D-054). A file you fill with real
   queries (`apps/api/search_eval/golden_queries.template.csv`: what was
   typed, the product meant, the kind, where it came from) and a command
   that scores it: the share with the right product in the top three, per
   kind, the time per search, and every miss. It refuses to call fewer than
   100 queries a valid measurement. **No real query was invented; the 85%
   target has not been measured.**
5. **CI** (`30aedfc`, extended in `e97c722`). Every push now runs, on
   GitHub's free runners, all API checks (lint, formatting, strict types,
   migrations, the full test suite against PostgreSQL 17) and all web
   checks (lint, strict types, unit tests, production build), and fails if
   the web app's copy of the API's description is out of date. **Every run
   so far passed.**
6. **The web app** (`e97c722`, `35b36cc`, D-055), in Amharic and English,
   designed for a 360-pixel phone first with the colours, type and tibeb
   line of the blueprint:
   - home, search (filters, sorting, "did you mean", "ask for a product"),
     product page with **the offers table**: every shop's price, its age,
     the shop's level, delivery and the total to your area, and the best
     offer with the reason it was chosen; the shop page with exactly what
     MarkX checked;
   - sign-in by phone and code, cart, **checkout in four steps** (address,
     delivery per shop, how you pay the shop, the server's priced review
     with each seller's legal name and address), your orders, **the order
     page with the handover code and its warning**, cancel, "the goods are
     right", "report a problem", and the tracking page by link.
   - The web app holds no business rule: every price, total and permission
     comes from the API, which checks everything again.
7. **Demo data** (`e97c722`, D-056) for a laptop: five phones, three made-up
   shops, delivery zones and a buyer, created through the real API so
   every rule applies. It refuses to run anywhere but a local machine.
8. **The seller dashboard** (`dca2864`): the order inbox with the answer
   countdown and what the shop receives after the fee; every fulfilment
   step on the order page (accept, decline, pack, send with a rider, enter
   the buyer's code, failed delivery, return, record the payment, answer a
   problem); the offers list with one-tap "still right" and in-place price
   and stock edits. A shop can only act for itself: the API checks it on
   every call.
9. **The admin dashboard** (`a2106c7`): staff sign in with a password and
   an authenticator code; the problem queue with overdue cases marked; the
   orders desk to find any order by its code, read every step, record a
   problem decision with a written reason, send a rider for a shop or issue
   a buyer a new handover code; seller applications with each document
   opened through a five-minute link, then approve or reject; and the
   search tools. The menu shows only what each staff role may do, and the
   API checks again on every action.
10. **Variant names** (this commit): the cart, the seller's offers and the
    shop page now say "Black · 128 GB" instead of the internal codes
    "black · 128gb", using the same code as the product page.
11. **Proof in a browser.** A script drives the whole journey in Chromium:
   sign in with a code, add the best offer, check out; **the shop, in its
   own dashboard,** accepts, packs and sends a rider; the buyer sees the
   six-digit code; the shop types a wrong code (refused: "4 attempts
   left"), then the right one; the buyer confirms the goods. A second
   script has a buyer report a problem and staff decide it (refund, goods
   back at the shop), and checks that one shop cannot open another's
   dashboard and a buyer cannot reach the admin area, on screen and at the
   API. **Both pass with no errors.** It also
   showed the API's protections working as designed: five codes per phone
   an hour, and no more than three open pay-at-the-door orders per buyer.

## A.3 The checks that were actually run

API, from `apps/api`, with nothing else using the test database:

```
uv run pytest                 ->  854 passed in 400.69s (0:06:40)
uv run ruff check .           ->  All checks passed!
uv run ruff format --check .  ->  138 files already formatted
uv run mypy markx             ->  Success: no issues found in 90 source files
uv run alembic check          ->  No new upgrade operations detected.
```

Web app, from `apps/web`:

```
npm run lint                  ->  no problems
npm run typecheck             ->  route types generated; strict tsc clean
npm test                      ->  9 passed
npm run build                 ->  compiled; 11 routes, all rendered per request
node e2e/buyer-journey.mjs    ->  the whole journey, "console errors: none"
node e2e/staff-journey.mjs    ->  problem decided; isolation refused; no errors
```

Page weight, measured once on the production build: about 140 KB of
JavaScript per page, compressed (the blueprint asks that the first web
milestone records this baseline; see D-055).

## A.4 What is NOT built

- The seller's onboarding, "add an offer", team and settings screens, and
  the admin screens for catalogue curation, invitations, takedowns and the
  audit trail. Their API exists and is tested.
- Product photos (no image pipeline yet), reviews, listing reports.
- The Telegram bot and Mini App shell; real SMS, Telegram and storage
  adapters (F-01 still blocks onboarding a real seller).
- Containers, deployment, backups, alerting. **Nothing is deployed.**
- The search golden set needs your real queries.

## A.5 What needs you

- **Real search queries** (not a decision, an input): about 100 "typed →
  product meant" pairs from real people, in Amharic script, English and
  Amharic typed in Latin letters. The template explains the columns.
- **A native Amharic editor** for every Amharic text, in the API and now
  the web app (`apps/web/messages/am.json`).
- F-01 to F-07 in `docs/DECISIONS.md` are unchanged; only F-01 blocks the
  launch.

## A.6 Boundaries kept

No AWS resource was touched; nothing was deployed; no paid resource was
created (CI uses GitHub's free hosted runners); no secret was committed
(the demo seed prints a laptop-only password and never stores one in the
repository); no data was deleted outside this session's own throwaway
laptop database; no history was rewritten; nothing was merged into `main`.

---

# Part B — The brief for the next AI engineer

Copy everything from `MARKX — SEVENTH ENGINEERING SESSION` to `END OF
BRIEF` into a new session.

---

**MARKX — SEVENTH ENGINEERING SESSION**

You continue MarkX from its existing state. Do not rebuild anything.

**1. Repository and branch.** `shumetmamo21-cyber/markx-marketplace`,
branch **`claude/project-scaffold`**. Never touch `main` or delete a
branch. Verify the head: `git fetch origin claude/project-scaffold && git
log -5 FETCH_HEAD`.

**2. Read first:** `AGENTS.md`, `MARKX_MASTER_BLUEPRINT.md` (sections I and
F.1 for the screens; C.3 and C.4 for who may do what), this file,
`docs/DEVELOPMENT_STATUS.md` ("The exact next task"), `docs/DECISIONS.md`
(D-001 to D-056; D-043, D-050 and D-053 are provisional; F-01 to F-07 are
open), `docs/ARCHITECTURE.md`, `docs/SETUP.md`, and `apps/web/AGENTS.md`.
Next.js 16 differs from your training: read
`apps/web/node_modules/next/dist/docs/` before using a feature.

**3. Reproduce every check before changing anything.** PostgreSQL 17 in
Docker (start `dockerd` yourself on a bare Linux machine), then from the
repository root `PGHOST=127.0.0.1 PGUSER=postgres
PGPASSWORD=postgres_dev_only infra/postgres/bootstrap.sh markx`. Then:

```bash
cd apps/api && uv sync
uv run pytest                  # expect 858 passed, seven to nine minutes
uv run ruff check . && uv run ruff format --check . && uv run mypy markx
uv run alembic upgrade head && uv run alembic check
cd ../web && npm ci && npm run lint && npm run typecheck && npm test && npm run build
```

**Never start a second test run while one is going**: both use
`markx_test` and wreck each other. Report the real numbers. Check the
latest GitHub Actions run for the branch passed.

**4. To see the app:** `uv run python -m scripts.seed_demo` (demo data,
laptop only), `uv run uvicorn markx.main:app --port 8000`, and in
`apps/web` `npm run dev`; open `http://localhost:3000`. Sign-in codes are in
`GET /api/v1/dev/sms-inbox?phone=...`. `node e2e/buyer-journey.mjs` replays
the buyer's journey.

**5. Task:** the rest of the admin and seller dashboards, exactly as "The
exact next task" in `docs/DEVELOPMENT_STATUS.md` lists them. The API for both exists and enforces roles and seller isolation;
the web app only shows what the API returns and sends the member's
choices. Every text in both message files; client components receive only
the message sections they use. Test at 360 pixels. Extend
`e2e/buyer-journey.mjs` with staff steps (find the order by code, decide a
problem).

**6. Boundaries:** no AWS, no deployment, no paid resource, no secret in
the repository, no data deletion, no merge into `main`, no weakened test.
MarkX never holds customers' money. Treat every provisional decision as
changeable.

**7. Finish** by updating `docs/DEVELOPMENT_STATUS.md`,
`docs/DECISIONS.md` and this file, with the commands you ran and what they
printed.

**END OF BRIEF**

---

# Part C — The project on one page

| Blueprint phase | State |
| --- | --- |
| P1 Project foundation | Mostly done: API, database pipeline, web shell, **CI**, typed API link. Containers and an automated page-weight check missing |
| P2 Database and backend foundation | Mostly done; no backups or alerting |
| P3 Authentication and roles | Done on the API; web sign-in for buyers done; staff sign-in screen missing |
| **P4 Customer storefront** | **Buyer journey done on the web** (D-055); images, account settings, Mini App shell missing |
| P5 Product catalogue | Done on the API; image pipeline missing |
| P6 Seller onboarding | Done on the API; web screens missing |
| P7 Listings and inventory | Done on the API; **on the web: offers list, quick edit, check-in**; "add an offer" screen and the bot missing |
| P8 Search | Mostly done on the API, **with the evaluator**; on the web: search, filters, "did you mean", request form. Golden set needs real queries |
| P9 Cart and checkout | **Done on the API and the web** |
| P10 Multi-seller orders | Done on the API, **and on the web for both buyer and seller** |
| P11 Admin operations | **On the web: problems, orders desk, seller review, search tools**; dispatch board, catalogue curation, audit trail missing |
| P12 onwards | Not started |

**Numbers:** 858 API tests, 9 web unit tests, two browser
journeys; 65 tables; migrations `0001` to `0007`; 90 typed API source files.

**Traps already paid for:** see `docs/DEVELOPMENT_STATUS.md` ("Lessons" and
the rules at its end), plus this session's three: two test sessions at once
wreck each other; Next.js 16 pages may export only page things (a helper
exported from a page breaks the build); the dev server keeps old message
files until restarted.
