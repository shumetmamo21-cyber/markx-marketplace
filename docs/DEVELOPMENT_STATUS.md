# Development status

**Last updated:** 21 November 2026, by the **three small fixes session**
(D-104) on branch `claude/markx-pr11-review-fixes-3uf2ts`, from `main` at
`7093e6c` with the complete history. That session first reviewed the fix
on pull request #11 independently and merged it (below; merge commit
`7093e6c`). Before it, pull request #10 (D-102) was merged as `9b3658f`;
pull request #9 (D-101) as `fe4546f`; the frontend resilience session
(D-100, pull request #8) as `b79caab`; the order life-cycle hardening
session (D-099, pull request #7) as `fae2514`; the staff conflict and
phone digits session (D-098, pull request #6) as `c70b338`; the checks and
secret-scan session (D-097, pull request #5) as `d01fef7`, and the backup
trust hardening session (D-096, pull request #4) as `773bbb6`.

## Three small fixes: product names in the seller bot, the review confirmation, the remembered Telegram account (21 November 2026, D-104)

One pull request into `main` (PR_LINE). **One migration (0022). Nothing
deployed; no server, domain, account, bot, SMS or paid resource.** Details
and two PROVISIONAL values (P-104-1, P-104-2): `docs/DECISIONS.md`, D-104.

| Fix | What changed | Proof |
| --- | --- | --- |
| F-26 (decided by the founder) | The seller's Telegram messages about an order (new-order alert, reminder, every other order message), the `/orders` inbox and an order's card name the products: names only, never a buyer detail, price or quantity; English or Amharic; each name at most 40 characters, at most 3 then "and N more" | 7 new tests, all fail on the old code |
| "Your review is saved" failing now and then | A website bug: the refresh after saving removed the rated item's form, and the message with it, about 75 ms after it appeared. The message now sits outside the items (`ReviewNotices`) and stays | The journey now requires the message to still be there after the refresh: 3 of 3 runs fail on the old site; **20 of 20 runs in a row pass** on the fixed site |
| A connected account with no remembered Telegram account | The database rule now says it in full (migration 0022); it let that state through because comparing with an empty value is not "false" in SQL | 3 new tests; the 2 that try the forbidden state fail on the old rule |

**Test results:** see "Tests executed", 21 November 2026 (D-104).

## Pull request #11 reviewed independently and merged (21 November 2026)

The fix on pull request #11 (commits `46ca31a`, `704d15e`, `6ae83b7` after
`9d0c888`) was reviewed read-only by this session, which wrote none of it.
**Verdict: no problem that had to be fixed first; merged** with a normal
merge pinned to `6ae83b7` (merge commit `7093e6c`); its branch is kept.

- The commits change only what the fix needs: `deploy.sh`, the preflight's
  new `--deploying` refusal, a comment in `config.py` and `api.env.example`,
  the rehearsal, the new tests and documents. No CI workflow changed.
- The automatic return checks the old release with
  `MARKX_ALLOW_NEWER_SCHEMA` forced off (`run -e ...=false`, which wins over
  `env_file` and Compose `environment`; pydantic reads the environment
  before `.env`), refuses a database it does not know ("schema: ahead"),
  requires the started release to report "current", and otherwise stops
  the API, worker and web app.
- `deploy` refuses while the setting is on (before any Docker call); the
  new release refuses it too, wherever it is set; a rollback by hand to a
  release older than the database needs the setting and
  `--accept-newer-schema`; in a safe stop the backup service, and
  `deploy.sh backup`, run as the release that migrated the database.
- The rehearsal ends with the setting off and runs the reviewer's case.
- One existing rehearsal check was changed: the compatible rollback now
  also passes `--accept-newer-schema`, which the new rule requires; a new
  check proves the setting alone is refused. Not weakened. No test or
  safety check was removed.
- Tests: 18 of the 20 new tests fail on `9d0c888`. With only the "may be
  sourced" line added to the old `deploy.sh`, the reviewer's case fails
  because old `recover` printed "old is running again, verified": the
  defect. The deploy-refusal tests fail on the old code because the
  refusal does not exist (the old script stops later, at its server
  check).
- Full API suite at `6ae83b7`, locally: **2061 passed, 0 skipped**.
  GitHub on `6ae83b7`: **CI #174** success (all 8 checks; production
  rehearsal **124 passed, 0 failed**, including the 7 "setting left on"
  checks) and **Browser journeys #50** success, first attempt.
- Main after the merge (`7093e6c`): **CI #175** success (all its jobs) and
  **Browser journeys #51** success, first attempt.

## Fix before merging pull request #11: an older release started against a database it does not accept (21 November 2026, D-103 section 5)

On the pull request's own branch, `claude/pr10-review-server-readiness-y7novo`,
on top of `9d0c888` (nobody had pushed since; checked first). **Not
merged**: another independent review follows. **No migration. Nothing
deployed; no server, domain, account or paid resource.**

**The defect** (independent review): after a failed update, MarkX could go
back to the old release even when that release does not truly accept the
database. The compatible rollback tells the operator to switch on
`MARKX_ALLOW_NEWER_SCHEMA`; nothing made sure it was switched off, and the
rehearsal itself ended with it on. Left on, the automatic return asked the
old release whether it accepted the database, the setting made it say yes
to any newer database, and `deploy.sh` started old code against an
unchecked change and reported it as "verified".

**The rule applied** (the founder's: go back to an older release only when
it truly accepts the database), in `infra/production/deploy.sh` and
`markx/ops/preflight.py`:

| | Fixed by | Proof |
| --- | --- | --- |
| The automatic return | checks the old release with the setting **forced off** (`run -e MARKX_ALLOW_NEWER_SCHEMA=false`, works with every release); the started release must report the schema `current` | the reviewer's case, in the tests and the rehearsal |
| An update while the setting is on | `deploy` refuses before it changes anything, saying what to do; the new release's preflight refuses it too (`--deploying`), wherever it is set | tests; rehearsal |
| Other way: a rollback by hand with the setting left on | the setting alone is no longer enough: `rollback RELEASE --accept-newer-schema` as well | tests; rehearsal |
| Other way: the backup service in a safe stop | runs as the release that migrated the database, never the older one | tests; rehearsal |
| Other way: `deploy.sh backup` after a safe stop | uses the release that migrated the database | tests |
| The rehearsal's end | the setting is off (not in `api.env`, not in the running API or worker), after a roll forward | rehearsal |

Not changed (D-103 section 5, point 4): the running release keeps serving
while a deployment's migration runs; closing that window means downtime on
every deploy, the founder's decision. **Test results:** see "Tests
executed", 21 November 2026 (fix before merging pull request #11).

## Server readiness: certificates, rollback, failed deployments, containers (21 November 2026, D-103)

Infrastructure, one operations check, tests and documents. **No migration.
No server exists: nothing deployed, no domain, certificate authority,
account or paid resource used.** Each fix is proven in the production
rehearsal (GitHub's machines and locally) and the alert by tests. Answers
the independent audit of 19 November 2026, section 13. Details, three
PROVISIONAL values (P-103-1 to P-103-3) and the settings left for the
founder: `docs/DECISIONS.md`, D-103.

| Audit defect | State | Proof |
| --- | --- | --- |
| **1** Certificate renewal missing; certificates expire silently | **Fixed.** `deploy.sh certificate install` (checked, atomic, proxy reload without restart, put back if refused), `issue`/`renew` with certbot, a systemd timer twice a day; **renewal off** (`MARKX_TLS_RENEWAL=none`) until the founder has a domain (F-17). The worker's watch alerts 21 days before expiry, critical in the last 7, whatever renews it | rehearsal "the certificate" (15 checks); `tests/api/test_tls_certificate_watch.py` (7) |
| **2** Rollback hard-codes `markx/`; does not roll back the backup service | **Fixed.** `MARKX_IMAGE_PREFIX` everywhere; all three images required; the backup service rolled back too | the whole rehearsal runs with a prefix; rehearsal "rollback" (3) |
| **3** A failed check after the migration leaves the site half-up | **Fixed.** Back on the last working release automatically when it accepts the migrated database; otherwise a safe stop (API, worker, web app stopped; recorded in `deploy-halted`; instructions printed) | rehearsal "a failed update" (10): a broken release, and a broken release with a newer migration |
| **4** Tags not digests; memory-only limits; uid 999 assumed | **Fixed.** Every outside image by digest (`infra/check-image-pins.sh` in CI); CPU and process limits on every service; uid/gid 999 and 1000 set and checked in the Dockerfiles | rehearsal "containers" (16); CI "Containers" job |

**Not done (unchanged from the audit):** a real server and certificate;
single-copy services (a deploy drops requests for seconds); log shipping; a
maintenance page during a safe stop (the proxy answers 502 or 504).

## Pull request #10 reviewed independently and merged (21 November 2026)

Reviewed read-only at `09136fa` (nothing changed, commented or pushed on
its branch). **No problem that had to be fixed first.** Merged with a
normal merge commit, pinned to `09136fa`: **`main` is `9b3658f`**, with
exactly the files of `09136fa`; the branch is kept. `main` then passed CI
#169 and Browser journeys #45.

- Every press and command goes through `deps.seller_membership` (the one
  check `require_seller` also uses) and the same service functions as the
  website's routes (`seller_respond`, `mark_ready`, `seller_dispatch`,
  `update_offer`, `set_stock`, `confirm_offers`), which lock the row and
  check the role, the store's own order, the state and the deadline again.
  The website's routes add nothing but the staff-session refusal, which a
  Telegram account cannot have. The sender must be the account's
  *connected* `telegram_id` (not the remembered one) of an active account,
  in a private chat with a person; a group, a bot or a forged chat is
  ignored.
- Updates are proved to come from Telegram by the secret header (D-093,
  unchanged, constant-time). A button carries only a verb and a seller
  order id; changing it to another store's order gets "That order was not
  found." A repeated update id changes nothing and is answered with the
  current state.
- The tracking link is the existing one: a 256-bit signature over the
  order and its expiry, 60 days; its page leaves out the handover code, the
  recipient's name, phones and pin, and every action. No Telegram text
  carries a handover code or a personal detail: the texts accept only an
  order code, a date and whole numbers (tested).
- Every new text exists in English and Amharic (tested; a native review
  is UNKNOWN).
- The 24 new tests fail on `fe4546f` for the right reason (with stand-ins
  for the new modules: the old webhook ignores presses and commands, and
  the Telegram words do not exist). No existing test, check or workflow
  was changed (the pull request adds one test file and no other file
  under `tests`, `.github`, `infra` or `e2e`).
- Locally on `09136fa`: **2034 passed, 0 skipped** (PostgreSQL 17.12 and
  MinIO, both required); web 146 passed, lint, types and build passed;
  ruff, mypy, `alembic check` and both API description checks passed. On
  GitHub: CI #168 (all 8 checks) and Browser journeys #44 passed. **Journeys
  #44 passed on its second attempt:** the first timed out in
  "Reviews, reports, pictures and problem evidence" waiting for "Your review
  is saved", the same flake recorded on 18 November ("Lessons"); the pull
  request changes nothing on that page.
- Observations, not blockers: a weekly message queued before this release
  would lack the two new figures and be refused as unsafe (no server
  exists, so none is queued); a pressed button may show a loading mark
  without `answerCallbackQuery` (UNKNOWN, stated in D-102).

## Telegram for orders: alerts with buttons, the seller bot, buyer updates, the weekly message (21 November 2026, D-102)

Product code, tests, the runbook and documents. **No migration. Nothing
deployed; no bot, token or account; nothing sent to or received from
Telegram; no SMS; no money.** It works only once the founder's bot exists
and Telegram linking and a push provider are switched on (D-092, D-093).
Details, nine PROVISIONAL values (P-102-1 to P-102-9) and founder question
F-26: `docs/DECISIONS.md`, D-102.

| Item | State | Proof (tests in `tests/api/test_telegram_bot.py`, 24; all fail on `fe4546f`) |
| --- | --- | --- |
| **1** New-order alerts to sellers; a reminder before an order expires | **Built.** The alert and the reminder (10 minutes before, D-092) carry ✅ Accept, ✖ Decline, 📥 Orders waiting, "Open in MarkX"; sent once, in the person's language | `test_a_new_order_reaches_the_shop…`, `test_the_reminder_before_an_order_expires…` |
| **2** S-07 the order inbox in the bot: confirm, decline, move on | **Built.** `/orders`; each order's card has the buttons its state allows: Accept, Decline (three reasons), Packed and ready, On its way. Handover codes only on the website | `test_the_owner_accepts_marks_ready_and_sends…`, `test_declining_from_telegram…`, `test_a_collection_order…` |
| **3** S-24 the bot commands | **Built.** `/help`, `/orders`, `/offers`, `/price`, `/stock`, `/checkin` (S-08) | `test_the_commands_list_listings_and_change_price_and_stock` |
| **4** C-10 order updates to buyers | **Built.** Every order message has its own words in Telegram (eight said only "You have a new message"), with a button: the secure tracking link for "order placed", the order page for the rest | `test_the_buyer_follows_the_order…`, `test_every_order_message_has_its_own_words_in_telegram` |
| **5** S-26 the weekly message | **Built.** Figures in Telegram (received, accepted, completed, prices to check) with a check-in button; re-checked at sending, so someone who left the store no longer gets it | `test_the_weekly_message_reads_as_figures…`, `test_the_weekly_message_is_not_sent_to_someone_who_left…` |
| Same permissions and order rules as the website, checked again at every press | **Yes:** the website's own seller check (`deps.seller_membership`, now shared) and its own service functions | the refusal tests: `catalogue` and `finance` roles, another store, a removed member, a disconnected or blocked Telegram, a closed store, too late, already answered, a forbidden move; the `orders` role may not change prices |
| No message lost or sent twice after a restart | **Yes, with one stated exception:** a repeated update acts once and is answered with the current state; outbox messages are never lost and never resent once accepted; a worker dying in the instant Telegram accepts a message makes it be sent again, marked (D-034) | `test_a_press_telegram_delivers_twice…`, `test_a_price_change_telegram_delivers_twice…`, the reminder and weekly tests |
| English and Amharic | **Every new text in both**; native review UNKNOWN | `test_every_bot_text_exists_in_english_and_amharic` |

**For later:** a real bot and phone (the runbook's step 9 lists the Bot
API shapes to re-read; `allowed_updates` must include `callback_query`);
F-26 (whether the bot shows what was ordered; since decided and built,
D-104); answering a reported
problem and recording a direct payment from the bot; staff alerts in
Telegram; a native speaker's review of the Amharic.

**Test results:** see "Tests executed", 21 November 2026 (D-102).

## Pull request #9 reviewed independently and merged (21 November 2026)

Reviewed read-only at `7eabf93` (nothing changed, commented or pushed on
its branch). **No problem that had to be fixed first.** Merged with a
normal merge commit, pinned to `7eabf93`: **`main` is `fe4546f`**, with
exactly the files of `7eabf93`; the branch is kept.

- The commits after `b89aeff` (`ce7b9b4`, `34bc777`, `7eabf93`) change only
  the fix: two account modules, the model, migration `0021`, the new test
  file, two words on the website (and one web test), documents.
- The recycled-number takeover is closed by signing in, connecting from
  the account page (the bot's link), and the Mini App: a different
  Telegram account bringing the same number is refused; the owner's own
  still signs in. All 13 new tests pass; on `b89aeff` 12 fail. With the
  new-column checks removed, 7 still fail on `b89aeff` with the takeover
  itself ("✅ signed in" or "✅ connected" for the stranger) and 4 are
  guards that pass on both.
- No existing test or check was changed by those commits.
- **Three things to know, none blocking:** (1) the database rule
  `telegram_id is null or telegram_id = bound_telegram_id` also accepts a
  connected account with *no* remembered Telegram account (SQL treats a
  NULL check as passing), so the database alone does not force every
  connection to be remembered; every code path does set both, and some
  existing tests rely on the gap; a stricter rule would be
  `bound_telegram_id is not null and telegram_id = bound_telegram_id`.
  (2) No delete or anonymise feature exists today, so nothing conflicts;
  when one is built, the trigger will refuse to clear
  `bound_telegram_id`, so erasure will need its own migration (as F-24
  says for moving a number), and a deleted account will keep its Telegram
  account from signing up again. (3) After "Disconnect Telegram", opening
  the Mini App alone does not sign the owner in; signing in on the website
  with Telegram connects it again. That is not a takeover.
- Results: see "Tests executed", 21 November 2026 (review of pull request #9).

## Fix before merging pull request #9: a recycled number could take over an account (21 November 2026, D-101 section 2a)

An independent review found that after "Disconnect Telegram" MarkX forgot
which Telegram account an account had, so a stranger later given the same
(recycled) phone number could sign in with their own Telegram account and
land in the old owner's account. **Fixed on the same branch, in pull
request #9, merged into `main` as `fe4546f` on 21 November 2026 after an
independent review.** Product code, one migration (`0021`), tests and
documents. **Nothing deployed; no bot, account or SMS; no money.**

| Item | State | Proof (tests) |
| --- | --- | --- |
| The review's defect: disconnect, then a stranger with the recycled number signs in with Telegram | **Fixed.** MarkX remembers for ever which Telegram account an account belongs to (`users.bound_telegram_id`; unique; a trigger refuses to change or clear it); disconnecting only stops messages; only that Telegram account signs in; any other is refused (`phone_on_other_telegram`) and told to contact support (F-24) | `tests/api/test_telegram_recycled_number.py::test_a_recycled_number_cannot_take_over_an_account_after_disconnect` fails on `b89aeff` (the bot tells the stranger "You are signed in") and passes here |
| An account that never had Telegram (invitation, staff, SMS) | **Unchanged:** claimed by the first Telegram sign-in with its number | the same file (invitation case); the existing SMS-account test |
| Other ways found and closed | Connected by the bot link or the Mini App then disconnected; "Connect Telegram" with a second Telegram account after a disconnect; a remembered Telegram account reaching a second account; a disconnected person with a new number got a new, empty account | the same file, 13 tests in all (12 fail on `b89aeff`, 1 guard passes on both); web: 1 new test |

**Outside this fix, said plainly:** signing in by SMS code (switched off)
proves only the number; before SMS is switched back on, the same
recycled-number question must be decided for it (with F-24). An account
that disconnected before migration `0021` would stay unbound (its old
Telegram id was never kept); nothing is deployed, so no real account is.

## Sign-in with Telegram, SMS off, M2, M3, M4 (21 November 2026, D-101)

Product code, one migration (`0020`), tests, one browser journey, one
workflow step, the production example settings and documents. **Nothing
deployed; no bot, token, SMS provider or account; nothing sent to or
received from Telegram; no money.** Details, the reasons and the eight
PROVISIONAL values and rules (P-101-1 to P-101-8): `docs/DECISIONS.md`,
D-101; new founder questions F-24 and F-25 (OPEN, recommendations given).

| Item | State | Proof (tests) |
| --- | --- | --- |
| **1** Everyone signs in on the website with Telegram (decision SI-1); staff keep their second step | **Built, OFF until the bot exists.** One button opens the Telegram app; the person presses Start and "Share my phone number"; the page signs in by itself. Staff then give their password and authenticator code. A link works once, for 10 minutes, and only for the browser that started it | `tests/api/test_telegram_sign_in.py` (32, all fail on `main`: no such feature); `src/lib/telegram-sign-in.test.ts` (3); journey `e2e/telegram-sign-in.mjs` |
| **2** A phone number confirmed by Telegram; Ethiopian mobile only; one number, one account; rules for a changed Telegram account or number | **Built.** Accounts are made only once Telegram confirms the number. A new number on the same Telegram account becomes the account's number; a number already tied to another Telegram account is refused (support decides, F-24) (PROVISIONAL P-101-6) | the same file: own number only, not forwarded, foreign numbers refused, the change rules, two at once |
| **3** SMS switched off by a setting; a real server starts with it off and still refuses the fake | **Done.** `MARKX_SMS_PROVIDER=off`: no code, no notification SMS; the code is kept. The production example says `off` | `tests/api/test_sign_in_abuse.py` (SMS section) |
| **4** M4 Telegram start-up data reusable for an hour | **Fixed.** Five minutes (P-101-3), and a sign-in uses it up | the same file (M4 section) |
| **5** M3 staff lock-out by an outsider; staff numbers told apart | **Fixed.** Locks per address (P-101-4); a lock answers like a wrong password; many failures alert the founder (P-101-5); with SMS off, no way around Telegram (P-101-8) | the same file (M3 section); two existing assertions changed from 429 to 401 (D-101 says why) |
| **6** M2 one person can spend the shared SMS budget | **Fixed** for when SMS is on again: daily shares per number, address and network (P-101-7); the budget stays the final limit; the 80% warning stays | the same file (M2 section): 28 of its 37 tests fail or error on `main`; 9 guards pass on both |
| **7** Pull request #7 review: one buyer's simultaneous orders and expired orders | **Saved.** They pass on `main` (the protection existed); breaking the code on purpose makes them fail | `tests/db/test_buyer_limit_contention.py` (23) |

**For later:** a real bot and a real phone (nothing was tried with
either); the Bot API's `contact` and `reply_markup` shapes re-read at
activation (UNKNOWN until then); the matching-code step (F-25); a staff
tool to move a number (F-24); the Mini App sign-in with the contact step;
native review of the new Amharic (website and bot). Someone without
Telegram cannot sign in while SMS is off.

**Test results:** see "Tests executed", 21 November 2026 (D-101).

## Frontend resilience (20 November 2026, D-100)

The website, its tests, one step of the browser-journeys workflow and
documents. **The API is not changed. Nothing deployed; no account; no
money.** Details: `docs/DECISIONS.md`, D-100. New founder question F-23
(OPEN).

| Finding | State | Proof |
| --- | --- | --- |
| **Defect e** / audit §10: about 20 parts of the website freeze with no message when the connection drops; no proper error pages | **Fixed.** One safe way to call the API that never throws (30 s limit, uploads 120 s, PROVISIONAL); a dropped connection or a server failure shows clear words and a "Try again" button in every one of the 22 component files that call the server (104 calls); no button or form stays stuck. Error pages for the whole site and each section (shop, seller, staff), in Amharic and English, never showing technical details | `src/lib/api/browser.test.ts` (14), `src/components/error-pages.test.ts` (26); `e2e/network-recovery.mjs` cuts the network halfway through a purchase and recovers, exactly one order placed; **on `main` (`fae2514`) it fails at step 1**: "Add to cart" stays "Adding…", disabled, no message, 20 s offline and 5 s after the connection returns |
| No automated accessibility check (audit §10) | **Added to the new journey.** axe-core 4.14.0, WCAG 2.1 A and AA, on every page it visits (notices and error pages included) and the main public pages in both languages; any violation fails. Two problems on every storefront page found and fixed | `e2e/a11y.mjs`; on `main` the first page fails with both |

**For later:** the 404 page for an address matching no route has no `lang`
on `<html>` (axe; the fix needs an experimental Next.js setting); the
other journeys do not call the accessibility check yet; losing the
connection while moving to another page shows the browser's own offline
page (only a PWA could change that); the time limits on real Ethiopian
networks are UNKNOWN until measured; native review of the new Amharic.

**Test results:** see "Tests executed", 20 November 2026 (D-100).

## Order life-cycle hardening (20 November 2026, D-099)

Product code, one migration (`0019`), tests and documents. **Nothing
deployed; no account; no money; no commission rule created.** Details and
the seven PROVISIONAL values (P-099-1 to P-099-7): `docs/DECISIONS.md`,
D-099; new founder question F-22.

| Finding | State | Proof (test) |
| --- | --- | --- |
| **M6** parts out for delivery or after a failed handover never expire (audit §8, §17 item 8) | **Fixed.** Past a time limit (48 hours on the road, never before the promised delivery time; 72 hours after a failed handover; both PROVISIONAL) the watch reports the part to staff by order code (`orders.stalled_on_the_road`, `orders.stalled_after_failed_handover`) and it stops taking one of the buyer's open-order places. It is never ended and its stock never released by the system (the goods are not on the shelf; paid parts need staff, D-086); the shop's return releases it | `tests/api/test_stalled_deliveries.py`, 8 tests; all 8 fail on `c70b338` (no check; the stalled part still refuses the buyer's next order with `too_many_open_orders`) |
| **H2** a rival can keep a shop's stock held by ordering and cancelling (audit §8, §9) | **Fixed for one account, limited for many.** Per buyer, before the shop answers: at most 5 units of one offer and 10 of one shop; a cool-down after 3 cancelled orders in 24 hours (all PROVISIONAL). Other buyers are never limited by one buyer's orders. Many accounts with many phone numbers remain possible (each bounded by the same limits) | `tests/api/test_stock_hold_limits.py`, 7 tests; 4 fail on `c70b338` (6 units accepted; a fourth order accepted after 3 cancellations; settings missing), 3 guards for ordinary buyers pass on both |
| **Commission cap** stored but never applied (audit §11; D-086, D-088 item 1) | **Fixed: applied.** The rule and its cap are copied onto each order line at placement (migration `0019`) and one calculation (`payments/fees.py`) applies each rule's cap per part to the shop's estimate and to the fee at completion; `cap_applied` is set. Commission stays at zero (D-088) | `tests/unit/test_fees.py`, 7 tests (new module); `tests/api/test_commission_cap.py`, 5 tests; 4 fail on `c70b338` (fee 1,185 birr instead of the 500 birr cap; rule and cap not copied), 1 guard passes on both |
| **Pull request #6 review:** a test that sign-in limits hold in any digits | **Added.** Resend cool-down, hourly code limit, lock after five wrong codes, staff lock, and one account / staff member / invitation / team member per number, each across Arabic-Indic, Persian, full-width and mixed digits | `tests/api/test_phone_digit_limits.py`, 8 tests; all 8 fail with the phone code from before D-098 (`d01fef7`), pass on `c70b338` and here |

**Also corrected:** the documents said pull request #6 was not merged; it
is (`c70b338`).

**Test results:** see "Tests executed", 20 November 2026 (D-099).

## Staff conflict of interest, phone digits (20 November 2026, D-098)

Product code, tests and documents. **Nothing deployed; no account; no
money.** Details and the PROVISIONAL choices: `docs/DECISIONS.md`, D-098.

| Finding | State | Proof (test) |
| --- | --- | --- |
| **H1** staff can decide about a store they belong to or an order they placed (audit §8, §9; earlier finding b) | **Fixed.** One shared check, `markx/trust/conflict.py`, in every staff action that decides or changes something about a store, an order, an offer, a review or a report (19 actions: the 8 seller-verification actions that had the check, and 11 that did not; listed in D-098). A refusal says another staff member must handle it and is written to the audit log (`staff.conflict_refused`) even though the request itself rolls back. No override (PROVISIONAL P-098-1) | `tests/api/test_staff_conflict.py` (22 tests): for each action the store's member, or the order's buyer, or the review's or report's author, is refused and recorded, nothing changes, and an unrelated staff member is then allowed. With the check switched off, 22 of 23 such tests fail (the one that passes checks that someone who left the team is allowed) |
| **B-3** a phone number typed with non-English digits caused a server error | **Fixed, by converting** (the friendlier option): any decimal digit (Arabic-Indic, Persian, Devanagari, full-width...) is read as 0 to 9; anything else (Ethiopic numerals ፩ to ፱, superscripts) gets the usual "Enter an Ethiopian mobile number" (422). The development SMS inbox, which gave a server error for any bad number, now answers 422 too | `tests/unit/test_phone.py` (new cases, and every decimal-digit script Unicode knows is checked against the database's own pattern); `tests/api/test_phone_digits.py` (45 tests): code sign-in, staff sign-in, staff accounts, seller invitations, addresses (both numbers), seller applications and contact phone, team members, product requests, rider phone (seller and staff), development SMS inbox. With the old `phone.py` these tests fail with the database's check violation, the server error |

**Also corrected:** the documents said pull request #5 (and, in places,
#4) was not merged; both are merged.

**Test results:** see "Tests executed", 20 November 2026 (D-098).

## Checks once per change, secret scan (20 November 2026, D-097)

CI settings, the secret-scan settings, `.gitignore` and documents only. **No
product code changed; nothing deployed; no account; no money.** Details:
`docs/DECISIONS.md`, D-097.

- **Whole-history secret scan: nothing real found.** Every branch and pull
  request (#1 to #4). Gitleaks 8.28.0 with default rules only: 7 findings,
  all the two labelled development/test encryption keys. Gitleaks with
  `.gitleaks.toml`: none. TruffleHog 3.90.0 (no verification): 2, both the
  test address `https://user:pass@...example`.
- **CI runs once per change.** Pull requests, pushes to `main`, by hand.
  Grouped by pull request number; a newer push cancels the older run of
  the same pull request; main's runs are never cancelled.
- **Documents-only changes** (every changed file a `.md` outside `apps/`,
  `infra/`, `.github/`) skip API, Web app, Containers and the Production
  stack rehearsal; Security always runs; the new "CI result" job passes.
  No test or check reads a document's text (searched); a code change runs
  every job as before.
- **Browser journeys**: pull requests and pushes to `main` that change
  code (same file filters as before), and by hand. A newer push cancels the
  older run of the same pull request (grouped by its number); a run on
  main is never cancelled. (The first version ran them only on `main`; the
  founder reversed that before merging.)
- **W-1 fixed:** the Gitleaks allow-list ignores only the labelled value
  itself, no longer a whole line. **`.gitignore`** ignores `*.pem`, `*.key`.

**Test results:** see "Tests executed", 20 November 2026 (D-097).

## Backup trust hardening (19 November 2026, D-096)

The independent audit's most serious backup findings, each checked first
against the code at `c4a1843` (all were still true), fixed, and proved by
tests against PostgreSQL 17.12 and MinIO only. **Nothing is connected: no
account, bucket, key or server exists; nothing was deployed; no money was
spent.** Details and every PROVISIONAL choice: `docs/DECISIONS.md`, D-096.

| Finding | State | Proof (test) |
| --- | --- | --- |
| **BK-1** the server's key can delete every backup; no object lock | **Fixed (code and tests); real provider NOT VERIFIED.** The service only adds, reads and lists; retention is `prune`, off the server, with its own key, version- and lock-aware; staging and production require a COMPLIANCE object lock (PROVISIONAL) | `test_the_servers_backup_key_can_add_read_and_list_but_never_delete`, `test_a_required_object_lock_is_checked_and_a_bucket_without_one_is_refused`, `test_in_a_locked_bucket_every_object_is_locked_and_a_reused_blob_stays_locked`, `test_retention_removes_every_version_and_leaves_no_delete_marker` (`tests/storage/test_backup_trust.py`); `test_the_service_backs_up_and_never_deletes_or_runs_retention`, `test_the_service_does_not_start_against_an_unsafe_bucket` (`tests/unit/test_backup_commands.py`) |
| **BK-3** a damaged upload is reused by name, and the set marked complete | **Fixed.** Reuse only when size and ETag match the record made right after the read-back passed; the index records each blob's encrypted size and SHA-256; a set is complete only when every blob passed | `test_a_blob_whose_upload_failed_its_check_is_uploaded_again_by_the_next_run` (the audit's regression test), `test_a_blob_changed_at_the_destination_since_its_check_is_uploaded_again`, `test_the_index_records_each_blobs_encrypted_size_and_hash`, `test_a_set_is_complete_only_when_every_blob_in_it_passed` |
| **BK-2** the drill puts the recovery key on the server and restores into the production cluster | **Fixed (code, CI and runbook).** `verify`, `restore`, `drill`, `prune` refuse staging and production; `drill --from-destination` on a throwaway recovery machine with a read-only key; `record-drill` for the watch | `test_what_needs_the_recovery_key_or_deletes_never_runs_on_a_server` (24 cases), `test_the_off_server_drill_needs_only_a_read_only_key_and_writes_nothing`, `test_record_drill_refuses_a_report_it_cannot_tie_to_a_real_set`; CI step "Off-server recovery drill" |
| **BK-6** a restore runs as the superuser, so a forged dump can run programs | **Fixed.** `pg_restore` and the checks run as `markx_migrator`/`markx_app`; the throwaway PostgreSQL has no network (`infra/backup/recovery-host.sh`); the runbook says sets after a suspected break-in are not trusted. Signing stays on the server (a later option) | `test_a_forged_dump_cannot_run_a_program_on_the_recovery_machine` (the same archive runs `COPY ... TO PROGRAM` as the superuser, is refused as the owner), `test_the_restored_copy_is_owned_by_the_owner_role_with_the_sources_exact_grants` |
| **BK-7** a restore can reset production's role passwords | **Fixed.** The BK-2 refusal alone did NOT cover it (a machine without `MARKX_ENV` could still point at production), so the restore now never resets an existing role's password and refuses `MARKX_DB_*_PASSWORD` when the roles exist | `test_a_restore_never_resets_the_password_of_an_existing_role` |
| **BK-17** CI uses MinIO's root keys and a floating `postgres:17` | **Fixed.** Five least-privilege MinIO users (`infra/backup/minio-least-privilege.sh`) in the tests and both CI drills; `postgres:17.12` pinned | every test in `test_backup_recovery.py` and `test_backup_trust.py` now runs on those users (CI requires them); CI steps "Least-privilege MinIO users" and both drills |

**Found and fixed on the way:** a restore as the owner role would have
widened every table's grants (bootstrap.sh's default privileges), taking
the audit log's protection away; the restore now clears them first
(proved by the exact-grants test, which fails without the fix).

**Still open from the backup findings:** BK-4 (alerts that work without the
server), BK-5 (an off-server escrow of the application secrets), moving
manifest signing off the server (audit 3B), BK-8 to BK-16 and BK-18; no
scheduled deep verification (BK-11). **To test on the real provider once
F-16 is decided:** the runbook's section "To test on the real provider",
Cloudflare R2's bucket locks above all (UNKNOWN).

**Test results:** see "Tests executed", 19 November 2026 (D-096).

## State on 19 November 2026

**Summary in plain English** (the state report's summary, corrected by a
check of the complete Git history; the corrections are listed under
"Reports" below):

- **Where things stand.** MarkX is a well-built but **unlaunched**
  marketplace. All the work of the AI sessions was merged into `main` on 19
  November 2026 through pull request #1 (merge commit `10a72b1`). Both
  automatic test suites passed on that exact version: the main test run (CI
  run 133) and the website click-through tests (Browser journeys run 22).
  Nothing is running on the internet, and no outside account (payments,
  SMS, Telegram bot, file storage, backups, domain) exists yet.
- **What works (in testing).** A buyer can search in Amharic or English,
  see every seller's offer for a product, fill a cart, order from several
  sellers at once, pay the seller directly at handover using a six-digit
  code, and report a problem. Sellers can apply, list offers, manage stock
  and handle orders. Staff have screens for approvals, problems, reviews,
  reports, settings and exports. Encrypted backups and a production server
  setup exist as code and are rehearsed automatically.
- **What is not done.** Sellers are not yet told about new orders by phone
  (no Telegram bot or SMS provider is connected); this is a **launch
  blocker**. There is no real server, domain, file store or off-server
  backup. A few Release 1 features are missing: the legal notice before
  ordering, "lite mode", price-history chart, share cards/QR code, a
  seller's customer list, reorder, gate photo on addresses, and the
  Ethiopian calendar/clock.
- **Earlier findings.** All eight earlier findings (a to h) are still true
  in the code; they are listed below as known defects. None is fixed: each
  needs a code change.
- **The history is complete; nothing was squashed.** `main` holds 125
  commits: the 123 of pull request #1, the initial commit `617a276` (its
  only starting commit) and the merge commit. Commit `daaee71` has a parent
  (`7c11d3c`), and the older commit numbers these documents quote, such as
  `7c492c6`, `eab7c21`, `497fcf5`, `88d481b`, `641a95b`, `1920e55` and
  `9af18c7`, are all in `main`'s history. The state report's "51 commits"
  and "`daaee71` has no parent" are what a shortened download of the last
  50 commits shows: `daaee71` is the 50th commit, so such a download stops
  there. Checked on 19 November 2026 with a complete clone
  (`git rev-parse --is-shallow-repository` prints `false`;
  `git rev-list --count origin/main` prints `125`;
  `git log -1 --format=%p daaee71` prints `7c11d3c`), and reproduced with
  `git clone --depth 50`, which shows 51 commits and cuts at `daaee71`.
- **Other branches.** Nothing useful is missing from `main`.
  `claude/markx-seller-management-oag1a4` is fully contained in `main` (no
  commit of it is missing). `claude/markx-third-session-cq58yj` has three
  commits that are not in `main` (`03a879b`, `6f81193`, `55c7b24`): an
  earlier, alternative version of the order-delivery work that `main`
  already contains in its own form, with equivalent tests.
  `claude/project-scaffold` is fully merged.
- **The documents were out of date in places** (the state report's section
  2); they were corrected on 19 November 2026.
- **Next task: waiting for the founder's choice.**

**Reports**

- The read-only state report:
  [docs/reports/2026-11-19-markx-readonly-audit-report.md](reports/2026-11-19-markx-readonly-audit-report.md),
  copied unchanged. **Corrections from the complete-history check of 19
  November 2026** (the report itself is left as written):
  - Summary and section 1: "the history was squashed into one commit before
    the merge", "`main` has 51 commits" and "`daaee71` has no parent" are
    wrong. `main` has 125 commits and `daaee71`'s parent is `7c11d3c`.
  - Section 1, branch table: `claude/project-scaffold` is 1 commit behind
    `main` (not 2). `claude/markx-third-session-cq58yj` is 104 behind and 3
    ahead (not 50 and 23), and shares history with `main` up to `eb52d2f`.
    `claude/markx-seller-management-oag1a4` is 108 behind and 0 ahead (not
    50 and 16), and is fully contained in `main`.
  - Section 2: the caution that dates of `daaee71` mean "at or before the
    squash" does not apply; those are the true last-change dates.
  - Section 2, point 5: the "68 tables" line is in `docs/ARCHITECTURE.md`
    (line 16), not in `README.md`.
  - Section 2, point 16: wrong. The commits it names are in `main`'s
    history; the documents' commit numbers were left as they are.
  - Section 6: the third-session branch has 3 commits not in `main` (not
    23), and the seller-management branch is merged by commit identity too.
  - Part 1: the 22-section audit was found and saved afterwards (next item).
- The 22-section independent audit:
  [docs/reports/2026-11-19-independent-audit.md](reports/2026-11-19-independent-audit.md).
  It was recovered word for word on 19 November 2026 from the record of the
  session that wrote it (written at 00:17 UTC). It checked
  `claude/project-scaffold` before pull request #1 was merged, so its
  statements that `main` is empty and PR #1 is open describe the state
  before the merge.

**Known defects confirmed in the code** (state report, section 5; each
needs a code change, none is fixed):

| | Defect | Where it is shown |
| --- | --- | --- |
| a | Commission is zero; the per-order cap is stored but never applied (**cap fixed by D-099**: copied onto each line and applied to every fee calculation; commission stays at zero, D-088) | [state report §5 a](reports/2026-11-19-markx-readonly-audit-report.md#5-earlier-findings) |
| b | The "not your own store" check exists only in seller verification: staff who belong to a store can still decide its disputes, reviews, reports and takedowns (**fixed by D-098**, H1: one shared check in every such staff action) | [state report §5 b](reports/2026-11-19-markx-readonly-audit-report.md#5-earlier-findings) |
| c | Orders out for delivery or with a failed delivery never expire (**fixed by D-099**, M6: past a time limit they go to staff and free the buyer's open-order place; their stock stays held until the shop settles them) | [state report §5 c](reports/2026-11-19-markx-readonly-audit-report.md#5-earlier-findings) |
| d | A buyer can keep a competitor's stock held by ordering and cancelling (limited, not removed; **limited further by D-099**, H2: per-buyer limits on unanswered holds per offer and per shop, and a cool-down after three cancellations in a day; many accounts with many phone numbers are still possible) | [state report §5 d](reports/2026-11-19-markx-readonly-audit-report.md#5-earlier-findings) |
| e | About 22 parts of the website freeze with no message when the connection drops; no proper error pages (**fixed by D-100**: one safe API call with "try again" in every part that calls the server, error pages in both languages, a network-cut journey) | [state report §5 e](reports/2026-11-19-markx-readonly-audit-report.md#5-earlier-findings) |
| f | Certificates do not renew automatically; rollback breaks when an image prefix is set | [state report §5 f](reports/2026-11-19-markx-readonly-audit-report.md#5-earlier-findings) |
| g | The picomatch audit warning is allowed until 31 December 2026; the web CSP allows inline scripts | [state report §5 g](reports/2026-11-19-markx-readonly-audit-report.md#5-earlier-findings) |
| h1 | The server's storage key can delete every backup (**fixed by D-096**, BK-1; merged, pull request #4) | [state report §5 h1](reports/2026-11-19-markx-readonly-audit-report.md#5-earlier-findings) |
| h2 | Backups are not protected by object lock (**fixed by D-096**, merged, pull request #4: required on staging and production, PROVISIONAL; real provider not verified) | [state report §5 h2](reports/2026-11-19-markx-readonly-audit-report.md#5-earlier-findings) |
| h3 | Recovery drills put the recovery private key on the server (**fixed by D-096**, BK-2; merged, pull request #4) | [state report §5 h3](reports/2026-11-19-markx-readonly-audit-report.md#5-earlier-findings) |
| h4 | A restore runs with full database administrator rights (**fixed by D-096**, BK-6; merged, pull request #4) | [state report §5 h4](reports/2026-11-19-markx-readonly-audit-report.md#5-earlier-findings) |
| h5 | A failed upload can be reused just by its name (**fixed by D-096**, BK-3; merged, pull request #4) | [state report §5 h5](reports/2026-11-19-markx-readonly-audit-report.md#5-earlier-findings) |
| h6 | All alerts run on the server they watch | [state report §5 h6](reports/2026-11-19-markx-readonly-audit-report.md#5-earlier-findings) |
| h7 | `MARKX_ENCRYPTION_KEY` and `MARKX_SECRET_KEY` have no recovery copy off the server (partly covered by a written instruction) | [state report §5 h7](reports/2026-11-19-markx-readonly-audit-report.md#5-earlier-findings) |
| h8 | The server holds the key that signs backups | [state report §5 h8](reports/2026-11-19-markx-readonly-audit-report.md#5-earlier-findings) |

**From the audit, not yet checked against the code.** These findings of
the independent audit are not among a to h above. The section numbers
point into
[the audit](reports/2026-11-19-independent-audit.md).

- Backup (audit §5):
  - BK-5 also names the database role passwords and the TLS keys as having
    no escrow;
  - BK-7: a restore or drill on the production cluster can reset production
    role passwords through bootstrap (**checked and fixed by D-096**,
    merged);
  - BK-8: "off-site" is decided by the provider label, not the endpoint;
  - BK-9: the backup uses the schema-owner role, with internet access;
  - BK-10: a restore depends on a content type sniffed from the first 16
    bytes;
  - BK-11: there is no scheduled deep verification;
  - BK-12: rotating the signing key re-uploads every file and leaves old
    sets "untrusted" for ever;
  - BK-13: anonymous reading of objects is not checked;
  - BK-14: multipart uploads are not paginated;
  - BK-15: the plaintext manifest shows row counts per table;
  - BK-16: unexpected restore errors leave no FAILED report;
  - BK-17: the CI drill uses root MinIO keys and a floating `postgres:17`
    tag (**checked and fixed by D-096**, merged);
  - BK-18: the recovery key is plain base64 with no passphrase or split.
- Backend and security (audit §8 and §9):
  - M1: fake reviews through self-orders;
  - M2: one global SMS budget of 500 a day can be used up, blocking all
    sign-ins (**fixed by D-101**: daily shares per number, address and
    network);
  - M3: targeted lockout of staff and staff-number enumeration (**fixed by
    D-101**: locks per address, one answer);
  - M4: Telegram sign-in data can be replayed for an hour (**fixed by
    D-101**: five minutes, single use);
  - M5: fees can be avoided by marking an order failed or returned after
    cash was collected; payments are seller-attested only; no staff tool
    for commission rules;
  - L4: OTP, session, SMS and notification rows are kept for ever; data
    requests are stored but never processed;
  - the Gitleaks allowlist matches whole lines, which could hide a real
    secret (**fixed by D-097**, W-1: only the labelled value is ignored);
  - secrets are passed as environment variables, and one `secret_key`
    serves every purpose with no rotation overlap;
  - the Low findings L1 to L9 of audit §9;
  - supply chain: actions pinned by tag, not SHA; images by tag, not
    digest; no container scan; no scheduled audit or Dependabot.
- Business logic (audit §7 and §11):
  - the OTP 24-hour deletion (blueprint G.2) is not done;
  - the payout cool-off is 72 hours against the blueprint's 48 (H.2);
  - a parent order shows "completed" while a part is still in its problem
    window;
  - a payment can be recorded only after handover (compare D-087, the
    founder's decision of 18 November 2026);
  - there is no refund record (blueprint J.5) and no money-return flow for
    paid undelivered parts (compare D-087: no refund process, by
    instruction);
  - settlement and payouts are models only;
  - there is no buyer cancellation-abuse scoring.
- Website (audit §10): no automated accessibility check; the Amharic
  wording has not been reviewed by a native editor; the browser journeys
  run against `next start`, not the production image behind nginx (they
  run on pull requests that change code since D-097, merged).
- Infrastructure (audit §13):
  - a failed check after migrations leaves the system half up;
  - images are referenced by tag, not digest;
  - only memory limits are set (no CPU or process limits);
  - user id 999 is assumed but not fixed in the Dockerfile;
  - each service runs as one copy, so a deploy causes downtime;
  - there is no log shipping;
  - rollback does not roll back the backup service.
- CI and testing (audit §14):
  - no scheduled runs;
  - no migration downgrade or upgrade-from-previous-release test;
  - no load test;
  - no test of BK-3 (**added by D-096**, merged);
  - the drill does not use least-privilege keys (**fixed by D-096**, merged);
  - branch protection on `main`: NOT VERIFIED by the audit.

**Known issue: Node.js 20 in the pinned GitHub actions.** GitHub's runners
warn on every CI job: "Node.js 20 is deprecated. The following actions
target Node.js 20 but are being forced to run on Node.js 24".
- The actions named are `actions/checkout@v4`, `actions/upload-artifact@v4`
  and `astral-sh/setup-uv@v6` (the API job of CI run 133), and
  `actions/checkout@v4` and `actions/setup-node@v4` (the web job).
- The jobs still pass. Fixing it means changing the workflow files, which
  needs the founder's approval as a code change.

---

**Updated on 18 November 2026** by the **off-server backup and disaster
recovery session** (D-094): the audit's six backup findings verified in the
code and all true (dumps on the same server, unauthenticated AES-256-CBC,
the passphrase beside the database passwords, no file backup, failures
heard by no one, no database-plus-file restore test). Replaced by
`python -m markx.backup`: a **backup set** is the PostgreSQL 17 dump and
every stored object, taken from one exported snapshot, encrypted with
**public-key authenticated encryption** (X25519 + AES-256-GCM in chunks,
"MXB2") so the server can encrypt but never decrypt, uploaded to a
provider-independent S3-compatible destination, read back and checked, and
committed by an **Ed25519-signed manifest**; a restore into a NEW database
and EMPTY stores that verifies everything first and checks everything
after; an automated **recovery drill** with seven injected faults, in CI on
every push; retention that never deletes the last good set and waits for
the founder's numbers; and five new watch alerts fed by `backup_runs`
(migration `0018`). The production `backup` service, `deploy.sh` and the
rehearsal use it; the CBC scripts are gone (a decrypt-only legacy restore
is kept). **Tested against PostgreSQL 17 and MinIO only. No provider,
bucket, account or real key exists; nothing was uploaded outside this
machine and CI; MarkX has NO off-server backup** until the founder decides
F-16, F-19 and F-20 (new) and the activation steps are done, and alerts reach
a person only once the alert group exists (F-18). Before it, the **Telegram
account connection session** (D-093): a signed-in person can connect their own Telegram
account with a one-time link that the bot's `/start` confirms through a
secret-checked webhook (`POST /me/telegram/link`, `POST /telegram/webhook`,
`GET`/`DELETE /me/telegram`; migration `0017`), with the token stored only as
a keyed hash, single-use, ten minutes, bound to the account and its sign-in
session; one MarkX account per Telegram account under locks and the unique
constraint; replays, duplicates and anything but `/start` in a private chat
ignored; the account page's section in Amharic and English for every state,
and a card on the seller overview. **The whole feature is OFF by default
(`MARKX_TELEGRAM_LINKING_ENABLED=false`); no bot exists, no webhook is
registered and nothing was sent to or received from Telegram. Seller
notifications remain a launch blocker** (N-1). Before it, the
**notification system session**
(D-092, N-1): the audit's defect fixed first — `get_push_sender()` raised on
staging and production, so every notification for a person with Telegram
linked was retried eight times and given up; now a missing provider is
recorded `unavailable` and the worker carries on. Delivery records per
notification and outside channel (`notification_deliveries`, migration
`0016`), a provider-independent Telegram interface with the fake and a Bot
API adapter tested against stand-ins only, order-alert SMS through the
existing SMS adapter (purpose `notification`, short English and Amharic
texts carrying the order code only, its own budget, a per-person limit and
a cooldown, **OFF by default**), a once-only reminder before a seller's
answer is due (`seller_order_reminders`), `dispute.decided`, a second check
at delivery that the recipient may still handle the store's orders, crash
safety committed around each provider call (Telegram at-least-once, SMS
at-most-once; exactly-once is not claimed) and four new watch alerts.
**No bot, no SMS provider and no account exists; nothing was sent outside
the server. Seller notifications are a launch blocker until a real channel
is connected and tested** (N-1). Before it, the **production deployment
foundation session** (D-091): production images for the API and the web
app; a separate production Compose file (`infra/production/`) with an
nginx reverse proxy (HTTPS-only, TLS 1.2/1.3, HSTS, body and edge rate
limits, the visitor's address set at the edge), PostgreSQL, the worker as
scheduler, a nightly encrypted backup service and a one-time migration step
under an advisory lock, on internal networks where only the proxy has ports
and only the API and worker reach the internet; liveness and readiness
separated, a preflight command and a worker heartbeat; stricter
real-server configuration (Fernet key, explicit trusted proxies, no DEBUG,
no raw configuration in a refused start-up) and a start-up check for the
web container; `deploy.sh` (check, deploy, rollback, backup, status) and a
local rehearsal of the whole stack that CI runs; runbooks in
`docs/runbooks/` and `docs/DEPLOYMENT.md`. Four existing defects fixed on
the way (a password in start-up errors, every page's search counted as one
visitor, `bootstrap.sh` resetting real passwords to the laptop defaults on
a restore, a missing bucket crashing the storage watch). **Nothing was
deployed and no account, server, domain or certificate was created; MarkX
is not production-ready** (F-01, F-14 and F-15 stay open; new founder items
F-16 to F-18). Before it, the **object storage session**
(D-090): one file-storage interface with four adapters chosen by
configuration (the local folders, MinIO, Amazon S3 and Cloudflare R2, on
boto3); seller documents, picture sources and problem photos in a private
bucket and rendered pictures in a separate public one; the API's personal
five-minute links unchanged and no bucket address ever given to a browser;
every store refusing anything but a real JPEG, PNG or WebP of its declared
type, oversized files and unsafe keys; outages as a 503 that names nothing;
a watch check for an unreachable store and for a private bucket that has
turned public; staging and production refusing to start without `s3` or
`r2` or with pictures on the site's own domain; MinIO in Compose, in CI's
API tests and in the browser journeys; and a copy tool for existing files
that only runs with the founder's approval. **Tested against MinIO only: no
Amazon or Cloudflare account or bucket exists, and no document was copied
anywhere** (F-01 stays open; new founder items F-14 and F-15). Before it,
the **SMS foundation session** (D-089): the provider-independent SMS interface (`send(phone, text, *,
reference) -> SmsResult`), a standard-library HTTPS adapter with a
placeholder wire format, delivery records in `sms_messages` (migration
`0015`; never the text or the code), a 60-second per-number resend cooldown
with the wait shown in both languages, failure-rate and unfinished-message
alerts, and staging and production refusing to start with the fake SMS
sender. **No provider is chosen or contacted and no real SMS has been sent**;
three new founder items, F-11 to F-13. Before it, the **founder's F-09 and
F-10 decisions**: a direct payment is now recorded only once the goods are handed
over (D-087, migration `0014`; no refund process, by instruction), and fees
stay at zero with the list of what must exist before any fee (D-088).
Before it, the **order and payment integrity session** (the audit's P0-3,
D-086): a paid part can no longer be cancelled
or returned without staff (service, database constraint and a staff alert);
a store can no longer tell which buyer wrote a review; the weekly report
splits buyer cancellations from the store's own unfulfilled orders and makes
each store's report on its own; three more order actions read the clock
after taking the order; commission and the ledger investigated (zero fees
are by design; the per-order cap is stored but never applied). Two new
founder decisions, F-09 and F-10. Before it, the **dispute timestamp fix**: a
staff decision on a reported problem now reads the clock only once it holds
the order, so `resolved_at` is the moment it took effect (a race test failed
once in CI #97 because of it); a deterministic regression test. Before it,
the **Turnstile session, second round** (D-085 update): Turnstile hostnames checked at start-up, the
founder's local test widget documented, the Turnstile test instructions
corrected (Turnstile verification, SMS delivery and a complete production
sign-in are three different things; only the first works today), the
credential-rotation and 100th-transaction security-review reminders, and a
flaky test fixed. Before it, the **Turnstile session** (D-085):
the real bot check, Cloudflare Turnstile, built on the API and the sign-in
page and tested against stand-ins. **Not yet tested against Cloudflare**:
the founder's keys are not configured yet, and no real server can start
without them. Before it, the **security and CI session** (the
independent audit's P0-1 and P0-2; D-084): five security fixes (SEC-1, -2,
-3, -5, -6), a secret scan and dependency audits in CI, the browser journeys
on every code push against Compose, and an automated page-weight check. See
"Security and CI session (D-084)" below and in "Tests executed". Before it:
the tenth engineering session (the web app's
owner: the buyer's and the seller's screens — reviews and report links
(D-072), pictures and problem evidence (D-074), the rest of the seller
dashboard (D-075) — and, in a second round, every remaining screen the API
supports: the buyer's account, the next-best offer, the category page,
search suggestions, the shop's location, closing and product suggestions,
the staff's trust actions, delivery zones and catalogue setup (D-076 to
D-078); in a third round, a store's track record on its page, search by
rating and seller level, a worker pass that reports failure, and the
browser journeys on GitHub (D-079 to D-081); then the cause of the "worker
pass that handled nothing", fixed (D-082); then, at the founder's request,
PROVISIONAL answers to F-01 to F-08, marked in the code and to be confirmed
before going live, and the retention job of F-08 (D-083)). The ninth session built every admin screen (D-069 to
D-071); a back-end-only continuation in parallel added the seller
performance figures and the weekly seller message (D-073), merged in this
session.
**Branch:** every session starts from the latest `main` and works on its own
new branch (`AGENTS.md` section 4). `claude/project-scaffold`, the working
branch until then, was merged into `main` through pull request #1 on 19
November 2026 (merge commit `10a72b1`).
**Latest commit:** see `git log -1`; the handoff (`docs/HANDOFF.md`) names it.
**Read this after** `AGENTS.md` and `MARKX_MASTER_BLUEPRINT.md`.
`docs/HANDOFF.md` holds the last session's report in plain words, the
decisions waiting on the founder, and a ready-to-paste brief for the next
engineer.

This file states what exists, what is tested and what is not. Nothing here is
aspirational. If a line says "tested", the test is in the repository and passed
on the date above.

## In one paragraph

The master blueprint is in the repository. The back end covers the foundation
plus four business phases: the complete Release 1 database schema, sign-in,
the permission model, delivery zones, buyer addresses, the staff-curated
catalogue, seller onboarding and management (P6), seller offers and inventory
(P7), **the background worker** (part of P2), and **the cart, checkout and
multi-seller orders (P9 and P10 on the API side)**. A buyer can fill a cart,
see every price recomputed by the server, place an order that fans out into
one seller order per seller; each seller confirms or declines its own part,
packs it, dispatches it or hands it over at the counter against the buyer's
six-digit code, and records the direct payment; the part completes when the
buyer confirms or the problem window passes, at which point the stock leaves
the shelf and the fee is charged. A silent seller's order expires, a failed
delivery is retried or returned, and an order nobody packs for fourteen days
is cancelled. The buyer's order page also opens from a signed link without
sign-in, never showing the handover code. When a seller declines or stays
silent, the buyer is pointed at the next-best offer from another seller. A
buyer can report a problem inside the 72-hour window, which stops
completion; both sides add their account and staff decide, completing the
part or recording that the seller refunded the buyer directly. **Search**
finds products from one box in Amharic script, Latin-letter Amharic or
English, tolerating typos, with filters, sorting, a query log, a zero-result
report and a synonym tool for staff, and an evaluator scores it against real
queries once the founder supplies them. **The web app** (`apps/web`, Next.js)
now serves the buyer's whole journey in Amharic and English: home, search,
product with the offers table, shop page, sign-in by code, cart, checkout,
orders with the handover code, cancel, "the goods are right", "report a
problem", and the tracking page by secure link; and **the seller dashboard**:
the order inbox with the answer countdown and every fulfilment step, and the
offers list with quick price and stock edits; and **the admin dashboard**:
staff sign-in, the problem queue and decisions, the orders desk, seller
applications with documents, the search tools, and (session nine) product
proposals, invitations, listing takedowns and the audit trail. **CI** runs every API and
web check on every push. **The eighth session (back end only)** added search
throttling (D-059), per-order isolation in the completion job (D-060), a
compatible-copy rule for the API description (D-061), **product pictures and
problem photos** (D-062), **encrypted backups with a restore drill in CI**
(D-063), **self-monitoring with alerts and a daily reconciliation** (D-064)
and **the rest of the admin back end**: the audit-log viewer, switches and
risk limits, staff accounts, the dispatch board and the business dashboard
(D-065), then **reviews and ratings** (D-066), **reports on listings,
stores and reviews** (D-067), **data exports for an accountant** (D-068)
and **the seller performance page with its weekly message** (D-073).
Session nine built the admin screens for them (D-070, D-071). **Session
ten** (the web app's owner) built the buyer's and the seller's remaining
screens: reviews, ratings and report links (D-072), pictures on the product
card and page, shops' own photos and problem evidence (D-074), and the rest
of the seller dashboard, from the application to performance (D-075).
In a second round it built every remaining screen the API supports (D-077),
refused closing a store with orders in progress (D-076) and gave the
settings their Amharic descriptions (D-078). **Files** (documents,
pictures, problem photos) go through one storage interface that works with
the local folders, MinIO, Amazon S3 or Cloudflare R2 by configuration
(D-090), tested against MinIO; no S3 or R2 bucket exists yet (F-01). **Not
built:** the bot (the founder creates it); Telegram *linking* (D-093)
and Telegram *sign-in* for everyone (D-101, decision SI-1) are built and
switched off until it exists; SMS is switched off (D-101); deployment. Nothing is deployed anywhere.

## Sessions so far

| Session | Commits | What it added |
| --- | --- | --- |
| 1 | `617a276` to `6f36391` | Blueprint, schema, sign-in, permissions, delivery zones, addresses, catalogue, documents. 454 tests |
| 2 | `8a6e583` to `8df958b` | Status corrections, sellers (P6), offers and inventory (P7). 647 tests |
| 3 | `399507e`, `bd835ef`, `7079cb5`, `eb52d2f` | Review fixes (a moderation bypass, lock ordering), the worker, cart and checkout (P9), multi-seller orders (P10, first half). 779 tests |
| 4 | `7c492c6`, `6582017`, `10573b4` | The second half of P10: ready, dispatch, the handover code, delivered, completed with `commit_stock` and the fee charge posted to the ledger, failed deliveries and returns, the direct payment record, the overdue-hold job, the staff orders desk's first three routes, the tracking page by secure link. 801 tests |
| 5 | `497fcf5`, `5ce4340`, `cdf16c5` and a documentation commit | Review fix (a cancelled shipment had no tracking event), the next-best offer (C-26), problems on a delivered order with staff decisions (`disputed`, `refunded`), search (P8 on the API side). 847 tests |
| 6 | `641a95b` to the head; see `docs/HANDOFF.md` | Review fix (a withdrawn product stayed findable), the founder's provisional approvals (D-053), the search evaluator (D-054), CI, the web app (D-055): the storefront and buyer journey, the seller dashboard, the admin dashboard; demo data (D-056); variant labels in the cart and offer lists. 854 API tests, 9 web unit tests, two browser journeys |
| 7 (parallel, backend only) | after `eab7c21`; see `docs/HANDOFF.md`, Part A.0 | Independent review of search, the next-best offer, disputes, seller isolation and the worker; two search fixes and an evaluator fix (D-057); containers for a laptop and a CI job that builds them (D-058). **`apps/web` not touched** |
| 8 (back end only) | `2e4944c` to `b2b674e`, then the performance commit after session nine's; see `docs/HANDOFF.md`, Part A.00 | Search throttle (D-059); completion job isolates each order (D-060); OpenAPI copy rule (D-061); pictures and problem photos, migration `0008` (D-062); backups and the restore drill (D-063); monitoring, alerts and reconciliation, migration `0009` (D-064); admin back end (D-065); a flaky contention test fixed; then reviews and ratings, migration `0010` (D-066), listing reports, migration `0011` (D-067), data exports (D-068), and the performance page and weekly seller message, migration `0012` (D-073). **`apps/web` not touched** |
| 9 (web owner, resuming) | `eab7c21`, `207aafe`, `22339ed`, `9ac3b94` and the commits after it | The founder's confirmation of the fulfilment hold (D-043, D-053); one test ported from the alternative branch; the takedown queue route `GET /admin/offers/held` (D-069); every admin screen the API supports, a role-aware admin home and menu, codes shown in words, a not-allowed page state (D-070, D-071); `e2e/admin-queues.mjs`. 935 API tests, 21 web unit tests |
| Telegram account connection (D-093) | the commits after `366f8f9`; see `git log` | `markx/accounts/telegram_link.py`: the one-time link, the webhook, status and disconnect; migration `0017` (`telegram_link_tokens`, `telegram_updates`, `users.telegram_linked_at`/`telegram_unlinked_at`); `MARKX_TELEGRAM_LINKING_ENABLED` and its settings (off); the Mini App link behind the same switch; `TelegramConnection.tsx`, `lib/telegram.ts`, the seller overview card; `tests/api/test_telegram_linking.py`; `e2e/telegram-connection.mjs` in the journeys. Nothing connected |
| Notification system (D-092, N-1) | the commits after `bd091bd`; see `git log` | The push-provider defect fixed; `notification_deliveries` and `seller_order_reminders` (migration `0016`); `notifications/delivery.py`, `texts.py`, the Bot API adapter; notification SMS (off), its budget, limit and cooldown; the deadline reminder job; `dispute.decided`; four `notifications.*` watch checks; `MARKX_TELEGRAM_PUSH_PROVIDER`; `tests/api/test_notification_delivery.py`. Nothing connected |
| Production deployment foundation (D-091) | the commits after `a9941d2`; see `git log` | API and web production images, `infra/production/` (Compose, nginx, env templates, `deploy.sh`, the rehearsal), `markx/ops/health.py` and `preflight.py`, the worker heartbeat, the migration lock, stricter real-server configuration, the web start-up check and address forwarding, `bootstrap.sh` keeping real passwords, `check_reachable` on a missing bucket, `docs/DEPLOYMENT.md`, `docs/runbooks/`, CI's web image and rehearsal jobs. No migration |
| Object storage (D-090) | the commit after `d4a29af`; see `git log` | `ObjectStore` with `local`, `minio`, `s3` and `r2` (boto3), the start-up checks, `file_storage` watch check, `scripts/copy_files_to_object_storage.py`, MinIO in Compose, CI and the journeys, `tests/storage/` (136 tests). No migration |
| SMS foundation (D-089) | see `git log`; the commit after `3c7921c` | The SMS interface, the HTTPS adapter skeleton (no provider), `sms_messages` (migration `0015`), the resend cooldown, `sms.failures` and `sms.unfinished` alerts, the SMS start-up checks, `e2e/sign-in-cooldown.mjs`. 1251 API tests, 71 web unit tests |
| F-09 option 2, F-10 recorded (D-087, D-088) | the commit after `9af18c7` | `PAYABLE` is now delivered, completed and disputed; migration `0014` (`trg_seller_orders_payment_at_handover`) refuses an advance payment record without touching existing ones; the web app shows "Record the payment" only from the handover on; F-09 and F-10 closed as D-087 and D-088 |
| Order and payment integrity (D-086) | `9af18c7` | Paid parts never end undelivered without staff (migration `0013`, `paid_orders_waiting` alert, buyer's Cancel hidden); `order_item_id` withheld from stores; weekly report: cancellations split by who ended them, one savepoint per store; `cancel_by_buyer`, `confirm_received`, `record_direct_payment` read the clock after the lock; commission and ledger gaps recorded (F-10) |
| Dispute timestamp fix | `1c55602` | `resolve_dispute` reads the clock after taking the seller order's lock (one line); `test_a_decision_reads_the_clock_only_once_it_holds_the_order`, deterministic, both decisions. No `DECISIONS.md` entry: a fix within D-050's rule, not a new decision |
| Turnstile, second round (D-085 update) | `8b32485` | Hostname validation at start-up, `localhost` refused on real servers; the local test widget and corrected test steps in `docs/SETUP.md`; rotation and security-review reminders; the flaky document-link forgery test made deterministic |
| Turnstile (D-085) | `45a699c` and the status commit after it | Cloudflare Turnstile verified on the server (`TurnstileBotCheck`), its configuration with the secret kept out of logs, the widget on the sign-in form, the CSP opened for Turnstile only, `e2e/turnstile-widget.mjs` in the browser journeys. Stand-ins only; no key exists yet |
| Security and CI (D-084) | `1698082`, `3a829d0` and the status commit | The audit's P0-1: sign-in open redirect (SEC-1), the fake bot check refused on real servers (SEC-2), trusted proxies only for forwarded addresses (SEC-3), security headers (SEC-5), exact-path anti-forgery exemptions (SEC-6); P0-2: Gitleaks, pip-audit, an npm audit gate with a reviewed allow-list, journeys on every code push against Compose, Playwright as a dev dependency, the page-weight check. 997 API tests, 64 web unit tests |
| 10 (web owner) | `b2e11ce`, `1920e55`, the merge `d015261`, `ae10c83`, `326ae26`, `af02d59`, `ffa2720`; second round `822f564`, `751e2b0`, `47e9fec` and the documentation commit; third round `c6b7a29`, `3511e0e`, `8dc0264`, `94d5bd3`, `b4bff76`, `876c1d9` and the documentation commits; see `docs/HANDOFF.md`, Part A.0000 | Reviews and report links for buyers, the shop's replies, `can_edit`/`can_reply` (D-072); thumbnails on the product card (`thumb_url`), the product page gallery, shops' photos, problem evidence (D-074); the rest of the seller dashboard and the application (D-075); then a store with open orders cannot close (D-076), every remaining screen the API supports (D-077) and the settings in Amharic (D-078); `e2e/shop-screens.mjs`, `e2e/seller-dashboard.mjs`, `e2e/setup-and-account.mjs`; then a store's track record on its page and search by rating and seller level (D-080), a worker pass that reports failure (D-079) and the browser journeys on GitHub (D-081). 951 API tests, 33 web unit tests |

## Blueprint phase tracking

Phases are the blueprint's P1 to P16 (section L.1).

| Phase | Name | State |
| --- | --- | --- |
| P1 | Project foundation | **Mostly done.** API skeleton, database pipeline, core helpers, **the web shell, the CI pipeline (`.github/workflows/ci.yml`) and the typed link between API and web** are done. **Containers for a laptop** (`apps/api/Dockerfile`, `infra/compose/compose.yaml`; API, worker, PostgreSQL; D-058) are done and built in CI; the web app is not in the laptop Compose file. **The production stack is prepared and rehearsed, not deployed** (D-091): the web image, `infra/production/` with the reverse proxy, `deploy.sh`, and a rehearsal in CI. The page-weight check runs in CI (D-084). The three technical reports are **not done** |
| P2 (deployment parts) | | See P2 below: the nightly schedule now exists **on the server** (the backup service, D-091); the **off-server copy** does not (F-16) |
| P2 | Database and backend foundation | **Mostly done.** Schema, three database roles, error format, request IDs, structured logs, **the worker process with the scheduler and the outbox dispatcher** are done and tested. **Encrypted backups, a scripted restore and a restore drill run in CI** (D-063); **the watch and reconciliation jobs, alerts with Telegram delivery when configured, and a worker health check** (D-064). **Not done:** error tracking (needs an account), the nightly schedule and the off-server copy (deployment), P2 criteria 3 to 5 (they need staging) |
| P3 | Authentication and roles | **Mostly done on the API side.** Phone-code sign-in, sessions, staff sign-in, Telegram signature check and the permission tables are done and tested. Turnstile is built (D-085, untested against Cloudflare); the SMS side is built up to the provider (D-089) but **no SMS provider is chosen**, so no real code can be sent |
| P4 | Customer storefront | **Mostly done for Release 1's buyer journey** (D-055): home, search with filters, product page with the offers table, shop page, sign-in, cart, checkout, orders, tracking. Pictures on the product card and page, reviews and report links (session ten, D-072, D-074). **Not done:** the category page as its own screen (search by category stands in), account settings and saved addresses screens, Telegram Mini App shell, server actions so changes work without script. (Automated browser tests do run in CI: the browser journeys, on every code push, D-084.) |
| P5 | Product catalogue | **Mostly done on the API side.** Categories, typed attributes, brands, products, variants, translations, staff create/approve/merge/archive, aliases, the restricted-goods list and seller product proposals are done and tested. **The image pipeline** (D-062): upload, metadata removal, WebP in two sizes within the D.26 budgets, rendered by the worker, moderation; criterion 3 is met by automated tests on a laptop. Pictures on the product card and page are shown (D-074). The S3 and R2 bucket adapter exists (D-090, tested against MinIO). **Not done:** seed data, a real bucket and its CDN (F-01, F-15); merging a product that has offers is still refused (see D-026) |
| P6 | Seller onboarding and dashboard | **Done on the API side.** Application, private document upload, staff review queue, verification levels with the checks behind the badge, owner and manager members, store page, payout account, dashboard counts. The web screens (session ten, D-075): application, documents, team, store settings, legal details, payout account, overview. Documents can live in a private S3 or R2 bucket (D-090). **Not done:** share cards and QR code, ownership transfer, closing a shop on the web, the real private bucket itself (F-01) |
| P7 | Seller listings and inventory | **Done on the API side.** Offers, price history, inventory and movements, quick edit, product proposals, the ranked offers list, the check-in, the stale-offer job **now run by the worker**, and a staff takedown that holds (D-032). The web screens: offers with quick edit (session six), add an offer and the shop's own photos (session ten). **Not done:** the seller Telegram bot, product proposals from a seller on the web |
| P8 | Search and product discovery | **Mostly done on the API side.** Search documents kept fresh through the outbox with an hourly rebuild (D-051); normalisation, letter merging and skeleton keys; prefix, sound and trigram matching; filters and sorting; suggestions and "did you mean"; the product-request form; the query log, the zero-result report and the synonym tool (D-052). **Throttled per address** (D-059). **Not done:** the two completion criteria (a golden set of 100 real queries, and timings at real size), "total cost to the door" as a sort, a delivery-speed filter (the rating filter exists: `min_rating`, D-080), edge caching and pages readable by search engines (they need the web app) |
| P9 | Cart and checkout | **Done on the API side, and on the web** (cart and checkout screens, D-055). Server-side cart for visitors and signed-in buyers, delivery choice and fees per store, the priced review step, `place_order` with server re-pricing, stock reservation and idempotency. Criteria 1 to 5 are met by automated tests. **Not done:** the legal disclosure wording (a founder input), and guest checkout as such: a visitor's cart survives signing in, but the order is placed by a signed-in account (see D-036) |
| P10 | Multi-seller orders | **Done on the API side, except the pieces listed.** Parent and seller orders, the state machine enforced by the database, status events, seller confirm and decline, the response deadline and the expiry job, buyer cancellation, notifications, shipments and payment intents; `ready`, `out_for_delivery` (seller or staff), `delivered` with the derived handover code and its five-attempt lockout, `completed` by the buyer or the worker with `commit_stock` and the fee charge, `delivery_failed`, retry, `returned`, the direct payment record, the overdue-hold cancellation. The tracking page by secure link without sign-in. The next-best offer after a decline or an expiry (D-049). Problems on a delivered order: `delivered -> disputed` by the buyer in the window, `disputed -> completed | refunded` by staff, Release 1 form with no money moved (D-050). Criteria 1, 2 and 4 are met by automated tests (`tests/api/test_fulfilment.py`, `tests/api/test_tracking.py`, `tests/api/test_disputes.py`). **Photos on a problem report** (D-062) and **reviews of completed items with the seller's reply** (D-066) exist on the API. The web screens for both, and the problem's messages and evidence photos, exist (session ten). **Not done:** photos on reviews, the bot. Criteria 3 and 5 need the bot and real buyers |
| P11 | Admin operations | **Mostly done on the API side.** The orders desk, problem cases and decisions, seller review, search tools (earlier sessions); **the audit-log viewer, switches and risk limits, staff accounts, the dispatch board, the business dashboard, picture moderation and the operations status** (D-062, D-064, D-065). **Review moderation (AD-12) and the reports queue (AD-16)** too (D-066, D-067). **Data exports for an accountant** (D-068) and **seller performance figures with the weekly message** (D-073). Session nine built their admin screens (D-070 to D-072). The seller's performance screen exists (session ten, D-075). **Not done:** the runbooks, seller statements (Release 2) |
| P12–P16 | Everything else | **Not started** (tables exist; no behaviour) |

## What is built and tested

All of it is in `apps/api`. Test command and result are at the end.

### Core helpers (blueprint P.1 item 5)

- **Money**: whole santim, exact arithmetic, basis-point fees rounded half up,
  "ETB 12,500" and "12,500 ብር" formatting, parsing of typed birr amounts.
- **Phone numbers**: accepts `09`, `07`, `9`, `7`, `+251`, `251` and `00251`
  forms; stores `+2519…`/`+2517…`; rejects everything else.
- **Ethiopic text**: same-sound letter merging (the four blueprint pairs match)
  and consonant skeleton keys ("silk", "selk", "slk" and ስልክ all give `slk`).
- **Order codes**: `MX-` plus six characters with no look-alikes.
- **Time-ordered UUIDs** (version 7), generated in the application.

### Database (blueprint G)

- `infra/postgres/bootstrap.sql` creates the three roles the blueprint requires
  (`markx_migrator`, `markx_app`, `markx_readonly`) and a database using the
  built-in `C.UTF-8` locale. Idempotent.
- Migration `0001`: all **63 tables** for Release 1, with 159 CHECK constraints
  and 81 foreign keys. Every "status" column accepts only its allowed values;
  money and stock columns cannot go negative; the uniqueness rules of G.8 are
  constraints (one offer per seller, variant and condition; one seller order
  per order and seller; one review per order item; and so on).
- Migration `0002`: history tables are append-only (privileges revoked from the
  app role **and** a trigger that refuses UPDATE/DELETE for every role); a
  deferred constraint trigger makes every ledger transaction balance.
- Migration `0003`: fixes a bug in `0002`'s ledger trigger (see "Lessons").
- Migrations `0004` to `0007`: see the migration table at the end.
- Tested: migrations apply from an empty database; models and migrations do
  not differ; trigram matching works on Ethiopic text; no foreign key cascades
  into orders or money.
- Tested by connecting as each role and attacking with plain SQL
  (`tests/db/test_protection.py`): the application role cannot update, delete
  or truncate the audit log, and neither can the schema owner; an unbalanced
  ledger transaction is refused at commit and a balanced one commits; ledger
  entries cannot be changed after they are written; the application role
  cannot change the schema or disable a trigger; the read-only role can read
  business data, write nothing, and cannot read credentials; no MarkX role is
  a superuser. This meets blueprint P2's first completion criterion.
- **The seller order life cycle is a database fact** (migration `0007`,
  tested with plain SQL): a seller order can only be created as `placed`; a
  status change that is not an arrow of the blueprint's G.6 diagram is
  refused by a trigger; and a transaction that changes a status without
  writing the matching `order_status_events` row is refused at commit. A
  test checks that the database's move function and the code's table agree
  on all 196 pairs of states.

### API foundation

- One error format with a code, a translation key and a request ID.
- Request IDs, JSON logs, security headers.
- Anti-forgery guard on every request that changes data (custom header,
  Origin check, and a per-session CSRF token for cookie sessions).
- Health endpoint that reports the database.
- Settings store: feature switches and limits with defaults in code.
- Rate limiting kept in PostgreSQL.

### Sign-in and permissions (blueprint D.2, C, H.2)

- **Sign-in with Telegram (D-101, decision SI-1).** Everyone signs in on
  the website through the bot's one-time link and shares their number with
  Telegram's own button; staff then give their password and authenticator
  code. OFF until the bot exists. SMS is switched off on real servers
  (`MARKX_SMS_PROVIDER=off`); the phone-code sign-in below is kept as the
  backup, with daily shares of the SMS budget (M2) and staff locks per
  address (M3).
- **Phone-code sign-in.** Six-digit code stored only as a keyed hash, five
  minute expiry, five attempts, then a 15-minute lock. Limits per number and
  per network address, a bot-check hook before any SMS, and a daily SMS budget
  that cuts off sending. The account is created at first sign-in.
- **SMS (D-089).** One interface for every sender; the fake (development
  inbox) on laptops and in tests; a provider-independent HTTPS adapter
  (fixed endpoint, 8-second timeout, no redirects, no retries, bounded
  answers, provider-independent error codes, Ethiopian numbers only, GSM-7
  and UCS-2 segment counting) with a placeholder wire format, because no
  provider is chosen. A delivery record per message in `sms_messages`
  (keyed hash of the number, never the text or code). A 60-second resend
  cooldown per number (`otp_resend_too_soon`, `retry_after_seconds`).
  Alerts: `sms.failures` (share failed in the last hour), `sms.unfinished`
  (no final status), alongside `sms.budget`. Staging and production refuse
  to start without a real SMS configuration.
- **Sessions.** Random token, only its hash stored, cookie that scripts cannot
  read, idle and absolute expiry, a new session at every sign-in, sign-out
  everywhere, a notice when another device signs in. A header-based session
  for the Telegram Mini App.
- **Staff sign-in.** Password hashed with Argon2id plus an authenticator code;
  the authenticator secret is encrypted; a used code cannot be replayed; five
  failures lock the account; every attempt is audit-logged; every failure
  looks the same to the caller.
- **Telegram.** Signature and timestamp of Mini App start-up data verified on
  the server; linking one Telegram identity to one account.
- **Connecting Telegram (D-093), OFF by default.** A one-time link
  (`POST /me/telegram/link`: 256-bit token, keyed hash only, ten minutes,
  single-use, bound to the account and session, one pending per account),
  completed by the bot's `/start <token>` through `POST /telegram/webhook`
  (secret header checked before the body is read; update ids deduplicated;
  only `/start` in a private chat from a person acts; rate limits), status
  and disconnect (`GET`/`DELETE /me/telegram`; disconnecting always works).
  Tested with the webhook called as Telegram would call it; **never by
  Telegram**.
- **Permission tables** of blueprint C.3 and C.4, in code, with a test for
  every one of the 140 cells.

### Delivery zones and buyer addresses (blueprint D.13, AD-05, C-08, C-28)

- Staff create zones, neighbourhoods and one flat fee per delivery method per
  zone. Only the super administrator and operations may (blueprint C.4); a
  test covers all five staff roles, a customer, a visitor, and a staff member
  signed in by phone code. Every change is audit-logged with before and after.
- A public, cacheable route lists active zones, areas and fees.
- Buyers save landmark addresses with an optional map pin and second phone.
  Removing one archives it. One buyer cannot see or remove another's address,
  and gets the same "not found" as for an address that does not exist.
- Requests to see, correct or delete personal data.

### Product catalogue (blueprint D.5, D.6, P5)

- A category tree up to three levels, with names in Amharic and English.
- Typed attributes (text, number, list of options), attached to a category as
  required, filterable or variant-defining. A category inherits the attributes
  of the categories above it.
- Products with names and descriptions in both languages, specifications
  checked against the category's rules, and variants. A product with nothing
  to choose gets one default variant, so offers always attach to a variant.
- **The database rejects a duplicate variant** (blueprint P5 criterion): a test
  inserts one with plain SQL and the unique constraint refuses it.
- Staff create, approve, archive and merge products. Only approved products
  have a public page. A merged product keeps its link, which forwards to the
  survivor, and its names become search aliases of the survivor. Merges chain.
- The restricted-goods list blocks a listing whose name or description
  contains a listed word. It matches whole words after the same normalisation
  search uses, so letter case and same-sound Amharic letters cannot slip past.
- Public, briefly cacheable routes for the category tree, a category with its
  filters, brands and a product page, each in the asked language with a
  fallback to the other.
- Permissions follow blueprint C.4 and are tested for all five staff roles.

### Sellers (blueprint D.3, D.4, C.3, C.5, P6)

Code: `markx/sellers/`, `markx/core/storage.py`, `markx/core/images.py`.
Routes: `/seller/...`, `/admin/sellers/...`, `/catalog/stores/{slug}`,
`/documents/{id}/content`.

- **Invitations.** Onboarding is invite-only (setting `sellers.invite_only`).
  Staff invite a phone number; the invitation is used once, by the account
  that owns that number, and expires after 14 days.
- **Application.** A signed-in person opens a draft application (business
  details, TIN, shop address), uploads the four document photos, adds a
  payout account and submits. Staff cannot see a draft. One application at a
  time per person; one live seller per TIN. Individual sellers are switched
  off by a setting, as the blueprint requires.
- **Documents.** Photos only (JPEG, PNG, WebP). The file is decoded and
  written out again, so a file that only claims to be a picture is refused
  and location data is removed. Files go to private storage under an
  unguessable key and are never served by path.
- **Document links.** A link works for five minutes, only for the signed-in
  person it was issued to, and only while that person is still allowed to
  see the document. Issuing a link and every view are written to the audit
  log. (P6 completion criterion 3.)
- **Staff review.** A queue paged by cursor; accept or reject each document;
  ask for more documents; approve at Level 1 or 2; reject with a reason;
  suspend and reinstate; raise or lower the level; sign off the yearly
  re-check. A level is granted only when the accepted, unexpired documents
  behind it exist: Level 2 needs identity, licence, TIN certificate, shop
  photo and a recorded shop visit. Level 3 is given only to a seller already
  at Level 2. A staff member cannot decide about a seller they belong to.
- **Database rules** (migration `0004`): a seller can be `active` or
  `suspended`, or hold a level above 0, only if its application is
  `approved`. A test attacks this with plain SQL.
- **Members.** The owner or a manager adds a manager by phone number; two
  seats on the free plan; the owner can never be removed; a member can
  leave. A removed member loses access on the next request.
- **Store page.** Name, description, policies, hours, areas, Telegram
  channel. The public page exists only for a trading seller and shows the
  level, what was checked and completed orders, and never the phone number.
- **Payout account.** The number is encrypted; only the last four digits are
  ever returned. The first account is active at once; a later change waits
  72 hours and the owner is notified. `activate_due_payout_accounts` applies
  a waiting change, and **the worker now runs it** every five minutes.
- **Seller isolation** (P6 completion criterion 2, blueprint C.5). Tested in
  `tests/api/test_seller_isolation.py`: seller A cannot read or change
  seller B through any route; B's document, member or offer id placed under
  A's own seller id is "not found"; a link signed for B does not open for A;
  another seller's id gives the same answer as an id that does not exist. One
  test walks **every** route under `/seller/{seller_id}` taken from the API
  description, so a route added later is checked without anyone remembering.
  The order routes added this session are covered by it.
- **Staff permissions** (C.4): only the super administrator and operations
  review sellers and open documents; tested for all five staff roles, a
  visitor, a customer, a seller, and a staff member signed in by phone code,
  over every `/admin/sellers` route.

### Offers and inventory (blueprint D.7, G.4, G.9, P7)

Code: `markx/offers/`. Routes: `/seller/{seller_id}/offers...`,
`/seller/{seller_id}/dashboard`, `/seller/{seller_id}/product-proposals`,
`/catalog/products/{slug}/offers`, `/catalog/stores/{slug}/offers`,
`/admin/offers/{id}/remove`, `/admin/offers/{id}/restore`.

- **Offers.** A trading seller attaches an offer to a variant of an approved
  product: price, condition, warranty, delivery options, stock. One offer
  per seller, variant and condition; **the database rejects a duplicate**
  (tested with plain SQL and with 20 simultaneous identical requests).
  Quick edit, pause, resume, remove; a removed offer listed again reuses its
  row so its history is continuous. Used goods need Level 2.
- **A staff takedown holds** (migration `0005`, D-032, found in this
  session's review): a seller cannot relist an offer that staff took down,
  not even by removing it first; a CHECK keeps a held offer `removed`
  whatever the code does; `POST /admin/offers/{id}/restore` lifts the hold.
- **Price history.** Every price change writes a row. Sending the same price
  again counts as confirming it.
- **Inventory.** Stock changes only through `markx/offers/service.py`, and
  every change writes a movement in the same transaction. The seller types
  the counted number; it cannot go below what is held for orders.
- **Stock holds.** `hold_stock`, `release_stock` and `commit_stock` are the
  conditional update of blueprint G.9. **Tested: 100 simultaneous buyers of
  the last unit, exactly one hold.** Checkout now calls `hold_stock` and
  `release_stock`; nothing calls `commit_stock` yet (completion is not built).
- **Ranked offers for a product page.** Only active offers of trading
  sellers at the launch level (`sellers.min_level_to_publish`, default 2).
  Computed on every read, never stored.
- **Freshness.** One-tap check-in confirms all live offers.
  `mark_stale_offers` hides an offer whose price was not confirmed for 14
  days, and **the worker runs it** every hour. The check-in and the job lock
  the rows they change in id order (D-033) and a test races them.
- **Product proposals.** A seller proposes a missing product; it is always
  `pending_review`, whatever the request says, and invisible until staff
  approve it.
- **One seller cannot edit another's offer** (P7 criterion 3): tested on
  every offer route, with the offer id under both seller ids.

### The worker (blueprint F.8, D.16, P2)

Code: `markx/worker/`. Command: `uv run python -m markx.worker` (`--once`
runs the due jobs, handles every due outbox message and exits, with 1 when a
job failed or the outbox could not be drained; D-079, D-082). Decisions
D-034 and D-035. The running worker handles at most 100 messages per pass,
so the jobs keep their times under a backlog, and starts the next pass at
once after a full batch; a pass sends what its own jobs queued (D-082).

- **Scheduled jobs**, one row each in `scheduled_jobs` (migration `0006`):
  `orders.expire_unanswered` every minute, `sellers.activate_due_payout_accounts`
  every five minutes, `offers.mark_stale` every hour. A worker runs a job only
  while holding the row's lock, so two workers never run one job at once; a
  dead worker leaves the job due; a job that raises loses only its own work
  and is retried after 1, 2, 4 ... 60 minutes; three failures in a row are
  logged at CRITICAL.
- **The outbox dispatcher.** One row per transaction, claimed with
  `FOR UPDATE SKIP LOCKED`; a handler that raises is retried after 30 s, 1,
  2, 4 ... minutes up to an hour and given up after 8 attempts; a worker that
  dies mid-row leaves it pending and untouched; one bad row never blocks the
  rest. `notify.push` carries an in-app notification to Telegram (when
  linked) and, for order alerts while the switch is on, to SMS, with an
  explicit delivery record per channel (D-092). **No real channel is
  connected**: on a real server the push factory returns no sender and the
  delivery is recorded `unavailable` without an error (before D-092 it
  raised, and each message was retried and given up).
- Tested (25 tests, `tests/worker/test_worker.py`): a committed message is
  delivered exactly once and one from a rolled-back transaction never (P2
  completion criterion 2); retries with growing delays; two workers never
  take the same row or run the same job; eight workers deliver 120 messages
  exactly once; a crash mid-row or mid-job loses nothing; a failing handler
  or job stops nothing else. Every test calls the worker's own loop with a
  clock it controls; nothing sleeps.

### Cart, checkout and orders (blueprint D.10, D.11, G.5 to G.7, P9, P10)

Code: `markx/orders/`, `markx/payments/ledger.py`. Routes: `/cart...`,
`/checkout/quote`, `/checkout`, `/me/orders...`,
`/seller/{seller_id}/orders...`, `/admin/orders...`, `/track/{order_id}`.
Decisions D-036 to D-050.

- **The cart** lives on the server. A visitor's cart is found by a secret in
  an `HttpOnly` cookie (only its hash is stored); it moves into the person's
  own cart when they sign in. A line records the offer, the quantity and the
  price the buyer saw. Reading the cart re-checks every line against live
  data and says what changed: a new price, an item out of stock, an offer or
  seller no longer available. An offer buyers cannot see on the product page
  cannot be put in a cart either. Up to 30 lines, 20 units each.
- **The review step** (`POST /checkout/quote`) prices the cart for one
  address and one delivery choice per store, all from the database: item
  totals, the fee for the chosen method into the buyer's zone, the grand
  total, and who the buyer is buying from (legal name, shop address, return
  policy). A method is offered only if every line from that store supports
  it, because a seller order travels as one shipment.
- **`place_order`** (`POST /checkout`) runs in one transaction, exactly as
  G.5 lists: the buyer's cart row is the lock; the same idempotency key
  returns the same order; every offer is re-read with its seller under a
  lock; the price in the cart must equal the live price (else
  `price_changed`) and the total the buyer saw must equal the recomputed one
  (else `total_changed`); a member of a store cannot buy from it; the open
  order cap and the largest order value apply; stock is held **in ascending
  offer id order** with one `inventory_reservations` row per line, and one
  line short rolls everything back with the offer named (`out_of_stock`);
  then the parent order with its address snapshot, one seller order per
  seller with its own totals and response deadline, the order items with
  their own copy of the title in both languages, the variant label, the
  price and the commission rate in force, a shipment and a payment intent
  per seller order, a `placed` event per seller order, and a notification
  for every seller's order handlers and for the buyer. The cart is emptied.
- **The seller's side.** `GET /seller/{id}/orders` lists one seller's parts
  of orders, newest first with a cursor, and never another seller's lines or
  the buyer's grand total. Confirm or decline, only by a member whose role
  handles orders, only while `placed` and inside the response window. A
  decline needs a reason and gives the stock back. The seller sees the fee
  in birr before confirming.
- **The buyer's side.** `GET /me/orders` and the order page, with the
  parent's status derived from the seller orders on every read. The buyer
  cancels one seller's part while it is `placed` or `confirmed`; the stock
  returns and the seller is told.
- **Phone numbers** appear on each side only after the seller confirms, and
  disappear again if the part ends undelivered (blueprint C.5).
- **The response deadline** counts business hours in Addis Ababa time
  (settings `orders.response_window_minutes`, `orders.business_open_hour`,
  `orders.business_close_hour`): an order placed at night is due half an
  hour after the shops open. **The worker expires unanswered orders** every
  minute and releases their stock; a late seller never blocks the others.
- **Commission.** The most specific rule in force (seller, plan, category,
  default) is copied onto each line as basis points. No rule exists today,
  so every line carries 0, which is what blueprint D.19 says for direct
  orders in year one. Rules can only be inserted by hand; the admin routes
  belong to P11.
- **Tested** (`tests/api/test_cart.py`, `tests/api/test_checkout.py`,
  `tests/db/test_checkout_contention.py`, `tests/unit/test_order_rules.py`):
  the five P9 completion criteria, including **100 simultaneous checkouts of
  the last unit create exactly one order** and **fifty buyers competing for
  ten units get exactly ten**; a lowered total and a stale cart price are
  refused; the same submission twice creates one order and another buyer's
  identical key does not return it; a two-seller order, every row it writes,
  the moves each part makes on its own and the parent's derived status; every
  status change is in the log and a move outside the diagram is refused by
  both layers; the line keeps its copy when the product is renamed, the
  price changed and the offer removed; the commission rule lookup; delivery
  choices; limits; who may answer; the deadline; buyer cancellation; one
  buyer never sees another's order and one seller never sees another's
  part; the buyer's phone is hidden until confirmation. Contention: checkout
  raced against the seller's price edits and stock counts, and confirm,
  decline, cancel and expiry raced for one order, with the stock released
  at most once.
- **Fulfilment (session four).** Seller routes under
  `/seller/{seller_id}/orders/{id}/`: `ready`, `dispatch` (rider name and
  phone, optional), `handover` (the buyer's code), `delivery-failed`,
  `return`, `payment`. Buyer: `confirm-received`. Staff: `GET
  /admin/orders/{code}` (`find_orders`), `POST
  /admin/orders/seller-orders/{id}/dispatch` and `/reissue-code`
  (`intervene_in_orders`, audit-logged). Every shipment change writes a
  tracking event; the buyer's page shows the shipment timeline, the rider's
  name and phone once dispatched, and the handover code from `ready` until
  the handover; the seller's page shows attempts left and, once completed,
  the fee charged. Worker jobs: `orders.complete_after_problem_window`
  (five minutes) and `orders.cancel_overdue_fulfilment` (ten minutes,
  D-043, provisional). Completion is the only caller of `commit_stock` and
  writes `fee_charges`, with a balanced ledger posting when the fee is above
  zero. Tests (`tests/api/test_fulfilment.py`, 10;
  `tests/db/test_fulfilment_contention.py`, 4): a two-seller order placed to
  completed with both delivery modes (P10 criterion 1); five wrong codes lock
  the shipment, the right code is then refused, staff reissue and the old
  code is dead; the code never appears in a seller or staff response, nor in
  any shipment column; a failed delivery retried and returned, stock back,
  intent cancelled; out-of-order moves refused; staff dispatch and who may
  intervene; the payment recorded once with the audit row; a 3% rule charged
  at completion and posted as a balanced debit and credit; an overdue hold
  cancelled by the worker while a dispatched parcel is left alone; the stock
  trail replays exactly after every path. Contention: the right code, a
  failed handover, a return and the hold job racing for one parcel; the
  buyer, the worker and the payment record racing to complete; twenty wrong
  codes at once counting exactly five; the worker's cancellation racing the
  seller's dispatch.
- **The tracking page by secure link (D.14, D-048).** `GET
  /track/{order_id}?expires=&signature=` without sign-in: a 256-bit
  signature over the order id and a sixty-day expiry, one `404` for a forged,
  expired or retargeted link. The page is the buyer's view minus the
  handover code, the recipient's name, phones, pin and notes, and the
  actions; the seller's and rider's contact appear under the usual rules.
  The "placed" notification carries the path for the Telegram or SMS
  message; the signed-in page carries a fresh one; staff and sellers get
  none. Tests (`tests/api/test_tracking.py`, 2): the page before and after
  dispatch, in both languages, with the code shown on the signed-in page
  and absent here; a forged signature, a shifted expiry, another order's
  signature, an unknown order, a missing parameter, a link sixty-one days
  old, a link that claims to live too long.

- **Review fix (session five).** `_release_everything` cancelled waiting
  shipments with a bulk `UPDATE` and no tracking event, on decline, buyer
  cancellation, expiry and the overdue-hold job: four paths broke "every
  shipment change writes its event" (J.10). It now locks those shipments in
  id order (after the seller orders, before the stock) and cancels each
  through `_track`. Test: `test_every_cancelled_shipment_has_its_tracking_event`,
  which failed on the old code (an empty trail) and passes now.
- **The next-best offer (C-26, D-049).** On a decline or an expiry the buyer
  gets one `order.next_best_offer` notification per line that has an
  alternative: the best offer in stock for the same variant from another
  seller, by the product page's own ranking for the buyer's zone. `GET
  /me/orders/{order_id}/seller-orders/{id}/alternatives` reads it live.
  Nothing is reserved; the buyer buys through the normal checkout. Tests
  (`tests/api/test_next_best_offer.py`, 5): Beta declines and Alpha is
  suggested; Alpha stays silent and Beta is suggested; nothing when no other
  seller has the variant or the other offer is out of stock; another buyer
  gets 404 and a visitor 401.
- **Problems on a delivered order (D.17, G.6, G.7, D-050).** Buyer: `POST
  /me/orders/{order_id}/seller-orders/{id}/problem` (type and description,
  only while `delivered` and inside the window) and `.../problem/messages`.
  Seller: `POST /seller/{seller_id}/orders/{id}/problem/reply`. Staff with
  `handle_cases`: `GET /admin/orders/problems` (the queue, most urgent
  first) and `POST /admin/orders/seller-orders/{id}/resolve-problem`
  (`no_action` completes the part with stock committed and fee charged;
  `seller_refunded` marks it `refunded`, no fee, stock back on sale if
  `goods_returned`, otherwise off the count). A written reason always, an
  audit row always. The buyer's and the seller's pages carry the case and
  its messages by role; the tracking link shows only the status. Setting
  `orders.problem_decision_hours` (48). Tests (`tests/api/test_disputes.py`,
  5; `tests/db/test_dispute_contention.py`, 2): a report stops the worker's
  completion; both sides add their account; support decides; refunds with
  and without the goods returned, with the stock trail replaying exactly and
  nothing in the ledger; who may report, reply and decide (another buyer,
  another seller, finance and catalogue staff all refused); no report after
  the window. Contention: a report racing the buyer's "received" and the
  worker's completion (exactly one wins); two staff decisions and a seller
  reply racing on one case (exactly one decision, stock settled once, no
  message after the decision).

### Search (blueprint D.8, F.7, AD-07, P8)

Code: `markx/search/`. Routes: `GET /search`, `GET /search/suggest`, `POST
/product-requests`, `/admin/search/zero-results`, `/admin/search/synonyms`.
Decisions D-051 and D-052.

- **Documents.** One per approved product: names in both languages, brand,
  model, model codes, aliases and category names, normalised; the `simple`
  full-text vector; skeleton keys; category path, brand, facets (condition of
  in-stock offers, specs and variant attributes); the lowest in-stock price,
  offer and seller counts, in stock, best seller level, freshest price,
  popularity. Rebuilt through the outbox in the transaction that made the
  change (a flush listener for ORM changes, explicit calls for Core
  statements, stock only when an offer goes in or out of stock), and all of
  them hourly by the worker.
- **Queries.** Normalised like documents, expanded by synonyms, matched by
  words (prefix), sound (skeleton keys) or letters (trigrams, every word),
  ranked by match tier, stock, freshness, seller level, price, popularity.
  Filters: category with its sub-categories, brand, condition, price range,
  seller level, in stock. Sorts: relevance, price, freshness. Every first
  page logged with its count. "Did you mean" when nothing matches.
- **Tests** (`tests/api/test_search_index.py`, 6; `tests/api/test_search.py`,
  26): the document holds what a buyer can find; stock crossing zero moves
  the lowest price (and a purchase that does not empty an offer queues
  nothing); a price change, a pause and a seller suspension reach it; the
  stale job's bulk update and the bulk check-in reach it; a rename, an alias
  added and removed, and an archive reach it; the hourly rebuild repairs a
  missing document and is safe to run twice. Thirteen spellings find the
  Samsung (English, Amharic script with two vowel spellings, Latin-letter
  Amharic, no vowels, a model code, a typo only trigrams catch) and six find
  the Tecno; results are products with the card's facts; a draft is never
  found; every filter; ranking and both sorts; the query log and the
  zero-result report with its permission; "did you mean" and suggestions;
  synonyms for a whole query and for one word, with their refusals,
  permission and audit rows; the product-request form with its phone check
  and its hourly limit.

### The web app (blueprint F.1, I, P4; D-055)

Code: `apps/web`. One Next.js 16 app in strict TypeScript with Tailwind 4;
every page under `/am` or `/en`; all text in `messages/am.json` and
`messages/en.json`. Pages read the API on the server with the visitor's
cookies and never cache; changes go from the browser to `/api` on the same
origin, so the API's cookies, CSRF token and origin check apply unchanged.
API types are generated from the API's OpenAPI description.

- **Storefront:** home (search, categories, popular products, protection),
  search (filters, sorting, paging as GET forms; "did you mean"; the
  product-request form), product (versions, the offers table for the chosen
  area with delivery and total, each price's age, the seller's level, the
  best offer and why, add to cart, specifications), shop page (level and
  what was checked, member since, completed orders, offers).
- **Buyer:** sign-in by phone and code, account and sign-out, cart (groups
  by shop, quantities, price changes, unavailable lines), checkout in four
  steps (address, delivery per shop, payment, the server's priced review
  with each seller's legal details), orders and the order page (status per
  shop, the handover code and its warning, contacts, timeline, cancel,
  "the goods are right", "report a problem"), the tracking page by link.
- **Tested:** `npm run lint`, `npm run typecheck` (strict), `npm test`
  (9 Vitest tests: price and time formatting, message keys and
  placeholders equal in both languages, API errors always in words) and
  `npm run build`, all in CI. `e2e/buyer-journey.mjs` drives the whole
  journey in Chromium against the demo data, the buyer's side and the shop's
  side through their screens (including a wrong handover code), and passed
  on 17 November 2026
  (not in CI: it needs a running API with demo data). Checked by hand at
  320, 360, 768 and 1280 pixels: no page is wider than the screen.
- **Seller dashboard** (`[lang]/seller/{seller}`): the order inbox by stage
  with the answer countdown and the payout after the fee; the order page
  with accept, decline with a reason, mark as packed, send with a rider,
  enter the buyer's code (attempts left; lockout), delivery failed, goods
  back on the shelf, record the payment, answer a problem; offers with
  counts, one-tap "still right", in-place price and stock edits, pause and
  resume. Seller isolation stays the API's: every call is checked by
  `require_seller`.
- **Admin dashboard** (`[lang]/admin`): staff sign-in with password and
  authenticator; a side menu showing only what the role may do (C.4); the
  problem queue (overdue marked); the orders desk (any order by code, full
  timelines, decide a problem, dispatch, a new handover code); seller
  applications (documents through five-minute links, accept or reject each,
  approve, ask again, reject); search tools (zero results, synonyms).
  `e2e/staff-journey.mjs` runs a problem from the buyer's report to the
  staff decision and checks isolation at both layers (another shop's
  dashboard and API: 404; the admin area and API for a buyer: 403).
- **Admin queues added in session nine** (D-070): product proposals
  (approve, turn down with a note, merge into an approved product),
  invitations (invite a phone number, withdraw an open one), listing
  takedowns (find a product's live offers by its link name, take one down
  with a reason, the queue of held listings with the reason, lift a hold;
  D-069), and the audit trail over D-065's viewer (filters by kind of
  record, record, action or a family of actions; "older entries"). The menu
  comes from one table of queues and the capability that opens each; the
  admin home sends each role to its first queue; roles, review states,
  seller, document and product statuses are shown in words in both
  languages; a page the API refuses says so.
- **The rest of the admin screens** (D-071): the dashboard (the API's figures
  for 1, 7, 30 or 90 days), the dispatch board (late parts marked, each
  opening in the orders desk), operations (open alerts, scheduled jobs, the
  outbox), reviews (held first; publish or hide with a reason), reports
  (acted on or dismissed with a note), settings (each row changeable only if
  the API says so), staff accounts (create — the authenticator secret shown
  once — change a role, switch off), exports (four CSV files; a refused
  period shown in words) and pictures (every state with its thumbnail;
  upload, take down). `menu.test.ts` checks the exact screens of each of the
  five staff roles.
- `e2e/admin-queues.mjs` drives all of it in Chromium against the demo data:
  15 steps, "console errors: none": proposals, invitations, a takedown lifted and relisted, the audit trail in English and Amharic, a rider order on the dispatch board, the dashboard, operations, a held review published, a report dismissed, a setting changed and restored, a staff account created (its shown secret signs it in), re-roled and switched off, an export downloaded and a reversed period refused, a picture uploaded, rendered and taken down, every page at 360 px, and a catalogue curator who sees only its six screens.
- **Reviews and reports** (session ten, D-072): the product and shop pages
  show the API's rating totals and published reviews, ten at a time; the
  buyer rates an item on the order page while the API lists it as waiting,
  and keeps every review on `/reviews` with its state, MarkX's reason if
  hidden, the shop's reply, and a change form while the API says
  `can_edit`; the shop answers on its Reviews screen where the API says
  `can_reply`. A report link sits on every product, listing, shop and
  review, for anyone. `MyReviewOut` gained `can_edit` and `can_reply`
  (both sides in one commit).
- **Pictures** (session ten, D-074): the product card carries the first
  ready catalogue thumbnail (`ProductCardOut.thumb_url`, both sides); the
  product page shows the catalogue pictures and "Photos from shops"; a shop
  manages its own photos of each product it sells (upload, withdraw); the
  evidence photos on a problem are on the buyer's order page, the shop's
  order page and the orders desk, with uploads while the problem is open,
  and the buyer can add messages to it. Message authors are in words.
- **The rest of the seller dashboard** (session ten, D-075): an overview
  (shop and application state, what is missing, send for review, what MarkX
  checked, every screen of the role), performance (the API's figures for 7,
  30 or 90 days and the weekly messages, D-073), add an offer from the
  catalogue, store settings, team, documents behind signed links, legal
  details, payout account; and the application form on `/seller` for an
  invited person. The seller menu follows the member's capabilities
  (`seller/[sellerId]/menu.test.ts`, per role of C.3).
- `e2e/shop-screens.mjs` (14 steps) and `e2e/seller-dashboard.mjs` (11
  steps) drive all of it in Chromium against the demo data, "console
  errors: none": a purchase rated, changed, shown on both pages, answered
  by the shop and then fixed; reports signed in and out, a second one
  refused in words; a shop's photo rendered, shown and withdrawn; a problem
  with a message and photos from both sides, seen by staff and decided; a
  catalogue picture on the product page and the product card; and a new
  invited phone taken from application to an approved shop with its store
  settings on the public page, a manager added and removed, an offer
  published and the performance page. Every page at 360 px in both
  languages.
- **Demo data:** `apps/api/scripts/seed_demo.py` (D-056), laptop only.
- **Third round** (D-079 to D-081): a store page's track record (accepts
  share, typical time to accept, delivery success over 90 days), search by
  rating and seller level, a single worker pass that reports failure in its
  exit code, and the browser journeys on GitHub when asked.
- **The remaining screens** (session ten, second round, D-077): the buyer's
  account (`/account`: name and language, saved addresses, messages from
  MarkX in words, data requests, sign out on every device), the next-best
  offer on a declined or expired part, the category page (`/c/{slug}`),
  search suggestions; the shop's location with a map link, closing the shop
  (refused while orders are in progress, D-076), suggesting a product; for
  staff a shop's level and standing, delivery zones with areas and fees,
  catalogue setup and the products screens. `e2e/setup-and-account.mjs` (13
  steps) drives them all. The settings screen shows Amharic descriptions on
  the Amharic page (D-078).
- **Known gaps:** the Mini App (`/auth/telegram`, `/me/telegram`) waits for
  the bot; website sign-in with Telegram is built (D-101) and waits for it
  too. Variant
  labels ("Black · 128 GB") come from the API in the cart, the seller's
  offers and the shop's price list, built by the same code as the product
  page (`catalog.selectors.variant_labels`).

### CI (blueprint P1)

`.github/workflows/ci.yml`, on every push and pull request, on GitHub's
hosted runners: the API job (PostgreSQL 17 service, ruff, ruff format,
strict mypy, migrations with `alembic check`, the whole suite in one
session, and a check that the web app's copy of the API description is
current) and the web job (lint, strict types, unit tests, production
build, and a check that the generated API types are current). First runs:
#1 to #4 passed.

**Since D-084:** a `security` job (Gitleaks, pip-audit, the npm audit
gate) runs with the others, the containers job also checks the CI Compose
override and that the image starts uvicorn with `--no-proxy-headers`, and
`journeys.yml` runs the page-weight check and all six journeys on **every
pull request and every push to `main` that changes `apps/`, `infra/` or the
workflow, and by hand on any branch (D-097)**, against PostgreSQL,
the migrations and the API from Compose. The history below describes D-081.

`.github/workflows/journeys.yml` (D-081) runs the six browser journeys in
Chromium against a fresh demo database, only on a push whose message
contains `[journeys]` (or, once on the default branch, from the Actions
tab). It raises the sign-in limits on its throwaway database, keeps the
screenshots and server logs for a week. Its first tagged run (#2) was
cancelled by the next ordinary push (fixed: see D-081). Run #4 on `b4bff76`
passed in five minutes: all six journeys, each with "console errors:
none". Run #5 on `876c1d9` (the buyer and staff journeys now fail on a
console error, like the other four) passed too, in seven minutes. GitHub warns that the
actions it uses (`checkout`, `setup-node`, `upload-artifact`, `setup-uv`)
target Node.js 20 and are forced onto Node.js 24; a warning only, the same
in `ci.yml`.

### Security and CI session (D-084)

What it changed, in plain words:

- **SEC-1 (high), fixed.** A sign-in link could send a person to another
  website after signing in (`/sign-in?next=/\evil.example`). One helper,
  `apps/web/src/lib/safe-next.ts`, now allows only paths on MarkX, used by
  `sign-in/page.tsx` and checked again in `SignInForm.tsx`. 31 unit tests.
- **SEC-2 (high), fixed.** The pretend bot check accepted anything, on every
  server. Staging and production now refuse to start with it, and refuse
  every sign-in code if they somehow run with it (`core/botcheck.py`,
  `core/config.py`). **A real bot check (Turnstile) must be built before any
  real server can start.**
- **SEC-3 (medium), fixed.** Visitors' addresses behind a proxy: only proxies
  listed in `MARKX_TRUSTED_PROXIES` are believed (`core/http.py`,
  `core/config.py`, `Dockerfile` with `--no-proxy-headers`), so rate limits
  count each real visitor and nobody can pick their own address.
- **SEC-5 (medium), fixed where safe.** Content Security Policy and the usual
  headers on API responses and web pages (`core/http.py`, `next.config.ts`);
  HSTS on real servers only. Inline scripts are still allowed in the web
  CSP (Next.js needs them without per-request nonces): open.
- **SEC-6 (low), fixed.** Anti-forgery exemptions by exact path; none today.
- **CI.** A `security` job (Gitleaks over all history, pip-audit, an npm
  audit gate), journeys on every code push against Compose, and the
  page-weight check. Details and the reasoning: D-084. Since D-097 the
  journeys run on pull requests and pushes to `main` that change code, and
  by hand.

### The search evaluator (P8 criteria; D-054)

`uv run python -m markx.search.evaluation FILE.csv` scores real queries
against the real search and writes nothing. The template is
`apps/api/search_eval/golden_queries.template.csv`. Tests
(`tests/api/test_search_evaluation.py`, 5) use a file marked SYNTHETIC.
**No real query exists yet; the 85% target is not measured.**

### Eighth session: back end only (D-059 to D-065)

All of it under `apps/api` and `infra/`; `apps/web` was not modified.

- **Search throttle** (D-059): `/search` and `/search/suggest` count each
  request per network address and minute (settings
  `search.requests_per_ip_per_minute` 120, `search.suggestions_per_ip_per_minute`
  300); past the limit, 429 before the search runs, so nothing is logged.
- **The completion job completes each order on its own** (D-060): one
  savepoint per order, commit-time checks forced inside it; a failing order
  stays delivered and is retried, the rest complete.
- **API description** (D-061): `apps/api/openapi.json` is checked exactly;
  the web app's copy must stay true for everything it has, and may lag
  behind additions (`scripts/check_openapi_copy.py`). It caught a schema-name
  clash in this session before it reached CI.
- **Pictures** (D-062, `markx/images/`): catalogue pictures (staff) and real
  photos (sellers with an offer), cleaned at upload, rendered by the worker
  to WebP in two sizes within 30 KB and 150 KB, no metadata, moderation by
  staff; problem photos for both sides of an open problem, private, by
  five-minute link, append-only.
- **Backups** (D-063, `infra/backup/`): replaced by D-094 (below); only
  `restore-legacy-cbc.sh` remains, for dumps in the retired format.
- **Monitoring** (D-064, `markx/ops/`): `ops.watch` every five minutes and
  `ops.reconcile` daily; alerts open, persist and resolve once each, through
  the outbox, to Telegram when configured; `GET /healthz/worker` for an
  outside monitor; `GET /admin/ops/status` and `/admin/ops/alerts`.
- **Admin back end** (D-065, `markx/admin/`): the audit-log viewer, settings
  and risk limits, staff accounts, the dispatch board, the business
  dashboard.
- **Reviews and ratings** (D-066, `markx/reviews/`): one review per item of
  a completed order, by its buyer, within 60 days; suspicious ones held for
  staff; the seller's reply; staff moderation; public product and store
  review pages; rating totals per product and seller, recounted through the
  outbox and daily.
- **Reports** (D-067, `markx/reports/`): anyone flags a product, offer,
  store or review they can see; one open report per person and target;
  the staff queue; resolution as actioned or dismissed with a note, for
  every report on a target at once; reporters told the outcome.
- **Data exports** (D-068, `markx/exports/`): four CSV files for an
  accountant (fees, ledger, seller orders without buyer data, seller
  balances), whole Addis Ababa days, exact amounts, formula-safe,
  audit-logged; super administrator and finance only.
- **Seller performance** (D-073, `markx/performance/`): the performance page
  in numbers for every store member, and the weekly message: an hourly job
  stores each trading store's figures for the last Monday-to-Sunday week
  once and tells its members.

### Backups and disaster recovery (D-094)

`apps/api/markx/backup/`, `python -m markx.backup`; procedures in
`docs/runbooks/backup-and-restore.md`. **Tested** locally and in CI against
PostgreSQL 17 and MinIO; **not connected** to any real destination.

- **Backup sets**: lock (advisory and file), exported snapshot, `pg_dump
  --snapshot` checked by exit status, archive signature and `pg_restore
  --list` against the snapshot's tables; row counts and file references
  from the same snapshot; every object of both buckets, after the
  snapshot, unchanged ones skipped, equal ones stored once; every upload
  read back and hashed; the signed manifest last. A missing referenced file
  makes the set `incomplete`. Failures keep the last good set and the
  evidence; retries; a dead run is marked `abandoned`.
- **Encryption** MXB2 (X25519, HKDF-SHA256, AES-256-GCM STREAM) and
  Ed25519 manifests; four key files from `keygen`; the recovery key never on
  the server (`deploy.sh check` refuses it).
- **Restore** into a new database and empty, non-live stores; verified
  before (signature, hashes, a full decryption) and after (migration
  version, row counts, indexes and constraints, audit protection, every
  file's checksum, every reference, the private target's privacy).
- **Drill** with seven injected faults; CI keeps its report (artifact
  `restore-drill`).
- **Retention**: founder-set; the newest complete set always kept; only
  signed sets trusted; blobs after 48 hours and only when unneeded. Since
  D-096 never on the server: `prune` with its own key, every version
  removed, what a lock holds left.
- **D-096 hardening** (branch `claude/markx-backup-trust-hardening-4mmhxz`):
  no delete from the server, object lock required on staging and
  production, verified blob reuse (the blob ledger), drills and restores
  only on a throwaway recovery machine, restores as the owner role, no
  password reset; least-privilege MinIO users in tests and CI. See the
  section at the top of this file.
- **Monitoring**: `backup_runs` (migration `0018`, read-only for the
  application role) and the watch's `backup.failed`, `backup.incomplete`,
  `backup.stale`, `backup.drill_failed`, `backup.drill_overdue` on staging
  and production.
- **Deployment**: the `backup` image stage, the Compose service, `deploy.sh`
  (a set before every migration), the rehearsal's checks and drill.

## What exists but is NOT tested

Be careful with these. They were written and never exercised.

- **Everything in `infra/production/` against a real server** (D-091). The
  Compose file, nginx, `deploy.sh` and the backup service run only in the
  local rehearsal, with `MARKX_ENV=local`, MinIO and a self-signed
  certificate. Never with a real certificate, real DNS, real buckets, a real
  SMS provider or Turnstile's production widget, never for more than one
  rehearsal's minutes (the nightly schedule has not waited for a night),
  never under real load (the memory limits are estimates for a 2 GB
  server), and never from Ethiopia. The staging/production configuration
  rules are tested in unit tests and by the rehearsal's refusals only.
- `docs/runbooks/` procedures that cannot be rehearsed: preparing a server,
  the certificate (no tool is installed; the deploy hook named in
  `tls-certificates.md` does not exist yet), recovering a lost server,
  secret rotation, the monthly drill on a real recovery machine against a
  real bucket (D-096: drills no longer run on a server).
- **Backups against a real provider** (D-094): every backup, restore and
  drill test used MinIO. The `s3` and `r2` paths of the backup destination
  share the storage adapter's client code, but no set has ever been written
  to Amazon S3 or Cloudflare R2, no real key exists, no backup schedule has
  run for a night, and the four-hour restore target has not been measured
  on real data volumes. Alerts are generated, but no person receives them
  until the alert group exists (F-18).

- The analytics model (`analytics_events`): the table exists and is
  constrained; **no service, route or test uses it**. (Corrected on 19
  November 2026: there are **no** `refunds` or `payouts` tables, and
  reviews and reports are in use since D-066 and D-067.)
  `product_requests` are written and never read by a route yet.
- `fee_charges.reversal_ledger_transaction_id` and `reversed_at`: unused.
  Release 1 never charges a fee on a refunded part, so nothing is reversed
  (D-050).
- Refunds, payouts and provider webhooks: **no table exists** for any of
  them (corrected on 19 November 2026; they are Release 2 work). Only
  `seller_payout_accounts` exists, for a seller's payout account details.
- `stores.logo_key`, `order_items.image_key`: columns with no behaviour.
  (Earlier versions of this list named `offer_price_tiers` and
  `seller_metrics_daily`; neither table exists in the schema. D-073.)
- `TelegramAlertSender` is tested against a stand-in for Telegram's API,
  never against Telegram itself (no bot or group exists yet).
- **The Telegram linking webhook** (D-093) is tested by calling it the way
  Telegram would, with test-only values, in the API tests and the browser
  journey; **Telegram has never called it** and no webhook is registered.
  The reply carried in the webhook response, and the update shapes, follow
  the Bot API as known when written.
- **The `s3` and `r2` storage adapters** (D-090) are tested against MinIO,
  which speaks the same S3 API, and their configuration (endpoint, region,
  addressing, encryption header) is checked without a network; **they have
  never talked to Amazon S3 or Cloudflare R2**: no account or bucket exists
  (F-01). R2's acceptance of the exact requests MarkX sends (Content-MD5, no
  newer checksums, no encryption header) is taken from its S3 compatibility,
  not tested.
- `commission_rules`: read by checkout, never written by any route.

## What does not exist

- The Telegram bot itself (the founder creates it). Signing in with
  Telegram (D-101) and connecting Telegram (D-093) are built and switched
  off until it exists.
  Every other route a person uses has its screen (D-070 to D-078); the
  remaining unused routes are the development SMS inbox, the health checks
  and the file links the API hands out.
- Photos on reviews, ratings on product cards and in search, payments beyond the direct payment record
  (Release 2: Protected prepay, refunds through a provider, payouts).
- Ownership transfer between seller members (needs the founder's decision,
  F-02).
- Store logo upload, share cards, QR code.
- The seller Telegram bot. The Bot API push adapter exists (D-092) but has
  never talked to Telegram; a real server uses no push provider and records
  every Telegram delivery `unavailable`. No SMS provider, so notification
  SMS (also off by default) cannot go out either. Delivery reports
  (webhooks) for either channel.
- A real private bucket for documents and a public one for pictures (F-01):
  the S3 and R2 adapters exist (D-090) and a real server refuses to start
  without one, but no account or bucket has been created. A real SMS
  provider: the adapter exists but speaks only MarkX's placeholder format
  until a provider is chosen (F-11) and its wire format written (D-089). No
  delivery-report webhook. The
  bot-check adapter (Turnstile) **exists but has never talked to
  Cloudflare**: it waits for the founder's keys (D-085). Until they are
  configured a real server refuses to start (D-084).
- Any deployed server. The reverse proxy, the production Compose file and
  the nightly backup schedule now exist **in the repository** (D-091) and
  are rehearsed locally; none of it runs anywhere.
- Error tracking (F-18), an outside uptime monitor (F-18), **a connected
  off-server backup destination** (F-16; the code exists, D-094), the
  recovery key's keeper (F-19) and the retention (F-20), the site's domain
  and certificate (F-17), the buckets themselves (F-01), versioning of the
  live buckets between nightly sets (F-14) and the pictures' CDN and domain
  (F-15). The weekly copy to the founder's drive. Zero-downtime
  deploys. A container registry. The server's firewall, updates and the
  spending alarm (host set-up, blueprint M.3). A tool to re-encrypt data
  under a new `MARKX_ENCRYPTION_KEY` (`docs/runbooks/secret-rotation.md`).
- Anything on AWS. Nothing has been deployed and no cloud resource was created.

## Lessons

- **Untested code was wrong.** Migration `0002` shipped a ledger trigger that
  made every ledger insert fail. It applied cleanly and looked correct. The
  first test that inserted a ledger row found it. Treat every item under
  "exists but is NOT tested" as probably broken until a test says otherwise.
- **A race test found a deadlock that no single-request test could.**
  Editing an offer locked the offer row with `FOR UPDATE` and then the stock
  row; a buyer's hold locked the stock row and then, through the movement's
  foreign key, needed the offer row. Under 60 threads PostgreSQL killed one
  of them. Offer and seller rows are now locked with `FOR NO KEY UPDATE`
  (D-027). Write a contention test for every operation that takes two locks.
- **`now()` is the transaction's start time.** Two stock movements written
  by one transaction had the same `created_at`, so their order was a coin
  toss. Movements and status events are stamped with `clock_timestamp()`
  (D-028).
- **A review of working code found a real hole.** The relist path of
  `create_offer` was correct for a seller's own removal and wrong for a staff
  takedown; the existing tests covered each half and never the two together
  (D-032). When reviewing, look for two correct features that compose into
  one wrong one.
- **`INSERT ... ON CONFLICT DO NOTHING` waits.** It blocks behind a
  transaction that holds the conflicting row, so a worker that "registered"
  its job inside the job's own transaction made a second worker wait for the
  whole run instead of skipping it (D-035).
- **A bulk `UPDATE` locks rows in plan order.** Two of them over the same rows
  can deadlock. Select the ids `ORDER BY id FOR NO KEY UPDATE` first (D-033).
- **If the page needs to know whether someone may act, ask the API.** The
  review edit form would have needed the service's window and reply rules
  copied into the page; two booleans in the response (D-072) keep the rule
  in one place and are tested against the service's own refusals.
- **A browser journey's own `fetch` obeys `Cache-Control`.** The public
  picture list is `max-age=60`, so a check right after an upload read the
  old list. Journeys call the API with `cache: 'no-store'`.
- **`role="alert"` is not only yours.** Next.js's route announcer has it
  too; wait for the form's own message (`form [role=alert]`).
- **Make every browser journey repeatable and self-cleaning:** tag what a
  run writes, decide or undo what an interrupted run left (an open problem
  blocked the next order; a new shop's cheaper offer would have changed
  another journey's best offer), and screenshot every page when a step
  fails.
- **Two sessions on one branch can take the same decision number.** Fetch
  before choosing one; on a clash keep both entries and renumber your own
  (D-074 here).

## Known problems

- **Seller notifications are a launch blocker (D-092, N-1).** Everything is
  built and tested against fakes, but no outside channel is connected: no
  Telegram bot, no SMS provider, notification SMS switched off. A seller
  learns of an order only in the dashboard, and an unanswered order expires
  in 30 business minutes. MarkX must not launch until at least one channel
  is connected and a real alert has reached a seller's phone.
- **Connecting Telegram is untested against Telegram** (D-093) and off. A
  notification already being sent at the moment someone disconnects may
  still go out once; notifications recorded `skipped` or `unavailable`
  before someone connected are never resent (a resend tool is a separate
  task); staff have no screen to disconnect someone.
- **Duplicates and losses are possible by design** (D-092): a worker that
  dies just after Telegram accepted a message sends it again; one that dies
  around an SMS send records it `unknown` and never resends it (it may be
  lost). Both are reported by the watch. No provider-side idempotency exists
  to do better (Telegram has none; no SMS provider is chosen).

- **MarkX cannot start on a real server today, by design** (D-084 to
  D-091): no SMS provider (F-11), no buckets (F-01), no picture domain
  (F-15), no Turnstile production widget. The production stack is ready
  for them; it is not "production-ready".
- **Database dumps stay on the server** (D-091): until F-16 is decided, the
  founder copies the newest dump off the server by hand at least weekly
  (`docs/runbooks/backup-and-restore.md`). Stored files have no backup at
  all (F-14).
- **A deploy restarts each service once** (one copy of each): a few seconds
  of refused requests, and pages being rendered when the web server stops
  fail (Next.js does not drain on SIGTERM).
- **Edge rate limits are estimates** (20 requests a second, 60 sign-in
  requests a minute per address). Many Ethiopian mobile users share one
  carrier address; measure before tightening.
- **Behind Cloudflare, the real-address snippet must be enabled first**
  (`infra/production/nginx/snippets/cloudflare-real-ip.conf.example`), or
  every visitor is one of Cloudflare's addresses to every limit.

- **A part paid in advance before D-087 that cannot go ahead waits for
  staff with no button to close it.** No new such part can arise (a payment
  is now recorded only from the handover on). For an old one, the buyer's
  cancel, the overdue job and "returned" refuse it and the watch alerts staff
  (`orders.paid_past_hold`, `orders.paid_delivery_failed`); staff can ask
  the shop to deliver. Recording a refund is, by the founder's decision, a
  Release 2 requirement (D-087).
- **Fixed (D-099): the commission cap is applied.** It was stored but never
  applied (D-086, D-088 item 1). Each line now copies the rule and its cap,
  and every fee calculation applies it. D-088's other items before any
  commission (a staff tool for rules, fee reversal, invoicing, statements,
  payouts) are still not built; fees stay at zero.
- **Weekly reports stored before D-086** count every cancellation as the
  buyer's; reports from now on split them.

- **Resolved: the dispute race test failed once in CI** (#97 on
  `8b32485`: `test_two_decisions_and_a_reply_race_on_one_case`, `assert 1 ==
  0`, one seller reply stamped after the decision). The rule held (the reply
  was accepted under the order's lock while the case was still open); the
  record was wrong by milliseconds: `resolve_dispute` read the clock before
  waiting for the lock, and a reply that got the lock in that wait was
  stamped later than the decision it preceded. Fixed by reading the clock
  after the lock, and proven by a deterministic test that fails on the old
  code. **Since reviewed (D-086):** three of the eight functions below were
  fixed the same way (`cancel_by_buyer`, `confirm_received`,
  `record_direct_payment`); the other five keep the clock first on purpose.
  The original note: eight other order functions also read the
  clock before their lock (`seller_respond`, `cancel_by_buyer`,
  `expire_unanswered_orders`, `confirm_received`,
  `complete_after_problem_window`, `cancel_overdue_fulfilment`,
  `record_direct_payment`, `open_dispute`). For the deadline jobs that is
  intended (the time decides what is due). No test has failed on any of
  them; review them if their recorded times must order exactly against
  concurrent writes.

- **Turnstile is untested against Cloudflare itself** (D-085). Every
  automated test stands in for Cloudflare; the documentation site was not
  reachable from the building session. The founder's local test widget now
  exists: the laptop test in `docs/SETUP.md` ("Testing Turnstile on a
  laptop") proves Turnstile verification once a person runs it. **Even then
  production sign-in does not work**: no SMS provider is chosen (the adapter
  exists, D-089, and a real server refuses to start without one), no
  production widget and no server.

- **The page weight is over the blueprint's 150 KB target** (D-084): 157 KB
  (home) to 195 KB (product page) before images; script 142 to 147 KB. The
  check in CI stops it growing (ceilings 210 KB and 170 KB); bringing it
  down (link prefetching, the RSC payload) is open work.
- **One reviewed audit finding is tolerated in development tools only**:
  picomatch GHSA-fc5q-39xc-vjpf (no fixed version exists). Its allow-list
  entry expires on 31 December 2026, when CI fails until it is reviewed
  again (`.github/security/npm-audit-allowlist.json`).
- **Fixed (D-104): `shop-screens.mjs` and "Your review is saved".** It
  failed now and then (first on 18 November 2026 locally, then on GitHub).
  The cause was the website: the refresh after saving removed the rated
  item's form and the message with it, about 75 ms after it appeared. The
  message now stays; the journey checks that it does.
- **The web CSP still allows inline scripts** (D-084): per-request nonces
  would make every page dynamic; measure before changing.

- **The browser journeys use the demo phones' sign-in codes**, five per phone
  per hour (`auth.otp_per_phone_per_hour`, working as designed). The admin
  journey signs each demo phone in once per run, so about four runs fit in
  an hour; a fifth is refused until the clock hour turns.
- **The admin journey changes the demo data** (orders, reviews, reports, a
  staff account per run); it relists what it takes down. Re-seed a fresh
  database for a clean demo. So do session ten's journeys: `shop-screens`
  buys two units, writes a review and decides its own problem (staff steps
  need the demo secret), and cleans up after an interrupted run;
  `seller-dashboard` leaves one approved "Demo Journey Phones" shop per run
  with no offer.
- **A buyer's fourth review of one shop in 30 days is held for staff**
  (`reviews.hold_after_same_seller`, D-066, working as designed), so
  `shop-screens.mjs` picks the shop the demo buyer reviewed least and stops
  with that reason once all three are at the limit: about six runs per
  30 days on one database. **The session's demo database has reached that
  limit**; re-seed a fresh one before running `shop-screens.mjs` again.
- **A buyer writes at most ten reviews a day** (`reviews.per_buyer_per_day`,
  working as designed); repeated journey runs reach it with the one demo
  buyer, so `admin-queues.mjs` lifts it through the staff settings route for
  its one review and restores it at once.
- **Solved: the worker pass that "handled nothing"** (session ten's open
  question). It handled exactly 100 messages, one batch, and stopped; the
  68 newer ones it left were the only ones looked at. `--once` now handles
  every due message, and a pass sends what its own jobs queued (D-082).
- **`setup-and-account.mjs` leaves its traces switched off**: per run one
  closed demo shop, an archived product and an archived proposal, an
  inactive "Gadgets" category, an inactive test zone, a demo brand and a
  test attribute. It switches off what an interrupted earlier run left on.
- **A staff authenticator code works once** (replay protection, working as
  designed): two staff sign-ins inside the same 30 seconds refuse the
  second. The journeys retry once with the next code.
- No failing test. (Corrected on 19 November 2026: the code does have known
  defects; see this list, for example the commission cap that is never
  applied, and the defects a to h in "State on 19 November 2026" at the top
  of this file.) The 801 tests of
  session four were reproduced unchanged at the start of session five before
  any code was written. One defect in session four's code was found and
  fixed (a cancelled shipment without its tracking event).
- **D-050 has two provisional parts**: what a refund does to the stock, and
  that support may decide a refund outcome alone.
- The next-best offer runs the product page's ranking once per line, inside
  the decline or expiry transaction. Fine at today's volume; the expiry job
  handles up to 200 orders a pass, so a very large batch makes that pass
  slower. Move the suggestion to the outbox if it ever shows up in timings.
- A seller who records a direct payment and later has the part refunded
  keeps the payment record as it was; the case decision is the record that
  the money went back. There is no `refunds` row in Release 1.
- A TIN is validated as exactly ten digits. That is the engineer's
  understanding of the Ethiopian format, not something the blueprint states
  (F-03).
- A rejected applicant needs a new invitation to apply again (F-05).
- All Amharic text was drafted by an AI agent. A native speaker must review it
  before launch (blueprint I.3).
- The parent order's derived status names (`awaiting_seller`, `in_progress`,
  `partly_delivered`, `completed`, `cancelled`, or the one status all parts
  share) are the engineer's; the blueprint gives only "partly delivered" as
  an example (D-038).
- **Nothing expires, completes or hides anything unless the worker is
  running.** On a laptop, start it in a second terminal (`docs/SETUP.md`).
- **D-043 is provisional.** An order still `confirmed` or `ready` fourteen
  days after confirmation is cancelled by the worker. The founder may prefer
  a staff warning; the change is one job.
- The parent order reads `completed` as soon as every part is handed over,
  even while one is still inside its problem window (D-038, D-045).
- Fixed by D-099: the fee cap per order (`cap_santim`) is copied onto each
  line and applied; `cap_applied` is set when it lowers a fee (D-045).
- A wrong handover code commits the attempt count inside the service
  (`db.commit()`), the same pattern as login codes. A caller that wraps
  `confirm_delivery` in a larger transaction would commit that larger
  transaction too; today's callers do not.
- **Product cards carry a picture but no rating yet** (D-074). The rating
  is on the product page (D-072); putting it on the card changes
  `ProductCardOut` on both sides again (D-061). Search filters by rating
  (`min_rating`, D-080) but does not rank by rating yet.
- **Commit `1920e55` says D-073 in its title**; after the merge with the
  parallel back-end session, which had taken D-073 for the performance
  page, its decision is **D-074**. History was not rewritten.
- **The weekly-reports migration (`0012`, the parallel session's) names
  D-069 in its docstring**; the decision is D-073. Left as it is: applied
  migrations are not edited.
- **Alerts reach nobody but the log until the founder creates the Telegram
  group and bot** and sets `MARKX_TELEGRAM_BOT_TOKEN` and
  `MARKX_ALERT_TELEGRAM_CHAT_ID`. A dead worker is only noticed by an
  outside monitor polling `/api/v1/healthz/worker`, which is not set up.
- **F-01 to F-08 have PROVISIONAL answers only** (D-083, the engineer's
  guess at the founder's request). **Each must be confirmed or changed by
  the founder before MarkX goes live**; treat `docs/DECISIONS.md`,
  "Decisions that need the founder", as part of the launch checklist. Each
  is marked `PROVISIONAL (F-0n, D-083)` in the code, and
  `tests/unit/test_provisional_decisions.py` keeps the markers in place.
  F-01 still blocks the launch: the adapters for S3 and R2 now exist
  (D-090), but the private document store itself does not exist until the
  founder chooses the provider and creates the account and buckets; a real
  server refuses to start until then. Copying any file there needs the
  founder's written approval.
- **Search logs and rate-limit counters are now deleted daily**
  (`retention.prune`, provisional periods of 180 days and one day; F-08,
  D-083). Before that they were never deleted.

## Tests executed

**Three small fixes** (D-104), on 21 November 2026, branch
`claude/markx-pr11-review-fixes-3uf2ts` from `main` at `7093e6c` (complete
history). PostgreSQL 17.12 and MinIO in containers, with
`MARKX_TEST_MINIO_REQUIRED=1` and `MARKX_TEST_BACKUP_REQUIRED=1`.

```text
uv run pytest -q -p no:cacheprovider -rs                 ->  2071 passed, 0 skipped, in 22 min 17 s (2061 + the 10 new)
F-26: 7 new tests in tests/api/test_telegram_bot.py      ->  7 passed; on 7093e6c (old code, new test file and
                                                             products.py only) all 7 fail: the alert and the inbox
                                                             carry no product names
database rule: 3 new in test_telegram_recycled_number.py ->  3 passed; on 7093e6c the 2 that try the forbidden state
                                                             fail with "DID NOT RAISE IntegrityError"
uv run ruff check .  /  ruff format --check .            ->  passed  /  259 files already formatted
uv run mypy markx                                        ->  no issues found in 153 source files
alembic upgrade head  /  alembic check                   ->  0021 -> 0022  /  no new upgrade operations detected
check_openapi_copy (exact, and the web app's copy)       ->  both match (no API change)
apps/web: npm run lint / npm run typecheck / npm test    ->  passed / passed / 146 passed (15 files)
apps/web: npm run build                                  ->  compiled
"Your review is saved", in Chromium (Compose stack, demo data, built web app, as journeys.yml):
  probe on the OLD site                                  ->  the message is shown, then removed about 75 ms later, for good
                                                             (0 after 3 s): the refresh removes the rated item's form
  shop-screens.mjs with the new check, OLD site          ->  3 runs: 3 failed, "the confirmation vanished when the page
                                                             refreshed"
  shop-screens.mjs on its own, FIXED site, 20 in a row   ->  20 passed, 0 failed (36 to 43 s each; a fresh demo
    (fresh demo database before each run)                    database each time, as a buyer's fourth review of one
                                                             shop in 30 days is held for staff)
```

**Fix before merging pull request #11** (D-103 section 5), on 21 November
2026, branch `claude/pr10-review-server-readiness-y7novo` on top of
`9d0c888` (complete history). PostgreSQL 17.12 and MinIO in containers,
with `MARKX_TEST_MINIO_REQUIRED=1` and `MARKX_TEST_BACKUP_REQUIRED=1`.

```text
uv run pytest -q -p no:cacheprovider                     ->  2061 passed, 0 skipped, in 22 min 57 s (2041 + the 20 new)
tests/deployment/test_deploy_newer_schema.py (new, 17)    ->  17 passed
  + 3 new in test_preflight_and_worker_heartbeat.py       ->  3 passed
the 20 new tests on 9d0c888 (worktree, the files only)    ->  18 failed, 2 passed (the two that check what must still work:
                                                             a rollback to a release that accepts the database, a backup
                                                             with no safe stop)
  the same, with only a "may be sourced" line added       ->  the reviewer's case fails with "...running again, verified":
    to the old deploy.sh                                     the defect itself
uv run ruff check .  /  ruff format --check .            ->  passed  /  258 files already formatted
uv run mypy markx                                        ->  no issues found in 152 source files
check_openapi_copy --exact openapi.json                  ->  matches the API exactly (no API change)
infra/check-image-pins.sh                                ->  every pulled image is pinned to its digest
sudo infra/production/rehearsal/rehearse.sh (local; MARKX_BUILD_CA for this machine's proxy)
  run 2 (final)                                          ->  rehearsal: 124 passed, 0 failed (was 116; 8 new checks)
  run 1                                                  ->  122 passed, 2 failed, both in the new checks, not in deploy.sh:
                                                             the reviewer's case looked for any "auto-rollback" in the log
                                                             (an earlier check rightly wrote one) and the roll forward did
                                                             not pass its release's Compose file; then the run broke because
                                                             the script was edited while it ran (not a finding)
  with the new rehearsal and the OLD deploy.sh (9d0c888)  ->  118 passed, 6 failed: the 6 new checks of the fix; the
                                                             reviewer's case printed "rehearsal-2 is running again, verified"
GitHub on 704d15e (pull request #11)                     ->  CI #173 success (all 8 checks; 2061 passed; rehearsal 124
                                                             passed, 0 failed), Browser journeys #49 success
  on 46ca31a                                             ->  CI #172 cancelled by the newer push; Browser journeys #48 success
```

**Server readiness** (D-103), on 21 November 2026, branch
`claude/pr10-review-server-readiness-y7novo` from `main` at `9b3658f`
(complete history). PostgreSQL 17.12 and MinIO in containers, with
`MARKX_TEST_MINIO_REQUIRED=1` and `MARKX_TEST_BACKUP_REQUIRED=1`.

```text
uv run pytest -q -p no:cacheprovider -rs                 ->  2041 passed, 0 skipped, in 21 min 5 s (2034 + the 7 new)
tests/api/test_tls_certificate_watch.py (new, 7)         ->  7 passed; on 9b3658f all 7 fail (no such check;
                                                             through the watch, no alert is raised)
uv run ruff check .  /  ruff format --check .            ->  passed  /  257 files already formatted
uv run mypy markx                                        ->  no issues found in 152 source files
check_openapi_copy --exact openapi.json                  ->  matches the API exactly (no API change)
infra/check-image-pins.sh                                ->  every pulled image is pinned to its digest
  before the CI and laptop pins                          ->  FAILED: 10 references (CI's postgres:17.12, laptop postgres:17)
sudo infra/production/rehearsal/rehearse.sh (local; MARKX_BUILD_CA for this machine's proxy)
                                                         ->  rehearsal: 116 passed, 0 failed (main: 74)
  two earlier local runs                                 ->  run 1: "certificate install" failed (the check read the
                                                             served certificate before nginx's reload took effect; it
                                                             now waits up to 15 s); the run then broke because the
                                                             script was edited while running (not a finding).
                                                             run 2: 114 passed, 2 failed, both in new checks: "status"
                                                             piped into grep -q (a broken pipe under pipefail) and the
                                                             safe stop answered 504 where only 502 was accepted; fixed
                                                             in the checks, nothing in deploy.sh
```

The rehearsal's new checks, by section: **containers** (16): memory, CPU
and process limits on all six services, uid 999 on api, worker and backup
and 1000 on web, set by the images, postgres, proxy and minio by digest,
the release's images under `MARKX_IMAGE_PREFIX`, the worker reads the
certificate and cannot read its key. **The certificate** (15): the watch's
critical alert for the 2-day certificate; `certificate check` fails inside
the warning time; another hostname and a foreign key refused and the old
certificate still served; install served without a proxy restart, with
the required modes; `check` and `certificate check` pass after; the alert
resolves; renewal off says so and `issue` refuses; renewal on, through a
stand-in for certbot, installs via the deploy hook; the timer's units
accepted by `systemd-analyze verify`. **Rollback** (3): every service
including backup, under the prefix; a missing release refused; a missing
backup image refused. **A failed update** (10): a broken release after its
migration: deploy fails, the last working release runs again (every
service), the site ready, never recorded as deployed; a broken release
with a newer migration: API, worker and web app stopped with instructions,
database and backup running, `deploy-halted` (600), `status` says so, the
site answers 504 from the proxy, the old release still refused, then
`MARKX_ALLOW_NEWER_SCHEMA=true` and `rollback` end the stop (schema ahead).

**Telegram for orders** (D-102), on 21 November 2026, branch
`claude/markx-telegram-pr9-completion-nneqom` from `main` at `fe4546f`
(complete history). PostgreSQL 17.12 and MinIO in containers, with
`MARKX_TEST_MINIO_REQUIRED=1` and `MARKX_TEST_BACKUP_REQUIRED=1` (the CI
settings: a missing service fails instead of skipping).

```text
uv run pytest -q -p no:cacheprovider -rs (final code)    ->  2034 passed, 0 skipped, in 21 min 48 s (2010 + the 24 new)
GitHub on f46fc83 (pull request #10)                     ->  CI #167 success (all 8 checks), Browser journeys #43 success
  an earlier full run, before the last fix               ->  1 failed, 2033 passed: tests/worker/test_worker.py compares
                                                             the fake sender's record field by field and the new code
                                                             had added the words to it; fixed in the code, the test
                                                             is unchanged
tests/api/test_telegram_bot.py (new, 24)                 ->  24 passed
the same 24 on fe4546f (worktree, the file only)         ->  cannot load (no markx.telegram_bot); with the new imports
                                                             replaced by stand-ins: 24 failed (no answer to a press or
                                                             command, no buttons, no Telegram words, the weekly message
                                                             reaching someone who left the store)
existing Telegram, notification, performance and seller
permission files with the new code                       ->  301 passed
uv run ruff check .  /  uv run ruff format --check .     ->  passed  /  256 files already formatted
uv run mypy markx                                        ->  no issues found in 152 source files
uv run alembic check                                     ->  no new upgrade operations detected (no migration)
check_openapi_copy --exact, both copies                  ->  match the API exactly
npm run lint / typecheck / test (apps/web)               ->  passed / passed / 146 passed
npm run gen:api, then git diff                           ->  schema.d.ts regenerated for the webhook's description
git diff 7eabf93 -- apps/api/tests apps/web/src          ->  only the new test file (and the generated types): no
                                                             existing test changed
```

**Review of pull request #9** (21 November 2026), read-only at `7eabf93`,
complete history (the clone was made complete first; it had been shallow).

```text
uv run pytest -q -p no:cacheprovider -rs                 ->  2010 passed, 0 skipped, in 20 min 50 s (MinIO and backup
                                                             tools required, as in CI)
tests/api/test_telegram_recycled_number.py on 7eabf93    ->  13 passed
the same file on b89aeff (worktree, the file only)       ->  12 failed, 1 passed (a guard)
  with every bound_telegram_id assertion removed         ->  7 failed with the takeover itself (the stranger "✅ signed
                                                             in" or "✅ connected" by sign-in, bot link and Mini App;
                                                             a new empty account; phone_in_use), 4 guards passed
ruff / format / mypy / alembic upgrade + check / both
OpenAPI copies (7eabf93)                                 ->  all passed; 0020 -> 0021
apps/web: lint, typecheck, unit tests                    ->  passed, passed, 146 passed
a scratch database: the 0021 check constraint            ->  accepts (telegram_id 4242, bound_telegram_id NULL);
                                                             refuses (5, 6)
GitHub on 7eabf93                                        ->  CI #163 success (all 8 checks), Browser journeys #39 success
GitHub on main fe4546f after the merge                   ->  CI #164 success, Browser journeys #40 success
```

**Recycled-number fix** (D-101 section 2a), on 21 November 2026, branch
`claude/telegram-signin-audit-fixes-q318w6` (pull request #9), from
`b89aeff` with the complete history (not shallow; nobody had pushed since
`b89aeff`). PostgreSQL 17 in a container; **MinIO was not started**, so the
file-storage and backup tests skipped locally (they run on GitHub).

```text
uv run pytest -q -p no:cacheprovider                     ->  1919 passed, 91 skipped (MinIO not running), in 16 min 2 s
tests/api/test_telegram_recycled_number.py (new, 13)     ->  13 passed
the same 13 against b89aeff (worktree, new file only)    ->  12 failed, 1 passed (the guard); the review's steps fail with
                                                             the bot telling the stranger "✅ You are signed in"
the Telegram files together (sign-in, linking, Mini App,
abuse, recycled number)                                  ->  179 passed
uv run ruff check .  /  uv run ruff format --check .     ->  passed  /  251 files already formatted
uv run mypy markx                                        ->  no issues found in 148 source files
uv run alembic upgrade head && uv run alembic check      ->  0020 -> 0021; no new upgrade operations detected
export_openapi compared with openapi.json                ->  identical (no API change)
apps/web: npm test; npm run lint; npm run typecheck      ->  146 passed (145 before; 1 new); passed; passed
```

Not run locally: the web build and the browser journeys (they run on
GitHub in the pull request; see the session's report for those runs).

**Sign-in with Telegram, SMS off, M2, M3, M4** (D-101), on 21 November
2026, branch `claude/telegram-signin-audit-fixes-q318w6`, from `main` at
`b79caab` with the complete history (`git fetch --unshallow`; `git
rev-parse --is-shallow-repository` prints `false`). PostgreSQL 17.12 and
MinIO in containers, with the CI job's settings (MinIO and the backup tools
required, least-privilege MinIO users, `postgres:17.12` client tools).

```text
uv run pytest -q -p no:cacheprovider                     ->  1997 passed, 0 skipped, in 18 min 18 s (1905 on main; 92 new)
the 92 new tests (3 files)                               ->  32 + 37 + 23 passed
uv run ruff check .  /  uv run ruff format --check .     ->  passed  /  250 files already formatted
uv run mypy markx                                        ->  no issues found in 148 source files
uv run alembic upgrade head && uv run alembic check      ->  0019 -> 0020; no new upgrade operations detected
check_openapi_copy --exact openapi.json; web copy        ->  both match the API exactly
apps/web: npm run lint; npm run typecheck                ->  passed; passed
apps/web: npm test                                       ->  145 passed (142 before; 3 new)
apps/web: npm run build; gen:api diff                    ->  passed; no change

# The new tests against the old code (a worktree of b79caab with only the new test files)
test_telegram_sign_in.py                                 ->  cannot even import: the feature does not exist (32 fail)
test_sign_in_abuse.py (new-only import made optional)    ->  25 failed, 3 errors, 9 passed (the 9 guards)
test_buyer_limit_contention.py                           ->  23 passed (the protection existed; see D-101 §7)
# The same item 7 tests with the code broken on purpose
unit-limit check removed                                 ->  per-shop race fails 5 of 5 rounds, per-offer 2 of 5
expired orders counted                                   ->  all 3 expiry tests fail
cart lock removed (only)                                 ->  still pass: the shop and offer locks serialise them

# Browser journeys on a fresh demo database (API with uvicorn, web with next start)
telegram-sign-in (new; API with SMS off, test-only bot)  ->  passed: Telegram sign-in, order placed, refusals en + am,
                                                             staff page Telegram first, axe: no violations
buyer-journey, staff-journey, sign-in-cooldown,
telegram-connection off (API as by default)              ->  all passed, "console errors: none"
```

The new journey's first run failed on the accessibility check (white text
on Telegram's light blue: too little contrast); the button is now a darker
blue and passes. Its second run failed on the engineer's own script (it
looked for an "Add a new address" button, but a new person's checkout
shows the address form at once); fixed in the journey. A first full API run
had 3 failures in `test_openapi_copy.py`, because a route description was
edited while the suite was running; the files and the code agree, and the
clean run above passed. Not run locally: the other journeys (they run on
GitHub in the pull request), the production stack rehearsal.

**Frontend resilience** (D-100), on 20 November 2026, branch
`claude/frontend-resilience-errors-g4z33c`, from `main` at `fae2514` with
the complete history (`git fetch --unshallow`; not shallow). PostgreSQL
17.12 and MinIO in containers, with the CI job's settings. The API code is
unchanged; its suite was run to confirm it.

```text
uv run pytest -q -p no:cacheprovider                     ->  1905 passed, in 16 min 7 s
uv run ruff check .  /  uv run ruff format --check .     ->  passed  /  245 files already formatted
uv run mypy markx                                        ->  no issues found in 147 source files
uv run alembic upgrade head && uv run alembic check      ->  no new upgrade operations detected
check_openapi_copy --exact openapi.json; web copy        ->  both match the API exactly
apps/web: npm run lint; npm run typecheck                ->  passed; passed
apps/web: npm test                                       ->  142 passed (102 before; 40 new)
apps/web: npm run build; gen:api diff; npm audit gate    ->  passed; no change; passed

# Browser journeys, in CI's order, on a fresh demo database (API with uvicorn, web with next start)
page-weight, seller-dashboard, buyer-journey, staff-journey,
admin-queues, shop-screens, setup-and-account            ->  all passed, "console errors: none"
network-recovery (new; axe on 16 pages)                  ->  passed, no accessibility violations
sign-in-cooldown, telegram off, telegram on, turnstile   ->  all passed

# The new journey against the old website (main, fae2514)
network-recovery (axe on)                                ->  fails on the first page: the two header problems
network-recovery (axe stubbed, proof copy only)          ->  fails at step 1: no message after "Add to cart" offline
"Add to cart" offline on main                            ->  still "Adding…" and disabled after 20 s, and 5 s after reconnecting
```

The first local runs of sign-in-cooldown and Telegram "on" failed because
of the engineer's own commands (the cool-down setting run from the wrong
folder; the journey not given its test-only values); run as CI runs them,
both passed.

**Order life-cycle hardening** (D-099), on 20 November 2026, branch
`claude/order-lifecycle-hardening-1djdof`, from `main` at `c70b338` with
the complete history (`git fetch --unshallow`; `git rev-parse
--is-shallow-repository` prints `false`). PostgreSQL 17.12 and MinIO in
containers, with the CI job's settings (MinIO and the backup tools
required, least-privilege MinIO users, `postgres:17.12` client tools).

```text
uv run pytest -q -p no:cacheprovider                     ->  1905 passed, 0 skipped, in 16 min 29 s
the 35 new tests (5 files)                               ->  35 passed
uv run ruff check .  /  uv run ruff format --check .     ->  passed  /  245 files already formatted
uv run mypy markx                                        ->  no issues found in 147 source files
uv run alembic upgrade head && uv run alembic check      ->  0018 -> 0019; no new upgrade operations detected
check_openapi_copy --exact openapi.json; web copy        ->  both match the API exactly (no API shape changed)
apps/web: npm run lint; npm run typecheck; npm test      ->  passed; passed; 102 passed

# The new tests against the old code (a worktree of c70b338 with only the new test files)
test_commission_cap, test_stalled_deliveries,
test_stock_hold_limits                                   ->  16 failed, 4 passed (the 4 ordinary-use guards)
test_fees                                                ->  cannot import: payments/fees.py is new
test_phone_digit_limits with d01fef7's phone.py           ->  8 failed (on c70b338: 8 passed)
```

A first, incomplete run of the unchanged code (839 passed, none failed)
was cut short when a second run was started by mistake and dropped the
shared test database; the complete run above is the one that counts.

**Staff conflict of interest, phone digits** (D-098), on 20 November
2026, branch `claude/staff-conflict-phone-fixes-qkiixq`, from `main` at
`d01fef7` with the complete history (not shallow). PostgreSQL 17.12 and
MinIO in containers, with the CI job's settings (MinIO and the backup tools
required, least-privilege MinIO users, `postgres:17.12` client tools).

```text
uv run pytest -q -p no:cacheprovider                     ->  1870 passed, 0 skipped, in 19 min 46 s
uv run pytest tests/api/test_staff_conflict.py           ->  22 passed
uv run pytest tests/api/test_phone_digits.py             ->  45 passed
uv run pytest tests/unit/test_phone.py                   ->  45 passed
uv run ruff check .  /  uv run ruff format --check .     ->  passed  /  238 files already formatted
uv run mypy markx                                        ->  no issues found in 145 source files
uv run alembic upgrade head && uv run alembic check      ->  no new upgrade operations detected
check_openapi_copy --exact openapi.json; web copy        ->  both match the API exactly
apps/web: npm run lint; npm run typecheck; npm test      ->  passed; passed; 102 passed

# The new tests catch the defects
conflict check switched off  ->  22 of 23 conflict tests fail (the "left the team" test passes, as it should)
old markx/core/phone.py      ->  phone-digit tests fail with the database's check violations (the server error)

# Found by the first full run, fixed
tests/db/test_dispute_contention.py: 3 tests decided disputes as the buyer
  (Actor(user_id=<buyer>)); now refused by D-098. They act as the bazaar's
  staff member; assertions unchanged; 4 passed.
```

The first full run, before that fix and without MinIO: 3 failed (those
three), 1776 passed, 91 skipped (the MinIO tests). Browser journeys were
not run locally; GitHub runs them on the pull request.

**Checks once per change, secret scan** (D-097), on 20 November 2026,
branch `claude/markx-checks-secret-scan-ik3o3z`, from `main` at `773bbb6`
with the complete history (not shallow), every branch and every pull
request's commits fetched. Tools from their GitHub releases, checksums
verified. **No product code changed, so the API and web suites were not
re-run locally; GitHub runs them on the pull request.**

```text
# Secret scan, every branch and pull request (git log --all; 140 commits, 4 merges)
gitleaks 8.28.0, default rules only (config outside the repo)  ->  7 findings, all labelled dev/test keys
gitleaks 8.28.0, the repository's .gitleaks.toml (old and new) ->  no leaks found
gitleaks dir (working tree), the new .gitleaks.toml            ->  no leaks found
trufflehog 3.90.0 git --no-verification                        ->  0 verified, 2 unverified (test URLs user:pass@...example)
# W-1, a throwaway repository: a random key on a line commented "# dev-only"
old .gitleaks.toml -> not reported;  new .gitleaks.toml -> reported (generic-api-key)
labelled values (markx-dev-only-token-..., the development key) -> allowed by both
# Workflows
actionlint 1.7.7 (with shellcheck 0.11.0) ci.yml               ->  clean
actionlint journeys.yml (also with pull_request added)         ->  2 SC2034 warnings, both in unchanged lines (also before)
# "What changed", run locally on real commits and test commits
pull request, docs only (3085cc7)            -> code=false     pull request #4 as a whole  -> code=true
push to main, docs only (f7df3ec)            -> code=false     new branch / by hand / bad base -> code=true
apps/.../README.md renamed into docs/        -> code=true      apps/web/AGENTS.md          -> code=true
README.md + AGENTS.md + docs/runbooks/*.md   -> code=false     docs/notes.txt, .gitignore  -> code=true
# "CI result", every case
code, all passed -> pass; code, one failed / cancelled / skipped -> FAIL
docs only, heavy skipped -> pass; docs only, security failed -> FAIL; "What changed" failed -> FAIL
```

GitHub, pull request #5 on `ec64a85`: CI 151 (one run, `pull_request`)
passed all seven jobs, the production rehearsal included; Browser journeys
28 (by hand) passed. The branch push alone started no run. On `65d1669`:
CI 152 (one run) passed all seven jobs. The commit that makes the journeys
start on pull requests again: its results, and main's after the merge, are
in the session report. Details: `docs/HANDOFF.md`, Part A.0000000000.

**Backup trust hardening** (D-096), on 19 November 2026, branch
`claude/markx-backup-trust-hardening-4mmhxz` (commits `ffbfc39`, `2b4e179`,
`f9b8c99`), PostgreSQL `postgres:17.12` and MinIO
(`bitnamilegacy/minio:2025.7.23-debian-12-r5`) in Docker on the session's
machine, the least-privilege MinIO users made by
`infra/backup/minio-least-privilege.sh`. **No real provider, bucket or key
was used; nothing left this machine.**

```text
# API, the whole suite (MinIO, the backup tests and their MinIO users required)
$ MARKX_TEST_MINIO_MC="docker exec -i markx-minio mc" uv run pytest -q -p no:cacheprovider
  ->  1789 passed in 798.56s (0:13:18)
$ uv run ruff check .            ->  All checks passed!
$ uv run ruff format --check .   ->  235 files already formatted
$ uv run mypy markx              ->  Success: no issues found in 144 source files
# The two CI drill steps, run locally with CI's exact commands and settings:
#   rehearsal (no-delete key, read-only source key)    ->  DRILL PASSED, 7 of 7 faults refused
#   off-server (read-only key, PostgreSQL --network none) ->  DRILL PASSED, 7 of 7 faults refused
# The recovery container: NetworkMode=none, only "lo", "Network is unreachable".
# The exact-grants test fails with prepare_for_owner_restore removed, passes with it.
```

GitHub, pull request #4, commit `adf128a`: **CI 144 and 145 passed** (all
five jobs; the API job ran 1789 tests and both drills), **Browser journeys 26
passed**. Earlier runs and why they failed:
`docs/reports/2026-11-19-backup-trust-hardening.md`.


**Off-server backup and disaster recovery** (D-094), on 18 November 2026,
commits `c7d0d82` to `3922579` (on `866a184`), PostgreSQL 17 and MinIO
(`bitnamilegacy/minio:2025.7.23`) in Docker on the session's machine,
PostgreSQL 17 client tools from the `postgres:17` image. **No real provider,
bucket or key was used; nothing left this machine.**

```text
# API, the whole suite (with MinIO and the backup tests required)
$ uv run pytest               ->  1748 passed in 718.74s (0:11:58)
  (run on 95af1a0's code; the three fixes after it, a corrupt source file,
   key rotation and an unmigrated database, were then run as:)
$ uv run pytest tests/unit/test_backup_*.py tests/api/test_backup_monitoring.py \
    tests/storage/test_backup_recovery.py tests/api/test_ops.py tests/db/test_migrations.py
                              ->  114 passed in 82.18s
  new tests: 33 encryption/keys/signatures, 16 configuration, 11 retention,
  16 monitoring, 22 PostgreSQL+MinIO backup and recovery
$ uv run ruff check .          ->  All checks passed!
$ uv run ruff format --check . ->  233 files already formatted
$ uv run mypy markx            ->  Success: no issues found in 144 source files
$ uv run alembic check         ->  No new upgrade operations detected.
$ uv run python -m scripts.check_openapi_copy --exact openapi.json -> matches exactly
$ uv run python -m scripts.check_openapi_copy ../web/src/lib/api/openapi.json -> matches exactly
# the CI drill step, replayed locally on a fresh demo database
$ python -m markx.backup drill --seed-sample-files ...
                              ->  DRILL PASSED: 76 tables, 368 rows, 19 files (16 private,
                                  3 public), 12 references resolved, 7 of 7 faults refused
# the backup image (docker build --target backup apps/api, via mirror.gcr.io)
                              ->  uid 999, pg_dump/pg_restore/psql 17.12; the drill run
                                  inside it: DRILL PASSED
# the production Compose backup service (postgres, minio, migrate, backup, with
# the rehearsal's override and settings; a partial rehearsal by hand)
                              ->  healthy; markx user, read-only root; a complete signed
                                  set; local copy MXB2, owner 999, mode 600; as production
                                  it refuses MinIO (exit 2, no secret printed); the drill
                                  passes inside the stack; SIGTERM stop in 2 s, exit 0
# NOT run locally: the full rehearsal (rehearse.sh). Docker Hub refused the
# nginx image (429, rate limit) and the GitHub registry is blocked here; CI
# runs it. Gitleaks: not installed here; CI runs it.
```

On GitHub, on `937c410` (all five commits): **CI #129 (push) passed**, all
five jobs: API (lint, types, migrations, the whole suite with the backup
tests required, both API description checks, and the step "Backup,
off-server copy and recovery drill (MinIO stand-in)", which fails unless the
drill prints DRILL PASSED; its report is the `restore-drill` artifact, kept
30 days); web; security (Gitleaks over the whole history, both dependency
audits); containers (including the new backup image check); and the
**production rehearsal: 74 passed, 0 failed**, among them the backup
service's refusal as production, a healthy service with a complete signed
set, the MXB2 local copy (owner 999, mode 600), the drill inside the stack,
and the backup service stopping on SIGTERM in 3 s. **CI #130** (pull request
#1, same commit) passed; **browser journeys #21** passed. The drill report
itself could not be downloaded into this session (the artifact host is not
reachable from here); the step's own check is the evidence.


**Telegram account connection** (D-093), on 18 November 2026, commits
`9d0a5ef` to `76b16b0` (on `366f8f9`), PostgreSQL 17 in Docker on the
session's machine, no MinIO locally. **Telegram was never contacted: every
webhook call in these tests and journeys was made by the test or the
journey itself, with test-only values.**

```text
# API, the whole suite, on the final code (after the lock-order fix)
$ uv run pytest                  -> 1596 passed, 57 skipped in 769.01s
  (the 57 skipped are the MinIO storage tests; CI runs them with MinIO)
  new: tests/api/test_telegram_linking.py (89), one each in
  test_auth_telegram.py, test_retention.py, test_security_hardening.py
$ uv run ruff check . / ruff format --check .   -> passed
$ uv run mypy markx              -> Success: no issues found in 129 source files
$ uv run alembic upgrade head && uv run alembic check -> No new upgrade operations detected.
$ scripts.check_openapi_copy --exact openapi.json, and the web copy -> match exactly
# tests checked against deliberately broken code (then restored):
  no expiry check -> 1 failure; secret not compared -> 6; no advisory lock and
  no unique-constraint fallback -> the concurrent-link test fails; the old
  lock order -> DeadlockDetected (500) in 4 of 5 runs of the new contention test
# web
$ npm test -> 102 passed (12 new); npm run lint -> clean; npm run typecheck -> clean;
  npm run build -> success
# browser journeys, locally (uvicorn + next start, PostgreSQL 17, local files)
$ node e2e/telegram-connection.mjs off -> passed (en, am, 360 px)
$ node e2e/telegram-connection.mjs on  -> all 9 steps passed (test-only values)
$ setup-and-account, buyer-journey, seller-dashboard, page-weight -> passed,
  no console errors
# secret scan: gitleaks 8.28.0 over the whole history -> no leaks found
# GitHub, on 76b16b0
Browser journeys #20: success, including "Telegram connection, switched off",
"... switched on with test-only values" and "Telegram linking off again"
CI #123 and #124 on 76b16b0: cancelled by the next push (concurrency)
CI #125 (push) and #126 (pull request #1) on d347175 (the same code plus
this file): success. The journeys do not run on a documentation-only push;
#20 above ran the same code
```

**Notification system** (D-092), on 18 November 2026, commits `43bec22`,
`f1c9a35`, `9dd87eb` (on `bd091bd`), PostgreSQL 17 in Docker on the
session's machine, no MinIO locally. No outside service was contacted.

```text
# API, the whole suite
$ uv run pytest                  -> 1504 passed, 57 skipped in 672.26s
  (the 57 skipped are the MinIO storage tests; CI runs them with MinIO)
  new: tests/api/test_notification_delivery.py (72), two in
  tests/deployment/test_production_config.py
$ uv run ruff check . / ruff format --check .   -> passed
$ uv run mypy markx              -> Success: no issues found in 128 source files
$ uv run alembic upgrade head && uv run alembic check -> No new upgrade operations detected.
$ uv run python -m scripts.check_openapi_copy --exact openapi.json -> matches exactly
  (no route or schema changed)
# web
$ npm test -> 90 passed; npm run lint -> clean; npm run typecheck -> clean
# GitHub, on 9dd87eb
CI #119 (push): success; CI #120 (pull request #1): success;
Browser journeys #19: success (secret scan and dependency audits are CI jobs)
```

**Production deployment foundation** (D-091), on 18 November 2026, on the
session's tree (commits `359e0c9` to the documentation commit), PostgreSQL
17 and MinIO in Docker on the session's machine. Nothing was deployed; no
outside account, domain, certificate authority or bucket was contacted.

```text
# API, the whole suite, on the final API code
$ MARKX_TEST_MINIO_REQUIRED=1 uv run pytest -> 1487 passed in 613.13s (1387 before; 100 new)
  tests/deployment (production configuration, liveness and readiness,
  preflight, the API and worker refusing to start, the worker heartbeat),
  tests/db/test_migration_lock.py (3), tests/storage/test_readiness_on_minio.py (3)
$ uv run ruff check .            -> All checks passed!
$ uv run ruff format --check .   -> 208 files already formatted
$ uv run mypy markx              -> Success: no issues found in 126 source files
$ uv run alembic upgrade head && uv run alembic check -> No new upgrade operations detected.
$ uv run python -m scripts.check_openapi_copy --exact openapi.json -> matches the API exactly
$ uv run python -m scripts.check_openapi_copy ../web/src/lib/api/openapi.json
  -> still true; new: GET /api/v1/healthz/live, GET /api/v1/healthz/ready

# the new rules against the old code (a9941d2's config.py with stubs for the
# two new names): 15 of the 70 configuration tests fail, exactly the new
# rules (Fernet key, bare origin, DEBUG, explicit trusted proxies, the raw
# configuration in errors, log levels, the start-up warning); the 55 that
# check the earlier rules pass on both
# a9941d2's storage.py: the missing-bucket test fails (StoredFileMissing: check)
# a9941d2's bootstrap.sh: a re-run without variables reset markx_app's real
#   password to the laptop default (shown by hand: the dev password connected)

# web
$ npm run lint -> clean;  npm run typecheck -> clean
$ npm test -> 90 passed (71 before; 19 new: forwarded.test.ts, deploy-env.test.ts)
$ npm run gen:api && git diff --exit-code src/lib/api/schema.d.ts -> unchanged
$ npm run build -> ok (the ordinary output, as CI builds it)

# browser journeys, replayed locally as journeys.yml runs them (laptop Compose
# stack, demo data, next start, Chromium)
page-weight (every page within its budget), seller-dashboard, buyer-journey,
staff-journey, admin-queues, shop-screens, setup-and-account,
sign-in-cooldown, turnstile-widget -> all passed, console errors: none

# security
$ gitleaks 8.28.0 git (all 98 commits) -> no leaks found (after allow-listing
  the tests' test-only Fernet key by value; it was the one finding)
$ gitleaks dir (the 55 new or changed files) -> no leaks found
$ uv run pip-audit -> No known vulnerabilities found
$ node .github/scripts/npm-audit-gate.mjs apps/web -> passed (production: none;
  development: the reviewed picomatch entry, allowed until 2026-12-31)

# containers
docker build apps/api, apps/web (with --secret build_ca: this machine reaches
registries through a TLS-inspecting proxy) -> both build; api runs as markx
(999), web as node (1000); no pytest, no sources, no dev dependencies; no
/run/secrets in either image
docker compose config: the laptop file, the laptop + CI files, the production
file with the example settings -> valid

# the production rehearsal (infra/production/rehearsal/rehearse.sh), final run
rehearsal: 67 passed, 0 failed
  PASS  the production Compose file is valid with the example settings
  PASS  deploy.sh check refuses the example settings (placeholders, owners, no certificate)
  PASS  deploy.sh refuses a stage other than staging or production
  PASS  deploy.sh check passes for the rehearsal's server layout
  PASS  the API refuses to start as production with development settings, naming them, no value
  PASS  the worker refuses to start as production with development settings
  PASS  preflight refuses the production configuration with exit 2, no value
  PASS  the web app refuses to start as production without its site key (exit 2)
  PASS  deploy.sh deploy: build, preflight, backup, migration, start, verify
  PASS  the deploy log holds none of this run's secrets
  PASS  the release is recorded
  PASS  only the proxy publishes ports
  PASS  PostgreSQL has no way out to the internet
  PASS  the web app has no way out to the internet
  PASS  the API can reach the internet (outside services)
  PASS  the web app cannot reach PostgreSQL
  PASS  the proxy cannot reach PostgreSQL
  PASS  the API reaches PostgreSQL
  PASS  the proxy reaches the API and the web app
  PASS  api runs as an unprivileged user (markx)
  PASS  api has a read-only root file system
  PASS  worker runs as an unprivileged user (markx)
  PASS  worker has a read-only root file system
  PASS  web runs as an unprivileged user (node)
  PASS  web has a read-only root file system
  PASS  proxy runs as an unprivileged user (101)
  PASS  proxy has a read-only root file system
  PASS  HTTP is redirected to HTTPS on the site's hostname
  PASS  the redirect never uses the visitor's Host header
  PASS  certificate challenges are served over HTTP
  PASS  an unknown hostname is refused at the TLS handshake
  PASS  TLS 1.1 is refused (the local OpenSSL cannot offer it either; weaker evidence)
  PASS  TLS 1.2 is accepted
  PASS  TLS 1.3 is accepted
  PASS  a page is served over HTTP/2
  PASS  a page has HSTS exactly once
  PASS  a page has its security policy
  PASS  a page does not name its framework
  PASS  the Server header has no version
  PASS  the API is ready through the proxy
  PASS  an API answer has HSTS exactly once
  PASS  the API does not name its server
  PASS  liveness answers
  PASS  /api/v1/openapi.json is not public
  PASS  /api/v1/docs is not public
  PASS  /api/v1/dev/sms-inbox?phone=0911000000 is not public
  PASS  a 2 MB JSON body is refused at the proxy (413)
  PASS  a 5 MB upload reaches the API, which decides (403)
  PASS  a 25 MB upload is refused at the proxy (413)
  PASS  one visitor is one address: the API call and the page's own call count the visitor, never a forged or internal address
  PASS  the edge rate limit answers 429 to a burst on sign-in
  PASS  the worker's heartbeat check is healthy
  PASS  the worker runs its scheduled jobs (/healthz/worker)
  PASS  two migration runs at once both finish
  PASS  and the schema did not change
  PASS  backups are written encrypted, owner 999, mode 600 (2 so far)
  PASS  the backup service is healthy
  PASS  the latest dump restores into a new database at the same migration
  PASS  the restore did not change the running site's passwords (preflight still passes)
  PASS  deploy.sh rollback starts another release's images, verified
  PASS  rollback refuses a release whose images are not here
  PASS  proxy stops on SIGTERM in 1s (exit 0)
  PASS  web stops on SIGTERM in 0s (exit 143)
  PASS  api stops on SIGTERM in 1s (exit 143)
  PASS  worker stops on SIGTERM in 0s (exit 0)
  PASS  backup stops on SIGTERM in 1s (exit 0)
  PASS  postgres stops on SIGTERM in 0s (exit 0)

# NOT run: shellcheck (not installed here, and installing it was not
# permitted in this workspace); bash -n on every script instead. actionlint
# (not installed); the workflows were parsed as YAML.
# NOT tested anywhere: a real server, a real certificate or DNS name, real
# S3/R2, a real SMS provider, Turnstile's production widget, a night of the
# backup schedule, load. See "What exists but is NOT tested".
```

**On GitHub, on `6d97cb1`:** CI #113 (push) failed in one job only, the new
"Production stack rehearsal": GitHub's newer Docker Buildx refuses to read
a build secret outside the project (`/dev/null`, the rehearsal's "no extra
CA" default) without an extra entitlement. API (1487 tests, the drill),
web, security and containers passed in the same run; CI #114 (the pull
request event) is the same commit. Browser journeys #17 passed. Fixed in
the next commit: the build-CA secret lives in its own override file
(`rehearsal/compose.build-ca.yaml`), added only when `MARKX_BUILD_CA` is set,
and `MARKX_COMPOSE_OVERRIDE` takes several files. The rehearsal passed again
locally after the fix (67 passed, 0 failed). **On GitHub, on `59b1b82`:**
CI #115 (push) passed every job: API (lint, format, types, migrations, the
suite, both API-description checks, the drill), web, security (Gitleaks
over every commit, pip-audit, the npm gate), containers (both images, the
production file with the example settings, the web image's checks), and
"Production stack rehearsal" (67 passed, 0 failed, in under three
minutes). CI #116 (the pull request event, same commit) passed. Browser
journeys #18 passed.

Earlier runs of the rehearsal in this session failed on the rehearsal's own
mistakes and on two real defects, all fixed before the final run: MinIO
not started by `run --no-deps` (deploy.sh now takes
`MARKX_DEPENDENCY_SERVICES`), a missing bucket raising instead of being an
outage (fixed in `storage.py`), the readiness of an empty database
(`unknown`, now `behind`), curl going through this machine's outbound proxy
(`--noproxy`), and header lines ending in a carriage return.

**Object storage** (D-090), on the commit after `d4a29af`, PostgreSQL 17
and MinIO (`bitnamilegacy/minio:2025.7.23-debian-12-r5`) in Docker. No
Amazon or Cloudflare account was contacted; no real document was uploaded.

```text
$ MARKX_TEST_MINIO_REQUIRED=1 uv run pytest -> 1387 passed in 653.95s (0:10:53)   (1251 before; 136 new)
  tests/storage -> 136 passed (61 contract on the local folders and on MinIO,
  53 configuration, 14 API and worker on MinIO, 8 copy tool)
# the new rules against the old code (d4a29af), as configuration and store
# probes that import nothing new:
  a real server with its files on its own disk  -> DID NOT RAISE (old starts)
  pictures served from the site's own domain    -> old refuses only r2 itself
  choosing r2 or minio by configuration         -> old: "Input should be 'local'"
  one bucket for documents and pictures         -> old refuses only r2 itself
  HTML, and an SVG declared as a PNG, stored    -> DID NOT RAISE (old stores them)
  -> 6 failed on the old code; the same 6 passed on the new
# each protection taken out of the new code, one at a time (a scratch copy):
  the byte check -> 7 failed; a missing bucket read as a missing file -> 1 failed;
  the endpoint left to the SDK (AWS_ENDPOINT_URL honoured) -> 1 failed;
  the privacy canary blinded -> 1 failed; the endpoint's error text logged ->
  1 failed; MinIO allowed on production -> 2 failed; one bucket for both ->
  1 failed; the permission re-check at opening removed -> 1 failed (and the
  existing local test too); the private no-store header dropped -> 1 failed
  (logging a refused credential's error text changed nothing: that text names
  no key, bucket or endpoint, so there was nothing to catch)
  ruff check -> All checks passed!; ruff format --check -> 200 files already formatted
  mypy markx -> no issues found in 124 source files
  alembic check -> no new upgrade operations (no migration in this session)
  check_openapi_copy, both copies -> match exactly (no API schema change)
  pip-audit (boto3 1.44.5 and its stubs included) -> No known vulnerabilities found
  npm audit gate -> passed; gitleaks 8.28.0: history (98 commits) -> no leaks;
  every changed or new file -> no leaks
$ web: lint clean; typecheck clean; npm test -> 71 passed; npm run build ok
  (two new message strings, storage_unavailable, in both languages)
$ Compose (laptop file plus the CI override, on spare ports): MinIO healthy,
  both buckets created, migrations, API and worker healthy; the API image
  (built here from a scratch copy of the Dockerfile that only adds this
  workspace's proxy certificate) runs as markx, holds no pytest and no type
  stubs, imports boto3 1.44.5
$ browser journeys against that Compose, demo data seeded, the workflow's
  settings and storage values applied:
  page-weight -> every page within its budget; seller-dashboard, buyer-journey,
  staff-journey, admin-queues, shop-screens, setup-and-account -> passed,
  console errors: none
  afterwards in MinIO: markx-private 26 objects (20 seller documents, 3
  picture sources, 2 problem photos, the watch's canary), markx-public 6
  rendered pictures; the local folder held only the development inboxes
$ GitHub Actions on 19e8078: CI #109 (push) -> success: API 1387 passed in
  684.00s with MinIO required (none skipped), both OpenAPI copies, DRILL
  PASSED; web; containers; security (Gitleaks, pip-audit, npm audit).
  CI #110 (pull request #1) -> success. Browser journeys #16 -> success, on
  Compose with MinIO
```

**SMS foundation** (D-089), on the commit after `3c7921c`, local PostgreSQL 17
in Docker. No SMS provider was contacted; no real SMS was sent.

```text
$ uv run pytest -> 1251 passed in 660.19s (0:11:00)   (1126 before; 125 new)
  tests/api/test_sms_adapter.py + test_sms_cooldown.py -> 125 passed, three
  random-order repeats -> 125 passed each
# the new behaviour against the old code (3c7921c), as HTTP and configuration
# probes that import nothing new:
  staging with the fake SMS sender  -> DID NOT RAISE ValidationError (old starts)
  a second code at once             -> assert 200 == 429 (old sends it)
  a delivery record for a code      -> relation "sms_messages" does not exist
  same three on the new code        -> 3 passed
  (the full new test files cannot be collected on the old code: the adapter,
  its result and its errors did not exist)
# found by the new tests while building: a refused redirect left the response
# socket open (ResourceWarning, an error in this suite); fixed in the adapter
# four existing tests changed, none weakened: three ask for a second code for
# one number and now let the cooldown pass first (a person coming back);
# test_turnstile's production settings now include a real SMS configuration
  ruff check -> All checks passed!; ruff format --check -> 193 files already formatted
  mypy markx -> no issues found in 124 source files
  alembic upgrade head (0014 -> 0015) ok; alembic check -> no new upgrade operations
  check_openapi_copy, both copies -> match exactly (no API schema change)
  pip-audit -> No known vulnerabilities found; npm audit gate -> passed
  gitleaks 8.28.0 (dir mode, every new or changed file) -> no leaks
$ web: lint clean; typecheck clean; npm test -> 71 passed (64 before; 7 new,
  sign-in-problem.test.ts); npm run build ok
$ browser journeys, against the API and the production build on this machine,
  demo data seeded, the workflow's settings applied:
  page-weight -> every page within its budget; seller-dashboard, buyer-journey,
  staff-journey, admin-queues, shop-screens, setup-and-account -> passed,
  console errors: none; sign-in-cooldown (cooldown back at 60) -> "refused
  with 60 s left, in English and Amharic"; turnstile-widget (stand-in) -> passed
$ GitHub Actions on 9b9f6db: CI #105 -> success (API: lint, format, mypy,
  migrations, tests, both OpenAPI copies, backup and restore drill; web: lint,
  types, unit tests, build; containers; security: Gitleaks, pip-audit, npm
  audit); Browser journeys #15 -> success (including the new cooldown step)
```

**F-09 option 2** (D-087), on the commit after `9af18c7`:

```text
$ pytest test_paid_orders, test_clock_after_lock, test_order_rules, test_fulfilment,
         test_disputes, test_fulfilment_contention -> 96 passed
# the new tests against the old code
  old service rule (advance payment allowed), trigger kept ->
    test_a_payment_cannot_be_recorded_before_the_handover failed: 500 == 409
    (the database trigger refused the advance record: its half works alone)
  without migration 0014 (no trigger) ->
    test_the_database_refuses_a_payment_recorded_before_the_handover: 3 failed
# kept: a part paid in advance before the rule still goes to completion with its
# payment record (test_a_part_paid_in_advance_before_the_rule_is_kept_and_goes_ahead)
$ uv run pytest -> 1126 passed in 591.68s (0:09:51)   (1119 before; 7 new)
  ruff check -> All checks passed!; ruff format --check -> 191 files already formatted
  mypy markx -> no issues found in 124 source files
  alembic upgrade head (0013 -> 0014) ok; alembic check -> no new upgrade operations
  check_openapi_copy, both copies -> match exactly (no API schema change)
  pip-audit -> No known vulnerabilities found; npm audit gate -> passed
$ web: lint clean; typecheck clean; npm test -> 64 passed; build ok; gen:api unchanged
```

**Order and payment integrity** (D-086), on the commit after `1c55602`. Each
new test was also run against the old code (the fix taken out, the test
kept):

```text
$ pytest tests/api/test_paid_orders.py -> 9 passed
  old order code (constraint kept) -> 3 failed: the buyer's cancel, the overdue
  job and "returned" all ended a paid part; 6 passed (unpaid baselines, database)
$ pytest tests/db/test_clock_after_lock.py -> 3 passed; old code -> 3 failed
$ pytest tests/api/test_reviews.py -k cannot_tell -> 1 passed
  old code -> failed: the store's review shared the order line's id with its order page
$ pytest tests/api/test_performance.py -> 7 passed (2 new)
  old code -> 2 failed: KeyError 'orders_cancelled_unfulfilled' (both counted as
  the buyer's); RuntimeError from one store stopped every store's report
$ uv run pytest -> 1119 passed in 502.12s (0:08:22)   (1104 before; 15 new)
  ruff check -> All checks passed!; ruff format --check -> 191 files already formatted
  mypy markx -> no issues found in 124 source files
  alembic upgrade head (0012 -> 0013) ok; alembic check -> no new upgrade operations
  check_openapi_copy, both copies -> match exactly (regenerated in this commit)
  pip-audit -> No known vulnerabilities found; npm audit gate -> passed
$ web: npm run lint -> clean; typecheck -> clean; npm test -> 64 passed; build -> ok
# browser journeys: on GitHub (they run on this push)
```

**Dispute timestamp fix**, on the commit after `8b32485`:

```text
# CI #97 on 8b32485: 1 failed, 1101 passed
  FAILED tests/db/test_dispute_contention.py::test_two_decisions_and_a_reply_race_on_one_case
  - assert 1 == 0 (one reply's created_at after the case's resolved_at); CI #98, same commit: passed
# the new deterministic test (a second connection tries to lock the order at every clock read)
$ pytest tests/db/test_dispute_contention.py -k reads_the_clock
  fixed code -> 2 passed;  old code (fix stashed) -> 2 failed: AssertionError: [False]
$ the whole dispute contention file, 30 runs (4 tests each, two of them 30-thread races)
  -> passed 30, failed 0
$ uv run pytest -> 1104 passed in 481.61s (0:08:01)
  ruff check -> All checks passed!; ruff format --check -> 189 files already formatted
  mypy markx -> no issues found in 124 source files; alembic check -> no new upgrade operations
  check_openapi_copy, both copies -> match exactly; pip-audit -> No known vulnerabilities found
```

**Turnstile session, second round** (D-085 update), on the commit after
`fbaf46c`. Cloudflare was not contacted; the founder's secret key was not
used, stored or printed:

```text
# the flaky test (CI #95 on fbaf46c: 1 failed, 1070 passed)
  measured: a signature ends in "AA" 187 times in 200,000 = about 1 in 1,069
$ pytest -p force_aa (a throwaway plugin: every signature ends in "AA")
  old test -> 1 failed: assert 200 == 403 (the CI failure, reproduced)
  new test -> 1 passed
$ pytest -p force_all_a (every signature is "AAA...A") new test -> 1 passed
$ new test, 30 ordinary runs -> passed 30, failed 0
# hostname validation
$ pytest tests/api/test_turnstile.py -> 105 passed (31 new: accepted and refused
  values with their reasons, every bad entry named at once, localhost refused on
  staging/production and allowed on a laptop, a real start-up in a separate
  process: exit code not 0, the message names the entry, no secret in it)
$ uv run pytest -> 1102 passed in 464.38s (0:07:44)
  ruff check -> All checks passed!; ruff format --check -> 189 files already formatted
  mypy markx -> no issues found in 124 source files; alembic check -> no new upgrade operations
  check_openapi_copy, both copies -> match exactly; pip-audit -> No known vulnerabilities found
# no secret in the repository: every 0x4... value in tracked and new files is the
# public site key, a test-only placeholder, or part of an npm checksum
```

**Turnstile session** (D-085), on `45a699c`. Cloudflare was never
contacted. On GitHub, all passed on `45a699c`: **CI #93** (push) and
**CI #94** (pull request #1), every job (API, web, containers, security:
Gitleaks found no leaks); **Browser journeys #10**: page weight, the six
journeys and the new Turnstile widget step. Locally:

```text
$ uv run pytest tests/api/test_turnstile.py tests/api/test_security_hardening.py tests/api/test_auth_otp.py -> 140 passed
$ uv run pytest -> 1071 passed in 459.24s (0:07:39)   (997 before; 74 new)
  ruff check -> All checks passed!; ruff format --check -> 189 files already formatted
  mypy markx -> no issues found in 124 source files; alembic check -> no new upgrade operations
  check_openapi_copy --exact openapi.json, and the web copy -> both match exactly (no API change)
  pip-audit -> No known vulnerabilities found
$ npm run lint -> clean; npm run typecheck -> clean; npm test -> 64 passed; gen:api -> unchanged
$ npm run build -> ok; CSP on /en/sign-in: script-src 'self' 'unsafe-inline'
  https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com
$ node .github/scripts/npm-audit-gate.mjs apps/web -> passed (no production advisories)
# web on :3000 with MARKX_TURNSTILE_SITE_KEY=test-only-site-key, API with the development check
$ node e2e/turnstile-widget.mjs
  1 the widget loads under the page's security policy, with the site key and the sign_in action
  2 before the check is solved, sending is refused in words and nothing is sent
  3 solved: the API received bot_token test-only-token-1
  4 a second attempt used a fresh token (test-only-token-2)
  5 a refused token is reported in words, the widget is reset (1), and a fresh token works
  console errors: none
# found on the way: the journey must use the site's own origin (on :3001 the
# API's anti-forgery check refused it, correctly), and a fresh phone number
# per run (five codes a number an hour, correctly)
# NOT run: anything against Cloudflare (no keys yet, by the founder's
# instruction); Cloudflare's documentation (not reachable from this session)
```

**Security and CI session** (D-084), on `3a829d0`:

```text
# before any change, on c6be8ad
$ uv run pytest -> 966 passed in 735.00s (0:12:15)
# the new tests on the OLD code (fixes stashed, tests kept)
$ uv run pytest tests/api/test_security_hardening.py -> 28 failed, 3 passed
# the old sign-in check, given the attack values
  "/\evil.example" -> browser goes to https://evil.example/ ; "/<tab>/evil.example" -> same
# on the fixed code
$ uv run pytest tests/api/test_security_hardening.py -> 31 passed
$ uv run pytest -> 997 passed in 473.98s (0:07:53)
  ruff check -> All checks passed!; ruff format --check -> 188 files already formatted
  mypy markx -> no issues found in 124 source files; alembic check -> no new upgrade operations
  check_openapi_copy --exact openapi.json -> matches the API exactly (no API change)
$ npx vitest run src/lib/safe-next.test.ts -> 31 passed
$ npm run lint -> clean; npm run typecheck -> clean; npm test -> 64 passed (8 files)
$ npm run gen:api -> schema.d.ts unchanged; npm run build -> 66 pages
$ uv run pip-audit -> No known vulnerabilities found
$ node .github/scripts/npm-audit-gate.mjs apps/web
  production: no known advisories; all: 1 high (picomatch, reviewed) -> passed
  (with an empty allow-list -> exit 1; with an expired entry -> exit 1)
$ docker compose -f infra/compose/compose.yaml -f infra/compose/compose.ci.yaml config --quiet -> valid
  (without its variables it refuses, by design)
# the Compose rehearsal: postgres, migrate, api from Compose; seed and worker
# passes from the host; web production build with the new headers
$ curl -i /api/v1/healthz -> 200, content-security-policy: default-src 'none'; frame-ancestors 'none'
$ curl -I /en -> Content-Security-Policy, X-Frame-Options DENY, Permissions-Policy present
$ node e2e/page-weight.mjs -> within budget (home 157.1 KB / 142.3 KB script ...
  product 194.5 KB / 147.0 KB; sign-in 175.5 KB / 147.1 KB)
$ node e2e/seller-dashboard.mjs, buyer-journey, staff-journey, admin-queues,
  setup-and-account -> all passed, "console errors: none"
$ node e2e/shop-screens.mjs -> failed once (see Known problems), then passed
  every step, "console errors: none"
# not run here: Gitleaks (downloading its binary was refused in this
# workspace); it runs in CI. actionlint is not installed; the workflows were
# parsed as YAML and checked on GitHub.
```

On GitHub, all on `3a829d0`: **CI #89** (push) and **CI #90** (pull
request #1) passed every job: API, web, containers (including the new
`--no-proxy-headers` check) and the new security job, where Gitleaks
8.28.0 (checksum OK) scanned 89 commits, 5.43 MB, "no leaks found";
pip-audit "No known vulnerabilities found"; the npm gate printed no
production advisories and the one reviewed picomatch entry, "passed".
**Browser journeys #9** passed in four minutes against Compose: the
page-weight check and all six journeys.

**Tenth session, fifth round** (D-083, provisional answers to F-01 to F-08):

```text
$ uv run pytest tests/api/test_retention.py tests/unit/test_settings_am.py tests/worker -> 32 passed
$ uv run pytest tests/unit/test_provisional_decisions.py -> 8 passed (one marker per F- item)
$ uv run pytest -> 966 passed in 550.82s (0:09:10)
  ruff check -> All checks passed!; ruff format --check -> 187 files already formatted
  mypy markx -> no issues found in 124 source files; alembic check -> no new upgrade operations
  check_openapi_copy --exact, openapi.json and the web copy -> both match the API exactly
```

**Tenth session, fourth round** (D-082, the worker pass that "handled nothing"):

```text
# the cause, read from the demo database
  the pass at 20:02:42 finished exactly 100 messages (run_after 18:01:14 to
  19:31:12.102, finished_at 20:02:42.623 to 20:02:43.734); 68 newer were left
# the two new tests, on the old code first
$ uv run pytest tests/worker -k "not_one_batch or same_pass" -> 2 failed
  (--once left 20 of 220 messages; a message a job queued: done 0, not 1)
# on the fixed code
$ uv run pytest tests/worker -> 25 passed
$ uv run pytest -> 953 passed in 588.89s (0:09:48)
  ruff check -> All checks passed!; mypy markx -> no issues found in 123 source files
# replays on a copy of the demo database (markx_ci)
$ 246 messages waiting 35 minutes, the eight jobs due; one --once -> exit 0,
  outbox_done 247 (with the alert ops.watch opened), none left
$ 196 waiting, then node e2e/admin-queues.mjs (one worker pass for its picture)
  -> 15 steps passed, "console errors: none"; that pass handled 225, none left
# on GitHub, on 00d9ba3
  Browser journeys run #7: success, all six; CI run #85: success
```

**Tenth session, third round** (D-079 to D-081):

```text
# on the final tree (the API last changed in 3511e0e)
$ cd apps/api && uv run pytest ->  951 passed in 595.30s (0:09:55)
  ruff check -> All checks passed!; ruff format --check -> 184 files already formatted
  mypy markx -> no issues found in 123 source files; alembic check -> no new upgrade operations
  check_openapi_copy --exact, openapi.json and the web copy -> both match the API exactly
$ cd apps/web && npm run lint, typecheck -> clean; npm test -> 33 passed (7 files)
  npm run gen:api -> schema.d.ts unchanged; npm run build -> 66 pages
# a rehearsal of the GitHub job on a fresh demo database (markx_ci), in its order
$ seller-dashboard, buyer-journey, staff-journey, admin-queues, shop-screens -> passed, "console errors: none"
$ setup-and-account -> 7 steps passed, then 429 rate_limited in step 8 (the demo buyer's sixth code in the hour)
  after raising the two sign-in limits on that database, as the job now does:
$ setup-and-account -> 13 steps passed, "console errors: none"
# on GitHub (Browser journeys workflow)
  run #2 on 94d5bd3: cancelled while building the web app (the next push; D-081)
  run #4 on b4bff76: success; seller-dashboard 11 steps, buyer 6, staff 6,
    admin 15, shop-screens 14, setup-and-account 13; each "console errors: none"
  run #5 on 876c1d9: success; all six again, every journey now failing on a console error
  GitHub Actions CI run #81 on 876c1d9: success (API, web app, containers)
```

**Tenth session, second round** (the remaining screens, D-076 to D-078):

```text
# the recheck, on ffa2720 before any change
$ cd apps/api && uv run pytest ->  944 passed in 763.73s (0:12:43)
$ cd apps/web && npm run lint, typecheck, test, build -> clean; 29 passed; 56 pages
  GitHub Actions run #57 on ffa2720: success

# on the final tree
$ cd apps/web && npm run lint, typecheck -> clean; npm test -> 33 passed (7 files)
$ npm run gen:api -> schema.d.ts unchanged; npm run build -> 66 pages
$ check_openapi_copy --exact openapi.json and the web copy -> both match the API exactly
$ node e2e/setup-and-account.mjs -> 13 steps passed, "console errors: none"
$ node e2e/seller-dashboard.mjs  -> 11 steps passed, "console errors: none"
$ node e2e/buyer-journey.mjs     ->  6 steps passed, "console errors: none"
$ cd apps/api && uv run pytest ->  948 passed in 736.30s (0:12:16)
  ruff check, ruff format --check, mypy (123 files), alembic check -> clean
$ MARKX_DEMO_TOTP_SECRET=… node e2e/staff-journey.mjs ->  6 steps passed, "console errors: none"
$ MARKX_DEMO_TOTP_SECRET=… node e2e/admin-queues.mjs  -> 15 steps passed, "console errors: none"
  (its first run on this tree stopped at step 13: its worker pass handled
  one batch of 100 messages and left the picture's; solved by D-082)
  GitHub Actions run #63 on b12602a: success
# shop-screens.mjs was not rerun after the second round: the demo buyer is at
# the review hold limit for all three demo shops (Known problems); it passed
# 14 steps on 326ae26
```

**Tenth session** (the web app's owner), against PostgreSQL 17 in Docker,
one test run at a time:

```text
# at the start, on 09a55b0 (the run overlapped this session's first edits)
$ cd apps/api && uv run pytest ->  932 passed, 3 failed in 748.29s
  The 3 failures were the API-description checks (tests/unit/test_openapi_copy.py):
  openapi.json was regenerated on disk while the run held the old code in
  memory. They passed on the new code (19 passed with test_reviews and
  test_reports), and CI #43 had passed all 935 on 09a55b0.

# on the merged tree (d015261: this session's API changes plus the parallel
# session's performance routes and migration 0012); no API change after it
$ uv run pytest               ->  944 passed in 785.57s (0:13:05)
$ uv run ruff check .         ->  All checks passed!
$ uv run ruff format --check . ->  181 files already formatted
$ uv run mypy markx           ->  Success: no issues found in 122 source files
$ uv run alembic upgrade head ->  0011 -> 0012; alembic check: No new upgrade operations detected.
$ check_openapi_copy --exact openapi.json and the web copy -> both match the API exactly

# the web app, on the final tree
$ npm run gen:api             ->  schema.d.ts unchanged
$ npm run lint                ->  no problems
$ npm run typecheck           ->  strict tsc clean
$ npm test                    ->  29 passed (5 files: format, labels, messages,
                                  the admin menu per role, the seller menu per role)
$ npm run build               ->  56 pages
$ MARKX_DEMO_TOTP_SECRET=… node e2e/shop-screens.mjs      ->  14 steps passed, "console errors: none"
$ MARKX_DEMO_TOTP_SECRET=… node e2e/seller-dashboard.mjs  ->  11 steps passed, "console errors: none"
$ MARKX_DEMO_TOTP_SECRET=… node e2e/admin-queues.mjs      ->  15 steps passed, "console errors: none"
$ node e2e/buyer-journey.mjs                               ->  6 steps passed, "console errors: none"
  (both after this session's last change, on the same demo database; the two
  Redmi 13C listings earlier runs had left taken down were relisted first by
  their shops)
```

**Ninth session, final run** — on `b2b674e` plus this session's changes, in
CI's order, against PostgreSQL 17 in Docker with nothing else using the test
database:

```text
$ cd apps/api
$ uv sync --locked
$ uv run ruff check .         ->  All checks passed!
$ uv run ruff format --check . ->  176 files already formatted
$ uv run mypy markx           ->  Success: no issues found in 118 source files
$ uv run alembic check        ->  No new upgrade operations detected.
$ uv run pytest               ->  935 passed in 726.22s (0:12:06)
$ uv run python -m scripts.check_openapi_copy --exact openapi.json         -> openapi.json matches the API exactly.
$ uv run python -m scripts.check_openapi_copy ../web/src/lib/api/openapi.json -> ../web/src/lib/api/openapi.json matches the API exactly.

$ cd apps/web
$ npm ci && npm run gen:api   ->  schema.d.ts regenerated from the current API
$ npm run lint                ->  no problems
$ npm run typecheck           ->  strict tsc clean
$ npm test                    ->  11 passed (3 files)
$ npm run build               ->  36 pages; the four new admin routes rendered per request
$ node e2e/admin-queues.mjs   ->  7 steps passed, "console errors: none"
```

**Ninth session, second half** (the rest of the admin screens, D-071; no API
change), on the final tree:

```text
$ cd apps/api && uv run pytest ->  935 passed in 725.61s (0:12:05)
  ruff check, ruff format --check (176 files), mypy (118 files), alembic check,
  check_openapi_copy --exact and the web copy check -> all clean
$ cd apps/web
$ npm run gen:api             ->  schema.d.ts unchanged
$ npm run lint                ->  no problems
$ npm run typecheck           ->  strict tsc clean
$ npm test                    ->  21 passed (4 files: format, labels, messages, the admin menu per role)
$ npm run build               ->  54 pages
$ node e2e/admin-queues.mjs   ->  15 steps passed, "console errors: none"
```

The journey's 360-pixel check caught one real layout fault on the way: a long
setting name made the settings page 19 pixels wider than a phone; the name
now wraps.

At the start of the session, on `88d481b` before any change: 854 API tests
passed (the sixth session's figure, reproduced exactly), and the web app's
`npm ci`, lint, typecheck, 9 unit tests and build all passed. The head moved
to `b2b674e` during the session (the eighth session's back-end work); this
session's work was re-applied on top of it and every check above was run
again there.

```text
$ cd apps/api                  (the back end's latest run: head `891ac71`, on
                               top of session nine's commits up to `b2e11ce`)
$ uv run pytest               ->  943 passed in 705.61s (0:11:45)
$ uv run ruff check .         ->  All checks passed!
$ uv run ruff format --check . ->  181 files already formatted
$ uv run mypy markx           ->  Success: no issues found in 122 source files
$ uv run alembic check        ->  No new upgrade operations detected.
$ uv run python -m scripts.check_openapi_copy --exact openapi.json
                              ->  openapi.json matches the API exactly.
$ uv run python -m scripts.check_openapi_copy ../web/src/lib/api/openapi.json
                              ->  true for everything it has; 4 additions it lacks
                                  (the performance page and weekly reports)
$ infra/backup/drill.sh markx ->  DRILL PASSED (67 tables, 353 rows, demo data; at 0009)
$ docker build apps/api; docker compose -f infra/compose/compose.yaml up
                              ->  (at 0009) migrations, API and worker healthy, a picture
                                  uploaded to the API container was rendered by the
                                  worker container
```

The web app was not touched in the seventh and eighth sessions; the checks
below are the sixth session's (the ninth session's are above), and CI runs
them on every push.

```text
$ cd apps/web
$ npm run lint                ->  no problems
$ npm run typecheck           ->  strict tsc clean
$ npm test                    ->  9 passed
$ npm run build               ->  11 routes, all rendered per request
$ node e2e/buyer-journey.mjs  ->  completed, "console errors: none"
$ node e2e/staff-journey.mjs  ->  refund decided; isolation 404/403; "console errors: none"
```

The eighth session reproduced the baseline before any change: 858 passed,
lint and formatting clean (138 files), strict types over 90 files, no
migration difference, the API image built. One GitHub push run (#27) failed
on a timing-dependent contention test, fixed in `6fe1ce6` (see "Known
problems" in `docs/HANDOFF.md`, Part A.00).

Run on 17 November 2026 against PostgreSQL 17 in Docker, with nothing else
using the test database. At the start of session six, before any change:
847 passed, a clean lint, 134 formatted files, 89 typed source files, no
migration difference. GitHub Actions runs #1 to #4 on this branch passed
(both jobs once the web job existed). mypy runs in strict mode; the
application code contains no `type: ignore`; the suite treats warnings as
errors. **Never run two test sessions at once**: they share `markx_test`
(session five lost one run to that).

Recounted by the tenth session from `pytest --collect-only` (966 tests, 50 files):

| File | Tests |
| --- | --- |
| `tests/unit/test_codes.py` | 7 |
| `tests/unit/test_ethiopic.py` | 35 |
| `tests/unit/test_images.py` | 9 |
| `tests/unit/test_money.py` | 40 |
| `tests/unit/test_openapi_copy.py` | 6 |
| `tests/unit/test_order_rules.py` | 54 |
| `tests/unit/test_permissions.py` | 144 |
| `tests/unit/test_phone.py` | 31 |
| `tests/unit/test_settings_am.py` | 2 |
| `tests/unit/test_provisional_decisions.py` | 8 |
| `tests/db/test_checkout_contention.py` | 5 |
| `tests/db/test_dispute_contention.py` | 2 |
| `tests/db/test_fulfilment_contention.py` | 4 |
| `tests/db/test_inventory.py` | 14 |
| `tests/db/test_migrations.py` | 8 |
| `tests/db/test_protection.py` | 49 |
| `tests/api/test_addresses.py` | 17 |
| `tests/api/test_admin_takedowns.py` | 8 |
| `tests/api/test_admin_tools.py` | 6 |
| `tests/api/test_auth_otp.py` | 35 |
| `tests/api/test_auth_staff.py` | 14 |
| `tests/api/test_auth_telegram.py` | 7 |
| `tests/api/test_cart.py` | 23 |
| `tests/api/test_catalog.py` | 36 |
| `tests/api/test_checkout.py` | 21 |
| `tests/api/test_csrf.py` | 8 |
| `tests/api/test_delivery.py` | 24 |
| `tests/api/test_disputes.py` | 5 |
| `tests/api/test_exports.py` | 4 |
| `tests/api/test_fulfilment.py` | 14 |
| `tests/api/test_health.py` | 7 |
| `tests/api/test_next_best_offer.py` | 5 |
| `tests/api/test_offers.py` | 42 |
| `tests/api/test_ops.py` | 8 |
| `tests/api/test_performance.py` | 5 |
| `tests/api/test_pictures.py` | 15 |
| `tests/api/test_reports.py` | 4 |
| `tests/api/test_retention.py` | 5 |
| `tests/api/test_reviews.py` | 10 |
| `tests/api/test_search.py` | 30 |
| `tests/api/test_seller_closing.py` | 2 |
| `tests/api/test_search_evaluation.py` | 6 |
| `tests/api/test_search_index.py` | 7 |
| `tests/api/test_seller_documents.py` | 14 |
| `tests/api/test_seller_isolation.py` | 65 |
| `tests/api/test_seller_onboarding.py` | 38 |
| `tests/api/test_seller_staff_permissions.py` | 23 |
| `tests/api/test_seller_team.py` | 13 |
| `tests/api/test_tracking.py` | 2 |
| `tests/worker/test_worker.py` | 25 |
| **Total** | **966** |

Counted by `uv run pytest --collect-only -q` on the final head.

## Database migrations

| Revision | File | What it does |
| --- | --- | --- |
| `0001` | `20261116_1525_initial_schema.py` | All Release 1 tables with their constraints |
| `0002` | `20261116_1540_history_protection_and_ledger_balance.py` | Append-only history tables; ledger balance trigger |
| `0003` | `20261116_1730_fix_ledger_balance_trigger.py` | Corrects the ledger trigger of `0002` |
| `0004` | `20261116_1818_seller_onboarding.py` | `seller_invitations`; the `draft` review state; `sellers.submitted_at`, `sellers.shop_visited_at`, `seller_documents.review_note`; CHECKs that tie trading and levels to approval |
| `0005` | `20261116_2000_offer_staff_hold.py` | `offers.removed_by_staff_at` and a CHECK that keeps a held offer removed (D-032) |
| `0006` | `20261116_2010_scheduled_jobs.py` | `scheduled_jobs`: one row per scheduled job, the row a worker locks to run it (D-035) |
| `0007` | `20261116_2030_order_life_cycle.py` | The seller order state diagram as a database function and trigger; a seller order starts as `placed`; a status without its event is refused at commit (D-038) |
| `0008` | `20261117_0936_product_pictures_and_problem_photos.py` | `product_images` pipeline columns and CHECKs (status, private source, removal record); `problem_photos`, append-only for every role (D-062) |
| `0009` | `20261117_0958_operations_alerts.py` | `ops_alerts`: one open alert per key (D-064) |
| `0010` | `20261117_1056_reviews_and_rating_summaries.py` | `reviews`: the `held` state, the moderation record, length limits; `rating_summaries` (D-066) |
| `0011` | `20261117_1116_listing_reports.py` | `reports`: a note, the reason list, one open report per person and target, closing CHECKs (D-067) |
| `0012` | `20261117_1158_seller_weekly_reports.py` | `seller_weekly_reports`: one row per store and week, starting on a Monday (D-073) |
| `0013` | `20261118_0700_paid_orders_never_end_undelivered.py` | `ck_seller_orders_paid_order_not_ended_undelivered`: a part with a recorded payment never ends declined, expired, cancelled or returned (D-086). Checks existing rows; deletes nothing |
| `0014` | `20261118_0800_payment_recorded_at_handover.py` | `trg_seller_orders_payment_at_handover`: a direct payment is recorded only while the part is delivered, completed or disputed; checks only the moment of recording, so existing records are kept and still move on (D-087) |
| `0016` | `20261118_1645_notification_deliveries_and_order_reminders.py` | `notification_deliveries`: one row per notification and outside channel (unique), its status and reason, never text or a number; `seller_order_reminders`: a reminder sent once per seller order and kind (D-092). Two new tables only |
| `0017` | `20261118_1752_telegram_account_linking.py` | `telegram_link_tokens` (keyed hash of a one-time token, account, session, expiry, status and failure reason; one pending per account; CHECKs pairing status, end time and reason) and `telegram_updates` (handled update ids); `users.telegram_linked_at` (set exactly when `telegram_id` is, by a CHECK; existing links given their `updated_at`) and `users.telegram_unlinked_at` (D-093) |
| `0015` | `20261118_1014_sms_delivery_records.py` | `sms_messages`: one delivery record per SMS, with its CHECKs (purpose and reference agree, a failure has its error code, a 32-byte keyed hash of the number, no text or code column) and three indexes (D-089). A new table only; nothing existing changed |
| `0018` | `20261118_1916_backup_runs.py` | `backup_runs`: every backup, drill and verification: when it ran, its final status, the destination's identity (never a credential), whether it is off the server, whether the set was verified, sizes, object counts and a short error code; the worker's watch alerts from it. The application role may only read it (D-094). Added to this table on 19 November 2026 |
| `0020` | `20261121_0900_telegram_sign_in.py` | `telegram_sign_ins`: each website sign-in with Telegram (keyed hashes of the link's token and of the browser's secret, the Telegram account that opened it, the account it reached, expiry, status and refusal reason; CHECKs tie each status to its fields) and `telegram_init_data_uses`: keyed hashes of Mini App start-up data already used to sign in (M4). Two new tables only (D-101) |

The schema has 77 tables (65 before `0008`; then `problem_photos`, `ops_alerts`, `rating_summaries`, `seller_weekly_reports`, `sms_messages`, `notification_deliveries`, `seller_order_reminders`, `telegram_link_tokens`, `telegram_updates`, `backup_runs`, and in `0020` `telegram_sign_ins` and `telegram_init_data_uses`; corrected on 19 November 2026 from 74, which left out `backup_runs`). P9 and P10 needed no new table and no migration at
all in sessions four and five: the first session's
schema already held carts, orders, seller orders, items, events, reservations,
shipments and payment intents.

## Founder reminders

These are written reminders; nothing in the code fires them.

- **Before production launch:** review the temporary Turnstile credentials
  and rotate the secret before production use. The local "MarkX" widget
  (`localhost`) is for testing only; production gets its own widget.
- **Any time:** the founder may rotate any Turnstile secret whenever they
  wish, for their own security (steps in `docs/SETUP.md`, "Credential
  rotation and the founder's security review").
- **At the 100th real MarkX transaction** (a seller order completed on the
  production site), or earlier whenever the founder asks: a security review
  of the secrets, staff accounts and the audit log, with the Turnstile
  secret rotated. The steps are in `docs/SETUP.md`.
- None of these is permission to put a secret in Git, a file, a document,
  a screenshot or a chat.

## Next task

**Next task: waiting for the founder's choice.**

### Open work for the founder to choose from

The list below was written by the sessions of 16 to 18 November 2026. It
is kept so that nothing is lost; it is **not** a choice. Do only the work
the founder has chosen. The known defects and the audit's findings are at
the top of this file ("State on 19 November 2026").

The earlier sessions' notes: two sessions may work in parallel, one owning
`apps/web` and the other the back end; finish and push each step first.

**Notifications (D-092): the launch blocker.**

1. The founder decides N-1 (Telegram, SMS or both) and creates the bot or
   chooses the SMS provider. Nothing in the code may be switched on before.
2. **Done (D-093): connecting Telegram**, built and OFF. With the founder's
   approval only: create the bot, set the four Telegram settings and
   `MARKX_TELEGRAM_PUSH_PROVIDER=bot_api`, register the webhook, connect the
   founder's own Telegram and receive one real order alert, exactly as in
   `docs/runbooks/telegram-linking.md`; re-read the Bot API documentation
   first (neither session could reach it). And/or F-11's SMS wire format,
   then the activation steps in `docs/DEPLOYMENT.md`.
3. Engineering that needs no account: a staff tool to disconnect a person's
   Telegram (for a lost account), and a deliberate, audited manual resend of
   an order alert that was `unavailable`, if the founder wants one (never
   automatic).
4. Founder items attached: retention of delivery records (with F-12) and a
   native speaker's review of the outside texts (`notifications/texts.py`).

**Deployment (D-091), before anything else touches `infra/production/`:**

1. Confirm that CI's "Production stack rehearsal" job passed on the latest
   commit; it is the only evidence the stack still works. Run
   `sudo -E infra/production/rehearsal/rehearse.sh` locally after any change
   to `infra/production/`, either Dockerfile, `markx/ops/health.py`,
   `markx/core/config.py` or `apps/web/deploy/`.
2. **Done (D-094): off-server backup and disaster recovery, code only.**
   Connecting it needs the founder (F-16, F-19, F-20, F-18) and then the
   steps in `docs/runbooks/backup-and-restore.md`, "Activating off-server
   backups": keys made off the server, the bucket and its two scoped keys,
   `backup.env`, a deploy, a drill and a restore on a separate machine, and
   a test alert received on a phone. Engineering that needs no account:
   a restore that streams very large files instead of reading each into
   memory (pictures are 20 MB at most today); a staff screen listing
   `backup_runs` (the alerts already carry the facts); a second
   destination for the blueprint's weekly copy, if the founder wants it
   automated.
3. Then, still without accounts: the certificate deploy hook named in
   `docs/runbooks/tls-certificates.md`; the re-encryption tool for
   `MARKX_ENCRYPTION_KEY` (`docs/runbooks/secret-rotation.md`); a
   draining stop for the web server.
4. With the founder, in order, each only with written approval: F-17 (the
   domain, the certificate route, Cloudflare or not), the server itself
   (blueprint M.3, O.1), F-01 and F-15 (buckets and the picture domain),
   F-11 (SMS), the Turnstile production widget, F-16 and F-18. Only then a
   first staging deploy with `deploy.sh`, the post-deployment checklist, and
   the blueprint's pre-launch security review (H.7).

**The web app's owner (resuming):**

1. Reproduce the checks and confirm the latest CI run passed.
2. Regenerate the API copy and types whenever the back end has added
   routes: `cd apps/api && uv run python -m scripts.export_openapi
   ../web/src/lib/api/openapi.json`, then `cd ../web && npm run gen:api`
   (D-061). Session ten did this; it was current at its last commit.
3. Every route a person uses has its screen (D-070 to D-078, D-093,
   D-101); the Mini App waits for the bot (founder). To check
   again, compare `apps/api/openapi.json` with the `/api/v1/...` paths in
   `apps/web/src` (the handoff gives the command). A new screen gets its line
   in the admin or seller `menu.ts` and `menu.test.ts`, its words in both
   message files, and a step in one of the browser journeys.
4. The browser journeys run on GitHub on every code push (D-084); add a
   step to one of them for every new screen. `[journeys]` is no longer
   needed. Keep the page-weight check green, and bring the product page
   towards the 150 KB target (D-084).
5. With the back end: delivery speed as a search filter and "total cost to
   the door" as a sort (D.8; they need the buyer's zone in search), and the
   Telegram Mini App shell once the bot exists. A rating on the product
   card is left out on purpose: blueprint D.9's card does not list one
   (D-080).

**The back end:**

0. **Turnstile (D-085) is built; its local test waits for a person.** The
   founder (or an engineer at the founder's computer) runs "Testing
   Turnstile on a laptop" in `docs/SETUP.md` with the "MarkX" test widget,
   typing the secret into the terminal; record the result. Never ask for the
   secret in chat or put it in any file. **Then, only when the founder
   authorises it: the SMS provider** (F-11, blueprint O.23). The
   provider-independent part is built (D-089); what remains is that
   provider's `SmsWireFormat` from its documentation, its tests, the four
   `MARKX_SMS_*` values on the server, and one real message to the founder's
   phone with permission. Never send an SMS without that permission.
0a. **F-09 and F-10 are decided** (D-087, D-088). Do not build a refund
   process or enable any fee until the founder asks. **Before any commission
   is enabled:** the seven items in D-088, the cap first. **With Protected
   checkout:** staff record and verify a refund before an order whose
   payment was captured can close without delivery (D-087).
1. When the founder confirms or changes an F- item (D-083): record it as a
   `D-` entry, change the code if the answer differs, and remove its
   `PROVISIONAL` marker and its line in `test_provisional_decisions.py`.
   F-01 then needs only the founder's private bucket and its
   `MARKX_STORAGE_*` settings: the S3 and R2 adapter already exists
   (`S3ObjectStore`, D-090; corrected on 19 November 2026).
2. Photos on reviews (C-18), following the problem-photo pipeline (D-062).
3. Ratings in search ranking (D.8; the rating filter exists, D-080), and
   the seller rating in the product page's offer ranking, as one change
   with the web app (D-061).
4. The real adapters, each behind its existing interface, once the founder
   decides where things live: SMS (F-11) and Telegram push. **Object
   storage is built** (D-090): once the founder decides F-01 and creates
   the buckets, set the `MARKX_STORAGE_*` values; protecting the buckets
   (F-14) and the pictures' CDN domain (F-15) wait for the founder.
5. The search golden set, only when the founder sends real queries (D-054).

Rules this session asks the next one to keep (in addition to `AGENTS.md`):

1. **Never run two test sessions at once**; they share `markx_test`.
2. **No business rule in the web app.** It shows what the API returns and
   sends the person's choices; the API checks everything again.
3. **No text in code.** Both message files, same keys; the unit test fails
   otherwise. API error codes are shown through `apiErrorText`.
4. **After an API change**, regenerate `openapi.json` and `schema.d.ts`;
   CI fails if they are stale.
5. **A Core `update()`/`insert()` on a table search watches queues the
   rebuild itself** (D-051).
