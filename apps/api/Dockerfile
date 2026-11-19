# The MarkX API and worker image (blueprint P1, F.13; D-058, D-091): the same
# image runs on a laptop (infra/compose) and in the production Compose file
# (infra/production).
# One image, two commands: the API (default) and `python -m markx.worker`.
# Nothing here is deployed; there is no registry and no cloud resource.
#
#   docker build -t markx-api apps/api
#
# Dependencies come from uv.lock exactly (`--locked`); the image runs as an
# unprivileged user and holds no secret: configuration arrives through
# MARKX_* environment variables at run time.

# The base image can be swapped for a mirror of the same image when Docker
# Hub limits pulls, e.g. --build-arg PYTHON_IMAGE=mirror.gcr.io/library/python:3.13.18-slim-bookworm
# Pinned to a patch release (D-091) so a rebuild of an old release gets the
# same interpreter; bump it deliberately, with CI.
ARG PYTHON_IMAGE=python:3.13.18-slim-bookworm
# The PostgreSQL client tools of the backup image (D-094) come from the same
# PostgreSQL release the production Compose file runs (17.12), in its Debian
# bookworm variant: the Python image is bookworm, and the tools must find the
# C library they were built against (the default tag is now trixie).
ARG POSTGRES_IMAGE=postgres:17.12-bookworm

FROM ${PYTHON_IMAGE} AS build
# uv, pinned, from PyPI (the same version the repository is developed with).
# build_ca: an optional extra certificate authority, only for a builder behind
# a TLS-inspecting proxy (docker build --secret id=build_ca,src=ca.crt); it is
# mounted for the download steps and never written into the image (D-091).
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi \
    && pip install --no-cache-dir --root-user-action=ignore uv==0.11.32
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
# Dependencies first, so a code change does not reinstall them.
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi \
    && uv sync --locked --no-dev --no-install-project
COPY alembic.ini ./
COPY migrations ./migrations
COPY markx ./markx
COPY scripts ./scripts
COPY search_eval ./search_eval
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi \
    && uv sync --locked --no-dev

FROM ${POSTGRES_IMAGE} AS pgclient
# pg_dump, pg_restore and psql with the libraries they need that a slim
# Python image lacks; the C library and the loader stay the system's own.
RUN set -eu; \
    mkdir -p /pgclient/bin /pgclient/lib; \
    for tool in pg_dump pg_restore psql; do cp "/usr/lib/postgresql/17/bin/$tool" /pgclient/bin/; done; \
    ldd /pgclient/bin/* | awk '$2 == "=>" && $3 ~ /^\// {print $3}' | sort -u \
      | grep -v -E '/(libc|libm|libdl|libpthread|librt|ld-linux[^/]*)\.so' \
      | while read -r lib; do cp -L "$lib" /pgclient/lib/; done

FROM ${PYTHON_IMAGE} AS app
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MARKX_STORAGE_DIR=/var/lib/markx/storage
RUN groupadd --system markx \
    && useradd --system --gid markx --home-dir /app --no-create-home markx \
    && mkdir -p /var/lib/markx/storage \
    && chown markx:markx /var/lib/markx/storage
COPY --from=build /opt/venv /opt/venv
COPY --from=build --chown=root:root /app /app
WORKDIR /app
USER markx

# The backup service (D-094): the same application, plus PostgreSQL 17's
# client tools. `docker build --target backup -t markx-backup apps/api`.
# It holds no key or credential: those arrive at run time (docs/DEPLOYMENT.md).
FROM app AS backup
COPY --from=pgclient /pgclient /opt/pgclient
USER root
RUN set -eu; \
    for tool in pg_dump pg_restore psql; do \
      printf '#!/bin/sh\nLD_LIBRARY_PATH=/opt/pgclient/lib exec /opt/pgclient/bin/%s "$@"\n' "$tool" \
        > "/usr/local/bin/$tool"; \
      chmod 755 "/usr/local/bin/$tool"; \
    done; \
    pg_dump --version && pg_restore --version && psql --version \
    && mkdir -p /backups && chown markx:markx /backups && chmod 700 /backups
USER markx
HEALTHCHECK --interval=5m --timeout=30s --start-period=30m --retries=2 \
    CMD ["python", "-m", "markx.backup", "check"]
CMD ["python", "-m", "markx.backup", "serve"]

# The API and worker image: the last stage, so a plain `docker build` makes it.
FROM app AS runtime
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/healthz', timeout=2).status == 200 else 1)"]
# --no-proxy-headers: the app reads X-Forwarded-For itself, from the proxies
# in MARKX_TRUSTED_PROXIES only (SEC-3, D-084); uvicorn's own copy would trust
# whatever FORWARDED_ALLOW_IPS says, including "*".
# --timeout-graceful-shutdown: on SIGTERM, requests in flight get 20 seconds
# to finish before the process exits (the production Compose file allows 30).
# --no-server-header: responses do not advertise the server software (D-091).
CMD ["uvicorn", "markx.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-server-header", "--timeout-graceful-shutdown", "20"]
