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

## What exists

| Piece | State |
| --- | --- |
| `python -m markx.backup` (`apps/api/markx/backup/`): one backup **set** = the PostgreSQL dump + every stored file, encrypted, uploaded, read back, signed | **Tested** (pytest on PostgreSQL 17 + MinIO, the CI drill, the rehearsal) |
| The `backup` service in the production Compose file: a set at start-up and daily, retries, retention, health check | **Tested** in the rehearsal; **Real world**: never run for days on a server |
| A set before every migration (`deploy.sh deploy`) and on demand (`deploy.sh backup`) | **Tested** in the rehearsal |
| Restore into a NEW database and EMPTY file stores, with full verification | **Tested** |
| The recovery drill, with seven injected faults | **Tested** in CI on every push (report kept as the `restore-drill` artifact) and in the rehearsal |
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
   read again; a blob already at the destination is not uploaded again.
5. **Upload and verify** each piece: size from the destination, then a full
   read-back compared with the SHA-256 of what was sent.
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
manifest records; and whose every blob exists. `verify --deep` also
decrypts every blob and checks it against the file's own hash.

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
  `status.json` (the health check), `.lock`.

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

## The monthly drill (blueprint F.13)

On the server, by the person who holds the recovery key. It takes a fresh
set, verifies it in full, restores it into a new database and into a
temporary folder (no new bucket is needed), compares everything, drops what
it created and records the result for the watch. It never touches the
running database or the live buckets.

```bash
# The recovery key and signer key come on a USB stick or from the password
# manager, into a folder only root can read, and are removed afterwards.
install -d -m 700 -o 999 -g 999 /root/recovery && cp /media/usb/recovery.key /media/usb/signer-public.key /root/recovery/
chown 999:999 /root/recovery/*; chmod 600 /root/recovery/recovery.key
cd /opt/markx/infra/production
set -a; . /etc/markx/postgres.env; set +a     # in this shell only
docker compose -f compose.yaml --env-file /etc/markx/compose.env run --rm --no-deps \
  -v /root/recovery:/run/recovery:ro \
  -e PGUSER=postgres -e PGPASSWORD="$POSTGRES_PASSWORD" \
  -e MARKX_DB_MIGRATOR_PASSWORD -e MARKX_DB_APP_PASSWORD -e MARKX_DB_READONLY_PASSWORD \
  backup python -m markx.backup drill \
    --recovery-key /run/recovery/recovery.key --signer /run/recovery/signer-public.key
shred -u /root/recovery/recovery.key; rm -rf /root/recovery
```

`MARKX_RELEASE` must be set to the running release (`tail -1
/etc/markx/releases.log`). "DRILL PASSED" and the time it took go into
`docs/DEVELOPMENT_STATUS.md`. **Always pass the three `MARKX_DB_*_PASSWORD`
values** to a restore or a drill on a server (D-091).

Doing the drill on the server puts the recovery key there for minutes. The
safer alternative is a restore on a separate machine (below), which also
proves recovery without the server.

## Restoring

Needs **the founder's written approval** whenever it is meant to replace
live data: everything written since the set is lost. A restore only ever
writes into a NEW database and EMPTY file stores; it never overwrites. You
need: the backup destination's read credentials, the recovery key, the
signer public key, a PostgreSQL 17 server where you are superuser, and the
MarkX code (the `backup` image, or a checkout with `uv`).

1. **Stop the writers** if the live system still runs: `docker compose ...
   stop proxy web api worker backup`. Keep the database running.
2. **Keep what is there.** If PostgreSQL still starts, take a set
   (`deploy.sh backup`). Never delete the old volume or buckets until the
   recovery is verified.
3. **Choose the set**: `python -m markx.backup list --signer signer-public.key`,
   the newest `complete` one from before the damage. Check it:

   ```bash
   python -m markx.backup verify --set <id> --deep \
     --recovery-key recovery.key --signer signer-public.key
   ```
