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
#
# What it touches, and nothing else (D-105, the review notes RN-2 and RN-3):
# - The socket folder (MARKX_RECOVERY_SOCKET_DIR) is PRIVATE: mode 700, owned
#   by the user who runs this, so no other user of this machine can reach the
#   database, which trusts its socket. The socket itself is in its "run"
#   subfolder, the only part the container sees: the image's start-up opens
#   that subfolder's permissions, and cannot touch the private folder around
#   it. The folder is marked as this script's own; `stop` deletes a folder
#   only when it carries that mark, and `start` refuses a folder that holds
#   anything else. A path too long for a Unix socket is refused.
# - The container is labelled as this script's own; `stop` removes a
#   container only when it carries that label, never another one that merely
#   has the same name.
set -euo pipefail

NAME="${MARKX_RECOVERY_CONTAINER:-markx-recovery-pg}"
IMAGE="${MARKX_RECOVERY_PG_IMAGE:-postgres:17.12@sha256:b60e90042aa6b8dbecd58e224b3e36114dbf8ad754465264c2476ad58a86e45c}"
SOCKET_DIR="${MARKX_RECOVERY_SOCKET_DIR:-${TMPDIR:-/tmp}/markx-recovery-socket}"
MARK=".markx-recovery-socket"
LABEL="markx.recovery"
# Linux: a Unix socket path holds at most 107 bytes (RN-4).
MAX_SOCKET_PATH=107

die() { echo "recovery-host.sh: $*" >&2; exit 2; }

check_name() {
  [[ "$NAME" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$ ]] \
    || die "MARKX_RECOVERY_CONTAINER must be a plain container name, not '$NAME'"
}

