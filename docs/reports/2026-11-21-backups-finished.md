# Backups finished before any real data — report (21 November 2026, D-105)

For the founder, in plain English. **Nothing was deployed, no account was
created, no money was spent, and nothing was sent to Telegram or to any
monitoring service.** Everything was built and tested with stand-ins: MinIO
instead of a storage provider, local PostgreSQL 17.12 containers, a pretend
monitor and a pretend Docker on the same machine, and GitHub's free test
machines.

## The short version

All seven items are done and proved by automatic tests: the audit's **BK-4**
and **BK-5**, and the five notes from the review of pull request #4
(**RN-1 to RN-5**). Before changing anything I checked that each one was
still true in the code (`main` at `9daaf57`). All seven were.

- If the server is lost, someone now hears of it.
- The server's own secrets have a safe, locked copy, and the monthly test
  restore proves it works by signing a staff member in.
- A backup file written over is recovered from its locked original, and
  raises an alert.
- The recovery script can no longer delete or stop something that is not
  its own, and its database is private.
- A folder name that is too long now gives a clear "FAILED", not a crash.
- A test-restore report can no longer claim "passed" without showing it.

The work is in **pull request #13**, which is **not merged**. It is backup
security work, so an independent review comes first, as you asked.

## Each item

### BK-4 — alerts that still work if the server is lost

- **What was wrong.** Every alert was raised on the server itself. If the
  server, its database or its background worker stopped, nothing could say
  so. A part of the site that became "unhealthy" told nobody.
- **What I changed.**
  - After each good backup, the server "checks in" with an outside
    monitoring service. When the check-ins stop, that outside service
    alerts you, whatever happened to the server. This is the "dead man's
    switch" the audit asked for.
  - Every five minutes the server checks its own parts. One that stays
    unhealthy, stopped or missing for 15 minutes sends one alert to the
    staff Telegram group through the bot, and one more when it is fine
    again. This works even when the database or the worker is down.
  - One command sends a test alert. It says clearly when nobody was told,
    and it fails then.
  - **Both stay switched off** until you choose the outside monitor and
    create the staff group (your decision F-18).
- **Proof.** 14 automatic tests (the check-in, its address kept secret, the
  test alert, the five-minute check), and the full production rehearsal: a
  part of the site was really paused, found, and an alert attempted.

### BK-5 — a safe copy of the server's own secrets

- **What was wrong.** The backups hold the data, not the server's own
  secrets. After losing the server, the staff sign-in codes in a restored
  copy could not be read, so no staff member could sign in.
- **What I changed.**
  - One command makes **one file** holding the site's keys, the database
    passwords and the certificate key. It is locked with the backup
    recovery key and signed by the server, so it is useless without that
    key and cannot be faked. The secrets are never written or shown in
    plain form, only file names.
  - A copy is also kept in the backup storage, where nobody can delete it.
  - It can only be opened on the separate recovery machine, never on the
    server.
  - **The test restore step the audit asked for.** After the restore, the
    staff sign-in codes must open with the copied key, and then **a staff
    member signs in to the restored copy** with their password and the code
    their phone shows at that moment. The secrets of another server must be
    refused.
  - **For a founder who uses only a phone:** you never have to open the
    file. Whoever runs the server sends it to you; you keep it in the same
    two places as the recovery key (for example your password manager).
    At the monthly test, the staff member who signs in reads the 6-digit
    code from their phone and tells it to the person running the test. You
    can be that staff member.
  - Who keeps the copy, and where, is **your decision F-19**.
