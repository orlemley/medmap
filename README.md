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
- [What's in `web/`](#whats-in-web)
- [Using the map](#using-the-map)
- [API reference](#api-reference)
- [Serving the frontend separately](#serving-the-frontend-separately)
- [Scoring (placeholder)](#scoring-placeholder)
- [What the data files contain](#what-the-data-files-contain)
- [Data assumptions](#data-assumptions)
- [Known limitations](#known-limitations)
- [Plugging in the real algorithm](#plugging-in-the-real-algorithm)
- [Troubleshooting](#troubleshooting)

---

## Quick start

**Requirements:** Python 3.8 or newer. No packages to install: the server uses
only the standard library. You need an internet connection in the browser for
the map tiles and the MapLibre library (both load from CDNs).

1. **Get the data.** The server reads the raw CSVs from `raw/` in the repo root.
   `raw/` is git-ignored, so each person downloads it themselves. On Windows:

   ```powershell
   ./src/optimal_hospital_placer/etl/get_raw_data.ps1 -Sources CMSHospital,PLACES,HPSA,MUAP,RUCA
   ```

   Those five sources are the only ones the map needs. See
   `src/optimal_hospital_placer/etl/get_raw_data.README.md` for the other options.

2. **Start the server** from the repo root:

   ```bash
   python web/api/server.py
   ```

   On macOS/Linux use `python3` if `python` isn't found. It takes about
   10–15 seconds to load the data, then prints:

   ```
   MedMap running at http://127.0.0.1:8000/  (Ctrl+C to stop)
   ```

3. **Open <http://127.0.0.1:8000/>** in a browser.

Options:

| Flag | Default | Meaning |
|---|---|---|
| `--port` | `8000` | Port for both the API and the site |
| `--host` | `127.0.0.1` | Use `0.0.0.0` to let other devices on your network connect (for example, to demo from a phone) |
| `--raw` | `<repo>/raw` | Path to the data folder, if it lives somewhere else |

> Open the site **through the server** (`http://...`), not by double-clicking
> the HTML files. Browsers block JavaScript modules on `file://` pages.

---

## What's in `web/`

```
web/
├── index.html            Home page: what MedMap is and how it works
├── map.html              The interactive map
├── about.html            Team, GitHub link, credits (names still TODO)
├── css/
│   ├── site.css          Shared styles (nav, pages, colours)
│   └── map.css           Map page: sidebar, legend, popups
├── js/
│   ├── config.js         API_BASE and basemap URL: the only settings you'd change
│   └── map.js            All map behaviour
└── api/
    ├── server.py         Dev server: JSON API and static files on one port
    ├── data_loader.py    Reads raw CSVs into memory and joins them
    └── placeholder_optimizer.py   Stand-in scoring until /algorithm exists
```

The frontend only talks to the backend over HTTP (`/api/...`). It never
imports Python code, so the placeholder can be replaced without touching the
frontend.

`web_test/` holds the earlier prototype (the HTML start screen ported from
`main.py` and the first MapLibre experiment). The new `web/` replaces it.
`web_test/` was left untouched.

**Libraries:** [MapLibre GL JS 6.11.2](https://maplibre.org/) (ESM build from
jsDelivr) and [OpenFreeMap](https://openfreemap.org/) "positron" tiles. Both are
free and need no API key. No framework and no build step.

---

## Using the map

| Control | What it does |
|---|---|
| **Region** | Limits candidate sites to one state and zooms there. Hospitals and population outside the state are still used when scoring, so a site near a border counts people across it. |
| **Weights** (4 sliders, 0–1) | How much population, distance, shortage bonus and cost matter. Results update 300 ms after you stop dragging (debounced), so dragging doesn't flood the API. The total turns amber if it's far from 1. **Make total 1** rescales the weights, and **Reset** restores the defaults. The server rescales weights anyway, so the total only needs to be roughly 1. |
| **Coverage radius** | Slider (5–100 mi) or number box. This is the distance at which a hospital counts as "reachable". It's used in scoring, drawn as the dashed rings, and used by the "beyond radius" heatmap. |
| **Sites** | How many recommendations to return (1–25). |
| **Recommended sites** list | Hover a row to highlight the site on the map. Click it to fly there and open its score breakdown. |
| **Layers** | Show or hide hospitals, recommended sites, coverage rings and the heatmap. Hiding a layer only changes its `visibility`, so it's never removed and re-added. |
| **Heatmap shows** | *All population* (tract populations), or *Population outside the radius of any hospital*, which shows the underserved people the scoring is trying to reach. |
| **Hospital types** | Show or hide markers by CMS hospital type (with counts). This is display only: scoring always uses the coverage hospitals listed [below](#data-assumptions). |
| **Legend** (bottom left) | Collapsible. It starts collapsed on phones. |

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
`map.html?w_population=0.5&w_distance=0.3&w_shortage=0.2&w_cost=0&radius=20&k=5&state=MO`.
Copy the link to share a view.

**Phones:** the sidebar becomes a drawer opened with the **Controls** button.

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

## Serving the frontend separately

The API sends CORS headers, so the static site can run on its own port:

```bash
python web/api/server.py --port 8000                 # API (still serves the site too)
python -m http.server 5500 --directory web            # static site only
```

Then set `API_BASE` in `web/js/config.js` to `"http://127.0.0.1:8000"` and open
<http://127.0.0.1:5500/map.html>. If `API_BASE` is wrong, the map shows a
"Can't reach the MedMap API" message explaining how to fix it.

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
and `web/js/map.js` (`DEFAULT_WEIGHTS`).

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
- Data is loaded into memory at startup (about 10–15 s). Nothing is cached to
  disk.
- Browsers need **WebGL2** (MapLibre 6 requirement), which all current
  browsers support.
- In the browser console, the OpenFreeMap basemap logs two harmless warnings
  about its highway-shield layers. They come from the basemap style, not
  MedMap.

---

## Plugging in the real algorithm

The frontend depends only on the HTTP contract above. When `/algorithm` is
ready, either:

- **Replace the engine inside this server:** in `web/api/server.py`, build the
  algorithm's optimizer instead of `PlaceholderOptimizer`. It needs a
  `get_top_placements(weights, radius=, k=, state=)` method that returns
  `(FeatureCollection, meta_dict)` with the feature properties listed under
  [`/api/optimize`](#get-apioptimize). The popup reads `rank`, `score`,
  `f_population`, `f_distance`, `f_shortage`, `f_cost`,
  `uncovered_population`, `avg_distance_reduction_mi`, `nearest_hospital_mi`,
  `in_mua`, `in_hpsa`, `density_per_sq_mi`, `density_imputed`,
  `tract_population`, `tract_id`, `county` and `state`. Or:
- **Run the algorithm's own API** and point `API_BASE` in `web/js/config.js` at
  it. It must also provide `/api/states` and `/api/hospitals` (and
  `/api/population` for the heatmap) in the same shapes.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Data folder not found` when starting | Download the data (step 1) or pass `--raw path/to/raw`. |
| `KeyError` or `FileNotFoundError` naming a CSV | One of the five required sources is missing. Re-run the download for `CMSHospital,PLACES,HPSA,MUAP,RUCA`. |
| Map shows "Can't reach the MedMap API" | Start `python web/api/server.py` and open the page from `http://127.0.0.1:8000/`, or fix `API_BASE`. |
| Blank page, or a console error about modules | You opened the HTML file directly. Use the server URL. |
| Grey map with no streets | The tile CDN is unreachable (offline or firewall). Hospitals and sites still draw. |
| `Address already in use` | Something else is on port 8000. Use `--port 8001`. |
| First score takes a few seconds | Normal for a new radius nationwide. Later slider moves are near-instant. |
