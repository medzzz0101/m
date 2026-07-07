# ---------------------------------------------------------------------------
# LATTICE — production container.
# Builds a small image that serves the FastAPI app + the web console.
# Works on any host that runs Docker and injects a $PORT (Render, Railway,
# Fly.io, Google Cloud Run, Azure, a plain VPS, …). No tunnel needed: this is
# a real, publicly-hostable web service.
# ---------------------------------------------------------------------------
FROM python:3.11-slim

# System libs Pillow / cryptography need at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so Docker caches them across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code.
COPY app ./app
COPY web ./web
COPY README.md .

# Writable runtime dirs (cache, uploads, invoices).
RUN mkdir -p data/cache data/uploads data/invoices

# The platform provides $PORT; default to 8000 for local `docker run`.
ENV PORT=8000
EXPOSE 8000

# Shell form so $PORT expands at runtime.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