- **Proof.** 15 automatic tests, the drill on GitHub (a staff member signed
  in to the restored copy; another server's key refused) and the production
  rehearsal (the copy holds no secret in plain form and opens from the
  backup storage).

### RN-1 — a backup file could be written over

- **What was wrong.** The server's key cannot delete backups, but it can
  write a file again under the same name. The original survives, locked,
  but nothing read it, and nobody was told.
- **What I changed.** Checking, restoring and the test restore now use the
  locked original when a file was written over. The backup service and the
  test restore notice it, and an alert is raised ("someone may hold the
  server's backup key"). The runbook says what to do.
- **Proof.** 2 tests: four parts of a backup written over with rubbish; the
  backup still checks, restores and passes the test restore, and the alert
  is raised. Both fail on the old code.

### RN-2 and RN-3 — the recovery script

- **What was wrong.** It deleted whatever folder its setting named, stopped
  whatever container its setting named, and left its database open to
  every user of the machine.
- **What I changed.** It deletes only a folder it made and marked, stops
  only a container it started and labelled, and keeps the database's
  folder private to its user.
- **Proof.** 6 tests, by hand as two different users (the other user could
  not connect), on GitHub, and in the rehearsal.

### RN-4 — a folder name over 107 characters crashed the test restore

- **What I changed.** It now reports "FAILED" with the reason, and the
  recovery script refuses such a folder before starting.
- **Proof.** 4 tests. On the old code, the test restore crashed.

### RN-5 — the test-restore report was believed

- **What was wrong.** The server recorded a test restore as passed because
  the report said so.
- **What I changed.** The server now checks the report's contents against
  the backup's own signed record: every check present and passed, every
  deliberate fault refused, the right number of files and rows. A report
  that says "passed" without showing it is recorded as **failed**, and an
  alert follows.
- **Proof.** 14 tests, and a new step on GitHub that enters the real report.

## Tests and checks

- **On this machine:** the whole test suite, **2126 passed, 0 failed** (2071
  before; 55 new). Style and strict type checks clean. Both test restores,
  run with GitHub's exact commands: **DRILL PASSED**. The production
  rehearsal: **138 passed, 0 failed** (14 new checks).
- **On the old code:** all 22 new tests for the review notes fail there, for
  the right reasons. The BK-4 and BK-5 tests cannot run there at all,
  because those features did not exist.
- **On GitHub, on the final code (commit `4742a9a`):** **CI #179, all 8
  jobs passed**, including the 2126 tests, both test restores and the
  production rehearsal (138 passed, 0 failed); **Browser journeys #55
  passed**.
- No existing test, check or rehearsal check was removed or weakened.
- Earlier attempts, for the record: the rehearsal first stopped because
  Docker's image service said "too many requests"; the second run found
  two mistakes in the rehearsal itself, now fixed (its pretend settings had
  no encryption key, which the new safety check rightly refused).

## What you must do or decide later

1. **F-18:** choose the outside monitor (it receives the daily check-in and
   alerts you, ideally by a second way such as e-mail) and create the staff
   Telegram group. Then the test alert must reach your phone.
2. **F-19:** who keeps the recovery key **and the secrets copy**, in which
   two places; and which staff member signs in at each monthly test.
3. **F-16 and F-20**, unchanged: the storage provider and how long backups
   are kept. Two new tests are listed for the real provider.
4. Confirm the PROVISIONAL values below.
5. Approve the merge of pull request #13 after the independent review.

## PROVISIONAL values (my safe defaults; please confirm)

1. **P-105-1** One check-in after each good backup; the monitor should
   expect one a day with about 3 hours' grace.
2. **P-105-2** A part of the site must stay unhealthy 15 minutes before an
   alert; checked every 5 minutes.
3. **P-105-3** The "backup file written over" alert stays open 30 days, so
   a quiet night does not close it before someone sees it.
4. **P-105-4** What the secrets copy holds: the site's settings and keys,
   the database passwords, the backup keys and the certificate files.
5. **P-105-5** A copy is also kept, locked, in the backup storage, and old
   copies are never deleted (an old backup needs the secrets of its time).
6. **P-105-6** A test restore counts only with every deliberate fault
   refused. The secrets step is checked when it runs but is not yet
   required, because no copy exists before F-19.

## What is UNKNOWN or not verified

- **"The BT items"** named in the task: no item with that label exists in
  the repository's documents. What was meant is UNKNOWN; I read D-096's
  PROVISIONAL items instead.
- Whether a real Telegram message reaches a phone, and whether a real
  monitor alerts: UNKNOWN until F-18. Nothing was sent.
- Whether Amazon S3 or Cloudflare R2 keep and report older versions the
  way MinIO does: NOT VERIFIED.
- The secrets copy cannot prove the copied "secret key" is the old
  server's: nothing stored depends on it alone. A stale copy would only
  change handover codes and links. So a new copy is needed after any
  secret changes.
- A test-restore report is checked but not signed; someone who controls
  the server and knows the backup's facts could still write a false one.
- **An incident on my own test machine** (a throwaway cloud machine, not
  your computer or any server): a first draft of one test was run once
  against the old recovery script with a dangerous folder setting. I
  checked afterwards: the system files are all present and unchanged in
  their permissions. What changed one folder's timestamp during that run
  is UNKNOWN. The test was rewritten the same hour so it can never touch
  anything outside its own temporary folder, even with the old script.

## Branch, pull request and commits

- **Branch:** `claude/backup-audit-findings-0icpm4`, from `main` at
  `9daaf57`, with the complete history. No other pull request was open, so
  none changes the same files.
- **Pull request:** #13,
  https://github.com/shumetmamo21-cyber/markx-marketplace/pull/13. Not
  merged.
- **Commits:** the code; the tests; CI and the rehearsal; the documents;
  the status and handoff; the rehearsal fix; and a last commit with these
  results and this report.

## Confirmation

No money was spent. No account was created. Nothing was deployed. No real
storage provider, Telegram bot or group, monitoring service or server was
used or contacted: only MinIO, local containers and stand-ins on this
machine and on GitHub's free test machines. Your AWS servers and payment
bot were not touched.
