# Backup trust hardening — report (19 November 2026, D-096)

For the founder, in plain English. Nothing here was deployed, no account
was created, no money was spent, and no real storage provider was used:
everything was built and tested with a stand-in (MinIO) and local
PostgreSQL 17.12 containers.

## The short version

Six backup problems from the independent audit are fixed in the code, each
proved by automatic tests: BK-1, BK-2, BK-3, BK-6, BK-7 and BK-17. Before
changing anything I checked that each one was still true in the code
(`main` at `c4a1843`). All six were.

- The server can no longer delete a backup.
- A damaged upload is never reused.
- Drills and restores no longer run on the server.
- A forged backup cannot harm the machine it is restored on.
- A restore can never change the live database's passwords.
- The tests and the automatic checks now use limited keys, as the real
  server will.

The work is in **pull request #4**, which is **not merged**. Reply "merge
approved" when you are ready.

## Each finding

### BK-1 — the server's key could delete every backup (Critical)

- **What was wrong.** The backup service on the server deleted old backups
  itself, so its storage key needed the right to delete. Anyone who broke
  into the server, or stole its settings file, could delete every backup.
  Nothing protected the backups against deletion.
- **What I changed.**
  - The server's backup key may now only add, read and list.
  - Deleting old backups ("retention") is a separate command. It runs on
    another machine, with its own key, and refuses to run on the server.
    It removes old copies completely, and leaves anything that is still
    protected.
  - On staging and production, the backup bucket must have an "object
    lock": nobody, not even the account owner, can delete a backup before
    its time. The service refuses to start without one (**PROVISIONAL**).
  - A file that a new backup reuses has its lock extended, so the newest
    backup is always fully protected.
  - The runbook also describes the other option: the storage provider's
    own expiry rules.
- **Proof.**
  - The server's key is refused when it tries to delete, and cannot run
    retention.
  - A bucket without a lock, with the weaker kind of lock, or with too
    short a lock is refused.
  - In a locked bucket every object is locked, and a reused file stays
    locked.
  - Retention leaves a locked backup whole.
  - Retention removes every old copy and leaves nothing hidden behind.
  - The service never deletes and does not start against an unsafe bucket.
  - Tests: `test_the_servers_backup_key_can_add_read_and_list_but_never_delete`,
    `test_a_required_object_lock_is_checked_and_a_bucket_without_one_is_refused`,
    `test_in_a_locked_bucket_every_object_is_locked_and_a_reused_blob_stays_locked`,
    `test_retention_removes_every_version_and_leaves_no_delete_marker`,
    `test_the_service_backs_up_and_never_deletes_or_runs_retention`,
    `test_the_service_does_not_start_against_an_unsafe_bucket`.

### BK-3 — a damaged upload could be reused (High)

- **What was wrong.** After uploading a file, the backup reads it back to
  check it. If that check failed, the bad file stayed in storage. The next
  backup saw a file with the right name and reused it without checking it,
  then called the whole backup complete and verified.
- **What I changed.**
  - The backup now keeps a record of every file whose check passed: its
    size, its encrypted fingerprint, and the storage's own fingerprint
    taken just after the check.
  - A file is reused only when the storage still shows exactly that.
  - Anything else is uploaded again. That includes a failed upload, a file
    changed since its check, and a file the record does not know.
  - Every backup's index now records each file's size and encrypted
    fingerprint.
  - A backup is called complete only when every file in it passed.
- **Proof.**
  - The audit's own regression test: a file arrives damaged and its check
    fails; the next backup uploads it again, and that backup restores
    correctly.
  - A file changed in storage after its check is uploaded again.
  - The index records each file's size and fingerprint, and a file cut
    short is caught.
  - A backup with one unchecked file is not called complete.
  - Tests: `test_a_blob_whose_upload_failed_its_check_is_uploaded_again_by_the_next_run`,
    `test_a_blob_changed_at_the_destination_since_its_check_is_uploaded_again`,
    `test_the_index_records_each_blobs_encrypted_size_and_hash`,
    `test_a_set_is_complete_only_when_every_blob_in_it_passed`.

### BK-2 — the monthly drill put the recovery key on the server (High)

- **What was wrong.** The monthly drill was done on the production server,
  with the secret recovery key copied onto it, restoring into the
  production database server.
