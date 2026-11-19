# MarkX — read-only audit report, 19 November 2026

Repository `shumetmamo21-cyber/markx-marketplace`, checked at the head of
`main`: commit `10a72b1` (`10a72b130abcdecec23fbac2a0c7a4dab27ddf28`).
Nothing in the project was changed. No test, migration, build or deployment
was run for this report; GitHub's own test results are used as proof. No
secret values appear here; only the names of settings.

---

## Summary in plain English

**Where things stand.** MarkX is a well-built but **unlaunched** marketplace.
All the work of the AI sessions was merged into `main` on 19 November 2026
(pull request #1). Both automatic test suites passed on that exact version:
the main test run (CI run 133) and the website click-through tests (Browser
journeys run 22). Nothing is running on the internet, and no outside account
(payments, SMS, Telegram bot, file storage, backups, domain) exists yet.

**What works (in testing).** A buyer can search in Amharic or English, see
every seller's offer for a product, fill a cart, order from several sellers
at once, pay the seller directly at handover using a six-digit code, and
report a problem. Sellers can apply, list offers, manage stock and handle
orders. Staff have screens for approvals, problems, reviews, reports,
settings and exports. Encrypted backups and a production server setup exist
as code and are rehearsed automatically.

**What is not done.** Sellers are not yet told about new orders by phone
(no Telegram bot or SMS provider is connected) — the project's own documents
call this a **launch blocker**. There is no real server, domain, file store
or off-server backup. A few Release 1 features are missing: the legal notice
before ordering, "lite mode", price-history chart, share cards/QR code, a
seller's customer list, reorder, gate photo on addresses, and the Ethiopian
calendar/clock.

**Earlier findings.** Of the eight earlier findings (a–h), **all eight are
still true in the code** (one sub-point, the copy of the encryption key, is
only covered by a written instruction). The most important for real
operation: (b) staff who belong to a store can still decide disputes,
reviews and takedowns about that store; (c) orders out for delivery or with
a failed delivery never time out; (e) about 22 website parts freeze with no
message if the internet drops, and there are no error pages; (h) the backup
design still gives the server enough power to delete all backups.

**The documents are out of date in places.** The main status file and the
handoff still say `main` holds only the first commit; the README still says
there is no web app; table and migration counts are off by one; and many
commit numbers the documents cite no longer exist, because the history was
squashed into one commit before the merge.

**Other branches.** Nothing useful is missing from `main`. The three
commits unique to `claude/markx-third-session-cq58yj` are an earlier,
alternative version of the order-delivery work that `main` already contains
in its own form, with equivalent tests.

**The 22-section audit** is not stored anywhere in the repository, and it
was not written in this conversation, so it could not be saved.

---

## Part 1 — Saving the 22-section audit

**Skipped.** The 22-section independent audit was **not written in this
conversation**, so there is nothing to save word for word.

It is also **not in the repository** on any branch. Proof: a search of the
file lists of `main`, `claude/project-scaffold`,
`claude/markx-third-session-cq58yj` and
`claude/markx-seller-management-oag1a4` finds no audit document (only
`.github/scripts/npm-audit-gate.mjs` and `.github/security/npm-audit-allowlist.json`,
which are unrelated). `docs/DECISIONS.md:2011-2014` (D-084) says: "The audit
report itself (`MARKX_INDEPENDENT_AUDIT_OPUS55.md`) was not in the
repository; the findings were taken from the founder's brief". Whether that
document has 22 sections: **UNKNOWN**.

---

## Part 2 — The report

### 1. Current state

**Latest commit on `main`:** `10a72b1`, 2026-11-19 03:45:16 +0300 (00:45:16
UTC), "Merge pull request #1 from shumetmamo21-cyber/claude/project-scaffold".
Its parents are `617a276` (the initial commit) and `373c082` (the head of
`claude/project-scaffold`). `main` has 51 commits.

**Important history fact.** Commit `daaee71` (2026-11-18 00:57 UTC,
"Handoff: the second round's final checks…") has **no parent**: the earlier
history of `claude/project-scaffold` was squashed into it. Everything before
it (sessions 1 to 10) exists on `main` only as that one commit. Proof:
`git log -1 --format=%p daaee71` prints nothing.

**Branches** (GitHub `list_branches`; ahead/behind from
`git rev-list --left-right --count origin/main...<branch>`):

| Branch | Latest commit | Date (UTC) | Behind `main` | Ahead of `main` | Shares history with `main` |
| --- | --- | --- | --- | --- | --- |
| `main` | `10a72b1` Merge pull request #1 | 2026-11-19 00:45 | — | — | — |
| `claude/project-scaffold` | `373c082` Status: CI #129, #130 and journeys #21 passed on 937c410 (D-094) | 2026-11-18 20:17 | 2 | 0 | Yes: fully merged (it is `main`'s second parent) |
| `claude/markx-third-session-cq58yj` | `55c7b24` Note the divergence from claude/project-scaffold on this branch | 2026-11-17 01:59 | 50 | 23 | Only the initial commit `617a276` |
| `claude/markx-seller-management-oag1a4` | `8df958b` Put the whole handoff in one document | 2026-11-16 19:20 | 50 | 16 | Only the initial commit `617a276` |
| `claude/markx-audit-report-oz853v` | this report's branch, made from `10a72b1` | 2026-11-19 | 0 | 1 | Yes |

The "ahead" counts for the last two old branches are by commit identity:
because `main`'s history was squashed, their commits are not ancestors of
`main` even where the content is the same. See section 6 for the content
comparison.

**Pull requests** (GitHub `list_pull_requests`, state all): **one only.**

| # | Title | From → to | State | Created | Merged |
| --- | --- | --- | --- | --- | --- |
| 1 | Scaffold MarkX marketplace monorepo | `claude/project-scaffold` → `main` | closed, **merged** | 2026-11-17 04:14 UTC | 2026-11-19 00:45 UTC |

**GitHub test results on `main` (commit `10a72b1`):**

| Run | Workflow | Event | Result | Link |
| --- | --- | --- | --- | --- |
| CI run **133** (id 44431552186) | `.github/workflows/ci.yml` | push to `main` | **success**, 00:45:22 → 01:00:25 UTC | https://github.com/shumetmamo21-cyber/markx-marketplace/actions/runs/44431552186 |
| Browser journeys run **22** (id 44431552188) | `.github/workflows/journeys.yml` | push to `main` | **success**, 00:45:22 → 00:50:46 UTC | https://github.com/shumetmamo21-cyber/markx-marketplace/actions/runs/44431552188 |

CI run 133, its five jobs, all **success**:

| Job | Result | Steps (all success) |
| --- | --- | --- |
| API (lint, types, migrations, tests) | success | Lint; Formatting; Strict type checks; Migrations apply and match the models; Tests (00:46:18 → 00:59:56); the API description is current; the web app's copy is still true; Backup, off-server copy and recovery drill (MinIO stand-in) |
| Web app (lint, types, unit tests, build) | success | Generated API types match; Lint; Strict type checks; Unit tests; Production build |
| Containers | success | Compose file valid; API/worker image builds; runs unprivileged; worker and migrations load; backup image builds with PostgreSQL 17 tools; production Compose valid; web image builds, runs unprivileged, refuses to start without settings |
| Production stack rehearsal (Compose, proxy, deploy, rollback) | success | "Rehearse a deployment" 00:45:28 → 00:48:33 |
| Security (secret scan, dependency audits) | success | Gitleaks over every commit; pip-audit; npm audit gate |

Browser journeys run 22, one job, **success**, every step passed: Page
weight; Seller dashboard; Buyer journey; Staff decide a problem; Admin
screens; Reviews, reports, pictures and problem evidence; Setup, trust
actions, account, proposals and closing; Resend cooldown; Telegram
connection off, on with test values, and off again; Turnstile widget
(Cloudflare replaced by a stand-in).

The exact number of tests that passed in run 133: **UNKNOWN** — the last 120
lines of the API job log retrieved for this report do not contain pytest's
summary line. The status document reports **1748 passed** in a local run of
D-094's code (`docs/DEVELOPMENT_STATUS.md:1317-1318`). A count of
`def test_` functions in `apps/api/tests` gives 887 (many are parametrised,
so this is not the number of test cases).

The run log also shows a GitHub warning: "Node.js 20 is deprecated…
actions/checkout@v4, actions/upload-artifact@v4, astral-sh/setup-uv@v6" are
being forced to run on Node.js 24 (API job log, last line).

Earlier runs: CI 129–132 and journeys 21 (on `937c410`/`373c082`) passed;
CI 123 and 124 (on `76b16b0`) were **cancelled**, not failed (GitHub
`list_workflow_runs`). 155 workflow runs exist in total.

### 2. Documents

Last change dates are from `git log -1 -- <file>` on `main`. **Caution:** a
date of `daaee71 2026-11-18` only means "last changed at or before the
squash"; the true earlier date is no longer in `main`'s history.

| Document | Lines | Last changed | What it is for |
| --- | --- | --- | --- |
| `MARKX_MASTER_BLUEPRINT.md` | 3163 | `daaee71` 2026-11-18 | The single source of truth: strategy, requirements, architecture, roadmap |
| `AGENTS.md` | 140 | `daaee71` 2026-11-18 | Rules for every AI agent |
| `CLAUDE.md` | 16 | `daaee71` 2026-11-18 | Start-up instructions for Claude Code |
| `README.md` | 40 | `6d97cb1` 2026-11-18 | Front page and reading order |
| `apps/web/AGENTS.md` | 33 | `daaee71` 2026-11-18 | Agent rules for the web app |
| `apps/api/migrations/README.md` | 7 | `daaee71` 2026-11-18 | Note on migrations |
| `docs/DEVELOPMENT_STATUS.md` | 2287 | `373c082` 2026-11-18 | What exists, what is tested, the next task |
| `docs/DECISIONS.md` | 3587 | `937c410` 2026-11-18 | Decisions D-001 to D-094 and the founder's open questions |
| `docs/HANDOFF.md` | 637 | `7c7a828` 2026-11-18 | Session reports and the brief for the next engineer |
| `docs/ARCHITECTURE.md` | 539 | `7c7a828` 2026-11-18 | How the code is organised |
| `docs/SETUP.md` | 716 | `7c7a828` 2026-11-18 | Running and testing on a laptop |
| `docs/DEPLOYMENT.md` | 301 | `7c7a828` 2026-11-18 | The production stack and every setting |
| `docs/runbooks/README.md` | 26 | `7c7a828` 2026-11-18 | Index of runbooks |
| `docs/runbooks/backup-and-restore.md` | 335 | `7c7a828` 2026-11-18 | Backups, drills, restores, keys |
| `docs/runbooks/checklists.md` | 54 | `6d97cb1` 2026-11-18 | Pre- and post-deployment checklists |
| `docs/runbooks/deploy.md` | 87 | `7c7a828` 2026-11-18 | Preparing a server and deploying |
| `docs/runbooks/migrations.md` | 52 | `6d97cb1` 2026-11-18 | Running migrations safely |
| `docs/runbooks/rollback.md` | 53 | `6d97cb1` 2026-11-18 | Rolling back a release |
| `docs/runbooks/secret-rotation.md` | 25 | `7c7a828` 2026-11-18 | Changing secrets |
| `docs/runbooks/telegram-linking.md` | 189 | `76b16b0` 2026-11-18 | Switching on Telegram linking |
| `docs/runbooks/tls-certificates.md` | 48 | `6d97cb1` 2026-11-18 | The site's certificate |

Other text files: `apps/api/search_eval/golden_queries.template.csv`
(template for real search queries), `apps/api/.env.example` and
`infra/production/env/*.env.example` (setting templates).

**The master blueprint is in the repository**: `MARKX_MASTER_BLUEPRINT.md`,
"**Consolidated edition 2.0 · 16 November 2026**" (line 3).

**Where documents disagree with the code or with GitHub:**

| # | Document and line | What it says | What is true | Proof |
| --- | --- | --- | --- | --- |
| 1 | `docs/DEVELOPMENT_STATUS.md:142-143` | "`main` holds the initial commit only and nothing has been merged into it." | PR #1 was merged; `main` is `10a72b1` | GitHub PR #1 `merged: true`; `git log origin/main` |
| 2 | `docs/HANDOFF.md:366` | "`main` \| `617a276`, the initial commit. **Untouched.**" | Same as above | Same |
| 3 | `docs/HANDOFF.md:367` | Lists a branch `claude/markx-engineering-p10-daa24c` | No such branch exists on GitHub | GitHub `list_branches` returns 4 branches, not that one |
| 4 | `README.md:6-12` | "What happens after confirmation (dispatch, handover, completion, payment) is not built. There is no web app" | All of these are built; `apps/web` exists; journeys run 22 passed | `apps/api/markx/orders/service.py` (`seller_dispatch`, `confirm_delivery`, `complete_seller_order`, `record_direct_payment`); `apps/web/src` |
| 5 | `README.md:16` (table) | "Schema for all of Release 1 (68 tables)" | 75 tables | 75 `__tablename__` in `apps/api/markx`; `op.create_table(` counts: 63 in `0001` + 12 later |
| 6 | `docs/DEVELOPMENT_STATUS.md:2146` | "The schema has 74 tables" | 75 (`backup_runs`, migration `0018`, is missing from the count and its list) | `apps/api/migrations/versions/20261118_1916_backup_runs.py` |
| 7 | `docs/DEVELOPMENT_STATUS.md:2125-2145` | The migration table lists `0001`–`0017` | `0018` (`backup_runs`) is missing from the table, although the same file's line 18 names it | `apps/api/migrations/versions/` has 18 files |
| 8 | `docs/DEVELOPMENT_STATUS.md:1004-1010` | "Models for refunds, payouts … the tables exist"; "`refunds`, `payouts`, provider webhooks: tables only" | **No `refunds`, `payouts` or webhook table exists** | No such `__tablename__`; `grep '"refunds"\|"payouts"'` in models and migrations finds nothing |
| 9 | `docs/DEVELOPMENT_STATUS.md:248` (P4) | Not done: "automated browser tests in CI" | Browser journeys run on every code push (journeys run 22) | `.github/workflows/journeys.yml:11-17` |
| 10 | `docs/DEVELOPMENT_STATUS.md:251` (P8) | Not done: "rating and delivery-speed filters" | The rating filter exists (`min_rating`); delivery speed does not | `apps/api/openapi.json`, `GET /api/v1/search` parameters |
| 11 | `docs/DEVELOPMENT_STATUS.md:1281-1282` | "Search does not rank or filter by rating yet." | It filters by rating (`min_rating`); ranking by rating is not built | Same; and `docs/DEVELOPMENT_STATUS.md:2267` says "the rating filter exists, D-080" — the file contradicts itself |
| 12 | `docs/DEVELOPMENT_STATUS.md:252` (P9) | "Done on the API side, **and on the web**" … then "**Not done:** the web screens" | The cart and checkout screens exist | `apps/web/src/components/CartView.tsx`, `Checkout.tsx` |
| 13 | `docs/DEVELOPMENT_STATUS.md:2264-2265` | F-01 "then needs the private store adapter (one class behind `PrivateStorage`)" | The S3/R2 adapter already exists (D-090); the same file says so at lines 2271-2272 | `apps/api/markx/core/storage.py:409` (`S3ObjectStore`) |
| 14 | `docs/DECISIONS.md:1039` | Document storage (F-01): "Local disk on a laptop only … one new adapter class" | Same as 13 | Same |
| 15 | `docs/DEVELOPMENT_STATUS.md:1243-1244` | "No failing test and no known defect in the tested code." | The same section lists known defects (commission cap not applied, D-086; paid parts with no close button) | `docs/DEVELOPMENT_STATUS.md:1159-1161`, `1152-1158` |
| 16 | `docs/DEVELOPMENT_STATUS.md:212-235`, `docs/HANDOFF.md` | Cite commits such as `7c492c6`, `eab7c21`, `497fcf5`, `88d481b`, `641a95b`, `1920e55` | These commits are **not in `main`'s history** and not on any current branch (lost in the squash) | `git merge-base --is-ancestor <c> origin/main` fails for each |
| 17 | `docs/SETUP.md:124`, `docs/DEVELOPMENT_STATUS.md:243` | "The web app is not in the Compose file yet" | True for the laptop file `infra/compose/compose.yaml`; the production file has a `web` service | `infra/production/compose.yaml:191` — not a contradiction, but easy to misread |
| 18 | `docs/DEVELOPMENT_STATUS.md:1` "Last updated" | Says nothing about the merge | — | Document predates the merge |
| 19 | `AGENTS.md:115`, `CLAUDE.md:14` | "Work on `claude/project-scaffold`" | That branch is now fully merged and 2 commits behind `main` | Section 1 |

**Founder decision list (F-01 to F-20).** It is in `docs/DECISIONS.md`,
"## Decisions that need the founder" (line 3226). F-09 and F-10 were
removed from that list when decided (D-087, D-088), so their wording is
copied from the last version that held them, commit `9af18c7`. All copies
below are **word for word**, cut straight from the files (Appendix A).

The list's introduction (`docs/DECISIONS.md:3228-3240`), word for word:

> **F-01 to F-08 have PROVISIONAL answers (D-083), given at the founder's
> request on 18 November 2026: the engineer's guess, which the founder must
> confirm or change before MarkX goes live. F-09 and F-10 (raised in D-086)
> were decided on 18 November 2026: see D-087 and D-088. F-11 to F-13
> (D-089, SMS), F-14 and F-15 (D-090, file storage), F-16 to F-18 (D-091,
> deployment), F-19 and F-20 (D-094, backups) and N-1 (D-092, notification
> channels) are open and have no provisional answer: the code does the most cautious thing until the founder
> decides.** Treat this list as part of the launch
> checklist. Each item says what the code does, what the engineer recommends
> (now the provisional answer) and why, what it blocks, and whether the
> founder's approval is required. When the founder decides one, it becomes a
> `D-` entry above, this item is removed, and its `PROVISIONAL` marker in the
> code and its line in `tests/unit/test_provisional_decisions.py` go.

**Is the 22-section audit in the repository?** **No** (see Part 1).

### 3. How it is built

**Tools and frameworks, exact versions** (Python versions from
`apps/api/uv.lock`; JavaScript versions from `apps/web/package-lock.json`;
images from the Dockerfiles and Compose files):

| Area | Tool | Version | Proof |
| --- | --- | --- | --- |
| API language | Python | 3.13 (image `python:3.13.18-slim-bookworm`) | `apps/api/pyproject.toml:5`; `apps/api/Dockerfile:17` |
| API framework | FastAPI | 0.163.1 | `uv.lock` |
| | Starlette | 1.10.0 | `uv.lock` |
| | Uvicorn | 0.54.0 | `uv.lock` |
| | Pydantic / pydantic-settings | 2.14.3 / 2.16.3 | `uv.lock` |
| Database access | SQLAlchemy | 2.1.8 | `uv.lock` |
| | Alembic (migrations) | 1.20.1 | `uv.lock` |
| | psycopg (+binary) | 3.3.9 | `uv.lock` |
| Security | cryptography | 50.0.2 | `uv.lock` |
| | argon2-cffi | 25.1.0 | `uv.lock` |
| | pyotp (staff two-step codes) | 2.12.0 | `uv.lock` |
| Files | Pillow | 13.0.0 | `uv.lock` |
| | boto3 (S3/R2/MinIO) | 1.44.5 | `uv.lock` |
| | python-multipart | 0.0.34 | `uv.lock` |
| API dev tools | pytest 9.2.0, ruff 0.17.5, mypy 2.4.1, pip-audit 2.10.1, httpx2 2.16.2, boto3-stubs 1.44.5 | | `uv.lock` |
| Database | PostgreSQL | 17 (CI and laptop: `postgres:17`; production: `postgres:17.12`; tools `postgres:17.12-bookworm`) | `.github/workflows/ci.yml:23`; `infra/production/compose.yaml:61`; `apps/api/Dockerfile:22` |
| Object storage stand-in | MinIO | `bitnamilegacy/minio:2025.7.23-debian-12-r5` (pinned by digest) | `infra/compose/compose.yaml:54` |
| Web language | Node.js | `node:22.23.5-bookworm-slim`; CI uses Node 22; `engines` `>=20.9` | `apps/web/Dockerfile:22`; `ci.yml:165`; `package.json:7` |
| Web framework | Next.js | 16.4.6 | `package-lock.json` |
| | React / React DOM | 19.3.1 | `package-lock.json` |
| | TypeScript | 5.9.3 | `package-lock.json` |
| | Tailwind CSS (+ @tailwindcss/postcss) | 4.3.5 | `package-lock.json` |
| | openapi-fetch / openapi-typescript | 0.17.0 / 7.13.0 | `package-lock.json` |
| Web tests | Vitest 5.1.0, Playwright 1.63.0, ESLint 10.15.0 (eslint-config-next 16.4.6) | | `package-lock.json` |
| Reverse proxy | nginx | `nginxinc/nginx-unprivileged:1.28.2-alpine` | `infra/production/compose.yaml:225` |
| CI | GitHub Actions: `actions/checkout@v4`, `actions/setup-node@v4`, `astral-sh/setup-uv@v6`, `actions/upload-artifact@v4`; runner `ubuntu-24.04` | | `.github/workflows/ci.yml` |
| Secret scan | Gitleaks | version not pinned in the repository; the status file says 8.28.0 was used locally — CI version **UNKNOWN** | `.gitleaks.toml`; `docs/DEVELOPMENT_STATUS.md:1394` |

**Folder layout** (tracked files):

```text
.github/            workflows (ci.yml, journeys.yml), npm-audit gate script, audit allow-list
AGENTS.md CLAUDE.md README.md MARKX_MASTER_BLUEPRINT.md
apps/
  api/              Python API and background worker
    markx/          accounts admin analytics audit backup catalog core delivery exports
                    images notifications offers ops orders payments performance reports
                    reviews search sellers trust worker  (+ main.py, registry.py)
    migrations/     Alembic, 18 versions
    scripts/        export_openapi, check_openapi_copy, seed_demo, copy_files_to_object_storage
    search_eval/    template for the search golden set
    tests/          api db deployment fixtures storage unit worker
    openapi.json    the API description (checked in CI)
  web/              Next.js web app
    src/app         pages ([lang]/(shop), seller, admin …)
    src/components  React components
    src/lib         helpers and the typed API client (lib/api)
    messages/       am.json, en.json
    e2e/            10 browser journeys (Playwright scripts)
    deploy/         start-up settings check
docs/               status, decisions, handoff, architecture, setup, deployment, runbooks/
infra/
  backup/           legacy CBC restore script
  compose/          laptop and CI Compose files
  postgres/         roles and database bootstrap
  production/       Compose, nginx, env templates, deploy.sh, rehearsal/
```

**Every API route** (185 operations, from `apps/api/openapi.json`, which CI
run 133 confirmed is current: step "The API description in apps/api is
current"). All paths start with `/api/v1`.

**admin: operations** (11)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/admin/audit-log` | Audit Log |
| GET | `/admin/dashboard` | Dashboard |
| GET | `/admin/dispatch-board` | Dispatch Board |
| GET | `/admin/ops/alerts` | Recent Alerts |
| GET | `/admin/ops/status` | Ops Status |
| GET | `/admin/settings` | Settings |
| PUT | `/admin/settings/{key}` | Change Setting |
| GET | `/admin/staff` | List Staff |
| POST | `/admin/staff` | Create Staff |
| POST | `/admin/staff/{staff_id}/active` | Set Staff Active |
| POST | `/admin/staff/{staff_id}/role` | Change Staff Role |

**admin: catalog** (21)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/admin/catalog/attributes` | All Attributes |
| POST | `/admin/catalog/attributes` | Create Attribute |
| POST | `/admin/catalog/attributes/{attribute_id}/options` | Add Option |
| POST | `/admin/catalog/brands` | Create Brand |
| GET | `/admin/catalog/categories` | All Categories |
| POST | `/admin/catalog/categories` | Create Category |
| PATCH | `/admin/catalog/categories/{category_id}` | Update Category |
| PUT | `/admin/catalog/categories/{category_id}/attributes/{attribute_id}` | Attach Attribute |
| GET | `/admin/catalog/products` | List Products |
| POST | `/admin/catalog/products` | Create Product |
| GET | `/admin/catalog/products/{product_id}` | Read Product |
| POST | `/admin/catalog/products/{product_id}/aliases` | Add Alias |
| DELETE | `/admin/catalog/products/{product_id}/aliases/{alias_id}` | Remove Alias |
| POST | `/admin/catalog/products/{product_id}/approve` | Approve |
| POST | `/admin/catalog/products/{product_id}/archive` | Archive |
| POST | `/admin/catalog/products/{product_id}/merge` | Merge |
| PUT | `/admin/catalog/products/{product_id}/text` | Update Text |
| POST | `/admin/catalog/products/{product_id}/variants` | Add Variant |
| GET | `/admin/catalog/restricted-terms` | Restricted Terms |
| POST | `/admin/catalog/restricted-terms` | Add Restricted Term |
| DELETE | `/admin/catalog/restricted-terms/{term_id}` | Remove Restricted Term |

**admin: pictures** (4)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| POST | `/admin/catalog/images/{image_id}/remove` | Remove Image |
| GET | `/admin/catalog/products/{product_id}/images` | Staff Product Images |
| POST | `/admin/catalog/products/{product_id}/images` | Add Catalogue Image |
| GET | `/admin/orders/seller-orders/{seller_order_id}/problem/photos` | Staff Problem Photos |

**admin: delivery** (6)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| PATCH | `/admin/delivery/areas/{area_id}` | Set Area Active |
| GET | `/admin/delivery/zones` | List All Zones |
| POST | `/admin/delivery/zones` | Create Zone |
| PATCH | `/admin/delivery/zones/{zone_id}` | Update Zone |
| POST | `/admin/delivery/zones/{zone_id}/areas` | Create Area |
| PUT | `/admin/delivery/zones/{zone_id}/rates` | Set Rate |

**admin: exports** (1)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/admin/exports/{kind}` | Export |

**admin: offers** (3)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/admin/offers/held` | List Held Offers |
| POST | `/admin/offers/{offer_id}/remove` | Staff Remove Offer |
| POST | `/admin/offers/{offer_id}/restore` | Staff Restore Offer |

**admin: orders** (5)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/admin/orders/problems` | Staff Open Problems |
| POST | `/admin/orders/seller-orders/{seller_order_id}/dispatch` | Staff Dispatch Seller Order |
| POST | `/admin/orders/seller-orders/{seller_order_id}/reissue-code` | Staff Reissue Handover Code |
| POST | `/admin/orders/seller-orders/{seller_order_id}/resolve-problem` | Staff Resolve Problem |
| GET | `/admin/orders/{code}` | Staff Read Order |

**admin: reports** (2)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/admin/reports` | Report Queue |
| POST | `/admin/reports/{report_id}/resolve` | Resolve Report |

**admin: reviews** (2)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/admin/reviews` | Review Queue |
| POST | `/admin/reviews/{review_id}/moderate` | Moderate Review |

**admin: search** (4)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/admin/search/synonyms` | List Synonyms |
| POST | `/admin/search/synonyms` | Add Synonym |
| DELETE | `/admin/search/synonyms/{synonym_id}` | Remove Synonym |
| GET | `/admin/search/zero-results` | Zero Results |

**admin: sellers** (14)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/admin/sellers` | List Sellers |
| GET | `/admin/sellers/invitations` | List Invitations |
| POST | `/admin/sellers/invitations` | Create Invitation |
| DELETE | `/admin/sellers/invitations/{invitation_id}` | Revoke Invitation |
| GET | `/admin/sellers/{seller_id}` | Read Seller For Review |
| POST | `/admin/sellers/{seller_id}/approve` | Approve |
| POST | `/admin/sellers/{seller_id}/documents/{document_id}/link` | Link Document For Staff |
| POST | `/admin/sellers/{seller_id}/documents/{document_id}/review` | Review Document |
| POST | `/admin/sellers/{seller_id}/recheck` | Complete Recheck |
| POST | `/admin/sellers/{seller_id}/reinstate` | Reinstate |
| POST | `/admin/sellers/{seller_id}/reject` | Reject |
| POST | `/admin/sellers/{seller_id}/request-documents` | Request Documents |
| POST | `/admin/sellers/{seller_id}/suspend` | Suspend |
| POST | `/admin/sellers/{seller_id}/verification-level` | Set Verification Level |

**auth** (6)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| POST | `/auth/otp/request` | Request Otp |
| POST | `/auth/otp/verify` | Verify Otp |
| POST | `/auth/sign-out` | Sign Out |
| POST | `/auth/sign-out-everywhere` | Sign Out Everywhere |
| POST | `/auth/staff/sign-in` | Staff Sign In |
| POST | `/auth/telegram` | Telegram Sign In |

**cart** (5)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| DELETE | `/cart` | Clear Cart |
| GET | `/cart` | Read Cart |
| POST | `/cart/accept-changes` | Accept Cart Changes |
| DELETE | `/cart/items/{offer_id}` | Remove Cart Item |
| PUT | `/cart/items/{offer_id}` | Set Cart Item |

**catalog** (9)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/catalog/brands` | Brands |
| GET | `/catalog/categories` | Category Tree |
| GET | `/catalog/categories/{slug}` | Category Detail |
| GET | `/catalog/products/{slug}` | Product |
| GET | `/catalog/products/{slug}/images` | Product Images |
| GET | `/catalog/products/{slug}/offers` | Product Offers |
| GET | `/catalog/products/{slug}/reviews` | Product Reviews |
| GET | `/catalog/stores/{slug}/offers` | Store Price List |
| GET | `/catalog/stores/{slug}/reviews` | Store Reviews |

**stores** (2)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/catalog/stores/{slug}` | Read Public Store |
| GET | `/documents/{document_id}/content` | Read Document Content |

**checkout** (2)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| POST | `/checkout` | Place Order |
| POST | `/checkout/quote` | Quote Checkout |

**delivery** (1)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/delivery/zones` | List Public Zones |

**dev** (2)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/dev/sms-inbox` | Sms Inbox |
| GET | `/media/{key}` | Media |

**health** (4)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/healthz` | Healthz |
| GET | `/healthz/live` | Healthz Live |
| GET | `/healthz/ready` | Healthz Ready |
| GET | `/healthz/worker` | Worker Health |

**me** (13)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/me` | Read Me |
| PATCH | `/me` | Update Me |
| GET | `/me/addresses` | List Addresses |
| POST | `/me/addresses` | Create Address |
| DELETE | `/me/addresses/{address_id}` | Delete Address |
| GET | `/me/data-requests` | List Data Requests |
| POST | `/me/data-requests` | Create Data Request |
| GET | `/me/notifications` | List Notifications |
| POST | `/me/notifications/read` | Read Notifications |
| DELETE | `/me/telegram` | Disconnect Telegram |
| GET | `/me/telegram` | Read Telegram Connection |
| POST | `/me/telegram` | Link Telegram |
| POST | `/me/telegram/link` | Start Telegram Link |

**orders** (11)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/me/orders` | List My Orders |
| GET | `/me/orders/{order_id}` | Read My Order |
| GET | `/me/orders/{order_id}/seller-orders/{seller_order_id}/alternatives` | My Seller Order Alternatives |
| POST | `/me/orders/{order_id}/seller-orders/{seller_order_id}/cancel` | Cancel My Seller Order |
| POST | `/me/orders/{order_id}/seller-orders/{seller_order_id}/confirm-received` | Confirm My Seller Order Received |
| POST | `/me/orders/{order_id}/seller-orders/{seller_order_id}/problem` | Report A Problem |
| POST | `/me/orders/{order_id}/seller-orders/{seller_order_id}/problem/messages` | Add To My Problem |
| GET | `/me/orders/{order_id}/seller-orders/{seller_order_id}/problem/photos` | My Problem Photos |
| POST | `/me/orders/{order_id}/seller-orders/{seller_order_id}/problem/photos` | Add My Problem Photo |
| GET | `/problem-photos/{photo_id}/content` | Read Problem Photo |
| GET | `/track/{order_id}` | Track Order |

**reviews** (4)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| POST | `/me/orders/{order_id}/items/{item_id}/review` | Write Review |
| GET | `/me/reviews` | My Reviews |
| GET | `/me/reviews/pending` | Reviewable |
| PUT | `/me/reviews/{review_id}` | Edit Review |

**search** (3)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| POST | `/product-requests` | Request A Product |
| GET | `/search` | Search Products |
| GET | `/search/suggest` | Suggest Products |

**reports** (1)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| POST | `/reports` | Report |

**seller** (17)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| POST | `/seller/applications` | Start Application |
| GET | `/seller/eligibility` | Read Eligibility |
| GET | `/seller/{seller_id}` | Read Seller |
| POST | `/seller/{seller_id}/close` | Close Seller |
| GET | `/seller/{seller_id}/documents` | List Documents |
| POST | `/seller/{seller_id}/documents` | Upload Document |
| POST | `/seller/{seller_id}/documents/{document_id}/link` | Link Own Document |
| GET | `/seller/{seller_id}/legal` | Read Legal |
| PATCH | `/seller/{seller_id}/legal` | Update Legal |
| GET | `/seller/{seller_id}/members` | List Members |
| POST | `/seller/{seller_id}/members` | Add Member |
| DELETE | `/seller/{seller_id}/members/{member_id}` | Remove Member |
| PUT | `/seller/{seller_id}/payout-account` | Set Payout Account |
| GET | `/seller/{seller_id}/payout-accounts` | List Payout Accounts |
| GET | `/seller/{seller_id}/store` | Read Store |
| PATCH | `/seller/{seller_id}/store` | Update Store |
| POST | `/seller/{seller_id}/submit` | Submit Application |

**seller: offers** (11)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/seller/{seller_id}/dashboard` | Dashboard |
| GET | `/seller/{seller_id}/offers` | List Offers |
| POST | `/seller/{seller_id}/offers` | Create Offer |
| POST | `/seller/{seller_id}/offers/check-in` | Check In |
| DELETE | `/seller/{seller_id}/offers/{offer_id}` | Remove Offer |
| GET | `/seller/{seller_id}/offers/{offer_id}` | Read Offer |
| PATCH | `/seller/{seller_id}/offers/{offer_id}` | Update Offer |
| POST | `/seller/{seller_id}/offers/{offer_id}/pause` | Pause Offer |
| POST | `/seller/{seller_id}/offers/{offer_id}/resume` | Resume Offer |
| PUT | `/seller/{seller_id}/offers/{offer_id}/stock` | Set Stock |
| POST | `/seller/{seller_id}/product-proposals` | Propose Product |

**seller: orders** (11)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/seller/{seller_id}/orders` | List Seller Orders |
| GET | `/seller/{seller_id}/orders/{seller_order_id}` | Read Seller Order |
| POST | `/seller/{seller_id}/orders/{seller_order_id}/confirm` | Confirm Seller Order |
| POST | `/seller/{seller_id}/orders/{seller_order_id}/decline` | Decline Seller Order |
| POST | `/seller/{seller_id}/orders/{seller_order_id}/delivery-failed` | Report Seller Order Delivery Failed |
| POST | `/seller/{seller_id}/orders/{seller_order_id}/dispatch` | Dispatch Seller Order |
| POST | `/seller/{seller_id}/orders/{seller_order_id}/handover` | Hand Over Seller Order |
| POST | `/seller/{seller_id}/orders/{seller_order_id}/payment` | Record Seller Order Payment |
| POST | `/seller/{seller_id}/orders/{seller_order_id}/problem/reply` | Reply To Seller Order Problem |
| POST | `/seller/{seller_id}/orders/{seller_order_id}/ready` | Mark Seller Order Ready |
| POST | `/seller/{seller_id}/orders/{seller_order_id}/return` | Return Seller Order |

**seller: pictures** (5)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/seller/{seller_id}/orders/{seller_order_id}/problem/photos` | Seller Problem Photos |
| POST | `/seller/{seller_id}/orders/{seller_order_id}/problem/photos` | Add Seller Problem Photo |
| POST | `/seller/{seller_id}/photos/{image_id}/withdraw` | Withdraw Seller Photo |
| GET | `/seller/{seller_id}/products/{product_id}/photos` | Seller Photos |
| POST | `/seller/{seller_id}/products/{product_id}/photos` | Add Seller Photo |

**seller: performance** (2)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/seller/{seller_id}/performance` | Performance |
| GET | `/seller/{seller_id}/weekly-reports` | Weekly Reports |

**seller: reviews** (2)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| GET | `/seller/{seller_id}/reviews` | Seller Reviews |
| POST | `/seller/{seller_id}/reviews/{review_id}/reply` | Reply To Review |

**telegram** (1)

| Method | Path | What it does (route summary) |
| --- | --- | --- |
| POST | `/telegram/webhook` | Telegram Webhook |

**Every database table** (75; one `__tablename__` each under `apps/api/markx`):

`addresses`, `analytics_events`, `attribute_option_translations`,
`attribute_options`, `attribute_translations`, `attributes`, `audit_log`,
`backup_runs`, `brands`, `cart_items`, `carts`, `categories`,
`category_attributes`, `category_translations`, `commission_rules`,
`data_requests`, `delivery_areas`, `delivery_rates`, `delivery_zones`,
`dispute_cases`, `dispute_messages`, `fee_charges`, `inventory`,
`inventory_movements`, `inventory_reservations`, `ledger_accounts`,
`ledger_entries`, `ledger_transactions`, `notification_deliveries`,
`notifications`, `offer_price_history`, `offers`, `ops_alerts`,
`order_items`, `order_status_events`, `orders`, `otp_challenges`,
`otp_locks`, `outbox`, `payment_attempts`, `payment_intents`,
`problem_photos`, `product_aliases`, `product_images`, `product_requests`,
`product_translations`, `product_variants`, `products`,
`rate_limit_counters`, `rating_summaries`, `reports`, `restricted_terms`,
`reviews`, `scheduled_jobs`, `search_documents`, `search_queries`,
`search_synonyms`, `seller_documents`, `seller_invitations`,
`seller_members`, `seller_order_reminders`, `seller_orders`,
`seller_payout_accounts`, `seller_weekly_reports`, `sellers`, `sessions`,
`settings`, `shipments`, `sms_messages`, `staff_members`, `stores`,
`telegram_link_tokens`, `telegram_updates`, `tracking_events`, `users`.

Tables with **no behaviour yet** (per `docs/DEVELOPMENT_STATUS.md:1004-1014`
and the models): `analytics_events`; `payment_attempts` (Release 2);
`commission_rules` (read by checkout, never written: `apps/api/markx/orders/service.py:525`).

**Every migration** (`apps/api/migrations/versions/`; descriptions from each
file's docstring and `docs/DEVELOPMENT_STATUS.md:2129-2145`):

| Rev | File | What it did |
| --- | --- | --- |
| 0001 | `20261116_1525_initial_schema.py` | 63 tables for Release 1 with their CHECK, UNIQUE and foreign-key rules |
| 0002 | `20261116_1540_history_protection_and_ledger_balance.py` | History tables made append-only; a trigger that makes every ledger transaction balance |
| 0003 | `20261116_1730_fix_ledger_balance_trigger.py` | Fixes 0002's ledger trigger (it made every ledger insert fail) |
| 0004 | `20261116_1818_seller_onboarding.py` | `seller_invitations`; the `draft` review state; new seller columns and checks |
| 0005 | `20261116_2000_offer_staff_hold.py` | `offers.removed_by_staff_at`: a staff takedown holds (D-032) |
| 0006 | `20261116_2010_scheduled_jobs.py` | `scheduled_jobs` (D-035) |
| 0007 | `20261116_2030_order_life_cycle.py` | The seller-order state diagram enforced by a database trigger (D-038) |
| 0008 | `20261117_0936_product_pictures_and_problem_photos.py` | Picture pipeline columns; `problem_photos`, append-only (D-062) |
| 0009 | `20261117_0958_operations_alerts.py` | `ops_alerts` (D-064) |
| 0010 | `20261117_1056_reviews_and_rating_summaries.py` | Review moderation state; `rating_summaries` (D-066) |
| 0011 | `20261117_1116_listing_reports.py` | Report reasons, notes, one open report per person and target (D-067) |
| 0012 | `20261117_1158_seller_weekly_reports.py` | `seller_weekly_reports` (D-073; its docstring says D-069) |
| 0013 | `20261118_0700_paid_orders_never_end_undelivered.py` | A paid part can never end declined/expired/cancelled/returned (D-086) |
| 0014 | `20261118_0800_payment_recorded_at_handover.py` | A direct payment may be recorded only from handover on (F-09 → D-087) |
| 0015 | `20261118_1014_sms_delivery_records.py` | `sms_messages` (D-089) |
| 0016 | `20261118_1645_notification_deliveries_and_order_reminders.py` | `notification_deliveries`, `seller_order_reminders` (D-092) |
| 0017 | `20261118_1752_telegram_account_linking.py` | `telegram_link_tokens`, `telegram_updates`, two `users` columns (D-093) |
| 0018 | `20261118_1916_backup_runs.py` | `backup_runs` (D-094) |

CI run 133 step "Migrations apply and match the models" passed.

**Background jobs.** The worker (`python -m markx.worker`) runs these
scheduled jobs (`apps/api/markx/worker/jobs.py:58-107`) and drains the
`outbox` table (`apps/api/markx/worker/outbox.py`):

| Job | Every | What it does |
| --- | --- | --- |
| `orders.expire_unanswered` | 1 min | Expires `placed` orders the seller did not answer |
| `orders.remind_approaching_deadline` | 1 min | One reminder before the answer deadline |
| `orders.complete_after_problem_window` | 5 min | Completes `delivered` parts after the problem window |
| `orders.cancel_overdue_fulfilment` | 10 min | Cancels `confirmed`/`ready` parts held past 14 days |
| `offers.mark_stale` | 1 h | Sinks/hides offers whose price was not confirmed |
| `sellers.activate_due_payout_accounts` | 5 min | Activates payout accounts after the cooling-off |
| `search.rebuild_all` | 1 h | Rebuilds search documents |
| `sellers.weekly_report` | 1 h | Sends each store's weekly performance message once |
| `reviews.recount_all` | 1 day | Recounts ratings |
| `retention.prune` | 1 day | Deletes old search logs and rate-limit counters (PROVISIONAL, F-08) |
| `ops.reconcile` | 1 day | Daily reconciliation |
| `ops.watch` | 5 min | Health checks that raise alerts |

The **backup** runs as a separate production service
(`infra/production/compose.yaml:278`, `python -m markx.backup`), nightly at
`MARKX_BACKUP_HOUR_UTC`.

**Outside service connections** — none is connected to a real account:

| Service | Code | State | Proof |
| --- | --- | --- | --- |
| **Payment** | Only a *record* that the buyer paid the seller directly; `payment_intents`/`payment_attempts` tables; no provider | **Not built** (Release 2). "Payment webhooks are not built." | `apps/api/markx/core/http.py:34`; `apps/api/markx/payments/` holds only `models.py`, `ledger.py` |
| **SMS** | `FakeSmsSender`, `HttpSmsSender` with a placeholder wire format | **Fake** on laptops; real servers refuse to start with the fake; no provider chosen (F-11) | `apps/api/markx/notifications/sms.py:181,244,344,442-457`. Settings: `MARKX_SMS_PROVIDER`, `MARKX_SMS_API_URL`, `MARKX_SMS_API_KEY`, `MARKX_SMS_SENDER_ID`, `MARKX_SMS_TIMEOUT_SECONDS` |
| **Telegram push (order alerts)** | `FakePushSender`, `BotApiPushSender` | **Off**: on a real server no provider → delivery recorded `unavailable`; no bot exists | `apps/api/markx/notifications/push.py:292-310`. Settings: `MARKX_TELEGRAM_PUSH_PROVIDER`, `MARKX_TELEGRAM_BOT_TOKEN` |
| **Telegram account linking** | one-time link + webhook | **Switched off** (`MARKX_TELEGRAM_LINKING_ENABLED` defaults to false) | `apps/api/markx/core/config.py:160`; settings `MARKX_TELEGRAM_BOT_USERNAME`, `MARKX_TELEGRAM_WEBHOOK_SECRET`, `MARKX_TELEGRAM_LINK_TTL_MINUTES` |
| **Telegram alerts to staff** | `TelegramAlertSender`, else log/file | **Off** until a group exists (F-18) | `apps/api/markx/ops/alerts.py:31-60`; setting `MARKX_ALERT_TELEGRAM_CHAT_ID` |
| **Telegram sign-in** | `POST /api/v1/auth/telegram` (signature check) | Built in the API, no web screen, no bot | `openapi.json` |
| **File storage** | `LocalObjectStore`, `S3ObjectStore` for `minio`, `s3`, `r2` | **Local/MinIO only**; no S3 or R2 account; real servers refuse `local` (F-01, F-14, F-15) | `apps/api/markx/core/storage.py:182-246,409`. Settings: `MARKX_FILE_STORAGE_PROVIDER`, `MARKX_STORAGE_*` |
| **Cloudflare Turnstile** | `FakeBotCheck`, `RefusingBotCheck`, `TurnstileBotCheck` | **Fake** on laptops; tested only against stand-ins; no production widget; a real server without it refuses sign-in codes | `apps/api/markx/core/botcheck.py:53-180`. Settings: `MARKX_BOT_CHECK_PROVIDER`, `MARKX_TURNSTILE_SECRET_KEY`, `MARKX_TURNSTILE_SITE_KEY`, `MARKX_TURNSTILE_ALLOWED_HOSTNAMES` |
| **Courier** | `partner_courier` delivery method and a staff dispatch board | **Manual only**; no courier company integration | `apps/api/markx/delivery/models.py:30`; `apps/api/markx/admin/service.py:255` |
| **Off-server backups** | S3-compatible destination for `s3`/`r2` | **Not connected**; tested only with MinIO (F-16) | `infra/production/env/backup.env.example` (names `MARKX_BACKUP_DESTINATION*`, `MARKX_BACKUP_SOURCE_*`, `MARKX_BACKUP_RETENTION_*`) |
| **AWS / any cloud** | — | Nothing created or deployed | `docs/DEVELOPMENT_STATUS.md:1068` |

Development-only default values for `MARKX_SECRET_KEY` and
`MARKX_ENCRYPTION_KEY` exist in `apps/api/markx/core/config.py:46-48`; the
configuration refuses them on staging and production (per the file's own
rule at `config.py:356` and `pyproject.toml` per-file note). Values not
reproduced here.

### 4. What is finished — Release 1 requirements

From the blueprint's requirement index (`MARKX_MASTER_BLUEPRINT.md:854-953`),
every item whose stage is R1 (or partly R1). "Tested" means the code exists
and CI run 133 / journeys run 22 passed; nothing was run for this report.

**Customer (C)**

| ID | Requirement (short) | State | Proof / what is missing |
| --- | --- | --- | --- |
| C-01 | Browse without an account | DONE | Public `catalog/*`, `search` routes; journeys "Buyer journey" |
| C-02 | Search in Amharic script, Latin Amharic, English, typos | DONE | `apps/api/markx/search/`; D-051, D-052 |
| C-03 | Filters and sorts | PARTIAL | `GET /search` has category, brand, price, condition, `min_level`, `min_rating`, `in_stock`; sort only `relevance`/`price`/`freshness`. **Missing:** delivery-speed filter, "total cost" sort (`openapi.json`) |
| C-04 | Product page with every offer | DONE | `RankedOfferOut` carries price, condition, warranty, seller level, delivery fee for `zone`, `total_santim`, `price_confirmed_at` |
| C-05 | Amharic/English toggle; Ethiopian dates and clock | PARTIAL | Both languages exist (`apps/web/messages/am.json`, `en.json`). Dates use `Intl.DateTimeFormat("am-ET")` with no Ethiopian calendar option and no Ethiopian clock (`apps/web/src/lib/format.ts:34-39`) |
| C-06 | Cart by seller, survives a dropped connection | DONE | Server-side cart (`/api/v1/cart`, `CartGroupOut`) |
| C-07 | Guest checkout with a phone number | PARTIAL | Order needs a signed-in account; a visitor's cart survives sign-in (D-036; `docs/DEVELOPMENT_STATUS.md:252`) |
| C-08 | Address: area, landmark, map pin, second phone, gate photo, notes | PARTIAL | All but the **gate photo** (`apps/api/markx/accounts/models.py:186-198`) |
| C-09 | Direct order flow | DONE | confirm/decline, `payment` route; D-087 |
| C-10 | Order page, timeline, Telegram/SMS updates, secure link | PARTIAL | Timeline and `/track/{order_id}` exist; **no real Telegram/SMS delivery** |
| C-11 | Sign-in by phone code or Telegram | PARTIAL | Phone code done; Telegram sign-in API only, no web screen, no bot |
| C-12 | Lite mode | NOT STARTED | No lite mode found in `apps/web/src` |
| C-15 | Handover code | DONE | `handover_code`, `confirm_delivery`, five-try lock (`tests/api/test_fulfilment.py:216`) |
| C-16 | Problem report with photos in a window (log only in R1) | DONE | `problem`, `problem/photos` routes; `tests/api/test_disputes.py` |
| C-18 | Reviews after a completed order | DONE (without photos) | `reviews` routes; photos on reviews not built (`docs/DEVELOPMENT_STATUS.md:2266`) |
| C-19 | Saved addresses, order history, reorder | PARTIAL | Addresses and history exist; **no reorder** found |
| C-21 | Price history chart (R1) | NOT STARTED | `offer_price_history` table is written; no route or chart |
| C-23 | Collection at the shop with a code | DONE | `shop_collection` method (`apps/api/markx/delivery/models.py:31`), `handover` route |
| C-26 | Next-best offer | DONE | `.../alternatives` route; D-049 |
| C-27 | Legal disclosure before ordering | NOT STARTED | Nothing found; waits for founder wording (`docs/DEVELOPMENT_STATUS.md:252`) |
| C-28 | Data requests from the account page | DONE | `me/data-requests`; `apps/web/src/components/AccountForms.tsx` |
| C-30 | Report link on listings, reviews, stores | DONE | `POST /reports`; `ReportForm.tsx` |

**Seller (S)**

| ID | Requirement | State | Proof / missing |
| --- | --- | --- | --- |
| S-01 | Apply from a phone; invite-only | DONE | `seller/applications`, `admin/sellers/invitations` |
| S-02 | Verification levels; private documents | DONE (storage local/MinIO only) | `sellers/service.py`; F-01 open |
| S-03 | Store page: name, logo, description, areas, hours, policies, track record | PARTIAL | **No logo upload** (`stores.logo_key` unused, `docs/DEVELOPMENT_STATUS.md:1011`) |
| S-04 | Add an offer quickly | DONE | `POST seller/{id}/offers` |
| S-05 | Propose a product | DONE | `product-proposals` route |
| S-06 | Phone photos, compressed **on the device** | PARTIAL | Upload exists; cleaning/resizing is on the server (D-062); no on-device compression in `PhotoUpload.tsx` |
| S-07 | Order inbox on web **and Telegram bot** | PARTIAL | Web done; no bot |
| S-08 | One-tap check-in; stale offers sink then hide | DONE | `offers/check-in`, `offers.mark_stale` job |
| S-09 | Owner and manager members (R1) | DONE | `seller/{id}/members` |
| S-10 | Share cards, QR code, shareable price list | PARTIAL | Price list route `catalog/stores/{slug}/offers` exists; **no share cards or QR** (`docs/DEVELOPMENT_STATUS.md:1041`) |
| S-11 | Customer list limited to own orders | NOT STARTED | No such route in `openapi.json` |
| S-12 | Own rider, update status | DONE | `dispatch`, `handover`, `delivery-failed` routes |
| S-13 | Payout account with cooling-off (collected in R1) | DONE | `payout-account`; `sellers.activate_due_payout_accounts` job |
| S-15 | Partner courier, manual dispatch in R1 | DONE | `admin/dispatch-board`, staff dispatch |
| S-16 | Reply to reviews and problems | DONE | `reviews/{id}/reply`, `problem/reply` |
| S-17 | Performance page | DONE | `seller/{id}/performance` |
| S-24 | Quick-edit list **and bot commands** | PARTIAL | Quick edit done (`SellerOfferRow.tsx`); no bot |
| S-26 | Weekly performance message | PARTIAL | Built (`sellers.weekly_report`), but it can only reach the seller in the app until a channel is connected |

**Administration (AD)**

| ID | Requirement | State | Proof / missing |
| --- | --- | --- | --- |
| AD-01 | Application queue, yearly re-check | DONE | `admin/sellers/*`, `recheck`; `sellers.recheck_due_on` (`apps/api/markx/sellers/models.py:134`) |
| AD-02 | Catalogue control | DONE (merge refused for products with offers, F-06) | `admin/catalog/*`; `catalog/service.py:703` |
| AD-03 | Listing and image moderation; restricted goods | DONE | `admin/offers/*`, `admin/catalog/images/*/remove`, `restricted-terms` |
| AD-04 | Order oversight | DONE | `admin/orders/{code}`, dispatch, reissue code |
| AD-05 | Delivery zones, fee table, dispatch board | DONE | `admin/delivery/*`, `admin/dispatch-board` |
| AD-06 | Staff roles, two-step sign-in, audit, switches | DONE | `auth/staff/sign-in` with TOTP (`accounts/router.py:162`), `admin/staff`, `admin/settings` |
| AD-07 | Synonyms, zero-result report | DONE | `admin/search/*` |
| AD-09 | Problem cases, log in R1 | DONE | `resolve-problem` |
| AD-12 | Review moderation | DONE | `admin/reviews/*` |
| AD-13 | Risk limits: value caps, pay-at-door eligibility, **caps for new accounts** | PARTIAL | `orders.max_order_value_santim`, `orders.max_open_direct_orders` (`settings_store.py:158-172`); no new-account cap found |
| AD-14 | Business dashboard | DONE | `admin/dashboard` |
| AD-16 | Reports queue | DONE | `admin/reports` |
| AD-17 | Audit-log viewer | DONE | `admin/audit-log` |

Count: **DONE 35 · PARTIAL 14 · NOT STARTED 4** (53 Release 1 items) (C-12, C-21, C-27, S-11).

### 5. Earlier findings

| | Finding | Verdict | Proof |
| --- | --- | --- | --- |
| a | Commission is zero; the cap is saved but not applied | **CONFIRMED** | No route or migration writes `commission_rules`; with no rule the fee rate is `0` (`apps/api/markx/orders/service.py:514-538`). `fee_charges.cap_santim` and `commission_rules` have a cap column (`apps/api/markx/payments/models.py:127,149`) but no code reads it; `cap_applied` is always false (`payments/models.py:175`). Documented: `docs/DEVELOPMENT_STATUS.md:1159-1161,1273-1274` |
| b | The "not your own store" check exists only in seller verification | **CONFIRMED** | `_refuse_own_seller` (`apps/api/markx/sellers/service.py:150-166`) is called only at `sellers/service.py:703` and `:839`. It is absent from `resolve_dispute` (`orders/service.py:1939+`), review `moderate` (`reviews/service.py:250-273`), `staff_remove_offer` / `staff_restore_offer` (`offers/service.py:594-622`) and report `resolve` (`reports/service.py:112`). Only tests for it: `tests/api/test_seller_onboarding.py:517,523` |
| c | Out-for-delivery and failed-delivery orders never expire | **CONFIRMED** | The deadline jobs select only `placed` (`orders/service.py:1129+`), `delivered` (`:1648+`) and `confirmed`/`ready` (`:1700+`). Nothing moves `out_for_delivery` or `delivery_failed`. The only check is an alert for *paid* parts in `delivery_failed` over a day (`apps/api/markx/ops/checks.py:67,278-286`) |
| d | Holding a competitor's stock by ordering and cancelling | **CONFIRMED** (limited, not removed) | Placing an order holds stock; a buyer may cancel and re-order with no cancellation limit or cool-down found. Limits that exist: 3 open pay-at-door orders (`orders.max_open_direct_orders`, `core/settings_store.py:158`), an order-value cap (`:166`), 30 checkouts per buyer per hour (`apps/api/markx/orders/router.py:227`). An unanswered order also holds stock until the business-hours deadline passes. One account can therefore keep stock held continuously, and several phone numbers multiply it |
| e | ~20 parts of the site freeze with no message when the connection drops; no proper error pages | **CONFIRMED** | 22 component files call the API from the browser with no `try`/`catch` (only `StaffActions.tsx` has one, for one JSON parse). `openapi-fetch` throws when the network fails, so the code after `await` never runs. Example: `apps/web/src/components/AddToCart.tsx:25-31` sets "adding", awaits, and never resets on a thrown error — the button stays disabled. No `error.tsx` or `global-error.tsx` exists; only `apps/web/src/app/[lang]/not-found.tsx` |
| f | Certificates do not renew automatically; rollback breaks with an image prefix | **CONFIRMED** | No certbot or renewal job in `infra/`; the deploy hook `install-certificate.sh` is "not in the repository yet" (`docs/runbooks/tls-certificates.md:22-31`). Compose names images `${MARKX_IMAGE_PREFIX:-markx}/api:…` (`infra/production/compose.yaml:40,191,278`) but `deploy.sh rollback` checks the fixed names `markx/api:$MARKX_RELEASE` and `markx/web:$MARKX_RELEASE` (`infra/production/deploy.sh:191`), so with a prefix set the rollback refuses ("images … are not on this server") |
| g | picomatch warning allowed until 31 Dec 2026; CSP allows inline scripts | **CONFIRMED** | `.github/security/npm-audit-allowlist.json`: `GHSA-fc5q-39xc-vjpf`, picomatch, high, `"expires": "2026-12-31"`. CSP: `script-src 'self' 'unsafe-inline' …` (`apps/web/next.config.ts:32`, explained at `:13`); also `docs/DEVELOPMENT_STATUS.md:1208-1209` |
| h1 | The server's storage key can delete every backup | **CONFIRMED** | The server-held destination key is to be allowed `DeleteObject` (`docs/runbooks/backup-and-restore.md:306-308`); retention deletes with it (`apps/api/markx/backup/destination.py:383-385`) |
| h2 | Backups not protected by object lock | **CONFIRMED** | Only advised "if offered", as part of F-16 (`backup-and-restore.md:293-295,306`); no object-lock code in `apps/api/markx/backup/` |
| h3 | Recovery drills put the recovery private key on the server | **CONFIRMED** | The monthly drill copies `recovery.key` to `/root/recovery` on the server (`backup-and-restore.md:177-197`); the runbook admits it (`:205-207`) |
| h4 | Restore runs with full database admin rights | **CONFIRMED** | Drill: `-e PGUSER=postgres` (`backup-and-restore.md:191`); restore needs "a PostgreSQL 17 server where you are superuser" (`:215-216`) |
| h5 | A failed upload can be reused just by its name | **CONFIRMED** | Before uploading a file, the runner lists the destination and treats a blob as present when its **name** is listed (`apps/api/markx/backup/runner.py:249-251,261,280-281`); the listed size is collected but not compared, and the content is not re-read on reuse. The runner's docstring says interrupted runs leave blobs "for the next run to reuse" (`runner.py:23-27`). (A later drill would detect a bad blob.) |
| h6 | All alerts run on the server they watch | **CONFIRMED** | Alerts are produced by the worker's `ops.watch` on the same host (`worker/jobs.py:106`); no outside monitor exists (F-18; `docs/DEVELOPMENT_STATUS.md:1289-1292`) |
| h7 | `MARKX_ENCRYPTION_KEY` and `MARKX_SECRET_KEY` have no recovery copy off the server | **CONFIRMED** for the system; partly covered by an instruction | Backups never include them (`backup-and-restore.md:92-93`). For `MARKX_ENCRYPTION_KEY` there is only a manual instruction to keep a copy where the founder keeps recovery material (`docs/runbooks/deploy.md:29-31`, `docs/DEPLOYMENT.md:128`); it is not in the activation steps or any check. For `MARKX_SECRET_KEY` no such instruction was found |
| h8 | The server holds the key that signs backups | **CONFIRMED** | `/etc/markx/backup-signing.key` on the server (`backup-and-restore.md:87`; `infra/production/env/backup.env.example` header) |

### 6. Unmerged work

**`claude/markx-third-session-cq58yj`.** Its 23 commits not in `main` by
identity are: the 16 of `claude/markx-seller-management-oag1a4` (below), 4
more from session three (`399507e`, `bd835ef`, `7079cb5`, `eb52d2f`), and
**the three unmerged commits**:

| Commit | Date (UTC) | Contents |
| --- | --- | --- |
| `03a879b` | 2026-11-17 01:54 | "Complete the seller order life cycle: dispatch, handover code, completion" — `orders/router.py`, `schemas.py`, `selectors.py`, `service.py` (+398 lines), `worker/jobs.py` (a `orders.complete_delivered` job), tests in `test_fulfilment.py`, `test_checkout_contention.py`, `test_worker.py` (934 lines added) |
| `6f81193` | 2026-11-17 01:58 | "Document the fulfilment milestone" — README, ARCHITECTURE, DECISIONS (D-043, D-044), DEVELOPMENT_STATUS, HANDOFF |
| `55c7b24` | 2026-11-17 01:59 | "Note the divergence from claude/project-scaffold" — a note in DEVELOPMENT_STATUS and HANDOFF that a fourth session built the same milestone on the working branch |

**Is anything missing from `main`? No functional gap was found.** The
branch's versions are an alternative implementation; `main` has its own
version of each piece:

| On the branch (`03a879b`) | On `main` |
| --- | --- |
| `dispatch` | `seller_dispatch`, `staff_dispatch`, `_dispatch` |
| `confirm_receipt` | `confirm_received` |
| `report_delivery_failure` | `report_delivery_failed`, `return_to_seller` |
| `complete_delivered_orders`, `_complete`, job `orders.complete_delivered` | `complete_after_problem_window`, `complete_seller_order`, job `orders.complete_after_problem_window` |
| `shows_handover_code` | `handover_code`, `staff_reissue_handover_code` |
| test `…locks_after_five_wrong_tries` | `test_wrong_codes_lock_the_shipment_until_staff_reissue` (`test_fulfilment.py:216`) |
| test `…retried_or_returned` | `test_a_failed_delivery_is_retried_and_finally_returned` (`:292`) |
| test `…refused_at_every_step` | `test_moves_out_of_order_are_refused` (`:337`) |
| test `…the_buyer_and_the_clock_race_to_complete…` | `test_completion_races_the_buyer_the_worker_and_the_payment_record` (`tests/db/test_fulfilment_contention.py:162`) |

Every route path of the branch's `orders/router.py` also exists on `main`.
No file exists only on the branch (`git diff --diff-filter=D origin/claude/markx-third-session-cq58yj origin/main` is empty).
`docs/HANDOFF.md:217-236` records that the founder made the fourth
session's version official, that the branch is kept as a reference, and
that one test was ported from it (`eab7c21`, a commit no longer in `main`'s
history). Whether every *behavioural detail* of the branch's version is
matched: **UNKNOWN** without running both; the names and tests above match
in purpose.

**`claude/markx-seller-management-oag1a4`:** 16 commits (`a1e1ce6` …
`8df958b`, 16 November). `docs/DECISIONS.md:437-441` (D-031) says every
commit was pushed to it and to `claude/project-scaffold` and "they are
identical". **Fully merged in content:** no file and no test name exists
only on it (comparisons as above); its differences from `main` are older
versions of lines changed later. Not merged by commit identity (squash).

**`claude/project-scaffold`:** fully merged (0 ahead; it is `main`'s second
parent).

### 7. Loose ends

**TODO / FIXME notes: 0.** A search for `TODO`, `FIXME`, `XXX` and `HACK`
across tracked files (lock files excluded) finds only `"XXX"` used as a
fake currency in `apps/api/tests/unit/test_money.py:101`, which is test
data, not a note. So there is no "ten most important" TODO list.

The code instead marks open questions with **`PROVISIONAL`** (15 lines) and
in-code notes. The ten most important open markers:

1. `apps/api/markx/core/storage.py:586` — PROVISIONAL (F-01): identity documents to a private R2 bucket; no bucket exists, real servers refuse to start.
2. `apps/api/markx/notifications/sms.py:16,244` — the SMS wire format is "MarkX's own placeholder shape, NOT any provider's API" (F-11).
3. `apps/api/markx/core/http.py:34` — "Payment webhooks are not built."
4. `apps/api/markx/offers/router.py:51` — PROVISIONAL (F-07): who may lift a takedown.
5. `apps/api/markx/offers/service.py:57` — PROVISIONAL (F-04): every used item needs Level 2.
6. `apps/api/markx/sellers/service.py:67` — PROVISIONAL (F-03): a TIN has exactly ten digits.
7. `apps/api/markx/sellers/service.py:920` — PROVISIONAL (F-05): a rejected applicant needs a new invitation.
8. `apps/api/markx/catalog/service.py:703-704` — merging products that have offers "is not built" (PROVISIONAL F-06).
9. `apps/api/markx/accounts/permissions.py:30` — PROVISIONAL (F-02): ownership transfer, not built.
10. `apps/api/markx/core/settings_store.py:261-278`, `ops/retention.py:3`, `worker/jobs.py:99` — PROVISIONAL (F-08): retention periods.

`apps/api/tests/unit/test_provisional_decisions.py:31` keeps these markers
in place.

**Things in the code that no document names** (search of `docs/*.md`,
`docs/runbooks/*.md`, `README.md` for the file name or path):

- Production nginx files: `infra/production/nginx/nginx.conf`,
  `snippets/proxy-api.conf`, `proxy-common.conf`, `proxy-web.conf`,
  `tls.conf`, `templates/markx.conf.template` (the proxy is described in
  words, but these files are not named).
- `infra/production/rehearsal/compose.rehearsal.yaml`.
- `apps/web/deploy/start.mjs`, `apps/web/deploy/check-env.d.mts`.
- API modules `markx/analytics`, `markx/audit`, `markx/trust`,
  `markx/catalog`, `markx/delivery` are not named by path (described by
  topic; `README.md:62` names `analytics/` as models only).
- 84 of the 185 API routes are not written out by their path in any
  document (they may be described in words; `apps/api/openapi.json` is the
  full list).
- CI's Node.js 20 deprecation warning for the pinned GitHub actions
  (section 1) is not mentioned anywhere.

---

## Appendix A — Founder decisions, word for word

### F-09 and F-10, as they stood in `docs/DECISIONS.md` at commit `9af18c7` (lines 2452–2490)

They were decided on 18 November 2026 and became D-087 and D-088
(`docs/DECISIONS.md:2282`, `:2317`).

````markdown
### F-09 How staff settle a paid order that cannot go ahead

- **Today (D-086):** a part with a recorded direct payment can no longer be
  cancelled by the buyer or the overdue job, or marked returned; it waits,
  and staff are alerted. Staff have no button that closes it with the money
  returned, because MarkX moves no money in Release 1 and the life cycle has
  no arrow for it outside a problem case.
- **Options:**
  1. **Staff record that the shop gave the money back** (as on a problem
     case, J.5: "staff record it"), with a written reason, which then lets
     the part end. Needs a refund record (the `refunds` table exists) and a
     staff screen. Keeps pre-delivery payment possible.
  2. **Record a payment only once the goods are handed over** (`delivered`
     on). The problem cannot arise; a transfer made before delivery is
     simply recorded at the handover. Smallest change; matches "pay at the
     door after inspecting" (D.12) and makes advance-payment scams harder.
  3. **Both:** option 2 now, option 1 when Protected checkout arrives.
- **Recommendation:** option 3. Option 2 removes the problem at its source
  for Release 1 at almost no cost; option 1 is needed anyway for Release 2.
- **Blocks:** nothing technical. A paid part that cannot go ahead waits for
  staff until this is decided.
- **Founder's approval required: yes** (how buyers may pay is a business
  rule).

### F-10 When commission fees start, and at what rates and caps

- **Today (D-086):** zero, by design (D.19: direct orders free in year one).
- **To decide:** whether direct orders ever carry a fee; the rates per
  category and the per-order caps (K.2 gives ranges marked [A]); when fees
  start (with Protected checkout, Release 2, per D.19); how sellers are
  invoiced for fees on direct orders, if any.
- **Engineering before the first non-zero rule:** apply the cap (it is
  stored but ignored today, so a capped rule would over-charge), a staff tool
  for versioned rules, and fee reversal on refund.
- **Blocks:** revenue, not launch.
- **Founder's approval required: yes.**

---
````

### F-01 to F-08, F-11 to F-20 and N-1, as they stand in `docs/DECISIONS.md` on `main` (lines 3242–3573)

````markdown
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
- **To decide:** the provider (AWS S3 or Cloudflare R2), the bucket's
  location (backups hold personal data: blueprint O.1), versioning or an
  object lock on the bucket (protects sets against a stolen backup key),
  and the spending. Also whether the blueprint's weekly copy to an
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
- **To decide:** the days and the minimum number of sets, with the legal
  retention of the personal data in them (the founder's own checks) and
  the storage cost.
- **Founder's approval required: yes.**
````

---

*Report produced read-only on 19 November 2026. Nothing was deployed, no
outside service other than GitHub was used, and no money was spent.*
