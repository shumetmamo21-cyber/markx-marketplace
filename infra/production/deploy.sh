#!/usr/bin/env bash
# Deploy, roll back and inspect MarkX on one server (blueprint F.13; D-091, D-103).
#
# NOTHING HAS BEEN DEPLOYED WITH THIS. It is ready for the day the founder
# creates a server; until then it runs only in the local rehearsal
# (infra/production/rehearsal/rehearse.sh). Read docs/runbooks/deploy.md.
#
#   infra/production/deploy.sh check              the server is set up correctly
#   infra/production/deploy.sh deploy RELEASE     build, check, back up, migrate, start, verify
#   infra/production/deploy.sh rollback RELEASE   start an earlier release's images again
#   infra/production/deploy.sh rollback RELEASE --accept-newer-schema
#                                                 the same, for a COMPATIBLE rollback to a release
#                                                 older than the database (docs/runbooks/rollback.md)
#   infra/production/deploy.sh backup             one verified, encrypted backup set now
#   infra/production/deploy.sh status             containers and health
#   infra/production/deploy.sh certificate install DIR
#                                                 put DIR/fullchain.pem and DIR/privkey.pem
#                                                 in place, checked, and reload the proxy
#   infra/production/deploy.sh certificate renew  renew if automatic renewal is on, then check
#   infra/production/deploy.sh certificate check  days left; exit 1 inside the warning time
#   infra/production/deploy.sh certificate issue  the first Let's Encrypt certificate
#   infra/production/deploy.sh certificate temporary
#                                                 a 7-day self-signed one, to start the proxy
#   infra/production/deploy.sh certificate install-timer
#                                                 the systemd timer that runs "renew" twice a day
#   infra/production/deploy.sh alert-test [--send-heartbeat]
#                                                 a test alert to the staff Telegram group, and
#                                                 whether the outside heartbeat is on (BK-4)
#   infra/production/deploy.sh watch              alert when a container stays unhealthy or stopped
#   infra/production/deploy.sh watch install-timer
#                                                 the systemd timer that runs "watch" every 5 minutes
#   infra/production/deploy.sh escrow-secrets     an encrypted copy of the server's secrets, locked
#                                                 to the recovery key, also put in the backup bucket
#                                                 (BK-5; docs/runbooks/backup-and-restore.md)
#
# RELEASE names the images (PREFIX/api, PREFIX/web, PREFIX/backup:RELEASE, where
# PREFIX is MARKX_IMAGE_PREFIX, default "markx"): use the Git commit being
# deployed (git rev-parse --short HEAD). Every release deployed is appended
# to $MARKX_CONFIG_DIR/releases.log.
#
# If anything fails AFTER the database was migrated (D-103), deploy goes
# back to the last working release when that release accepts the migrated
# database; otherwise it stops the API, the worker and the web app, so no
# half-working site runs, writes $MARKX_CONFIG_DIR/deploy-halted and says
# what to do. It never migrates down.
#
# MARKX_ALLOW_NEWER_SCHEMA (D-103, the founder's rule: go back to an older
# release only when it truly accepts the database). The setting lets an
# older release accept a newer database; only an operator, for one
# compatible rollback, ever turns it on. So: the automatic return checks the
# old release with the setting FORCED OFF, whatever api.env says; deploy
# refuses to start while it is on; rollback to a release older than the
# database needs --accept-newer-schema on the command line as well, so a
# setting left on never decides a rollback by itself.
#
# Settings: MARKX_COMPOSE_ENV (default /etc/markx/compose.env) and the files
# it points to in MARKX_CONFIG_DIR. MARKX_COMPOSE_OVERRIDE adds more Compose
# files, separated by ":" (the rehearsal uses it), and MARKX_DEPENDENCY_SERVICES the
# services started before the checks (default: postgres). It never prints a secret, never runs
# `down -v`, never removes a volume or a backup, and never downgrades the
# database: migrations only go forward.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose_env="${MARKX_COMPOSE_ENV:-/etc/markx/compose.env}"

say() { printf '%s\n' "$*"; }
fail() { printf 'deploy.sh: %s\n' "$*" >&2; exit 1; }

[[ -r "$compose_env" ]] || fail "cannot read $compose_env (copy infra/production/env/compose.env.example)"

# The few non-secret values this script itself needs, read without running
# the file as a script.
setting() {
  sed -n "s/^$1=//p" "$compose_env" | tail -1
}
stage="$(setting MARKX_ENV)"
config_dir="$(setting MARKX_CONFIG_DIR)"; config_dir="${config_dir:-/etc/markx}"
backup_dir="$(setting MARKX_BACKUP_HOST_DIR)"; backup_dir="${backup_dir:-/var/backups/markx}"
tls_dir="$(setting MARKX_TLS_DIR)"; tls_dir="${tls_dir:-/etc/markx/tls}"
acme_dir="$(setting MARKX_ACME_DIR)"; acme_dir="${acme_dir:-/var/lib/markx/acme}"
site_host="$(setting MARKX_SITE_HOSTNAME)"
# D-103: the same prefix the Compose file names the images with. An exported
# MARKX_IMAGE_PREFIX wins over the file, as it does for Compose itself.
image_prefix="${MARKX_IMAGE_PREFIX:-$(setting MARKX_IMAGE_PREFIX)}"; image_prefix="${image_prefix:-markx}"
# D-103: certificate renewal. "none" (the default) until the founder has a
# domain and chooses how (F-17); "certbot": Let's Encrypt, HTTP challenge.
tls_renewal="$(setting MARKX_TLS_RENEWAL)"; tls_renewal="${tls_renewal:-none}"
acme_email="$(setting MARKX_ACME_EMAIL)"
tls_warn_days="$(setting MARKX_TLS_WARN_DAYS)"; tls_warn_days="${tls_warn_days:-21}"
# Only the rehearsal points this elsewhere (a stand-in that contacts nobody).
certbot="${MARKX_CERTBOT_COMMAND:-certbot}"
releases_log="$config_dir/releases.log"
halt_file="$config_dir/deploy-halted"
# D-105 (BK-4): the container watch. PROVISIONAL (P-105-2): a container that
# stays unhealthy or stopped this many minutes alerts the staff group.
watch_minutes="$(setting MARKX_CONTAINER_ALERT_MINUTES)"; watch_minutes="${watch_minutes:-15}"
watch_state_dir="${MARKX_WATCH_STATE_DIR:-/var/lib/markx/watch}"

