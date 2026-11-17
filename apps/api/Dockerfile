# The MarkX API and worker image, for a laptop (blueprint P1; D-058).
# One image, two commands: the API (default) and `python -m markx.worker`.
# Nothing here is deployed; there is no registry and no cloud resource.
#
#   docker build -t markx-api apps/api
#
# Dependencies come from uv.lock exactly (`--locked`); the image runs as an
# unprivileged user and holds no secret: configuration arrives through
# MARKX_* environment variables at run time.

# The base image can be swapped for a mirror of the same image when Docker
# Hub limits pulls, e.g. --build-arg PYTHON_IMAGE=mirror.gcr.io/library/python:3.13-slim-bookworm
ARG PYTHON_IMAGE=python:3.13-slim-bookworm

FROM ${PYTHON_IMAGE} AS build
# uv, pinned, from PyPI (the same version the repository is developed with).
RUN pip install --no-cache-dir --root-user-action=ignore uv==0.11.32
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
# Dependencies first, so a code change does not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY alembic.ini ./
COPY migrations ./migrations
COPY markx ./markx
COPY scripts ./scripts
COPY search_eval ./search_eval
RUN uv sync --locked --no-dev

FROM ${PYTHON_IMAGE}
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
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/healthz', timeout=2).status == 200 else 1)"]
CMD ["uvicorn", "markx.main:app", "--host", "0.0.0.0", "--port", "8000"]
