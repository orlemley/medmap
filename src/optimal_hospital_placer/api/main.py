from __future__ import annotations

import json
import math
import os
from typing import Any, Literal

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from shapely import wkb
from shapely.geometry import mapping

from .db import connect, stage5_paths


API_PREFIX = "/api/v1"

app = FastAPI(
    title="Optimal Hospital Placer API",
    version="1.0.0",
    description=(
        "REST API over the final Stage 5 hospital-siting analytical dataset. "
        "DuckDB queries GeoParquet/Parquet and map endpoints return GeoJSON for MapLibre GL JS."
    ),
)

# Development default. Set FRONTEND_ORIGIN in production, e.g.
# FRONTEND_ORIGIN=https://your-app.example.com
frontend_origins = [x.strip() for x in os.getenv(
    "FRONTEND_ORIGIN",
    "http://localhost:5173,http://127.0.0.1:5173"
).split(",") if x.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ----------------------------- helpers -------------------------------------

def scalar(value: Any) -> Any:
    """Convert pandas/numpy values into JSON-safe Python scalars."""
    if value is None:
        return None
    if isinstance(value, (np.generic,)):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {k: scalar(v) for k, v in row.items()}
        for row in df.to_dict(orient="records")
    ]


def feature_collection(features: list[dict[str, Any]], **metadata: Any) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": metadata,
    }


def geometry_from_wkb(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        geom = wkb.loads(bytes(value))
        return mapping(geom)
    except Exception:
        return None


def parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        west, south, east, north = [float(v.strip()) for v in bbox.split(",")]
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="bbox must be west,south,east,north, for example -93,38,-91,40",
        ) from exc
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= 90 and -90 <= north <= 90):
        raise HTTPException(status_code=400, detail="bbox coordinates are outside valid longitude/latitude ranges")
    if south >= north:
        raise HTTPException(status_code=400, detail="bbox south must be less than north")
    if west >= east:
        raise HTTPException(status_code=400, detail="This initial API does not support antimeridian-crossing bboxes")
    return west, south, east, north


def api_error(code: str, message: str, status_code: int = 400) -> None:
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})


# ----------------------------- system/meta ---------------------------------

@app.get(f"{API_PREFIX}/health", tags=["system"])
def health() -> dict[str, Any]:
    p = stage5_paths()
    con = connect()
    try:
        con.execute("SELECT 1").fetchone()
    finally:
        con.close()
    return {
        "status": "ok",
        "api_version": "v1",
        "dataset_stage": 5,
        "dataset_run_id": p["run_id"],
    }


@app.get(f"{API_PREFIX}/meta", tags=["system"])
def meta() -> dict[str, Any]:
    p = stage5_paths()
    dictionary = json.loads(p["feature_dictionary"].read_text(encoding="utf-8-sig"))
    return {
        "api_version": "v1",
        "dataset_stage": 5,
        "dataset_run_id": p["run_id"],
        "map_crs": "EPSG:4326",
        "percentage_scale": "0_to_100",
        "score_scale": "0_to_1",
        "distance_unit": "miles",
        "map_format": "GeoJSON",
        "scores": [
            "screening_need_score",
            "access_gap_score",
            "demographic_need_score",
        ],
        "important_notes": [
            "Nearest-hospital distances are straight-line great-circle distances, not drive times.",
            "screening_need_score is an exploratory screening score, not a validated final siting model.",
            "Stage 5 is the application analytical source of truth; frontend code should not read ETL files directly.",
        ],
        "feature_dictionary": dictionary,
    }


@app.get(f"{API_PREFIX}/summary", tags=["system"])
def summary() -> dict[str, Any]:
    p = stage5_paths()
    stage_summary = json.loads(p["summary"].read_text(encoding="utf-8-sig"))
    con = connect()
    try:
        row = con.execute("""
            SELECT
                (SELECT count(*) FROM tracts) AS tract_count,
                (SELECT count(*) FROM counties) AS county_count,
                (SELECT count(*) FROM facilities) AS facility_count,
                (SELECT count(*) FROM facilities WHERE facility_type = 'hospital') AS hospital_count,
                (SELECT sum(population) FROM tracts) AS total_population
        """).fetchone()
    finally:
        con.close()
    return {
        "tract_count": int(row[0] or 0),
        "county_count": int(row[1] or 0),
        "facility_count": int(row[2] or 0),
        "hospital_count": int(row[3] or 0),
        "total_population": scalar(row[4]),
        "stage5": stage_summary,
    }


