#!/usr/bin/env bash
# Deploy, roll back and inspect MarkX on one server (blueprint F.13; D-091).
#
# NOTHING HAS BEEN DEPLOYED WITH THIS. It is ready for the day the founder
# creates a server; until then it runs only in the local rehearsal
# (infra/production/rehearsal/rehearse.sh). Read docs/runbooks/deploy.md.
#
#   infra/production/deploy.sh check              the server is set up correctly
#   infra/production/deploy.sh deploy RELEASE     build, check, back up, migrate, start, verify
#   infra/production/deploy.sh rollback RELEASE   start an earlier release's images again
#   infra/production/deploy.sh backup             one encrypted dump now
#   infra/production/deploy.sh status             containers and health
#
# RELEASE names the images (markx/api:RELEASE, markx/web:RELEASE): use the
# Git commit being deployed (git rev-parse --short HEAD). Every release
# deployed is appended to $MARKX_CONFIG_DIR/releases.log.
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
  check_file "$config_dir/backup.key" 999 400 "the backup passphrase, read by the backup container" || bad=1
  if [[ -f "$config_dir/backup.key" ]] && (( $(wc -c < "$config_dir/backup.key") < 32 )); then
    say "  UNSAFE   $config_dir/backup.key is shorter than 32 characters"; bad=1
  fi
  if placeholders_in "$compose_env" && [[ "$stage" != local ]]; then
    say "  UNSAFE   $compose_env still holds an example hostname (example.invalid)"; bad=1
  fi
  say "certificate in $tls_dir:"
  check_file "$tls_dir/fullchain.pem" 0 644 "the certificate chain" || bad=1
  # The proxy runs as uid 101 and must read the key; nobody else may.
  check_file "$tls_dir/privkey.pem" 101 400 "the private key (docs/runbooks/tls-certificates.md)" || bad=1
  say "backup folder:"
  if [[ -d "$backup_dir" && "$(stat -c %u "$backup_dir")" == 999 ]]; then
    say "  ok       $backup_dir"
  else
    say "  UNSAFE   $backup_dir must exist and belong to uid 999 (the backup container)"; bad=1
  fi
  say "compose file:"
  if MARKX_RELEASE="${MARKX_RELEASE:-check}" compose config --quiet; then say "  ok       valid"; else bad=1; fi
  (( bad == 0 )) || fail "the server is not ready; fix the lines above"
  say "check: PASSED"
}

# -- deploy -----------------------------------------------------------------------------

preflight() { # extra arguments for markx.ops.preflight
  compose run --rm --no-deps -T api python -m markx.ops.preflight "$@"
}

backup_now() {
  say "== an encrypted backup before anything changes"
  compose run --rm --no-deps -T --entrypoint /markx-backup/backup.sh backup markx
}

record() { # what, release
  printf '%s %s %s\n' "$(date -u +%FT%TZ)" "$1" "$2" >> "$config_dir/releases.log"
}

verify() {
  say "== after the start: readiness and the worker"
  compose exec -T api python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/healthz/ready', timeout=5).status == 200 else 1)" \
    || fail "the API is not ready; see docs/runbooks/rollback.md"
  compose exec -T web node -e "fetch('http://127.0.0.1:3000/healthz').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))" \
    || fail "the web app does not answer; see docs/runbooks/rollback.md"
  compose exec -T proxy wget -q -O /dev/null http://127.0.0.1:8081/health \
    || fail "the proxy does not answer"
  say "verified: proxy, web and API ready. Now run the post-deployment checklist"
  say "(docs/runbooks/checklists.md) from outside the server."
}

cmd_deploy() {
  require_release "${1:-}"
  cmd_check
  say "== build release $MARKX_RELEASE"
  compose build api web
  say "== the new release's configuration check"
  preflight --config-only
  say "== the database"
  # Production's file stores are outside (S3 or R2); the rehearsal adds its
  # MinIO here (MARKX_DEPENDENCY_SERVICES="postgres minio").
  # shellcheck disable=SC2086
  compose up -d --wait ${MARKX_DEPENDENCY_SERVICES:-postgres}
  preflight --allow-pending-migrations
  backup_now
  say "== the one-time migration step"
  compose --profile migrate run --rm -T migrate
  say "== the new release against the migrated database"
  preflight
  say "== start"
  compose up -d --wait --remove-orphans
  verify
  record deploy "$MARKX_RELEASE"
  say "deployed $MARKX_RELEASE"
}

cmd_rollback() {
  require_release "${1:-}"
  docker image inspect "markx/api:$MARKX_RELEASE" "markx/web:$MARKX_RELEASE" >/dev/null 2>&1 \
    || fail "the images of $MARKX_RELEASE are not on this server; rebuild it with deploy (it never migrates down)"
  say "== roll back to $MARKX_RELEASE (no migration runs; the database stays as it is)"
  # Refuses if the database is newer than that release, unless the operator
  # set MARKX_ALLOW_NEWER_SCHEMA=true in api.env for this compatible rollback.
  preflight
  compose up -d --wait --no-build api worker web proxy
  verify
  record rollback "$MARKX_RELEASE"
  say "rolled back to $MARKX_RELEASE"
}

cmd_status() {
  compose ps
  say ""
  compose exec -T api python -c "import json, urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/healthz/ready', timeout=5)))" 2>/dev/null \
    || say "the API is not ready (or not running)"
  tail -5 "$config_dir/releases.log" 2>/dev/null || true
}

command="${1:-}"; shift || true
case "$command" in
  check) MARKX_RELEASE="${MARKX_RELEASE:-check}" cmd_check ;;
  deploy) cmd_deploy "$@" ;;
  rollback) cmd_rollback "$@" ;;
  backup) export MARKX_RELEASE="${MARKX_RELEASE:-backup}"; backup_now ;;
  status) export MARKX_RELEASE="${MARKX_RELEASE:-$(awk 'END {print $3}' "$config_dir/releases.log" 2>/dev/null)}"; cmd_status ;;
  *) sed -n '2,23p' "$0"; exit 2 ;;
esac
