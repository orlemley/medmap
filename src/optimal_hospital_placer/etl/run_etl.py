"""Run the complete Stage 1-8 hospital-placement pipeline.

Defaults reproduce the latest large successful run: all states, about 17k
Stage 6A shortlist tracts, two candidates per tract, 3k Stage 7 finalists,
and all Stage 7 top sites carried into Stage 8. Size settings are overridable.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

ETL = Path(__file__).resolve().parent
ROOT = ETL.parents[2]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")


def run_publishing_stage(label: str, script: Path, arguments: list[Any], pointer: Path) -> Path:
    """Run a stage and require a new, successful published-run pointer."""
    previous = pointer.read_bytes() if pointer.exists() else None
    command = [sys.executable, "-u", str(script), *map(str, arguments)]
    print(f"\n=== {label} ===", flush=True)
    print("Command:", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, check=True)
    if not pointer.exists():
        raise RuntimeError(f"{label} did not publish {pointer}")
    current = pointer.read_bytes()
    if current == previous:
        raise RuntimeError(f"{label} did not publish a new successful run")
    published = read_json(pointer)
    if published.get("status") not in {None, "complete", "complete_with_review_items"}:
        raise RuntimeError(f"{label} published non-success status: {published.get('status')}")
    run = Path(published["run_directory"]).resolve()
    if not run.is_dir():
        raise RuntimeError(f"{label} published a missing run directory: {run}")
    return run


def require_count(run: Path, field_path: tuple[str, ...], minimum: int, label: str) -> None:
    """Reject a successful-looking nationwide stage that unexpectedly collapsed."""
    value: Any = read_json(run / "manifest.json")
    for field in field_path:
        value = value[field]
    if int(value) < minimum:
        raise RuntimeError(f"{label} produced only {int(value):,} rows; expected at least {minimum:,}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geocode", action="store_true",
                        help="Allow Stage 3 to request missing Census/OSM geocodes; otherwise use caches only")
    parser.add_argument("--states", nargs="+", help="State FIPS codes; default is all states and DC")
    parser.add_argument("--boundary-dir", type=Path, default=ROOT / "data/reference/tiger2023")
    parser.add_argument("--geocode-cache", type=Path, default=ROOT / "data/reference/geocode_cache")
    parser.add_argument("--skip-acs-download", action="store_true",
                        help="Require existing ACS downloads instead of downloading missing files")
    parser.add_argument("--allow-small-output", action="store_true",
                        help="Disable nationwide sample-size guards (state-restricted runs disable them automatically)")

    screening = parser.add_argument_group("Stage 6A large-sample screening")
    screening.add_argument("--min-population", type=int, default=500)
    screening.add_argument("--min-screening-score", type=float, default=0.30)
    screening.add_argument("--min-nearest-hospital-miles", type=float, default=7.0)
    screening.add_argument("--top-n-per-state", type=int, default=300)
    screening.add_argument("--top-fraction-per-state", type=float, default=0.15)
    screening.add_argument("--severe-existing-drive-minutes", type=float, default=30.0)
    screening.add_argument("--severe-min-population", type=int, default=750)

    candidates = parser.add_argument_group("Stage 6 candidate generation")
    candidates.add_argument("--candidates-per-tract", type=int, default=2)
    candidates.add_argument("--demand-prefilter-miles", type=float, default=75.0)
    candidates.add_argument("--hospital-prefilter-miles", type=float, default=125.0)
    candidates.add_argument("--baseline-nearest-hospitals-k", type=int, default=12)
    candidates.add_argument("--urban-detour-factor", type=float, default=1.20)
    candidates.add_argument("--rural-detour-factor", type=float, default=1.34)
    candidates.add_argument("--urban-effective-mph", type=float, default=29.0)
    candidates.add_argument("--rural-effective-mph", type=float, default=52.0)

    stage7 = parser.add_argument_group("Stage 7 configuration optimization")
    stage7.add_argument("--target-beds-per-1000", type=float, default=2.5)
    stage7.add_argument("--finalist-sites", type=int, default=3000)
    stage7.add_argument("--refinement-sites", type=int, default=100)
    stage7.add_argument("--weight-access", type=float, default=0.30)
    stage7.add_argument("--weight-capacity", type=float, default=0.25)
    stage7.add_argument("--weight-vulnerability", type=float, default=0.15)
    stage7.add_argument("--weight-configuration-fit", type=float, default=0.20)
    stage7.add_argument("--weight-cost-efficiency", type=float, default=0.10)

    stage8 = parser.add_argument_group("Stage 8 final enrichment")
    stage8.add_argument("--stage8-source", choices=["finalists", "top-sites"], default="top-sites",
                        help="top-sites preserves the full Stage 6 pool; finalists limits it")
    stage8.add_argument("--stage8-max-sites", type=int, default=0, help="0 keeps every source site")
    stage8.add_argument("--weight-stage7", type=float, default=0.55)
    stage8.add_argument("--weight-drive-access", type=float, default=0.25)
    stage8.add_argument("--weight-service-fit", type=float, default=0.20)
    stage8.add_argument("--service-threshold-adjustment", type=float, default=0.0)
    stage8.add_argument("--max-recommended-services", type=int, default=8)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    pipeline_started = datetime.now(timezone.utc).isoformat()
    runs: dict[str, str] = {}
    stage3_args: list[Any] = ["--boundary-dir", args.boundary_dir.resolve(),
                              "--geocode-cache", args.geocode_cache.resolve()]
    if args.geocode:
        stage3_args.append("--geocode")
    if args.states:
        stage3_args.extend(["--states", *args.states])
    states_args: list[Any] = ["--states", *args.states] if args.states else []

    try:
        stage1 = run_publishing_stage("Stage 1 of 8: raw staging", ETL / "stage1/run_stage1.py", [],
                                      ROOT / "data/stage1/latest_success.json")
        runs["stage1"] = str(stage1)
        stage2 = run_publishing_stage("Stage 2 of 8: normalization", ETL / "stage2/run_stage2.py",
                                      ["--stage1-run", stage1], ROOT / "data/stage2/latest_success.json")
        runs["stage2"] = str(stage2)
        stage3 = run_publishing_stage("Stage 3 of 8: registry and geocoding", ETL / "stage3/run_stage3.py",
                                      ["--stage2-run", stage2, *stage3_args], ROOT / "data/stage3/latest_success.json")
        runs["stage3"] = str(stage3)

        stage4_args: list[Any] = ["--stage3-run", stage3]
        if args.skip_acs_download:
            stage4_args.append("--skip-download")
        stage4 = run_publishing_stage("Stage 4 of 8: ACS enrichment", ETL / "acs/run_acs.py", stage4_args,
                                      ROOT / "data/stage4/latest_success.json")
        runs["stage4"] = str(stage4)
        stage5 = run_publishing_stage("Stage 5 of 8: screening features", ETL / "stage5/run_stage5.py",
                                      ["--stage4-run", stage4], ROOT / "data/stage5/latest_success.json")
        runs["stage5"] = str(stage5)

        stage6a_args: list[Any] = [
            "--stage5-run", stage5, "--min-population", args.min_population,
            "--min-screening-score", args.min_screening_score,
            "--min-nearest-hospital-miles", args.min_nearest_hospital_miles,
            "--top-n-per-state", args.top_n_per_state,
            "--top-fraction-per-state", args.top_fraction_per_state,
            "--severe-existing-drive-minutes", args.severe_existing_drive_minutes,
            "--severe-min-population", args.severe_min_population,
        ]
        stage6a = run_publishing_stage("Stage 6A of 8: large-sample screening", ETL / "stage6/run_stage6a.py",
                                       stage6a_args, ROOT / "data/stage6a/latest_success.json")
        runs["stage6a"] = str(stage6a)
        if not args.states and not args.allow_small_output:
            require_count(stage6a, ("summary", "shortlisted_tracts"), 10_000, "Stage 6A")

        stage6_args: list[Any] = [
            "--stage5-run", stage5, "--stage6a-run", stage6a,
            "--candidates-per-tract", args.candidates_per_tract,
            "--demand-prefilter-miles", args.demand_prefilter_miles,
            "--hospital-prefilter-miles", args.hospital_prefilter_miles,
            "--baseline-nearest-hospitals-k", args.baseline_nearest_hospitals_k,
            "--urban-detour-factor", args.urban_detour_factor,
            "--rural-detour-factor", args.rural_detour_factor,
            "--urban-effective-mph", args.urban_effective_mph,
            "--rural-effective-mph", args.rural_effective_mph, *states_args,
        ]
        stage6 = run_publishing_stage("Stage 6 of 8: candidate access", ETL / "stage6/run_stage6_fast.py",
                                      stage6_args, ROOT / "data/stage6/latest_success.json")
        runs["stage6"] = str(stage6)
        if not args.states and not args.allow_small_output:
            require_count(stage6, ("summary", "candidate_sites"), 20_000, "Stage 6")

        stage7_args: list[Any] = [
            "--stage6-run", stage6, "--target-beds-per-1000", args.target_beds_per_1000,
            "--finalist-sites", args.finalist_sites, "--refinement-sites", args.refinement_sites,
            "--weight-access", args.weight_access, "--weight-capacity", args.weight_capacity,
            "--weight-vulnerability", args.weight_vulnerability,
            "--weight-configuration-fit", args.weight_configuration_fit,
            "--weight-cost-efficiency", args.weight_cost_efficiency, *states_args,
        ]
        stage7 = run_publishing_stage("Stage 7 of 8: configuration optimization", ETL / "stage7/run_stage7.py",
                                      stage7_args, ROOT / "data/stage7/latest_success.json")
        runs["stage7"] = str(stage7)

        stage8_args: list[Any] = [
            "--stage7-run", stage7, "--source", args.stage8_source,
            "--max-sites", args.stage8_max_sites, "--weight-stage7", args.weight_stage7,
            "--weight-drive-access", args.weight_drive_access,
            "--weight-service-fit", args.weight_service_fit,
            "--service-threshold-adjustment", args.service_threshold_adjustment,
            "--max-recommended-services", args.max_recommended_services, *states_args,
        ]
        stage8 = run_publishing_stage("Stage 8 of 8: final enrichment", ETL / "stage8/run_stage8.py",
                                      stage8_args, ROOT / "data/stage8/latest_success.json")
        runs["stage8"] = str(stage8)
        if not args.states and not args.allow_small_output:
            require_count(stage8, ("source_rows",), 20_000, "Stage 8")
    except subprocess.CalledProcessError as exc:
        print(f"\nETL stopped: a stage failed (exit code {exc.returncode}).", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"\nETL stopped: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nETL interrupted. Completed snapshots remain intact.", file=sys.stderr)
        return 130

    write_json(ROOT / "data/etl/latest_success.json", {
        "status": "complete", "started_utc": pipeline_started,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "arguments": vars(args), "runs": runs, "final_run": runs["stage8"],
    })
    print(f"\nETL complete. Stage 8 output: {runs['stage8']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
