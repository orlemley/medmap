"""Copy the active API snapshots into Docker's self-contained build context.

This exporter is deliberately non-destructive: it never writes under data/ and
never removes files. Re-running it updates pointer copies and copies the active
run into its run-id directory while leaving older packaged runs intact.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PureWindowsPath
import shutil
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DATA = ROOT / "data"
DESTINATION = ROOT / "docker" / "runtime-data"
STAGES = {
    "stage5": ("tract_features.parquet", "county_features.parquet", "facilities.parquet"),
    "stage7": ("candidate_hospitals.parquet", "top_sites.parquet", "finalists.parquet"),
    "stage8": ("final_candidates.parquet", "service_recommendations.parquet", "travel_access_summary.parquet"),
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def source_run(stage: str, pointer: Path, info: dict[str, Any]) -> Path:
    raw = str(info["run_directory"])
    declared = Path(raw)
    run_id = PureWindowsPath(raw).name if "\\" in raw else declared.name
    candidates = [declared if declared.is_absolute() else ROOT / declared,
                  pointer.parent / "runs" / run_id]
    for candidate in candidates:
        if candidate.is_dir():
            resolved = candidate.resolve()
            expected_parent = (SOURCE_DATA / stage / "runs").resolve()
            if expected_parent not in resolved.parents:
                raise RuntimeError(f"Refusing run outside {expected_parent}: {resolved}")
            return resolved
    raise FileNotFoundError(f"Cannot resolve active {stage} run {raw!r}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_source() -> list[tuple[str, Path, Path, dict[str, Any]]]:
    selected = []
    for stage, required in STAGES.items():
        pointer = SOURCE_DATA / stage / "latest_success.json"
        if not pointer.is_file():
            raise FileNotFoundError(f"Missing {pointer}")
        info = read_json(pointer)
        if info.get("status") != "complete":
            raise RuntimeError(f"{pointer} is not a completed snapshot")
        run = source_run(stage, pointer, info)
        missing = [name for name in required if not (run / name).is_file()]
        if missing:
            raise FileNotFoundError(f"{stage} is missing required files: {missing}")
        selected.append((stage, pointer, run, info))
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Validate the source snapshots without copying anything")
    args = parser.parse_args()
    selected = validate_source()

    total = sum(path.stat().st_size for _, _, run, _ in selected for path in run.rglob("*") if path.is_file())
    print(f"Validated Stage 5/7/8 runtime snapshots ({total / 1024**2:,.1f} MiB).")
    if args.check:
        return 0

    DESTINATION.mkdir(parents=True, exist_ok=True)
    package_files = []
    for stage, _, run, info in selected:
        destination_run = DESTINATION / stage / "runs" / run.name
        destination_run.mkdir(parents=True, exist_ok=True)
        print(f"Copying {stage} run {run.name}...")
        for source in run.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(run)
            destination = destination_run / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            package_files.append({
                "path": destination.relative_to(DESTINATION).as_posix(),
                "bytes": destination.stat().st_size,
                "sha256": sha256(destination),
            })
        packaged_pointer = dict(info)
        packaged_pointer["run_directory"] = f"data/{stage}/runs/{run.name}"
        pointer_destination = DESTINATION / stage / "latest_success.json"
        pointer_destination.parent.mkdir(parents=True, exist_ok=True)
        pointer_destination.write_text(json.dumps(packaged_pointer, indent=2, default=str), encoding="utf-8")

    manifest = {
        "status": "complete",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Generated copy for Docker; source data was not modified or removed.",
        "files": package_files,
    }
    (DESTINATION / "package_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"Docker runtime data prepared at {DESTINATION}")
    print("Source data was not modified or deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