@app.get(f"{API_PREFIX}/states", tags=["lookup"])
def states() -> dict[str, Any]:
    con = connect()
    try:
        df = con.execute("""
            SELECT
                substr(tract_geoid, 1, 2) AS state_fips,
                count(*) AS tract_count,
                sum(population) AS population,
                avg(screening_need_score) AS mean_screening_need_score
            FROM tracts
            WHERE tract_geoid IS NOT NULL
            GROUP BY 1
            ORDER BY 1
        """).fetchdf()
    finally:
        con.close()
    return {"count": len(df), "data": records(df)}


# ------------------------------- maps --------------------------------------

@app.get(f"{API_PREFIX}/map/tracts", tags=["map"])
def map_tracts(
    bbox: str = Query(..., description="west,south,east,north"),
    min_population: int = Query(0, ge=0),
    min_score: float | None = Query(None, ge=0, le=1),
    limit: int = Query(5000, ge=1, le=10000),
) -> dict[str, Any]:
    """GeoJSON tract polygons for the current MapLibre viewport.

    The initial implementation filters by Stage-5 centroid. This is fast and
    adequate for normal map browsing; vector tiles can replace this endpoint
    later without changing detail/candidate APIs.
    """
    west, south, east, north = parse_bbox(bbox)
    sql = """
        SELECT
            tract_geoid,
            county_geoid,
            geometry,
            population,
            centroid_longitude,
            centroid_latitude,
            existing_hospital_count,
            distance_to_nearest_hospital_miles,
            screening_need_score,
            access_gap_score,
            demographic_need_score
        FROM tracts
        WHERE centroid_longitude BETWEEN ? AND ?
          AND centroid_latitude BETWEEN ? AND ?
          AND coalesce(population, 0) >= ?
    """
    params: list[Any] = [west, east, south, north, min_population]
    if min_score is not None:
        sql += " AND screening_need_score >= ?"
        params.append(min_score)
    sql += " ORDER BY screening_need_score DESC NULLS LAST LIMIT ?"
    params.append(limit)

    con = connect()
    try:
        df = con.execute(sql, params).fetchdf()
    finally:
        con.close()

    features = []
    for row in df.to_dict(orient="records"):
        geom = geometry_from_wkb(row.pop("geometry", None))
        if geom is None:
            continue
        geoid = str(row.get("tract_geoid"))
        features.append({
            "type": "Feature",
            "id": geoid,
            "geometry": geom,
            "properties": {k: scalar(v) for k, v in row.items()},
        })
    return feature_collection(
        features,
        count=len(features),
        bbox=[west, south, east, north],
        truncated=len(df) >= limit,
    )


