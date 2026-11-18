#!/usr/bin/env bash
# Create the MarkX roles and one database. Needs a PostgreSQL superuser.
#
#   PGHOST=127.0.0.1 PGUSER=postgres PGPASSWORD=... infra/postgres/bootstrap.sh markx
#
# Role passwords come from the environment; the defaults are for a laptop only.
# PSQL overrides the psql command (for example, to run it inside the database
# container with `docker exec -i`); the SQL is read from standard input, so
# the command needs no access to this directory.
set -euo pipefail

dbname="${1:-markx}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# A role's password is reset on a re-run only when its variable is given
# (D-091). Without this, a re-run without the variables (a restore on a
# real server, for example) would set every role back to its laptop default.
${PSQL:-psql} -v ON_ERROR_STOP=1 --no-psqlrc --quiet -d postgres \
  -v dbname="$dbname" \
  -v migrator_password="${MARKX_DB_MIGRATOR_PASSWORD:-markx_migrator_dev-only}" \
  -v app_password="${MARKX_DB_APP_PASSWORD:-markx_app_dev-only}" \
  -v readonly_password="${MARKX_DB_READONLY_PASSWORD:-markx_readonly_dev-only}" \
  -v reset_migrator="${MARKX_DB_MIGRATOR_PASSWORD:+1}" \
  -v reset_app="${MARKX_DB_APP_PASSWORD:+1}" \
  -v reset_readonly="${MARKX_DB_READONLY_PASSWORD:+1}" \
  < "$here/bootstrap.sql" >/dev/null

echo "database '$dbname' is ready (roles: markx_migrator, markx_app, markx_readonly)"
