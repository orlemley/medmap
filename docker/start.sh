#!/bin/sh
set -e

# Legacy convenience entrypoint. The production image uses the equivalent CMD
# in Dockerfile and serves the compiled Vite app from FastAPI.
exec python -m uvicorn optimal_hospital_placer.api.main:app \
  --app-dir /app/src \
  --host "${HOST:-0.0.0.0}" \
  --port "${PORT:-8000}"
