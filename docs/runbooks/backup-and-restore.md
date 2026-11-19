# Backups, restores and disaster recovery (D-094)

**Status on 18 November 2026: built and tested locally and in CI against
PostgreSQL 17 and MinIO only. NO real backup destination is connected, no
bucket or account exists, no key has been made for a real server, and no
real off-server backup has ever been taken.** Choosing the provider, the
bucket's location, the retention and who holds the recovery key are the
founder's decisions (F-16, F-14, F-19, F-20 in `docs/DECISIONS.md`). Until
they are made and the steps in "Activating off-server backups" are done,
MarkX has **no** off-server backup.

Targets (blueprint H.2): at most 24 hours of data lost, 4 hours to restore.

**Hardened on 19 November 2026 (D-096; audit BK-1, BK-2, BK-3, BK-6,
BK-7, BK-17), tested with PostgreSQL 17.12 and MinIO only.** Three rules
follow from it, and every procedure below keeps them:

1. **Nothing on the server can delete a backup.** The server's backup key
   may only add, read and list. Retention runs elsewhere, with its own key.
   On staging and production the bucket must have an object lock, or the
   backup service does not start (PROVISIONAL, F-16).
2. **The recovery key never comes to the server.** `verify`, `restore`,
   `drill` and `prune` refuse to run on staging and production. Drills and
   restores happen on a separate, throwaway **recovery machine**.
3. **A restore runs as an ordinary role, in a box with no network.** The
   archive is restored as `markx_migrator`, never the superuser, into a
   throwaway PostgreSQL container without network or secrets, and a
   restore never resets a database password.

## What exists

