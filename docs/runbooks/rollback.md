# Rolling back

**Never carried out on a real server.** `deploy.sh rollback`, the automatic
return after a failed deployment and the safe stop were rehearsed locally
and on GitHub's machines (`rehearse.sh`, "rollback", "a failed update" and
"the setting left on", D-103).

Rolling back means **starting an earlier release's images again**. It never
migrates the database down; there is no down-migration on a server.

## Decide first: code only, or the data too?

1. **No migration since the release you go back to** (compare the two
   commits' `apps/api/migrations/versions/`): a code rollback is safe.
2. **Migrations ran, and the newer release's notes say they are
   backward-compatible** with the release you go back to: a code rollback
   is allowed, acknowledged with one setting and one word on the command
   line (below).
3. **Migrations ran and are not backward-compatible, or nobody knows**: do
   not run old code against the new schema. Roll **forward** with a fix
   instead. If data is damaged and a fix cannot wait, restore the database
   (`backup-and-restore.md`, "Recovering the database"); that loses every
   change since the backup and needs the founder's written approval.

## A code rollback

As root on the server:

```bash
tail /etc/markx/releases.log                        # the earlier releases
infra/production/deploy.sh rollback <earlier-release>
```

It starts that release's API, worker, web app and proxy, waits for them,
then its **backup service** too (D-103), all under the image names of
`MARKX_IMAGE_PREFIX` in `compose.env` (default `markx`). It refuses if any
of the three images (`PREFIX/api`, `PREFIX/web`, `PREFIX/backup`) of that
release is no longer on the server (then
`git checkout` that commit and `deploy.sh deploy` it: a deploy never
migrates down either, so it is the same as a rollback with a rebuild).

It runs the earlier release's preflight first, **with
`MARKX_ALLOW_NEWER_SCHEMA` forced off** (D-103: the founder's rule, go back
only to a release that truly accepts the database). **If the database is
newer than that release** (case 2 above), the preflight says "the database
is newer than this release: do not start it" and nothing is started. Only
for case 2:

1. Add `MARKX_ALLOW_NEWER_SCHEMA=true` to `/etc/markx/api.env`.
2. Run `infra/production/deploy.sh rollback <earlier-release> --accept-newer-schema`.
   Both are needed: the setting alone (for example one left on from an
   earlier rollback) never starts an older release, and the word alone
   is refused too. Readiness reports `"schema": "ahead"` and is ready.
3. **Remove the line again before the next deploy.** `deploy.sh deploy`
   refuses to start while it is on ("MARKX_ALLOW_NEWER_SCHEMA is on …
   Nothing was changed"), and the new release refuses it too, wherever it
   is set. `deploy.sh check` and `status` warn while it is on. Remove it
   just before deploying: the running release keeps the value it started
   with, but if it restarts without the line it stops being ready (safe,
   not silent).

Why the setting must not stay on: if a later deployment failed after its
migration, the automatic return would go back to an older release. It
checks that release with the setting forced off, so it would refuse and
stop safely; but the setting would have made the older release accept any
newer database.

Then the post-deployment verification (`checklists.md`) against the old
release, and a line in `docs/DEVELOPMENT_STATUS.md` saying what happened.

## When a deployment fails after its migration (automatic, D-103)

`deploy.sh deploy` takes a backup, migrates, then checks the new release.
If anything fails **after the migration** (the new release's preflight, its
start, or the readiness of the API, web app and proxy), it never leaves the
new release half-running against the migrated database:

1. **Back on the last working release, automatically**, when that release
   truly accepts the migrated database (no migration in the failed release,
   or one the old release already knows). It is checked with
   `MARKX_ALLOW_NEWER_SCHEMA` **forced off**, whatever `api.env` says, and
   once started it must report the schema as `current` (D-103). Every service, the backup service
   included, runs the last working release again, verified; the log of
   releases says `auto-rollback`; `deploy` exits with an error saying so.
   Fix the release and deploy again.
2. **Otherwise a safe stop** ("A deployment halted", below).

A migration that itself fails changes nothing: PostgreSQL runs it in one
transaction, the running release was not touched, and `deploy` says so.

## A deployment halted

`deploy.sh` stopped the API, the worker and the web app because the last
working release refuses the migrated database (it is newer than that
release), or there is no earlier release, or it did not start either.
`deploy.sh status` and `/etc/markx/deploy-halted` say which release failed
and which was the last working one. In this state:

- PostgreSQL and the backup service run; the backup service runs **as the
  failed release**, the one that migrated the database, never as an older
  one (D-103). The database was backed up just before the migration
  (`python -m markx.backup list` in the backup service shows the set);
  `deploy.sh backup` takes another, also as the failed release.
- Nothing that serves or changes data runs; the proxy answers 502 or 504 (no application answers).

What to do, in this order of preference:

1. **Roll forward**: fix the release, then `deploy.sh deploy <fixed release>`.
2. **Only if the failed release's notes say its migrations are
   backward-compatible** (case 2 above): add `MARKX_ALLOW_NEWER_SCHEMA=true`
   to `/etc/markx/api.env`, then
   `deploy.sh rollback <last working release> --accept-newer-schema`;
   readiness reports `"schema": "ahead"`. **Remove the line before the next
   deploy**, which refuses to start while it is on.
3. **Only with the founder's written approval, if data is damaged**: restore
   the database from the backup taken before the deployment
   (`backup-and-restore.md`, "Recovering the database").

A successful `deploy` or `rollback` removes `deploy-halted`.

## What a rollback does not undo

- Migrations (see above).
- Messages already sent (SMS, Telegram), files already written to the
  buckets, and anything the worker did meanwhile.
- A changed setting in `/etc/markx`: change it back by hand.
