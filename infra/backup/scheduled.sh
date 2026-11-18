#!/usr/bin/env bash
# The backup service's loop (blueprint F.13, H.2; D-063, D-091).
#
# Runs inside the production Compose file's `backup` container (postgres:17
# image, as uid 999, read-only root): one encrypted dump at start-up, then
# one a day at MARKX_BACKUP_HOUR_UTC, each through backup.sh, which keeps
# MARKX_BACKUP_KEEP_DAYS days of its own files and deletes nothing else.
#
#   scheduled.sh            the loop (the container's entrypoint)
#   scheduled.sh --check    exit 0 if the last good dump is under 26 hours old
#                           (the container's health check)
#
# The dumps stay on THIS server (MARKX_BACKUP_HOST_DIR). The blueprint's
# off-server copies (object storage, the founder's drive) are not connected,
# and stored files are not in any dump (F-14).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dir="${MARKX_BACKUP_DIR:?MARKX_BACKUP_DIR must be set}"
status="$dir/.last-success"

if [[ "${1:-}" == "--check" ]]; then
  [[ -f "$status" && -n "$(find "$status" -mmin -1560)" ]]
  exit $?
fi

hour="${MARKX_BACKUP_HOUR_UTC:-23}"
keep="${MARKX_BACKUP_KEEP_DAYS:-30}"
db="${MARKX_BACKUP_DATABASE:-markx}"
[[ "$hour" =~ ^([01]?[0-9]|2[0-3])$ ]] || { echo "MARKX_BACKUP_HOUR_UTC must be 0 to 23" >&2; exit 2; }
[[ "$keep" =~ ^[0-9]+$ && "$keep" -ge 1 ]] || { echo "MARKX_BACKUP_KEEP_DAYS must be at least 1" >&2; exit 2; }

run_backup() {
  if "$here/backup.sh" "$db" --keep-days "$keep"; then
    touch "$status"
  else
    # Visible as an unhealthy container and in its log. Nothing outside the
    # server hears of it yet (docs/runbooks/backup-and-restore.md).
    echo "BACKUP FAILED at $(date -u +%FT%TZ); the previous good dump is kept" >&2
  fi
}

# Stop between dumps at once; a dump in progress is left to finish its pipe.
trap 'echo "backup service stopping"; exit 0' TERM INT

echo "backup service: a dump now, then daily at ${hour}:00 UTC, keeping ${keep} days"
run_backup
while true; do
  now="$(date -u +%s)"
  next="$(date -u -d "today ${hour}:00" +%s)"
  (( next > now )) || next="$(date -u -d "tomorrow ${hour}:00" +%s)"
  sleep "$(( next - now ))" &
  wait $!
  run_backup
done
