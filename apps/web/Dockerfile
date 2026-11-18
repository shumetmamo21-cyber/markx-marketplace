# The MarkX web app's production image (blueprint F.13; D-091).
# Nothing here is deployed; there is no registry and no cloud resource.
#
#   docker build -t markx-web \
#     --build-arg MARKX_MEDIA_ORIGIN=https://media.example.invalid apps/web
#
# Three stages: the locked dependencies, the build (Next.js "standalone"
# output: the server and only the files it uses), and a small runtime that
# holds no development tool, no source and no secret, and runs as the
# unprivileged `node` user.
#
# Decided at BUILD time, because Next.js writes next.config.ts into the
# build: MARKX_MEDIA_ORIGIN (the picture CDN in the security policy, F.6)
# and MARKX_API_ORIGIN (only the laptop rewrite uses it; in production the
# reverse proxy sends /api to the API). Neither is a secret. Read at RUN
# time: MARKX_API_ORIGIN for server pages, MARKX_TURNSTILE_SITE_KEY (public),
# MARKX_ENV, MARKX_PUBLIC_ORIGIN and MARKX_MEDIA_ORIGIN for the start-up
# check (deploy/check-env.mjs), which refuses a staging or production
# container without them.

# Pinned to the Node.js release CI uses (22); bump deliberately, with CI.
ARG NODE_IMAGE=node:22.23.5-bookworm-slim

FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# build_ca: an optional extra certificate authority, only for a builder behind
# a TLS-inspecting proxy (docker build --secret id=build_ca,src=ca.crt). It is
# mounted for this one step and never written into any layer of the image.
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi \
    && npm ci --no-audit --no-fund

FROM ${NODE_IMAGE} AS build
WORKDIR /app
ARG MARKX_MEDIA_ORIGIN=""
ARG MARKX_API_ORIGIN=http://api:8000
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    MARKX_NEXT_OUTPUT=standalone \
    MARKX_MEDIA_ORIGIN=${MARKX_MEDIA_ORIGIN} \
    MARKX_API_ORIGIN=${MARKX_API_ORIGIN}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build \
    && test -f .next/standalone/server.js

FROM ${NODE_IMAGE} AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
# Root-owned and read-only to the server; only Next's cache folder is its own.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY deploy/check-env.mjs deploy/start.mjs ./deploy/
RUN mkdir -p .next/cache && chown node:node .next/cache
USER node
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=6 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/healthz').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]
CMD ["node", "deploy/start.mjs"]
