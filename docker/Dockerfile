# MedMap: the whole demo (React site + Python API) in one image.
#
# Build from the repo root (the build context must include web/):
#   docker build -f docker/Dockerfile -t medmap .
#   docker run --rm -p 8000:8000 medmap          -> http://localhost:8000
# Or use docker/docker-compose.yml (see README "Running with Docker").
#
# Needs nothing from the host at runtime: the React site is built in stage 1,
# and the data comes from web/api/medmap_data.json.gz (no raw/ folder needed).

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

# ---- Stage 2: the Python server (standard library only) --------------------
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    MEDMAP_IN_DOCKER=1

WORKDIR /app
RUN useradd --create-home --uid 10001 medmap

# Same layout as the repo, so server.py finds web/dist next to web/api.
COPY web/api/*.py web/api/
COPY web/api/medmap_data.json.gz web/api/
COPY --from=web-build /web/dist web/dist

USER 10001
EXPOSE 8000

# python:slim has no curl, so check health with Python itself.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT', '8000'), timeout=4)"]

CMD ["python", "web/api/server.py"]
