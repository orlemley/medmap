from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException

from .states import FIPS_TO_ABBR, STATE_NAMES


def scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def record(row: dict[str, Any]) -> dict[str, Any]:
    return {k: scalar(v) for k, v in row.items()}


def records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [record(r) for r in df.to_dict(orient="records")]


def parse_bbox(value: str | None) -> tuple[float, float, float, float] | None:
    if value is None or value == "":
        return None
    try:
        west, south, east, north = [float(v.strip()) for v in value.split(",")]
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={"code":"invalid_bbox","message":"bbox must be west,south,east,north"},
        ) from exc
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= 90 and -90 <= north <= 90):
        raise HTTPException(status_code=400, detail={"code":"invalid_bbox","message":"bbox coordinates are outside valid ranges"})
    if west >= east or south >= north:
        raise HTTPException(status_code=400, detail={"code":"invalid_bbox","message":"bbox must satisfy west < east and south < north"})
    return west, south, east, north


def feature_collection(features: list[dict[str, Any]], **meta: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"type":"FeatureCollection","features":features}
    if meta:
        result["meta"] = {k: scalar(v) for k, v in meta.items()}
    return result


def candidate_feature(row: dict[str, Any], rank: int | None = None, score: float | None = None) -> dict[str, Any]:
    props = record(row.copy())
    lat = scalar(props.pop("latitude", None))
    lon = scalar(props.pop("longitude", None))
    site_id = str(props.get("site_id"))
    if rank is not None:
        props["rank"] = rank
    if score is not None:
        props["score"] = score
    elif "stage8_score" in props:
        props["score"] = props["stage8_score"]

    state_fips = str(props.get("state_fips") or "").zfill(2)
    abbr = FIPS_TO_ABBR.get(state_fips)
    if abbr:
        props["state"] = abbr
        props["state_name"] = STATE_NAMES.get(abbr)

    # Backwards-compatible aliases for the current React prototype.
    props.setdefault("tract_id", props.get("source_tract_geoid"))
    county = (
        props.get("county_name") or props.get("source_county_name") or
        props.get("ruca_countyname23") or props.get("ruca_countyname20") or ""
    )
    if isinstance(county, str) and county.lower().endswith(" county"):
        county = county[:-7]
    props.setdefault("county", county)
    props.setdefault("uncovered_population", props.get("newly_accessible_population_30min") or 0)
    props.setdefault("nearest_hospital_mi", props.get("nearest_existing_hospital_estimated_drive_miles"))
    mean_saved = props.get("population_weighted_mean_minutes_saved")
    speed = props.get("stage8_effective_speed_mph")
    if props.get("avg_distance_reduction_mi") is None and mean_saved is not None and speed is not None:
        try:
            props["avg_distance_reduction_mi"] = round(float(mean_saved) * float(speed) / 60.0, 1)
        except Exception:
            props["avg_distance_reduction_mi"] = None
    props.setdefault("tract_population", props.get("source_population") or props.get("population_within_15min"))
    props.setdefault("density_per_sq_mi", props.get("source_population_density_per_sq_mi"))
    props.setdefault("density_imputed", False)
    props.setdefault("in_mua", bool(props.get("source_in_mua") or props.get("in_mua") or False))
    props.setdefault("in_hpsa", bool(props.get("source_in_hpsa") or props.get("in_hpsa") or False))

    return {
        "type":"Feature",
        "id":site_id,
        "geometry":{"type":"Point","coordinates":[lon, lat]},
        "properties":props,
    }


def state_fields(state_fips: str) -> dict[str, Any]:
    fips = str(state_fips).zfill(2)
    abbr = FIPS_TO_ABBR.get(fips, fips)
    return {"state_fips": fips, "state": abbr, "name": STATE_NAMES.get(abbr, abbr)}