@app.get(f"{API_PREFIX}/map/counties", tags=["map"])
def map_counties(
    bbox: str = Query(..., description="west,south,east,north"),
    min_population: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> dict[str, Any]:
    west, south, east, north = parse_bbox(bbox)
    con = connect()
    try:
        df = con.execute("""
            SELECT
                county_geoid,
                geometry,
                population,
                centroid_longitude,
                centroid_latitude,
                existing_hospital_count,
                known_beds_per_1000_residents,
                screening_need_score,
                access_gap_score,
                demographic_need_score
            FROM counties
            WHERE centroid_longitude BETWEEN ? AND ?
              AND centroid_latitude BETWEEN ? AND ?
              AND coalesce(population, 0) >= ?
            ORDER BY screening_need_score DESC NULLS LAST
            LIMIT ?
        """, [west, east, south, north, min_population, limit]).fetchdf()
    finally:
        con.close()

    features = []
    for row in df.to_dict(orient="records"):
        geom = geometry_from_wkb(row.pop("geometry", None))
        if geom is None:
            continue
        geoid = str(row.get("county_geoid"))
        features.append({
            "type": "Feature",
            "id": geoid,
            "geometry": geom,
            "properties": {k: scalar(v) for k, v in row.items()},
        })
    return feature_collection(features, count=len(features), bbox=[west, south, east, north])


@app.get(f"{API_PREFIX}/map/facilities", tags=["map"])
def map_facilities(
    bbox: str = Query(..., description="west,south,east,north"),
    facility_type: str | None = None,
    emergency_only: bool = False,
    limit: int = Query(5000, ge=1, le=10000),
) -> dict[str, Any]:
    west, south, east, north = parse_bbox(bbox)
    sql = """
        SELECT
            facility_id,
            ccn,
            name,
            facility_type,
            ownership,
            emergency_services,
            hospital_overall_rating,
            bed_count,
            city,
            state,
            zip,
            longitude,
            latitude,
            tract_geoid,
            county_geoid
        FROM facilities
        WHERE longitude BETWEEN ? AND ?
          AND latitude BETWEEN ? AND ?
    """
    params: list[Any] = [west, east, south, north]
    if facility_type:
        sql += " AND facility_type = ?"
        params.append(facility_type)
    if emergency_only:
        sql += " AND coalesce(emergency_services, false) = true"
    sql += " LIMIT ?"
    params.append(limit)

    con = connect()
    try:
        df = con.execute(sql, params).fetchdf()
    finally:
        con.close()

    features = []
    for row in records(df):
        lon = row.get("longitude")
        lat = row.get("latitude")
        if lon is None or lat is None:
            continue
        feature_id = row.get("facility_id") or row.get("ccn")
        features.append({
            "type": "Feature",
            "id": str(feature_id) if feature_id is not None else None,
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": row,
        })
    return feature_collection(features, count=len(features), bbox=[west, south, east, north])


# ---------------------------- tract detail ---------------------------------

@app.get(f"{API_PREFIX}/tracts/{{tract_geoid}}", tags=["tracts"])
def tract_detail(tract_geoid: str) -> dict[str, Any]:
    if not tract_geoid.isdigit() or len(tract_geoid) != 11:
        api_error("INVALID_TRACT_GEOID", "tract_geoid must be an 11-digit Census tract GEOID")

    con = connect()
    try:
        df = con.execute("""
            SELECT
                tract_geoid,
                county_geoid,
                population,
                population_age_65_plus,
                population_age_65_plus_pct,
                population_under_18,
                population_under_18_pct,
                median_household_income,
                population_below_poverty,
                poverty_pct,
                uninsured_population,
                uninsured_pct,
                disabled_population,
                disability_pct,
                households_no_vehicle,
                households_no_vehicle_pct,
                existing_facility_count,
                existing_hospital_count,
                existing_hospital_known_beds,
                existing_hospitals_missing_beds,
                known_beds_per_1000_residents,
                mua_coverage_fraction,
                mup_coverage_fraction,
                shortage_area_coverage_fraction,
                centroid_longitude,
                centroid_latitude,
                distance_to_nearest_hospital_miles,
                distance_to_nearest_emergency_hospital_miles,
                nearby_hospitals_10mi,
                nearby_hospitals_25mi,
                nearby_hospitals_50mi,
                nearby_known_beds_10mi,
                nearby_known_beds_25mi,
                nearby_known_beds_50mi,
                population_need_score,
                elderly_need_score,
                poverty_need_score,
                uninsured_need_score,
                disability_need_score,
                transport_need_score,
                distance_access_need_score,
                nearby_capacity_need_score,
                shortage_area_need_score,
                demographic_need_score,
                access_gap_score,
                screening_need_score
            FROM tracts
            WHERE tract_geoid = ?
            LIMIT 1
        """, [tract_geoid]).fetchdf()
    finally:
        con.close()

    if df.empty:
        api_error("TRACT_NOT_FOUND", f"No tract exists with GEOID {tract_geoid}", 404)
    return records(df)[0]


# ----------------------------- candidates ----------------------------------

CANDIDATE_SORT_COLUMNS = {
    "screening_need_score": "screening_need_score",
    "access_gap_score": "access_gap_score",
    "demographic_need_score": "demographic_need_score",
    "population": "population",
    "nearest_hospital_miles": "distance_to_nearest_hospital_miles",
    "poverty_pct": "poverty_pct",
    "uninsured_pct": "uninsured_pct",
}


@app.get(f"{API_PREFIX}/candidates", tags=["candidates"])
def candidates(
    state_fips: str | None = Query(None, min_length=2, max_length=2),
    county_geoid: str | None = Query(None, min_length=5, max_length=5),
    min_population: int = Query(1000, ge=0),
    max_existing_hospitals: int | None = Query(None, ge=0),
    min_distance_to_hospital: float | None = Query(None, ge=0),
    min_poverty_pct: float | None = Query(None, ge=0, le=100),
    min_uninsured_pct: float | None = Query(None, ge=0, le=100),
    min_access_gap_score: float | None = Query(None, ge=0, le=1),
    min_demographic_need_score: float | None = Query(None, ge=0, le=1),
    min_screening_need_score: float | None = Query(None, ge=0, le=1),
    sort: str = "screening_need_score",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    sort_column = CANDIDATE_SORT_COLUMNS.get(sort)
    if not sort_column:
        api_error("INVALID_SORT", f"sort must be one of: {', '.join(CANDIDATE_SORT_COLUMNS)}")

    where = ["coalesce(population, 0) >= ?"]
    params: list[Any] = [min_population]

    if state_fips:
        if not state_fips.isdigit():
            api_error("INVALID_STATE_FIPS", "state_fips must contain two digits")
        where.append("substr(tract_geoid, 1, 2) = ?")
        params.append(state_fips)
    if county_geoid:
        if not county_geoid.isdigit():
            api_error("INVALID_COUNTY_GEOID", "county_geoid must contain five digits")
        where.append("county_geoid = ?")
        params.append(county_geoid)
    if max_existing_hospitals is not None:
        where.append("coalesce(existing_hospital_count, 0) <= ?")
        params.append(max_existing_hospitals)
    if min_distance_to_hospital is not None:
        where.append("distance_to_nearest_hospital_miles >= ?")
        params.append(min_distance_to_hospital)
    if min_poverty_pct is not None:
        where.append("poverty_pct >= ?")
        params.append(min_poverty_pct)
    if min_uninsured_pct is not None:
        where.append("uninsured_pct >= ?")
        params.append(min_uninsured_pct)
    if min_access_gap_score is not None:
        where.append("access_gap_score >= ?")
        params.append(min_access_gap_score)
    if min_demographic_need_score is not None:
        where.append("demographic_need_score >= ?")
        params.append(min_demographic_need_score)
    if min_screening_need_score is not None:
        where.append("screening_need_score >= ?")
        params.append(min_screening_need_score)

    where_sql = " AND ".join(where)
    order_sql = "ASC" if order == "asc" else "DESC"

    con = connect()
    try:
        total = con.execute(f"SELECT count(*) FROM tracts WHERE {where_sql}", params).fetchone()[0]
        df = con.execute(f"""
            SELECT
                tract_geoid,
                county_geoid,
                centroid_longitude AS longitude,
                centroid_latitude AS latitude,
                population,
                median_household_income,
                population_age_65_plus_pct AS age_65_plus_pct,
                poverty_pct,
                uninsured_pct,
                disability_pct,
                households_no_vehicle_pct AS no_vehicle_pct,
                existing_hospital_count AS hospital_count,
                existing_hospital_known_beds AS known_beds,
                distance_to_nearest_hospital_miles AS nearest_hospital_miles,
                distance_to_nearest_emergency_hospital_miles AS nearest_emergency_hospital_miles,
                nearby_hospitals_25mi AS hospitals_within_25mi,
                nearby_known_beds_25mi AS beds_within_25mi,
                shortage_area_coverage_fraction,
                demographic_need_score,
                access_gap_score,
                screening_need_score
            FROM tracts
            WHERE {where_sql}
            ORDER BY {sort_column} {order_sql} NULLS LAST, tract_geoid
            LIMIT ? OFFSET ?
        """, [*params, limit, offset]).fetchdf()
    finally:
        con.close()

    data = records(df)
    for i, item in enumerate(data, start=offset + 1):
        item["rank"] = i

    return {
        "count": len(data),
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "order": order,
        "filters": {
            "state_fips": state_fips,
            "county_geoid": county_geoid,
            "min_population": min_population,
            "max_existing_hospitals": max_existing_hospitals,
            "min_distance_to_hospital": min_distance_to_hospital,
            "min_poverty_pct": min_poverty_pct,
            "min_uninsured_pct": min_uninsured_pct,
            "min_access_gap_score": min_access_gap_score,
            "min_demographic_need_score": min_demographic_need_score,
            "min_screening_need_score": min_screening_need_score,
        },
        "data": data,
    }


# ------------------------ nearby facilities --------------------------------

@app.get(f"{API_PREFIX}/tracts/{{tract_geoid}}/nearby-facilities", tags=["tracts"])
def nearby_facilities(
    tract_geoid: str,
    radius_miles: float = Query(25, gt=0, le=250),
    hospital_only: bool = True,
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    if not tract_geoid.isdigit() or len(tract_geoid) != 11:
        api_error("INVALID_TRACT_GEOID", "tract_geoid must be an 11-digit Census tract GEOID")

    con = connect()
    try:
        center = con.execute(
            "SELECT centroid_longitude, centroid_latitude FROM tracts WHERE tract_geoid = ? LIMIT 1",
            [tract_geoid],
        ).fetchone()
        if center is None:
            api_error("TRACT_NOT_FOUND", f"No tract exists with GEOID {tract_geoid}", 404)
        lon, lat = center

        # Great-circle (haversine) distance in miles. The inexpensive lat/lon
        # prefilter keeps the trig calculation bounded for normal radii.
        lat_delta = radius_miles / 69.0
        cos_lat = max(math.cos(math.radians(float(lat))), 0.01)
        lon_delta = radius_miles / (69.0 * cos_lat)

        type_clause = "AND facility_type = 'hospital'" if hospital_only else ""
        df = con.execute(f"""
            WITH nearby AS (
                SELECT
                    facility_id,
                    ccn,
                    name,
                    facility_type,
                    ownership,
                    emergency_services,
                    hospital_overall_rating,
                    bed_count,
                    city,
                    state,
                    longitude,
                    latitude,
                    tract_geoid,
                    county_geoid,
                    3958.7613 * 2 * asin(
                        sqrt(
                            pow(sin(radians(latitude - ?) / 2), 2)
                            + cos(radians(?)) * cos(radians(latitude))
                            * pow(sin(radians(longitude - ?) / 2), 2)
                        )
                    ) AS distance_miles
                FROM facilities
                WHERE longitude BETWEEN ? AND ?
                  AND latitude BETWEEN ? AND ?
                  AND longitude IS NOT NULL
                  AND latitude IS NOT NULL
                  {type_clause}
            )
            SELECT *
            FROM nearby
            WHERE distance_miles <= ?
            ORDER BY distance_miles ASC
            LIMIT ?
        """, [lat, lat, lon, lon - lon_delta, lon + lon_delta, lat - lat_delta, lat + lat_delta, radius_miles, limit]).fetchdf()
    finally:
        con.close()

    return {
        "tract_geoid": tract_geoid,
        "radius_miles": radius_miles,
        "hospital_only": hospital_only,
        "count": len(df),
        "data": records(df),
    }


@app.get("/", include_in_schema=False)
def root() -> JSONResponse:
    return JSONResponse({
        "name": "Optimal Hospital Placer API",
        "version": "v1",
        "docs": "/docs",
        "api": API_PREFIX,
    })
