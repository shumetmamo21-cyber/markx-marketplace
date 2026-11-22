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
#   backups        the backup service makes a verified, signed set; a real
#                  server refuses a same-server destination; the recovery
#                  drill restores database and files and refuses tampering
#   alerts and    (D-105) the secrets copy made by deploy.sh holds no secret in
#   secrets copy   plain form and opens with the recovery key from the bucket;
#                  the test alert says nobody was told while alerts are off;
#                  a paused container is found by the watch, which tries to
#                  alert; the recovery PostgreSQL's socket folder is private
#                  and a folder that is not its own is left alone
#   containers     (D-103) every outside image by digest; memory, CPU and
#                  process limits on every service; the user ids the images set
#   certificate    (D-103) a new certificate installed and served without a
#                  restart; a wrong one refused; renewal off by default and,
#                  switched on, renewed through certbot's deploy hook (a
#                  stand-in for certbot: no certificate authority is
#                  contacted); the renewal timer's units; the worker's watch
#                  alerts before expiry and stops when renewed
#   rollback       deploy.sh rollback to an earlier release, every service
#                  including the backup service, with MARKX_IMAGE_PREFIX set
#   failed update  (D-103) a release that fails its checks after the
#                  migration: back on the last working release; and when that
#                  release refuses the migrated database, a safe stop with
#                  instructions, then the documented way out
#   the setting    (D-103) MARKX_ALLOW_NEWER_SCHEMA left on: a rollback needs
#   left on        --accept-newer-schema as well; deploy refuses to start, and
#                  the new release refuses it wherever it is set; the
#                  reviewer's case (a database with a later change, the
#                  setting on, a failed update): the automatic return checks
#                  the old release with the setting forced off and refuses;
#                  then a roll forward, and the run ends with the setting off
#   shutdown       every service stops on SIGTERM within its grace period
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
compose_files=(-f "$prod/compose.yaml" -f "$here/compose.rehearsal.yaml")
if [[ -n "${MARKX_BUILD_CA:-}" ]]; then
  MARKX_COMPOSE_OVERRIDE+=":$here/compose.build-ca.yaml"
  compose_files+=(-f "$here/compose.build-ca.yaml")
fi
export MARKX_DEPLOY_REHEARSAL=1
export MARKX_DEPENDENCY_SERVICES="postgres minio"
# D-103: the whole rehearsal names its images with a prefix of its own, so
# deploy, rollback and recovery prove they use MARKX_IMAGE_PREFIX.
prefix="markx-rehearsal"

