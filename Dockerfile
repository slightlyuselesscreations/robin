FROM --platform=$BUILDPLATFORM node:24-alpine AS frontend
WORKDIR /build
RUN corepack enable pnpm
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build


FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    ROBIN_DATA_DIR=/data \
    ROBIN_STATIC_DIR=/app/static \
    PYTHONUNBUFFERED=1

COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.18,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --no-install-project

COPY backend/robin ./robin
COPY --from=frontend /build/dist ./static

RUN useradd --uid 1000 --user-group --no-create-home --shell /usr/sbin/nologin robin \
    && mkdir -p /data && chown robin:robin /data
USER robin
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health').read()"

CMD ["uvicorn", "robin.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-proxy-headers", \
     "--no-access-log"]
