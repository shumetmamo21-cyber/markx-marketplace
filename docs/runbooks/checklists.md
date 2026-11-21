# Checklists

## Pre-deployment (every release)

Rehearsed by `rehearse.sh` up to the lines marked **real server**.

- [ ] The founder approved this deployment in writing (blueprint F.13:
      "production deploys need the founder's manual approval").
- [ ] CI is green on the exact commit: API, web, security, containers,
      production rehearsal, browser journeys. Note the run numbers.
- [ ] `git log` since the last release read; every new migration's
      docstring read (`docs/runbooks/migrations.md`): is any of them slow,
      locking, or not backward-compatible? If so, plan a quiet hour.
- [ ] The release notes say whether rolling back to the previous release
      is compatible with its migrations (needed for `rollback.md`).
- [ ] **Real server:** `infra/production/deploy.sh check` passes (settings
      files, owners and modes, no example values, the certificate, the
      backup folder, the Compose file).
- [ ] **Real server:** the certificate is valid for longer than the
      warning time (`infra/production/deploy.sh certificate check` passes;
      D-103), and `systemctl list-timers markx-certificate.timer` shows the
      next run.
- [ ] **Real server:** free disk space for at least two more database dumps
      and two more images (`df -h`, `docker system df`).
- [ ] **Real server:** the last nightly backup exists and the backup
      container is healthy (`deploy.sh status`).
- [ ] Someone who can roll back is available for the next hour.

## Post-deployment verification

`deploy.sh deploy` already checked readiness, the web server and the proxy
from inside the server. Then, from OUTSIDE the server:

- [ ] `curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' http://<host>/`
      gives `301 https://<host>/`.
- [ ] `curl -sS https://<host>/api/v1/healthz/ready` gives
      `{"status":"ready","database":"up","schema":"current","storage":"up"}`.
- [ ] `curl -sS https://<host>/api/v1/healthz/worker` gives `"worker":"up"`
      (within five minutes of the start).
- [ ] `curl -sSI https://<host>/am` gives 200, one
      `strict-transport-security` header and a `content-security-policy`.
- [ ] `curl -sS -o /dev/null -w '%{http_code}\n' https://<host>/api/v1/openapi.json`
      gives 404.
- [ ] An outside TLS test of the hostname (for example SSL Labs) shows TLS
      1.2 and 1.3 only and a complete chain.
- [ ] The home page, a product page and search open in a phone browser, in
      Amharic and English; pictures load from the media hostname.
- [ ] A staff member signs in to the admin dashboard; Operations shows no
      new critical alert (`/admin/ops/status`).
- [ ] `docker compose ... logs --since 15m api worker | grep -E '"level": "(ERROR|CRITICAL)"'`
      shows nothing unexpected.
- [ ] `deploy.sh status`: every container is `healthy`.
- [ ] `/etc/markx/releases.log` has the new line; the release is written in
      `docs/DEVELOPMENT_STATUS.md` with the date and the checks above.

If any line fails and is not understood within 15 minutes: `rollback.md`.
