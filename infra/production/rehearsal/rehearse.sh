#!/usr/bin/env bash
# The local rehearsal of a production deployment (D-091).
#
#   sudo -E infra/production/rehearsal/rehearse.sh            (CI, a laptop)
#   MARKX_BUILD_CA=/path/ca.crt sudo -E .../rehearse.sh      (behind a TLS-inspecting proxy)
#
# It builds the production images and runs the PRODUCTION Compose file and
# deploy.sh on this machine, with throwaway settings made up for the run
# (random passwords, a self-signed certificate for markx.example.invalid,
# MinIO instead of buckets), then tests what a real server relies on:
#
#   configuration  the file is valid; deploy.sh refuses example values; the
#                  API, the worker and the web app refuse to start as
#                  "production" without real settings, naming them, never a
#                  value
#   deployment     deploy.sh deploy: build, preflight, backup, one-time
#                  migration, start, verify
#   isolation      only the proxy has ports; PostgreSQL and the web app have
#                  no way out; PostgreSQL is unreachable from the proxy and
#                  the web app
#   the proxy      HTTP to HTTPS, certificate challenges, unknown names
#                  refused, TLS 1.2 and 1.3 only, security headers once, the
#                  dev routes and the API description hidden, body limits,
#                  the edge rate limit, the visitor's real address reaching
#                  the API (also through the web server's own calls)
#   health         readiness through the proxy, the worker's heartbeat and
#                  its jobs
#   migrations     two migration runs at once both succeed; nothing changes
#   backups        the backup service's dump restores into a new database
#   shutdown       every service stops on SIGTERM within its grace period
#   rollback       deploy.sh rollback to an earlier release
#
# Everything is local: no account, domain, certificate authority or bucket
# is contacted. It removes its containers, networks, volumes and files at
# the end (it is the only place `down -v` is ever run, on its own project).
# Exit status 0 only when every check passed.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
prod="$(cd "$here/.." && pwd)"
repo="$(cd "$prod/../.." && pwd)"
[[ $EUID -eq 0 ]] || { echo "run as root (sudo -E): it sets file owners as a server would" >&2; exit 2; }

work="$(mktemp -d "${RUNNER_TEMP:-/tmp}/markx-rehearsal.XXXXXX")"
chmod 755 "$work"
host="markx.example.invalid"
http_port=18080
https_port=18443

export MARKX_COMPOSE_ENV="$work/compose.env"
export MARKX_COMPOSE_OVERRIDE="$here/compose.rehearsal.yaml"
export MARKX_DEPLOY_REHEARSAL=1
export MARKX_DEPENDENCY_SERVICES="postgres minio"
export MARKX_BUILD_CA="${MARKX_BUILD_CA:-/dev/null}"

compose() {
  docker compose -f "$prod/compose.yaml" -f "$MARKX_COMPOSE_OVERRIDE" --env-file "$MARKX_COMPOSE_ENV" "$@"
}

passed=0
failed=0
pass() { echo "PASS  $*"; passed=$((passed + 1)); }
fail() { echo "FAIL  $*"; failed=$((failed + 1)); }
check() { # description, command...
  local what="$1"; shift
  if "$@" >/dev/null 2>&1; then pass "$what"; else fail "$what"; fi
}
refuse() { # description, command... (must fail)
  local what="$1"; shift
  if "$@" >/dev/null 2>&1; then fail "$what"; else pass "$what"; fi
}

