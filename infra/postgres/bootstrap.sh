#!/usr/bin/env bash
# Create the MarkX roles and one database. Needs a PostgreSQL superuser.
#
#   PGHOST=127.0.0.1 PGUSER=postgres PGPASSWORD=... infra/postgres/bootstrap.sh markx
#
# Role passwords come from the environment; the defaults are for a laptop only.
set -euo pipefail

dbname="${1:-markx}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

psql -v ON_ERROR_STOP=1 --no-psqlrc --quiet -d postgres \
  -v dbname="$dbname" \
  -v migrator_password="${MARKX_DB_MIGRATOR_PASSWORD:-markx_migrator_dev-only}" \
  -v app_password="${MARKX_DB_APP_PASSWORD:-markx_app_dev-only}" \
  -v readonly_password="${MARKX_DB_READONLY_PASSWORD:-markx_readonly_dev-only}" \
  -f "$here/bootstrap.sql" >/dev/null

echo "database '$dbname' is ready (roles: markx_migrator, markx_app, markx_readonly)"
