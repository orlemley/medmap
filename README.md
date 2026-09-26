# MedMap

A hospital-placement recommendation tool built for **TigerHacks26**.

MedMap suggests where a new hospital should be built so that it cuts driving
distance for the people farthest from care and takes pressure off existing
hospitals. It combines census population, HRSA shortage-area designations
(MUA/P and HPSA), and the locations of every hospital CMS tracks, and shows the
results on an interactive map where you set how much each factor matters.

> **Status:** the map, the pages and the API are working. The **placement
> algorithm is still a placeholder** (see [Scoring](#scoring-placeholder)).
> The real algorithm is planned for `/algorithm` (see `algorithm_prompt.txt`).

---

## Contents

- [Quick start](#quick-start)
- [Sharing the demo with other people](#sharing-the-demo-with-other-people)
- [Running with Docker](#running-with-docker)
- [Updating the data](#updating-the-data)
- [What's in `web/`](#whats-in-web)
- [Working on the frontend](#working-on-the-frontend)
- [Using the map](#using-the-map)
- [API reference](#api-reference)
- [Scoring (placeholder)](#scoring-placeholder)
- [What the data files contain](#what-the-data-files-contain)
- [Data assumptions](#data-assumptions)
- [Known limitations](#known-limitations)
- [Plugging in the real algorithm](#plugging-in-the-real-algorithm)
- [Troubleshooting](#troubleshooting)

---

## Quick start

Everything needed to run the demo is in the repo: the built React site
(`web/dist/`) and a 1.6 MB data file (`web/api/medmap_data.json.gz`). **No data
download and no Node.js needed.** Pick one:

**A. With Python** (3.8 or newer; nothing to `pip install`)

- Windows: double-click **`web/start.cmd`**. It starts the server and opens
  the site in your browser.
- Any OS, from the repo root:

  ```bash
  python web/api/server.py --open      # use python3 on macOS/Linux if needed
  ```

**B. With Docker** (no Python or Node needed; see [Running with Docker](#running-with-docker))

```bash
docker compose -f docker/docker-compose.yml up --build
```

Either way the site is at **<http://localhost:8000/>** (the same as
`http://127.0.0.1:8000/`), and the map is at `/map`. It starts in a few
seconds. The browser needs internet access for the map tiles.

> **Don't open the HTML files directly** (double-clicking them, or
> `start chrome ./index.html`). Browsers won't run the app from a `file://`
> page, and the map needs the server for its data. If you do, the page tells
> you what to run instead.

Server options:

| Flag | Default | Meaning |
|---|---|---|
| `--host` | `$HOST` or `127.0.0.1` | `127.0.0.1` = only this computer. `0.0.0.0` = other devices on the network can connect too. |
| `--port` | `$PORT` or `8000` | Port for both the API and the site |
| `--open` | off | Open the site in the default browser once the server is ready |
| `--raw PATH` | off | Load the raw CSVs from `PATH` instead of the data file (see [Updating the data](#updating-the-data)) |

Environment variables: `MEDMAP_CACHE_SIZE` (default 16) caps how many radius
and state score tables are kept in memory. Each nationwide table is about
40 MB, and the base server uses about 95 MB. `OPTIMIZER_URL` sends scoring to
another service (see [Plugging in the real algorithm](#plugging-in-the-real-algorithm)).

---

## Sharing the demo with other people

**`127.0.0.1` (and `localhost`) always means "this same device."** If a
teammate types `http://127.0.0.1:8000` on their laptop, it looks for a server
on *their* laptop, not yours. There are three ways to let other people use
MedMap:

| Option | Who it's for | What they need | Your laptop must stay on? |
|---|---|---|---|
| **1. Same Wi-Fi**: they open your laptop's address | Teammates and judges in the room | Just a browser | Yes |
| **2. They run it themselves**: Python or Docker | Teammates, judges who want to run it | Python or Docker | No |
| **3. Temporary public link**: a free tunnel | Anyone, on any network | Just a browser | Yes |

### 1. Same Wi-Fi

On your laptop, double-click **`web/share.cmd`** (or run
`python web/api/server.py --host 0.0.0.0`). It prints something like:

```
MedMap running at http://127.0.0.1:8000/  (Ctrl+C to stop)
  Other devices on the same network: http://192.168.1.23:8000/
```

Give people the second address. If Windows asks, **allow Python through the
firewall**. Tick *Public networks* too if the venue Wi-Fi is marked public.
The Docker setup works the same way: its `8000:8000` port mapping is
reachable at `http://<your IP>:8000` too.

This won't work on networks that block device-to-device traffic, which many
venue, hotel and campus Wi-Fi networks do. In that case, use option 3.

### 2. They run it themselves

Teammates clone the repo and use the [Quick start](#quick-start): Python
(`web/start.cmd`) or [Docker](#running-with-docker). Nobody needs `raw/` or
Node.js.

### 3. Temporary public link (free, no account)

Install Cloudflare's tunnel tool once
(`winget install --id Cloudflare.cloudflared`), start MedMap (Python or
Docker), then run:

```bash
cloudflared tunnel --url http://localhost:8000
```

It prints a public `https://<random-words>.trycloudflare.com` link that works
from any device, on any network, until you press Ctrl+C. The link changes
each time.

---

## Running with Docker

Docker runs the whole demo with nothing else installed: no Python, no Node,
no data download. Tested with Docker Desktop 29.8 on Windows.

```bash
docker compose -f docker/docker-compose.yml up --build     # http://localhost:8000
docker compose -f docker/docker-compose.yml down           # stop and remove
```

Run these from the repo root. On Windows, `./docker/run-env.ps1` does the
same (`-Dev` adds the dev server described below; `-Down` stops everything).
The first build downloads the base images and takes about a minute; after that
it takes seconds. The container is ready (and marked *healthy*) about 8
seconds after it starts.

### What's in the image

`docker/Dockerfile` builds one self-contained image (~180 MB):

1. **Stage 1** (Node 24) runs `npm ci` and `npm run build` to build the React
   site from `web/src`.
2. **Stage 2** (Python 3.13 slim) copies `web/api/*.py`, the data file and
   the built site. It runs `server.py` as a non-root user, with a health check
   on `/api/health`.

It uses about 250 MB of RAM. The build context is the repo root, and
`.dockerignore` keeps `raw/`, `node_modules`, `.git` and so on out of it.
Without compose:

```bash
docker build -f docker/Dockerfile -t medmap .
docker run --rm -p 8000:8000 medmap
```

### Settings

Copy `docker/.env.example` to `docker/.env` and change what you need.
`docker/.env` is git-ignored, and every setting has a default:

| Variable | Default | Meaning |
|---|---|---|
| `MEDMAP_PORT` | `8000` | Port on your computer for the site and API |
| `WEB_DEV_PORT` | `5173` | Port for the hot-reload dev server |
| `MEDMAP_CACHE_SIZE` | `6` | Score tables kept in memory (~40 MB each) |
| `OPTIMIZER_URL` | empty | Where to get scores from; empty = built-in placeholder (see below) |

### Editing the frontend without installing Node

```bash
docker compose -f docker/docker-compose.yml --profile dev up --build
```

This also runs the Vite dev server in a Node container at
**<http://localhost:5173/>**. `web/` is mounted from your computer, so saving
a file updates the page in under a second, and `/api` is forwarded to the
`medmap` container. When you're done, stop it and rebuild the committed site so
`web/dist/` is current for Python users:

```bash
docker compose -f docker/docker-compose.yml --profile dev stop web-dev
docker compose -f docker/docker-compose.yml --profile dev run --rm --no-deps web-dev sh -c "npm ci && npm run build"
```

### Adding more services later

The setup is built to grow without changing the website:

- **The real algorithm.** Give `/algorithm` its own Dockerfile and an API
  that answers `GET /api/optimize` like the placeholder does (same query
  parameters and response shape; see [API reference](#api-reference)).
  Uncomment the `algorithm` service template at the bottom of
  `docker/docker-compose.yml`, and set `OPTIMIZER_URL=http://algorithm:8000`
  in `docker/.env`. The `medmap` container then forwards every scoring request
  to it (`web/api/remote_optimizer.py`), while still serving the site,
  hospitals and heatmap data. If the algorithm container is down, the site
  stays up and the status line shows a clear error (HTTP 502). This was tested
  with a stand-in algorithm container.
- **Other services** (a database, a job that rebuilds the data): add them as
  services in the same file. Containers reach each other by service name
  (`http://medmap:8000`, `http://algorithm:8000`).
- **Deploying later.** The image runs anywhere that runs containers.
  It reads `PORT` and `HOST` from the environment, which is how most hosts
  configure containers. Build it from `docker/Dockerfile` with the repo root
  as context. Nothing in it depends on this computer.

---

## Updating the data

The server reads `web/api/medmap_data.json.gz`, which holds the joined tables
built from the raw CSVs. It gives the same results as loading the CSVs
directly (checked on every endpoint) and loads in 0.2 s instead of 10–20 s.
To rebuild it after downloading newer raw data (Windows):

```powershell
./src/optimal_hospital_placer/etl/get_raw_data.ps1 -Sources CMSHospital,PLACES,HPSA,MUAP,RUCA
python web/api/build_data.py          # reads raw/, writes web/api/medmap_data.json.gz
```

Then commit the updated `medmap_data.json.gz`. To run straight from the CSVs
instead, use `python web/api/server.py --raw raw`.

---

## What's in `web/`

The frontend is a **React** app built with **Vite**. The Python server
serves the built copy in `web/dist/` and the JSON API on the same port.

```
web/
├── start.cmd                 Windows: double-click to start MedMap (this computer only)
├── share.cmd                 Windows: same, but other devices on your Wi-Fi can open it
├── index.html                Vite entry page (loads src/main.jsx)
├── package.json              npm scripts: dev, build, preview, api
├── vite.config.js            Dev server on 5173, forwards /api to Python on 8000
├── public/favicon.svg
├── dist/                     Built site (committed; rebuild with `npm run build`)
├── src/
│   ├── main.jsx              Mounts <App/> into index.html's #root
│   ├── App.jsx               Routes: /  /map  /about (the map page loads on demand)
│   ├── config.js             API_BASE, basemap style, GitHub link
│   ├── pages/
│   │   ├── HomePage.jsx
│   │   ├── MapPage.jsx       Owns the map page state: settings, data, popups
│   │   └── AboutPage.jsx     Team, GitHub link, credits (names still TODO)
│   ├── components/
│   │   ├── Layout.jsx        Top nav + page outlet
│   │   ├── map/
│   │   │   ├── MedMap.jsx    MapLibre wrapped as a React component
│   │   │   ├── layers.js     Sources, layers, and feature-state expressions
│   │   │   ├── Popups.jsx    Hospital and site popups (React, rendered into MapLibre popups)
│   │   │   └── Legend.jsx    Bottom-right legend: collapsible and closable
│   │   └── sidebar/
│   │       └── Controls.jsx  Region, weights, placement, results, layers, type filter
│   ├── hooks/
│   │   ├── useDebouncedValue.js
│   │   └── useOptimize.js    Calls /api/optimize, cancels outdated requests
│   ├── lib/                  api.js, constants.js, format.js, geo.js
│   └── styles/               site.css, map.css
└── api/
    ├── server.py             JSON API + serves web/dist on one port
    ├── data_loader.py        Joins the raw CSVs; saves/loads the data bundle
    ├── medmap_data.json.gz   The joined data (1.6 MB, committed); used by default
    ├── build_data.py         Rebuilds medmap_data.json.gz from raw/
    ├── placeholder_optimizer.py   Stand-in scoring until /algorithm exists
    └── remote_optimizer.py   Forwards scoring to another service when OPTIMIZER_URL is set
```

Docker files live outside `web/`: `docker/Dockerfile`,
`docker/docker-compose.yml`, `docker/.env.example`, `docker/run-env.ps1` and
`.dockerignore`.

**How React and the map connect:** `MapPage` holds all the state (weights,
radius, layers, the open popup, and so on) and passes it as props to
`<MedMap>`. `MedMap` creates the MapLibre map once and uses one `useEffect`
per concern to push props into it: GeoJSON sources, layer visibility, the
hospital-type filter, and feature-state for hover and selection. MapLibre's own
events (hover, click) call back up through `onHospitalsClick`,
`onCandidateClick`, `onCandidateHover` and `onPopupClose`. Popup contents are
ordinary React components rendered into the MapLibre popup with a portal.
`MapPage` calls `fitBounds` and `focusOn` on the map through a `ref`.

The frontend only talks to the backend over HTTP (`/api/...`). It never
imports Python code, so the placeholder can be replaced without touching the
frontend.

`web_test/` holds the earlier prototype (the HTML start screen ported from
`main.py` and the first MapLibre experiment). `web/` replaces it.
`web_test/` was left untouched.

**Libraries:** [React 19](https://react.dev/),
[React Router 8](https://reactrouter.com/),
[MapLibre GL JS 6.11.2](https://maplibre.org/) (bundled from npm, not a CDN),
[Vite 8](https://vite.dev/), and [OpenFreeMap](https://openfreemap.org/)
"positron" tiles. None needs an API key.

---

## Working on the frontend

Install [Node.js](https://nodejs.org/) 22.12 or newer (LTS is fine), then once:

```bash
cd web
npm install
```

**Day to day**, run two terminals:

```bash
python web/api/server.py          # terminal 1, from the repo root: API on :8000
cd web && npm run dev             # terminal 2: React app on http://localhost:5173
```

Open <http://localhost:5173/>. Vite reloads the page as you save files and
forwards `/api/...` to the Python server, so everything is one origin.

**Before committing frontend changes**, rebuild the copy the Python server
serves:

```bash
cd web && npm run build           # writes web/dist/
```

`web/dist/` is committed on purpose so teammates without Node can still run
the demo. If you change `src/` and forget to rebuild, `start.cmd` will show the
old version.

Notes:

- In `npm run dev`, React's StrictMode mounts each component twice to catch
  bugs, so you'll see two `/api/optimize` requests on page load (the first is
  cancelled). The production build sends one.
- MapLibre 6 needs its web worker handed to it explicitly under a bundler.
  `MedMap.jsx` does this with
  `import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url"`.
  Don't remove it, or no map tiles will load.
- To point the frontend at a different API (for example the future
  `/algorithm` server), build with `VITE_API_BASE=http://127.0.0.1:8001 npm run build`.
  The Python API sends CORS headers, so a different origin works.

---

## Using the map

| Control | What it does |
|---|---|
| **Region** | Limits candidate sites to one state and zooms there. Hospitals and population outside the state are still used when scoring, so a site near a border counts people across it. |
| **Weights** (4 sliders, 0–1) | How much population, distance, shortage bonus and cost matter. Results update 300 ms after you stop dragging (debounced), so dragging doesn't flood the API. The total turns amber if it's far from 1. **Make total 1** rescales the weights, and **Reset** restores the defaults. The server rescales weights anyway, so the total only needs to be roughly 1. |
| **Coverage radius** | Slider (5–100 mi) or number box. This is the distance at which a hospital counts as "reachable". It's used in scoring, drawn as the dashed rings, and used by the "beyond radius" heatmap. |
| **Sites** | How many recommendations to return (1–25). |
| **Recommended sites** list | Hover a row to highlight the site on the map. Click it to fly there and open its score breakdown. |
| **Layers** | Show or hide hospitals, recommended sites, coverage rings and the heatmap. Hiding a layer only changes its `visibility`, so it's never removed and re-added. The **Heatmap** button in the map's top-right corner (as on the whiteboard sketch) is a shortcut for the same switch. |
| **Heatmap shows** | *All population* (tract populations), or *Population outside the radius of any hospital*, which shows the underserved people the scoring is trying to reach. |
| **Hospital types** | Show or hide markers by CMS hospital type (with counts). This is display only: scoring always uses the coverage hospitals listed [below](#data-assumptions). |
| **Legend** (bottom right, as on the sketch) | Click the title to collapse it, or **×** to close it (a small **Legend** button brings it back). It starts collapsed on phones. |

On the map:

- **Hover** a hospital or site to highlight it.
- **Click a hospital** to see its name, type, address, phone, ownership,
  emergency services, CMS star rating, and how its location was determined.
  When several hospitals share a ZIP code (and so a point), the popup lists all
  of them.
- **Click a recommended site** to see the score breakdown. There's a bar for each
  factor (0–1) and its weighted contribution to the score, plus the underlying
  numbers: people gaining coverage, average miles saved, distance to the
  nearest hospital today, shortage flags, and density.
- Highlighting uses `map.setFeatureState()` with `hover` and `selected` keys,
  and the layers' `circle-color` and `circle-radius` expressions read those
  states. Layer paint is never changed to highlight something.

**Shareable URLs:** the weights, radius, number of sites and state are kept in
the address bar, for example
`/map?w_population=0.5&w_distance=0.3&w_shortage=0.2&w_cost=0&radius=20&k=5&state=MO`.
Copy the link to share a view. Old `map.html` links still work (they redirect).

**Phones:** the sidebar becomes a drawer opened with the **Controls** button
at the map's top left, and closed with **Close controls** at the top of the
drawer.

**Debugging:** the MapLibre map object is available in the browser console as
`window.medmapMap`.

---

## API reference

All endpoints are `GET`, return JSON, send `Access-Control-Allow-Origin: *`,
and are gzip-compressed when the browser accepts it. Invalid parameters return
**400** with `{"error": "..."}`. An unknown `/api/...` path returns **404**.

### `GET /api/optimize`

Ranks candidate sites.

| Param | Type | Default | Range |
|---|---|---|---|
| `w_population` | float | `0.4` | 0–1 |
| `w_distance` | float | `0.3` | 0–1 |
| `w_shortage` | float | `0.2` | 0–1 |
| `w_cost` | float | `0.1` | 0–1 |
| `radius` | int (miles) | `30` | 5–100 |
| `k` | int | `5` | 1–25 |
| `state` | 2-letter code | all states | see `/api/states` |
| `include_hospitals` | `0`/`1` | `1` | Set to `0` to skip the ~2 MB hospital list (the map does this) |

Response:

```jsonc
{
  "candidates": {                       // GeoJSON FeatureCollection, best first
    "type": "FeatureCollection",
    "features": [{
      "type": "Feature",
      "id": 29179380200,                // census tract FIPS as a number: stable id
      "geometry": { "type": "Point", "coordinates": [-90.90049, 37.22629] },
      "properties": {
        "rank": 1, "score": 0.9231,
        "tract_id": "29179380200", "state": "MO", "county": "Reynolds",
        "tract_population": 3437,
        "uncovered_population": 8987,       // people gaining a hospital within radius
        "avg_distance_reduction_mi": 22.0,  // average miles saved for those people
        "nearest_hospital_mi": 30.9,        // from this tract to today's nearest hospital
        "density_per_sq_mi": 9.5, "density_imputed": false,
        "in_mua": true, "in_hpsa": true, "ruca": 10,
        "f_population": 0.9651, "f_distance": 0.8187,   // normalized factors, 0-1
        "f_shortage": 1.0,      "f_cost": 0.9148
      }
    }]
  },
  "hospitals": { /* FeatureCollection, omitted when include_hospitals=0 */ },
  "meta": {
    "engine": "placeholder",
    "weights": { "population": 0.4, "distance": 0.3, "shortage": 0.2, "cost": 0.1 },
    "radius_mi": 30, "k": 5, "state": "MO",
    "candidates_considered": 1648,
    "candidates_adding_coverage": 77,   // 0 means everyone is already covered at this radius
    "compute_ms": 31
  }
}
```

### Other endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/hospitals?state=XX` | FeatureCollection of hospitals. `id` is a stable integer (hospitals sorted by CMS Facility ID). Properties: `facility_id, name, address, city, state, zip, county, phone, type, ownership, emergency, rating, counts_for_coverage, loc_quality`. |
| `GET /api/population?state=XX` | One point per census tract for the heatmap: `p` = population, `d` = straight-line miles to the nearest coverage hospital. About 1 MB gzipped for the whole U.S. The map only loads it when the heatmap is first turned on. |
| `GET /api/states` | `{"states": [{"state", "bbox": [w, s, e, n], "tracts", "hospitals"}]}` for the 50 states and DC |
| `GET /api/health` | `{"status": "ok", "engine", "stats"}` with the data-loading counts listed in [Data assumptions](#data-assumptions) |

Timing on a laptop: the first `/api/optimize` for a new radius takes about
0.5–3 s nationwide (up to about 8 s at a 5-mile radius) or under 0.1 s for one
state. After that, only the weights change and the call takes a few
milliseconds, because weight-independent factors are cached per
(radius, state), keeping the 16 most recent.

---

## Scoring (placeholder)

> This is a **stand-in** so the map shows real, explainable results. It
> follows the factor definitions in `algorithm_prompt.txt`, but it is not the
> final algorithm: there's no greedy re-scoring and no unit tests yet. It lives
> in `web/api/placeholder_optimizer.py`.

**Candidates:** every census tract centroid (83,522 nationwide, or the tracts
in the selected state).

**Coverage:** a tract is *covered* when a **coverage hospital** is within
`radius` miles of its centroid. Distances are **straight-line (haversine)
miles**, not driving miles.

For a candidate tract *c*, let *U* be the uncovered tracts within `radius` of
*c* (including uncovered tracts in neighbouring states), *pop(t)* a tract's
population, *near(t)* the miles from tract *t* to its nearest coverage hospital,
and *dist(c,t)* the miles from *c* to *t*. Then:

| Factor | Raw value | Normalized to [0, 1] |
|---|---|---|
| **population** | P = Σ<sub>t∈U</sub> pop(t) | min(1, P / p95) |
| **distance** | D = Σ<sub>t∈U</sub> pop(t)·(near(t) − dist(c,t)) / P (0 if P = 0) | min(1, D / p95) |
| **shortage** | 0.5·[c is in an active MUA/P] + 0.5·[c is in an active primary-care HPSA] | already 0, 0.5 or 1 |
| **cost** | L = ln(1 + people per sq. mile of c) | 1 − (L − min L) / (max L − min L) |

*p95* is the 95th percentile of that factor's **non-zero** raw values over the
candidate pool. Dividing by the maximum instead let a single outlier (an
Aleutian island tract hundreds of miles from any hospital) squash every other
candidate's distance factor to nearly 0. *min* and *max* are also taken over
the candidate pool.

**Score:**

```
score = (w_population·population + w_distance·distance
         + w_shortage·shortage + w_cost·cost) / (w_population + w_distance + w_shortage + w_cost)
```

If every weight is 0, all four are treated as equal.

**Default weights:** population **0.4**, distance **0.3**, shortage **0.2**,
cost **0.1**. They're defined in both `web/api/server.py` (`DEFAULT_WEIGHTS`)
and `web/src/lib/constants.js` (`DEFAULT_WEIGHTS`).

**Picking k sites:** sort by score (ties go to more uncovered population, then
tract id). Walk down the list, skipping any candidate closer than `radius`
miles to one already picked, until *k* are chosen. This spacing rule stops the
top 5 from being five neighbouring tracts. It is **not** the greedy
"remove covered demand and rescore" approach the real algorithm should use.

**When nobody is uncovered:** in some states at large radii (for example Texas
at 60 mi), every tract already has a coverage hospital in range. Population and
distance are then 0 for every candidate, so only shortage and cost decide the
ranking. The map says so in the status line.

For scale, at the default 30 miles, **399 tracts (about 1.02 million people)**
have no coverage hospital within 30 straight-line miles.

---

## What the data files contain

This is the Step 0 exploration of `raw/`. Every CSV was profiled (columns,
inferred types, row counts, sample rows). **No hospital file has
latitude/longitude**, so hospitals are placed by ZIP code (see
[assumptions](#data-assumptions)).

### Used by the map

| File | Rows × cols | What it is | Columns used |
|---|---|---|---|
| `CMSHospital/Hospital_General_Information.csv` | 5,419 × 38 | CMS Care Compare hospital list: every Medicare hospital | `Facility ID, Facility Name, Address, City/Town, State, ZIP Code, County/Parish, Telephone Number, Hospital Type, Hospital Ownership, Emergency Services, Hospital overall rating` |
| `PLACES/places_tract.csv` | 83,522 × 88 | CDC PLACES tract-level health estimates, with population and a centroid (`Geolocation` = `POINT (lon lat)`) | `StateAbbr, CountyName, CountyFIPS, TractFIPS, TotalPopulation, Geolocation` |
| `PLACES/places_zcta.csv` | 32,520 × 84 | Same, by ZIP Code Tabulation Area | `ZCTA5, Geolocation` (to place hospitals) |
| `PLACES/places_county.csv` | 3,143 × 167 | Same, by county | `StateAbbr, CountyName, Geolocation` (hospital fallback) |
| `RUCA/2020-rural-urban-commuting-area-codes-census-tracts.csv` | 85,528 × 27 | USDA rural-urban codes (1 = metro core … 10 = rural) plus population, land area and density per tract | `TractFIPS20, PrimaryRUCA, PopDensity` |
| `MUAP/MUA_DET.csv` | 20,132 × 63 | HRSA Medically Underserved Areas/Populations, one row per component (tract, county subdivision or county) | `MUA/P Status Description`, component type, `MUA/P Area Code` (tract FIPS), state+county FIPS |
| `HPSA/BCD_HPSA_FCT_DET_PC.csv` | 80,199 × 66 | HRSA **primary-care** Health Professional Shortage Areas, one row per component | `HPSA Status, Designation Type, HPSA Component Type Description, HPSA Geography Identification Number` |

### Not used yet

| File | Rows × cols | What it is | Could be used for |
|---|---|---|---|
| `CMSFacilities/Hospital_and_other.DATA.Q2_2026.csv` | 44,707 × 473 | CMS Provider of Services file: hospitals and other providers, with `CRTFD_BED_CNT` (certified beds), provider category, ZIP, state/county FIPS | **Bed counts** for "burden on existing hospitals" |
| `CMSFacilities/Hospital_Enrollments_2026.07.31.csv` | 9,161 × 39 | Medicare hospital enrollments: CCN, provider type, subgroups (general, long-term, swing-bed…) | Cross-checking hospital types |
| `CMSFacilities/POS_iQIES.DATA.Q2_2026.csv` | 77,564 × 182 | Provider of Services (iQIES): home health, nursing homes and similar | — |
| `CMSFacilities/{FQHC,RHC,HHA,Hospice,SNF}_Enrollments_*.csv` | 5.6k–14.4k rows each | Medicare enrollments for health centers, rural health clinics, home health, hospice, skilled nursing | Counting FQHC/RHC primary care as partial coverage |
| `HPSA/BCD_HPSA_FCT_DET_DH.csv`, `..._MH.csv` | 47,436 × 65 and 41,250 × 65 | Dental and mental-health HPSAs | Extra shortage flags |
| `PLACES/places_place.csv` | 29,923 × 168 | PLACES by city/town | City labels |
| `SVI/SVI_2022_US.csv`, `SVI_2022_US_county.csv` | 84,120 × 158 and 3,144 × 158 | CDC Social Vulnerability Index (tract and county) | A vulnerability factor |
| `AHRF/*.zip` | zipped | HRSA Area Health Resources Files (county-level workforce and facilities; main CSV ~40 MB inside the zip) plus docs | County physician and bed supply |
| `ACS/acs_2024_variables.json` | — | Census ACS **variable metadata only**, no data rows | — |

Which files have what:

- **Hospital coordinates:** none. Hospitals have addresses and ZIPs only. The
  only lat/lon columns are in the HPSA files, and only on facility-type
  designations (FQHCs, clinics), not hospitals.
- **Census/population:** PLACES (`TotalPopulation` at tract, ZCTA, county and
  place level), RUCA (`Population`, `PopDensity`), SVI (`E_TOTPOP`).
- **MUA/HPSA designations:** `MUAP/MUA_DET.csv` and the three `HPSA/*.csv`
  files, keyed by tract FIPS, county FIPS or county subdivision.

---

## Data assumptions

Each of these is a judgment call. The counts come from `/api/health` on the
current `raw/` snapshot.

1. **Hospital locations are ZIP-code centroids.** Each hospital goes at the
   PLACES ZCTA centroid for its ZIP (**5,208** hospitals). If the ZIP isn't a
   ZCTA (PO-box or single-building ZIPs, such as UCLA's 90095), it goes to the
   numerically nearest ZCTA with the same first three digits (**144**), then to
   the county centroid (**1**). **1** hospital couldn't be placed. Every
   hospital popup says which method was used. Hospitals in the same ZIP share a
   point, and the popup lists all of them.
2. **Territories are left out.** PLACES covers the 50 states and DC only, so the
   **65** hospitals in PR, VI, GU, AS and MP have no population to score
   against and are dropped. **5,353** hospitals are on the map.
3. **Coverage hospitals** (the ones that count as existing care) are the CMS
   types *Acute Care Hospitals*, *Critical Access Hospitals*, *Acute Care -
   Veterans Administration*, *Acute Care - Department of Defense* and *Rural
   Emergency Hospital*. *Psychiatric*, *Childrens* and *Long-term* hospitals
   are drawn on the map but don't count, since they don't serve general acute
   demand. Popups say "Not counted as existing coverage" for these.
4. **Population** is PLACES `TotalPopulation` at the tract centroid (331.4
   million total). Everyone in a tract is treated as living at its centroid.
5. **Active designations** are status *Designated* or *Proposed For
   Withdrawal*. *Withdrawn* rows are ignored.
6. **MUA/P:** tract components match by 11-digit tract FIPS, and whole-county
   components flag every tract in that county. All designation types count:
   MUA, MUP (population group) and their governor's-exception variants
   (MUA-GE, MUP-GE). **County-subdivision components are skipped**
   because this data has no tract-to-subdivision mapping. Result: **26,989**
   tracts flagged.
7. **HPSA:** primary care only. Only *Geographic HPSA*, *High Needs Geographic
   HPSA* and *HPSA Population* designations are used; facility HPSAs (FQHCs,
   prisons, clinics) are points, not areas. Tract and whole-county components
   are matched as for MUA/P. Result: **41,513** tracts flagged.
8. **Tract IDs don't always match between sources.** 10,164 of 12,022 active
   MUA tract codes and 15,443 of 16,875 HPSA tract codes match a PLACES tract.
   The rest are Puerto Rico tracts or tract numbers that changed between census
   vintages.
9. **Density** comes from RUCA `PopDensity` (people per square mile), matched
   by tract FIPS for **82,646** of 83,522 tracts. The other 876 use the median
   density of the candidate pool, and their popups say "(estimated)".
10. **Alaska:** a few Aleutian tracts sit east of the 180° meridian. They're
    handled for map bounds, but the spatial grid doesn't wrap across 180°, so
    radius searches there don't see points on the other side. This has no
    practical effect at radii ≤ 100 mi.

---

## Known limitations

- **Straight-line distance, not driving distance.** Mountains, rivers and road
  networks are ignored.
- **ZIP-centroid hospital locations** can be several miles off, more in large
  rural ZIPs.
- **Placeholder scoring:** no greedy re-scoring, no hospital capacity (beds),
  and no measure of existing hospitals' load. "Lifting burden off existing
  hospitals" is only approximated by covering people who are far from any.
- **Tract-centroid population:** big rural tracts are treated as one point.
- The committed data file is a snapshot. If the raw sources are
  re-downloaded, someone has to run `build_data.py` and commit the result
  (see [Updating the data](#updating-the-data)).
- Score tables are cached in memory only, so each server restart recomputes
  them on first use (a few seconds per new radius nationwide).
- Browsers need **WebGL2** (MapLibre 6 requirement), which all current
  browsers support.
- In the browser console, the OpenFreeMap basemap logs two harmless warnings
  about its highway-shield layers. They come from the basemap style, not
  MedMap.

---

## Plugging in the real algorithm

The frontend depends only on the HTTP contract above. When `/algorithm` is
ready, pick one:

- **Run it as its own service (recommended):** give it an API that answers
  `GET /api/optimize` with the same parameters and response, and set
  `OPTIMIZER_URL` to its address. `web/api/remote_optimizer.py` then forwards
  scoring to it, and this server keeps serving the site and the other
  endpoints. With Docker, it's a compose change; see
  [Adding more services later](#adding-more-services-later). Without Docker,
  run it on another port and start this server with, for example,
  `OPTIMIZER_URL=http://127.0.0.1:8001 python web/api/server.py`.
- **Replace the engine inside this server:** in `web/api/server.py`, build the
  algorithm's optimizer instead of `PlaceholderOptimizer`. It needs a
  `get_top_placements(weights, radius=, k=, state=)` method that returns
  `(FeatureCollection, meta_dict)` with the feature properties listed under
  [`/api/optimize`](#get-apioptimize). The popup reads `rank`, `score`,
  `f_population`, `f_distance`, `f_shortage`, `f_cost`,
  `uncovered_population`, `avg_distance_reduction_mi`, `nearest_hospital_mi`,
  `in_mua`, `in_hpsa`, `density_per_sq_mi`, `density_imputed`,
  `tract_population`, `tract_id`, `county` and `state`. Or:
In both cases the popup reads the same properties, so returned features need
all of the ones listed above.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Missing raw files in ...` | Only with `--raw` or `build_data.py`: download the five sources listed in [Updating the data](#updating-the-data). |
| Page says "Open MedMap through its server" | You opened `index.html` as a file. Double-click `web/start.cmd` or run `python web/api/server.py --open`. |
| Map shows "Can't reach the MedMap API" | The server isn't running, or (in `npm run dev`) it isn't on port 8000. Start `python web/api/server.py`. |
| Page says "The MedMap site hasn't been built" | `web/dist/` is missing. Run `npm install` and `npm run build` in `web/`. |
| A teammate opens `http://127.0.0.1:8000` and gets nothing | That address means *their own* computer. Give them your Wi-Fi address from `share.cmd`, or a public link. See [Sharing the demo](#sharing-the-demo-with-other-people). |
| Other devices can't open the `http://192.168...:8000` link | Allow Python (or Docker) through the Windows firewall, and make sure you started with `share.cmd` / `--host 0.0.0.0`. Some venue Wi-Fi networks block device-to-device traffic. Use the tunnel option instead. |
| `No data found ... medmap_data.json.gz is missing` | Run `git pull`; the file is committed. Or rebuild it (see [Updating the data](#updating-the-data)). |
| Docker: `port is already allocated` | Something else (maybe `start.cmd`) is using port 8000. Stop it, or set `MEDMAP_PORT=8001` in `docker/.env`. |
| `docker: command not found` right after installing Docker Desktop | Close and reopen the terminal (or VS Code) so it picks up Docker's new PATH, and make sure Docker Desktop is running. |
| Docker site says `Can't reach the optimizer service` | `OPTIMIZER_URL` is set but that service isn't running. Start it, or clear `OPTIMIZER_URL` in `docker/.env` to use the placeholder. |
| `start.cmd` says Python isn't installed | Install Python 3 from python.org (tick "Add python.exe to PATH") or run `winget install Python.Python.3.12`. |
| Changes in `web/src/` don't show up at :8000 | The server shows the built copy. Run `npm run build` in `web/`, or use `npm run dev` while editing. |
| Map area is blank but the sidebar works | Your browser lacks WebGL2 (MapLibre 6 requires it); the map area says so. Use a current Chrome, Edge, Firefox or Safari. |
| Grey map with no streets | The tile CDN is unreachable (offline or firewall). Hospitals and sites still draw. |
| `Address already in use` | Something else is on port 8000. Use `--port 8001`. |
| First score takes a few seconds | Normal for a new radius nationwide. Later slider moves are near-instant. |