[[ "$image_prefix" =~ ^[a-z0-9][a-z0-9._:/-]*[a-z0-9]$|^[a-z0-9]$ ]] \
  || fail "MARKX_IMAGE_PREFIX in $compose_env is not an image name prefix: '$image_prefix'"
[[ "$tls_renewal" == none || "$tls_renewal" == certbot ]] \
  || fail "MARKX_TLS_RENEWAL in $compose_env must be none or certbot, not '$tls_renewal'"
[[ "$tls_warn_days" =~ ^[0-9]{1,2}$ ]] && (( 10#$tls_warn_days >= 8 && 10#$tls_warn_days <= 90 )) \
  || fail "MARKX_TLS_WARN_DAYS in $compose_env must be a number of days from 8 to 90"
tls_warn_days=$((10#$tls_warn_days))
[[ "$watch_minutes" =~ ^[0-9]{1,3}$ ]] && (( 10#$watch_minutes >= 5 && 10#$watch_minutes <= 720 )) \
  || fail "MARKX_CONTAINER_ALERT_MINUTES in $compose_env must be a number of minutes from 5 to 720"
watch_minutes=$((10#$watch_minutes))
export MARKX_IMAGE_PREFIX="$image_prefix"

case "$stage" in
  staging|production) ;;
  local)
    # Only the local rehearsal runs this way: the real-server rules cannot
    # be met without real accounts, which do not exist.
    [[ "${MARKX_DEPLOY_REHEARSAL:-}" == "1" ]] \
      || fail "MARKX_ENV=local is for the local rehearsal only (MARKX_DEPLOY_REHEARSAL=1)"
    say "REHEARSAL: MARKX_ENV=local on this machine; this is not a real server" ;;
  *) fail "MARKX_ENV in $compose_env must be staging or production, not '${stage}'" ;;
esac

compose() {
  local files=(-f "$here/compose.yaml")
  local extra
  # MARKX_COMPOSE_OVERRIDE: one or more extra Compose files, separated by ":".
  IFS=: read -r -a extra <<< "${MARKX_COMPOSE_OVERRIDE:-}"
  for f in "${extra[@]}"; do [[ -n "$f" ]] && files+=(-f "$f"); done
  docker compose "${files[@]}" --env-file "$compose_env" "$@"
}

require_release() {
  [[ "${1:-}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] \
    || fail "give a release name: letters, digits, dot, dash, underscore (the Git commit)"
  export MARKX_RELEASE="$1"
}

# The images of one release, as the Compose file names them.
release_images() { # release
  printf '%s\n' "$image_prefix/api:$1" "$image_prefix/web:$1" "$image_prefix/backup:$1"
}

images_present() { # release
  local images; mapfile -t images < <(release_images "$1")
  docker image inspect "${images[@]}" >/dev/null 2>&1
}

# The release running now: the last one deployed or rolled back to (a
# release whose deployment failed is never recorded as running).
last_release() {
  awk '$2 == "deploy" || $2 == "rollback" || $2 == "auto-rollback" { r = $3 } END { print r }' \
    "$releases_log" 2>/dev/null || true
}

# Is MARKX_ALLOW_NEWER_SCHEMA on in this settings file? Anything but an
# explicit false (0, off, f, false, n, no) counts as on: the safe reading.
newer_schema_setting_in() { # file
  [[ -r "$1" ]] || return 1
  local value
  while IFS= read -r value; do
    value="${value//[[:space:]\"\']/}"; value="${value,,}"
    case "$value" in 0|off|f|false|n|no) ;; *) return 0 ;; esac
  done < <(sed -n -E 's/^[[:space:]]*(export[[:space:]]+)?MARKX_ALLOW_NEWER_SCHEMA[[:space:]]*=(.*)$/\2/p' "$1")
  return 1
}

newer_schema_setting_on() { newer_schema_setting_in "$config_dir/api.env"; }

# -- check ------------------------------------------------------------------------------

check_file() { # path, owner, the strictest mode allowed (octal), what it is
  local path="$1" owner="$2" mode="$3" what="$4"
  [[ -f "$path" ]] || { say "  MISSING  $path ($what)"; return 1; }
  local actual_owner actual_mode
  actual_owner="$(stat -c %u "$path")"; actual_mode="$(stat -c %a "$path")"
  local problem=""
  [[ "$actual_owner" == "$owner" ]] || problem="owner is uid $actual_owner, want $owner"
  (( (8#$actual_mode & ~8#$mode) == 0 )) || problem="${problem:+$problem; }mode is $actual_mode, want $mode or stricter"
  if [[ -n "$problem" ]]; then say "  UNSAFE   $path: $problem"; return 1; fi
  say "  ok       $path"
}

placeholders_in() { # a settings file must hold no example value
  grep -l -E 'REPLACE_WITH|example\.invalid' "$1" >/dev/null 2>&1
}

# What is wrong with a certificate and its key, one line each; status 1 if
# anything is (D-103). Checked before a certificate is put in place and by
# `check`: it parses, the key is its own, it names the site's hostname, and
# it is valid for at least MIN_SECONDS more.
certificate_problems() { # certificate, key, min_seconds
  local cert="$1" key="$2" min="$3" bad=0
  command -v openssl >/dev/null || { say "  MISSING  openssl on this server (apt-get install openssl)"; return 1; }
  if ! openssl x509 -in "$cert" -noout 2>/dev/null; then
    say "  UNSAFE   $cert is not a PEM certificate"; return 1
  fi
  local cert_pub key_pub
  cert_pub="$(openssl x509 -in "$cert" -noout -pubkey 2>/dev/null | openssl pkey -pubin -outform DER 2>/dev/null | sha256sum)"
  key_pub="$(openssl pkey -in "$key" -pubout -outform DER 2>/dev/null | sha256sum)"
  if [[ -z "$cert_pub" || "$cert_pub" != "$key_pub" ]]; then
    say "  UNSAFE   the private key does not belong to the certificate"; bad=1
  fi
  if [[ -z "$site_host" ]] || ! openssl x509 -in "$cert" -noout -checkhost "$site_host" 2>/dev/null | grep -q "does match"; then
    say "  UNSAFE   the certificate is not for MARKX_SITE_HOSTNAME ($site_host)"; bad=1
  fi
  if ! openssl x509 -in "$cert" -noout -checkend "$min" >/dev/null 2>&1; then
    if (( min == 0 )); then say "  UNSAFE   the certificate has EXPIRED"; else say "  UNSAFE   the certificate expires within $((min / 86400)) day(s)"; fi
    bad=1
  fi
  return "$bad"
}

certificate_days_left() { # certificate -> whole days (negative once expired)
  local end; end="$(openssl x509 -in "$1" -noout -enddate | cut -d= -f2)"
  echo $(( ($(date -u -d "$end" +%s) - $(date -u +%s)) / 86400 ))
}

cmd_check() {
  local bad=0
  say "settings files in $config_dir:"
  for name in api.env migrate.env postgres.env web.env backup.env; do
    check_file "$config_dir/$name" 0 600 "copy env/$name.example and fill it in" || bad=1
    if [[ -f "$config_dir/$name" ]] && placeholders_in "$config_dir/$name" && [[ "$stage" != local ]]; then
      say "  UNSAFE   $config_dir/$name still holds an example value (REPLACE_WITH or example.invalid)"
      bad=1
    fi
  done
  # D-094: the server holds the PUBLIC half of the recovery key and the
  # signing key; the recovery key itself must never be on it.
  check_file "$config_dir/backup-signing.key" 999 400 "the backup signing key (python -m markx.backup keygen)" || bad=1
  check_file "$config_dir/backup-public.key" 0 644 "the recovery key's PUBLIC half (keygen's backup-public.key)" || bad=1
  if grep -rlq "MARKX-BACKUP-RECOVERY-KEY" "$config_dir" 2>/dev/null; then
    say "  UNSAFE   a backup RECOVERY key is on this server ($config_dir); it belongs off the server"
    bad=1
  fi
  if [[ -f "$config_dir/backup.key" ]]; then
    say "  note     $config_dir/backup.key is the retired passphrase (D-063); keep it only while"
    say "           legacy .dump.enc files may need restore-legacy-cbc.sh, then remove it"
  fi
  if placeholders_in "$compose_env" && [[ "$stage" != local ]]; then
    say "  UNSAFE   $compose_env still holds an example hostname (example.invalid)"; bad=1
  fi
  say "certificate in $tls_dir:"
  local cert_ok=1
  check_file "$tls_dir/fullchain.pem" 0 644 "the certificate chain" || { bad=1; cert_ok=0; }
  # The proxy runs as uid 101 and must read the key; nobody else may.
  check_file "$tls_dir/privkey.pem" 101 400 "the private key (docs/runbooks/tls-certificates.md)" || { bad=1; cert_ok=0; }
  if (( cert_ok )); then
    if certificate_problems "$tls_dir/fullchain.pem" "$tls_dir/privkey.pem" 0; then
      local days; days="$(certificate_days_left "$tls_dir/fullchain.pem")"
      if (( days < tls_warn_days )); then
        say "  WARNING  the certificate expires in $days day(s); renew it (deploy.sh certificate renew)"
      else
        say "  ok       the key matches, it is for $site_host, $days day(s) left"
      fi
    else
      bad=1
    fi
  fi
  if [[ "$tls_renewal" == none ]]; then
    say "  note     automatic renewal is OFF (MARKX_TLS_RENEWAL=none): the founder chooses how (F-17);"
    say "           the worker's watch still alerts $tls_warn_days days before the certificate expires"
  else
    say "  ok       automatic renewal: $tls_renewal"
  fi
  say "backup folder:"
  if [[ -d "$backup_dir" && "$(stat -c %u "$backup_dir")" == 999 ]]; then
    say "  ok       $backup_dir"
  else
    say "  UNSAFE   $backup_dir must exist and belong to uid 999 (the backup container)"; bad=1
  fi
  say "compose file:"
  if MARKX_RELEASE="${MARKX_RELEASE:-check}" compose config --quiet; then say "  ok       valid"; else bad=1; fi
  if [[ -f "$halt_file" ]]; then
    say "  note     the last deployment HALTED ($halt_file): see deploy.sh status"
  fi
  # D-105 (BK-5): a total-loss recovery needs this server's secrets, too.
  if ! compgen -G "$backup_dir/escrow/markx-secrets-*.json" >/dev/null; then
    say "  note     no secrets copy has been made on this server: run deploy.sh escrow-secrets"
    say "           after setting up, and again after any secret changes (BK-5)"
  fi
  if newer_schema_setting_on; then
    say "  WARNING  MARKX_ALLOW_NEWER_SCHEMA is on in $config_dir/api.env (a compatible rollback):"
    say "           remove the line before the next deploy; deploy refuses to start while it is on"
  fi
  (( bad == 0 )) || fail "the server is not ready; fix the lines above"
  say "check: PASSED"
}

# -- deploy -----------------------------------------------------------------------------

preflight() { # extra arguments for markx.ops.preflight
  compose run --rm --no-deps -T api python -m markx.ops.preflight "$@"
}

# Does $MARKX_RELEASE TRULY accept the database (D-103)? Its preflight with
# MARKX_ALLOW_NEWER_SCHEMA forced off, whatever api.env or anything else
# says: `run -e` wins over every settings file, and every release reads it,
# including one built before this rule. Used wherever an older release would
# be started without an operator vouching for it on the command line.
preflight_strict() {
  compose run --rm --no-deps -T -e MARKX_ALLOW_NEWER_SCHEMA=false api python -m markx.ops.preflight
}

# The schema word the running API reports ("current", "ahead", ...).
running_schema() {
  compose exec -T api python -c "import json, urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/healthz/ready', timeout=5)).get('schema', 'unknown'))" 2>/dev/null \
    || echo unknown
}

backup_now() {
  say "== a verified, encrypted backup set before anything changes"
  # Exit 3: the nightly backup is running right now; wait for it, then take our own.
  local tries=0 status
  while true; do
    status=0
    compose run --rm --no-deps -T backup python -m markx.backup run || status=$?
    [[ $status -eq 0 ]] && return 0
    [[ $status -eq 3 && $tries -lt 20 ]] || fail "the backup failed (exit $status); nothing was changed"
    tries=$((tries + 1)); say "   another backup is running; waiting 30 s"; sleep 30
  done
}

record() { # what, release
  printf '%s %s %s\n' "$(date -u +%FT%TZ)" "$1" "$2" >> "$releases_log"
}

# Are the proxy, the web app and the API answering? Status 1, with a line
# saying what is not, instead of stopping the script: the caller decides.
running_ok() {
  compose exec -T api python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/healthz/ready', timeout=5).status == 200 else 1)" \
    || { say "   the API is not ready"; return 1; }
  compose exec -T web node -e "fetch('http://127.0.0.1:3000/healthz').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))" \
    || { say "   the web app does not answer"; return 1; }
  compose exec -T proxy wget -q -O /dev/null http://127.0.0.1:8081/health \
    || { say "   the proxy does not answer"; return 1; }
}

verified() {
  say "verified: proxy, web and API ready. Now run the post-deployment checklist"
  say "(docs/runbooks/checklists.md) from outside the server."
}

# Start the images of $MARKX_RELEASE that are already on this server, without
# building or migrating: the API, the worker, the web app and the proxy,
# waited for, then the backup service. The backup service is started without
# waiting: it reports healthy only once a set newer than 26 hours exists,
# which is not this script's to decide.
start_built_release() {
  compose up -d --wait --no-build api worker web proxy || { say "   the release did not become healthy"; return 1; }
  compose up -d --no-build --no-deps backup || { say "   the backup service did not start"; return 1; }
  running_ok
}

# The deployment failed after the migration (D-103): never leave the new
# release half-running against the migrated database.
recover() { # failed release, previous release (may be empty)
  local failed="$1" previous="$2"
  say ""
  say "!! release $failed FAILED its checks after the database was migrated"
  if [[ -z "$previous" ]]; then
    say "   no earlier release was ever deployed here: nothing to go back to"
  elif ! images_present "$previous"; then
    say "   the images of the last working release, $previous, are no longer on this server"
  else
    say "== going back to the last working release, $previous"
    say "   (checked with MARKX_ALLOW_NEWER_SCHEMA forced off: only a release that truly accepts"
    say "   the database is started again, whatever api.env says)"
    export MARKX_RELEASE="$previous"
    local schema
    if ! preflight_strict; then
      say "   $previous refuses the migrated database (it is newer than that release)"
    elif ! start_built_release; then
      say "   $previous did not start cleanly either"
    elif schema="$(running_schema)"; [[ "$schema" != current ]]; then
      # It accepted the database a moment ago; it must still say so now.
      say "   $previous started but reports the schema as '$schema', not current"
    else
      record auto-rollback "$previous"
      rm -f "$halt_file"
      verified
      fail "deployment of $failed FAILED after its migration; $previous is running again, verified. The database keeps the migration. Fix the release and deploy again (docs/runbooks/rollback.md)."
    fi
  fi
  halt "$failed" "$previous"
}

# The safe state: the database and its backups stay up; nothing that serves
# or changes data runs. The proxy answers 502 or 504 until a release is started.
halt() { # failed release, previous release
  local failed="$1" previous="$2"
  say "== stopping the API, the worker and the web app: no half-working site"
  compose stop api worker web || say "   (stopping did not complete; check deploy.sh status)"
  # The backup service keeps running, as the release that migrated the
  # database (D-103): an older release's backup code may not know the new
  # schema (a new table of file references, say), so it is never left
  # running against it.
  say "== the backup service runs as $failed, the release that migrated the database"
  MARKX_RELEASE="$failed" compose up -d --no-build --no-deps backup \
    || say "   (the backup service did not start as $failed; check deploy.sh status)"
  {
    printf 'halted_at=%s\n' "$(date -u +%FT%TZ)"
    printf 'failed_release=%s\n' "$failed"
    printf 'last_working_release=%s\n' "${previous:-none}"
    printf 'state=the database is migrated; the API, the worker and the web app are stopped\n'
  } > "$halt_file"
  chmod 600 "$halt_file"
  say ""
  say "DEPLOYMENT HALTED in a safe state ($halt_file):"
  say "  - The database is migrated and running; it was backed up just before the migration"
  say "    (python -m markx.backup list, in the backup service, shows the set)."
  say "  - The API, the worker and the web app are STOPPED; the site answers 502 or 504. Nothing runs"
  say "    against the migrated database, so nothing is half-done. PostgreSQL and backups run."
  say "What to do, in this order of preference (docs/runbooks/rollback.md, \"A deployment halted\"):"
  say "  1. Roll forward: fix the release, then  deploy.sh deploy <fixed release>"
  if [[ -n "$previous" ]]; then
    say "  2. Only if the new release's notes say its migrations are backward-compatible: add"
    say "     MARKX_ALLOW_NEWER_SCHEMA=true to $config_dir/api.env, then"
    say "     deploy.sh rollback $previous --accept-newer-schema"
    say "     and REMOVE that line again before the next deploy (deploy refuses while it is on)."
  fi
  say "  3. Only with the founder's written approval, if data is damaged: restore the database"
  say "     from the backup taken before this deployment (docs/runbooks/backup-and-restore.md)."
  fail "deployment of $failed HALTED after its migration; the site is stopped safely (see above)"
}

cmd_deploy() {
  require_release "${1:-}"
  local release="$MARKX_RELEASE" previous
  # D-103: never deploy with the setting on. If this deployment failed after
  # its migration, the setting would make an older release say yes to a
  # database it does not accept.
  if newer_schema_setting_on; then
    fail "MARKX_ALLOW_NEWER_SCHEMA is on in $config_dir/api.env (left from a compatible rollback). A deployment never runs with it on. Remove that line from $config_dir/api.env, then run  deploy.sh deploy $release  again. Nothing was changed."
  fi
  previous="$(last_release)"
  [[ "$previous" == "$release" ]] && previous=""
  if [[ -f "$halt_file" ]]; then say "note: the last deployment halted ($halt_file); this one replaces it"; fi
  cmd_check
  say "== build release $release"
  compose build api web backup
  say "== the new release's configuration check"
  # --deploying: the new release itself refuses MARKX_ALLOW_NEWER_SCHEMA,
  # wherever it is set (D-103).
  preflight --config-only --deploying
  say "== the database"
  # Production's file stores are outside (S3 or R2); the rehearsal adds its
  # MinIO here (MARKX_DEPENDENCY_SERVICES="postgres minio").
  # shellcheck disable=SC2086
  compose up -d --wait ${MARKX_DEPENDENCY_SERVICES:-postgres}
  preflight --allow-pending-migrations --deploying
  backup_now
  say "== the one-time migration step"
  # PostgreSQL runs the migrations in one transaction: a failed migration
  # leaves the database as it was and the running release untouched.
  compose --profile migrate run --rm -T migrate \
    || fail "the migration failed; the database is as it was and the running release was not touched"
  # From here on the database is migrated: any failure goes to recover.
  say "== the new release against the migrated database"
  if ! preflight --deploying; then
    say "   the new release's preflight refused the migrated database"
    recover "$release" "$previous"
  fi
  say "== start"
  if ! compose up -d --wait --remove-orphans; then
    say "   the new release did not become healthy"
    recover "$release" "$previous"
  fi
  say "== after the start: readiness and the worker"
  running_ok || recover "$release" "$previous"
  record deploy "$release"
  rm -f "$halt_file"
  verified
  say "deployed $release"
}

cmd_rollback() {
  local release="" accept=0 arg
  for arg in "$@"; do
    case "$arg" in
      --accept-newer-schema) accept=1 ;;
      *) [[ -z "$release" ]] || fail "rollback: one release, then optionally --accept-newer-schema"
         release="$arg" ;;
    esac
  done
  require_release "$release"
  local images; mapfile -t images < <(release_images "$MARKX_RELEASE")
  images_present "$MARKX_RELEASE" \
    || fail "the images of $MARKX_RELEASE (${images[*]}) are not all on this server; rebuild it with deploy (it never migrates down)"
  say "== roll back to $MARKX_RELEASE (no migration runs; the database stays as it is)"
  # D-103: first, does that release truly accept the database (the setting
  # forced off)? If it does, nothing else is needed.
  local out status=0
  out="$(preflight_strict 2>&1)" || status=$?
  printf '%s\n' "$out"
  if (( status != 0 )); then
    grep -qx "schema: ahead" <<< "$out" \
      || fail "the preflight of $MARKX_RELEASE failed; nothing was started (see above)"
    # The database is newer than that release. Only a compatible rollback,
    # vouched for twice: the setting in api.env (which the release needs to
    # stay ready) AND this command line. A setting left on is not enough.
    (( accept )) || fail "the database is newer than $MARKX_RELEASE: nothing was started. Only if the newer release's notes say its migrations are backward-compatible: add MARKX_ALLOW_NEWER_SCHEMA=true to $config_dir/api.env and run  deploy.sh rollback $MARKX_RELEASE --accept-newer-schema  (docs/runbooks/rollback.md)"
    newer_schema_setting_on \
      || fail "--accept-newer-schema also needs MARKX_ALLOW_NEWER_SCHEMA=true in $config_dir/api.env; nothing was started"
    say "== a COMPATIBLE rollback: the database is newer than $MARKX_RELEASE, acknowledged"
    preflight || fail "$MARKX_RELEASE refuses the database even with MARKX_ALLOW_NEWER_SCHEMA=true; nothing was started"
  elif (( accept )); then
    say "   (--accept-newer-schema is not needed: $MARKX_RELEASE accepts the database as it is)"
  fi
  start_built_release || fail "the rollback to $MARKX_RELEASE did not start cleanly; see docs/runbooks/rollback.md"
  record rollback "$MARKX_RELEASE"
  rm -f "$halt_file"
  verified
  say "rolled back to $MARKX_RELEASE (API, worker, web app, proxy and backup service)"
  if newer_schema_setting_on; then
    say "REMEMBER: MARKX_ALLOW_NEWER_SCHEMA is on in $config_dir/api.env. Remove it before the next"
    say "deploy (deploy refuses to start while it is on)."
  fi
}

cmd_status() {
  if [[ -f "$halt_file" ]]; then
    say "!! THE LAST DEPLOYMENT HALTED ($halt_file):"
    sed 's/^/   /' "$halt_file"
    say "   docs/runbooks/rollback.md, \"A deployment halted\", says what to do."
    say ""
  fi
  if newer_schema_setting_on; then
    say "!! MARKX_ALLOW_NEWER_SCHEMA is on in $config_dir/api.env (a compatible rollback): remove it"
    say "   before the next deploy, which refuses to start while it is on."
    say ""
  fi
  compose ps
  say ""
  compose exec -T api python -c "import json, urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/healthz/ready', timeout=5)))" 2>/dev/null \
    || say "the API is not ready (or not running)"
  tail -5 "$releases_log" 2>/dev/null || true
}

# -- the certificate (D-103) --------------------------------------------------------------

proxy_running() {
  [[ -n "$(compose ps --status running -q proxy 2>/dev/null)" ]]
}

# Put a certificate in place: checked first, written beside the current one
# and renamed over it (the proxy reads whole files), then the proxy checks
# its configuration and reloads without a restart. If the proxy refuses it,
# the previous certificate is put back.
cert_install() { # folder holding fullchain.pem and privkey.pem
  local src="${1:-}"
  [[ -n "$src" && -f "$src/fullchain.pem" && -f "$src/privkey.pem" ]] \
    || fail "give a folder holding fullchain.pem and privkey.pem"
  say "== the new certificate in $src"
  certificate_problems "$src/fullchain.pem" "$src/privkey.pem" 86400 \
    || fail "the new certificate was refused; the current one is unchanged"
  mkdir -p "$tls_dir"; chmod 755 "$tls_dir"
  local cert="$tls_dir/fullchain.pem" key="$tls_dir/privkey.pem" had_previous=0
  if [[ -f "$cert" && -f "$key" ]]; then
    cp -p "$cert" "$tls_dir/.fullchain.pem.previous"; cp -p "$key" "$tls_dir/.privkey.pem.previous"
    had_previous=1
  fi
  install -o 0 -g 0 -m 644 "$src/fullchain.pem" "$tls_dir/.fullchain.pem.new"
  install -o 101 -g 101 -m 400 "$src/privkey.pem" "$tls_dir/.privkey.pem.new"
  mv -f "$tls_dir/.fullchain.pem.new" "$cert"
  mv -f "$tls_dir/.privkey.pem.new" "$key"
  if proxy_running; then
    if compose exec -T proxy nginx -t >/dev/null 2>&1 && compose exec -T proxy nginx -s reload >/dev/null 2>&1; then
      say "   the proxy reloaded with the new certificate"
    else
      if (( had_previous )); then
        mv -f "$tls_dir/.fullchain.pem.previous" "$cert"; mv -f "$tls_dir/.privkey.pem.previous" "$key"
        compose exec -T proxy nginx -s reload >/dev/null 2>&1 || true
      fi
      fail "the proxy refused the new certificate; the previous one is back in place"
    fi
  else
    say "   the proxy is not running; it reads the new certificate when it starts"
  fi
  rm -f "$tls_dir/.fullchain.pem.previous" "$tls_dir/.privkey.pem.previous"
  say "installed: $(openssl x509 -in "$cert" -noout -subject -enddate | tr '\n' ' ')"
}

cert_check() {
  local cert="$tls_dir/fullchain.pem"
  [[ -f "$cert" ]] || fail "no certificate at $cert"
  local days; days="$(certificate_days_left "$cert")"
  local end; end="$(openssl x509 -in "$cert" -noout -enddate | cut -d= -f2)"
  if (( days < 0 )) || ! openssl x509 -in "$cert" -noout -checkend 0 >/dev/null 2>&1; then
    fail "the certificate EXPIRED ($end): browsers refuse the site; renew it now"
  fi
  if (( days < tls_warn_days )); then
    fail "the certificate expires in $days day(s) ($end) and was not renewed (renewal: $tls_renewal)"
  fi
  say "certificate: $days day(s) left, until $end (renewal: $tls_renewal)"
}

# The deploy hook certbot runs for each renewed certificate.
deploy_hook() {
  printf 'MARKX_COMPOSE_ENV=%q %q certificate install-renewed' "$compose_env" "$here/deploy.sh"
}

cert_renew() {
  if [[ "$tls_renewal" == none ]]; then
    say "automatic renewal is OFF (MARKX_TLS_RENEWAL=none in $compose_env): the founder chooses"
    say "how (F-17). Install each new certificate with: deploy.sh certificate install DIR"
  else
    say "== certbot renew (renews only a certificate within 30 days of its expiry)"
    "$certbot" renew --non-interactive --webroot -w "$acme_dir" --deploy-hook "$(deploy_hook)" \
      || fail "certbot could not renew the certificate; the current one is unchanged"
  fi
  cert_check
}

cert_issue() {
  [[ "$tls_renewal" == certbot ]] \
    || fail "set MARKX_TLS_RENEWAL=certbot in $compose_env first (the founder's choice, F-17)"
  [[ -n "$acme_email" && "$acme_email" != *example.invalid ]] \
    || fail "set MARKX_ACME_EMAIL in $compose_env (Let's Encrypt's expiry notices go there)"
  proxy_running || fail "the proxy must be running to answer the challenge: deploy first, with a temporary certificate"
  "$certbot" certonly --non-interactive --agree-tos -m "$acme_email" \
    --webroot -w "$acme_dir" -d "$site_host" --deploy-hook "$(deploy_hook)" \
    || fail "certbot could not get a certificate for $site_host"
  cert_check
}

# A self-signed certificate valid for 7 days, so the proxy can start before
# the first real one exists. The watch alerts about it at once, on purpose.
cert_temporary() {
  [[ -n "$site_host" ]] || fail "set MARKX_SITE_HOSTNAME in $compose_env"
  local tmp; tmp="$(mktemp -d)"
  openssl req -x509 -newkey rsa:2048 -nodes -days 7 -subj "/CN=$site_host" \
    -addext "subjectAltName=DNS:$site_host" -keyout "$tmp/privkey.pem" -out "$tmp/fullchain.pem" 2>/dev/null
  cert_install "$tmp"
  rm -rf "$tmp"
  say "TEMPORARY: replace it with a real certificate within 7 days (deploy.sh certificate issue)"
}

# The systemd timer that runs `certificate renew` twice a day (D-103). With
# renewal off it still runs the check, which fails inside the warning time,
# so `systemctl --failed` shows it too.
cert_install_timer() {
  local units="${MARKX_SYSTEMD_DIR:-/etc/systemd/system}" source="$here/systemd"
  mkdir -p "$units"
  sed -e "s|@DEPLOY@|$here/deploy.sh|g" -e "s|@COMPOSE_ENV@|$compose_env|g" \
    "$source/markx-certificate.service" > "$units/markx-certificate.service"
  cp "$source/markx-certificate.timer" "$units/markx-certificate.timer"
  chmod 644 "$units/markx-certificate.service" "$units/markx-certificate.timer"
  if [[ -z "${MARKX_SYSTEMD_DIR:-}" ]]; then
    systemctl daemon-reload && systemctl enable --now markx-certificate.timer \
      || fail "the timer could not be enabled"
    say "enabled: markx-certificate.timer ($(systemctl show -p NextElapseUSecRealtime --value markx-certificate.timer 2>/dev/null))"
  else
    say "written to $units (not enabled: MARKX_SYSTEMD_DIR is set)"
  fi
}

cmd_certificate() {
  # The proxy may be inspected and reloaded whatever release is running.
  export MARKX_RELEASE="${MARKX_RELEASE:-$(last_release)}"; MARKX_RELEASE="${MARKX_RELEASE:-none}"
  local what="${1:-}"; shift || true
  case "$what" in
    install) cert_install "$@" ;;
    install-renewed) [[ -n "${RENEWED_LINEAGE:-}" ]] || fail "RENEWED_LINEAGE is not set (certbot sets it)"
                     cert_install "$RENEWED_LINEAGE" ;;
    renew) cert_renew ;;
    check) cert_check ;;
    issue) cert_issue ;;
    temporary) cert_temporary ;;
    install-timer) cert_install_timer ;;
    *) fail "certificate: install DIR | renew | check | issue | temporary | install-timer" ;;
  esac
}

