#!/usr/bin/env bash
# Take one encrypted backup of a MarkX database (blueprint F.13, H.2, P2; D-063).
#
#   MARKX_BACKUP_PASSPHRASE_FILE=/secure/backup.key infra/backup/backup.sh markx
#
# Writes, into MARKX_BACKUP_DIR (default ./var/backups):
#   markx-<db>-<UTC time>.dump.enc         the pg_dump, AES-256 encrypted
#   markx-<db>-<UTC time>.dump.enc.sha256  its checksum, to check a copy
#
# Connection: the usual PG* variables (PGHOST, PGPORT, PGUSER, PGPASSWORD), as
# the schema owner (markx_migrator) or a superuser. The passphrase file must
# hold at least 32 characters and live outside the repository and outside the
# backup directory; the script refuses otherwise, and never writes an
# unencrypted dump to disk.
#
# PG_DUMP overrides the pg_dump command when the local client is older than
# the server, e.g. PG_DUMP="docker exec -i -e PGUSER -e PGPASSWORD markx-pg pg_dump".
#
# Nothing is ever deleted unless --keep-days N is given, which removes this
# script's own backup files older than N days from the backup directory
# (blueprint: "kept 30 days"; PROVISIONAL — FOUNDER MAY CHANGE BEFORE LAUNCH).
set -euo pipefail
umask 077

usage() { echo "usage: backup.sh DBNAME [--keep-days N]" >&2; exit 2; }
[[ $# -ge 1 ]] || usage
db="$1"; shift
keep_days=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-days) [[ $# -ge 2 && "$2" =~ ^[0-9]+$ && "$2" -ge 1 ]] || usage; keep_days="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[[ "$db" =~ ^[a-z_][a-z0-9_]{0,62}$ ]] || { echo "unsafe database name: $db" >&2; exit 2; }

key="${MARKX_BACKUP_PASSPHRASE_FILE:-}"
[[ -n "$key" && -r "$key" ]] || { echo "MARKX_BACKUP_PASSPHRASE_FILE must name a readable file" >&2; exit 2; }
[[ "$(wc -c < "$key")" -ge 32 ]] || { echo "the passphrase must be at least 32 characters" >&2; exit 2; }

dir="${MARKX_BACKUP_DIR:-./var/backups}"
mkdir -p "$dir"
dir="$(cd "$dir" && pwd)"
case "$(cd "$(dirname "$key")" && pwd)/" in
  "$dir"/*) echo "keep the passphrase file outside the backup directory" >&2; exit 2 ;;
esac

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$dir/markx-$db-$stamp.dump.enc"
partial="$out.partial"
trap 'rm -f "$partial"' EXIT

# Custom format: compressed, restorable table by table. Owners and grants are
# kept, so a restore has the same protection (append-only tables, roles).
${PG_DUMP:-pg_dump} --format=custom --compress=6 --no-password "$db" \
  | openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -pass "file:$key" -out "$partial"
mv "$partial" "$out"
trap - EXIT
(cd "$dir" && sha256sum "$(basename "$out")" > "$(basename "$out").sha256")
echo "backup written: $out ($(wc -c < "$out") bytes)"

if [[ -n "$keep_days" ]]; then
  find "$dir" -maxdepth 1 -type f -name "markx-$db-*.dump.enc*" -mtime "+$keep_days" -print -delete \
    | sed 's/^/removed old backup: /'
fi
