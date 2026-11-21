# Report: pull request #10 reviewed and merged; server readiness (D-103)

**21 November 2026.** Repository `shumetmamo21-cyber/markx-marketplace`,
complete history (the clone was un-shallowed before anything else).
**Nothing was deployed and nothing was paid for.** No account, domain,
certificate authority, Telegram bot, SMS or real server was used; the AWS
connection available in the session was not touched.

---

## Part 1 — Pull request #10 (Telegram for orders, D-102)

### Verdict: no problem that had to be fixed first. Merged.

- Reviewed read-only at **`09136fa`** (the commit you named). I did not
  change it, comment on it or push to its branch.
- Just before merging I checked it had not changed (same latest commit,
  same update time, same base `fe4546f`).
- Merged with a **normal merge** (not a squash), pinned to `09136fa`.
  **The new `main` is `9b3658f`**, a merge commit whose files are exactly
  those of `09136fa`. The pull request's branch is kept.
- **`main` passed its checks:** CI run #169 and Browser journeys run #45,
  both on the first attempt.

### What I checked, and what I found

| Question | Answer, with evidence |
| --- | --- |
| Does every bot action use the website's own permission check and order rules, again at each press? | **Yes.** Every press and command goes through the same seller check the website uses (`seller_membership`, now shared) and the same order and offer functions the website's buttons call. Those lock the order and check the role, that the order belongs to the shop, its state and its deadline. The website adds only one more rule (no staff session), which a Telegram account cannot have. |
| Wrong role, another shop, removed member, blocked or disconnected Telegram, late or repeated answer, step out of order? | **All refused**, each by a test: the `catalogue` and `finance` roles; another shop's order ("That order was not found"); a member removed after the alert; a disconnected Telegram account (only the currently connected one counts) and a blocked account; a closed shop; too late; already answered; "ready" before "accepted"; the `orders` role changing prices. |
| Do messages and presses really come from Telegram? Can a button be changed to act on another order or shop? | Updates are accepted only with Telegram's secret header (compared safely, unchanged). Presses from a group chat, from a bot, or where the chat is not the sender's own are ignored. A button holds only an action and an order number; changing it to someone else's order is refused like a missing one. |
| A press delivered twice acts once; reminders and weekly messages never twice? | **Yes.** Each Telegram update number is stored with the change it made; a repeat changes nothing and shows the current state (tests: a press and a price change sent twice). Reminders and weekly messages go through the existing outbox (tests: sent once even after repeated worker runs). One exception, already documented in D-034: if the worker dies in the instant Telegram accepts a message, it is sent again, marked as such. |
| Tracking link unguessable and minimal? No handover code or personal detail in Telegram? | The link is the existing one: a 256-bit signature over the order and its expiry (60 days). Its page leaves out the handover code, the recipient's name, phones and exact location, and every action. Telegram texts may contain only an order code, a date and whole numbers (tested); a "new handover code" message says only "open MarkX to see it". |
| Every new message in English and Amharic? | **Yes** (tested). A native speaker's review: **UNKNOWN**. |
| New tests fail on the old code for the right reason; nothing weakened? | All **24 new tests fail on `fe4546f`**, because the old webhook ignores button presses and commands, and the Telegram wording does not exist (run in a separate copy with empty stand-ins so the file loads). The pull request adds one test file and changes no existing test, check, workflow, infrastructure file or browser journey. |
| Full test suite locally, nothing skipped? | **API: 2034 passed, 0 skipped**, with the storage service and the backup tools required (CI settings). **Web: 146 passed**; lint, type checks and build passed. Lint, formatting, strict types, migrations check and both API description checks passed. |
| Every GitHub check on the latest commit passed? | **Yes:** CI run #168 (all 8 checks, including the production rehearsal) and Browser journeys run #44. **Note:** journeys #44 passed on its **second attempt**. The first attempt failed in "Reviews, reports, pictures and problem evidence", waiting for "Your review is saved". That is the same intermittent failure already recorded on 18 November, and the pull request changes nothing on that page. |

**Two small observations (not blockers):** a weekly message created before
this release would be missing two new figures and would be refused as
unsafe (no server exists, so none is waiting). A pressed button may keep a
small loading mark in Telegram, because the bot does not send Telegram's
"answer the press" call. Whether it does is **UNKNOWN** without a real bot;
the pull request already says so.

---

## Part 2 — Server readiness (D-103)

