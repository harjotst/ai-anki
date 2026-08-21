# Python is pinned to 3.12 deliberately: the dependency set is resolved against
# it, and a base image that drifts to 3.13 on rebuild is a deploy that fails for
# reasons nothing in this repository changed.
FROM node:22-slim AS frontend

WORKDIR /build
# The frontend is optional while it is being built out. Copying the manifest
# first keeps the install layer cached against source churn.
COPY frontend/package*.json ./frontend/
RUN if [ -f frontend/package.json ]; then cd frontend && npm ci --no-audit --no-fund; fi
COPY frontend/ ./frontend/
RUN if [ -f frontend/package.json ]; then cd frontend && npm run build; else mkdir -p frontend/dist; fi


FROM python:3.12-slim-bookworm

# Debian bookworm carries glibc 2.36, which matters: the dev-only `anki` wheels
# are manylinux_2_35 and will not install on anything older. Nothing in the
# runtime image needs them, but the same base is used for CI.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    AI_ANKI_DB_PATH=/data/ai-anki.db \
    AI_ANKI_DATA_DIR=/data/uploads \
    # Starlette spools large uploads to a temp file. Left on the default, that
    # is the slow ephemeral rootfs; on the volume it is the same disk the
    # database already lives on.
    TMPDIR=/data/tmp

# LibreOffice for document and presentation conversion, plus fonts. Without the
# font packages, a deck using anything the container lacks is silently
# substituted and the output is mangled rather than failed.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        libreoffice-impress \
        fonts-liberation \
        fonts-dejavu-core \
        fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN python -m pip install --upgrade pip && python -m pip install .

COPY app/ ./app/
COPY --from=frontend /build/frontend/dist ./frontend/dist

RUN mkdir -p /data/uploads /data/tmp

EXPOSE 8080

# Exec form, so uvicorn is PID 1 and receives SIGTERM directly. Under a shell
# wrapper the shell is PID 1, SIGTERM never reaches the application, and the
# graceful drain simply does not run before the platform's SIGKILL arrives.
#
# The graceful-shutdown timeout sits under fly.toml's kill_timeout of 300s, so
# the drain is bounded by our own deadline rather than by the kill.
CMD ["uvicorn", "app.asgi:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--timeout-graceful-shutdown", "240"]
