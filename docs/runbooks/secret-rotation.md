# Changing a secret

Every secret lives in `/etc/markx` on the server (and, for recovery, where
the founder keeps it), never in Git, chat or a screenshot. The founder may
rotate any secret at any time; the Turnstile steps are in `docs/SETUP.md`.
Rotate everything after anyone with access leaves, and at the security
review of the 100th transaction (`docs/DEVELOPMENT_STATUS.md`, "Founder
reminders").

After changing a file: `docker compose ... up -d --wait <services>` (an
environment change recreates the container). `deploy.sh check` before.

| Secret | Where | Steps | Who restarts |
| --- | --- | --- | --- |
| A database role's password | `postgres.env` and the URL in `api.env`, `migrate.env` or `backup.env` | 1. `alter role markx_app password '<new>'` as the superuser inside the postgres container. 2. Change the files. 3. Restart. The variable in `postgres.env` only matters for a new volume, a restore or a drill | api, worker (app role); backup (migrator) |
| `POSTGRES_PASSWORD` | `postgres.env` | `alter role postgres password '<new>'`, then the file | nothing running |
| `MARKX_SECRET_KEY` | `api.env` | Change it and restart. Signed links already sent (tracking links, document links) stop working; sessions and anti-forgery tokens are reissued at the next sign-in | api, worker |
| `MARKX_ENCRYPTION_KEY` | `api.env` | **Not by replacing it**: staff authenticator secrets and payout account numbers encrypted with it become unreadable. Re-encryption needs a small tool that does not exist yet; build it before the first rotation | — |
| Turnstile secret | `api.env` | Rotate in Cloudflare's dashboard, then the file (`docs/SETUP.md`) | api |
| SMS API key | `api.env` | The provider's dashboard, then the file | api, worker |
| Storage access key | `api.env` | Create the new key at the provider scoped to the two buckets, change the file, restart, then delete the old key | api, worker |
| Telegram bot token | `api.env` | BotFather's `/revoke`, then the file | api, worker |
| `backup.key` | `/etc/markx/backup.key` | Write a new one (`deploy.md`); **keep the old one** as long as any dump made with it is kept (30 days, and every off-server copy) | backup |
| TLS private key | `/etc/markx/tls` | `tls-certificates.md` | proxy (reload) |
