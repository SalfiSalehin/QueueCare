# Build context is the repository root so the backend can import the ml/ package.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# libgomp is required by LightGBM
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install -r /app/backend/requirements.txt

COPY backend /app/backend
COPY ml /app/ml

# Non-root runtime user
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

WORKDIR /app/backend
ENV PYTHONPATH=/app/backend:/app

EXPOSE 8000

# ---- production: no reload, no dev mounts. ONE worker per container on purpose: the outbox relay and the
# notification worker run inside each process; scale by running more containers, not --workers (see docs/deployment.md).
FROM base AS prod
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--timeout-graceful-shutdown", "20"]

# ---- development (kept LAST so a plain `docker compose build` still produces the dev image)
FROM base AS dev
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
