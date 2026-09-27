# MedMap

A data-driven hospital planning tool that identifies **where new hospitals could have the greatest impact** and **what kind of hospital should be built there**.

Instead of ranking locations by population alone, the project combines:

- existing hospital access and capacity
- estimated drive-time accessibility
- underserved and vulnerable populations
- hospital size / bed configuration
- department and service needs
- configurable optimization weights

The result is an interactive map where users can explore candidate hospital locations, compare tradeoffs, and inspect recommended hospital configurations and services.

## Why it is useful

The pipeline is designed around a simple question:

> **If we could build a hospital here, how much would it improve access to care?**

The system precomputes nationwide analytical features, then serves them through **DuckDB + FastAPI** so the frontend can re-rank and filter candidates interactively without rerunning the ETL.

Highlights:

- Nationwide tract-level analysis
- Fast approximate drive-time/access modeling
- Existing hospital and bed-capacity analysis
- Recommended hospital size and configuration
- Department/service recommendations
- Geographic filtering and zoom-aware candidate discovery
- Interactive weighting of access, capacity, vulnerability, cost, drive access, and service fit
- Final API returns frontend-ready GeoJSON for MapLibre

## Stack

**Data / ETL:** Python, Pandas, NumPy, SciPy, GeoPandas, Parquet  
**Analytics:** DuckDB  
**Backend:** FastAPI  
**Frontend:** React + MapLibre GL JS

---

## Run the project

Run these commands from the repository root.

### 1. Start the backend

```powershell
python -m pip install -r src/optimal_hospital_placer/api/requirements.txt

python -m uvicorn optimal_hospital_placer.api.main:app `
  --app-dir src `
  --host 127.0.0.1 `
  --port 8080
```

API documentation:

```text
http://127.0.0.1:8080/docs
```

### 2. Start the frontend

From the web/frontend directory:

```powershell
npm install
npm run dev
```

Open the local URL printed by Vite, normally:

```text
http://localhost:5173
```

The frontend should proxy `/api` requests to:

```text
http://127.0.0.1:8080
```

Example Vite proxy configuration:

```js
server: {
  proxy: {
    "/api": "http://127.0.0.1:8080"
  }
}
```

---

## Optional: public judge URL with Cloudflare Tunnel

If `cloudflared` is installed, keep both the FastAPI backend and frontend running, then expose the frontend:

```powershell
cloudflared tunnel --url http://localhost:5173
```

Cloudflare will print a temporary public HTTPS URL.

Because the frontend uses relative `/api/...` requests and Vite proxies `/api` to FastAPI on port `8080`, the same public URL can serve both the UI and backend requests.

In other words:

```text
Judge
  ↓
Cloudflare public URL
  ↓
Vite frontend :5173
  ├── frontend assets
  └── /api/* → FastAPI :8080
```

The computer hosting the demo must remain powered on and connected to the internet.

---

## Data pipeline

The analytical pipeline is staged so expensive data preparation happens before the demo:

```text
Raw public data
    ↓
Geospatial + demographic enrichment
    ↓
Access / capacity modeling
    ↓
Candidate screening
    ↓
Hospital configuration optimization
    ↓
Service + travel refinement
    ↓
Stage 8 Parquet
    ↓
DuckDB + FastAPI
    ↓
Interactive MapLibre frontend
```

The live application does **not** rerun the ETL. It queries the final precomputed Stage 8 dataset, making interactive filtering and re-ranking fast enough for a live demo.
