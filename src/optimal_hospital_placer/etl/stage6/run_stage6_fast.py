"""Run the final hackathon Stage 6: fast nationwide approximate access modeling."""
from __future__ import annotations

if __package__ in (None, ""):
    import sys
    from pathlib import Path as _BootstrapPath
    sys.path.insert(0, str(_BootstrapPath(__file__).resolve().parent.parent))
    __package__ = "stage6"

import argparse
from pathlib import Path

from .config import Stage6FastConfig
from .fast_stage6 import run_stage6_fast
from .road_model import ApproxRoadModel

ROOT = Path(__file__).resolve().parents[4]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage5-run", type=Path)
    p.add_argument("--stage6a-run", type=Path)
    p.add_argument("--states", nargs="+", help="Optional state FIPS candidates to model; demand remains national/cross-border")
    p.add_argument("--candidates-per-tract", type=int, default=1)
    p.add_argument("--demand-prefilter-miles", type=float, default=70.0)
    p.add_argument("--hospital-prefilter-miles", type=float, default=110.0)
    p.add_argument("--baseline-nearest-hospitals-k", type=int, default=12)
    p.add_argument("--urban-detour-factor", type=float, default=1.20)
    p.add_argument("--rural-detour-factor", type=float, default=1.34)
    p.add_argument("--urban-effective-mph", type=float, default=29.0)
    p.add_argument("--rural-effective-mph", type=float, default=52.0)
    args = p.parse_args()

    road = ApproxRoadModel(
        urban_detour_factor=args.urban_detour_factor,
        rural_detour_factor=args.rural_detour_factor,
        urban_effective_mph=args.urban_effective_mph,
        rural_effective_mph=args.rural_effective_mph,
    )
    cfg = Stage6FastConfig(
        candidates_per_tract=max(1, args.candidates_per_tract),
        demand_prefilter_miles=args.demand_prefilter_miles,
        hospital_prefilter_miles=args.hospital_prefilter_miles,
        baseline_nearest_hospitals_k=max(1, args.baseline_nearest_hospitals_k),
        road_model=road,
    )
    run_stage6_fast(ROOT, cfg, args.stage5_run, args.stage6a_run, args.states)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
