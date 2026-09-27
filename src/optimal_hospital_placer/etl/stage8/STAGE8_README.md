# Stage 8 — Final Candidate Refinement

Stage 8 is the final analytical ETL stage for the hackathon pipeline.

It deliberately keeps a large discoverable pool of physical sites while adding two things that were only coarse/implicit before:

1. **Department/service recommendations**
2. **Drive-time and drive-distance access features**

It does **not** require Docker or Valhalla. It consumes the approximate drive-time work already done by fast Stage 6 and makes that travel information a first-class part of the final score and API data contract.

## Inputs

By default Stage 8 reads:

`data/stage7/latest_success.json`

then:

`finalists.parquet`

If you want every Stage 7 top physical site instead, use:

`--source top-sites`

Stage 8 also attempts to join Stage 5 source-tract demographics, especially under-18 share and rurality/RUCA fields, when available.

## Run

From the repository root:

```powershell
python src/optimal_hospital_placer/etl/stage8/run_stage8.py
```

If your Stage 7 `finalists.parquet` contains 5,000 sites, all 5,000 are retained by default.

Use every Stage 7 top site instead:

```powershell
python src/optimal_hospital_placer/etl/stage8/run_stage8.py --source top-sites
```

Missouri only:

```powershell
python src/optimal_hospital_placer/etl/stage8/run_stage8.py --states 29
```

Cap a smoke test:

```powershell
python src/optimal_hospital_placer/etl/stage8/run_stage8.py --max-sites 200
```

## Outputs

`data/stage8/runs/<run>/`

- `final_candidates.parquet` — main final API/frontend table
- `service_recommendations.parquet` — long-format site × service table
- `travel_access_summary.parquet` — site × 15/30/45/60 minute access table
- `precise_routing_queue.parquet` — high-priority subset for future site-local Valhalla refinement
- `assumptions.json`
- `summary.json`
- `manifest.json`

and:

`data/stage8/latest_success.json`

## Services considered

- Emergency Department
- ICU
- General Surgery
- Maternity / Labor & Delivery
- Cardiology
- Stroke Capability
- Behavioral Health
- Pediatrics
- Advanced Imaging
- Oncology
- Dialysis

Each service gets its own `service_<name>_score`, `service_<name>_recommended`, and `service_<name>_gap`.

A `service_gap=true` means the Stage 8 service model recommends the department but the Stage 7 archetype did not already include it.

These are transparent hackathon planning heuristics, not clinical-utilization forecasts.

## Travel/access metrics

Stage 8 carries forward Stage 6's modeled travel-time features and explicitly adds:

- nearest existing hospital modeled drive minutes
- nearest existing hospital estimated drive miles
- modeled drive miles reachable in 15/30/45/60 minutes
- modeled straight-line radius corresponding to those drive-time windows
- population/newly accessible population within each drive-time window
- existing hospitals/beds within each drive-time window
- `drive_access_score`

`routing_refined=false` means these remain modeled values rather than exact road-network routing.

## Final score

Default:

`stage8_score = 55% Stage7 + 25% drive_access + 20% service_fit`

All three components are persisted separately so FastAPI can reweight them.

## Frontend guidance

Use `final_candidates.parquet` as the final analytical source of truth, but do not draw every row nationally.

Recommended API behavior:

- national viewport: return roughly 25–50 spatially diverse rows
- state/large region: 50–150
- local region: 100–300 or more
- candidate click: query full service + travel details

The dataset can safely contain thousands of discoverable candidates even though the map displays only a small subset.

## Precise routing later

`precise_routing_queue.parquet` does **not** delete other sites. It only identifies the strongest candidates for optional expensive routing.

The intended future refinement is site-local:

candidate → small local road graph → exact drive matrix/isochrones → update that candidate.

Do not build one rectangle around every finalist in the country.