cleanup() {
  local status=$?
  if [[ $status -ne 0 || $failed -ne 0 ]]; then
    echo "---- container states and the last log lines, for the failure above"
    compose ps -a 2>/dev/null || true
    compose logs --tail 40 2>/dev/null | grep -v -E 'PASSWORD|SECRET' || true
  fi
  export MARKX_RELEASE=rehearsal-1
  compose --profile migrate down -v --remove-orphans >/dev/null 2>&1 || true
  docker image rm -f markx/api:rehearsal-1 markx/web:rehearsal-1 \
    markx/api:rehearsal-2 markx/web:rehearsal-2 >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

random() { head -c 32 /dev/urandom | base64 | tr -d '/+=' | cut -c1-32; }

# -- 1. throwaway settings, laid out as on a server -------------------------------

config="$work/etc"; tls="$config/tls"; acme="$work/acme"; backups="$work/backups"
mkdir -p "$config" "$tls" "$acme/.well-known/acme-challenge" "$backups"
superuser_pw="rehearsal-$(random)"; migrator_pw="rehearsal-$(random)"
app_pw="rehearsal-$(random)"; readonly_pw="rehearsal-$(random)"
secret_key="rehearsal-$(random)$(random)"

cat > "$MARKX_COMPOSE_ENV" <<EOF
MARKX_ENV=local
MARKX_CONFIG_DIR=$config
MARKX_SITE_HOSTNAME=$host
MARKX_PUBLIC_ORIGIN=https://$host
MARKX_MEDIA_ORIGIN=https://media.$host
MARKX_HSTS_MAX_AGE=31536000
MARKX_TLS_DIR=$tls
MARKX_ACME_DIR=$acme
MARKX_BACKUP_HOST_DIR=$backups
MARKX_PUBLIC_BIND=127.0.0.1
MARKX_HTTP_PORT=$http_port
MARKX_HTTPS_PORT=$https_port
MARKX_API_WORKERS=1
EOF
cat > "$config/api.env" <<EOF
MARKX_DATABASE_URL=postgresql+psycopg://markx_app:$app_pw@postgres:5432/markx
MARKX_MIGRATION_DATABASE_URL=postgresql+psycopg://markx_migrator@postgres:5432/markx
MARKX_SECRET_KEY=$secret_key
MARKX_PUBLIC_ORIGIN=https://$host
MARKX_COOKIE_SECURE=true
MARKX_LOG_LEVEL=INFO
MARKX_FILE_STORAGE_PROVIDER=minio
MARKX_STORAGE_ENDPOINT_URL=http://minio:9000
MARKX_STORAGE_ACCESS_KEY_ID=markx-dev-only
MARKX_STORAGE_SECRET_ACCESS_KEY=markx-minio-dev-only-password
MARKX_STORAGE_PRIVATE_BUCKET=markx-private
MARKX_STORAGE_PUBLIC_BUCKET=markx-public
EOF
echo "MARKX_MIGRATION_DATABASE_URL=postgresql+psycopg://markx_migrator:$migrator_pw@postgres:5432/markx" > "$config/migrate.env"
cat > "$config/postgres.env" <<EOF
POSTGRES_PASSWORD=$superuser_pw
MARKX_DB_MIGRATOR_PASSWORD=$migrator_pw
MARKX_DB_APP_PASSWORD=$app_pw
MARKX_DB_READONLY_PASSWORD=$readonly_pw
EOF
# No site key: the production start-up check below must name it.
echo "MARKX_TURNSTILE_SITE_KEY=" > "$config/web.env"
cat > "$config/backup.env" <<EOF
PGPASSWORD=$migrator_pw
MARKX_BACKUP_HOUR_UTC=23
MARKX_BACKUP_KEEP_DAYS=30
EOF
chmod 600 "$config"/*.env
head -c 48 /dev/urandom | base64 > "$config/backup.key"
chown 999:999 "$config/backup.key"; chmod 400 "$config/backup.key"
chown 999:999 "$backups"; chmod 700 "$backups"
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=$host" \
  -addext "subjectAltName=DNS:$host" -keyout "$tls/privkey.pem" -out "$tls/fullchain.pem" 2>/dev/null
chown 101:101 "$tls/privkey.pem"; chmod 400 "$tls/privkey.pem"; chmod 644 "$tls/fullchain.pem"
echo "rehearsal-token-content" > "$acme/.well-known/acme-challenge/rehearsal-token"
chmod -R a+rX "$acme"

secrets_of_this_run=("$superuser_pw" "$migrator_pw" "$app_pw" "$readonly_pw" "$secret_key")
leaks_none() { # file: none of this run's secrets appears in it
  local s; for s in "${secrets_of_this_run[@]}"; do ! grep -qF -- "$s" "$1" || return 1; done
}

# -- 2. configuration -------------------------------------------------------------

echo "== configuration"
examples="$work/examples"; mkdir -p "$examples"
for f in "$prod"/env/*.env.example; do cp "$f" "$examples/$(basename "$f" .example)"; done
sed -i "s|^MARKX_CONFIG_DIR=.*|MARKX_CONFIG_DIR=$examples|" "$examples/compose.env"
check "the production Compose file is valid with the example settings" \
  env MARKX_RELEASE=check docker compose -f "$prod/compose.yaml" --env-file "$examples/compose.env" config --quiet
refuse "deploy.sh check refuses the example settings (placeholders, owners, no certificate)" \
  env -u MARKX_DEPLOY_REHEARSAL MARKX_COMPOSE_ENV="$examples/compose.env" "$prod/deploy.sh" check
check "deploy.sh refuses a stage other than staging or production" \
  bash -c "sed 's/^MARKX_ENV=.*/MARKX_ENV=prod/' '$examples/compose.env' > '$work/bad.env'; ! MARKX_COMPOSE_ENV='$work/bad.env' '$prod/deploy.sh' check"
check "deploy.sh check passes for the rehearsal's server layout" "$prod/deploy.sh" check

export MARKX_RELEASE=rehearsal-1
echo "== build (this takes a few minutes)"
compose build api web

compose up -d --wait postgres
compose run --rm --no-deps -T -e MARKX_ENV=production api python -c "import markx.main" > "$work/api-refusal.txt" 2>&1 || true
if grep -q "MARKX_SMS_PROVIDER must be a real SMS provider" "$work/api-refusal.txt" \
  && grep -q "MARKX_FILE_STORAGE_PROVIDER must be real object storage" "$work/api-refusal.txt" \
  && grep -q "MARKX_BOT_CHECK_PROVIDER must be a real bot check" "$work/api-refusal.txt" \
  && leaks_none "$work/api-refusal.txt"; then
  pass "the API refuses to start as production with development settings, naming them, no value"
else
  fail "the API refuses to start as production with development settings"; cat "$work/api-refusal.txt"
fi
compose run --rm --no-deps -T -e MARKX_ENV=production worker > "$work/worker-refusal.txt" 2>&1 && worker_status=0 || worker_status=$?
if [[ $worker_status -ne 0 ]] && grep -q "MARKX_SMS_PROVIDER" "$work/worker-refusal.txt" && leaks_none "$work/worker-refusal.txt"; then
  pass "the worker refuses to start as production with development settings"
else
  fail "the worker refuses to start as production"; cat "$work/worker-refusal.txt"
fi
compose run --rm --no-deps -T -e MARKX_ENV=production api python -m markx.ops.preflight --config-only > "$work/preflight.txt" 2>&1 && pre_status=0 || pre_status=$?
if [[ $pre_status -eq 2 ]] && grep -q "configuration: REFUSED" "$work/preflight.txt" && leaks_none "$work/preflight.txt"; then
  pass "preflight refuses the production configuration with exit 2, no value"
else
  fail "preflight refuses the production configuration"; cat "$work/preflight.txt"
fi
compose run --rm --no-deps -T -e MARKX_ENV=production web > "$work/web-refusal.txt" 2>&1 && web_status=0 || web_status=$?
if [[ $web_status -eq 2 ]] && grep -q "MARKX_TURNSTILE_SITE_KEY must be set" "$work/web-refusal.txt"; then
  pass "the web app refuses to start as production without its site key (exit 2)"
else
  fail "the web app refuses to start as production"; cat "$work/web-refusal.txt"
fi

# -- 3. deployment ----------------------------------------------------------------

# MinIO reports healthy a moment before it has made its two buckets; a real
# provider's buckets exist before any deploy.
compose up -d --wait minio >/dev/null 2>&1
for _ in $(seq 1 30); do
  compose exec -T minio sh -c 'test -d /bitnami/minio/data/markx-private && test -d /bitnami/minio/data/markx-public' \
    >/dev/null 2>&1 && break
  sleep 1
done

echo "== deploy.sh deploy rehearsal-1"
if "$prod/deploy.sh" deploy rehearsal-1 > "$work/deploy.txt" 2>&1; then
  pass "deploy.sh deploy: build, preflight, backup, migration, start, verify"
else
  fail "deploy.sh deploy"; tail -40 "$work/deploy.txt"; exit 1
fi
check "the deploy log holds none of this run's secrets" leaks_none "$work/deploy.txt"
check "the release is recorded" grep -q " deploy rehearsal-1$" "$config/releases.log"

# -- 4. isolation -----------------------------------------------------------------

# From here on every check runs and is reported, whatever an earlier one did.
set +e

echo "== isolation"
published=""
for s in $(compose ps --services); do
  ports="$(docker inspect "$(compose ps -q "$s")" --format '{{range $p, $b := .NetworkSettings.Ports}}{{if $b}}{{$p}} {{end}}{{end}}')"
  if [[ -n "$ports" ]]; then published+="$s "; fi
done
if [[ "$published" == "proxy " ]]; then pass "only the proxy publishes ports"; else fail "published ports: $published"; fi
tcp() { # service, host, port: can that container open a TCP connection?
  case "$1" in
    web) compose exec -T web node -e "const s=require('net').connect({host:'$2',port:$3,timeout:4000});s.on('connect',()=>process.exit(0));s.on('error',()=>process.exit(1));s.on('timeout',()=>process.exit(1))" ;;
    proxy) compose exec -T proxy nc -z -w 4 "$2" "$3" ;;
    *) compose exec -T "$1" bash -c "timeout 5 bash -c '</dev/tcp/$2/$3'" ;;
  esac
}
refuse "PostgreSQL has no way out to the internet" tcp postgres 1.1.1.1 443
refuse "the web app has no way out to the internet" tcp web 1.1.1.1 443
check  "the API can reach the internet (outside services)" tcp api 1.1.1.1 443
refuse "the web app cannot reach PostgreSQL" tcp web postgres 5432
refuse "the proxy cannot reach PostgreSQL" tcp proxy postgres 5432
check  "the API reaches PostgreSQL" tcp api postgres 5432
if tcp proxy api 8000 >/dev/null 2>&1 && tcp proxy web 3000 >/dev/null 2>&1; then
  pass "the proxy reaches the API and the web app"
