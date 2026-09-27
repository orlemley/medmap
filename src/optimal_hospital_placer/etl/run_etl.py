"""Run the complete Stage 1-8 hospital-placement pipeline.

Defaults reproduce the latest large successful run: all states, about 17k
Stage 6A shortlist tracts, two candidates per tract, 3k Stage 7 finalists,
and all Stage 7 top sites carried into Stage 8. Size settings are overridable.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PureWindowsPath
import subprocess
import sys
from typing import Any

ETL = Path(__file__).resolve().parent
ROOT = ETL.parents[2]
REQUIREMENTS = [
    ETL / "stage1/requirements.txt",
    ETL / "stage2/requirements.txt",
    ETL / "stage3/requirements.txt",
    ETL / "acs/requirements.txt",
    ETL / "stage5/requirements.txt",
    ETL / "stage6/requirements.txt",
    ETL / "stage7/requirements.txt",
    ETL / "stage8/requirements.txt",
]
STAGE1_SOURCES = ["ACS", "AHRF", "CMSFacilities", "CMSHospital", "HPSA", "MUAP",
                  "PLACES", "RUCA", "SVI"]
CACHE_PATH = ROOT / "data/etl/stage_cache.json"
REQUIRED_OUTPUTS = {
    "stage1": ["tables.json", "inventory.json"],
    "stage2": ["tables.json", "source_inventory.json"],
    "stage3": ["tracts.parquet", "counties.parquet", "facilities.parquet"],
    "stage4": ["tracts.parquet", "counties.parquet", "facilities.parquet"],
    "stage5": ["tract_features.parquet", "county_features.parquet", "facilities.parquet"],
    "stage6a": ["screened_tracts.parquet", "shortlisted_tracts.parquet"],
    "stage6": ["candidate_sites.parquet", "candidate_site_features.parquet", "existing_access.parquet"],
    "stage7": ["candidate_hospitals.parquet", "top_sites.parquet", "finalists.parquet"],
    "stage8": ["final_candidates.parquet", "service_recommendations.parquet", "travel_access_summary.parquet"],
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")


def portable_path(path: Path) -> str:
    """Store repository-owned paths without embedding one developer's checkout."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def resolve_run_reference(value: Any, pointer: Path) -> Path:
    """Resolve relative refs and recover old Windows refs copied to another host."""
    raw = str(value)
    declared = Path(raw)
    candidates = [declared] if declared.is_absolute() else [ROOT / declared]
    run_id = PureWindowsPath(raw).name if "\\" in raw else declared.name
    candidates.append(pointer.parent / "runs" / run_id)
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    raise FileNotFoundError(
        f"Published run does not exist for {pointer}: {raw!r}; "
        f"also tried {pointer.parent / 'runs' / run_id}"
    )


def portable_argument(value: Any) -> str:
    return portable_path(value) if isinstance(value, Path) else str(value)