# -- alerts that do not need the application (BK-4, D-105) ----------------------------------

# One alert straight to the staff Telegram group through the bot, from a
# throwaway container of the worker's image (it has the bot's settings and a
# way out), so it works while the API, the worker or the database is down.
# Exit 0 only when the group accepted it.
notify() { # state (opened|resolved), key, text
  # stdin from /dev/null: the watch calls this inside a loop reading its own input.
  compose run --rm --no-deps -T worker python -m markx.ops.notify send \
    --key "$2" --severity critical --state "$1" --text "$3" < /dev/null
}

cmd_alert_test() {
  export MARKX_RELEASE="${MARKX_RELEASE:-$(last_release)}"
  [[ -n "$MARKX_RELEASE" ]] || fail "no release deployed yet; give MARKX_RELEASE"
  local rc=0
  say "== a test alert to the staff Telegram group (it should reach your phone within a minute)"
  compose run --rm --no-deps -T worker python -m markx.ops.notify test || rc=1
  say "== the outside heartbeat (the alert that still works if this server is lost)"
  if [[ "${1:-}" == "--send-heartbeat" ]]; then
    compose run --rm --no-deps -T backup python -m markx.backup heartbeat --send || rc=1
  else
    compose run --rm --no-deps -T backup python -m markx.backup heartbeat || rc=1
  fi
  (( rc == 0 )) || fail "the test alert did not reach the staff Telegram group (see above)"
  say "alert-test: PASSED. Confirm on the phone that the message arrived."
}