else
  fail "the proxy reaches the API and the web app"
fi
for s in api worker web proxy; do
  user="$(docker inspect "$(compose ps -q "$s")" --format '{{.Config.User}}')"
  [[ -z "$user" ]] && user="$(compose exec -T "$s" id -u)"
  case "$user" in 0|root) fail "$s runs as root" ;; *) pass "$s runs as an unprivileged user ($user)" ;; esac
  ro="$(docker inspect "$(compose ps -q "$s")" --format '{{.HostConfig.ReadonlyRootfs}}')"
  [[ "$ro" == true ]] && pass "$s has a read-only root file system" || fail "$s root file system is writable"
done

# -- 5. the proxy -----------------------------------------------------------------

echo "== the proxy"
cacert="$tls/fullchain.pem"
url="https://$host:$https_port"
code() { https -o /dev/null -w '%{http_code}' "$@"; }
# --noproxy: talk to this machine's proxy container directly, even where an
# outbound HTTP(S) proxy is configured for everything else.
https() { curl -sS --noproxy '*' --resolve "$host:$https_port:127.0.0.1" --cacert "$cacert" "$@"; }

redirect="$(curl -sS --noproxy '*' -o /dev/null -w '%{http_code} %{redirect_url}' "http://127.0.0.1:$http_port/am/search?q=x")"
[[ "$redirect" == "301 https://$host/am/search?q=x" ]] && pass "HTTP is redirected to HTTPS on the site's hostname" || fail "HTTP redirect: $redirect"
redirect="$(curl -sS --noproxy '*' -o /dev/null -w '%{redirect_url}' -H 'Host: evil.example' "http://127.0.0.1:$http_port/")"
[[ "$redirect" == "https://$host/" ]] && pass "the redirect never uses the visitor's Host header" || fail "redirect with a forged Host: $redirect"
[[ "$(curl -sS --noproxy '*' "http://127.0.0.1:$http_port/.well-known/acme-challenge/rehearsal-token")" == "rehearsal-token-content" ]] \
  && pass "certificate challenges are served over HTTP" || fail "certificate challenges"
unknown="$(curl -sS --noproxy '*' --resolve "other.invalid:$https_port:127.0.0.1" -k -o /dev/null "https://other.invalid:$https_port/" 2>&1)"
if grep -qi -E 'alert|handshake|unrecognized name|ssl' <<<"$unknown" && https -o /dev/null "$url/healthz"; then
  pass "an unknown hostname is refused at the TLS handshake"
else
  fail "unknown hostname: $unknown"
fi
# A client that offers TLS 1.1 at most must be refused by the server (if the
# local OpenSSL cannot offer 1.1 at all, this proves less; it is said so).
if openssl s_client -connect "127.0.0.1:$https_port" -servername "$host" -tls1_1 </dev/null >"$work/tls11.txt" 2>&1; then
  fail "TLS 1.1 is accepted"
elif grep -qi 'no protocols available' "$work/tls11.txt"; then
  pass "TLS 1.1 is refused (the local OpenSSL cannot offer it either; weaker evidence)"
else
  pass "TLS 1.1 is refused by the server"
fi
check  "TLS 1.2 is accepted" https --tlsv1.2 --tls-max 1.2 -o /dev/null "$url/healthz"
check  "TLS 1.3 is accepted" https --tlsv1.3 -o /dev/null "$url/healthz"

https -D - -o /dev/null "$url/am" | tr -d '\r' > "$work/page.h"
grep -qi '^HTTP/2 200' "$work/page.h" && pass "a page is served over HTTP/2" || fail "page: $(head -1 "$work/page.h")"
[[ "$(grep -ci '^strict-transport-security: max-age=31536000' "$work/page.h")" == 1 ]] && pass "a page has HSTS exactly once" || fail "page HSTS"
grep -qi '^content-security-policy:' "$work/page.h" && pass "a page has its security policy" || fail "page CSP"
grep -qi '^x-powered-by' "$work/page.h" && fail "a page says X-Powered-By" || pass "a page does not name its framework"
grep -qi '^server: nginx$' "$work/page.h" && pass "the Server header has no version" || fail "server header: $(grep -i '^server' "$work/page.h")"

https -D - -o "$work/ready.json" "$url/api/v1/healthz/ready" | tr -d '\r' > "$work/ready.h"
grep -q '"status":"ready"' "$work/ready.json" && pass "the API is ready through the proxy" || fail "readiness: $(cat "$work/ready.json")"
[[ "$(grep -ci '^strict-transport-security' "$work/ready.h")" == 1 ]] && pass "an API answer has HSTS exactly once" || fail "API HSTS"
grep -qi '^server: uvicorn' "$work/ready.h" && fail "the API names its server" || pass "the API does not name its server"
[[ "$(code "$url/api/v1/healthz/live")" == 200 ]] && pass "liveness answers" || fail "liveness"
for path in /api/v1/openapi.json /api/v1/docs "/api/v1/dev/sms-inbox?phone=0911000000"; do
  [[ "$(code "$url$path")" == 404 ]] && pass "$path is not public" || fail "$path is public"
done

head -c 2000000 /dev/zero > "$work/2mb"; head -c 5000000 /dev/zero > "$work/5mb"; head -c 25000000 /dev/zero > "$work/25mb"
[[ "$(code -X POST -H 'Content-Type: application/json' --data-binary @"$work/2mb" "$url/api/v1/auth/otp/request")" == 413 ]] \
  && pass "a 2 MB JSON body is refused at the proxy (413)" || fail "2 MB JSON body"
upload="$url/api/v1/seller/00000000-0000-0000-0000-000000000000/documents"
status="$(code -X POST -H 'Content-Type: application/octet-stream' --data-binary @"$work/5mb" "$upload")"
[[ "$status" != 413 && "$status" =~ ^4 ]] && pass "a 5 MB upload reaches the API, which decides ($status)" || fail "5 MB upload: $status"
[[ "$(code -X POST -H 'Content-Type: application/octet-stream' --data-binary @"$work/25mb" "$upload")" == 413 ]] \
  && pass "a 25 MB upload is refused at the proxy (413)" || fail "25 MB upload"

# The visitor's address. The proxy SETS X-Forwarded-For; the API trusts only
# the frontend network; the web server passes the address on (D-091).
psql_markx() { compose exec -T postgres psql -U postgres -d markx -tAc "$1"; }
psql_markx "delete from rate_limit_counters where bucket like 'search:%'" >/dev/null
https -o /dev/null -H 'X-Forwarded-For: 6.6.6.6' "$url/api/v1/search?q=rehearsal&lang=en"
https -o /dev/null -H 'X-Forwarded-For: 6.6.6.6' "$url/en"
buckets="$(psql_markx "select bucket || '=' || sum(count) from rate_limit_counters where bucket like 'search:ip:%' group by bucket order by bucket")"
subnet_prefix="172.30.10."
if [[ -n "$buckets" ]] && ! grep -q '6.6.6.6' <<<"$buckets" && ! grep -q "$subnet_prefix" <<<"$buckets" \
  && [[ "$(wc -l <<<"$buckets")" == 1 ]] && grep -q '=2$' <<<"$buckets"; then
  pass "one visitor is one address: the API call and the page's own call count the visitor, never a forged or internal address"
else
  fail "visitor address in the rate-limit counters: $buckets"
fi

codes="$(for _ in $(seq 1 45); do code "$url/api/v1/auth/sign-out-everywhere"; echo; done | sort | uniq -c | tr '\n' ' ')"
grep -q ' 429' <<<"$codes" && pass "the edge rate limit answers 429 to a burst on sign-in" || fail "edge rate limit: $codes"

# -- 6. health, migrations, backups ------------------------------------------------

echo "== health, migrations, backups"
for _ in $(seq 1 30); do
  [[ "$(docker inspect "$(compose ps -q worker)" --format '{{.State.Health.Status}}')" == healthy ]] && break; sleep 3
done
[[ "$(docker inspect "$(compose ps -q worker)" --format '{{.State.Health.Status}}')" == healthy ]] \
  && pass "the worker's heartbeat check is healthy" || fail "worker health"
for _ in $(seq 1 30); do [[ "$(code "$url/api/v1/healthz/worker")" == 200 ]] && break; sleep 3; done
[[ "$(code "$url/api/v1/healthz/worker")" == 200 ]] && pass "the worker runs its scheduled jobs (/healthz/worker)" || fail "/healthz/worker"

before="$(psql_markx "select version_num from alembic_version")"
compose --profile migrate run --rm -T migrate > "$work/m1.txt" 2>&1 & m1=$!
compose --profile migrate run --rm -T migrate > "$work/m2.txt" 2>&1 & m2=$!
if wait $m1 && wait $m2; then pass "two migration runs at once both finish"; else fail "concurrent migrations"; cat "$work/m1.txt" "$work/m2.txt"; fi
[[ "$(psql_markx "select version_num from alembic_version")" == "$before" ]] && pass "and the schema did not change" || fail "schema changed"

dump="$(ls -t "$backups"/markx-markx-*.dump.enc | head -1)"
[[ -n "$dump" && "$(stat -c %u "$dump")" == 999 && "$(stat -c %a "$dump")" == 600 ]] \
  && pass "backups are written encrypted, owner 999, mode 600 ($(ls "$backups"/*.dump.enc | wc -l) so far)" || fail "backup files"
check "the backup service is healthy" bash -c "[[ \$(docker inspect $(compose ps -q backup) --format '{{.State.Health.Status}}') == healthy ]]"
if compose run --rm --no-deps -T --entrypoint bash \
    -e PGUSER=postgres -e PGPASSWORD="$superuser_pw" \
    -e MARKX_DB_MIGRATOR_PASSWORD="$migrator_pw" -e MARKX_DB_APP_PASSWORD="$app_pw" \
    -e MARKX_DB_READONLY_PASSWORD="$readonly_pw" backup -c \
    "/markx-backup/restore.sh /backups/$(basename "$dump") markx_restore_check && psql -d markx_restore_check -tAc 'select version_num from alembic_version'" \
    > "$work/restore.txt" 2>&1 && grep -q "$before" "$work/restore.txt"; then
  pass "the latest dump restores into a new database at the same migration"
else
  fail "restore"; cat "$work/restore.txt"
fi
if compose exec -T api python -m markx.ops.preflight 2>&1 | grep -q 'preflight: PASSED'; then
  pass "the restore did not change the running site's passwords (preflight still passes)"
else
  fail "after the restore the API cannot use the database"
fi
psql_markx "drop database markx_restore_check" >/dev/null 2>&1 || true

# -- 7. rollback ------------------------------------------------------------------

echo "== rollback"
docker tag markx/api:rehearsal-1 markx/api:rehearsal-2
docker tag markx/web:rehearsal-1 markx/web:rehearsal-2
if MARKX_RELEASE=rehearsal-2 "$prod/deploy.sh" rollback rehearsal-2 > "$work/rollback.txt" 2>&1 \
  && [[ "$(docker inspect "$(compose ps -q api)" --format '{{.Config.Image}}')" == markx/api:rehearsal-2 ]]; then
  pass "deploy.sh rollback starts another release's images, verified"
else
  fail "rollback"; tail -30 "$work/rollback.txt"
fi
export MARKX_RELEASE=rehearsal-2
refuse "rollback refuses a release whose images are not here" "$prod/deploy.sh" rollback no-such-release

# -- 8. shutdown ------------------------------------------------------------------

echo "== shutdown"
for s in proxy web api worker backup postgres; do
  id="$(compose ps -q "$s")"
  started=$(date +%s)
  compose stop "$s" >/dev/null 2>&1
  took=$(( $(date +%s) - started ))
  exit_code="$(docker inspect "$id" --format '{{.State.ExitCode}}')"
  # 137 is SIGKILL: the grace period ran out.
  if [[ "$exit_code" != 137 ]]; then pass "$s stops on SIGTERM in ${took}s (exit $exit_code)"; else fail "$s was killed after ${took}s"; fi
done

echo
echo "rehearsal: $passed passed, $failed failed"
[[ $failed -eq 0 ]]
