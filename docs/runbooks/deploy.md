# Deploying

**Never carried out on a real server** (none exists). Rehearsed locally,
end to end, by `infra/production/rehearsal/rehearse.sh`.

## Once: preparing a new server

Only after the founder has approved the server, its monthly cost and where
it lives (blueprint M.3, O.1). These steps are the founder's or done with
the founder.

1. A long-term-support Ubuntu server, at least 2 GB of memory, an encrypted
   disk, automatic security updates, a firewall admitting 80 and 443 only
   (Cloudflare's ranges only, if Cloudflare is in front), no SSH port open
   to the world (blueprint M.3). Docker Engine and the Compose plugin from
   Docker's own repository.
2. The code: `git clone` the repository to `/opt/markx` and check out the
   commit to deploy. The server needs read access to the repository only.
3. The settings, as root:

   ```bash
   install -d -m 700 /etc/markx /etc/markx/tls
   cd /opt/markx/infra/production/env
   for f in *.env.example; do install -m 600 "$f" "/etc/markx/${f%.example}"; done
   ```

   Then edit each file and replace every `REPLACE_WITH_…` and every
   `example.invalid`. Generate each secret on the server (the commands are
   in the files); never reuse one and never send one over chat. Keep
   `MARKX_ENCRYPTION_KEY` also where the founder keeps recovery material:
   without it the encrypted columns cannot be read.
4. The backup keys and folder (D-094; `backup-and-restore.md`, "Activating
   off-server backups": the destination, the recovery key's keeper and the
   retention are the founder's decisions F-16, F-19, F-20). The keys are
   made on a trusted machine, never on the server; only the PUBLIC key and
   the signing key come here, the recovery key never does:

   ```bash
   install -o 0 -g 0 -m 644 backup-public.key /etc/markx/backup-public.key
   install -o 999 -g 999 -m 400 signing.key /etc/markx/backup-signing.key
   install -d -o 999 -g 999 -m 700 /var/backups/markx
   install -d -m 755 /var/lib/markx/acme
   ```
5. The certificate: `tls-certificates.md`.
6. `infra/production/deploy.sh check` until it says `check: PASSED`.

## Every release

As root on the server, after the pre-deployment checklist:

```bash
cd /opt/markx
git fetch origin && git checkout --detach <commit>
infra/production/deploy.sh deploy "$(git rev-parse --short HEAD)"
```

What it does, and stops at the first failure:

1. `check` (as above).
2. Builds `markx/api:<release>` and `markx/web:<release>` from the commit.
3. Runs the new image's configuration check (`python -m markx.ops.preflight
   --config-only`): every refused setting is named, never its value.
4. Starts PostgreSQL if needed; checks the database and the file stores,
   accepting pending migrations.
5. **Takes an encrypted backup** into `/var/backups/markx`.
6. **Runs the one-time migration step** (`migrate` service). A second run
   started by mistake waits for the first and does nothing.
7. Checks again: the schema must now be exactly this release's.
8. Starts or replaces every service and waits until each is healthy (the
   API means ready; the proxy starts after the API and the web app).
9. Verifies readiness, the web server and the proxy from inside, and
   appends the release to `/etc/markx/releases.log`.

Then the post-deployment verification in `checklists.md`, from outside.

If it stops: nothing after the failing step ran. Before step 6 the old
release is still running untouched. After step 6 the database is migrated
and the old release may no longer be ready (its schema is "ahead"): roll
forward with a fix, or follow `rollback.md`.

## The first deploy

The same command. PostgreSQL creates the three MarkX roles from
`postgres.env` on its empty volume; every migration is pending, and the
preflight accepts that. **A real first deploy cannot pass today**: the API
refuses to start without a real SMS provider (F-11), real buckets (F-01)
and the picture CDN's domain (F-15), by design.
