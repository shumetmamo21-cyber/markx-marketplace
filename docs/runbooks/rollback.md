# Rolling back

**Never carried out on a real server.** `deploy.sh rollback` was rehearsed
locally (`rehearse.sh`, "rollback").

Rolling back means **starting an earlier release's images again**. It never
migrates the database down; there is no down-migration on a server.

## Decide first: code only, or the data too?

1. **No migration since the release you go back to** (compare the two
   commits' `apps/api/migrations/versions/`): a code rollback is safe.
2. **Migrations ran, and the newer release's notes say they are
   backward-compatible** with the release you go back to: a code rollback
   is allowed, acknowledged with one setting (below).
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

It refuses if that release's images are no longer on the server (then
`git checkout` that commit and `deploy.sh deploy` it: a deploy never
migrates down either, so it is the same as a rollback with a rebuild).

It runs the earlier release's preflight first. **If the database is newer
than that release** (case 2 above), the preflight says "the database is
newer than this release: do not start it" and stops. Only for case 2:

1. Add `MARKX_ALLOW_NEWER_SCHEMA=true` to `/etc/markx/api.env`.
2. Run the rollback again. Readiness reports `"schema": "ahead"` and is
   ready.
3. **Remove the line again** with the next deploy forward, which always
   brings the schema back to `current`.

Then the post-deployment verification (`checklists.md`) against the old
release, and a line in `docs/DEVELOPMENT_STATUS.md` saying what happened.

## What a rollback does not undo

- Migrations (see above).
- Messages already sent (SMS, Telegram), files already written to the
  buckets, and anything the worker did meanwhile.
- A changed setting in `/etc/markx`: change it back by hand.