4. **Restore into new targets.** Files go to two new, empty buckets (or a
   folder); the target buckets' keys go in `MARKX_RESTORE_TARGET_ACCESS_KEY_ID`
   and `MARKX_RESTORE_TARGET_SECRET_ACCESS_KEY`, never on the command line.
   The database name must be new and must be typed twice:

   ```bash
   python -m markx.backup restore --set <id> \
     --recovery-key recovery.key --signer signer-public.key \
     --target-db markx_restored --confirm-target markx_restored \
     --target-provider r2 --target-endpoint https://<account>.r2.cloudflarestorage.com \
     --target-private-bucket <new-private> --target-public-bucket <new-public> \
     --report restore-report.json
   ```

   (`--target-files-dir DIR` restores files into a folder; `--no-files`
   restores the database alone.) The restore refuses: a manifest that does
   not verify, a changed piece, an incomplete set (unless
   `--accept-incomplete`, in a disaster only; the report then says FAILED
   for completeness), an existing database, the backed-up database's own
   name, a system database, a mismatched confirmation, non-empty target
   stores and the live buckets.
5. **Read the report.** `RESULT: PASSED` only when: every file restored and
   read back with its checksum, private files only in the private target
   and that target not readable anonymously, the migration version and
   every table's row count equal to the snapshot's, no invalid index or
   unvalidated constraint, the audit log still protected, and every file a
   row refers to present.
6. **Swap**, as the superuser, with nothing connected:
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
   agrees in writing.

**If the whole server is lost:** a new server (`deploy.md`, "Once"), the
settings from where the founder keeps them, then steps 3 to 8 from the
backup destination. Nothing from the old server is needed.

## Retention

`MARKX_BACKUP_RETENTION_DAYS` (0 keeps everything) and
`MARKX_BACKUP_RETENTION_MIN_SETS` are **required** on staging and
production and are the founder's choice (F-20); a laptop defaults to 7 days
and 3 sets. After each successful nightly set the service applies them
(`python -m markx.backup prune` shows the plan; `--execute` applies it):

- the newest `MIN_SETS` complete sets, and always the newest one, are kept
  whatever their age; with no complete set nothing is deleted;
- only sets signed by this service's key count; nothing is deleted because
  of an unsigned or foreign manifest;
- a blob goes only when no kept set lists it and it is older than 48 hours
  (`MARKX_BACKUP_BLOB_GRACE_HOURS`); if any kept set's blob list cannot be
  read and checked, no blob is deleted;
- it runs under the backup lock, and only inside the destination's prefix.
  It never touches the stored files themselves.

Object versioning or an object lock on the backup bucket (where the
provider offers it) would protect sets even against someone holding the
backup key; it is part of F-16.

## Activating off-server backups (needs the founder)

1. **Decide** F-16 (provider and bucket location), F-19 (who keeps the
   recovery key, where) and F-20 (retention).
2. **Keys**, on a trusted machine, never the server:
   `uv run python -m markx.backup keygen --out ./markx-backup-keys`. Store
   `recovery.key` and `signer-public.key` twice, apart; then delete
   `recovery.key` from that machine.
3. **The bucket** (founder's account, written approval): private, no public
   access, no website, versioning or object lock if offered, in the chosen
   location. **Its own access key**, allowed only `ListBucket`, `GetObject`,
   `PutObject`, `DeleteObject` and `AbortMultipartUpload` on that bucket.
   A **read-only key** for the two file buckets (list and get only).
4. `/etc/markx/backup.env` from `infra/production/env/backup.env.example`;
   `/etc/markx/backup-public.key` (root, 644) and
   `/etc/markx/backup-signing.key` (999, 400). `deploy.sh check`.
5. `deploy.sh deploy <release>`: the service starts and takes a set; it
   refuses to start if anything is missing or the destination is not
   off-server.
6. A drill with the recovery key (above), then a restore on a separate
   machine. Record both in `docs/DEVELOPMENT_STATUS.md`.
7. Configure the alert group (F-18) and confirm a test alert arrives on a
   phone. Only then may anyone say MarkX has off-server backups.

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
