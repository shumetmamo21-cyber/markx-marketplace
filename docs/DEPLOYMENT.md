# Deploying MarkX

**Status on 18 November 2026: NOTHING IS DEPLOYED.** No server, domain,
certificate, bucket, SMS account, Turnstile production widget or Telegram
alert group exists for MarkX. This document describes the deployment
foundation that is in the repository (D-091) and what it still needs. MarkX
is **not production-ready**: see "What is not done" at the end.

Read with: `docs/runbooks/` (the procedures), `infra/production/` (the
files), `docs/DECISIONS.md` D-091 (why it is built this way).

## The four kinds of status used here

| Mark | Meaning |
| --- | --- |
| **Tested** | Implemented and exercised by an automated test or the local rehearsal, with the result recorded in `docs/DEVELOPMENT_STATUS.md` |
| **Prepared** | Implemented, but never connected to the real service it is for (it cannot be: the account does not exist) |
| **Founder** | Waits for a decision or an account only the founder can make |
| **Real world** | Can only be proven on a real server with real traffic |

## The shape

One server, Docker Compose, six long-running containers and one one-time
step (blueprint F.0, F.13):

```text
                 internet
                    |
          80, 443   v
   +---------------------------+   edge network (the only one with ports)
   | proxy  nginx, uid 101     |
   +---------------------------+
        |  /api/...    |  everything else
        v              v                     frontend network: internal, no way out
   +-----------+  +-----------+              (172.30.10.0/24; the API trusts
   | api       |<-| web       |               forwarded addresses from it only)
   | FastAPI   |  | Next.js   |
   | uid 999   |  | uid 1000  |
   +-----------+  +-----------+
        |                                    backend network: internal, no way out
        v
   +-----------+  +-----------+  +-----------+  +-----------+
   | postgres  |<-| worker    |  | backup    |  | migrate   |  (profile; one-time)
   | 17.12     |  | jobs and  |  | nightly   |  | alembic   |
   |           |  | schedules |  | set (*)   |  | upgrade   |
   +-----------+  +-----------+  +-----------+  +-----------+
   api, worker and backup are also on the egress network: Turnstile, SMS,
   S3/R2, Telegram, the backup destination
   (*) the database and every stored file, encrypted, to an off-server bucket
       (D-094); NO destination is connected yet (F-16)
```

| Service | Image | What it does | Health check | Stop grace |
| --- | --- | --- | --- | --- |
| `proxy` | `nginxinc/nginx-unprivileged:1.28.2-alpine` | TLS, HTTP to HTTPS, routing, limits, HSTS | internal `/health` on 127.0.0.1:8081 | 15 s |
| `web` | `markx/web:<release>` (`apps/web/Dockerfile`) | Pages, server-side calls to the API | `GET /healthz` (liveness) | 30 s |
| `api` | `markx/api:<release>` (`apps/api/Dockerfile`) | Every business rule | `GET /api/v1/healthz/ready` (readiness) | 30 s (uvicorn drains for 20 s) |
| `worker` | the API image, `python -m markx.worker` | Scheduled jobs, the outbox, pictures; also the scheduler | `--check-heartbeat` (a pass in the last 5 min) | 60 s (finishes the row in hand) |
| `postgres` | `postgres:17.12` | The database, on a named volume, data checksums on | `pg_isready` | 60 s |
| `backup` | `markx/backup:<release>` (the `backup` stage of `apps/api/Dockerfile`), `python -m markx.backup serve` | A backup set (database and files) at start-up and daily: encrypted, uploaded, read back, signed; retries and retention (D-094) | a verified set under 26 h old, off-server on staging and production | 30 s |
| `migrate` | the API image, `alembic upgrade head` | The one-time migration step; never started by `up` | — | — |

Hardening on the application containers (**Tested** by the rehearsal):
unprivileged users, read-only root file systems with `tmpfs` for `/tmp`,
`no-new-privileges`, every Linux capability dropped, `init` for signal
handling, memory limits sized for a 2 GB server (blueprint M.3; each can be
changed in `compose.env`), and log rotation (5 files of 10 MB per container).

### Liveness and readiness