- **What I changed.**
  - The verify, restore, drill and retention commands refuse to run on
    staging and production.
  - A new kind of drill runs on a separate, throwaway "recovery machine":
    your laptop, or a free CI runner. It uses a key that can only read the
    backups, and a private database container with no network at all.
  - It takes no backup and writes nothing to storage.
  - Its report is then entered on the server, so the "drill overdue" alert
    still works.
  - The runbook's drill and restore sections are rewritten to match.
  - The automatic checks run this exact drill on every change.
- **Proof.**
  - The commands refuse to run on staging and production (24 cases).
  - The off-server drill needs only a read-only key and writes nothing.
  - The report is entered on the server, and a report naming a backup that
    does not exist is refused.
  - CI step "Off-server recovery drill".
  - Tests: `test_what_needs_the_recovery_key_or_deletes_never_runs_on_a_server`,
    `test_the_off_server_drill_needs_only_a_read_only_key_and_writes_nothing`,
    `test_record_drill_refuses_a_report_it_cannot_tie_to_a_real_set`.

### BK-6 — a restore ran with full administrator rights (High)

- **What was wrong.** A restore ran as the database administrator. A
  backup forged by someone who had taken over the server could then run
  programs on the recovery machine.
- **What I changed.**
  - The restore now runs as an ordinary database owner, so a forged backup
    cannot run programs.
  - It restores into a throwaway database container with no network and no
    secrets.
  - The runbook now says that backups made after a suspected break-in must
    not be trusted.
  - Backup signing stays on the server for now, as you asked. Moving it
    away is recorded as a later option.
  - Found on the way and fixed: restoring as the ordinary owner would have
    loosened the database's permissions, including the protection of the
    audit log. The restore now prevents that, and a test compares every
    table's permissions with the original's.
- **Proof.**
  - A forged backup that runs a program when restored as administrator is
    refused when restored the MarkX way.
  - Every restored table has exactly the original's owner and permissions.
    This test fails without the fix.
  - The recovery container was checked to have no network.
  - Tests: `test_a_forged_dump_cannot_run_a_program_on_the_recovery_machine`,
    `test_the_restored_copy_is_owned_by_the_owner_role_with_the_sources_exact_grants`.

### BK-7 — a restore could reset production's passwords (Medium)

- **What was wrong.** The old instructions said to give the database
  passwords to every restore. On a server where the database accounts
  already exist, this resets their passwords and could lock the live site
  out.
- **What I changed.** I checked first: the BK-2 refusal alone does **not**
  cover this, because a laptop could still point at the production
  database. So I added the refusal the audit describes. A restore never
  resets an existing account's password, and refuses to run if it is given
  those passwords. The automatic production rehearsal was updated to match.
- **Proof.**
  - The restore is refused, the application can still sign in with its own
    password, and the restore works once the passwords are removed.
  - Test: `test_a_restore_never_resets_the_password_of_an_existing_role`.

### BK-17 — the tests used all-powerful keys (Low)

- **What was wrong.** The tests and the CI drill used the storage
  stand-in's master key, and a PostgreSQL version that was not pinned.
- **What I changed.**
  - Five limited test users: the server's key (cannot delete), the
    recovery machine's key (read only), the retention key, a read-only key
    for the stored files, and a key for the drill's own temporary storage.
  - PostgreSQL is pinned to 17.12.
  - This also proves BK-1 on every run.
- **Proof.** Every backup test and both CI drills now run on these users,
  and CI requires them.

## Branch, pull request, commits and files

- **Branch:** `claude/markx-backup-trust-hardening-4mmhxz`, from `main` at
  `c4a1843`, with the complete history.
- **Pull request:** #4,
  https://github.com/shumetmamo21-cyber/markx-marketplace/pull/4. Not
  merged.
- **Commits:**
  - `ffbfc39` the code;
  - `2b4e179` the tests, CI and the permissions fix;
  - `f9b8c99` the documents;
  - and the commit that adds this report.
