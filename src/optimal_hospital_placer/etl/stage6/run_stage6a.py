"""Run fast nationwide Stage 6A screening before expensive Valhalla refinement."""
from __future__ import annotations

if __package__ in (None, ""):
    import sys
    from pathlib import Path as _BootstrapPath
    sys.path.insert(0, str(_BootstrapPath(__file__).resolve().parent.parent))
    __package__ = "stage6"

import argparse
from dataclasses import replace
from pathlib import Path

from .stage6a_screen import Stage6AScreenConfig, run_stage6a

ROOT = Path(__file__).resolve().parents[4]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage5-run", type=Path)
    p.add_argument("--min-population", type=int)
    p.add_argument("--min-screening-score", type=float)
    p.add_argument("--min-nearest-hospital-miles", type=float)
    p.add_argument("--top-n-per-state", type=int)
    p.add_argument("--top-fraction-per-state", type=float)
    p.add_argument("--severe-existing-drive-minutes", type=float)
    p.add_argument("--severe-min-population", type=int)
    args = p.parse_args()

    cfg = Stage6AScreenConfig()
    overrides = {
        "min_population": args.min_population,
        "min_screening_score": args.min_screening_score,
        "min_nearest_hospital_miles": args.min_nearest_hospital_miles,
        "top_n_per_state": args.top_n_per_state,
        "top_fraction_per_state": args.top_fraction_per_state,
        "severe_existing_drive_minutes": args.severe_existing_drive_minutes,
        "severe_min_population": args.severe_min_population,
    }
    cfg = replace(cfg, **{k: v for k, v in overrides.items() if v is not None})

    run = run_stage6a(ROOT, args.stage5_run, cfg)
    print(f"Stage 6A complete: {run}")
    print(f"  {run / 'screened_tracts.parquet'}")
    print(f"  {run / 'shortlisted_tracts.parquet'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
