# MarkX — handoff

**Written:** 17 November 2026, during the sixth AI engineering session, and
kept current at each pushed milestone; Parts A.00 and A.0 were added by the
two back-end-only sessions that followed, Part A.000 by the ninth session
and Part A.0000 by the tenth (both the web app's owner), and Parts A.00000
to A.0000000 by the deployment, Telegram and backup sessions. Part
A.00000000 was added on 19 November 2026 by the documents-repair session,
Part A.000000000 the same day by the backup trust hardening session, and
Part A.0000000000 on 20 November 2026 by the checks and secret-scan
session (D-097), Part A.00000000000 the same day by the staff conflict
and phone digits session (D-098), Part A.000000000000 the same day by
the order life-cycle hardening session (D-099), Part A.0000000000000
the same day by the frontend resilience session (D-100), Part
A.00000000000000 on 21 November 2026 by the Telegram sign-in session
(D-101), Part A.000000000000000 the same day by the recycled-number
fix session (D-101 section 2a), and Part A.0000000000000000 the same day
by the session that reviewed and merged pull request #9 and finished
Telegram for orders (D-102), and Part A.00000000000000000 the same day by
the session that reviewed and merged pull request #10 and made the
deployment ready for a server (D-103), and Part A.000000000000000000 the
same day by the session that fixed the defect the independent review of
pull request #11 found (D-103 section 5).
**Who this is for:** the founder, and the next AI engineer (Opus Max).

- **Part A — the report for the founder.**
- **Part B — the brief for the next AI engineer**, ready to paste.
- **Part C — the project on one page.**

Nothing here is new work. It describes what is in the repository and what
the checks actually printed.

---

# Part A.000000000000000000 — Fix before merging pull request #11 (21 November 2026, D-103 section 5)

On pull request #11's own branch (`claude/pr10-review-server-readiness-y7novo`),
on top of `9d0c888`; nobody had pushed to it since (checked first).
**Not merged**: another independent review follows. **No migration.
Nothing deployed; no server, domain, account or paid resource.**

**What was wrong, in plain words.** After a failed update MarkX goes back
to the last working release by itself. For a rare kind of rollback, the
runbook tells the operator to switch on a setting that lets an older
release accept a newer database, and to switch it off later. Nothing made
sure it was switched off. Left on, the automatic return asked the old
release "do you accept this database?", the setting made it say yes to
anything, and MarkX started old code against a database it may not
understand, calling it "verified". That can lose data.

**What changed** (your rule: go back to an old release only when it truly
accepts the database):

- The automatic return now asks the old release **with that setting
  forced off**, whatever the settings file says. A database the old
  release does not know is refused, and the site stops safely instead.
- An update **refuses to start while the setting is on**, and says: remove
  the line, then run it again. Nothing is changed.
- A rollback by hand to a release older than the database now needs the
  setting **and** a word on the command line (`--accept-newer-schema`), so
  a setting left on can never decide a rollback by itself.
- In a safe stop, backups run as the release that changed the database,
  never as the older one.
- The rehearsal now ends with the setting off, and proves all of this,
  including the reviewer's exact case.

**What needs you:** nothing new. One thing left as it was, for you to know:
while an update's database change runs, the release already running keeps
serving for those moments (stopping the site for every update instead is
your choice, if you ever want it; D-103 section 5).

**For the next engineer:** `deploy.sh` can now be loaded by a test
(`source`), which stops before running a command;
`tests/deployment/test_deploy_newer_schema.py` drives its functions with a
stand-in for `docker`. Never let `MARKX_ALLOW_NEWER_SCHEMA` decide anything
automatic: check with `preflight_strict`.

---

# Part A.00000000000000000 — Pull request #10 merged; server readiness (21 November 2026, D-103)

**Part 1, the review.** Pull request #10 (Telegram for orders, D-102) was
reviewed read-only at `09136fa` (not changed, commented on or pushed to),
found to have **no problem that had to be fixed first**, and merged with a
normal merge commit pinned to `09136fa`: **`main` is `9b3658f`**, its files
exactly those of `09136fa`; the branch is kept; `main` passed CI #169 and
Browser journeys #45. Evidence and two non-blocking observations:
`docs/DEVELOPMENT_STATUS.md`, "Pull request #10 reviewed independently and
merged".

**Part 2, the work.** On `claude/pr10-review-server-readiness-y7novo`, from
`9b3658f`; one pull request into `main`, **not merged** (an independent
review follows). **No migration. No server exists: nothing deployed, no
domain, certificate authority, account or paid resource.** In plain words,
for the day a server exists:

- **The site's certificate** can be put in place with one command, which
  refuses a wrong one and keeps the site up while it switches. Renewal can
  run on its own twice a day, but is **switched off until you choose a
  domain** and how its certificate is made (F-17). Whatever happens to
  renewal, MarkX itself warns three weeks before the certificate would
  expire, urgently in the last week.
- **Going back to an earlier release** now works with any image name and
  takes the backup service back too.
- **A release that breaks after it changed the database** no longer leaves
  a half-working site: MarkX goes back to the last working release by
  itself when that release accepts the changed database, and otherwise
  stops the site safely, writes down what happened and prints what to do.
- **Containers** run exactly the image versions tested (by fingerprint),
  with limits on processor and processes as well as memory, under user ids
  fixed in the build.

**What needs you:** F-17 (the domain; then `MARKX_TLS_RENEWAL` and
`MARKX_ACME_EMAIL`), and confirm or change P-103-1 to P-103-3
(`docs/DECISIONS.md`, D-103): the warning time, the processor and process
limits (they depend on the server's size), and the renewal times.

**For the next engineer:** never edit `rehearse.sh` while it runs (bash
reads it as it goes); `cmd | grep -q` under `pipefail` fails when `grep`
stops reading first: capture, then search; nginx applies a reload a moment
later, so wait for the new certificate rather than read it once.

---

# Part A.0000000000000000 — Pull request #9 merged; Telegram for orders (21 November 2026, D-102)

**Part 1, the review.** Pull request #9 was reviewed read-only at
`7eabf93` (not changed, commented on or pushed to), found to have **no
problem that had to be fixed first**, and merged with a normal merge
commit pinned to `7eabf93`: **`main` is `fe4546f`**, its files exactly
those of `7eabf93`; the branch is kept. Evidence and the three non-blocking
observations (a database rule that accepts a connected but unremembered
account, a future conflict with erasing accounts, the Mini App after a
disconnect): `docs/DEVELOPMENT_STATUS.md`, "Pull request #9 reviewed
independently and merged".

**Part 2, the work.** On `claude/markx-telegram-pr9-completion-nneqom`,
from `fe4546f`; one pull request into `main`, **not merged** (an
independent review follows). **No migration. Nothing deployed; no bot,
token or account; nothing sent to Telegram; no SMS; no money.** In plain
words, once the founder's bot exists and is switched on:

- **A shop** gets each new order in Telegram with Accept and Decline
  buttons, and a reminder with the same buttons 10 minutes before it
  expires. `/orders` lists what waits for it; each order's buttons move it
  on: accepted, packed and ready, on its way. Declining offers three
  reasons. `/offers`, `/price`, `/stock` and `/checkin` keep listings
  fresh. Handover codes are entered only on the website.
- **A buyer** gets every order update in Telegram in their own words and
  language, with a button to the order.
- **Every Monday** the shop gets its figures in Telegram, with a button
  for "all my prices are still right".
- **Each press is checked again on the server** with the website's own
  seller check and the website's own order and offer functions, so the
  bot can never do what the website would refuse.

**What needs you:** confirm or change P-102-1 to P-102-9 and answer F-26
(`docs/DECISIONS.md`, D-102); when the bot exists, follow
`docs/runbooks/telegram-linking.md`, steps 5 and 9 (the webhook must
receive `callback_query`, or every button does nothing).

**Commits:** `2376b1e` (the bot, the buttons, buyer and weekly texts),
`dd262f9` (the next-best-offer text and the test that every order message
has its own words), then the documents.

**For the next engineer:** the bot is `apps/api/markx/telegram_bot/`
(`service.py` answers an update; `keyboards.py` builds buttons; `texts.py`
holds its words). `telegram_link.handle_update` sends button presses and
commands there, and answers a repeated update with `replay=True`. Any new
seller action in the bot must call `deps.seller_membership` and the same
service function as the website; never check a role by hand. A new order
message needs Telegram words in `notifications/texts.py`
(`TELEGRAM_TEXTS`), or `test_every_order_message_has_its_own_words_in_telegram`
fails.

---

# Part A.000000000000000 — Fix before merging pull request #9: a recycled number (21 November 2026, D-101 section 2a)

On the same branch, `claude/telegram-signin-audit-fixes-q318w6`, so the fix
is in pull request #9; nobody had pushed to it since `b89aeff`. **Not
merged**: another independent review follows. **Nothing deployed; no bot,
account or SMS; no money.** In plain words:

- **The defect.** After pressing "Disconnect Telegram", MarkX forgot which
  Telegram account an account had. If the phone company later gave that
  number to a stranger, the stranger could sign in with Telegram and land
  in the old owner's account, with their orders, addresses and shop.
- **The fix (the founder's rule P-101-6).** MarkX now always remembers
  which Telegram account an account belongs to, even after disconnecting;
  disconnecting only stops messages. Only that Telegram account can sign
  in again. Anyone else bringing the same number is refused and told to
  contact support. An account that never had Telegram (made by an
  invitation, by staff or by SMS) can still be claimed by its first
  Telegram sign-in, as before. The database itself refuses to forget or
  change it.
- **Other ways closed the same way:** Telegram connected by the bot's link
  or the Mini App and then disconnected; connecting a second Telegram
  account after disconnecting; one Telegram account reaching a second
  MarkX account; and a person who disconnected and changed number no
  longer gets a new, empty account.
- **Not covered, for the founder:** signing in by SMS (switched off) proves
  only the number; decide the same question for it before SMS returns.

**For the next engineer:** `users.bound_telegram_id` (migration `0021`) is
the account's Telegram account for good; `telegram_id` is only "messages
on". Lookups "which account does this Telegram account have" use
`bound_telegram_id`. The trigger `trg_users_keep_bound_telegram` refuses
any change once set, so F-24's support tool needs its own migration. Tests:
`tests/api/test_telegram_recycled_number.py`.

---

# Part A.00000000000000 — Sign-in with Telegram, SMS off, M2, M3, M4 (21 November 2026, D-101)

On branch `claude/telegram-signin-audit-fixes-q318w6`, from `main` at
`b79caab` (pull request #8, D-100, merged), with the complete history. One
pull request into `main`, **not merged**: this is security work and an
independent review follows; never merge without the founder's written
approval. **Nothing deployed; no bot, token, SMS provider or account; no
money spent.** In plain words:

- **Everyone signs in with Telegram (decision SI-1).** On the sign-in page
  a buyer or seller taps "Sign in with Telegram", then "Open Telegram". The
  Telegram app opens; they press Start, then the bot's "📱 Share my phone
  number" button, and go back to the page, which signs them in by itself.
  They type nothing; MarkX pays nothing. **Staff** do the same on the staff
  page, then give their password and authenticator code as before.
- **The phone number is confirmed by Telegram.** It must be an Ethiopian
  mobile number; one number is still one account. A new number on the same
  Telegram account becomes the account's number. A number already used
  with another Telegram account is refused and the person is told to
  contact support (numbers are recycled). These rules are PROVISIONAL.
- **SMS is switched off** by one setting, `MARKX_SMS_PROVIDER=off`. A real
  server can now start without an SMS provider and still refuses the fake
  one. The SMS code is kept for later. **While the bot does not exist,
  nobody can sign in on a real server**: the page says so.
- **The audit's three sign-in findings are fixed:** Telegram start-up data
  works once and for five minutes (M4); an outsider can no longer lock a
  staff member out or tell staff numbers from others (M3); no one number,
  address or network can use up the shared SMS budget (M2).
- **Saved tests** prove that two orders of one buyer at the same moment
  cannot pass the buying limits and that expired orders never count.
- **Proved in a real browser** (`e2e/telegram-sign-in.mjs`, in the
  journeys on GitHub): with SMS off, a new person signs in with Telegram
  (the journey plays Telegram) and places an order; a foreign number is
  refused in English and Amharic; the staff page asks for Telegram first.
- **Eight PROVISIONAL values and rules** (P-101-1 to P-101-8) and two new
  questions, **F-24** (who may move a number to another Telegram account;
  no staff tool exists yet) and **F-25** (whether to add a matching code),
  are in D-101.

**For the next engineer:**

- Telegram sign-in lives in `markx/accounts/telegram_sign_in.py`; the
  webhook in `telegram_link.py` hands it `/start si-<token>` and shared
  contacts. It is on exactly when Telegram linking is on (the same bot and
  secret). Lock order: users' rows (ascending id), then the Telegram
  account's advisory lock, then the number's.
- Tests play Telegram with `tests/telegram_play.py`; the `sms_off` fixture
  (in `tests/conftest.py`) switches SMS off for a test.
- The staff lock on the phone-and-password route lives in the rate-limit
  counters (`staff-login:fail:<staff id>:<address>`); the Telegram route's
  lock is still `staff_members.locked_until`.
- Before the bot goes live, re-read the Bot API documentation for the
  `contact` message and `reply_markup` in a webhook reply
  (`docs/runbooks/telegram-linking.md`, step 8); this session could not
  reach it.
- The CI journeys recreate the API with SMS `off` for the new step only;
  every other step keeps the fake SMS sender.

---

# Part A.0000000000000 — Frontend resilience (20 November 2026, D-100)

On branch `claude/frontend-resilience-errors-g4z33c`, from `main` at
`fae2514` (pull request #7, D-099, merged), with the complete history.
One pull request into `main`. The founder's task approved the merge in
advance on one condition: every check on the latest commit passes and the
pull request has not changed since; then a normal merge (not a squash),
pinned to that commit, keeping the branch. Whether it was merged, and the
new `main` commit, are in the session's report: they cannot be written
into the same pull request. **The website, its tests, one workflow step
and documents only; the API is unchanged. Nothing deployed; no account; no
money spent.** In plain words:

- **The website no longer freezes when the connection drops.** Every part
  of it that talks to the server (22 component files: add to cart, the
  cart, checkout, the buyer's order buttons, reviews, reports, sign-in and
  sign-out, the account, the shop's dashboard, every staff screen, photo
  and document uploads, the CSV export) now goes through one safe call. If
  the network drops, the request takes more than 30 seconds (uploads 120),
  or something other than MarkX answers (a proxy's error page, a crash),
  the person sees "No connection. Check your internet, then try again." or
  "MarkX could not answer just now. Please try again in a moment." (in
  Amharic on Amharic pages) with a **Try again** button, and every button
  and form is usable again. MarkX's own refusals ("too many open orders")
  are shown as before.
- **Trying again never places an order twice.** Checkout keeps the same
  order key when the person tries again, so the server returns the order
  it already took.
- **Proper error pages.** If a page cannot be built (for example the API
  is down), the person sees "This page could not be shown", in Amharic or
  English, with Try again and a way back (home, the seller area or the
  staff area), and never a technical detail. One for the whole site, one
  for each section.
- **Proved in a real browser** (`e2e/network-recovery.mjs`, now in the
  browser journeys on GitHub): add to cart offline, a fake proxy error,
  "Place order" offline, the answer lost after the server took the order,
  then Try again: exactly one order. Then the API is stopped: the error
  page in both languages; started again: Try again brings the page back.
  On the old website the same journey fails at the first step.
- **An automatic accessibility check (axe)** runs on every page of that
  journey and on the main public pages in both languages. It found two
  problems on every storefront page (the logo link's name, the search
  field's suggestion list); both are fixed.
- **New question F-23 (OPEN):** may a member of staff edit the text,
  variants, aliases or pictures of a product their own shop proposed?
  Today they can (checked in the code).

**For the next engineer:**

- Call the API from the browser only through `browserApi`, `sendForm` or
  `getSafely` (`src/lib/api/browser.ts`); they never throw. Show a failure
  with `ProblemNotice` (`src/components/Resilience.tsx`): pass the error
  code, the component's own words and either the call to repeat or
  `"submit"` inside a form.
- The error pages' words are in both message files and, for
  `global-error.tsx` only, copied in `src/lib/fallback-text.ts`; a unit
  test fails if the copy differs. Change the message files first.
- `e2e/a11y.mjs` (`checkAccessibility(page, label)`) can be called from any
  journey; the other journeys do not call it yet.
- `e2e/network-recovery.mjs` needs `MARKX_E2E_STOP_API` and
  `MARKX_E2E_START_API` (commands that stop and start the API); the
  workflow sets them to Docker Compose commands.
- For later (D-100): the 404 page's missing `lang` (needs an experimental
  Next.js setting); a PWA for offline page moves; measuring the time limits
  on real networks; native review of the new Amharic.

---

# Part A.000000000000 — Order life-cycle hardening (20 November 2026, D-099)

On branch `claude/order-lifecycle-hardening-1djdof`, from `main` at
`c70b338` (pull request #6, D-098, merged), with the complete history.
One pull request into `main`, **not merged**: the founder says "merge
approved" first. Product code, one migration, tests and documents.
**Nothing deployed; no account; no money spent; no commission rule
created.** In plain words:

- **Deliveries that nobody finishes no longer wait for ever (M6).** An
  order out for delivery for more than two days (never before its promised
  delivery time), or waiting three days after a failed delivery with no
  retry and no return, is now reported to staff by its order code. It stops
  taking one of the buyer's three open-order places. It keeps its stock:
  the system never ends it and never puts its goods back on sale, because
  nobody knows where the goods are. The shop still finishes or returns it.
- **A rival can no longer hold a shop's whole stock with one account
  (H2).** Before the shop answers, one buyer's orders can hold at most 5 of
  one item and 10 items of one shop. A buyer who cancels 3 orders in a day
  waits until the first of those is a day old before ordering again. Other
  buyers are never limited by one buyer's orders.
- **The commission cap now works.** A capped rule can no longer charge
  more than its cap. Commission stays at zero; no rule was created.
- **A test proves sign-in limits hold in any digits** (from the pull
  request #6 review).
- **Seven PROVISIONAL values** (P-099-1 to P-099-7, listed in D-099) and a
  new question, F-22: should staff get a button to close a stalled
  delivery or release its stock?
- **Next task: waiting for the founder's choice.**

**For the next engineer:**

- A fee is calculated only in `markx/payments/fees.py`
  (`seller_order_fee`); order lines carry `commission_rule_id` and
  `commission_cap_santim` copied at placement (`commission_rate`, which
  replaced `commission_bps`).
- "Stalled" is defined once, in `markx/orders/stalled.py`; the buyer's
  open-order count and the watch check `stalled_deliveries` both use it.
  Status events are append-only: tests move the clock forward (`now=`),
  never the events back.
- `place_order` refuses `unconfirmed_offer_limit`, `unconfirmed_store_limit`
  and `cancellation_cooldown` under the buyer's cart lock. A new refusal
  code needs words in `apps/web/messages/en.json` and `am.json`, or the web
  shows the generic message.
- The browser journeys all use the demo buyer 0911000950 and cancel
  leftover orders first. On a fresh database they cancel nothing; on a
  laptop database reused across many failed runs, the cool-down can refuse
  their checkout. Reseed, or raise `orders.cancellations_before_cooldown`
  on that laptop.
- Never run two pytest runs at once: this session did, by mistake, and the
  second dropped `markx_test` under the first.

**Tests:** see "Tests executed", 20 November 2026 (D-099), in
`docs/DEVELOPMENT_STATUS.md`.

---

# Part A.00000000000 — Staff conflict of interest, phone digits (20 November 2026, D-098)

On branch `claude/staff-conflict-phone-fixes-qkiixq`, from `main` at
`d01fef7` (pull request #5 merged), with one pull request into `main`,
pull request #6, **merged on 20 November 2026 as `c70b338`**. Product
code, tests and documents. **Nothing deployed; no account; no money
spent.** In plain words:

- **Staff can no longer judge their own case (H1).** A member of staff who
  works in a shop cannot take staff decisions about that shop: its
  problems with orders, its reviews, its listings and photos, reports
  about it, sending its orders out, new handover codes, its product
  proposals, and (as before) its verification. A member of staff who
  bought something cannot handle their own order, and nobody moderates
  their own review or closes their own report. They are told another
  staff member must handle it, and the attempt is written in the audit
  log. 19 staff actions are covered (D-098 lists them).
- **There is no override (PROVISIONAL).** If no other staff member can
  act, the case waits. Your question F-21: is that acceptable, or should
  someone be able to unblock it?
- **Also PROVISIONAL:** whoever filed a report cannot close it.
- **Phone numbers typed with other digits now work (B-3).** Some phone
  keyboards type Arabic or "wide" digits. They used to cause a server
  error; they are now read as the normal digits, everywhere a phone number
  is entered. Ethiopic numerals (፩ ፪ ፫), which have no zero and are not
  used for phone numbers, get the normal "Enter an Ethiopian mobile
  number" message.
- **The documents no longer say pull request #5 (or #4) is not merged.**
- **Next task: waiting for the founder's choice.**

**For the next engineer:**

- A new staff action that decides or changes something about a store, an
  order, an offer, a review or a report must call
  `markx.trust.conflict.refuse_conflict` as soon as it has found the thing,
  and needs a test in `tests/api/test_staff_conflict.py` (insider refused
  and recorded, outsider allowed).
- Every phone number goes through `markx.core.phone.normalize_phone`;
  never match a phone with `\d` (it matches every script's digits).
- The refusal's audit row is written in its own transaction on purpose:
  the request rolls back, the record must not.

---

# Part A.0000000000 — Checks once per change, secret scan (20 November 2026, D-097)

On branch `claude/markx-checks-secret-scan-ik3o3z`, from `main` at
`773bbb6` (pull request #4 merged), with one pull request into `main`,
**pull request #5, merged on 20 November 2026 as `d01fef7`** at the
founder's written approval (CI 153 and Browser journeys 29 passed on
`45f4f35`; CI 154 and Browser journeys 30 passed on `main` at `d01fef7`). CI settings,
`.gitleaks.toml`, `.gitignore` and documents only. **No product code
changed; nothing deployed; no account; no money spent.** In plain words:

- **No secret was ever committed.** The whole history, every branch and
  pull request, was scanned with two tools. They found only values labelled
  as development or test values, and two made-up test web addresses.
- **Each change now starts one CI run, not two.** CI runs on pull
  requests, on main, and by hand. A newer push to a pull request cancels
  its older run; main's runs are never cancelled.
- **A change to documents only** skips the long jobs (tests, images,
  production rehearsal) but still runs the secret scan, and the pull
  request still shows one passing "CI result". Any code change runs every
  job, production rehearsal included.
- **Browser journeys** run on every pull request that changes code (one
  run per push; a newer push cancels the older run), when code reaches
  main, and by hand on any branch. (The first version ran them only on
  main; you reversed that before merging, so a change to the screens is
  always tested before it can be merged.)
- **The secret scan's exceptions are narrower (W-1)** and `.gitignore`
  ignores key and certificate files.
- **Next task: waiting for the founder's choice.**

**GitHub results (pull request #5, commit `ec64a85`).** The branch push
alone started no run. Opening the pull request started **one** CI run,
**CI 151 (event `pull_request`): passed**, all seven jobs: What changed
(it listed `.github/workflows/*`, `.gitignore`, `.gitleaks.toml` as code,
so every job ran), Security, API (tests, both recovery drills), Web app,
Containers, Production stack rehearsal, CI result. **Browser journeys 28**,
started by hand on the branch: **passed** (page weight and every journey).
Before D-097 the same kind of change started two CI runs (pull request #4:
144 and 145). The commit that recorded these results (`65d1669`) started
CI 152, again one run, which passed all seven jobs. The last commit
(`45f4f35`) makes the journeys start on pull requests again: CI 153 and
Browser journeys 29 passed on it. (Added on 20 November 2026 by D-098:)
the pull request was merged as `d01fef7`, and CI 154 and Browser journeys
30 passed on `main` there.

**For the next engineer:**

- A push to a branch with no pull request runs no CI. Open the pull
  request, or start CI by hand (Actions, CI, Run workflow).
- Browser journeys start by themselves on a pull request that changes
  `apps/`, `infra/` or `journeys.yml`; a documents-only pull request does
  not start them (and so shows no journeys check at all).
- If a check ever starts reading a document's text, add that file to
  `read_by_checks` in `ci.yml`'s "What changed" step, or a documents-only
  change to it will skip the tests.
- The allow-list in `.gitleaks.toml` is tested against the secret value
  only: a new labelled test value must carry `dev-only`, `test-only` or
  `not-a-real-secret` in the value itself.

---

# Part A.000000000 — Backup trust hardening (19 November 2026, D-096)

On branch `claude/markx-backup-trust-hardening-4mmhxz`, from `main` at
`c4a1843`, with one pull request into `main`, **pull request #4, merged
on 20 November 2026 as `773bbb6`**. Built and tested with PostgreSQL 17.12
and MinIO only; **no money spent, no account created, nothing deployed, no
real storage used.** In plain words, for the founder:

- **The server can no longer delete a backup (BK-1).** Its backup key may
  only add, read and list. Deleting old backups ("retention") is now a
  separate job run away from the server with its own key. On staging and
  production the backup bucket must have an "object lock" (nobody can
  delete a backup before its time, not even with the account's keys), or
  the backup service will not start. This costs storage, so it is
  **PROVISIONAL** until you confirm it with F-16.
- **A damaged upload is never reused (BK-3).** The backup now remembers
  each file it uploaded and checked, and reuses one only when the storage
  still shows exactly that file; anything else is uploaded again.
- **Drills and restores never happen on the server (BK-2).** The recovery
  key stays off the server: the drill and any restore run on a separate,
  throwaway machine (your laptop, or a free CI runner) with a key that can
  only read the backups. CI now does this on every push.
- **A forged backup cannot harm the recovery machine (BK-6)**, and **a
  restore can never change the live database's passwords (BK-7).**
- **The tests use limited keys (BK-17)**, as the real server will.
- **What you need to decide:** the six PROVISIONAL items in D-096 (object
  lock required, its mode, 30 days minimum, 44 days recommended, retention
  run by hand monthly at the drill, the recovery machine being the
  key-holder's laptop), together with F-16, F-19 and F-20.
- **Still open:** BK-4 (alerts that survive losing the server), BK-5 (a
  safe copy of the application's secrets), moving backup signing off the
  server, the other lower findings; and every test against the real
  provider, Cloudflare R2's lock above all (UNKNOWN today).
- **Checks:** 1789 tests passed locally; on GitHub, pull request #4's CI
  runs 144 and 145 and Browser journeys run 26 passed on `adf128a`. The
  report: `docs/reports/2026-11-19-backup-trust-hardening.md`.
- Details, tests and proof: `docs/DEVELOPMENT_STATUS.md`, "Backup trust
  hardening"; decision D-096 in `docs/DECISIONS.md`; procedures in
  `docs/runbooks/backup-and-restore.md`.
- **Next task: waiting for the founder's choice.**

**For the next engineer** (traps paid for in this session):

- The backup tests need the least-privilege MinIO users: run
  `MC="docker exec -i markx-minio mc" infra/backup/minio-least-privilege.sh`
  once, or set `MARKX_TEST_MINIO_MC` to that command. MinIO matches a policy
  wildcard only at the END of a bucket name: the tests' file buckets are
  `markx-test-files-*` for that reason.
- A restore runs `pg_restore` as `markx_migrator`. bootstrap.sh's default
  privileges must be cleared in the new database first
  (`prepare_for_owner_restore`), or every restored table gets wider grants
  than its source.
- MinIO keeps an object-lock date to the millisecond: lengthen to a whole
  second, rounded up. A bucket made in a test with a COMPLIANCE lock cannot
  be removed until the lock ends; that is expected.
- `S3Destination.put_file` now returns the stored object (its ETag and lock
  date); a test double must return it too.

---

# Part A.00000000 — Documents repaired, audit saved (19 November 2026, D-095)

Documents only: no code, test, migration, setting or workflow changed;
nothing was deployed; no outside service but GitHub was used. In plain
words, for the founder:

- **Where things stand.** All the sessions' work was merged into `main` on
  19 November 2026 through pull request #1 (merge commit `10a72b1`). CI run
  133 and Browser journeys run 22 passed on that commit. Each session now
  starts from the latest `main` on its own new branch, and nothing is merged
  into `main` without your written approval (`AGENTS.md` section 4, D-095).
- **The history is complete.** `main` holds all 125 commits (the 123 of
  pull request #1, the initial commit and the merge commit). Nothing was
  squashed: the state report's "51 commits" and "`daaee71` has no parent"
  are what a shortened (50-commit) download shows. Old commit numbers in
  these documents, such as `7c492c6`, `eab7c21` and `497fcf5`, are all in
  `main`'s history. Details and proof: `docs/DEVELOPMENT_STATUS.md`, "State
  on 19 November 2026".
- **Two reports are now in the repository:** the read-only state report
  (`docs/reports/2026-11-19-markx-readonly-audit-report.md`, copied
  unchanged) and the 22-section independent audit
  (`docs/reports/2026-11-19-independent-audit.md`, recovered word for word
  from the audit session's record).
- **The documents were corrected** where they disagreed with the code (the
  state report's section 2); the eight confirmed defects (a to h) and the
  audit's other findings are listed as known problems in
  `docs/DEVELOPMENT_STATUS.md`. None of them is fixed: each needs a code
  change.
- **Your four decisions of 19 November 2026** are recorded as D-095 in
  `docs/DECISIONS.md`.
- **Next task: waiting for the founder's choice.**

---

# Part A.0000000 — Off-server backup and disaster recovery (18 November 2026, D-094)

Recorded in `docs/DEVELOPMENT_STATUS.md` (with every command and result)
and `docs/DECISIONS.md` (D-094, and the founder items F-14, F-16, F-19,
F-20). In plain words, for the founder:

- **What was wrong** (all six audit findings checked in the code and true):
  the nightly dump stayed on the same server; its encryption could not tell
  a changed file from a good one; its key sat beside the database
  passwords; the uploaded documents and pictures were not backed up at
  all; a failed backup told nobody; and no test proved that the database
  and the files could be recovered together.
- **What exists now:** each night the backup service takes one *set*: the
  database and every stored file from the same moment, locked so two never
  run at once. Everything is encrypted before it leaves the container, with
  a key pair: the server holds only the half that locks, **you hold the
  half that unlocks** (the recovery key). A stolen or lost server reveals
  no backup and is not needed for a restore. Every piece is uploaded,
  read back and checked, then a signed list says what the set holds; a
  restore refuses anything changed, missing, cut short, unsigned or locked
  to another key, and only ever writes into a new database and empty
  storage. A drill does the whole recovery automatically, and on every code
  change in CI, with seven deliberate faults that must each be refused.
  Failed, incomplete or stale backups and failed drills raise alerts.
- **What does NOT exist:** a real backup bucket. **MarkX has no off-server
  backup today.** Nothing was connected to AWS, Cloudflare or anything
  else; no account, bucket or real key was made; nothing cost money.
  Alerts are generated, but nobody receives them until your Telegram alert
  group exists (F-18).
- **Your decisions** (`docs/DECISIONS.md`): **F-16** which provider and
  where the backup bucket lives, and whether it gets versioning or an
  object lock; **F-19** who keeps the recovery key and where (two places;
  losing every copy loses every backup, for ever); **F-20** how many days
  and how many sets are kept (the blueprint says 30 days; not chosen for
  you); **F-14** whether the live buckets also get versioning; **F-18** the
  alert group. Then the activation steps in
  `docs/runbooks/backup-and-restore.md` ("Activating off-server backups")
  take about an hour with an engineer.

---

# Part A.000000 — Connecting Telegram (18 November 2026, D-093)

Recorded, like the sessions before it, in `docs/DEVELOPMENT_STATUS.md` and
`docs/DECISIONS.md` (D-093). In short: a signed-in person can connect their
own Telegram account from the account page with a one-time link that the
MarkX bot confirms through a secret-checked webhook, see the state in
Amharic or English, and disconnect at any time. **It is switched off by
default; no bot exists, no webhook is registered, nothing was sent to or
received from Telegram, and no notification was enabled.** Seller
notifications remain a launch blocker. Switching it on is a future task
that needs the founder's approval: `docs/runbooks/telegram-linking.md`.

---

# Part A.00000 — The production deployment foundation (18 November 2026, D-091)

Later sessions (D-084 to D-090) recorded their reports in
`docs/DEVELOPMENT_STATUS.md` and `docs/DECISIONS.md` rather than here; so
does this one. In short: MarkX now has production images for the API and
the web app, a production Compose file with an nginx reverse proxy, a
backup service and a one-time migration step (`infra/production/`),
liveness and readiness probes, a preflight command, `deploy.sh` with
deploy and rollback, a local rehearsal of the whole stack that CI runs, and
runbooks (`docs/DEPLOYMENT.md`, `docs/runbooks/`). **Nothing was deployed and
no account, server, domain or certificate was created.** MarkX is not
production-ready: it cannot start on a real server until the founder
decides F-01, F-11 and F-15, and it has no off-server backups (F-16) and no
backups of stored files (F-14). Next task: waiting for the founder's
choice.

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
out. Final checks: 948 API tests; 33 web unit tests; the buyer, staff,
admin, seller-dashboard and setup-and-account journeys passed in Chromium
with no console errors; GitHub Actions run #63 passed. One open question
was left: a single worker pass in one admin journey run seemed to handle
none of the outbox messages that were due. Solved later (D-082, below).

**Third round** (the founder: "do it now from the list you can do with
accuracy; if not, skip and summarise"). Done: a store's page shows its
track record over 90 days (how many orders it accepts, how fast, how many
deliveries succeed) and search can filter by product rating and seller
level (`3511e0e`, D-080); a single worker pass (`--once`) now exits with an
error when a job failed or the outbox could not be drained (`c6b7a29`,
D-079); and the six
browser journeys run on GitHub's free runners against a fresh demo database
when a commit message contains `[journeys]` (D-081). Their first run was
cancelled by my own next push; fixed (`b4bff76`), run #4 passed all six
with no console errors, and two journeys that printed console errors
without failing now fail (`876c1d9`). Skipped, with the reason: Telegram
sign-in and the Mini App (they need your bot); a rating on the product
card (blueprint D.9's card does not have one); delivery speed as a filter
and "total cost to the door" as a sort (search does not know the buyer's
delivery zone yet: back-end work first); a native speaker's review of the
Amharic (needs a person). Final checks: 951 API tests, 33 web unit tests,
the web build (66 pages), every lint and type check clean; on GitHub, the
six journeys (run #5) and CI run #81 passed on `876c1d9`.

**Fourth round** (the founder: "one unexplained glitch: fix it"). It was
not a glitch in the database: the worker pass handled exactly 100 messages
(one batch), the oldest, and stopped; the 68 newer ones it left were the
only ones the first look counted. `--once` now handles every due message,
and a pass also sends what its own scheduled jobs queued (D-082). Two new
tests fail on the old code and pass now; 953 API tests pass; the admin
journey, given a backlog of 196 messages, passed with one worker pass that
handled 225 and left none.

**Fifth round** (the founder: "for F-01 to F-08 fill with your intelligence
guess, but comment that it must change for real live"). Each now has a
PROVISIONAL answer, the recommendation already written under it (D-083).
**Every one must be confirmed or changed by the founder before MarkX goes
live**; each is marked `PROVISIONAL (F-0n, D-083)` in the code where it
lives, and a test fails if a marker disappears. Only F-08 needed new code:
a daily job deletes search logs older than 180 days and rate-limit counters
a day after their window, the periods are two settings staff can change
(described as provisional on the settings screen in both languages), and
each deletion is counted in the audit log. F-01 (a private Cloudflare R2
bucket for identity documents) is recorded but not created: that is a paid
account holding Ethiopian personal data, which only the founder can open,
and a real environment still refuses to store a document until it exists.
F-02 and F-06 apply to features not built yet (transfer, merging products
with offers); F-03, F-04, F-05 and F-07 keep what the code already does.

**Still to build on the web:** Telegram sign-in and the Mini App once the
founder creates the bot; delivery speed as a search filter and "total cost
to the door" as a sort (they need the buyer's delivery zone in search).
The Amharic text of this session is AI-drafted and needs a native speaker.

**Waiting on the founder:** to confirm or change the PROVISIONAL answers
to F-01 to F-08 (D-083) before going live; F-01 also needs the founder to
create the private document store.

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
| `main` | `617a276`, the initial commit. **Untouched.** (Correction, 19 November 2026: since then, pull request #1 was merged; `main` is now `10a72b1`.) |
| Other branches | `claude/markx-engineering-p10-daa24c`, `claude/markx-seller-management-oag1a4`, `claude/markx-third-session-cq58yj`: kept, not touched. (Correction, 19 November 2026: `claude/markx-engineering-p10-daa24c` is no longer on GitHub; who removed it and when is UNKNOWN.) |
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
- F-01 to F-08 in `docs/DECISIONS.md` now have PROVISIONAL answers
  (D-083), to be confirmed or changed before going live; F-01 still blocks
  the launch until the founder creates the private document store.

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

**1. Repository and branch.** `shumetmamo21-cyber/markx-marketplace`.
Start from the latest **`main`** and work on your own new branch (`AGENTS.md`
section 4; `claude/project-scaffold` was merged into `main` on 19 November
2026 and is no longer worked on). Never merge into `main` without the
founder's written approval, and never delete a branch. Verify the head:
`git fetch origin main && git log -5 FETCH_HEAD`.

**2. Read first:** `AGENTS.md`, `MARKX_MASTER_BLUEPRINT.md` (sections I and
F.1 for the screens; C.3 and C.4 for who may do what), this file,
`docs/DEVELOPMENT_STATUS.md` (start with "State on 19 November 2026"), `docs/DECISIONS.md`
(D-001 to D-083; D-043, D-050, D-053, D-076 and parts of D-062 to D-067 are
provisional; F-01 to F-08 have PROVISIONAL answers in D-083 that the founder
must confirm before going live), `docs/ARCHITECTURE.md`, `docs/SETUP.md`, and `apps/web/AGENTS.md`.
Next.js 16 differs from your training: read
`apps/web/node_modules/next/dist/docs/` before using a feature.

**3. Reproduce every check before changing anything.** PostgreSQL 17 in
Docker (start `dockerd` yourself on a bare Linux machine), then from the
repository root `PGHOST=127.0.0.1 PGUSER=postgres
PGPASSWORD=postgres_dev_only infra/postgres/bootstrap.sh markx`. Then:

```bash
cd apps/api && uv sync
uv run pytest                  # expect 966 passed, ten to fourteen minutes
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
in once per run; the API allows five codes per phone per clock hour. The
same journeys run on GitHub, against a fresh demo database, on every push
that changes `apps/` or `infra/` (D-084; the `[journeys]` commit tag of
D-081 is no longer needed); that job raises the limit on its throwaway
database.

**5. Task.** Next task: waiting for the founder's choice. The open work is
listed in `docs/DEVELOPMENT_STATUS.md` ("Open work for the founder to choose
from"); do only what the founder chose. **When the founder's choice is web
work (the web app's owner):** first pick up any API additions made
since the tenth session: `cd apps/api && uv run python -m
scripts.export_openapi ../web/src/lib/api/openapi.json`, then `cd ../web &&
npm run gen:api` (D-061; it was current at the tenth session's last commit).
Then the work the founder chose.
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

**5b. A back-end-only session:** next task: waiting for the founder's
choice; do only the back-end work the founder chose. Do not modify `apps/web`; add routes and schemas only, never
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

**Note, 19 November 2026:** this page was written on 17 November 2026 and
its numbers are from then. Today the schema has 75 tables and migrations
run from `0001` to `0018`; for the current state see
`docs/DEVELOPMENT_STATUS.md`, "State on 19 November 2026".

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
