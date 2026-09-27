# MedMap: the whole demo (React site + Python API) in one image.
#
# Build from the repo root (the build context must include web/):
#   python docker/prepare_runtime_data.py
#   docker build -f docker/Dockerfile -t medmap .
#   docker run --rm -p 8000:8000 medmap  -> http://localhost:8000
# Or use docker/docker-compose.yml (see README "Running with Docker").
#
# The React site is built in stage 1. The selected unmodified Stage 5/7/8
# snapshots are prepared separately and embedded at /app/data.

# ---- Stage 1: build the React site -----------------------------------------
FROM node:24-slim AS web-build
WORKDIR /web

# Dependencies first, so editing src/ doesn't re-run npm ci.
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY web/index.html web/vite.config.js ./
COPY web/public ./public
COPY web/src ./src
RUN npm run build

# ---- Stage 2: FastAPI + DuckDB over the processed snapshots -----------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    MEDMAP_IN_DOCKER=1

WORKDIR /app
RUN useradd --create-home --uid 10001 medmap

# Keep the repository layout so the API finds /app/data and /app/web/dist.
COPY src/optimal_hospital_placer/api/requirements.txt /tmp/api-requirements.txt
RUN pip install --no-cache-dir -r /tmp/api-requirements.txt
COPY src ./src
COPY --from=web-build /web/dist web/dist
COPY --chown=10001:10001 docker/runtime-data/ /app/data/
RUN test -f /app/data/stage5/latest_success.json \
    && test -f /app/data/stage7/latest_success.json \
    && test -f /app/data/stage8/latest_success.json

USER 10001
EXPOSE 8000

# python:slim has no curl, so check health with Python itself.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/v1/health' % os.environ.get('PORT', '8000'), timeout=4)"]

CMD ["sh", "-c", "python -m uvicorn optimal_hospital_placer.api.main:app --app-dir src --host ${HOST} --port ${PORT}"]