| Endpoint | Question | Used by |
| --- | --- | --- |
| `GET /api/v1/healthz/live` | Does the API process answer? Touches nothing else | an outside monitor; never restarts on a database outage |
| `GET /api/v1/healthz/ready` | Database answers, schema is this release's, both file stores answer | the container check, the proxy's start order, `deploy.sh`, an outside monitor |
| `GET /api/v1/healthz` | API and database (D-064, unchanged) | existing monitors |
| `GET /api/v1/healthz/worker` | Has a scheduled job started in the last five minutes? (D-064) | an outside monitor |
| `GET /healthz` (web) | Does the web server answer? | the container check |

Readiness answers in fixed words only (`ready`/`not_ready`, `up`/`down`,
`current`/`behind`/`ahead`/`unknown`, `not_used`); the details (which
migration, which store, why) go to the log. The storage probe asks the
provider at most once every 15 seconds, whoever calls. **Tested.**

## Settings

Two kinds of file, both **outside the repository**, on the server only:

- `/etc/markx/compose.env`: **not secret**; what the Compose file needs.
- `/etc/markx/*.env` and `/etc/markx/backup-signing.key`: **secret**, owner
  root, mode 600 (the signing key: owner 999, mode 400).
  `/etc/markx/backup-public.key`: not secret (root, 644). `deploy.sh check`
  refuses wrong owners, wrong modes, example values, and a backup
  **recovery** key anywhere in `/etc/markx` (it never belongs on the server).

Templates with placeholders only: `infra/production/env/*.env.example`. The
API refuses to start on staging or production, naming every problem and
never a value, if a rule below is broken (**Tested**:
`tests/deployment/test_production_config.py`).

### Compose and proxy (`compose.env`)

| Setting | For | Required | Purpose |
| --- | --- | --- | --- |
| `MARKX_ENV` | all | yes | `staging` or `production`; `deploy.sh` refuses anything else |
| `MARKX_CONFIG_DIR` | all | default `/etc/markx` | where the secret files are |
| `MARKX_SITE_HOSTNAME` | proxy | yes | the one hostname the site answers on (**Founder**: no domain yet) |
| `MARKX_PUBLIC_ORIGIN` | web | yes | `https://<hostname>`; the API has the same value in `api.env` |
| `MARKX_MEDIA_ORIGIN` | web (build and run) | yes | the picture CDN's own origin (F.6; **Founder**, F-15) |
| `MARKX_HSTS_MAX_AGE` | proxy | default 31536000 | HTTPS-only memory in browsers |
| `MARKX_TLS_DIR` | proxy | default `/etc/markx/tls` | `fullchain.pem` (644), `privkey.pem` (owner 101, 400) |
| `MARKX_ACME_DIR` | proxy | default `/var/lib/markx/acme` | certificate challenges |
| `MARKX_BACKUP_HOST_DIR` | backup | default `/var/backups/markx` | where dumps are written (owner 999) |
| `MARKX_FRONTEND_SUBNET` | api, networks | default `172.30.10.0/24` | the proxy network; becomes `MARKX_TRUSTED_PROXIES` |
| `MARKX_API_WORKERS` | api | default 2 | uvicorn processes |
| `MARKX_PUBLIC_BIND`, `MARKX_HTTP_PORT`, `MARKX_HTTPS_PORT` | proxy | defaults `0.0.0.0`, 80, 443 | where the proxy listens |
| `MARKX_*_MEMORY` | each service | defaults in the file | memory limits |
| `MARKX_RELEASE` | all | set by `deploy.sh` | the image tag (the Git commit) |

### API, worker and migration step (`api.env`, `migrate.env`)

`MARKX_ENV` and `MARKX_TRUSTED_PROXIES` are set by the Compose file itself.

