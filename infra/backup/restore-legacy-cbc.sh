#!/usr/bin/env bash
# LEGACY ONLY: restore a dump made by the retired backup.sh (D-063) into a
# NEW, empty database. Kept so that no backup made in the old format becomes
# unreadable (D-094); nothing makes new dumps in this format any more.
#
#   MARKX_BACKUP_PASSPHRASE_FILE=/secure/backup.key \
#     infra/backup/restore-legacy-cbc.sh var/backups/markx-markx-20261117T020000Z.dump.enc markx_restored
#
# THE OLD FORMAT IS NOT AUTHENTICATED (openssl enc -aes-256-cbc): a changed
# file is caught only by its .sha256 file, which travels beside it and can be
# changed with it. Restore a legacy dump only when it is the last resort,
# only from a copy you have kept yourself, and check the result by hand.
# New backups use `python -m markx.backup` (MXB2, authenticated, signed).
#
# Never overwrites anything: it refuses when the target database exists.
# Connection: the PG* variables, as a PostgreSQL superuser (the three MarkX
# roles and the database are created first, exactly as bootstrap.sh does).
# The checksum file, when present next to the backup, is checked first.
#
# PG_RESTORE and PSQL override the commands (e.g. "docker exec -i markx-pg pg_restore").
set -euo pipefail

[[ $# -eq 2 ]] || { echo "usage: restore-legacy-cbc.sh BACKUP_FILE TARGET_DB" >&2; exit 2; }
file="$1"; target="$2"
[[ "$target" =~ ^[a-z_][a-z0-9_]{0,62}$ ]] || { echo "unsafe database name: $target" >&2; exit 2; }
[[ -r "$file" ]] || { echo "cannot read $file" >&2; exit 2; }
key="${MARKX_BACKUP_PASSPHRASE_FILE:-}"
[[ -n "$key" && -r "$key" ]] || { echo "MARKX_BACKUP_PASSPHRASE_FILE must name a readable file" >&2; exit 2; }
psql_cmd="${PSQL:-psql}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -r "$file.sha256" ]]; then
  (cd "$(dirname "$file")" && sha256sum --check --quiet "$(basename "$file").sha256") \
    || { echo "checksum mismatch: $file is damaged or was changed" >&2; exit 1; }
fi

exists="$($psql_cmd --no-psqlrc -tA -d postgres -v ON_ERROR_STOP=1 \
  -c "select 1 from pg_database where datname = '$target'")"
[[ -z "$exists" ]] || { echo "database $target already exists; restore never overwrites" >&2; exit 1; }

PSQL="$psql_cmd" "$here/../postgres/bootstrap.sh" "$target" >/dev/null
# If anything below fails, remove the empty database this script just
# created, and nothing else.
trap '$psql_cmd --no-psqlrc -q -d postgres -c "drop database if exists $target" >/dev/null 2>&1; echo "restore failed; the empty database $target was removed" >&2' ERR

# One transaction: a restore that fails part-way writes nothing.
openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass "file:$key" -in "$file" \
  | ${PG_RESTORE:-pg_restore} --exit-on-error --single-transaction --no-password -d "$target"
trap - ERR
echo "restored $file into $target"
