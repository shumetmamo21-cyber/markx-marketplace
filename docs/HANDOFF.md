# MarkX — handoff

**Written:** 17 November 2026, during the sixth AI engineering session, and
kept current at each pushed milestone; Parts A.00 and A.0 were added by the
two back-end-only sessions that followed, Part A.000 by the ninth session
and Part A.0000 by the tenth (both the web app's owner).
**Who this is for:** the founder, and the next AI engineer (Opus Max).

- **Part A — the report for the founder.**
- **Part B — the brief for the next AI engineer**, ready to paste.
- **Part C — the project on one page.**

Nothing here is new work. It describes what is in the repository and what
the checks actually printed.

---

# Part A.0000 — The tenth session: the buyer's and the seller's screens (17 November 2026)

The web app's owner, on the founder's request to continue with the buyer and
seller screens. Built on `09a55b0` in three pushed stages, each tested
before it was pushed:

1. **Reviews and report links** (`b2e11ce`, D-072). Product and shop pages
   show the rating totals and published reviews; the buyer rates an item on
   the order page and keeps their reviews on `/reviews`; the shop replies
   on its Reviews screen; a report link sits on every product, listing,
   shop and review, for anyone. The API now says who may act on a review
   (`MyReviewOut.can_edit`, `can_reply`, two new API tests), so no rule is
   copied into the page. The seller menu follows the member's capabilities.
2. **Pictures** (`1920e55`, D-074; its title says D-073, see below). The
   product card shows the first ready catalogue thumbnail
   (`ProductCardOut.thumb_url`, both sides, one new API test); the product
   page shows the pictures and the shops' own photos; a shop adds and
   withdraws real photos of what it sells; the buyer, the shop and staff see
   a problem's evidence photos, the buyer and the shop add theirs and the
   buyer adds messages while it is open.
3. **The rest of the seller dashboard** (`ae10c83`, D-075; no API change):
   the overview (application state, what is missing, send for review), the
   performance page over the parallel session's new routes, add an offer
   from the catalogue, store settings, team, documents, legal details,
   payout account, and the application form on `/seller`.

**A parallel back-end session pushed meanwhile** (`891ac71`, `d60bc25`: the
seller performance figures and the weekly seller message, migration `0012`,
D-073). The push was refused, nothing was forced: the branch was merged
(`d015261`), the decision-log clash resolved by keeping both and
renumbering this session's pictures decision to **D-074** (the title of the
already-pushed `1920e55` still says D-073; history was not rewritten).

