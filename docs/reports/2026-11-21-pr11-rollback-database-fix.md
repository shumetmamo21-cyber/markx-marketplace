# MarkX: the fix before merging pull request #11

**21 November 2026.** Pull request #11 (server readiness, D-103), on its own
branch `claude/pr10-review-server-readiness-y7novo`. **Not merged**: another
independent review follows. **Nothing was deployed. No server, domain,
account, certificate authority or paid resource was used. No money.**

## Before starting

- Nobody had pushed to the branch since `9d0c888` (checked on GitHub and
  with `git ls-remote` right before the first push).
- Worked on the complete Git history (not a shortened copy).

## The defect

After a failed update, MarkX goes back to the last working release by
itself. For a rare "compatible rollback", the runbook tells the operator to
switch on a setting (`MARKX_ALLOW_NEWER_SCHEMA`) that lets an older release
accept a newer database, and to switch it off with the next update. Nothing
made sure it was switched off, and the pull request's own rehearsal ended
with it still on. Left on, the automatic return asked the old release
whether it accepted the database, the setting made it say yes to any newer
database, and MarkX started old code against an unchecked change and
called it "verified". That can lose data.

## What changed (the founder's rule: go back only when the old release truly accepts the database)

1. **The automatic return checks the old release with the setting forced
   off**, whatever the settings file says. A database the old release does
   not know is refused, and the site stops safely instead. After starting
   the old release, it also checks that it reports the database as
   "current".
2. **An update refuses to start while the setting is on.** It says:
   remove that line from the settings file, then run the update again;
   nothing was changed. The new release also refuses it itself, wherever
   the setting is put.
3. **The rehearsal ends with the setting off** and proves both points,
   including the reviewer's exact case.

## Other ways found and closed the same way

- **A rollback by hand with the setting left on.** Before, a forgotten
  setting let any later rollback start an older release against a newer
  database. Now the setting alone is not enough: the operator must also
  type `--accept-newer-schema` for that one rollback.
- **Backups during a safe stop.** If an update stopped before the new
  release started, the old release's backup service kept running against
  the changed database (old backup code may not know a new table of
  files). The safe stop now runs backups as the release that changed the
  database.
- **A backup by hand after a safe stop** used the old release; it now uses
  the release that changed the database.
- The server check and the status screen now warn while the setting is
  on, and a rollback reminds the operator to remove it.

**Left as it was (for the founder to know):** while an update's database
change runs, the release already running keeps serving for those moments.
That is how every update works without taking the site down; it does not
*start* an older release. Stopping the site for every update instead would
be the founder's choice.

## Proof

**New tests (20), in the normal test suite:**
`tests/deployment/test_deploy_newer_schema.py` (17) runs the real deploy
script against a stand-in for Docker; 3 more test the new release's own
refusal. On the old code (`9d0c888`), 18 of the 20 fail. The 2 that pass
check things that must keep working: a rollback to a release that accepts
the database, and a normal backup. With only a "may be loaded by a test"
line added to the old script, the reviewer's case fails on the old code
with "…running again, verified", which is the defect itself.

**New rehearsal checks (8), on real containers:**

- With the setting on, but without the extra word, a rollback still
  refuses the newer database.
- An update refuses to start while the setting is on, says what to do, and
  changes nothing.
- The server check warns while the setting is on.
- The new release refuses the setting even when it is put somewhere other
  than the settings file.
- **The reviewer's case:** a database carrying a later change, the setting
  on, a failed update. The automatic return checks the old release with
  the setting forced off, refuses, and stops safely.
- In that safe stop, backups run as the release that changed the database.
- A roll forward ends the safe stop (database "current").
- **The rehearsal ends with the setting off:** not in the settings file,
  and not in the running API or worker.

I also ran the new rehearsal against the **old** deploy script: 6 of the new
checks failed, and the reviewer's case printed "rehearsal-2 is running
again, verified".

No existing test, check or rehearsal check was weakened or removed. The
existing compatible-rollback check now also passes `--accept-newer-schema`.

## Test results

| What | Result |
| --- | --- |
| Full API suite, locally (PostgreSQL 17.12, MinIO, nothing skipped) | 2061 passed, 0 skipped (2041 before + 20 new) |
| Lint, format, strict types, API description, image pins | all passed |
| Production rehearsal, locally, final run | 124 passed, 0 failed (116 before) |
| Production rehearsal, locally, first run | 122 passed, 2 failed: both were mistakes in my new checks (not in the deploy script), fixed |
| New rehearsal with the OLD deploy script | 118 passed, 6 failed (the defect reproduced) |
| GitHub, commit `704d15e` | CI #173 success (all 8 checks; 2061 passed; rehearsal 124 passed, 0 failed); Browser journeys #49 success |
| GitHub, commit `46ca31a` | CI #172 cancelled by the newer push; Browser journeys #48 success |

## Documents updated

`docs/DECISIONS.md` (D-103 section 5 records the rule), `docs/DEPLOYMENT.md`,
`docs/runbooks/rollback.md`, `docs/runbooks/deploy.md`,
`docs/DEVELOPMENT_STATUS.md`, `docs/HANDOFF.md`, `docs/ARCHITECTURE.md`,
`infra/production/env/api.env.example`.

## Not verified (UNKNOWN)

- A real server: nothing exists, and nothing was deployed.
