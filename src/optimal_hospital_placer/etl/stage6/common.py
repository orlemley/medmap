from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
from uuid import uuid4

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

EARTH_MILES = 3958.7613


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_dir(output_root: Path) -> Path:
    run = output_root / "runs" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    run.mkdir(parents=True, exist_ok=False)
    return run


def replace_directory_atomic(temp_dir: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = destination.with_name(destination.name + ".old")
    if backup.exists():
        shutil.rmtree(backup)
    if destination.exists():
        destination.rename(backup)
    temp_dir.rename(destination)
    if backup.exists():
        shutil.rmtree(backup)


def state_fips_from_geoid(series: pd.Series) -> pd.Series:
    return series.astype("string").str.zfill(11).str[:2]


def boolish(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series.dtype):
        return series.fillna(False).astype(bool)
    normalized = series.astype("string").str.strip().str.lower()
    return normalized.isin({"true", "1", "yes", "y", "t"})


def unit_xyz(latitudes, longitudes) -> np.ndarray:
    lat = np.radians(np.asarray(latitudes, dtype=float))
    lon = np.radians(np.asarray(longitudes, dtype=float))
    clat = np.cos(lat)
    return np.column_stack((clat * np.cos(lon), clat * np.sin(lon), np.sin(lat)))


def chord_radius(miles: float) -> float:
    angle = float(miles) / EARTH_MILES
    return 2.0 * math.sin(angle / 2.0)


def haversine_miles(lat1, lon1, lat2, lon2):
    lat1 = np.radians(np.asarray(lat1, dtype=float))
    lon1 = np.radians(np.asarray(lon1, dtype=float))
    lat2 = np.radians(np.asarray(lat2, dtype=float))
    lon2 = np.radians(np.asarray(lon2, dtype=float))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2 * EARTH_MILES * np.arcsin(np.minimum(1.0, np.sqrt(a)))


def indices_within_radius(source_lat, source_lon, target_lat, target_lon, miles: float):
    if len(target_lat) == 0 or len(source_lat) == 0:
        return [list() for _ in range(len(source_lat))]
    tree = cKDTree(unit_xyz(target_lat, target_lon))
    return tree.query_ball_point(unit_xyz(source_lat, source_lon), r=chord_radius(miles))


def subset_near_any(frame: pd.DataFrame, seeds: pd.DataFrame, radius_miles: float) -> pd.DataFrame:
    if frame.empty or seeds.empty:
        return frame.iloc[0:0].copy()
    seed_tree = cKDTree(unit_xyz(seeds["latitude"], seeds["longitude"]))
    distances, _ = seed_tree.query(unit_xyz(frame["latitude"], frame["longitude"]), k=1)
    return frame.loc[distances <= chord_radius(radius_miles)].copy()


def safe_numeric(frame: pd.DataFrame, column: str, default=np.nan) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").astype("float64")


def percentile_score(series: pd.Series, higher_is_more_need=True) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").astype(float)
    if not higher_is_more_need:
        s = -s
    return s.rank(method="average", pct=True, na_option="keep")