Started from the new `main` (`9b3658f`). **No other pull request was open**,
so none could change the same files. Pull request **#11**, not merged: an
independent review follows.

### What changed, in plain words

1. **Certificates.**
   - One command now puts a new certificate in place. It refuses a wrong
     one (another site's, a mismatched key, an expired one) and keeps the
     site up while it switches.
   - Renewal can run by itself twice a day.
   - **MarkX itself now warns 21 days before the certificate expires**
     (urgently in the last 7), even if renewal is never set up. The warning
     goes through the same alert channel as every other MarkX alert.
2. **Going back to an earlier release** now uses whatever image name prefix
   is configured, and takes the backup service back too.
3. **A release that breaks after changing the database** no longer leaves
   a half-working site:
   - If the last working release can use the changed database, MarkX goes
     back to it automatically.
   - Otherwise it stops the site safely: the database and backups keep
     running. It writes down what happened and prints the ways out, in
     order: fix and redeploy; roll back only if the change is
     backward-compatible; restore from the backup taken just before, only
     with your written approval.
4. **Containers.**
   - Every outside image is now fixed to its exact fingerprint (digest),
     and a new automatic check refuses one that isn't.
   - Processor and process limits were added next to the memory limits.
   - The user ids are set in the build instead of assumed.

### What proves each fix

The production rehearsal on a throwaway machine ran **116 checks, 0
failed** (it had 74), plus 7 new automated tests.

| Fix | Proof |
| --- | --- |
| Certificates | 15 rehearsal checks: the alert appears for a nearly expired certificate and clears after a new one; wrong certificates refused and the old one still served; a new one served without restarting; renewal off says so; renewal on works end to end through a stand-in for the certificate tool that contacts nobody; the timer files are accepted by the system. Plus 7 tests (all 7 fail on the old code). |
| Rollback with a prefix | The whole rehearsal now uses a prefix. A rollback moves every service, the backup service included; a missing image is refused. |
| Failed check after an update | A deliberately broken release deployed after a database update: the last working release came back by itself, everywhere. A broken release with a newer database change: the safe stop with instructions, the database and backups still running, then the documented way out. |
| Containers | 16 checks: limits on all six services, the user ids, every outside image by digest. |

**Full API test suite on this branch: 2041 passed, 0 skipped.** Lint,
formatting, strict types and the API description check passed.

### Left switched off for you (founder)

- **`MARKX_TLS_RENEWAL=none`** and **`MARKX_ACME_EMAIL`** (unset): turn on
  once you have chosen the domain and how its certificate is made (F-17).
- **Three provisional values** to confirm or change (D-103):
  - P-103-1: the 21-day warning;
  - P-103-2: the processor and process limits, which depend on the
    server's size (UNKNOWN today);
  - P-103-3: the renewal times.

### Pull request #11 and its checks

**Pull request #11**, latest commit `bf314be`, **not merged**: an
independent review follows.

- **CI run #170: all checks passed.** That covers the production
  rehearsal on GitHub's machines, the containers job with the new digest
  and user-id checks, the API tests, the web app and security.
- **Browser journeys run #46 passed on its second attempt.**
  - The first attempt hit the same "Your review is saved" timeout as pull
    request #10's first attempt. My change does not touch that page.
  - I re-ran only the failed job, once; it passed.
  - That timeout has now happened three times (18 November and twice
    today), so it is worth a separate look. I have not investigated or
    fixed it, because it is outside this task.

### Honest notes

- **Not verified (UNKNOWN):** a real server, domain and Let's Encrypt
  challenge. Alerts reaching a person: the Telegram alert group does not
  exist yet, so alerts go to the log.
- **Two local rehearsal runs failed before the final one,** both because of
  my own new checks, not the fixes. One check read the certificate before
  the proxy had switched to it; another misread a correct answer. Both
  checks are fixed, and nothing in the deployment script changed because
  of them.
- **A slip of mine, contained:** an editing command once ran part of a
  script by mistake in this session's throwaway container. It left a few
  empty folders and tiny files at the container's top level (`/api.env`,
  `/broken-a`, `/broken-b`, `/deploy-3.txt`, `/deploy-4.txt`,
  `/rollback.txt`, `/rollback-ack.txt`, `/renew-on.txt`). A safety check
  stopped me deleting them myself. They are **not in the repository**, hold
  nothing secret, and disappear with the container.