- **Changed files:**
  - **backup code:** `apps/api/markx/backup/` (`__main__.py`, `config.py`,
    `database.py`, `destination.py`, `drill.py`, `restore.py`,
    `retention.py`, `runner.py`);
  - **tests:** `apps/api/tests/storage/test_backup_trust.py` (new),
    `apps/api/tests/unit/test_backup_commands.py` (new),
    `apps/api/tests/storage/test_backup_recovery.py`,
    `apps/api/tests/storage/conftest.py`;
  - **scripts:** `infra/backup/minio-least-privilege.sh` (new),
    `infra/backup/recovery-host.sh` (new);
  - **CI:** `.github/workflows/ci.yml`,
    `infra/production/rehearsal/rehearse.sh`;
  - **settings example:** `infra/production/env/backup.env.example`;
  - **documents:** `docs/DECISIONS.md`, `docs/DEVELOPMENT_STATUS.md`,
    `docs/HANDOFF.md`, `docs/DEPLOYMENT.md`,
    `docs/runbooks/backup-and-restore.md`, `docs/runbooks/deploy.md`,
    `docs/runbooks/README.md`, and this report.

**Exactly what changed in CI:**

1. The PostgreSQL service and its tools: `postgres:17` became
   `postgres:17.12`.
2. A new step before the tests creates the limited storage users.
3. The existing drill uses the limited keys instead of the master key.
4. A new step, "Off-server recovery drill", uses the read-only key and a
   database container with no network.
5. A new step always deletes the run's test keys at the end.
6. The drill artifact now also keeps the off-server drill's report.
7. The production rehearsal's drill passes "log in" passwords instead of
   the "reset" ones.

No check was removed or weakened.

## Test results

**On this machine:**

- The whole API test suite: **1789 passed** in 13 min 18 s. That includes
  the 38 new tests, and every earlier test still passes.
- Lint, formatting and strict type checks: clean.
- Both CI drills, run here with CI's exact commands: **DRILL PASSED**, 7 of
  7 injected faults refused, in each.

**On GitHub:** GITHUB_RESULTS

## PROVISIONAL choices for you to confirm

These are also listed in `docs/DECISIONS.md` (D-096) and marked in the
code.

1. **An object lock is required on staging and production.** It costs
   storage, because nothing can be removed before its lock ends. Confirm
   with F-16.
2. **The strict kind of lock ("COMPLIANCE").** Not even you can delete a
   locked backup early, so a mistake costs storage until the lock ends.
   Confirm with F-16.
3. **The lock lasts at least 30 days** (the blueprint's backup period).
   Confirm with F-16 and F-20.
4. **The bucket's own lock period is set to 44 days** (30 + 14), so that
   reused files need their lock extended only about every two weeks. This
   is a recommendation in the runbook. Confirm with F-16.
5. **Retention is run by hand, once a month, after the drill**, from the
   recovery machine. The alternative is the provider's own expiry rules.
   Confirm with F-20.
6. **The recovery machine is the recovery-key holder's own laptop.** A free
   CI runner works the same way, but keeping the real recovery key in a CI
   system is a custody choice. Confirm with F-19.

## To test again on the real provider, once F-16 is decided

1. That a bucket without a lock, with the weak kind of lock, or with too
   short a lock is refused, and the chosen bucket passes.
2. **Cloudflare R2 in particular: UNKNOWN today.** R2 has its own kind of
   lock. Whether it answers the standard lock checks this code makes,
   whether one file's lock can be extended, and whether a locked file can
   be deleted are not verified. Nothing contacted R2. If R2 does not answer,
   the service refuses an R2 bucket on staging and production.
3. That the server's key cannot delete or shorten a lock, and that the
   read-only key cannot write.
4. That every object of a first backup is locked, and that a second backup
   reuses every file. The fingerprints the record relies on must stay the
   same, for large files too.
5. That the provider accepts the upload checksums the storage library
   sends, on a locked bucket.
6. The off-server drill, entering its report on the server, then
   retention, dry run first.
7. A timed full restore, which measures the real recovery time.

The full list is in the runbook: "To test on the real provider".

## Still open from the backup findings

- **BK-4:** alerts that still work if the server is lost.
- **BK-5:** a safe copy, away from the server, of the application's own
  secrets.
- **Backup signing** still happens on the server. Moving it away is a
  later option.
- **Not changed:** BK-8 to BK-16 and BK-18. In particular there is still
  no scheduled deep check of the backups (BK-11).

## Confirmation

No money was spent. No account was created. Nothing was deployed. No real
storage provider was contacted: only MinIO and local Docker containers on
this machine and on GitHub's free test runners. Your AWS servers and
payment bot were not touched.