compose() {
  docker compose "${compose_files[@]}" --env-file "$MARKX_COMPOSE_ENV" "$@"
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
  local r i
  for r in 1 2 3 4 5 6 7; do
    for i in api web backup; do docker image rm -f "$prefix/$i:rehearsal-$r" >/dev/null 2>&1 || true; done
  done
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
# D-105: a real server has its own encryption key (the secrets copy refuses
# an api.env without one); a random Fernet key for this run.
encryption_key="$(head -c 32 /dev/urandom | base64 | tr '+/' '-_')"

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
MARKX_IMAGE_PREFIX=$prefix
MARKX_TLS_RENEWAL=none
EOF
cat > "$config/api.env" <<EOF
MARKX_DATABASE_URL=postgresql+psycopg://markx_app:$app_pw@postgres:5432/markx
MARKX_MIGRATION_DATABASE_URL=postgresql+psycopg://markx_migrator@postgres:5432/markx
MARKX_SECRET_KEY=$secret_key
MARKX_ENCRYPTION_KEY=$encryption_key
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
# The backup service (D-094) writes to a MinIO bucket of its own here; a
# real server refuses MinIO (checked below) and needs s3 or r2.
cat > "$config/backup.env" <<EOF
PGPASSWORD=$migrator_pw
MARKX_BACKUP_DESTINATION=minio
MARKX_BACKUP_DESTINATION_ENDPOINT_URL=http://minio:9000
MARKX_BACKUP_DESTINATION_BUCKET=markx-backups
MARKX_BACKUP_DESTINATION_PREFIX=markx/rehearsal
MARKX_BACKUP_DESTINATION_ACCESS_KEY_ID=markx-dev-only
MARKX_BACKUP_DESTINATION_SECRET_ACCESS_KEY=markx-minio-dev-only-password
MARKX_BACKUP_SOURCE_PROVIDER=minio
MARKX_BACKUP_SOURCE_ENDPOINT_URL=http://minio:9000
MARKX_BACKUP_SOURCE_PRIVATE_BUCKET=markx-private
MARKX_BACKUP_SOURCE_PUBLIC_BUCKET=markx-public
MARKX_BACKUP_SOURCE_ACCESS_KEY_ID=markx-dev-only
MARKX_BACKUP_SOURCE_SECRET_ACCESS_KEY=markx-minio-dev-only-password
MARKX_BACKUP_HOUR_UTC=23
MARKX_BACKUP_RETENTION_DAYS=7
MARKX_BACKUP_RETENTION_MIN_SETS=3
EOF
chmod 600 "$config"/*.env
# The backup keys, made with openssl in the format `python -m markx.backup
# keygen` writes (the image is not built yet). The RECOVERY key stays out of
# the server's configuration folder, as on a real server.
raw_keypair() { # algorithm, private label, public label, private file, public file
  openssl genpkey -algorithm "$1" -outform DER -out "$work/key.der" 2>/dev/null
  printf '%s:%s\n' "$2" "$(tail -c 32 "$work/key.der" | base64 -w0)" > "$4"
  printf '%s:%s\n' "$3" "$(openssl pkey -inform DER -in "$work/key.der" -pubout -outform DER | tail -c 32 | base64 -w0)" > "$5"
  rm -f "$work/key.der"
}
raw_keypair X25519 MARKX-BACKUP-RECOVERY-KEY-1 MARKX-BACKUP-PUBLIC-KEY-1 "$work/recovery.key" "$config/backup-public.key"
raw_keypair ED25519 MARKX-BACKUP-SIGNING-KEY-1 MARKX-BACKUP-SIGNER-1 "$config/backup-signing.key" "$work/signer-public.key"
chown 999:999 "$config/backup-signing.key"; chmod 400 "$config/backup-signing.key"
chmod 644 "$config/backup-public.key"
# Only the drill below reads these, mounted into a one-off container.
chown 999:999 "$work/recovery.key" "$work/signer-public.key"; chmod 600 "$work/recovery.key"
chown 999:999 "$backups"; chmod 700 "$backups"
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=$host" \
  -addext "subjectAltName=DNS:$host" -keyout "$tls/privkey.pem" -out "$tls/fullchain.pem" 2>/dev/null
chown 101:101 "$tls/privkey.pem"; chmod 400 "$tls/privkey.pem"; chmod 644 "$tls/fullchain.pem"
echo "rehearsal-token-content" > "$acme/.well-known/acme-challenge/rehearsal-token"
chmod -R a+rX "$acme"

secrets_of_this_run=("$superuser_pw" "$migrator_pw" "$app_pw" "$readonly_pw" "$secret_key" "$encryption_key")
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
cp "$work/recovery.key" "$config/stray-recovery.key"
refuse "deploy.sh check refuses a backup RECOVERY key on the server" "$prod/deploy.sh" check
rm -f "$config/stray-recovery.key"

export MARKX_RELEASE=rehearsal-1
echo "== build (this takes a few minutes)"
compose build api web backup

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
compose run --rm --no-deps -T -e MARKX_ENV=production backup python -m markx.backup run > "$work/backup-refusal.txt" 2>&1 && backup_status=0 || backup_status=$?
if [[ $backup_status -eq 2 ]] && grep -q "must be off-server object storage" "$work/backup-refusal.txt" \
  && ! grep -q "markx-minio-dev-only-password" "$work/backup-refusal.txt" && leaks_none "$work/backup-refusal.txt"; then
  pass "the backup service refuses, as production, a backup that is not off-server (exit 2, no value)"
else
  fail "the backup service refuses a same-server backup as production"; cat "$work/backup-refusal.txt"
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
for s in api worker web proxy backup; do
  user="$(docker inspect "$(compose ps -q "$s")" --format '{{.Config.User}}')"
  [[ -z "$user" ]] && user="$(compose exec -T "$s" id -u)"
  case "$user" in 0|root) fail "$s runs as root" ;; *) pass "$s runs as an unprivileged user ($user)" ;; esac
  ro="$(docker inspect "$(compose ps -q "$s")" --format '{{.HostConfig.ReadonlyRootfs}}')"
  [[ "$ro" == true ]] && pass "$s has a read-only root file system" || fail "$s root file system is writable"
done

echo "== containers (D-103)"
for s in postgres api worker web proxy backup; do
  limits="$(docker inspect "$(compose ps -q "$s")" --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}}')"
  read -r memory cpus pids <<<"$limits"
  if (( memory > 0 && cpus > 0 && cpus <= 1000000000 && pids > 0 )); then
    pass "$s has memory, CPU and process limits ($memory bytes, $((cpus / 10000000))% of a CPU, $pids processes)"
  else
    fail "$s limits: $limits"
  fi
done
for s in api worker backup; do
  [[ "$(docker inspect "$(compose ps -q "$s")" --format '{{.Config.User}}')" == 999:999 ]] \
    && pass "$s runs as uid 999, set by its image" || fail "$s user: $(docker inspect "$(compose ps -q "$s")" --format '{{.Config.User}}')"
done
[[ "$(docker inspect "$(compose ps -q web)" --format '{{.Config.User}}')" == 1000:1000 ]] \
  && pass "web runs as uid 1000, set by its image" || fail "web user"
for s in postgres proxy minio; do
  [[ "$(docker inspect "$(compose ps -q "$s")" --format '{{.Config.Image}}')" =~ @sha256:[0-9a-f]{64}$ ]] \
    && pass "$s runs an image pinned to its digest" || fail "$s image: $(docker inspect "$(compose ps -q "$s")" --format '{{.Config.Image}}')"
done
[[ "$(docker inspect "$(compose ps -q api)" --format '{{.Config.Image}}')" == "$prefix/api:rehearsal-1" ]] \
  && pass "the release's images carry MARKX_IMAGE_PREFIX ($prefix)" || fail "api image name"
check  "the worker reads the certificate, for its expiry" compose exec -T worker test -r /run/markx-tls/fullchain.pem
refuse "the worker cannot read the certificate's private key" compose exec -T worker cat /run/markx-tls/privkey.pem

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

for _ in $(seq 1 40); do
  [[ "$(docker inspect "$(compose ps -q backup)" --format '{{.State.Health.Status}}')" == healthy ]] && break; sleep 3
done
check "the backup service is healthy (a verified set exists)" bash -c "[[ \$(docker inspect $(compose ps -q backup) --format '{{.State.Health.Status}}') == healthy ]]"
compose run --rm --no-deps -T backup python -m markx.backup list > "$work/sets.txt" 2>&1
grep -q " complete " "$work/sets.txt" && pass "the backup destination holds a complete, signed set" \
  || { fail "backup sets"; cat "$work/sets.txt"; }
dump="$(find "$backups/sets" -name database.dump.mxb 2>/dev/null | head -1)"
[[ -n "$dump" && "$(stat -c %u "$dump")" == 999 && "$(stat -c %a "$dump")" == 600 ]] \
  && head -c 8 "$dump" | grep -q "MARKXBK" \
  && pass "the local copy is MXB2 ciphertext, owner 999, mode 600" || fail "local backup copy: $dump"
# D-096 (BK-7): the drill logs in as the owner and application roles with
# their passwords, and never resets one; the MARKX_DB_*_PASSWORD values,
# which would, are refused on a server whose roles exist. (A real drill runs
# on a separate recovery machine, BK-2; this one rehearses the code path.)
if compose run --rm --no-deps -T \
    -v "$work/recovery.key:/run/recovery/recovery.key:ro" -v "$work/signer-public.key:/run/recovery/signer-public.key:ro" \
    -e PGUSER=postgres -e PGPASSWORD="$superuser_pw" \
    -e MARKX_RESTORE_OWNER_PASSWORD="$migrator_pw" -e MARKX_RESTORE_APP_PASSWORD="$app_pw" backup \
    python -m markx.backup drill --recovery-key /run/recovery/recovery.key --signer /run/recovery/signer-public.key \
    > "$work/drill.txt" 2>&1 && grep -q "DRILL PASSED" "$work/drill.txt" && grep -q "migration version: $before" "$work/drill.txt"; then
  pass "the recovery drill restores database and files into new targets, verified, and refuses every injected fault"
else
  fail "recovery drill"; cat "$work/drill.txt"
fi
check "the drill log holds none of this run's secrets" leaks_none "$work/drill.txt"
if compose exec -T api python -m markx.ops.preflight 2>&1 | grep -q 'preflight: PASSED'; then
  pass "the drill did not change the running site's passwords (preflight still passes)"
else
  fail "after the drill the API cannot use the database"
fi
[[ -z "$(psql_markx "select datname from pg_database where datname like 'markx_drill%'")" ]] \
  && pass "the drill removed its own database" || fail "a drill database was left behind"

# -- 6b. alerts that do not need the server, and the secrets copy (D-105) ----------------

echo "== alerts without the application, the secrets copy (D-105)"
# BK-5: deploy.sh pipes the settings and the certificate key into the backup
# image, which encrypts them to the recovery key's public half and puts the
# copy in the bucket too.
if "$prod/deploy.sh" escrow-secrets > "$work/escrow.txt" 2>&1; then
  pass "deploy.sh escrow-secrets makes a secrets copy and puts it in the backup bucket"
else
  fail "deploy.sh escrow-secrets"; cat "$work/escrow.txt"
fi
escrow_file="$(find "$backups/escrow" -name 'markx-secrets-*.json' 2>/dev/null | head -1)"
[[ -n "$escrow_file" && "$(stat -c %u "$escrow_file")" == 999 && "$(stat -c %a "$escrow_file")" == 600 ]] \
  && pass "the secrets copy is owner 999, mode 600" || fail "secrets copy file: $escrow_file"
[[ -n "$escrow_file" ]] && leaks_none "$escrow_file" \
  && pass "the secrets copy holds none of this run's secrets in plain form" \
  || fail "the secrets copy is missing or holds a secret in plain form"
check "deploy.sh escrow-secrets printed none of this run's secrets" leaks_none "$work/escrow.txt"
if compose run --rm --no-deps -T \
    -v "$work/recovery.key:/run/recovery/recovery.key:ro" -v "$work/signer-public.key:/run/recovery/signer-public.key:ro" \
    backup python -m markx.backup open-secrets --from-destination \
    --recovery-key /run/recovery/recovery.key --signer /run/recovery/signer-public.key --check \
    > "$work/escrow-open.txt" 2>&1 \
   && grep -q "signature and contents verified" "$work/escrow-open.txt" \
   && grep -q "  api.env " "$work/escrow-open.txt" && grep -q "  postgres.env " "$work/escrow-open.txt" \
   && grep -q "  tls/privkey.pem " "$work/escrow-open.txt"; then
  pass "the copy in the bucket opens with the recovery key: api.env, postgres.env, the certificate key"
else
  fail "opening the secrets copy"; cat "$work/escrow-open.txt"
fi
check "opening the copy printed none of this run's secrets" leaks_none "$work/escrow-open.txt"
# BK-4: alerts are off until the founder's group exists (F-18): the test
# alert must say that nobody was told, and fail.
if "$prod/deploy.sh" alert-test > "$work/alert-test.txt" 2>&1; then
  fail "alert-test passed although no alert group is configured"
else
  grep -q "NOT DELIVERED TO ANY PERSON" "$work/alert-test.txt" \
    && grep -q "outside heartbeat: OFF" "$work/alert-test.txt" \
    && pass "the test alert says nobody was told while alerts and the heartbeat are off" \
    || { fail "alert-test output"; cat "$work/alert-test.txt"; }
fi
# BK-4: the container watch on real containers. A paused container is a
# problem; seen for longer than the alert time (aged in the watch's state),
# the watch tries to alert through the worker's image; then all clear. The
# worker is paused for a few seconds only (its health check, every 30 s with
# 3 tries, stays healthy), and is waited for before the all-clear.
export MARKX_WATCH_STATE_DIR="$work/watch"
if "$prod/deploy.sh" watch > "$work/watch.txt" 2>&1 && grep -q "every container is running and healthy" "$work/watch.txt"; then
  pass "the container watch finds every container running and healthy"
else
  fail "container watch"; cat "$work/watch.txt"
fi
docker pause "$(compose ps -q worker)" >/dev/null
"$prod/deploy.sh" watch > "$work/watch.txt" 2>&1 || true
sed -i "s/^worker [0-9]* /worker $(( $(date +%s) - 3600 )) /" "$work/watch/containers"
"$prod/deploy.sh" watch > "$work/watch2.txt" 2>&1 && watch_status=0 || watch_status=$?
docker unpause "$(compose ps -q worker)" >/dev/null
for _ in $(seq 1 40); do
  [[ "$(docker inspect "$(compose ps -q worker)" --format '{{.State.Health.Status}}')" == healthy ]] && break; sleep 3
done
if [[ $watch_status -ne 0 ]] && grep -q "PROBLEM  worker: paused" "$work/watch2.txt" \
   && grep -q "NOT DELIVERED TO ANY PERSON" "$work/watch2.txt"; then
  pass "a paused container is found and the watch tries to alert the staff group through the bot"
else
  fail "the watch and a paused container"; cat "$work/watch.txt" "$work/watch2.txt"
fi
"$prod/deploy.sh" watch > "$work/watch3.txt" 2>&1 \
  && pass "unpaused, the watch is clear again" || { fail "watch after unpause"; cat "$work/watch3.txt"; }
unset MARKX_WATCH_STATE_DIR
# RN-2, RN-3: the recovery machine's PostgreSQL, for real.
recovery_sock="$work/rsock"
if MARKX_RECOVERY_SOCKET_DIR="$recovery_sock" MARKX_RECOVERY_CONTAINER=markx-rehearsal-recovery \
     "$repo/infra/backup/recovery-host.sh" start > "$work/recovery.env" 2> "$work/recovery.txt" \
   && [[ "$(stat -c %a "$recovery_sock")" == 700 ]] \
   && (source "$work/recovery.env" && pg_isready -q 2>/dev/null || [[ -S "$PGHOST/.s.PGSQL.5432" ]]); then
  pass "the recovery PostgreSQL starts with no network and a private (700) socket folder"
else
  fail "recovery PostgreSQL"; cat "$work/recovery.txt"
fi
MARKX_RECOVERY_SOCKET_DIR="$recovery_sock" MARKX_RECOVERY_CONTAINER=markx-rehearsal-recovery \
  "$repo/infra/backup/recovery-host.sh" stop 2>/dev/null
[[ ! -e "$recovery_sock" ]] && ! docker container inspect markx-rehearsal-recovery >/dev/null 2>&1 \
  && pass "and stop removes its container and its socket folder" || fail "recovery stop"
mkdir -p "$work/not-ours"; echo keep > "$work/not-ours/precious.txt"
refuse "the recovery script refuses a socket folder that is not its own" \
  env MARKX_RECOVERY_SOCKET_DIR="$work/not-ours" "$repo/infra/backup/recovery-host.sh" stop
[[ -f "$work/not-ours/precious.txt" ]] && pass "and leaves that folder's files alone" || fail "a foreign folder was emptied"

# -- 7. the certificate (D-103) ------------------------------------------------------

echo "== the certificate"
served_serial() {
  openssl s_client -connect "127.0.0.1:$https_port" -servername "$host" </dev/null 2>/dev/null \
    | openssl x509 -noout -serial 2>/dev/null
}
file_serial() { openssl x509 -in "$1" -noout -serial; }
# nginx applies a reload through new worker processes a moment later.
serves() { # certificate file: wait until the proxy serves it
  local want; want="$(file_serial "$1")"
  for _ in $(seq 1 15); do [[ "$(served_serial)" == "$want" ]] && return 0; sleep 1; done
  return 1
}
make_certificate() { # folder, days, [hostname]
  mkdir -p "$1"
  openssl req -x509 -newkey rsa:2048 -nodes -days "$2" -subj "/CN=${3:-$host}" \
    -addext "subjectAltName=DNS:${3:-$host}" -keyout "$1/privkey.pem" -out "$1/fullchain.pem" 2>/dev/null
}
alert_state() { # the open certificate alert's severity, or nothing
  psql_markx "select severity from ops_alerts where key = 'tls.certificate_expiring' and resolved_at is null"
}
run_watch_now() {
  psql_markx "update scheduled_jobs set next_run_at = now() where name = 'ops.watch'" >/dev/null
}
run_watch_now
for _ in $(seq 1 40); do [[ "$(alert_state)" == critical ]] && break; sleep 3; done
[[ "$(alert_state)" == critical ]] \
  && pass "the worker's watch raised a critical alert: the rehearsal's certificate expires in 2 days" \
  || fail "certificate alert: '$(alert_state)'"
"$prod/deploy.sh" certificate check > "$work/cert-check.txt" 2>&1 && st=0 || st=$?
[[ $st -ne 0 ]] && grep -q "was not renewed" "$work/cert-check.txt" \
  && pass "deploy.sh certificate check fails inside the warning time" || { fail "certificate check"; cat "$work/cert-check.txt"; }

before_serial="$(served_serial)"
make_certificate "$work/cert-other-host" 90 other.example.invalid
refuse "a certificate for another hostname is refused" "$prod/deploy.sh" certificate install "$work/cert-other-host"
make_certificate "$work/cert-a" 90; make_certificate "$work/cert-b" 90
mkdir -p "$work/cert-mismatch"; cp "$work/cert-a/fullchain.pem" "$work/cert-b/privkey.pem" "$work/cert-mismatch/"
refuse "a certificate with somebody else's key is refused" "$prod/deploy.sh" certificate install "$work/cert-mismatch"
[[ -n "$before_serial" && "$(served_serial)" == "$before_serial" ]] \
  && pass "after both refusals the proxy still serves the certificate it had" || fail "served certificate changed"
proxy_started="$(docker inspect "$(compose ps -q proxy)" --format '{{.State.StartedAt}}')"
if "$prod/deploy.sh" certificate install "$work/cert-a" > "$work/cert-install.txt" 2>&1 \
  && serves "$work/cert-a/fullchain.pem"; then
  pass "deploy.sh certificate install puts a new certificate in place and the proxy serves it"
else
  fail "certificate install"; cat "$work/cert-install.txt"
fi
[[ "$(docker inspect "$(compose ps -q proxy)" --format '{{.State.StartedAt}}')" == "$proxy_started" ]] \
  && pass "the proxy reloaded the certificate without a restart" || fail "the proxy was restarted"
[[ "$(stat -c '%u %a' "$tls/fullchain.pem")" == "0 644" && "$(stat -c '%u %a' "$tls/privkey.pem")" == "101 400" ]] \
  && pass "the installed files have the owners and modes deploy.sh check requires" || fail "installed file modes"
check "deploy.sh check passes with the installed certificate" "$prod/deploy.sh" check
check "deploy.sh certificate check passes with 90 days left" "$prod/deploy.sh" certificate check
run_watch_now
for _ in $(seq 1 40); do [[ -z "$(alert_state)" ]] && break; sleep 3; done
[[ -z "$(alert_state)" ]] && pass "the watch resolved the certificate alert after the renewal" || fail "alert still open: $(alert_state)"

"$prod/deploy.sh" certificate renew > "$work/renew-off.txt" 2>&1 \
  && grep -q "automatic renewal is OFF" "$work/renew-off.txt" \
  && pass "renewal is off by default (MARKX_TLS_RENEWAL=none) and says so" || { fail "renew with renewal off"; cat "$work/renew-off.txt"; }
refuse "deploy.sh certificate issue refuses while renewal is off" "$prod/deploy.sh" certificate issue
# A stand-in for certbot: contacts nobody; makes a "renewed" certificate in a
# lineage folder and runs the deploy hook it was given, as certbot does.
cat > "$work/certbot" <<STANDIN
#!/usr/bin/env bash
set -euo pipefail
echo "\$*" >> "$work/certbot.calls"
hook=""; webroot=""
while (( \$# )); do
  case "\$1" in --deploy-hook) hook="\$2"; shift 2 ;; -w) webroot="\$2"; shift 2 ;; *) shift ;; esac
done
[[ "\$webroot" == "$acme" ]] || { echo "certbot stand-in: wrong webroot '\$webroot'" >&2; exit 1; }
lineage="$work/letsencrypt/live/$host"; mkdir -p "\$lineage"
openssl req -x509 -newkey rsa:2048 -nodes -days 90 -subj "/CN=$host" -addext "subjectAltName=DNS:$host" \
  -keyout "\$lineage/privkey.pem" -out "\$lineage/fullchain.pem" 2>/dev/null
RENEWED_LINEAGE="\$lineage" sh -c "\$hook"
STANDIN
chmod 700 "$work/certbot"
sed -i 's/^MARKX_TLS_RENEWAL=.*/MARKX_TLS_RENEWAL=certbot/' "$MARKX_COMPOSE_ENV"
if MARKX_CERTBOT_COMMAND="$work/certbot" "$prod/deploy.sh" certificate renew > "$work/renew-on.txt" 2>&1 \
  && grep -q "^renew " "$work/certbot.calls" \
  && serves "$work/letsencrypt/live/$host/fullchain.pem"; then
  pass "with MARKX_TLS_RENEWAL=certbot, renew runs certbot, whose deploy hook installs the new certificate"
else
  fail "renewal through certbot's deploy hook"; cat "$work/renew-on.txt"
fi
sed -i 's/^MARKX_TLS_RENEWAL=.*/MARKX_TLS_RENEWAL=none/' "$MARKX_COMPOSE_ENV"
if MARKX_SYSTEMD_DIR="$work/systemd" "$prod/deploy.sh" certificate install-timer > /dev/null 2>&1 \
  && grep -qxF "ExecStart=$prod/deploy.sh certificate renew" "$work/systemd/markx-certificate.service" \
  && grep -qxF "Environment=MARKX_COMPOSE_ENV=$MARKX_COMPOSE_ENV" "$work/systemd/markx-certificate.service" \
  && grep -qxF "Persistent=true" "$work/systemd/markx-certificate.timer"; then
  if command -v systemd-analyze >/dev/null 2>&1; then
    if systemd-analyze verify "$work/systemd/markx-certificate.service" "$work/systemd/markx-certificate.timer" > "$work/verify.txt" 2>&1; then
      pass "the renewal timer's units are written with this server's paths and systemd accepts them"
    else
      fail "systemd-analyze verify"; cat "$work/verify.txt"
    fi
  else
    pass "the renewal timer's units are written with this server's paths (no systemd-analyze here; weaker evidence)"
  fi
else
  fail "the renewal timer's units"
fi

# -- 8. rollback, with MARKX_IMAGE_PREFIX set (D-103) ----------------------------------

echo "== rollback"
image_of() { docker inspect "$(compose ps -q "$1")" --format '{{.Config.Image}}'; }
release_images_of() { echo "$(image_of api) $(image_of worker) $(image_of web) $(image_of backup)"; }
images_of_release() { echo "$prefix/api:$1 $prefix/api:$1 $prefix/web:$1 $prefix/backup:$1"; }
for i in api web backup; do docker tag "$prefix/$i:rehearsal-1" "$prefix/$i:rehearsal-2"; done
if MARKX_RELEASE=rehearsal-2 "$prod/deploy.sh" rollback rehearsal-2 > "$work/rollback.txt" 2>&1 \
  && [[ "$(release_images_of)" == "$(images_of_release rehearsal-2)" ]]; then
  pass "deploy.sh rollback starts another release's images, the backup service's too, verified"
else
  fail "rollback ($(release_images_of))"; tail -30 "$work/rollback.txt"
fi
export MARKX_RELEASE=rehearsal-2
refuse "rollback refuses a release whose images are not here" "$prod/deploy.sh" rollback no-such-release
docker image rm "$prefix/backup:rehearsal-2" >/dev/null 2>&1 || true
refuse "rollback refuses a release whose backup image is missing" "$prod/deploy.sh" rollback rehearsal-2
docker tag "$prefix/backup:rehearsal-1" "$prefix/backup:rehearsal-2"

# -- 9. a release that fails its checks after the migration (D-103) -------------------

echo "== a failed update"
# A broken release: the same code, except that its API never becomes ready.
# Only its build context differs (a copy of apps/api, given to deploy.sh as
# one more Compose file), so the running services are not touched by it.
broken_release() { # name, with a newer migration (yes/no), broken (default) or healthy
  local dir="$work/$1"
  mkdir -p "$dir"
  tar -C "$repo/apps" --exclude=.venv --exclude=.mypy_cache --exclude=.ruff_cache \
    --exclude=.pytest_cache --exclude=__pycache__ -cf - api | tar -C "$dir" -xf -
  if [[ "${3:-broken}" == broken ]]; then
    sed -i 's/return self.schema == "current" or (self.schema == "ahead" and self.newer_schema_allowed)/return False  # rehearsal: a broken release/' \
      "$dir/api/markx/ops/health.py"
    grep -q "rehearsal: a broken release" "$dir/api/markx/ops/health.py" || return 1
  fi
  if [[ "$2" == yes ]]; then
    cat > "$dir/api/migrations/versions/29991231_0000_rehearsal_newer_schema.py" <<MIGRATION
"""The rehearsal's own migration: the database becomes newer than every real release."""
from alembic import op

revision = "rehearsal_newer"
down_revision = "$before"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("comment on table alembic_version is 'rehearsal: a newer schema'")


def downgrade() -> None:
    pass
MIGRATION
  fi
  cat > "$dir.yaml" <<OVERRIDE
services:
  api:
    build:
      context: $dir/api
  backup:
    build:
      context: $dir/api
      target: backup
OVERRIDE
}
if broken_release broken-a no; then
  MARKX_COMPOSE_OVERRIDE="$MARKX_COMPOSE_OVERRIDE:$work/broken-a.yaml" "$prod/deploy.sh" deploy rehearsal-3 \
    > "$work/deploy-3.txt" 2>&1 && st=0 || st=$?
  if [[ $st -ne 0 ]] && grep -q "rehearsal-2 is running again, verified" "$work/deploy-3.txt" \
    && [[ "$(release_images_of)" == "$(images_of_release rehearsal-2)" ]] \
    && [[ "$(tail -1 "$config/releases.log" | cut -d' ' -f2-)" == "auto-rollback rehearsal-2" ]] \
    && [[ ! -e "$config/deploy-halted" ]]; then
    pass "a release that fails after its migration: deploy fails and the last working release runs again, every service"
  else
    fail "the automatic return to the last working release (exit $st, $(release_images_of))"; tail -40 "$work/deploy-3.txt"
  fi
  [[ "$(https "$url/api/v1/healthz/ready")" == *'"status":"ready"'* ]] \
    && pass "and the site is ready through the proxy" || fail "site after the automatic return"
  grep -q " deploy rehearsal-3$" "$config/releases.log" && fail "the failed release was recorded as deployed" \
    || pass "the failed release is never recorded as deployed"
else
  fail "making the broken release"
fi

if broken_release broken-b yes; then
  MARKX_COMPOSE_OVERRIDE="$MARKX_COMPOSE_OVERRIDE:$work/broken-b.yaml" "$prod/deploy.sh" deploy rehearsal-4 \
    > "$work/deploy-4.txt" 2>&1 && st=0 || st=$?
  stopped=1
  for s in api worker web; do
    [[ -z "$(compose ps --status running -q "$s")" ]] || stopped=0
  done
  if [[ $st -ne 0 ]] && grep -q "refuses the migrated database" "$work/deploy-4.txt" \
    && grep -q "DEPLOYMENT HALTED in a safe state" "$work/deploy-4.txt" \
    && grep -q "MARKX_ALLOW_NEWER_SCHEMA=true" "$work/deploy-4.txt" \
    && [[ "$(psql_markx "select version_num from alembic_version")" == rehearsal_newer ]] \
    && (( stopped )); then
    pass "when the last working release refuses the migrated database: the API, worker and web app stop, with instructions"
  else
    fail "the safe stop (exit $st, stopped=$stopped)"; tail -40 "$work/deploy-4.txt"
  fi
  [[ -n "$(compose ps --status running -q postgres)" && -n "$(compose ps --status running -q backup)" ]] \
    && pass "in the safe stop the database and the backup service keep running" || fail "postgres or backup stopped"
  grep -qx "failed_release=rehearsal-4" "$config/deploy-halted" 2>/dev/null \
    && [[ "$(stat -c %a "$config/deploy-halted")" == 600 ]] \
    && pass "the safe stop is written down (deploy-halted in the settings folder)" || fail "halt record"
  "$prod/deploy.sh" status > "$work/status-halted.txt" 2>&1 || true
  grep -q "THE LAST DEPLOYMENT HALTED" "$work/status-halted.txt" \
    && pass "deploy.sh status says the deployment halted" || { fail "status after the halt"; cat "$work/status-halted.txt"; }
  # 502 or 504 from the proxy itself: no application answers at all.
  halted_code="$(code "$url/api/v1/healthz/ready")"
  [[ "$halted_code" =~ ^50[234]$ ]] \
    && pass "the site answers $halted_code from the proxy: nothing half-working serves visitors" \
    || fail "site in the safe stop: $halted_code"
  refuse "the last working release still refuses the newer database without the acknowledgement" \
    "$prod/deploy.sh" rollback rehearsal-2
  # The documented way out for a backward-compatible migration (rollback.md).
  echo "MARKX_ALLOW_NEWER_SCHEMA=true" >> "$config/api.env"
  # D-103: the setting alone, as if left on, never decides a rollback.
  "$prod/deploy.sh" rollback rehearsal-2 > "$work/rollback-setting-only.txt" 2>&1 && st=0 || st=$?
  if [[ $st -ne 0 ]] && grep -q "the database is newer than rehearsal-2: nothing was started" "$work/rollback-setting-only.txt" \
    && [[ -e "$config/deploy-halted" ]] && [[ -z "$(compose ps --status running -q api)" ]]; then
    pass "with the setting on but without --accept-newer-schema, rollback still refuses the newer database"
  else
    fail "a rollback decided by the setting alone (exit $st)"; tail -20 "$work/rollback-setting-only.txt"
  fi
  if "$prod/deploy.sh" rollback rehearsal-2 --accept-newer-schema > "$work/rollback-ack.txt" 2>&1 \
    && [[ "$(https "$url/api/v1/healthz/ready")" == *'"schema":"ahead"'* ]] \
    && [[ ! -e "$config/deploy-halted" ]] && [[ "$(release_images_of)" == "$(images_of_release rehearsal-2)" ]]; then
    pass "with MARKX_ALLOW_NEWER_SCHEMA=true the rollback ends the safe stop (schema: ahead)"
  else
    fail "the way out of the safe stop"; tail -30 "$work/rollback-ack.txt"
  fi
else
  fail "making the broken release with a newer migration"
fi

# -- 9b. the setting left on (D-103, the founder's rule) --------------------------------
# Go back to an older release only when it truly accepts the database. The
# compatible rollback above left MARKX_ALLOW_NEWER_SCHEMA=true in api.env and
# the database carries a change rehearsal-2 does not know (rehearsal_newer).

echo "== the setting left on"
running_release_line="$(tail -1 "$config/releases.log" | cut -d' ' -f2-)"
"$prod/deploy.sh" deploy rehearsal-5 > "$work/deploy-5.txt" 2>&1 && st=0 || st=$?
if [[ $st -ne 0 ]] && grep -q "MARKX_ALLOW_NEWER_SCHEMA is on in $config/api.env" "$work/deploy-5.txt" \
  && grep -q "Remove that line from $config/api.env" "$work/deploy-5.txt" \
  && grep -q "Nothing was changed" "$work/deploy-5.txt" \
  && [[ "$(tail -1 "$config/releases.log" | cut -d' ' -f2-)" == "$running_release_line" ]] \
  && [[ "$(release_images_of)" == "$(images_of_release rehearsal-2)" ]]; then
  pass "deploy refuses to start while MARKX_ALLOW_NEWER_SCHEMA is on, saying what to do, and changes nothing"
else
  fail "deploy with the setting left on (exit $st)"; tail -20 "$work/deploy-5.txt"
fi
"$prod/deploy.sh" check > "$work/check-setting.txt" 2>&1 || true
grep -q "WARNING  MARKX_ALLOW_NEWER_SCHEMA is on" "$work/check-setting.txt" \
  && pass "deploy.sh check warns while the setting is on" || { fail "check with the setting on"; tail -10 "$work/check-setting.txt"; }

# The same setting where deploy.sh cannot read it (Compose's own environment
# for the API and the worker, not api.env): the containers see it exactly as
# if api.env held it.
sed -i '/^MARKX_ALLOW_NEWER_SCHEMA=/d' "$config/api.env"
cat > "$work/setting-elsewhere.yaml" <<'OVERRIDE'
services:
  api:
    environment:
      MARKX_ALLOW_NEWER_SCHEMA: "true"
  worker:
    environment:
      MARKX_ALLOW_NEWER_SCHEMA: "true"
OVERRIDE
MARKX_COMPOSE_OVERRIDE="$MARKX_COMPOSE_OVERRIDE:$work/setting-elsewhere.yaml" "$prod/deploy.sh" deploy rehearsal-5 \
  > "$work/deploy-5b.txt" 2>&1 && st=0 || st=$?
if [[ $st -ne 0 ]] && grep -q "deployment: REFUSED: MARKX_ALLOW_NEWER_SCHEMA is on" "$work/deploy-5b.txt" \
  && ! grep -q "the one-time migration step" "$work/deploy-5b.txt" \
  && [[ "$(tail -1 "$config/releases.log" | cut -d' ' -f2-)" == "$running_release_line" ]]; then
  pass "the new release itself refuses a deployment with the setting on, wherever it is set (before any migration)"
else
  fail "the new release's own refusal (exit $st)"; tail -20 "$work/deploy-5b.txt"
fi

# The reviewer's case. A failed update, the database carrying a later change,
# the setting on for every container. The new release here is one made
# before the rule (its own refusal taken out), so the deployment gets as far
# as the automatic return: only the forced-off check stands in the way.
if broken_release broken-c yes; then
  sed -i 's/    if arguments.deploying and config.allow_newer_schema:/    if False:  # rehearsal: a release made before D-103/' \
    "$work/broken-c/api/markx/ops/preflight.py"
  if grep -q "rehearsal: a release made before D-103" "$work/broken-c/api/markx/ops/preflight.py"; then
    MARKX_COMPOSE_OVERRIDE="$MARKX_COMPOSE_OVERRIDE:$work/broken-c.yaml:$work/setting-elsewhere.yaml" \
      "$prod/deploy.sh" deploy rehearsal-6 > "$work/deploy-6.txt" 2>&1 && st=0 || st=$?
    stopped=1
    for s in api worker web; do
      [[ -z "$(compose ps --status running -q "$s")" ]] || stopped=0
    done
    if [[ $st -ne 0 ]] && grep -q "checked with MARKX_ALLOW_NEWER_SCHEMA forced off" "$work/deploy-6.txt" \
      && grep -q "rehearsal-2 refuses the migrated database" "$work/deploy-6.txt" \
      && grep -q "DEPLOYMENT HALTED in a safe state" "$work/deploy-6.txt" \
      && ! grep -q "running again, verified" "$work/deploy-6.txt" \
      && [[ "$(tail -1 "$config/releases.log" | cut -d' ' -f2-)" == "$running_release_line" ]] \
      && [[ "$(psql_markx "select version_num from alembic_version")" == rehearsal_newer ]] \
      && (( stopped )); then
      pass "the reviewer's case: a newer database and the setting on; the automatic return checks rehearsal-2 with it forced off, refuses, and stops safely"
    else
      fail "the automatic return with the setting left on (exit $st, stopped=$stopped)"; tail -40 "$work/deploy-6.txt"
    fi
    [[ "$(image_of backup)" == "$prefix/backup:rehearsal-6" ]] \
      && pass "in the safe stop the backup service runs as the release that migrated the database" \
      || fail "backup service in the safe stop: $(image_of backup)"
  else
    fail "making the release without the deploy-time refusal"
  fi
else
  fail "making the broken release for the reviewer's case"
fi

# The way out the runbook prefers: roll forward. The run ends with the
# setting off everywhere and the schema current.
if broken_release fixed yes healthy; then
  if MARKX_COMPOSE_OVERRIDE="$MARKX_COMPOSE_OVERRIDE:$work/fixed.yaml" "$prod/deploy.sh" deploy rehearsal-7 \
    > "$work/deploy-7.txt" 2>&1 \
    && [[ "$(https "$url/api/v1/healthz/ready")" == *'"schema":"current"'* ]] \
    && [[ "$(release_images_of)" == "$(images_of_release rehearsal-7)" ]] \
    && [[ ! -e "$config/deploy-halted" ]]; then
    pass "a roll forward ends the safe stop (schema: current)"
  else
    fail "the roll forward"; tail -30 "$work/deploy-7.txt"
  fi
else
  fail "making the fixed release"
fi
if ! grep -q "MARKX_ALLOW_NEWER_SCHEMA" "$config/api.env" \
  && [[ "$(compose exec -T api printenv MARKX_ALLOW_NEWER_SCHEMA 2>/dev/null)" == "" ]] \
  && [[ "$(compose exec -T worker printenv MARKX_ALLOW_NEWER_SCHEMA 2>/dev/null)" == "" ]]; then
  pass "the rehearsal ends with MARKX_ALLOW_NEWER_SCHEMA off: not in api.env, not in the running API or worker"
else
  fail "MARKX_ALLOW_NEWER_SCHEMA is still on at the end"
fi

# -- 10. shutdown ------------------------------------------------------------------

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