**What the browser journeys found** (all fixed): "1 reviews" (now "1
review"); a review form that would have been offered after the shop
replied (fixed in the API, `can_edit`); the journeys themselves read a
cached copy of the picture list, mistook Next.js's route announcer for a
refusal, were not repeatable (an earlier run's review matched), and could
be blocked by an interrupted run's open problem or by a demo shop's offer
undercutting the demo prices; all now handled. The staff authenticator code
is refused when reused within 30 seconds (replay protection, by design);
the journeys retry once. Session nine's `admin-queues.mjs` could take down
one listing and relist another (the page's order is not the API's ranking);
it now takes down exactly the listing it relists.

**Final checks:** see `docs/DEVELOPMENT_STATUS.md`, "Tests executed",
tenth session.

**Second round** (the founder: "do the undone tasks one by one, recheck what
has been built"). The recheck reproduced 944 API tests on `ffa2720` and
compared every API route with the routes the web app calls. That showed the
first report was wrong to say every screen the API supports existed: staff
had no screens for catalogue setup, delivery zones or a shop's level and
standing, and buyers none for their account, the next-best offer, the
category page or search suggestions. All built now, one by one, with the
shop's location, closing and product suggestions (`751e2b0`, D-077). Closing
a store with orders in progress is now refused (`822f564`, D-076), and the
settings carry Amharic descriptions (`47e9fec`, D-078). The journey found
one real fault before it shipped: "add a version" forced a value on a detail
the other versions leave empty, which the API refuses. The only routes left
without a screen are Telegram sign-in and linking (they need the bot), the
development SMS inbox, the health checks and the file links the API hands
out.

**Still to build on the web:** Telegram sign-in and the Mini App once the
founder creates the bot; ratings on the product card (with the back end).
The Amharic text of this session is AI-drafted and needs a native speaker.

**Waiting on the founder:** unchanged — F-01 to F-08 in `docs/DECISIONS.md`.

---

# Part A.000 — The ninth session: the admin queues on the web (17 November 2026)

The web app's owner, resuming, on the founder's instructions of 17 November
2026: `claude/project-scaffold` is the official branch; the fourth session's
implementation is the official one; nothing completed is rebuilt; the
alternative branch `claude/markx-third-session-cq58yj` is kept as a
reference and was neither merged, deleted nor rewritten.

**What it did, each step pushed:**

1. **Reproduced the checks** on `88d481b` before any change: 854 API tests
   passed (the sixth session's figure exactly); the web app's `npm ci`,
   lint, typecheck, 9 unit tests and build passed.
2. **Compared the two branches' tests.** The official branch covers
   everything the alternative branch tested except one refusal: no direct
   payment is recorded while a part is still `placed`, or after the goods
   were returned. That one test was ported (`eab7c21`); no implementation
   changed. A tracking-event fix found in the review turned out to be
   already on the official branch (`497fcf5`), so the duplicate was dropped
   before it was pushed.
3. **Recorded the founder's confirmation of the fulfilment hold** (D-043,
   D-053, `eab7c21`): after 14 days a part still `confirmed` or `ready` is
   cancelled and its stock freed, as the provisional pilot policy, subject to
   safe handling of orders already out for delivery. The job meets that
   condition by construction (it never selects a part on the road) and an
   existing test proves it.
4. **The admin queues on the web** (D-069, D-070), built on the head that had
   meanwhile moved to `b2b674e`: screens for product proposals, invitations,
   listing takedowns and the audit trail; a role-aware admin home and menu
   (catalogue and finance staff were being sent to a page they may not
   open); codes shown in words in both languages; a page the API refuses
   now says so. One back-end addition the takedown screen needed:
   `GET /admin/offers/held`. This session's own audit-log route was dropped
   in favour of D-065's `GET /admin/audit-log`, which the eighth session had
   built in parallel.

**Final checks** (on `b2b674e` plus this session's work): `uv run pytest` **935 passed** in 726 s (927 on `b2b674e` plus this session's 8); ruff clean; 176 files formatted; strict mypy clean over 118 source files; `alembic check` no difference; `apps/api/openapi.json` exact and the web app's copy exact too (regenerated). The web app: lint and strict typecheck clean, **11 unit tests passed**, the production build passed, and `e2e/admin-queues.mjs` passed all 7 steps in Chromium with no console errors.
GitHub Actions run #37 on `b2b674e`, the head this was built on, passed.

5. **Every other admin screen the API supports** (D-071), in pushed stages
   with no API change: the dashboard, the dispatch board and operations
   (`9ac3b94`); then reviews, reports, settings, staff accounts, exports and
   pictures. A unit test fixes the exact screens of each of the five staff
   roles; `e2e/admin-queues.mjs` now runs 15 steps in Chromium
   against the demo data. Two things the browser journey found along the
   way were in the journey, not the app, and are fixed there: it took a
   listing down without relisting it (lifting a hold publishes nothing,
   D-032), and it signed the same demo phone in more often than the API's
   five codes per phone per hour allow. One fault was in the app: a long
   setting name made the settings page 19 px wider than a phone; fixed.

**Final checks of the second half:** on the final tree: `uv run pytest` **935 passed** in 726 s (no API change in this half); ruff, format (176 files), strict mypy (118 files), `alembic check` and both API-description checks clean; web lint and strict typecheck clean, **21 unit tests passed**, the build passed, `schema.d.ts` matches; `e2e/admin-queues.mjs` passed all 15 steps with no console errors.

**Still to build on the web** (Part B, step 5): reviews and report links for
buyers, pictures on product pages and in the seller's offers, problem photos
on the order pages and in the orders desk, the rest of the seller dashboard
(add an offer, application, documents, team, store settings), and setting
descriptions in Amharic.

**Waiting on the founder:** unchanged — F-01 to F-08 in `docs/DECISIONS.md`.
Nothing this session did depends on them.

---

# Part A.00 — The eighth session: the back end, continued (17 November 2026)

A second back-end-only session, while the web-app session stays paused.
**`apps/web` was not modified at all** (no page, component, route, style,
dependency, configuration or generated file; `git diff eab7c21 HEAD --
apps/web` is empty). It started from `96fddf6` and reproduced the baseline
first: **858 passed**, lint, formatting, strict types and the migration
check clean, the API image built.

**Final checks, on `891ac71` (after session nine's commits):** `uv run
pytest` **943 passed in 706 s**; ruff clean; 181 files formatted; strict mypy
clean over 122 source files; `alembic check` no difference;
`apps/api/openapi.json` exact; the web app's copy true with 4 additions.
Earlier, on `2c89323`: 923 passed. On `6fe1ce6`: the restore
drill passed on the demo data, and the API image built and the Compose
stack rendered an uploaded picture in the worker container; CI runs the
drill and the container build on every push. Migrations added: `0008` to
`0012`.

| Commit | What |
| --- | --- |
| `2e4944c` | **Search throttle** (D-059): searches and suggestions are counted per network address and minute; past the limit a search is refused before it runs or is logged |
| `6dbaeb7` | **One stuck order no longer blocks the others** (D-060): the completion job completes each order in its own savepoint, with the database's commit-time checks run inside it |
| `4bcea17` | **The back end may add API routes without touching the web app** (D-061): `apps/api/openapi.json` is checked exactly; the web app's copy must stay true and may lag behind additions |
| `8702e58` | **Pictures** (D-062, migration `0008`): catalogue pictures and sellers' real photos, cleaned at upload, rendered by the worker to small WebP files with no location data, moderated by staff; **problem photos** for both sides of a reported problem, private, append-only |
| `2b7ba94` | **Backups** (D-063): an encrypted dump, a restore that never overwrites, and a restore drill that CI runs on every push |
| `403e101` | **Monitoring** (D-064, migration `0009`): the marketplace checks itself every five minutes and reconciles its money and stock daily; alerts open and close once each and go to the founder's Telegram group when one is configured; a worker health check for an outside monitor |
| `51f4af8` | **The rest of the admin back end** (D-065): the audit-log viewer, switches and risk limits, staff accounts, the dispatch board, the business dashboard |
| `c26e8cb` | **Reviews and ratings** (D-066, migration `0010`): the buyer of a completed item reviews it once within 60 days; suspicious reviews (contact details, many reviews of one seller) wait for staff; the seller replies but cannot remove; staff publish or hide with a reason; rating totals per product and seller follow in the background |
| `2c89323` | **Reports on listings, stores and reviews** (D-067, migration `0011`): anyone flags what they can see; one open report per person and target; staff work the queue and resolve every report on a target with a note; reporters are told the outcome |
| `b2b674e` | **Data exports for an accountant** (D-068): fees, ledger, seller orders (no buyer data) and seller balances as CSV for whole Addis Ababa days; exact amounts; safe to open in a spreadsheet; every export audit-logged; super administrator and finance only |
| `891ac71` | **The performance page and the weekly seller message** (D-073, migration `0012`): each store's numbers for any period, and once a week, for the last Monday-to-Sunday week, its figures kept and its members told, never twice |
| `6fe1ce6` | **A flaky test fixed**: `test_checkouts_race_the_seller_editing_the_offer_without_deadlock` failed once on GitHub (push run #27) because a buyer whose order won the first round had an empty cart in the next; every cart is now refilled before each round. Its allowed outcomes are unchanged |

**What the web app's owner needs to know:** session nine regenerated its
copy of the API description; since then the back end added 4 routes and
schemas (the seller performance page and the weekly reports, D-073), listed
by `uv run python -m scripts.check_openapi_copy
../web/src/lib/api/openapi.json`. Nothing the web app already uses changed.
To use them: `cd apps/api && uv run python -m scripts.export_openapi
../web/src/lib/api/openapi.json`, then `npm run gen:api` in `apps/web`. The
review, report and feedback screens are the web app owner's; the back-end
session does not touch them.

**What needs the founder:** real search queries (unchanged); F-08, how long
search logs and rate-limit counters are kept (deleting rows needs your
approval); a private Telegram group and a bot for alerts, when you want
them; and the provisional choices marked in D-062 to D-065.

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

Copy everything from `MARKX — NEXT ENGINEERING SESSION` to `END OF
BRIEF` into a new session. It serves the web app's owner when it resumes;
a back-end-only session follows the same brief with step 5b.

---

**MARKX — NEXT ENGINEERING SESSION**

You continue MarkX from its existing state. Do not rebuild anything.

**1. Repository and branch.** `shumetmamo21-cyber/markx-marketplace`,
branch **`claude/project-scaffold`**. Never touch `main` or delete a
branch. Verify the head: `git fetch origin claude/project-scaffold && git
log -5 FETCH_HEAD`.

**2. Read first:** `AGENTS.md`, `MARKX_MASTER_BLUEPRINT.md` (sections I and
F.1 for the screens; C.3 and C.4 for who may do what), this file,
`docs/DEVELOPMENT_STATUS.md` ("The exact next task"), `docs/DECISIONS.md`
(D-001 to D-078; D-043, D-050, D-053, D-076 and parts of D-062 to D-067 are
provisional; F-01 to F-08 are open), `docs/ARCHITECTURE.md`, `docs/SETUP.md`, and `apps/web/AGENTS.md`.
Next.js 16 differs from your training: read
`apps/web/node_modules/next/dist/docs/` before using a feature.

**3. Reproduce every check before changing anything.** PostgreSQL 17 in
Docker (start `dockerd` yourself on a bare Linux machine), then from the
repository root `PGHOST=127.0.0.1 PGUSER=postgres
PGPASSWORD=postgres_dev_only infra/postgres/bootstrap.sh markx`. Then:

```bash
cd apps/api && uv sync
uv run pytest                  # expect 948 passed, twelve to fourteen minutes
uv run ruff check . && uv run ruff format --check . && uv run mypy markx
uv run alembic upgrade head && uv run alembic check
uv run python -m scripts.check_openapi_copy --exact openapi.json
uv run python -m scripts.check_openapi_copy ../web/src/lib/api/openapi.json
cd ../web && npm ci && npm run lint && npm run typecheck && npm test && npm run build
# expect 33 web unit tests
```

**Never start a second test run while one is going**: both use
`markx_test` and wreck each other. Report the real numbers. Check the
latest GitHub Actions run for the branch passed.

**4. To see the app:** `uv run python -m scripts.seed_demo` (demo data,
laptop only), `uv run uvicorn markx.main:app --port 8000`, and in
`apps/web` `npm run dev`; open `http://localhost:3000`. Sign-in codes are in
`GET /api/v1/dev/sms-inbox?phone=...`. `node e2e/buyer-journey.mjs` replays
the buyer's journey; with `MARKX_DEMO_TOTP_SECRET=...` (the secret
`seed_demo` printed), `node e2e/admin-queues.mjs` replays every admin
screen, `node e2e/shop-screens.mjs` the buyer's reviews, reports, pictures
and problem evidence with the shop's side, `node e2e/seller-dashboard.mjs`
a new shop from its application to its first offer, and `node
e2e/setup-and-account.mjs` staff setup, trust actions, the buyer's account,
proposals and closing; `staff-journey.mjs` takes the secret too. Each signs a demo phone
in once per run; the API allows five codes per phone per clock hour.

**5. Task (the web app's owner):** first pick up any API additions made
since the tenth session: `cd apps/api && uv run python -m
scripts.export_openapi ../web/src/lib/api/openapi.json`, then `cd ../web &&
npm run gen:api` (D-061; it was current at the tenth session's last commit).
Then the list in "The exact next task" in `docs/DEVELOPMENT_STATUS.md`.
**Every route a person uses has its screen** (D-070 to D-078) except
Telegram sign-in and linking, which wait for the bot. Check it again by
comparing `apps/api/openapi.json` with the `/api/v1/...` paths in
`apps/web/src` (leave out `schema.d.ts` and `openapi.json`). Any new admin route gets its line in
`apps/web/src/app/[lang]/admin/(desk)/menu.ts` and `menu.test.ts` and a step
in `e2e/admin-queues.mjs`; a seller screen the same in
`apps/web/src/app/[lang]/seller/[sellerId]/menu.ts` and
`e2e/seller-dashboard.mjs`. Where the API does not say what a person may do
with something, add a `can_*` field on both sides rather than copying the
rule into the page (D-072). The API enforces every role and seller
boundary; the web app only shows what it returns and sends the member's
choices. Every text in both message files; client components receive only
the message sections they use. Test at 360 pixels.

**5b. Task (a back-end-only session):** the back-end list in "The exact
next task". Do not modify `apps/web`; add routes and schemas only, never
change an existing one (D-061), and keep `apps/api/openapi.json` current
(`uv run python -m scripts.export_openapi openapi.json`).

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
| P1 Project foundation | Mostly done: API, database pipeline, web shell, **CI**, typed API link, **containers for API, worker and database**. The web app's container and an automated page-weight check missing |
| P2 Database and backend foundation | Mostly done: **encrypted backups with a CI restore drill, self-monitoring, alerts, daily reconciliation, worker health check**. Error tracking, the nightly schedule and off-server copy, and the staging criteria missing |
| P3 Authentication and roles | Done on the API; web sign-in for buyers done; staff sign-in screen missing |
| **P4 Customer storefront** | **Buyer journey done on the web** (D-055); images, account settings, Mini App shell missing |
| P5 Product catalogue | Done on the API, **with the image pipeline**; seed data, pictures on cards, a real bucket missing |
| P6 Seller onboarding | Done on the API; web screens missing |
| P7 Listings and inventory | Done on the API; **on the web: offers list, quick edit, check-in**; "add an offer" screen and the bot missing |
| P8 Search | Mostly done on the API, **with the evaluator**; on the web: search, filters, "did you mean", request form. Golden set needs real queries |
| P9 Cart and checkout | **Done on the API and the web** |
| P10 Multi-seller orders | Done on the API, **and on the web for both buyer and seller** |
| P11 Admin operations | **On the web: problems, orders desk, seller review, search tools. On the API also: audit-log viewer, settings and risk limits, staff accounts, dispatch board, dashboard, picture moderation, operations status, review moderation, the reports queue, data exports, seller performance and the weekly message**; their screens and the runbooks missing |
| P12 onwards | Not started |

**Numbers:** 943 API tests; 69 tables; migrations `0001` to `0012`; 122
typed API source files. The web app's own numbers are in Part A.000.

**Traps already paid for:** see `docs/DEVELOPMENT_STATUS.md` ("Lessons" and
the rules at its end), plus the sixth session's three: two test sessions
at once wreck each other; Next.js 16 pages may export only page things (a
helper exported from a page breaks the build); the dev server keeps old
message files until restarted. And the eighth session's: a migration file
added while a full test run is going fails the "latest revision" test of
that run; a docstring on a route is part of the API description; two
Pydantic schemas with one name rename each other in the API description
(the copy check catches it); time-travel tests stamp `completed_at` in the
future, so period figures must be tested with real-time actions.