check_socket_dir() {
  [[ "$SOCKET_DIR" == /* ]] || die "MARKX_RECOVERY_SOCKET_DIR must be an absolute path"
  case "/$SOCKET_DIR/" in
    */../*|*/./*) die "MARKX_RECOVERY_SOCKET_DIR must not contain '.' or '..'" ;;
  esac
  [[ "$SOCKET_DIR" != "/" && "$(basename "$SOCKET_DIR")" != "" ]] \
    || die "MARKX_RECOVERY_SOCKET_DIR must name a folder of its own"
  local socket="$SOCKET_DIR/run/.s.PGSQL.5432"
  (( ${#socket} <= MAX_SOCKET_PATH )) \
    || die "the socket path $socket is ${#socket} bytes; a Unix socket path can be at most $MAX_SOCKET_PATH: choose a shorter MARKX_RECOVERY_SOCKET_DIR"
}

# Ours: a real folder (not a link), owned by this user, carrying the mark.
ours() {
  [[ -d "$SOCKET_DIR" && ! -L "$SOCKET_DIR" && -O "$SOCKET_DIR" && -f "$SOCKET_DIR/$MARK" ]]
}

container_label() {
  docker container inspect --format "{{ index .Config.Labels \"$LABEL\" }}" "$NAME" 2>/dev/null || true
}

start() {
  check_name
  check_socket_dir
  if docker container inspect "$NAME" >/dev/null 2>&1; then
    die "a container named $NAME already exists; run '$0 stop' first (it removes only its own)"
  fi
  if [[ -e "$SOCKET_DIR" || -L "$SOCKET_DIR" ]]; then
    if ours; then
      clear_socket_dir   # left by an earlier run of this script
    elif [[ -d "$SOCKET_DIR" && ! -L "$SOCKET_DIR" && -O "$SOCKET_DIR" && -z "$(ls -A "$SOCKET_DIR")" ]]; then
      :                  # an empty folder of this user's: it becomes ours
    else
      die "$SOCKET_DIR exists and is not this script's empty socket folder; it was left alone. Choose another MARKX_RECOVERY_SOCKET_DIR"
    fi
  fi
  mkdir -p -m 700 "$SOCKET_DIR"
  chmod 700 "$SOCKET_DIR"
  : > "$SOCKET_DIR/$MARK"
  mkdir -m 700 "$SOCKET_DIR/run"
  # PostgreSQL inside runs as this user, so the socket subfolder is its own;
  # its data goes in a folder it makes itself (PGDATA below), as the image
  # needs for a user of its own (its default data folder belongs to 999).
  # PostgreSQL never runs as root: as root, the subfolder is given to the
  # image's own postgres user (999) instead; the private folder stays root's.
  local user_args=()
  if [[ "$(id -u)" == 0 ]]; then
    chown 999:999 "$SOCKET_DIR/run"
  else
    user_args=(--user "$(id -u):$(id -g)")
  fi
  # The superuser's password is random and never shown: inside the box the
  # socket is trusted, and only this user can reach the socket.
  docker run -d --name "$NAME" --network none --label "$LABEL=1" "${user_args[@]}" \
    -v "$SOCKET_DIR/run:/var/run/postgresql" \
    -e PGDATA=/var/lib/postgresql/data/cluster \
    -e POSTGRES_PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')" \
    -e POSTGRES_INITDB_ARGS="--locale-provider=builtin --builtin-locale=C.UTF-8 --encoding=UTF8" \
    "$IMAGE" >/dev/null
  for _ in $(seq 1 60); do
    if docker logs "$NAME" 2>&1 | grep -q "PostgreSQL init process complete" \
       && docker exec "$NAME" pg_isready -q -U postgres -h /var/run/postgresql; then
      break
    fi
    sleep 1
  done
  docker exec "$NAME" pg_isready -q -U postgres -h /var/run/postgresql \
    || { echo "the recovery PostgreSQL did not start" >&2; docker logs "$NAME" >&2; exit 1; }
  chmod 700 "$SOCKET_DIR"  # again, in case anything changed it
  tools="docker run --rm -i --network none -v $SOCKET_DIR/run:$SOCKET_DIR/run -e PGHOST -e PGUSER -e PGPASSWORD $IMAGE"
  cat <<EOF
export PGHOST='$SOCKET_DIR/run' PGUSER=postgres PGPORT=5432
unset PGPASSWORD MARKX_DB_MIGRATOR_PASSWORD MARKX_DB_APP_PASSWORD MARKX_DB_READONLY_PASSWORD
export MARKX_BACKUP_PG_RESTORE_COMMAND='$tools pg_restore'
export MARKX_BACKUP_PSQL_COMMAND='$tools psql'
export MARKX_BACKUP_PG_DUMP_COMMAND='$tools pg_dump'
EOF
  echo "recovery PostgreSQL ready: container $NAME, no network, private socket folder $SOCKET_DIR" >&2
}

# Empty our own socket folder (its mark stays until the folder goes).
clear_socket_dir() {
  find "$SOCKET_DIR" -mindepth 1 -maxdepth 1 ! -name "$MARK" -exec rm -rf -- {} + 2>/dev/null || true
}

stop() {
  check_name
  check_socket_dir
  local label; label="$(container_label)"
  if docker container inspect "$NAME" >/dev/null 2>&1; then
    [[ "$label" == 1 ]] \
      || die "the container $NAME was not started by this script (no '$LABEL' label); it was left alone"
    # A clean shutdown first: PostgreSQL then removes its own socket files.
    docker stop -t 30 "$NAME" >/dev/null 2>&1 || true
    docker rm -f -v "$NAME" >/dev/null 2>&1 || true
  fi
  if [[ -e "$SOCKET_DIR" || -L "$SOCKET_DIR" ]]; then
    ours || die "$SOCKET_DIR is not this script's socket folder (no mark, another owner or a link); it was left alone"
    clear_socket_dir
    rm -f -- "$SOCKET_DIR/$MARK"
    rmdir -- "$SOCKET_DIR" 2>/dev/null \
      || die "$SOCKET_DIR still holds files this user cannot remove; it was left in place"
  fi
  echo "recovery PostgreSQL $NAME removed with its data" >&2
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  *) echo "usage: $0 start|stop" >&2; exit 2 ;;
esac
