# Final Optimal Hospital Placer API

This is the final API layer over the Stage 8 analytical snapshot.

## Design

- **Stage 8 is the final analytical source of truth.**
- DuckDB queries Parquet directly.
- FastAPI never reruns ETL, routing, or rewrites Parquet for an API request.
- `/api/v1/...` is the stable API.
- Legacy `/api/...` endpoints preserve useful compatibility with the supplied React/MapLibre web package.

## Install

From the repository root:

```powershell
python -m pip install -r src/optimal_hospital_placer/api/requirements.txt
```

## Run

From the repository root:

```powershell
python -m uvicorn optimal_hospital_placer.api.main:app `
  --app-dir src `
  --reload `
  --host 127.0.0.1 `
  --port 8080
```

Alternative if you already set `PYTHONPATH=src`:

```powershell
python -m uvicorn optimal_hospital_placer.api.main:app --reload --port 8080
```

Docs:

- `http://127.0.0.1:8080/docs`
- `http://127.0.0.1:8080/redoc`

## Required data

Stage 8 must have completed:

`data/stage8/latest_success.json`

The API expects:

- `final_candidates.parquet`
- `service_recommendations.parquet`
- `travel_access_summary.parquet`

Stage 7 is optional but enables alternate hospital configurations.

Stage 5 is optional but enables existing-hospital and population/heatmap endpoints.

## Core endpoints

### System

- `GET /api/v1/health`
- `GET /api/v1/meta`
- `GET /api/v1/summary`
- `GET /api/v1/states`
- `GET /api/v1/services`

### Map

- `GET /api/v1/map/candidates`
- `GET /api/v1/map/hospitals`
- `GET /api/v1/map/population`

Example:

```text
/api/v1/map/candidates?bbox=-94,37,-90,40&zoom=7&limit=150
```

Candidate map responses are GeoJSON. At low zoom, results are spatially diversified so the national map does not become a pile of nearly identical neighboring candidates. As the viewport narrows/zoom increases, more local alternatives can be returned.

Useful candidate filters:

```text
state=MO
service=emergency
service=icu
require_all_services=true
min_beds=50
max_beds=200
min_score=0.55
routing_refined=false
```

### Candidate detail

- `GET /api/v1/candidates/{site_id}`
- `GET /api/v1/candidates/{site_id}/services`
- `GET /api/v1/candidates/{site_id}/access`
- `GET /api/v1/candidates/{site_id}/configurations`

The full detail endpoint includes services, 15/30/45/60-minute access bands, and Stage 7 alternate configurations when available.

### Interactive optimization

`POST /api/v1/optimize`

Example body:

```json
{
  "weights": {
    "access": 0.22,
    "capacity": 0.18,
    "vulnerability": 0.12,
    "configuration_fit": 0.12,
    "cost_efficiency": 0.08,
    "drive_access": 0.16,
    "service_fit": 0.12
  },
  "state": "MO",
  "limit": 100,
  "services": ["emergency", "icu"],
  "require_all_services": false,
  "diversify": true
}
```

Weights are normalized server-side. Re-ranking is a DuckDB query over persisted component scores; it does not rerun Stage 6/7/8.

## Compatibility with the supplied frontend

The following old routes are included:

- `GET /api/health`
- `GET /api/states`
- `GET /api/hospitals`
- `GET /api/population`
- `GET /api/optimize`

The existing frontend's old weights are mapped approximately:

- `population` -> new-access/access component
- `distance` -> Stage 8 drive-access component
- `shortage` -> capacity + vulnerability
- `cost` -> cost-efficiency

The old `radius` query parameter is accepted so the current UI keeps working, but Stage 8 no longer treats it as the true optimization radius. The final analytical model is based on the 15/30/45/60-minute access fields.

For the final frontend, migrate to `/api/v1/...` and change the old "coverage radius" control into a drive-time/access-threshold control or service/access filters.

## Vite development proxy

Point `/api` at port 8080:

```js
// vite.config.js
export default defineConfig({
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8080"
    }
  }
})
```

## Recommended frontend behavior

National view:
- request `/api/v1/map/candidates?zoom=4&limit=40`
- show a small spatially diverse set.

State/large-region view:
- send the current `bbox` and zoom.
- request roughly 75–175 candidates.

Local view:
- send the tighter `bbox`.
- allow 200–500 candidates if useful.

On click:
- fetch `/api/v1/candidates/{site_id}`.
- show recommended configuration, component scores, departments/services, travel/access bands, and routing-model provenance.

Do not download the whole Parquet dataset into the browser.
