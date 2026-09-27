# Final hackathon Stage 6

This version intentionally removes Valhalla/Docker from the nationwide Stage 6 path.

## Pipeline

Stage 5 -> Stage 6A screen -> Stage 6 fast -> Stage 7 -> precise routing only for finalists.

Stage 6 fast uses a rurality-adjusted straight-line road/travel-time approximation. It preserves the same application-facing feature family as the old Valhalla-heavy 6B while adding explicit provenance:

- `travel_time_model = approximate_v2_rurality_adjusted`
- `routing_refined = false`
- `candidate_precision = tract_level_proxy`

It produces:

- `candidate_sites.parquet`
- `candidate_site_features.parquet`
- `existing_access.parquet`
- `refinement_candidates.parquet` (top 250 Stage-6 candidates, only a convenience handoff)
- `summary.json`
- `manifest.json`
- `data/stage6/latest_success.json`

## Run

From repository root:

```powershell
python -m pip install -r src/optimal_hospital_placer/etl/stage6/requirements.txt
python src/optimal_hospital_placer/etl/stage6/run_stage6.py screen
python src/optimal_hospital_placer/etl/stage6/run_stage6.py fast
```

Or with defaults in one command:

```powershell
python src/optimal_hospital_placer/etl/stage6/run_stage6.py pipeline
```

Missouri-only candidates for development (cross-border demand still remains available):

```powershell
python src/optimal_hospital_placer/etl/stage6/run_stage6.py fast --states 29
```

A more aggressive Stage 6A shortlist can be created first:

```powershell
python src/optimal_hospital_placer/etl/stage6/run_stage6.py screen `
  --top-n-per-state 50 `
  --top-fraction-per-state 0.03 `
  --severe-existing-drive-minutes 45

python src/optimal_hospital_placer/etl/stage6/run_stage6.py fast
```

## Deliberate accuracy tradeoff

This is not road-network routing. It estimates travel time from straight-line distance using rurality-dependent detour factors and effective speeds. This is much faster and is intended to rank/screen locations for the hackathon.

Precise routing should happen **after Stage 7**, because Stage 7 will reduce site x hospital-configuration combinations to a small finalist set. At that point, build a tiny routing workspace around each finalist (or a small local cluster of finalists), calculate actual drive-time matrices and isochrones, and overwrite/augment the finalist metrics. Do not build a nationwide or state-sized routing graph.
