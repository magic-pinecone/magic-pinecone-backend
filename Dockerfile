# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:python3.14-alpine AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# psycopg2 builds from source on Alpine, so it needs a compiler and pg_config.
RUN --mount=type=cache,target=/var/cache/apk \
    apk add build-base postgresql-dev

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY . .

FROM python:3.14-alpine

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apk \
    apk add libpq

COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