| Piece | State |
| --- | --- |
| `python -m markx.backup` (`apps/api/markx/backup/`): one backup **set** = the PostgreSQL dump + every stored file, encrypted, uploaded, read back, signed | **Tested** (pytest on PostgreSQL 17 + MinIO, the CI drill, the rehearsal) |
| The `backup` service in the production Compose file: a set at start-up and daily, retries, health check; **no retention, no delete** (D-096) | **Tested** in the rehearsal; **Real world**: never run for days on a server |
| A set before every migration (`deploy.sh deploy`) and on demand (`deploy.sh backup`) | **Tested** in the rehearsal |
| Restore into a NEW database and EMPTY file stores, with full verification | **Tested** |
| The recovery drill, with seven injected faults | **Tested** in CI on every push (report kept as the `restore-drill` artifact) and in the rehearsal |
| The off-server drill (`drill --from-destination`) on a throwaway recovery machine, with a read-only key (D-096) | **Tested** in CI on every push: a container with no network, MinIO, test keys. **Real world**: never run against a real bucket |
| Retention away from the server (`prune`, its own key), version- and lock-aware (D-096) | **Tested** against MinIO (versioned and object-locked buckets). **Real world**: never run |
| Object lock required on staging and production (D-096) | **Tested** against MinIO's S3 Object Lock. **NOT VERIFIED** on Amazon S3 or Cloudflare R2 |
| Alerts: failed, incomplete or stale backups; failed or overdue drills (the worker's watch) | **Tested** (generated). **Prepared** (delivered): a person hears of them only once the founder's Telegram alert group is configured (F-18); until then they reach the log only |
| An off-server destination (S3 or R2) | **Founder** (F-16). The code refuses to call anything else off-server |
| `infra/backup/restore-legacy-cbc.sh`: decrypt-and-restore of the retired `.dump.enc` format (D-063) | Kept for old dumps only; nothing makes that format any more |

## How it works

### A backup set

```text
<bucket>/<prefix>/sets/<backup id>/database.dump.mxb   pg_dump custom format, encrypted
<bucket>/<prefix>/sets/<backup id>/files.index.mxb     which file is which blob, encrypted
<bucket>/<prefix>/sets/<backup id>/blobs.txt           opaque blob names the set needs
<bucket>/<prefix>/sets/<backup id>/manifest.json       written LAST, signed
<bucket>/<prefix>/objects/<id[:2]>/<id>                one encrypted blob per distinct file
```

The backup id is the start time and a random part, e.g.
`20261118T230000Z-3fa2c1d0`.

1. **Lock.** One backup at a time, across machines (a PostgreSQL advisory
   lock, plus a file lock in the working folder). A second one is recorded
   `skipped` and leaves.
2. **Snapshot.** One REPEATABLE READ transaction exports its snapshot;
   `pg_dump --snapshot` dumps exactly that instant, and the same transaction
   counts every table's rows and lists every file the rows refer to.
3. **Dump check.** pg_dump must exit 0, the output must be a custom-format
   archive, and `pg_restore --list` must read its table of contents and
   find every table of the snapshot. The plaintext is streamed into the
   encryption; it never touches a disk.
4. **Files, after the snapshot.** Both buckets are listed and each object
   is encrypted into a blob named by a keyed hash of its content. An object
   whose fingerprint (size and ETag) is unchanged since the last run is not
   read again. A blob already at the destination is reused **only** when
   the destination still lists it with the size and the ETag it had right
   after its own read-back passed (the blob ledger, D-096); anything else,
   including an upload whose check failed, is uploaded again over it.
5. **Upload and verify** each piece: size from the destination, then a full
   read-back compared with the SHA-256 of what was sent; with an object
   lock, the object must also be locked. A reused blob whose lock would end
   too soon has it lengthened.
6. **Manifest last**, signed. Only now does the set exist.

**Why the files match the database.** Every MarkX upload writes the file
before the row that names it commits, and no feature deletes or rewrites a
stored file (D-062, D-090). So every file the snapshot refers to already
exists when the listing starts, after the snapshot. If one is nevertheless
missing, the set is marked **incomplete**: it is signed and kept as
evidence, a restore refuses it by default, and the watch alerts. *Any
future feature that deletes files must delete the row first and the file
after; otherwise this guarantee no longer holds.*

**A recoverable set** is one whose manifest is present, verifies against a
trusted signer key, and says `complete`; whose every piece has the hash the
manifest records; and whose every blob exists with the encrypted size the
index records. `verify --deep` also decrypts every blob and checks it
against the file's own hash, and reports any blob uploaded again since the
set was made (other encrypted bytes, the same file). A set is written
`complete` only when every one of its blobs passed its check.

### Encryption and keys (`markx/backup/crypto.py`)

Format **MXB2**: X25519 key agreement with a fresh ephemeral key per file,
HKDF-SHA256 to a per-file key, AES-256-GCM in 1 MiB chunks with a counter
nonce and a last-chunk flag (the STREAM construction), the header
authenticated with every chunk. A changed byte, a reordered, dropped or
repeated chunk, a file cut short or extended, and a wrong key are all
refused. Library: `cryptography` (already a dependency).

| Key | Made by `keygen` as | Lives | Secret? |
| --- | --- | --- | --- |
| Recovery key (X25519 private) | `recovery.key` | **OFF the server**, in two separate safe places the founder controls | **Yes, the most important one** |
| Recipient public key | `backup-public.key` | the server, `/etc/markx/backup-public.key` (root, 644) | No |
| Signing key (Ed25519) | `signing.key` | the server, `/etc/markx/backup-signing.key` (999, 400) | Yes |
| Signer public key | `signer-public.key` | with the recovery key, and anywhere | No |

The server can encrypt but **cannot decrypt** its own backups: a stolen or
lost server reveals no backup. A restore needs the recovery key and the
signer public key, nothing from the server. The application's
`MARKX_SECRET_KEY` and `MARKX_ENCRYPTION_KEY` are never used. `deploy.sh
check` refuses a recovery key found in `/etc/markx`.

Not a cloud key service: the recovery key is a file the founder keeps (a
password manager with emergency access, an encrypted USB key in a safe, a
printed copy in a sealed envelope: F-19 chooses). Keeping it in the same
place as the server's passwords would not protect against losing both.

**If the recovery key is lost:** every set encrypted to it is unreadable,
by anyone, for ever. There is no back door. Do immediately: make a new key
pair, put the new public key on the server, take a backup at once
(`deploy.sh backup`), check it with a drill using the new recovery key, and
store the new key twice. Older sets stay unrecoverable; retention removes
them in time.

**Rotating keys** (yearly, or when anyone who had the recovery key leaves):
`keygen` on a trusted machine, the new `backup-public.key` (and
`backup-signing.key`) to `/etc/markx`, restart the `backup` service, take
a set, drill with the NEW recovery key. **Keep the OLD recovery key and old
signer public key** until no set made with them is kept (`list` shows each
set; the manifest names its `recipient_key_id`). A restore accepts several
`--recovery-key` and `--signer` files and picks the right one. Blob names
include the key, so the first set after a rotation re-uploads every file
once.

### What the server holds

`/var/backups/markx` (the container's `/backups`), owner 999, mode 700:

- `incoming/<id>/` the set being made;
- `sets/<id>/` the last `MARKX_BACKUP_LOCAL_KEEP_SETS` (default 2) sets
  whose remote copy was verified: a convenience for a fast restore, **not
  an off-server backup**; only a verified one is ever removed;
- `failed/<id>/` the evidence of failed attempts (the encrypted pieces, the
  tools' output, `report.json` with the error and its trace), the newest
  10 kept;
- `file-catalog-<keys>.json` (which object is which blob, for the next run;
  one per key pair, so no blob of an old key is reused after a rotation),
  `blob-ledger-<keys>.json` (each blob whose read-back passed: its
  encrypted size and SHA-256 and the destination's ETag right after; a
  blob not in it, or listed otherwise, is uploaded again), `status.json`
  (the health check), `.lock`. Losing this folder costs one full upload of
  every file at the next set (on a versioned bucket, the old copies stay
  until retention), never a backup.

Files are mode 600 (the service runs with `umask 077`).

## Every day

Nothing to do if alerts reach a person. Once a week, or whenever an alert
says so: `deploy.sh status` (the backup container must be `healthy`), and

```bash
cd /opt/markx/infra/production
docker compose -f compose.yaml --env-file /etc/markx/compose.env run --rm --no-deps backup \
  python -m markx.backup list
```

The newest line must say `complete` and be from the last night.

**Alerts** (`markx/ops/checks.py`, the worker's watch every 5 minutes,
switched on automatically on staging and production):

| Key | When | Severity |
| --- | --- | --- |
| `backup.failed` | the last attempt failed or its process died | critical |
| `backup.incomplete` | the last set misses files the database refers to | critical |
| `backup.stale` | no verified **off-server** set newer than `MARKX_BACKUP_MAX_AGE_HOURS` (26); also when none ever existed | critical |
| `backup.drill_failed` | the last restore drill failed | critical |
| `backup.drill_overdue` | no drill passed in `MARKX_RESTORE_DRILL_MAX_AGE_DAYS` (35) | warning |

Each attempt's record (`backup_runs`: status, sizes, object counts, the
destination's identity, the error code) is what the watch reads. An alert
**generated** here goes through the outbox to the alert channel: the
founder's Telegram group once `MARKX_TELEGRAM_BOT_TOKEN` and
`MARKX_ALERT_TELEGRAM_CHAT_ID` are set, **otherwise only the log, which no
one reads by itself** (F-18). The backup container's health check is a
second, local signal: `unhealthy` when no verified set is fresh.

## A backup now

```bash
infra/production/deploy.sh backup
```

Exit 0 means a complete, verified set exists. `deploy.sh deploy` takes one
before every migration and stops if it fails.

## The recovery machine (D-096)

Every drill and every restore runs here, **never on the server**. It is a
throwaway machine: the recovery-key holder's own laptop (PROVISIONAL
P-096-6), or a free CI runner (CI does exactly this on every push, with
test keys and MinIO). It needs:

- Docker, and a checkout of the MarkX repository at the release that made
  the set (or newer) with `uv` (`cd apps/api && uv sync --locked`);
- the backup bucket's **read-only key** (list and get only; never the
  server's key, never the retention key);
- `recovery.key` and `signer-public.key`, from where the founder keeps them
  (F-19), into a folder only you can read, removed afterwards;
- **nothing from the server**: no `/etc/markx` file, no database password,
  no `MARKX_SECRET_KEY`, no SSH key to the server.

The database it restores into is a **throwaway PostgreSQL 17.12 container
with no network at all**, reached only through a socket folder, holding no
secret. `infra/backup/recovery-host.sh` makes it and removes it with all
its data. The restore runs as the `markx_migrator` role, never the
superuser, so even a forged backup cannot run a program there, and a
restore never resets a role's password (D-096).

```bash
cd markx-marketplace/apps/api
install -d -m 700 ~/markx-recovery && cp /media/usb/recovery.key /media/usb/signer-public.key ~/markx-recovery/
chmod 600 ~/markx-recovery/recovery.key
# The bucket, read-only (in this shell only; never on a command line you save):
export MARKX_BACKUP_DESTINATION=s3   # or r2, as F-16 chose
export MARKX_BACKUP_DESTINATION_ENDPOINT_URL=https://<endpoint> MARKX_BACKUP_DESTINATION_REGION=<region>
export MARKX_BACKUP_DESTINATION_BUCKET=<backup bucket> MARKX_BACKUP_DESTINATION_PREFIX=markx/production
read -rs MARKX_BACKUP_DESTINATION_SECRET_ACCESS_KEY; export MARKX_BACKUP_DESTINATION_SECRET_ACCESS_KEY
export MARKX_BACKUP_DESTINATION_ACCESS_KEY_ID=<read-only key id>
eval "$(../../infra/backup/recovery-host.sh start)"   # the throwaway PostgreSQL, no network
```

Do **not** set `MARKX_ENV` (the commands refuse staging and production), and
do not set any `MARKX_DB_*_PASSWORD` (a restore never resets one).

**When you are done, always:**

```bash
../../infra/backup/recovery-host.sh stop      # the container and its data are gone
shred -u ~/markx-recovery/recovery.key; rm -rf ~/markx-recovery
unset MARKX_BACKUP_DESTINATION_SECRET_ACCESS_KEY
```

### Backups made after a suspected break-in are not trusted

The server holds the key that signs manifests (moving signing off the
server is a later option, D-096). Someone in control of the server can
therefore make sets that verify perfectly and hold anything. If a break-in
on the server is suspected from a moment T:

- **trust no set made after T**, however well it verifies; restore the
  newest complete set made **before** T (`created_at` in `list`);
- restore it only on the recovery machine as above (no network, the owner
  role), never anywhere that holds secrets;
- treat the signing key as stolen: make a new key pair (`keygen`, off the
  server), and after the server is rebuilt, sign only with the new one;
  keep the old `signer-public.key` only to read sets made before T.

## The monthly drill (blueprint F.13)

On the recovery machine (above), by the person who holds the recovery
key. It takes **no** backup and writes **nothing** to the bucket: it picks
the newest complete set the server made, verifies it in full (every blob
decrypted), restores it into a new database in the throwaway PostgreSQL and
the files into a temporary folder, compares everything, proves on a local
copy that seven kinds of tampering are refused, removes what it made, and
writes a report.

```bash
uv run python -m markx.backup drill --from-destination \
  --recovery-key ~/markx-recovery/recovery.key --signer ~/markx-recovery/signer-public.key \
  --report ~/drill-$(date -u +%Y%m%d).json
```

"DRILL PASSED" and the time it took go into `docs/DEVELOPMENT_STATUS.md`.
(`--set <id>` drills another set than the newest.) Then enter the result
on the server, so the watch knows a drill passed (`backup.drill_overdue`).
The report holds no secret; `record-drill` checks that its set exists and
verifies with the server's own signer:

```bash
scp ~/drill-<date>.json <server>:/tmp/
# on the server:
cd /opt/markx/infra/production
docker compose -f compose.yaml --env-file /etc/markx/compose.env run --rm --no-deps \
  -v /tmp/drill-<date>.json:/run/drill.json:ro backup python -m markx.backup record-drill --report /run/drill.json
```

Then retention, if it is due (below), and the cleanup of the recovery
machine. On a laptop or in CI, `python -m markx.backup drill` (without
`--from-destination`) is the **rehearsal**: it takes a new set first, from
a laptop's or CI's own database, which needs the signing key. It refuses
staging and production like every drill.

## Restoring

Needs **the founder's written approval** whenever it is meant to replace
live data: everything written since the set is lost. A restore only ever
writes into a NEW database and EMPTY file stores; it never overwrites. It
always starts on the recovery machine (above).

1. **Stop the writers** if the live system still runs: `docker compose ...
   stop proxy web api worker backup`. Keep the database running.
2. **Keep what is there.** If PostgreSQL still starts, take a set
   (`deploy.sh backup`). Never delete the old volume or buckets until the
   recovery is verified.
3. **Choose the set**, on the recovery machine:
   `uv run python -m markx.backup list --signer ~/markx-recovery/signer-public.key`,
   the newest `complete` one from before the damage (and from before any
   suspected break-in, above). Check it:

   ```bash
   uv run python -m markx.backup verify --set <id> --deep \
     --recovery-key ~/markx-recovery/recovery.key --signer ~/markx-recovery/signer-public.key
   ```
4. **Restore it into the throwaway PostgreSQL** and a folder, and read the
   report:

   ```bash
   uv run python -m markx.backup restore --set <id> \
     --recovery-key ~/markx-recovery/recovery.key --signer ~/markx-recovery/signer-public.key \
     --target-db markx_restored --confirm-target markx_restored \
     --target-files-dir ~/markx-restored-files --report restore-report.json
   ```

   The restore refuses: a manifest that does not verify, a changed piece, a
   blob of the wrong size, an incomplete set (unless `--accept-incomplete`,
   in a disaster only; the report then says FAILED for completeness), an
   existing database, the backed-up database's own name, a system database,
   a mismatched confirmation, non-empty target stores, the live buckets,
   and any `MARKX_DB_*_PASSWORD` given where the MarkX roles already exist.
   `RESULT: PASSED` only when: every file restored and read back with its
   checksum, private files only in the private target and that target not
   readable by others, the migration version and every table's row count
   equal to the snapshot's, no invalid index or unvalidated constraint, the
   audit log still protected from `markx_app`, and every file a row refers
   to present. Look at the data you expect to recover (as `markx_migrator`,
   through the socket: `psql -h "$PGHOST" -U markx_migrator markx_restored`).
5. **Put it in place**, once the founder agrees in writing. The verified
   set is restored a second time, now into the **new or repaired server's**
   PostgreSQL, still run from the recovery machine (through an SSH tunnel
   to that server's database port), into a new name:
   - point `PG*` at the server's PostgreSQL superuser through the tunnel
     (in this shell only), with `MARKX_RESTORE_OWNER_PASSWORD` and
     `MARKX_RESTORE_APP_PASSWORD` the roles' real passwords; **never**
     `MARKX_DB_*_PASSWORD` (a restore never resets them and refuses them).
     On a brand-new server whose roles do not exist yet, give the three
     `MARKX_DB_*_PASSWORD` values instead: they create the roles;
   - files into two new, empty buckets: `--target-provider s3|r2
     --target-endpoint ... --target-private-bucket <new-private>
     --target-public-bucket <new-public>`, their keys in
     `MARKX_RESTORE_TARGET_ACCESS_KEY_ID` and
     `MARKX_RESTORE_TARGET_SECRET_ACCESS_KEY`, never on the command line;
   - the archive is again restored as `markx_migrator`, never the superuser.
6. **Swap**, on the server, as the superuser, with nothing connected:
   `alter database markx rename to markx_damaged_<date>;`
   `alter database markx_restored rename to markx;`
   Point `MARKX_STORAGE_PRIVATE_BUCKET`/`_PUBLIC_BUCKET` at the restored
   buckets (or copy the objects back into new live buckets), and the
   picture CDN at the new public bucket.
7. **The release that matches the set's schema** (`application.release` and
   `alembic_revision` in the manifest): `deploy.sh deploy` the current
   release (it migrates forward) or roll back the code (`rollback.md`).
8. Post-deployment checks (`checklists.md`); tell the founder what was lost
   (from the set's `created_at` to the damage).
9. Drop `markx_damaged_<date>` and the old buckets only after the founder
   agrees in writing. Clean up the recovery machine (above).

**If the whole server is lost:** a new server (`deploy.md`, "Once"), the
settings from where the founder keeps them, then steps 3 to 8 from the
backup destination. Nothing from the old server is needed.

## Retention (away from the server, D-096)

`MARKX_BACKUP_RETENTION_DAYS` (0 keeps everything) and
`MARKX_BACKUP_RETENTION_MIN_SETS` are the founder's choice (F-20); they are
required on staging and production and whenever retention deletes from
off-server storage; a laptop defaults to 7 days and 3 sets. **The server
never applies them**: its key cannot delete. Retention is run on the
recovery machine (PROVISIONAL P-096-5: by hand, monthly, right after the
drill) with the **retention key**, the only key that may delete, kept with
the recovery key and never on the server:

```bash
export MARKX_BACKUP_RETENTION_DAYS=<days> MARKX_BACKUP_RETENTION_MIN_SETS=<sets>
export MARKX_BACKUP_DESTINATION_ACCESS_KEY_ID=<retention key id>   # and its secret, read -rs
uv run python -m markx.backup prune --signer ~/markx-recovery/signer-public.key            # the plan
uv run python -m markx.backup prune --signer ~/markx-recovery/signer-public.key --execute  # apply it
```

- the newest `MIN_SETS` complete sets, and always the newest one, are kept
  whatever their age; with no complete set nothing is deleted;
- only sets signed by the trusted signer count; nothing is deleted because
  of an unsigned or foreign manifest;
- a blob goes only when no kept set lists it and it is older than 48 hours
  (`MARKX_BACKUP_BLOB_GRACE_HOURS`), so a backup running at the same moment
  is safe; if any kept set's blob list cannot be read and checked, no blob
  is deleted;
- **every version** of an object is removed, so a versioned bucket really
  frees the space and keeps no delete marker; objects already hidden behind
  a delete marker are removed too once older than the retention period,
  unless a kept set needs them;
- **an object still under its lock stays**: retention says how many it
  left, and a later run removes them; a set whose manifest is still locked
  is left whole, so a half-deleted set never looks complete;
- only inside the destination's prefix; it never touches the stored files.

**The alternative: the provider's own expiry rules** ("lifecycle rules").
They need no retention key at all, which is simpler, but they delete by age
alone: they cannot know which sets are complete, keep the newest set, or
see that a new set still needs an old blob. If they are used, they may
expire **only** the `sets/` prefix after the retention period, and
**never** objects under `objects/` (old blobs are still needed by new
sets); blobs no set needs are then left for `prune` to remove. On a
versioned bucket, a rule may also remove noncurrent versions, again never
under `objects/`. Which way is the founder's choice (F-20).

**The object lock and retention together.** With the lock (below),
nothing can be removed before its lock ends, by anyone. Set the bucket's
default retention to the minimum lock plus about two weeks (PROVISIONAL
P-096-4: 30 + 14 = 44 days), so that a reused blob's lock is lengthened
about once a fortnight; the bucket then holds at least about 44 days of
sets whatever `MARKX_BACKUP_RETENTION_DAYS` says.

## Activating off-server backups (needs the founder)

1. **Decide** F-16 (provider and bucket location), F-19 (who keeps the
   recovery key, where) and F-20 (retention).
2. **Keys**, on a trusted machine, never the server:
   `uv run python -m markx.backup keygen --out ./markx-backup-keys`. Store
   `recovery.key` and `signer-public.key` twice, apart; then delete
   `recovery.key` from that machine.
3. **The bucket** (founder's account, written approval): private, no public
   access, no website, in the chosen location, created **with S3 Object
   Lock enabled** (whether it can be switched on later is the provider's
   rule: check it, UNKNOWN here), a
   default retention in **COMPLIANCE** mode of at least
   `MARKX_BACKUP_OBJECT_LOCK_MIN_DAYS` (30) days, 44 recommended
   (PROVISIONAL P-096-1 to P-096-4). Staging and production refuse to start
   the backup service without it. Then **three keys on that bucket**, each
   for one place:
   - **the server's key** (into `backup.env`): `ListBucket`,
     `GetBucketLocation`, `GetBucketObjectLockConfiguration`,
     `ListBucketMultipartUploads`, `PutObject`, `GetObject`,
     `GetObjectRetention`, `PutObjectRetention` (COMPLIANCE only ever
     lengthens a lock), `AbortMultipartUpload`, `ListMultipartUploadParts`.
     **No `DeleteObject`, no `DeleteObjectVersion`, no bypass of the lock,
     no bucket settings.**
   - **the recovery machine's read-only key**: `ListBucket`,
     `GetBucketLocation`, `GetBucketObjectLockConfiguration`, `GetObject`,
     `GetObjectRetention`. Kept with the recovery key.
   - **the retention key**: the read-only key's rights plus
     `ListBucketVersions`, `GetObjectVersion`, `DeleteObject`,
     `DeleteObjectVersion`. Kept with the recovery key, never on the server.

   `infra/backup/minio-least-privilege.sh` shows the same three policies
   for MinIO. A **read-only key** for the two file buckets (list and get
   only).
4. `/etc/markx/backup.env` from `infra/production/env/backup.env.example`;
   `/etc/markx/backup-public.key` (root, 644) and
   `/etc/markx/backup-signing.key` (999, 400). `deploy.sh check`.
5. `deploy.sh deploy <release>`: the service starts and takes a set; it
   refuses to start if anything is missing or the destination is not
   off-server.
6. **Prove the key's limits once, by hand:** with the server's key, a
   delete of any object must be refused; with the read-only key, a write
   must be refused. Then the drill on the recovery machine (above), its
   `record-drill` on the server, and a timed restore on the recovery
   machine (the measured RTO). Record all in `docs/DEVELOPMENT_STATUS.md`.
7. Configure the alert group (F-18) and confirm a test alert arrives on a
   phone. Only then may anyone say MarkX has off-server backups.

## To test on the real provider, once F-16 is decided (D-096)

Built and tested against MinIO only. Before anyone says MarkX has
off-server backups, on the chosen provider, with the founder's approval:

1. The object-lock check: a bucket without a lock, with GOVERNANCE, and
   with too short a period are each refused; the chosen bucket passes.
2. **Cloudflare R2 especially (UNKNOWN today):** whether R2's "bucket
   locks" answer `GetObjectLockConfiguration`, whether `PutObjectRetention`
   lengthens one object's lock, whether a locked object's version can be
   deleted (it must not), and whether a head returns the lock date. If R2
   does not answer these, the code refuses an R2 bucket on staging and
   production; the choice is then S3, or a code change for R2's own lock
   API, decided by the founder.
3. The server's key cannot delete (`DeleteObject`, `DeleteObjects`,
   `DeleteObjectVersion`), cannot shorten a lock and cannot change bucket
   settings; the read-only key cannot write.
4. A first set: every object locked; ETags as listed equal ETags after
   upload (the blob ledger relies on it; for multipart uploads too); a
   second set reuses every blob (`new_blobs: 0`).
5. Upload checksums: boto3 sends its default checksums on every upload;
   check the provider accepts them on a locked bucket.
6. `drill --from-destination` from a recovery machine with the read-only
   key; `record-drill` on the server; then `prune` with the retention key,
   dry run first: locked objects reported as held, nothing else removed.
7. A timed full restore (the RTO).

## Legacy dumps (D-063)

Before D-094 the backup wrote `markx-<db>-<time>.dump.enc` with `openssl
enc -aes-256-cbc` (not authenticated) and a passphrase file beside the
server's other secrets. MarkX was never deployed, so no real dump in that
format exists. If one exists on a laptop, it can still be restored into a
new database:

```bash
MARKX_BACKUP_PASSPHRASE_FILE=~/markx-backup.key \
  infra/backup/restore-legacy-cbc.sh var/backups/<file>.dump.enc markx_restored
```

Then take a new set of the restored data in the new format if it is worth
keeping, and destroy the old dump and passphrase.