| Setting | Secret | Rule on staging and production |
| --- | --- | --- |
| `MARKX_DATABASE_URL` | yes | the `markx_app` role; no `dev-only` password |
| `MARKX_MIGRATION_DATABASE_URL` | yes, in `migrate.env` only | the `markx_migrator` role; `api.env` holds it **without** a password, so the API and worker cannot change the schema |
| `MARKX_SECRET_KEY` | yes | at least 32 characters, not the development key |
| `MARKX_ENCRYPTION_KEY` | yes | a real Fernet key, not the development key (new in D-091); keep a copy off the server |
| `MARKX_PUBLIC_ORIGIN` | no | `https://` and a bare origin, no path (new) |
| `MARKX_COOKIE_SECURE` | no | `true` |
| `MARKX_TRUSTED_PROXIES` | no | must be set explicitly (new); `*` and `0.0.0.0/0` are always refused |
| `MARKX_LOG_LEVEL` | no | a real level everywhere (new); not `DEBUG` on a real server (new) |
| `MARKX_BOT_CHECK_PROVIDER`, `MARKX_TURNSTILE_SECRET_KEY`, `MARKX_TURNSTILE_SITE_KEY`, `MARKX_TURNSTILE_ALLOWED_HOSTNAMES` | the secret key | `turnstile` with both keys; not Cloudflare's test keys; not `localhost` (D-084, D-085). **Prepared**: no production widget |
| `MARKX_SMS_PROVIDER`, `MARKX_SMS_API_URL`, `MARKX_SMS_API_KEY`, `MARKX_SMS_SENDER_ID` | the key | `http` with all three (D-089). **Founder** (F-11): no provider, so a real server cannot start today |
| `MARKX_FILE_STORAGE_PROVIDER` and `MARKX_STORAGE_*` | the access keys | `s3` or `r2`, two different buckets, `https://` endpoint (D-090). **Founder** (F-01): no bucket |
| `MARKX_PUBLIC_MEDIA_BASE_URL` | no | `https://` on a host other than the site's (F.6). **Founder** (F-15) |
| `MARKX_TELEGRAM_BOT_TOKEN`, `MARKX_ALERT_TELEGRAM_CHAT_ID` | the token | optional; without both, alerts reach only the log and the API and worker say so at start-up (new). **Founder** |
| `MARKX_TELEGRAM_PUSH_PROVIDER`, `MARKX_TELEGRAM_PUSH_TIMEOUT_SECONDS` | no (the token above is) | unset or `none` today: no bot exists, every Telegram delivery is recorded `unavailable` and a start-up warning says so; `fake` is refused; `bot_api` needs `MARKX_TELEGRAM_BOT_TOKEN` (D-092). **Founder** (N-1) |
| `MARKX_TELEGRAM_LINKING_ENABLED` | no | `false` (default): connecting Telegram is off, the webhook answers 404. `true` needs the two below or the API refuses to start (D-093). **Founder** (N-1) |
| `MARKX_TELEGRAM_BOT_USERNAME` | no | the bot's username without `@`; required when linking is on |
| `MARKX_TELEGRAM_WEBHOOK_SECRET` | **yes** | 32 to 256 of `A-Z a-z 0-9 _ -`, repeated by Telegram in `X-Telegram-Bot-Api-Secret-Token`; required when linking is on; test or development values refused (D-093) |
| `MARKX_TELEGRAM_LINK_TTL_MINUTES` | no | `10` (2 to 30): how long a connection link works |
| `MARKX_ALLOW_NEWER_SCHEMA` | no | only during an acknowledged rollback (`docs/runbooks/rollback.md`; new) |
| `MARKX_WORKER_HEARTBEAT_FILE` | no | set by the Compose file for the worker (new) |
| `MARKX_DB_POOL_SIZE`, `MARKX_DB_MAX_OVERFLOW`, `MARKX_STORAGE_*_TIMEOUT_SECONDS`, `MARKX_STORAGE_MAX_OBJECT_BYTES`, `MARKX_STORAGE_SERVER_SIDE_ENCRYPTION`, `MARKX_SMS_TIMEOUT_SECONDS`, `MARKX_TURNSTILE_TIMEOUT_SECONDS`, `MARKX_*_SESSION_*_MINUTES`, `MARKX_TOTP_ISSUER`, `MARKX_WORKER_POLL_SECONDS` | no | defaults are the intended values |
| `MARKX_STORAGE_DIR` | no | set by the Compose file to a `tmpfs`; nothing writes there on a real server any more: the fake push sender is refused there (D-092) |

### Web (`web.env` and `compose.env`)

The web container refuses to start on staging or production without these
(`apps/web/deploy/check-env.mjs`; **Tested**):

| Setting | Where | Rule |
| --- | --- | --- |
| `MARKX_ENV` | Compose | `local`, `test`, `staging` or `production`; anything else is refused |
| `NODE_ENV` | Compose | `production` |
| `MARKX_API_ORIGIN` | Compose | `http://api:8000` (the internal address) |
| `MARKX_PUBLIC_ORIGIN` | Compose | `https://` origin |
| `MARKX_MEDIA_ORIGIN` | Compose, also a build argument | `https://` origin on another host |
| `MARKX_TURNSTILE_SITE_KEY` | `web.env` | set, not a Cloudflare test key |
| `MARKX_HSTS_MAX_AGE` | — | must NOT be set at run time; the proxy sends HSTS |

