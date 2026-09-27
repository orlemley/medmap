from __future__ import annotations

import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optimal_hospital_placer.etl.stage7.config import Stage7Config
from optimal_hospital_placer.etl.stage7.optimize import run_stage7


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 7 hospital configuration optimization")
    parser.add_argument("--stage6-run", type=Path)
    parser.add_argument("--states", nargs="+")
    parser.add_argument("--target-beds-per-1000", type=float, default=2.5)
    parser.add_argument("--finalist-sites", type=int, default=50)
    parser.add_argument("--refinement-sites", type=int, default=20)
    parser.add_argument("--weight-access", type=float, default=0.30)
    parser.add_argument("--weight-capacity", type=float, default=0.25)
    parser.add_argument("--weight-vulnerability", type=float, default=0.15)
    parser.add_argument("--weight-configuration-fit", type=float, default=0.20)
    parser.add_argument("--weight-cost-efficiency", type=float, default=0.10)
    args = parser.parse_args()

    cfg = Stage7Config(
        target_beds_per_1000=args.target_beds_per_1000,
        finalist_unique_sites=args.finalist_sites,
        refinement_unique_sites=args.refinement_sites,
        weight_access=args.weight_access,
        weight_capacity=args.weight_capacity,
        weight_vulnerability=args.weight_vulnerability,
        weight_configuration_fit=args.weight_configuration_fit,
        weight_cost_efficiency=args.weight_cost_efficiency,
    )
    run_stage7(ROOT, cfg, stage6_run=args.stage6_run, states=args.states)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
