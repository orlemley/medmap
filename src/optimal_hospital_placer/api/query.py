from __future__ import annotations

import math
from typing import Any

from fastapi import HTTPException

from .states import normalize_state
from .utils import parse_bbox


ALLOWED_SERVICES = {
    "emergency","icu","general_surgery","maternity","cardiology","stroke",
    "behavioral_health","pediatrics","advanced_imaging","oncology","dialysis"
}


def candidate_where(
    *,
    state: str | None = None,
    bbox: str | None = None,
    min_score: float | None = None,
    min_beds: int | None = None,
    max_beds: int | None = None,
    services: list[str] | None = None,
    require_all_services: bool = False,
    routing_refined: bool | None = None,
    score_expression: str = "stage8_score",
) -> tuple[str, list[Any]]:
    clauses = ["latitude IS NOT NULL", "longitude IS NOT NULL"]
    params: list[Any] = []

    try:
        state_fips, _ = normalize_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code":"invalid_state","message":str(exc)}) from exc
    if state_fips:
        clauses.append("lpad(CAST(state_fips AS VARCHAR), 2, '0') = ?")
        params.append(state_fips)

    box = parse_bbox(bbox)
    if box:
        west, south, east, north = box
        clauses += ["longitude BETWEEN ? AND ?", "latitude BETWEEN ? AND ?"]
        params += [west, east, south, north]

    if min_score is not None:
        clauses.append(f"({score_expression}) >= ?")
        params.append(float(min_score))
    if min_beds is not None:
        clauses.append("coalesce(proposed_beds,0) >= ?")
        params.append(int(min_beds))
    if max_beds is not None:
        clauses.append("coalesce(proposed_beds,0) <= ?")
        params.append(int(max_beds))
    if routing_refined is not None:
        clauses.append("coalesce(routing_refined,false) = ?")
        params.append(bool(routing_refined))

    cleaned = []
    for service in services or []:
        key = service.strip().lower()
        if not key:
            continue
        if key not in ALLOWED_SERVICES:
            raise HTTPException(
                status_code=400,
                detail={"code":"unknown_service","message":f"Unknown service '{service}'","allowed":sorted(ALLOWED_SERVICES)},
            )
        cleaned.append(key)

    if cleaned:
        if require_all_services:
            for key in cleaned:
                clauses.append(f"coalesce(service_{key}_recommended,false)")
        else:
            clauses.append("(" + " OR ".join(f"coalesce(service_{key}_recommended,false)" for key in cleaned) + ")")

    return " AND ".join(clauses), params


def grid_cell_degrees(zoom: float | None) -> float:
    if zoom is None:
        return 0.0
    if zoom <= 4:
        return 3.0
    if zoom <= 5:
        return 2.0
    if zoom <= 6:
        return 1.25
    if zoom <= 7:
        return 0.75
    if zoom <= 8:
        return 0.40
    if zoom <= 9:
        return 0.20
    return 0.0


def default_limit_for_zoom(zoom: float | None) -> int:
    if zoom is None or zoom <= 4:
        return 50
    if zoom <= 6:
        return 100
    if zoom <= 8:
        return 175
    if zoom <= 10:
        return 300
    return 500


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance used only to spread already-ranked results."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * 3958.8 * math.asin(min(1.0, math.sqrt(a)))


def initial_separation_miles(
    limit: int,
    bbox: tuple[float, float, float, float] | None,
    state: str | None,
) -> float:
    """Choose a useful starting separation for national and viewport searches."""
    if bbox:
        west, south, east, north = bbox
        diagonal = haversine_miles(south, west, north, east)
        # Approximate spacing for `limit` points covering the visible area.
        return max(5.0, min(75.0, diagonal * 0.75 / math.sqrt(max(1, limit))))
    return 40.0 if state else 75.0


def diversify_ranked_rows(
    rows: list[dict[str, Any]],
    limit: int,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    state: str | None = None,
) -> tuple[list[dict[str, Any]], float]:
    """Select high-ranked, distinct communities while preserving score order.

    At most one point per source tract is eligible. Distance is relaxed in
    stages, so sparse searches remain widely spread and dense searches still
    fill the requested result count when enough distinct tracts exist.
    """
    unique: list[dict[str, Any]] = []
    seen_tracts: set[str] = set()
    for row in rows:
        tract = str(row.get("source_tract_geoid") or row.get("tract_geoid") or row.get("site_id"))
        if tract in seen_tracts:
            continue
        try:
            float(row["latitude"]); float(row["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        seen_tracts.add(tract)
        unique.append(row)

    initial = initial_separation_miles(limit, bbox, state)
    thresholds = [initial, initial * .75, initial * .5, initial * .25, initial * .1, 0.0]
    selected: list[dict[str, Any]] = []
    selected_sites: set[str] = set()
    for threshold in thresholds:
        for row in unique:
            site = str(row.get("site_id"))
            if site in selected_sites:
                continue
            lat, lon = float(row["latitude"]), float(row["longitude"])
            if threshold and any(
                haversine_miles(lat, lon, float(other["latitude"]), float(other["longitude"])) < threshold
                for other in selected
            ):
                continue
            selected.append(row)
            selected_sites.add(site)
            if len(selected) >= limit:
                return selected, initial
    return selected, initial