### Database (`postgres.env`)

| Setting | For | Purpose |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | postgres | the superuser; used for restores and drills only |
| `MARKX_DB_MIGRATOR_PASSWORD`, `MARKX_DB_APP_PASSWORD`, `MARKX_DB_READONLY_PASSWORD` | postgres (first start only) | the three MarkX roles (blueprint F.3); must match the URLs above |

### Backups (`backup.env`, `backup-public.key`, `backup-signing.key`; D-094)

Read by the `backup` service only; the API and the worker never hold a
backup credential or key. **None of these exists for a real server yet**
(F-16, F-19, F-20). Template: `infra/production/env/backup.env.example`.
Procedures: `docs/runbooks/backup-and-restore.md`.

| Setting | Purpose |
| --- | --- |
| `PGPASSWORD` | the `markx_migrator` password (the schema owner reads every table) |
| `MARKX_BACKUP_DESTINATION` | `s3` or `r2`; staging and production refuse `local` and `minio` |
| `MARKX_BACKUP_DESTINATION_ENDPOINT_URL`, `_REGION`, `_BUCKET`, `_PREFIX` | the dedicated backup bucket, never a file bucket; `https://` only |
| `MARKX_BACKUP_DESTINATION_ACCESS_KEY_ID`, `_SECRET_ACCESS_KEY` | **its own key**, scoped to that bucket; never the file stores' key, never the machine's credentials |
| `MARKX_BACKUP_SOURCE_PROVIDER`, `_ENDPOINT_URL`, `_REGION`, `_PRIVATE_BUCKET`, `_PUBLIC_BUCKET` | the two file buckets to copy |
| `MARKX_BACKUP_SOURCE_ACCESS_KEY_ID`, `_SECRET_ACCESS_KEY` | a **read-only** key for the two file buckets |
| `MARKX_BACKUP_HOUR_UTC` | the nightly set (default 23, 02:00 in Addis Ababa) |
| `MARKX_BACKUP_RETENTION_DAYS`, `MARKX_BACKUP_RETENTION_MIN_SETS` | **required** on a real server; the founder's decision (F-20); 0 days keeps everything |
| `MARKX_BACKUP_RETRY_ATTEMPTS`, `_RETRY_DELAY_SECONDS`, `_MAX_AGE_HOURS`, `_LOCAL_KEEP_SETS`, `_BLOB_GRACE_HOURS` | optional: 3 attempts, 600 s, 26 h, 2 local copies, 48 h |
| `/etc/markx/backup-public.key` | the recovery key's PUBLIC half: the server encrypts, never decrypts |
| `/etc/markx/backup-signing.key` | signs manifests; secret, owner 999, mode 400 |

The **recovery key** (private) and the signer public key are kept off the
server by the founder (F-19); a restore needs only them and the bucket's
read access. In `api.env`, `MARKX_BACKUP_MONITORING` (`auto`: on for
staging and production), `MARKX_BACKUP_MAX_AGE_HOURS` (26) and
`MARKX_RESTORE_DRILL_MAX_AGE_DAYS` (35) set the worker's backup alerts.

## The reverse proxy

`infra/production/nginx/` (**Tested** locally with a self-signed
certificate; **Real world** with a real certificate):

- Port 80: certificate challenges from `MARKX_ACME_DIR`, everything else a
  301 to `https://MARKX_SITE_HOSTNAME`, whatever Host the visitor sent.
- Port 443: TLS 1.2 and 1.3 only, forward-secret ciphers, no session
  tickets, HTTP/2; a request for any other name gets no certificate.
- HSTS once per answer (the API's and web app's own copies are replaced);
  no version in `Server`; no `X-Powered-By`. The pages' and the API's own
  security headers (SEC-5, D-084) pass through unchanged.
- `/api/` to the API, everything else to the web app. `/api/v1/dev/`,
  `/api/v1/docs` and `/api/v1/openapi.json` answer 404.
- Bodies: 1 MB for every API call, 21 MB for the five upload routes only.
- Edge limits per address: 20 requests a second (burst 80) everywhere, 60
  a minute (burst 30) under `/api/v1/auth/`, 64 connections. Generous on
  purpose: many Ethiopian mobile users share one carrier address; the API's
  own limits are the precise ones. **Real world**: tune with measurements.