def portable_value(value: Any) -> Any:
    if isinstance(value, Path):
        return portable_path(value)
    if isinstance(value, dict):
        return {key: portable_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [portable_value(item) for item in value]
    return value


def normalize_operational_pointers() -> None:
    """Migrate copied/local latest-success pointers away from checkout-specific paths."""
    data_root = ROOT / "data"
    if not data_root.is_dir():
        return
    for pointer in data_root.rglob("latest_success.json"):
        try:
            published = read_json(pointer)
            if "run_directory" not in published:
                continue
            run = resolve_run_reference(published["run_directory"], pointer)
            reference = portable_path(run)
            if published["run_directory"] != reference:
                published["run_directory"] = reference
                write_json(pointer, published)
        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
            # The owning stage will provide the actionable validation error if
            # this pointer is selected. Do not rewrite an unresolved reference.
            continue


def digest_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def code_digest(path: Path) -> str:
    digest = hashlib.sha256()
    files = [path] if path.is_file() else sorted(path.rglob("*.py"))
    for file in files:
        digest.update(file.relative_to(ETL).as_posix().encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()


def raw_snapshot() -> list[tuple[str, int, int]]:
    raw = ROOT / "data/raw"
    snapshot = []
    for source in STAGE1_SOURCES:
        folder = raw / source
        if not folder.is_dir():
            raise FileNotFoundError(f"Missing raw source directory: {folder}")
        files = [p for p in folder.rglob("*") if p.is_file() and not p.name.endswith(".part")]
        if not files:
            raise FileNotFoundError(f"Raw source directory has no inputs: {folder}")
        for file in sorted(files):
            stat = file.stat()
            snapshot.append((file.relative_to(raw).as_posix(), stat.st_size, stat.st_mtime_ns))
    return snapshot


def boundary_identity(directory: Path) -> Any:
    manifest = directory / "manifest.json"
    return read_json(manifest) if manifest.is_file() else None


def install_dependencies(force: bool = False) -> None:
    """Resolve every stage's declared requirements into this interpreter."""
    missing = [path for path in REQUIREMENTS if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing ETL requirement files: {missing}")
    pip_check = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if pip_check.returncode:
        print("pip is missing; bootstrapping it with ensurepip", flush=True)
        subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"], check=True)
    identity = digest_json({str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in REQUIREMENTS})
    marker = ROOT / "data/etl/dependencies.json"
    python_identity = {"version": sys.version, "executable": Path(sys.executable).name}
    if not force and marker.is_file():
        cached = read_json(marker)
        check = subprocess.run([sys.executable, "-m", "pip", "check"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if cached.get("identity") == identity and cached.get("python") == python_identity and check.returncode == 0:
            print("\n=== Python dependencies already satisfied (cached) ===", flush=True)
            return
    command = [sys.executable, "-m", "pip", "install"]
    for path in REQUIREMENTS:
        command.extend(["--requirement", str(path)])
    print("\n=== Preparing Python dependencies ===", flush=True)
    print("Command:", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, check=True)
    write_json(marker, {"identity": identity, "python": python_identity,
                        "completed_utc": datetime.now(timezone.utc).isoformat()})


def completed_run(stage_key: str, run: Path) -> tuple[bool, dict[str, Any]]:
    for name in ("manifest.json", "run.json"):
        path = run / name
        if path.is_file():
            report = read_json(path)
            complete = report.get("status") in {"complete", "complete_with_review_items"}
            outputs_exist = all((run / name).is_file() for name in REQUIRED_OUTPUTS[stage_key])
            return complete and outputs_exist, report
    return False, {}


def run_cached_stage(stage_key: str, label: str, script: Path, arguments: list[Any], pointer: Path,
                     cache: dict[str, Any], force: set[str], extra_identity: Any = None) -> Path:
    identity = digest_json({
        "stage": stage_key,
        "arguments": [portable_argument(value) for value in arguments],
        "code": code_digest(script.parent),
        "extra": extra_identity,
    })
    record = cache.get(stage_key, {})
    try:
        cached_run = resolve_run_reference(record["run_directory"], pointer)
    except (KeyError, FileNotFoundError):
        cached_run = ROOT / "__missing__"
    valid, report = completed_run(stage_key, cached_run) if cached_run.is_dir() else (False, {})
    if stage_key not in force and "all" not in force and record.get("identity") == identity and valid:
        print(f"\n=== {label} ===", flush=True)
        print(f"Using cached completed run: {cached_run}", flush=True)
        write_json(pointer, {**report, "run_directory": portable_path(cached_run)})
        return cached_run.resolve()
    run = run_publishing_stage(label, script, arguments, pointer)
    cache[stage_key] = {"identity": identity, "run_directory": portable_path(run),
                        "completed_utc": datetime.now(timezone.utc).isoformat()}
    write_json(CACHE_PATH, cache)
    return run


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
    run = resolve_run_reference(published["run_directory"], pointer)
    published["run_directory"] = portable_path(run)
    write_json(pointer, published)
    return run


def run_step(label: str, script: Path, arguments: list[Any]) -> None:
    """Run a required preparation step that does not publish a stage pointer."""
    command = [sys.executable, "-u", str(script), *map(str, arguments)]
    print(f"\n=== {label} ===", flush=True)
    print("Command:", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, check=True)


def require_count(run: Path, field_path: tuple[str, ...], minimum: int, label: str) -> None:
    """Reject a successful-looking nationwide stage that unexpectedly collapsed."""
    value: Any = read_json(run / "manifest.json")
    for field in field_path:
        value = value[field]
    if int(value) < minimum:
        raise RuntimeError(f"{label} produced only {int(value):,} rows; expected at least {minimum:,}")


def require_geocoded_hospitals(stage3: Path) -> None:
    """Enforce the Stage 3 contract required by downstream access modeling."""
    quality_path = stage3 / "quality_report.json"
    if not quality_path.is_file():
        raise RuntimeError(f"Stage 3 did not publish {quality_path}")
    geocoding = read_json(quality_path).get("facility_geocoding", {})
    located = int(geocoding.get("hospitals_located", 0) or 0)
    unlocated = int(geocoding.get("hospitals_unlocated", 0) or 0)
    if located < 1:
        raise RuntimeError(
            "Stage 3 produced zero located hospitals, so Stage 6 cannot compute its baseline. "
            "Geocoding is enabled by default; if --no-geocode was intentional, populate the "
            "geocode cache first. Completed upstream stages remain cached. "
            f"Stage 3 reported {located:,} located and {unlocated:,} unlocated hospitals."
        )
    print(f"Stage 3 location check: {located:,} hospitals located; {unlocated:,} unlocated.", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--geocode", action=argparse.BooleanOptionalAction, default=True,
        help="Fetch missing Census/OSM hospital geocodes (default); --no-geocode uses cache only",
    )
    parser.add_argument("--states", nargs="+", help="State FIPS codes; default is all states and DC")
    parser.add_argument("--boundary-dir", type=Path, default=ROOT / "data/reference/tiger2023")
    parser.add_argument("--geocode-cache", type=Path, default=ROOT / "data/reference/geocode_cache")
    parser.add_argument("--skip-acs-download", action="store_true",
                        help="Require existing ACS downloads instead of downloading missing files")
    parser.add_argument("--skip-boundary-download", action="store_true",
                        help="Require cached TIGER 2023 boundary ZIPs instead of downloading missing files")
    parser.add_argument("--skip-dependency-install", action="store_true",
                        help="Do not run pip; require the current interpreter to be pre-provisioned")
    parser.add_argument("--force-dependency-install", action="store_true",
                        help="Run pip even when the requirements checkpoint is valid")
    parser.add_argument("--no-stage-cache", action="store_true",
                        help="Rebuild every stage instead of reusing matching completed runs")
    parser.add_argument("--force-stage", action="append", default=[],
                        choices=["all", "stage1", "stage2", "stage3", "stage4", "stage5",
                                 "stage6a", "stage6", "stage7", "stage8"],
                        help="Rebuild this stage; downstream cache identities then change")
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
    normalize_operational_pointers()
    pipeline_started = datetime.now(timezone.utc).isoformat()
    runs: dict[str, str] = {}
    cache = read_json(CACHE_PATH) if CACHE_PATH.is_file() else {}
    force = set(args.force_stage)
    if args.no_stage_cache:
        force.add("all")
    stage3_args: list[Any] = ["--boundary-dir", args.boundary_dir.resolve(),
                              "--geocode-cache", args.geocode_cache.resolve()]
    if args.geocode:
        stage3_args.append("--geocode")
    if args.states:
        stage3_args.extend(["--states", *args.states])
    states_args: list[Any] = ["--states", *args.states] if args.states else []

    try:
        if not args.skip_dependency_install:
            install_dependencies(force=args.force_dependency_install)
        stage1_args: list[Any] = ["--sources", *STAGE1_SOURCES]
        stage1 = run_cached_stage("stage1", "Stage 1 of 8: raw staging", ETL / "stage1/run_stage1.py",
                                  stage1_args, ROOT / "data/stage1/latest_success.json", cache, force,
                                  raw_snapshot())
        runs["stage1"] = portable_path(stage1)
        stage2 = run_cached_stage("stage2", "Stage 2 of 8: normalization", ETL / "stage2/run_stage2.py",
                                  ["--stage1-run", stage1], ROOT / "data/stage2/latest_success.json",
                                  cache, force)
        runs["stage2"] = portable_path(stage2)
        if not args.skip_boundary_download:
            boundary_args: list[Any] = ["--directory", args.boundary_dir.resolve()]
            if args.states:
                boundary_args.extend(["--states", *args.states])
            run_step("Preparing Census TIGER 2023 boundaries", ETL / "stage3/prepare_boundaries.py",
                     boundary_args)
        stage3 = run_cached_stage("stage3", "Stage 3 of 8: registry and geocoding",
                                  ETL / "stage3/run_stage3.py", ["--stage2-run", stage2, *stage3_args],
                                  ROOT / "data/stage3/latest_success.json", cache, force,
                                  boundary_identity(args.boundary_dir.resolve()))
        runs["stage3"] = portable_path(stage3)
        require_geocoded_hospitals(stage3)

        stage4_args: list[Any] = ["--stage3-run", stage3]
        if args.skip_acs_download:
            stage4_args.append("--skip-download")
        stage4 = run_cached_stage("stage4", "Stage 4 of 8: ACS enrichment", ETL / "acs/run_acs.py",
                                  stage4_args, ROOT / "data/stage4/latest_success.json", cache, force)
        runs["stage4"] = portable_path(stage4)
        stage5 = run_cached_stage("stage5", "Stage 5 of 8: screening features",
                                  ETL / "stage5/run_stage5.py", ["--stage4-run", stage4],
                                  ROOT / "data/stage5/latest_success.json", cache, force)
        runs["stage5"] = portable_path(stage5)

        stage6a_args: list[Any] = [
            "--stage5-run", stage5, "--min-population", args.min_population,
            "--min-screening-score", args.min_screening_score,
            "--min-nearest-hospital-miles", args.min_nearest_hospital_miles,
            "--top-n-per-state", args.top_n_per_state,
            "--top-fraction-per-state", args.top_fraction_per_state,
            "--severe-existing-drive-minutes", args.severe_existing_drive_minutes,
            "--severe-min-population", args.severe_min_population,
        ]
        stage6a = run_cached_stage("stage6a", "Stage 6A of 8: large-sample screening",
                                   ETL / "stage6/run_stage6a.py", stage6a_args,
                                   ROOT / "data/stage6a/latest_success.json", cache, force)
        runs["stage6a"] = portable_path(stage6a)
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
        stage6 = run_cached_stage("stage6", "Stage 6 of 8: candidate access",
                                  ETL / "stage6/run_stage6_fast.py", stage6_args,
                                  ROOT / "data/stage6/latest_success.json", cache, force)
        runs["stage6"] = portable_path(stage6)
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
        stage7 = run_cached_stage("stage7", "Stage 7 of 8: configuration optimization",
                                  ETL / "stage7/run_stage7.py", stage7_args,
                                  ROOT / "data/stage7/latest_success.json", cache, force)
        runs["stage7"] = portable_path(stage7)

        stage8_args: list[Any] = [
            "--stage7-run", stage7, "--source", args.stage8_source,
            "--max-sites", args.stage8_max_sites, "--weight-stage7", args.weight_stage7,
            "--weight-drive-access", args.weight_drive_access,
            "--weight-service-fit", args.weight_service_fit,
            "--service-threshold-adjustment", args.service_threshold_adjustment,
            "--max-recommended-services", args.max_recommended_services, *states_args,
        ]
        stage8 = run_cached_stage("stage8", "Stage 8 of 8: final enrichment",
                                  ETL / "stage8/run_stage8.py", stage8_args,
                                  ROOT / "data/stage8/latest_success.json", cache, force)
        runs["stage8"] = portable_path(stage8)
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
        "arguments": portable_value(vars(args)), "runs": runs, "final_run": runs["stage8"],
    })
    print(f"\nETL complete. Stage 8 output: {runs['stage8']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
