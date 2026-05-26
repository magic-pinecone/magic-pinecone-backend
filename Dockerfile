FROM ghcr.io/astral-sh/uv:python3.14-alpine AS builder

ENV UV_COMPILE_BYTECODE=1

WORKDIR /app

# psycopg2 builds from source on Alpine, so it needs a compiler and pg_config.
RUN apk add --no-cache build-base postgresql-dev

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-install-project --no-dev

COPY . .

FROM python:3.14-alpine

WORKDIR /app

RUN apk add --no-cache libpq

COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