- `X-Forwarded-For` is **set** to the address the proxy saw, never appended,
  so a visitor cannot choose their address. The API believes it only from
  the frontend network; the web server passes the same single address on
  to the API for its own calls (`apps/web/src/lib/api/forwarded.ts`).
  Before D-091 every page's server-side search counted as one visitor, the
  web container, against the search limit (120 a minute for the whole site).
- Access log: JSON, paths only (no query string, cookie, user agent or
  referrer), with the request id the API also logs.
- No WebSocket is used today; the upgrade headers are passed to the web app
  so one added later works.
- **Cloudflare in front** (blueprint F.13, M.2: Proposed; **Founder**): not
  enabled. `snippets/cloudflare-real-ip.conf.example` says exactly what to
  change, and why the server's firewall must then admit Cloudflare only.

## Migrations

Forward only (AGENTS.md). Run once per release by `deploy.sh`, after a fresh
backup and before the new release starts, by the `migrate` service, the
only container with the schema owner's password. `alembic upgrade` takes a
PostgreSQL advisory lock, so a second run waits and then does nothing
(**Tested**: `tests/db/test_migration_lock.py` and the rehearsal's two
simultaneous runs). The API, the web app and the worker never migrate. See
`docs/runbooks/migrations.md`.

## What is not done

**Prepared, not connected** (the account or the thing does not exist):

- Any server. `deploy.sh` has run only in the local rehearsal.
- The site's domain and a real TLS certificate (F-17); the certificate tool
  itself (certbot or a Cloudflare origin certificate) is not in the stack
  (`docs/runbooks/tls-certificates.md`).
- Turnstile's production widget; an SMS provider (F-11); the buckets (F-01)
  and the picture CDN and its domain (F-15); the Telegram alert group.
- **The backup destination (F-16), the recovery key (F-19) and the
  retention (F-20).** The backup service (D-094) is built and tested
  against MinIO; on a real server it refuses to start until they exist.
  Until then there is no off-server backup: a disk or server loss loses
  the data. Activation steps: `docs/runbooks/backup-and-restore.md`.
- The Cloudflare edge.

**Seller notifications: a launch blocker (D-092, N-1).** The notification
system is built and tested against fakes and stand-ins: in-app messages,
Telegram and SMS delivery with a record per channel, the deadline reminder
and the failure alerts. **No outside channel is connected**: no Telegram bot,
no SMS provider, and notification SMS is switched off
(`notifications.sms_enabled`). A seller today learns of a new order only by
opening the dashboard, and an order nobody sees expires in 30 business
minutes. MarkX must not launch until at least one channel is connected and a
real order alert has been received on a seller's phone. To activate:

1. The founder decides N-1 (Telegram, SMS or both) and creates the bot
   and/or chooses the SMS provider (F-11) and approves the cost.
2. Telegram: set `MARKX_TELEGRAM_BOT_TOKEN` and
   `MARKX_TELEGRAM_PUSH_PROVIDER=bot_api`. A seller must connect Telegram
   once: the one-time link, the webhook and the account page's section are
   built and OFF (D-093); switching them on and registering the webhook are
   in `docs/runbooks/telegram-linking.md`. SMS: configure the
   provider (D-089), then a super administrator turns on
   `notifications.sms_enabled` and sets `notifications.sms_daily_budget`.
3. Place a test order to a store the founder owns and confirm the alert
   arrives; check the delivery record says `accepted` and the watch shows no
   `notifications.*` alert.

**Not built:**

- The blueprint's weekly copy to an encrypted drive the founder holds: not
  automated (a second destination, F-16).
- Versioning of the live file buckets between two nightly sets (F-14).
- An outside uptime monitor and error tracking (F-18; both need an account).
  Backup alerts are generated by the worker's watch but reach a person only
  once the Telegram alert group exists; until then, the log.
- Zero-downtime deploys: one copy of each service, so a restart drops
  requests for a few seconds. The web server stops at once on SIGTERM (Next.js
  does not drain), so pages being rendered at that moment fail.
- A container registry and image signing: images are built on the server
  from the checked-out commit.
- A firewall configuration for the server, automatic security updates of
  the host, and the spending alarm (blueprint M.3, M.12): host setup, at
  server creation.

**Real world only:** real TLS from outside, real latency from Ethiopia,
memory limits under real load, edge rate limits against real carrier
addresses, a backup to and a restore from a real off-server destination
within the four-hour target (blueprint H.2), the security review before
launch (blueprint H.7).
