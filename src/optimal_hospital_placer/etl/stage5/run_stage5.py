"""Stage 5: turn Stage 4 data into app-ready hospital-siting screening features.

Reads the latest successful Stage 4 snapshot unless --stage4-run is supplied.
Writes enriched tract/county GeoParquet plus facilities, a feature dictionary,
summary, manifest, and data/stage5/latest_success.json.

This stage is intentionally self-contained: no downloads and no network calls.
Distances are straight-line great-circle approximations, not driving times.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
from uuid import uuid4

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree


ROOT = Path(__file__).resolve().parents[4]
EARTH_KM = 6371.0088
MILES_TO_KM = 1.609344


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")


def safe_numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").astype("float64")


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    numerator = pd.to_numeric(numerator, errors="coerce").astype("float64")
    denominator = pd.to_numeric(denominator, errors="coerce").astype("float64")
    out = numerator / denominator.where(denominator > 0)
    return out.replace([np.inf, -np.inf], np.nan)


def pct(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return safe_divide(numerator, denominator) * 100.0


def row_sum(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    existing = [c for c in columns if c in frame.columns]
    if not existing:
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    values = frame[existing].apply(pd.to_numeric, errors="coerce")
    result = values.sum(axis=1, min_count=1)
    # If the expected list is only partially present, do not silently publish a partial aggregate.
    if len(existing) != len(columns):
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    return result.astype("float64")


def dictionary_matching_columns(dictionary: dict, table: str, phrase: str) -> list[str]:
    phrase = phrase.lower()
    result = []
    for column, info in dictionary.items():
        if not isinstance(info, dict):
            continue
        if info.get("table") != table or info.get("kind") != "estimate":
            continue
        text = " | ".join(str(info.get(k, "")) for k in ("label", "label_path")).lower()
        if phrase in text:
            result.append(column)
    return sorted(set(result))


def percentile_score(series: pd.Series, higher_is_more_need: bool = True) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").astype("float64")
    if not higher_is_more_need:
        s = -s
    # pct=True yields a stable 0..1 screening scale without assuming a distribution.
    return s.rank(method="average", pct=True, na_option="keep")


def centroids_lon_lat(gdf: gpd.GeoDataFrame) -> tuple[np.ndarray, np.ndarray]:
    if gdf.crs is None:
        raise ValueError("GeoParquet is missing CRS")
    projected = gdf.to_crs(6933)
    centers = gpd.GeoSeries(projected.geometry.centroid, crs=6933).to_crs(4326)
    return centers.x.to_numpy(dtype="float64"), centers.y.to_numpy(dtype="float64")


def sphere_xyz(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    lon_r = np.radians(lon)
    lat_r = np.radians(lat)
    cos_lat = np.cos(lat_r)
    return np.column_stack((cos_lat * np.cos(lon_r), cos_lat * np.sin(lon_r), np.sin(lat_r)))


def chord_to_km(chord: np.ndarray) -> np.ndarray:
    chord = np.clip(chord, 0.0, 2.0)
    return 2.0 * EARTH_KM * np.arcsin(chord / 2.0)


def km_to_chord(km: float) -> float:
    return 2.0 * math.sin(km / (2.0 * EARTH_KM))


def spatial_access_features(gdf: gpd.GeoDataFrame, facilities: gpd.GeoDataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=gdf.index)
    lon, lat = centroids_lon_lat(gdf)
    result["centroid_longitude"] = lon
    result["centroid_latitude"] = lat

    hospitals = facilities.loc[
        facilities.get("facility_type", pd.Series(index=facilities.index, dtype="object")).eq("hospital")
        & facilities.get("longitude", pd.Series(index=facilities.index, dtype="float64")).notna()
        & facilities.get("latitude", pd.Series(index=facilities.index, dtype="float64")).notna()
    ].copy()

    if hospitals.empty:
        for c in [
            "distance_to_nearest_hospital_miles",
            "distance_to_nearest_emergency_hospital_miles",
            "nearby_hospitals_10mi", "nearby_hospitals_25mi", "nearby_hospitals_50mi",
            "nearby_known_beds_10mi", "nearby_known_beds_25mi", "nearby_known_beds_50mi",
        ]:
            result[c] = np.nan
        return result

    query_xyz = sphere_xyz(lon, lat)
    hosp_xyz = sphere_xyz(
        pd.to_numeric(hospitals["longitude"], errors="coerce").to_numpy(dtype="float64"),
        pd.to_numeric(hospitals["latitude"], errors="coerce").to_numpy(dtype="float64"),
    )
    tree = cKDTree(hosp_xyz)
    nearest_chord, _ = tree.query(query_xyz, k=1)
    result["distance_to_nearest_hospital_miles"] = chord_to_km(nearest_chord) / MILES_TO_KM

    emergency = hospitals.loc[hospitals.get("emergency_services", False).fillna(False).astype(bool)]
    if not emergency.empty:
        emergency_xyz = sphere_xyz(
            pd.to_numeric(emergency["longitude"], errors="coerce").to_numpy(dtype="float64"),
            pd.to_numeric(emergency["latitude"], errors="coerce").to_numpy(dtype="float64"),
        )
        emergency_tree = cKDTree(emergency_xyz)
        chord, _ = emergency_tree.query(query_xyz, k=1)
        result["distance_to_nearest_emergency_hospital_miles"] = chord_to_km(chord) / MILES_TO_KM
    else:
        result["distance_to_nearest_emergency_hospital_miles"] = np.nan

    beds = pd.to_numeric(hospitals.get("bed_count"), errors="coerce").fillna(0).to_numpy(dtype="float64")
    for miles in (10, 25, 50):
        neighbors = tree.query_ball_point(query_xyz, r=km_to_chord(miles * MILES_TO_KM))
        result[f"nearby_hospitals_{miles}mi"] = np.fromiter((len(x) for x in neighbors), dtype="int64", count=len(neighbors))
        result[f"nearby_known_beds_{miles}mi"] = np.fromiter(
            (float(beds[x].sum()) if len(x) else 0.0 for x in neighbors),
            dtype="float64", count=len(neighbors)
        )
    return result


def derive_features(gdf: gpd.GeoDataFrame, acs_dictionary: dict, facilities: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    frame = gdf.copy()

    # ACS base measures.
    frame["population"] = safe_numeric(frame, "acs_b01001_e001")
    frame["median_household_income"] = safe_numeric(frame, "acs_b19013_e001")

    age_65_columns = [
        "acs_b01001_e020", "acs_b01001_e021", "acs_b01001_e022",
        "acs_b01001_e023", "acs_b01001_e024", "acs_b01001_e025",
        "acs_b01001_e044", "acs_b01001_e045", "acs_b01001_e046",
        "acs_b01001_e047", "acs_b01001_e048", "acs_b01001_e049",
    ]
    under_18_columns = [
        "acs_b01001_e003", "acs_b01001_e004", "acs_b01001_e005", "acs_b01001_e006",
        "acs_b01001_e027", "acs_b01001_e028", "acs_b01001_e029", "acs_b01001_e030",
    ]
    frame["population_age_65_plus"] = row_sum(frame, age_65_columns)
    frame["population_age_65_plus_pct"] = pct(frame["population_age_65_plus"], frame["population"])
    frame["population_under_18"] = row_sum(frame, under_18_columns)
    frame["population_under_18_pct"] = pct(frame["population_under_18"], frame["population"])

    frame["poverty_universe_population"] = safe_numeric(frame, "acs_b17001_e001")
    frame["population_below_poverty"] = safe_numeric(frame, "acs_b17001_e002")
    frame["poverty_pct"] = pct(frame["population_below_poverty"], frame["poverty_universe_population"])

    frame["vehicle_households"] = safe_numeric(frame, "acs_b08201_e001")
    frame["households_no_vehicle"] = safe_numeric(frame, "acs_b08201_e002")
    frame["households_no_vehicle_pct"] = pct(frame["households_no_vehicle"], frame["vehicle_households"])

    uninsured_cols = dictionary_matching_columns(acs_dictionary, "B27001", "no health insurance coverage")
    frame["uninsured_population"] = row_sum(frame, uninsured_cols) if uninsured_cols else np.nan
    frame["health_insurance_universe_population"] = safe_numeric(frame, "acs_b27001_e001")
    frame["uninsured_pct"] = pct(frame["uninsured_population"], frame["health_insurance_universe_population"])

    disabled_cols = dictionary_matching_columns(acs_dictionary, "B18101", "with a disability")
    frame["disabled_population"] = row_sum(frame, disabled_cols) if disabled_cols else np.nan
    frame["disability_universe_population"] = safe_numeric(frame, "acs_b18101_e001")
    frame["disability_pct"] = pct(frame["disabled_population"], frame["disability_universe_population"])

    # Existing capacity carried from Stage 3/4.
    frame["existing_facility_count"] = safe_numeric(frame, "located_registry_facility_count")
    frame["existing_hospital_count"] = safe_numeric(frame, "located_registry_hospital_count")
    frame["existing_hospital_known_beds"] = safe_numeric(frame, "located_hospital_known_beds_sum")
    frame["existing_hospitals_missing_beds"] = safe_numeric(frame, "located_hospitals_missing_beds")
    frame["known_beds_per_1000_residents"] = safe_divide(frame["existing_hospital_known_beds"], frame["population"]) * 1000.0

    # HRSA MUA/P footprint proxies already produced in Stage 3.
    frame["mua_coverage_fraction"] = safe_numeric(frame, "mua_boundary_area_fraction")
    frame["mup_coverage_fraction"] = safe_numeric(frame, "mup_boundary_area_fraction")
    frame["shortage_area_coverage_fraction"] = pd.concat(
        [frame["mua_coverage_fraction"], frame["mup_coverage_fraction"]], axis=1
    ).max(axis=1, skipna=True)

    # Straight-line spatial access from tract/county centroid to geocoded hospitals.
    spatial = spatial_access_features(frame, facilities)
    for column in spatial:
        frame[column] = spatial[column].to_numpy()

    # Screening components on a 0..1 percentile scale. Keep components visible so
    # the API/app can reweight them instead of treating this as a validated model.
    frame["population_need_score"] = percentile_score(frame["population"])
    frame["elderly_need_score"] = percentile_score(frame["population_age_65_plus_pct"])
    frame["poverty_need_score"] = percentile_score(frame["poverty_pct"])
    frame["uninsured_need_score"] = percentile_score(frame["uninsured_pct"])
    frame["disability_need_score"] = percentile_score(frame["disability_pct"])
    frame["transport_need_score"] = percentile_score(frame["households_no_vehicle_pct"])
    frame["distance_access_need_score"] = percentile_score(frame["distance_to_nearest_hospital_miles"])
    frame["nearby_capacity_need_score"] = percentile_score(frame["nearby_known_beds_25mi"], higher_is_more_need=False)
    frame["shortage_area_need_score"] = frame["shortage_area_coverage_fraction"].clip(lower=0, upper=1)

    frame["demographic_need_score"] = frame[[
        "elderly_need_score", "poverty_need_score", "uninsured_need_score",
        "disability_need_score", "transport_need_score",
    ]].mean(axis=1, skipna=True)
    frame["access_gap_score"] = frame[[
        "distance_access_need_score", "nearby_capacity_need_score",
    ]].mean(axis=1, skipna=True)
    frame["screening_need_score"] = frame[[
        "population_need_score", "demographic_need_score",
        "access_gap_score", "shortage_area_need_score",
    ]].mean(axis=1, skipna=True)

    return frame


def feature_dictionary() -> dict:
    return {
        "population": "ACS total population (B01001).",
        "population_age_65_plus": "ACS population age 65+ summed across sex/age cells.",
        "population_age_65_plus_pct": "Age 65+ share of total population.",
        "population_under_18": "ACS population under age 18 summed across sex/age cells.",
        "population_under_18_pct": "Under-18 share of total population.",
        "median_household_income": "ACS median household income in 2023 inflation-adjusted dollars (B19013).",
        "population_below_poverty": "ACS population below poverty level (B17001).",
        "poverty_pct": "Population below poverty / poverty-status universe.",
        "uninsured_population": "Sum of B27001 estimate cells labeled 'No health insurance coverage'.",
        "uninsured_pct": "Uninsured population / B27001 universe.",
        "disabled_population": "Sum of B18101 estimate cells labeled 'With a disability'.",
        "disability_pct": "Disabled population / B18101 universe.",
        "households_no_vehicle": "ACS households with no vehicle available (B08201).",
        "households_no_vehicle_pct": "No-vehicle households / B08201 household universe.",
        "existing_hospital_count": "Located hospital registry count from Stage 3.",
        "existing_hospital_known_beds": "Known beds summed for located hospitals from Stage 3.",
        "known_beds_per_1000_residents": "Known beds physically in geography per 1,000 residents; not a service-area capacity rate.",
        "mua_coverage_fraction": "MUA boundary footprint fraction from Stage 3.",
        "mup_coverage_fraction": "MUP boundary footprint fraction from Stage 3.",
        "shortage_area_coverage_fraction": "Maximum of MUA and MUP footprint fractions.",
        "centroid_longitude": "Longitude of equal-area geometry centroid used for access calculations.",
        "centroid_latitude": "Latitude of equal-area geometry centroid used for access calculations.",
        "distance_to_nearest_hospital_miles": "Great-circle distance from geography centroid to nearest geocoded registry hospital; not driving distance.",
        "distance_to_nearest_emergency_hospital_miles": "Great-circle distance from geography centroid to nearest geocoded hospital marked emergency_services.",
        "nearby_hospitals_10mi": "Geocoded registry hospitals within 10 straight-line miles of centroid.",
        "nearby_hospitals_25mi": "Geocoded registry hospitals within 25 straight-line miles of centroid.",
        "nearby_hospitals_50mi": "Geocoded registry hospitals within 50 straight-line miles of centroid.",
        "nearby_known_beds_10mi": "Known beds among geocoded registry hospitals within 10 straight-line miles.",
        "nearby_known_beds_25mi": "Known beds among geocoded registry hospitals within 25 straight-line miles.",
        "nearby_known_beds_50mi": "Known beds among geocoded registry hospitals within 50 straight-line miles.",
        "demographic_need_score": "Unvalidated screening percentile mean of elderly, poverty, uninsured, disability, and no-vehicle signals.",
        "access_gap_score": "Unvalidated screening percentile mean of nearest-hospital distance and inverse nearby known-bed capacity.",
        "screening_need_score": "Unvalidated screening score combining population, demographic, access, and shortage-area signals. Use for exploration, not as a final siting decision.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage4-run", type=Path, help="Specific Stage 4 run directory; default latest successful run")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "stage5")
    args = parser.parse_args()

    if args.stage4_run:
        stage4 = args.stage4_run.resolve()
    else:
        pointer = ROOT / "data" / "stage4" / "latest_success.json"
        if not pointer.exists():
            raise FileNotFoundError("Missing data/stage4/latest_success.json. Run ACS/Stage 4 first.")
        stage4 = Path(read_json(pointer)["run_directory"]).resolve()

    required = [stage4 / "tracts.parquet", stage4 / "counties.parquet", stage4 / "facilities.parquet", stage4 / "data_dictionary.json"]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Stage 4 is incomplete; missing: {missing}")

    output = args.output_dir.resolve()
    run = output / "runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    run.mkdir(parents=True, exist_ok=False)

    manifest = {
        "status": "running",
        "stage4_run": str(stage4),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "distance_method": "great_circle_from_equal_area_geometry_centroid",
        "score_status": "screening_only_unvalidated",
    }
    write_json(run / "manifest.json", manifest)

    try:
        print(f"Reading Stage 4: {stage4}", flush=True)
        tracts = gpd.read_parquet(stage4 / "tracts.parquet")
        counties = gpd.read_parquet(stage4 / "counties.parquet")
        facilities = gpd.read_parquet(stage4 / "facilities.parquet")
        dictionaries = read_json(stage4 / "data_dictionary.json")
        tract_dict = dictionaries.get("tracts", {})
        county_dict = dictionaries.get("counties", {})

        print(f"Deriving tract features for {len(tracts):,} rows", flush=True)
        tract_features = derive_features(tracts, tract_dict, facilities)
        print(f"Deriving county features for {len(counties):,} rows", flush=True)
        county_features = derive_features(counties, county_dict, facilities)

        # Minimal fail-fast checks only: keys/rows/geometry must survive.
        if len(tract_features) != len(tracts) or tract_features["tract_geoid"].duplicated().any():
            raise ValueError("Tract row/key integrity failed")
        if len(county_features) != len(counties) or county_features["county_geoid"].duplicated().any():
            raise ValueError("County row/key integrity failed")
        if tract_features.geometry.isna().any() or county_features.geometry.isna().any():
            raise ValueError("Reference geometry unexpectedly missing")

        tract_features.to_parquet(run / "tract_features.parquet", index=False, compression="zstd")
        county_features.to_parquet(run / "county_features.parquet", index=False, compression="zstd")
        shutil.copyfile(stage4 / "facilities.parquet", run / "facilities.parquet")

        features = feature_dictionary()
        write_json(run / "feature_dictionary.json", features)
        summary = {
            "tract_rows": int(len(tract_features)),
            "county_rows": int(len(county_features)),
            "facility_rows": int(len(facilities)),
            "located_hospitals": int(((facilities.get("facility_type") == "hospital") & facilities.get("longitude").notna() & facilities.get("latitude").notna()).sum()),
            "tracts_with_population": int(tract_features["population"].notna().sum()),
            "tracts_with_nearest_hospital_distance": int(tract_features["distance_to_nearest_hospital_miles"].notna().sum()),
            "notes": [
                "Stage 5 performs no network calls.",
                "Distances are straight-line, not travel time.",
                "Registry facility counts/status inherit Stage 3 limitations.",
                "screening_need_score is an app/exploration starter, not a validated optimal-siting model.",
            ],
        }
        write_json(run / "summary.json", summary)

        manifest.update({
            "status": "complete",
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "outputs": {
                "tract_features": "tract_features.parquet",
                "county_features": "county_features.parquet",
                "facilities": "facilities.parquet",
                "feature_dictionary": "feature_dictionary.json",
                "summary": "summary.json",
            },
            "rows": {"tracts": len(tract_features), "counties": len(county_features), "facilities": len(facilities)},
        })
        write_json(run / "manifest.json", manifest)
        write_json(output / "latest_success.json", {"run_directory": str(run), **manifest})
        print(f"\nStage 5 complete: {run}", flush=True)
        print(f"  {run / 'tract_features.parquet'}", flush=True)
        print(f"  {run / 'county_features.parquet'}", flush=True)
        print(f"  {run / 'facilities.parquet'}", flush=True)
        return 0
    except Exception as exc:
        manifest.update(status="failed", error=str(exc), finished_utc=datetime.now(timezone.utc).isoformat())
        write_json(run / "manifest.json", manifest)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
