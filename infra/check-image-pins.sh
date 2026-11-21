#!/usr/bin/env bash
# Every container image MarkX pulls is named by its exact content, not only
# by a tag (D-103; audit of 19 November 2026, section 13: "tags not
# digests"). A tag can be pushed again with different content; a digest
# cannot. Images MarkX builds itself (PREFIX/api, markx-api:local, ...) are
# not pulled and are not checked.
#
#   infra/check-image-pins.sh        exit 0 when every pulled image is pinned
#
# Run by CI (the containers job). To bump an image: change the tag AND the
# digest together, from `docker buildx imagetools inspect IMAGE:TAG` (the
# digest of the multi-platform index, so every server architecture works).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

files=(
  infra/production/compose.yaml
  infra/production/rehearsal/*.yaml
  infra/compose/*.yaml
  apps/api/Dockerfile
  apps/web/Dockerfile
  .github/workflows/*.yml
)
pinned='@sha256:[0-9a-f]{64}'
bad=0

# 1. Every `image:` line names a pinned image, or one MarkX builds.
while IFS= read -r line; do
  file="${line%%:*}"; rest="${line#*:}"; number="${rest%%:*}"; value="${rest#*:}"
  value="$(sed -E 's/^[[:space:]]*image:[[:space:]]*//; s/[[:space:]]+#.*$//; s/^"//; s/"$//' <<<"$value")"
  case "$value" in
    *'${MARKX_IMAGE_PREFIX'*|markx-*:*) continue ;;  # built by MarkX
  esac
  if ! grep -qE "$pinned\$" <<<"$value"; then
    echo "NOT PINNED  $file:$number  image: $value"; bad=1
  fi
done < <(grep -nE '^[[:space:]]*image:' "${files[@]}" /dev/null || true)

# 2. Every base image of a Dockerfile (ARG ..._IMAGE=...) is pinned.
while IFS= read -r line; do
  if ! grep -qE "$pinned\$" <<<"$line"; then echo "NOT PINNED  $line"; bad=1; fi
done < <(grep -nHE '^ARG [A-Z_]*IMAGE=' apps/api/Dockerfile apps/web/Dockerfile || true)

# 3. Every other mention of an outside image MarkX uses (a `docker run` in a
#    workflow or a script) carries its digest.
upstream='(postgres|python|node|nginxinc/nginx-unprivileged|bitnamilegacy/minio):[0-9][A-Za-z0-9._-]*'
while IFS= read -r line; do
  echo "NOT PINNED  $line"; bad=1
done < <(grep -nHoE "(^|[[:space:]=\"])$upstream(@sha256:[0-9a-f]{64})?" "${files[@]}" infra/production/rehearsal/*.sh \
           | grep -vE "$pinned\$" || true)

if (( bad )); then
  echo "check-image-pins: FAILED (pin each image above to its digest)"; exit 1
fi
echo "check-image-pins: every pulled image is pinned to its digest"
