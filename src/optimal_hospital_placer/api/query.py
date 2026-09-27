from __future__ import annotations

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
