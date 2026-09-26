from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def stage5_paths() -> dict[str, Path | str]:
    pointer = ROOT / "data" / "stage5" / "latest_success.json"
    if not pointer.exists():
        raise RuntimeError(
            "Stage 5 is not available. Expected data/stage5/latest_success.json. "
            "Run Stage 5 before starting the API."
        )

    info = json.loads(pointer.read_text(encoding="utf-8-sig"))
    run = Path(info["run_directory"]).resolve()
    if not run.is_dir():
        raise RuntimeError(f"Stage 5 run directory does not exist: {run}")

    paths = {
        "run": run,
        "run_id": run.name,
        "tracts": run / "tract_features.parquet",
        "counties": run / "county_features.parquet",
        "facilities": run / "facilities.parquet",
        "summary": run / "summary.json",
        "feature_dictionary": run / "feature_dictionary.json",
    }
    missing = [str(p) for k, p in paths.items() if isinstance(p, Path) and k not in {"run"} and not p.exists()]
    if missing:
        raise RuntimeError(f"Stage 5 snapshot is incomplete. Missing: {missing}")
    return paths


def connect() -> duckdb.DuckDBPyConnection:
    """Create a request-scoped read-only analytical connection.

    Data remains in Parquet; DuckDB is the query engine. Views are local to the
    connection, which keeps concurrent FastAPI requests independent.
    """
    p = stage5_paths()
    con = duckdb.connect(database=":memory:")
    con.execute("PRAGMA threads=4")
    con.execute(
        f"CREATE VIEW tracts AS SELECT * FROM read_parquet('{Path(p['tracts']).as_posix()}')"
    )
    con.execute(
        f"CREATE VIEW counties AS SELECT * FROM read_parquet('{Path(p['counties']).as_posix()}')"
    )
    con.execute(
        f"CREATE VIEW facilities AS SELECT * FROM read_parquet('{Path(p['facilities']).as_posix()}')"
    )
    return con
