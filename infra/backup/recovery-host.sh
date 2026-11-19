#!/usr/bin/env bash
# A throwaway PostgreSQL 17 for a restore or a drill on a separate recovery
# machine (D-096; BK-2, BK-6): a laptop, or a free CI runner. NEVER the
# server. docs/runbooks/backup-and-restore.md, "The recovery machine".
#
#   eval "$(infra/backup/recovery-host.sh start)"   # prints the settings to use
#   ...  python -m markx.backup drill --from-destination ...  (or restore)
#   infra/backup/recovery-host.sh stop              # removes it and all its data
#
# What makes it throwaway:
# - its own container, from the pinned PostgreSQL 17.12 image, with NO
#   network at all (--network none): it cannot reach the internet, the
#   server or anything else, so a forged backup restored into it has nowhere
#   to send anything; it is reached only through a Unix socket in a folder;
# - no secret: nothing from the server, no MarkX password (the MarkX roles get
#   bootstrap.sh's laptop defaults, which are enough inside a sealed box);
# - its data lives inside the container and is gone with `stop`.
# The client tools (pg_restore, psql) run the same way, in throwaway
# containers without network that see only the socket folder.
set -euo pipefail

NAME="${MARKX_RECOVERY_CONTAINER:-markx-recovery-pg}"
IMAGE="${MARKX_RECOVERY_PG_IMAGE:-postgres:17.12@sha256:b60e90042aa6b8dbecd58e224b3e36114dbf8ad754465264c2476ad58a86e45c}"
SOCKET_DIR="${MARKX_RECOVERY_SOCKET_DIR:-${TMPDIR:-/tmp}/markx-recovery-socket}"

start() {
  if docker container inspect "$NAME" >/dev/null 2>&1; then
    echo "a container named $NAME already exists; run '$0 stop' first" >&2
    exit 2
  fi
  rm -rf "$SOCKET_DIR"
  mkdir -p "$SOCKET_DIR"
  chmod 777 "$SOCKET_DIR"  # the server inside runs as its own user
  # The superuser's password is random and never shown: inside the box the
  # socket is trusted, and nothing outside can reach it.
  docker run -d --name "$NAME" --network none \
    -v "$SOCKET_DIR:/var/run/postgresql" \
    -e POSTGRES_PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')" \
    -e POSTGRES_INITDB_ARGS="--locale-provider=builtin --builtin-locale=C.UTF-8 --encoding=UTF8" \
    "$IMAGE" >/dev/null
  for _ in $(seq 1 60); do
    if docker logs "$NAME" 2>&1 | grep -q "PostgreSQL init process complete" \
       && docker exec "$NAME" pg_isready -q -h /var/run/postgresql; then
      break
    fi
    sleep 1
  done
  docker exec "$NAME" pg_isready -q -h /var/run/postgresql \
    || { echo "the recovery PostgreSQL did not start" >&2; docker logs "$NAME" >&2; exit 1; }
  tools="docker run --rm -i --network none -v $SOCKET_DIR:$SOCKET_DIR -e PGHOST -e PGUSER -e PGPASSWORD $IMAGE"
  cat <<EOF
export PGHOST='$SOCKET_DIR' PGUSER=postgres PGPORT=5432
unset PGPASSWORD MARKX_DB_MIGRATOR_PASSWORD MARKX_DB_APP_PASSWORD MARKX_DB_READONLY_PASSWORD
export MARKX_BACKUP_PG_RESTORE_COMMAND='$tools pg_restore'
export MARKX_BACKUP_PSQL_COMMAND='$tools psql'
export MARKX_BACKUP_PG_DUMP_COMMAND='$tools pg_dump'
EOF
  echo "recovery PostgreSQL ready: container $NAME, no network, socket $SOCKET_DIR" >&2
}

stop() {
  docker rm -f -v "$NAME" >/dev/null 2>&1 || true
  rm -rf "$SOCKET_DIR"
  echo "recovery PostgreSQL $NAME removed with its data" >&2
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  *) echo "usage: $0 start|stop" >&2; exit 2 ;;
esac
