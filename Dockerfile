FROM python:3.11-slim

# System dependencies — the placement scoring engine is a small Linux binary
# we install at build time. For now we stage the directory so a real binary
# can be dropped in via a multi-stage build.
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY data/ ./data/
# .env is intentionally NOT copied in. Inject runtime config via
# `docker run --env-file .env` or compose's `env_file:` / `environment:`
# so secrets never get baked into the image layer.

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