# The services that must always be running (migrate is a one-time step).
watched_services=(postgres api worker web proxy backup)

# "service state health" of each watched service's container, "missing" when
# it has none; a `compose run` container is not the service.
container_report() {
  local lines; lines="$(compose ps -a --format '{{.Service}} {{.Name}} {{.State}} {{.Health}}' 2>/dev/null || true)"
  local service line state health
  for service in "${watched_services[@]}"; do
    line="$(awk -v s="$service" '$1 == s && $2 !~ /-run-/ { print $3, ($4 == "" ? "-" : $4); exit }' <<< "$lines")"
    read -r state health <<< "${line:-missing -}"
    printf '%s %s %s\n' "$service" "$state" "$health"
  done
}

# What is wrong with a container, in words; nothing when it is fine.
container_problem() { # state, health
  case "$1" in
    running) if [[ "$2" == unhealthy ]]; then printf 'unhealthy'; fi ;;
    missing) printf 'missing (no container)' ;;
    *) printf '%s' "$1" ;;  # exited, dead, restarting, paused, created
  esac
  return 0
}

# Every five minutes (the markx-watch timer): a container that has been
# unhealthy, stopped or missing for MARKX_CONTAINER_ALERT_MINUTES alerts the
# staff group once, and once more when it is fine again. Docker's own
# "unhealthy" status tells no one; this does. What it cannot see (the whole
# server, or Docker itself, gone) is the outside heartbeat's job.
cmd_watch() {
  export MARKX_RELEASE="${MARKX_RELEASE:-$(last_release)}"
  if [[ -z "$MARKX_RELEASE" ]]; then say "watch: nothing is deployed yet"; return 0; fi
  mkdir -p "$watch_state_dir"; chmod 700 "$watch_state_dir"
  local state_file="$watch_state_dir/containers" now; now="$(date +%s)"
  declare -A since=() alerted=()
  local service s a
  if [[ -f "$state_file" ]]; then
    while read -r service s a; do
      [[ "$service" =~ ^[a-z]+$ && "$s" =~ ^[0-9]+$ && "$a" =~ ^[01]$ ]] || continue
      since[$service]="$s"; alerted[$service]="$a"
    done < "$state_file"
  fi
  local state health problem minutes bad=0 new_state=""
  while read -r service state health; do
    problem="$(container_problem "$state" "$health")"
    if [[ -n "$problem" ]]; then
      bad=1
      s="${since[$service]:-$now}"; a="${alerted[$service]:-0}"
      minutes=$(( (now - s) / 60 ))
      say "  PROBLEM  $service: $problem for $minutes minute(s)"
      if [[ "$a" == 0 ]] && (( now - s >= watch_minutes * 60 )); then
        if notify opened "container.$service" "The $service container on the $stage server has been $problem for $minutes minutes. See: deploy.sh status (docs/runbooks/deploy.md)."; then
          a=1
        else
          say "  the alert about $service could not be delivered; trying again next time"
        fi
      fi
      new_state+="$service $s $a"$'\n'
    else
      if [[ "${alerted[$service]:-0}" == 1 ]]; then
        notify resolved "container.$service" "The $service container on the $stage server is $state again." \
          || say "  the all-clear about $service could not be delivered"
      fi
    fi
  done < <(container_report)
  printf '%s' "$new_state" > "$state_file.tmp"; mv -f "$state_file.tmp" "$state_file"
  (( bad == 0 )) || fail "a container is not healthy (see above)"
  say "watch: every container is running and healthy"
}

