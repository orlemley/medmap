# Deploying MedMap

MedMap is now one deployable application: FastAPI serves `/api/v1/*` and, after
a frontend build, serves the Vite app and its client-side routes as well.

## Required data

The API reads the processed Stage 5, Stage 7, and Stage 8 outputs under `data/`.
Set `OHP_PROJECT_ROOT` to the repository root when the working directory is
different. In a container or hosted service, mount or copy `data/` at that root.

## Local development

Run the API and Vite development server in separate terminals:

```powershell
python -m uvicorn optimal_hospital_placer.api.main:app --app-dir src --reload --port 8000
cd web
npm install
npm run dev
```

Vite proxies `/api` to port 8000. Open `http://localhost:5173`.

## Production-style local run

```powershell
cd web
npm ci
npm run build
cd ..
python -m uvicorn optimal_hospital_placer.api.main:app --app-dir src --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`. The health check is `/api/v1/health`.

## Docker

From the repository root:

```powershell
docker compose -f docker/docker-compose.yml up --build
```

The multi-stage image builds the Vite bundle, installs the API dependencies,
and runs one Uvicorn process. This is the simplest hackathon deployment target
for Render, Railway, Fly.io, Azure Container Apps, or any service accepting a
Dockerfile. Persisted processed data must be available in the image or mounted
at `/app/data`.

## Split hosting

The frontend can also be hosted as static files. Build it with the public API
origin configured:

```powershell
$env:VITE_API_BASE = "https://api.example.org"
cd web
npm ci
npm run build
```

Publish `web/dist/` and route all non-file paths to `index.html`. Deploy FastAPI
separately and point `OHP_PROJECT_ROOT` at its data-bearing application root.
The API currently permits cross-origin browser calls; restrict its CORS origins
to the final frontend domain before a long-lived production deployment.

## Deployment smoke test

Verify these URLs after deployment:

- `/api/v1/health`
- `/api/v1/states`
- `/api/v1/services`
- `/map` (refresh this route directly to confirm SPA fallback)

Then choose a state, change a scoring weight, select a candidate, and confirm
that its access bands, recommended services, and alternate configurations load.
