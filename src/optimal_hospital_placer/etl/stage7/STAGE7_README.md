# Stage 7 — hospital configuration optimization

Stage 7 reads `data/stage6/latest_success.json` and evaluates each Stage 6 candidate site against five transparent hospital archetypes:

- `rural_25`
- `community_50`
- `community_100`
- `regional_200`
- `regional_300`

It does **not** rerun Stage 6 and does not need Docker/Valhalla.

## Run

From repository root:

```powershell
python -m pip install -r src/optimal_hospital_placer/etl/stage7/requirements.txt
python src/optimal_hospital_placer/etl/stage7/run_stage7.py
```

Missouri only:

```powershell
python src/optimal_hospital_placer/etl/stage7/run_stage7.py --states 29
```

## Outputs

`data/stage7/latest_success.json` points to a run containing:

- `candidate_hospitals.parquet` — every site × hospital-configuration scenario
- `top_sites.parquet` — best configuration for every unique site
- `finalists.parquet` — top unique sites for application/demo use
- `routing_refinement_queue.parquet` — top unique sites to validate with precise local routing
- `assumptions.json`
- `summary.json`
- `manifest.json`

## Scoring

Stored separately for API-time reweighting:

- `access_score`
- `capacity_score`
- `vulnerability_score`
- `configuration_fit_score`
- `cost_efficiency_score`
- `overall_score`

The default composite is:

- access: 30%
- capacity: 25%
- vulnerability: 15%
- configuration fit: 20%
- cost efficiency: 10%

The API should re-rank the stored components rather than rerunning Stage 7 when a user moves weight sliders.

## Important assumptions

`target_beds_per_1000=2.5`, hospital archetypes, and capital costs are **planning proxies for comparative ranking**. They are intentionally recorded in `assumptions.json` and should not be presented as project-level financial forecasts or universal clinical standards.

## Precise routing after Stage 7

Use `routing_refinement_queue.parquet`, normally ~20 unique finalist sites. For each finalist, build a **small local** OSM/Valhalla workspace centered on that site and its relevant 60-minute demand area, compute actual drive-time matrices/isochrones, then update only those finalist access metrics. Do not build one rectangle around all finalists and do not reroute all Stage 6 candidates.
