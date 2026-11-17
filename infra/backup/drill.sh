#!/usr/bin/env bash
# The restore drill (blueprint F.13 "a restore drill every month", P2
# completion criterion 3; D-063). Proves a backup can be restored:
#
#   MARKX_BACKUP_PASSPHRASE_FILE=/secure/backup.key infra/backup/drill.sh markx
#
# 1. takes a fresh encrypted backup of DBNAME (backup.sh);
# 2. restores it into a new database, markx_drill_<UTC time> (restore.sh);
# 3. compares the two: the migration version, and the row count of every
#    table, which must be equal (run it while nothing writes, or expect the
#    tables being written to to differ, which the report names);
# 4. checks the restored copy kept its protections: the application role
#    still cannot change the audit log;
# 5. drops the drill database it created, unless --keep is given. It never
#    touches any other database.
#
# Connection: the PG* variables, as a superuser. PG_DUMP, PG_RESTORE and PSQL
# override the commands (see backup.sh). Exit status 0 only when every check
# passed.
set -euo pipefail

[[ $# -ge 1 ]] || { echo "usage: drill.sh DBNAME [--keep]" >&2; exit 2; }
db="$1"; keep="${2:-}"
[[ "$db" =~ ^[a-z_][a-z0-9_]{0,62}$ ]] || { echo "unsafe database name: $db" >&2; exit 2; }
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
psql_cmd="${PSQL:-psql}"
target="markx_drill_$(date -u +%Y%m%d%H%M%S)"
q() { $psql_cmd --no-psqlrc -tA -v ON_ERROR_STOP=1 -d "$1" -c "$2"; }

workdir="$(mktemp -d)"
cleanup() {
  rm -rf "$workdir"
  if [[ "$keep" != "--keep" ]] && [[ -n "$(q postgres "select 1 from pg_database where datname = '$target'")" ]]; then
    q postgres "drop database $target" >/dev/null && echo "drill database $target dropped"
  fi
}
trap cleanup EXIT

started=$(date +%s)
MARKX_BACKUP_DIR="$workdir" "$here/backup.sh" "$db"
backup_file="$(ls "$workdir"/*.dump.enc)"
"$here/restore.sh" "$backup_file" "$target"
elapsed=$(( $(date +%s) - started ))

counts() {
  q "$1" "select string_agg(format('%s=%s', t.table_name,
           (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I', t.table_name), false, true, '')))[1]::text),
           ' ' order by t.table_name)
          from information_schema.tables t
         where t.table_schema = 'public' and t.table_type = 'BASE TABLE'" | tr ' ' '\n'
}
failures=0
source_version="$(q "$db" "select version_num from alembic_version")"
restored_version="$(q "$target" "select version_num from alembic_version")"
if [[ "$source_version" == "$restored_version" ]]; then
  echo "ok    migration version $restored_version"
else
  echo "FAIL  migration version: $db has $source_version, the copy $restored_version"; failures=$((failures + 1))
fi

diff_out="$(diff <(counts "$db") <(counts "$target") || true)"
tables="$(counts "$target" | wc -l)"
rows="$(counts "$target" | awk -F= '{s+=$2} END {print s+0}')"
if [[ -z "$diff_out" ]]; then
  echo "ok    $tables tables, $rows rows, every count equal"
else
  echo "FAIL  row counts differ (< $db, > copy):"; echo "$diff_out"; failures=$((failures + 1))
fi

# The protections came back with the data: the application role still may
# not rewrite history. Run inside a transaction that is always rolled back.
if q "$target" "begin; set local role markx_app; update audit_log set action = action; rollback;" >/dev/null 2>&1; then
  echo "FAIL  the application role could change the audit log in the copy"; failures=$((failures + 1))
else
  echo "ok    the audit log is still protected in the copy"
fi

echo "restore took ${elapsed}s (target: under 4 hours, blueprint H.2)"
if [[ $failures -eq 0 ]]; then echo "DRILL PASSED"; else echo "DRILL FAILED ($failures)"; exit 1; fi
