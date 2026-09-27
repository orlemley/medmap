from __future__ import annotations

import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
SRC_ROOT = HERE.parents[2]
PROJECT_ROOT = HERE.parents[3]

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from optimal_hospital_placer.etl.stage8.config import Stage8Config
from optimal_hospital_placer.etl.stage8.pipeline import run_stage8


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage 8 final candidate refinement: services/departments + drive-time/distance features"
    )
    parser.add_argument("--stage7-run", type=Path)
    parser.add_argument("--source", choices=["finalists", "top-sites"], default="finalists")
    parser.add_argument("--states", nargs="+")
    parser.add_argument("--max-sites", type=int, default=0, help="0 = all source sites")

    parser.add_argument("--weight-stage7", type=float, default=0.55)
    parser.add_argument("--weight-drive-access", type=float, default=0.25)
    parser.add_argument("--weight-service-fit", type=float, default=0.20)

    parser.add_argument("--service-threshold-adjustment", type=float, default=0.0)
    parser.add_argument("--max-recommended-services", type=int, default=8)

    args = parser.parse_args()
    cfg = Stage8Config(
        source_table=args.source,
        max_sites=args.max_sites,
        weight_stage7=args.weight_stage7,
        weight_drive_access=args.weight_drive_access,
        weight_service_fit=args.weight_service_fit,
        service_threshold_adjustment=args.service_threshold_adjustment,
        max_recommended_services=args.max_recommended_services,
    )

    run_stage8(
        PROJECT_ROOT,
        cfg,
        stage7_run=args.stage7_run,
        states=args.states,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
