# Backups, restores and recovering the database

## What exists (D-063, D-091)

| Piece | State |
| --- | --- |
| `infra/backup/backup.sh`: one encrypted dump (`pg_dump` custom format, AES-256, a checksum) | **Tested** in CI (the drill) and in the rehearsal |
| `infra/backup/restore.sh`: into a NEW database only, never over one | **Tested** in CI and in the rehearsal |
| `infra/backup/drill.sh`: back up, restore, compare every table's rows, check the protections, clean up | **Tested** in CI on the demo data |
| The `backup` service: a dump at start-up and daily at `MARKX_BACKUP_HOUR_UTC`, 30 days kept, healthy only with a dump under 26 hours old | **Tested** in the rehearsal; **Real world**: never run for days |
| A dump before every migration (`deploy.sh`) | **Tested** in the rehearsal |
| **Off-server copies** (blueprint H.2: object storage for 30 days, weekly to the founder's encrypted drive) | **Not built.** Dumps stay on the server's own disk: losing the server loses them |
| **The stored files** (documents, pictures, problem photos) | **Not backed up (F-14, open).** No dump contains them and nothing copies the buckets |
| An alert when a nightly dump fails | **Not built.** It shows only as an unhealthy `backup` container and in its log |

Targets (blueprint H.2): at most 24 hours of data lost, 4 hours to restore.
The first holds only while the dumps survive the server: it does not hold
today.

## Every day

Nothing to do, but look at it once a week (`deploy.sh status`): the backup
container must be `healthy`, and `/var/backups/markx` must hold a new
`markx-markx-<time>.dump.enc` and its `.sha256` per day.

**Until off-server copies are built**, the founder (or someone the founder
names) copies the newest dump and its `.sha256` off the server at least
weekly, to the encrypted drive the blueprint names. The dump is encrypted;
`backup.key` must never travel with it.

## A backup now

```bash
infra/production/deploy.sh backup
```

## The monthly drill (blueprint F.13)

On the server, against the live database, into a throwaway copy that it
drops again; it changes nothing else:

```bash
cd /opt/markx/infra/production
set -a; . /etc/markx/postgres.env; set +a     # the superuser and role passwords, in this shell only
docker compose -f compose.yaml --env-file /etc/markx/compose.env run --rm --no-deps \
  --entrypoint /markx-backup/drill.sh \
  -e PGUSER=postgres -e PGPASSWORD="$POSTGRES_PASSWORD" \
  -e MARKX_DB_MIGRATOR_PASSWORD -e MARKX_DB_APP_PASSWORD -e MARKX_DB_READONLY_PASSWORD \
  -e MARKX_BACKUP_PASSPHRASE_FILE=/run/secrets/backup.key \
  backup markx
```

`MARKX_RELEASE` must be set to the running release (`tail -1
/etc/markx/releases.log`). Write the result ("DRILL PASSED", the time it
took) in `docs/DEVELOPMENT_STATUS.md`.

**Always pass the three `MARKX_DB_*_PASSWORD` values** to a restore or a
drill on a server. Since D-091 `bootstrap.sh` no longer resets a role's
password when its variable is missing; before D-091 a restore without them
set the live roles back to the laptop passwords and stopped the API.

## Recovering the database

When the database is lost or damaged. **Needs the founder's written
approval**: everything written since the dump is lost.

1. **Stop the writers**, keep the database running:
   `docker compose ... stop proxy web api worker`
2. **Keep what is there.** Take a dump of the damaged database too
   (`deploy.sh backup`), if PostgreSQL still starts. Never delete the old
   volume until the recovery is verified.
3. **Choose the dump**: the newest one from before the damage. Check its
   checksum (`sha256sum -c <file>.sha256` in `/var/backups/markx`).
4. **Restore into a NEW database**, `markx_restored`:

   ```bash
   set -a; . /etc/markx/postgres.env; set +a
   docker compose ... run --rm --no-deps --entrypoint /markx-backup/restore.sh \
     -e PGUSER=postgres -e PGPASSWORD="$POSTGRES_PASSWORD" \
     -e MARKX_DB_MIGRATOR_PASSWORD -e MARKX_DB_APP_PASSWORD -e MARKX_DB_READONLY_PASSWORD \
     -e MARKX_BACKUP_PASSPHRASE_FILE=/run/secrets/backup.key \
     backup /backups/<file>.dump.enc markx_restored
   ```
5. **Look at it** (`psql -d markx_restored` inside the postgres container):
   the newest orders, the alembic version.
6. **Swap the names**, as the superuser, with nothing connected:
   `alter database markx rename to markx_damaged_<date>;`
   `alter database markx_restored rename to markx;`
7. **Bring the release that matches the dump's schema back**: if the dump
   is older than the last migration, `deploy.sh deploy` the current release
   (it migrates the restored copy forward) or roll back the code
   (`rollback.md`).
8. Post-deployment verification (`checklists.md`); tell the founder what
   was lost (from the time of the dump to the damage).
9. Drop `markx_damaged_<date>` only after the founder agrees in writing.

**If the whole server is lost:** a new server (`deploy.md`, "Once"), the
same settings from where the founder keeps them, the newest dump copied
back from off the server into `/var/backups/markx`, and from step 4 into a
new database, renamed `markx`. Without an off-server copy there is nothing
to restore: that is why the weekly copy matters until it is automated.

## Stored files (F-14)

Not protected yet. Until the founder decides F-14 (versioning, a second
bucket with a scheduled copy, or a copy to the founder's drive), a deleted
or damaged object in a bucket is lost for good, and the database rows that
point to it remain. No procedure here restores a file.
