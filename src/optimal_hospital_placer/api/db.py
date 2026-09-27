from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path, PureWindowsPath
from typing import Any

import duckdb


def project_root() -> Path:
    override = os.environ.get("OHP_PROJECT_ROOT")
    if override:
        return Path(override).resolve()
    # .../src/optimal_hospital_placer/api/db.py -> repo root
    return Path(__file__).resolve().parents[3]


def _read_pointer(stage: str) -> tuple[dict[str, Any], Path]:
    root = project_root()
    pointer = root / "data" / stage / "latest_success.json"
    if not pointer.exists():
        raise RuntimeError(
            f"{stage} is unavailable. Expected {pointer}. Run {stage} before starting the API."
        )
    info = json.loads(pointer.read_text(encoding="utf-8-sig"))
    if info.get("status") != "complete":
        raise RuntimeError(f"{pointer} does not describe a complete run")
    declared_run = Path(info["run_directory"])
    if declared_run.is_dir():
        run = declared_run.resolve()
    else:
        # ETL snapshots are often produced on Windows, while the API container
        # runs Linux. A pointer such as C:\\repo\\data\\stage8\\runs\\<id>
        # is not meaningful in Linux, but its run ID is portable. Resolve that
        # ID against the mounted stage directory instead.
        raw_run = str(info["run_directory"])
        run_id = PureWindowsPath(raw_run).name if "\\" in raw_run else Path(raw_run).name
        run = (pointer.parent / "runs" / run_id).resolve()
    if not run.is_dir():
        raise RuntimeError(
            f"{stage} run directory does not exist: {run} "
            f"(snapshot declared {info['run_directory']!r})"
        )
    return info, run


@lru_cache(maxsize=1)
def paths() -> dict[str, Any]:
    stage8_info, stage8 = _read_pointer("stage8")

    result: dict[str, Any] = {
        "stage8_run": stage8,
        "stage8_run_id": stage8.name,
        "stage8_info": stage8_info,
        "final_candidates": stage8 / "final_candidates.parquet",
        "services": stage8 / "service_recommendations.parquet",
        "travel": stage8 / "travel_access_summary.parquet",
        "routing_queue": stage8 / "precise_routing_queue.parquet",
        "stage8_summary": stage8 / "summary.json",
        "stage8_assumptions": stage8 / "assumptions.json",
    }

    # Stage 7 is useful for alternate configurations at a selected physical site.
    try:
        stage7_info, stage7 = _read_pointer("stage7")
        result.update({
            "stage7_run": stage7,
            "stage7_run_id": stage7.name,
            "stage7_info": stage7_info,
            "configurations": stage7 / "candidate_hospitals.parquet",
            "stage7_summary": stage7 / "summary.json",
        })
    except Exception:
        result["stage7_run"] = None

    # Stage 5 remains useful for existing hospitals and population heatmap context.
    try:
        stage5_info, stage5 = _read_pointer("stage5")
        result.update({
            "stage5_run": stage5,
            "stage5_run_id": stage5.name,
            "stage5_info": stage5_info,
            "tracts": stage5 / "tract_features.parquet",
            "counties": stage5 / "county_features.parquet",
            "facilities": stage5 / "facilities.parquet",
            "stage5_summary": stage5 / "summary.json",
        })
    except Exception:
        result["stage5_run"] = None

    required = ["final_candidates", "services", "travel"]
    missing = [str(result[k]) for k in required if not Path(result[k]).exists()]
    if missing:
        raise RuntimeError(f"Stage 8 snapshot is incomplete. Missing: {missing}")
    return result


def _q(path: Path) -> str:
    return "'" + path.as_posix().replace("'", "''") + "'"


def connect() -> duckdb.DuckDBPyConnection:
    p = paths()
    con = duckdb.connect(database=":memory:")
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA enable_object_cache=true")
    con.execute(f"CREATE VIEW final_candidates AS SELECT * FROM read_parquet({_q(p['final_candidates'])})")
    con.execute(f"CREATE VIEW service_recommendations AS SELECT * FROM read_parquet({_q(p['services'])})")
    con.execute(f"CREATE VIEW travel_access AS SELECT * FROM read_parquet({_q(p['travel'])})")

    if p.get("routing_queue") and Path(p["routing_queue"]).exists():
        con.execute(f"CREATE VIEW precise_routing_queue AS SELECT * FROM read_parquet({_q(p['routing_queue'])})")

    if p.get("configurations") and Path(p["configurations"]).exists():
        con.execute(f"CREATE VIEW candidate_hospitals AS SELECT * FROM read_parquet({_q(p['configurations'])})")

    if p.get("tracts") and Path(p["tracts"]).exists():
        con.execute(f"CREATE VIEW tracts AS SELECT * FROM read_parquet({_q(p['tracts'])})")
    if p.get("counties") and Path(p["counties"]).exists():
        con.execute(f"CREATE VIEW counties AS SELECT * FROM read_parquet({_q(p['counties'])})")
    if p.get("facilities") and Path(p["facilities"]).exists():
        con.execute(f"CREATE VIEW facilities AS SELECT * FROM read_parquet({_q(p['facilities'])})")
    return con


def clear_path_cache() -> None:
    paths.cache_clear()