# A systemd service and timer from infra/production/systemd, with this
# script's and the settings file's paths filled in.
install_timer() { # unit name
  local units="${MARKX_SYSTEMD_DIR:-/etc/systemd/system}" source="$here/systemd" name="$1"
  mkdir -p "$units"
  sed -e "s|@DEPLOY@|$here/deploy.sh|g" -e "s|@COMPOSE_ENV@|$compose_env|g" \
    "$source/$name.service" > "$units/$name.service"
  cp "$source/$name.timer" "$units/$name.timer"
  chmod 644 "$units/$name.service" "$units/$name.timer"
  if [[ -z "${MARKX_SYSTEMD_DIR:-}" ]]; then
    systemctl daemon-reload && systemctl enable --now "$name.timer" \
      || fail "the timer could not be enabled"
    say "enabled: $name.timer"
  else
    say "written to $units (not enabled: MARKX_SYSTEMD_DIR is set)"
  fi
}

# -- the secrets copy (BK-5, D-105) ---------------------------------------------------------

# The secrets a total-loss recovery needs, read here as root and piped as a
# tar stream (never a file on disk) into the backup image, which encrypts
# them to the recovery key's PUBLIC half, signs the copy, writes it to
# $backup_dir/escrow and puts it in the backup bucket (read back, locked).
# Nothing secret is printed; only file names.
cmd_escrow_secrets() {
  export MARKX_RELEASE="${MARKX_RELEASE:-$(last_release)}"
  [[ -n "$MARKX_RELEASE" ]] || fail "no release deployed yet; give MARKX_RELEASE"
  local settings=() tls=() name
  for name in api.env postgres.env migrate.env backup.env web.env compose.env \
              backup-signing.key backup-public.key; do
    [[ -f "$config_dir/$name" && ! -L "$config_dir/$name" ]] && settings+=("$name")
  done
  for name in privkey.pem fullchain.pem; do
    [[ -f "$tls_dir/$name" && ! -L "$tls_dir/$name" ]] && tls+=("$name")
  done
  say "== an encrypted copy of this server's secrets (BK-5)"
  say "   from $config_dir: ${settings[*]}"
  say "   from $tls_dir: ${tls[*]:-(no certificate files)}"
  local args=(-cf - --numeric-owner -C "$config_dir" "${settings[@]}")
  (( ${#tls[@]} )) && args+=(-C "$tls_dir" --transform 's,^privkey\.pem$,tls/privkey.pem,' \
                                --transform 's,^fullchain\.pem$,tls/fullchain.pem,' "${tls[@]}")
  tar "${args[@]}" | compose run --rm --no-deps -T backup python -m markx.backup escrow-secrets \
    --from-tar --out-dir /backups/escrow --upload \
    || fail "no secrets copy was made (see above)"
  say "The copy is in $backup_dir/escrow and in the backup bucket. Give the founder a copy to keep"
  say "with the recovery key (F-19; docs/runbooks/backup-and-restore.md, 'The secrets copy')."
}

# Sourced (the tests call the functions one by one), it stops here.
[[ "${BASH_SOURCE[0]}" == "$0" ]] || return 0

command="${1:-}"; shift || true
case "$command" in
  check) MARKX_RELEASE="${MARKX_RELEASE:-check}" cmd_check ;;
  deploy) cmd_deploy "$@" ;;
  rollback) cmd_rollback "$@" ;;
  # The running release's backup image. After a halt (D-103), the release
  # that migrated the database, never the older one.
  backup) [[ -z "${MARKX_RELEASE:-}" && -f "$halt_file" ]] \
            && MARKX_RELEASE="$(sed -n 's/^failed_release=//p' "$halt_file" | tail -1)"
          export MARKX_RELEASE="${MARKX_RELEASE:-$(last_release)}"
          [[ -n "$MARKX_RELEASE" ]] || fail "no release deployed yet; give MARKX_RELEASE"
          backup_now ;;
  status) export MARKX_RELEASE="${MARKX_RELEASE:-$(last_release)}"; cmd_status ;;
  certificate) cmd_certificate "$@" ;;
  alert-test) cmd_alert_test "$@" ;;
  watch) case "${1:-}" in
           "") cmd_watch ;;
           install-timer) install_timer markx-watch ;;
           *) fail "watch: (nothing) | install-timer" ;;
         esac ;;
  escrow-secrets) cmd_escrow_secrets ;;
  *) sed -n '2,50p' "$0"; exit 2 ;;
esac
