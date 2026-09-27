from __future__ import annotations

from dataclasses import asdict
import hashlib
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import Point

from .common import (
    chord_radius,
    haversine_miles,
    new_run_dir,
    percentile_score,
    read_json,
    state_fips_from_geoid,
    unit_xyz,
    utc_now,
    write_json,
)
from .config import Stage6FastConfig
from .road_model import estimated_drive_minutes, numeric, road_parameters


TRAVEL_MODEL = "approximate_v2_rurality_adjusted"


def latest_stage5(root: Path) -> Path:
    pointer = root / "data" / "stage5" / "latest_success.json"
    if not pointer.exists():
        raise FileNotFoundError("Missing data/stage5/latest_success.json")
    return Path(read_json(pointer)["run_directory"]).resolve()


def latest_stage6a(root: Path) -> Path:
    pointer = root / "data" / "stage6a" / "latest_success.json"
    if not pointer.exists():
        raise FileNotFoundError(
            "Missing data/stage6a/latest_success.json. Run `run_stage6.py screen` first."
        )
    return Path(read_json(pointer)["run_directory"]).resolve()


def _representative_lat_lon(tracts: gpd.GeoDataFrame) -> tuple[np.ndarray, np.ndarray]:
    wgs = tracts.to_crs(4326) if tracts.crs and tracts.crs.to_epsg() != 4326 else tracts
    reps = wgs.geometry.representative_point()
    return reps.y.to_numpy(float), reps.x.to_numpy(float)


def _candidate_points_for_row(geometry, count: int) -> list[Point]:
    """Deterministic, geometry-contained candidate points; default count is one."""
    if geometry is None or geometry.is_empty or count <= 0:
        return []
    points = [geometry.representative_point()]
    if count == 1:
        return points
    centroid = geometry.centroid
    if geometry.covers(centroid):
        points.append(centroid)
    if len(points) >= count:
        return points[:count]
    minx, miny, maxx, maxy = geometry.bounds
    # Small deterministic lattice; only used when user explicitly requests >1.
    for frac_x, frac_y in ((.35,.35),(.65,.65),(.35,.65),(.65,.35),(.5,.25),(.5,.75)):
        p = Point(minx + (maxx-minx)*frac_x, miny + (maxy-miny)*frac_y)
        if geometry.covers(p) and all(p.distance(q) > 1e-10 for q in points):
            points.append(p)
            if len(points) >= count:
                break
    return points[:count]


def build_candidates(
    tracts: gpd.GeoDataFrame,
    shortlist: pd.DataFrame,
    cfg: Stage6FastConfig,
    states: set[str] | None,
) -> pd.DataFrame:
    short = shortlist.copy()
    short["tract_geoid"] = short["tract_geoid"].astype("string")
    if states:
        short = short.loc[short["state_fips"].astype("string").str.zfill(2).isin(states)].copy()
    short = short.sort_values("stage6a_score", ascending=False)

    frame = tracts.copy()
    frame["tract_geoid"] = frame["tract_geoid"].astype("string")
    chosen = frame.loc[frame["tract_geoid"].isin(set(short["tract_geoid"]))].copy()
    if chosen.empty:
        return pd.DataFrame()
    score_cols = [c for c in [
        "tract_geoid", "stage6a_score", "state_rank", "state_percentile",
        "estimated_existing_drive_minutes", "approx_weighted_drive_minutes_saved",
        "approx_newly_accessible_population_30min", "approx_access_benefit_score",
        "approx_new_access_score", "approx_capacity_gap_score", "approx_vulnerability_score",
    ] if c in short.columns]
    chosen = chosen.merge(short[score_cols], on="tract_geoid", how="left")
    chosen = chosen.to_crs(4326) if chosen.crs and chosen.crs.to_epsg() != 4326 else chosen

    rows: list[dict] = []
    for row in chosen.itertuples():
        pts = _candidate_points_for_row(row.geometry, cfg.candidates_per_tract)
        for ordinal, p in enumerate(pts):
            raw = f"{row.tract_geoid}|{ordinal}|{p.y:.6f}|{p.x:.6f}"
            rows.append({
                "site_id": "S6F-" + hashlib.sha1(raw.encode()).hexdigest()[:14],
                "source_tract_geoid": str(row.tract_geoid),
                "state_fips": str(row.tract_geoid)[:2],
                "county_geoid": str(getattr(row, "county_geoid", "")) or None,
                "latitude": float(p.y),
                "longitude": float(p.x),
                "candidate_source": "stage6a_tract_representative_point",
                "candidate_ordinal": ordinal,
                "candidate_precision": "tract_level_proxy",
                "road_snap_distance_miles": np.nan,
                "stage5_screening_need_score": float(getattr(row, "screening_need_score", np.nan)),
                "stage5_population": float(getattr(row, "population", np.nan)),
                "stage6a_score": float(getattr(row, "stage6a_score", np.nan)),
            })
    return pd.DataFrame(rows).sort_values("stage6a_score", ascending=False).reset_index(drop=True)


def build_demand(tracts: gpd.GeoDataFrame, model) -> pd.DataFrame:
    frame = tracts.copy().reset_index(drop=True)
    if {"centroid_latitude", "centroid_longitude"}.issubset(frame.columns):
        lat = pd.to_numeric(frame["centroid_latitude"], errors="coerce")
        lon = pd.to_numeric(frame["centroid_longitude"], errors="coerce")
    else:
        lat_np, lon_np = _representative_lat_lon(frame)
        lat = pd.Series(lat_np, index=frame.index)
        lon = pd.Series(lon_np, index=frame.index)

    rural, detour, mph = road_parameters(frame, model)
    out = pd.DataFrame({
        "demand_id": frame["tract_geoid"].astype("string"),
        "tract_geoid": frame["tract_geoid"].astype("string"),
        "state_fips": state_fips_from_geoid(frame["tract_geoid"]),
        "latitude": pd.to_numeric(lat, errors="coerce"),
        "longitude": pd.to_numeric(lon, errors="coerce"),
        "rurality_proxy": rural,
        "road_detour_factor": detour,
        "effective_speed_mph": mph,
    })
    for col in [
        "county_geoid", "population", "population_age_65_plus", "population_below_poverty",
        "uninsured_population", "disabled_population", "households_no_vehicle",
        "demographic_need_score", "screening_need_score", "access_gap_score",
        "shortage_area_coverage_fraction", "distance_to_nearest_hospital_miles",
    ]:
        if col in frame.columns:
            out[col] = frame[col].to_numpy()
    pop = numeric(out, "population", 0)
    return out.loc[
        out["latitude"].notna() & out["longitude"].notna() & (pop > 0)
    ].reset_index(drop=True)


def build_hospitals(facilities: pd.DataFrame) -> pd.DataFrame:
    frame = facilities.copy()
    if "facility_type" in frame.columns:
        frame = frame.loc[frame["facility_type"].astype("string").str.lower().eq("hospital")].copy()
    frame["latitude"] = pd.to_numeric(frame.get("latitude"), errors="coerce")
    frame["longitude"] = pd.to_numeric(frame.get("longitude"), errors="coerce")
    frame = frame.dropna(subset=["latitude", "longitude"]).copy()
    if "facility_id" not in frame.columns:
        frame["facility_id"] = np.arange(len(frame)).astype(str)
    frame["facility_id"] = frame["facility_id"].astype(str)
    frame["bed_count"] = pd.to_numeric(frame.get("bed_count"), errors="coerce").fillna(0).clip(lower=0)
    if "emergency_services" in frame.columns:
        if pd.api.types.is_bool_dtype(frame["emergency_services"].dtype):
            frame["emergency_services"] = frame["emergency_services"].fillna(False)
        else:
            frame["emergency_services"] = frame["emergency_services"].astype("string").str.lower().isin({"true","1","yes","y"})
    else:
        frame["emergency_services"] = False
    return frame.reset_index(drop=True)


def compute_existing_access_fast(
    demand: pd.DataFrame,
    hospitals: pd.DataFrame,
    cfg: Stage6FastConfig,
) -> pd.DataFrame:
    if hospitals.empty:
        raise RuntimeError("No geocoded hospitals available for Stage 6 baseline")

    h_xyz = unit_xyz(hospitals.latitude, hospitals.longitude)
    h_tree = cKDTree(h_xyz)
    d_xyz = unit_xyz(demand.latitude, demand.longitude)

    # Under this approximation a demand tract's detour/speed are constant across
    # hospital alternatives, so nearest straight-line hospital is also the nearest
    # modeled-drive-time hospital. This makes the national baseline extremely cheap.
    _, nearest_idx = h_tree.query(d_xyz, k=1)
    nearest_idx = np.asarray(nearest_idx, dtype=int)

    h_lat = hospitals.latitude.to_numpy(float)
    h_lon = hospitals.longitude.to_numpy(float)
    h_beds = hospitals.bed_count.to_numpy(float)
    h_emergency = hospitals.emergency_services.to_numpy(bool)
    h_ids = hospitals.facility_id.astype(str).to_numpy()
    d_lat = demand.latitude.to_numpy(float)
    d_lon = demand.longitude.to_numpy(float)
    d_detour = demand.road_detour_factor.to_numpy(float)
    d_mph = demand.effective_speed_mph.to_numpy(float)

    # Emergency baseline is a separate nearest-neighbor query against emergency
    # facilities only; no broad hospital list is required.
    emergency_idx = np.flatnonzero(h_emergency)
    emergency_tree = cKDTree(h_xyz[emergency_idx]) if len(emergency_idx) else None
    if emergency_tree is not None:
        _, e_local = emergency_tree.query(d_xyz, k=1)
        e_global = emergency_idx[np.asarray(e_local, dtype=int)]
    else:
        e_global = np.full(len(demand), -1, dtype=int)

    # For counts/beds inside modeled 15/30/45/60 minutes, only hospitals that can
    # physically fit inside the largest time threshold matter. Convert each demand
    # tract's max-time threshold to a straight-line search radius and cap it by the
    # configured prefilter.
    max_minutes = max(cfg.access_minutes)
    max_straight_miles = np.minimum(
        cfg.hospital_prefilter_miles,
        (max_minutes / 60.0) * d_mph / np.maximum(d_detour, 0.01),
    )
    radii = np.asarray([chord_radius(x) for x in max_straight_miles], dtype=float)

    rows = []
    chunk = 5000
    for start in range(0, len(demand), chunk):
        stop = min(len(demand), start + chunk)
        nearby_chunk = h_tree.query_ball_point(d_xyz[start:stop], r=radii[start:stop])
        for local_i, raw_neighbors in enumerate(nearby_chunk):
            i = start + local_i
            best_h = int(nearest_idx[i])
            best_direct = float(haversine_miles(d_lat[i], d_lon[i], h_lat[best_h], h_lon[best_h]))
            best_minutes = float(estimated_drive_minutes(best_direct, d_detour[i], d_mph[i]))
            best_miles = float(best_direct * d_detour[i])

            emergency_minutes = np.nan
            emergency_id = None
            if e_global[i] >= 0:
                eh = int(e_global[i])
                e_direct = float(haversine_miles(d_lat[i], d_lon[i], h_lat[eh], h_lon[eh]))
                emergency_minutes = float(estimated_drive_minutes(e_direct, d_detour[i], d_mph[i]))
                emergency_id = str(h_ids[eh])

            nidx = np.asarray(raw_neighbors, dtype=int)
            if len(nidx):
                nmiles = haversine_miles(d_lat[i], d_lon[i], h_lat[nidx], h_lon[nidx])
                nminutes = estimated_drive_minutes(nmiles, d_detour[i], d_mph[i])
            else:
                nminutes = np.array([], dtype=float)

            row = {
                "demand_id": str(demand.iloc[i].demand_id),
                "nearest_hospital_id": str(h_ids[best_h]),
                "nearest_hospital_drive_minutes": best_minutes,
                "nearest_hospital_drive_miles": best_miles,
                "nearest_emergency_hospital_id": emergency_id,
                "nearest_emergency_drive_minutes": emergency_minutes,
                "travel_time_model": TRAVEL_MODEL,
                "routing_refined": False,
            }
            for threshold in cfg.access_minutes:
                mask = nminutes <= threshold
                row[f"hospitals_within_{threshold}min"] = int(mask.sum())
                row[f"beds_within_{threshold}min"] = float(h_beds[nidx][mask].sum()) if len(nidx) else 0.0
            rows.append(row)
    return pd.DataFrame(rows)


def compute_candidate_features_fast(
    candidates: pd.DataFrame,
    source_tracts: pd.DataFrame,
    demand: pd.DataFrame,
    baseline: pd.DataFrame,
    hospitals: pd.DataFrame,
    cfg: Stage6FastConfig,
) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()

    demand = demand.reset_index(drop=True)
    baseline_map = baseline.set_index("demand_id")
    demand_tree = cKDTree(unit_xyz(demand.latitude, demand.longitude))
    hospital_tree = cKDTree(unit_xyz(hospitals.latitude, hospitals.longitude)) if len(hospitals) else None

    population = numeric(demand, "population", 0).clip(lower=0).to_numpy()
    demographic = numeric(demand, "demographic_need_score", 0).clip(0, 1).to_numpy()
    elderly = numeric(demand, "population_age_65_plus", 0).clip(lower=0).to_numpy()
    poverty = numeric(demand, "population_below_poverty", 0).clip(lower=0).to_numpy()
    uninsured = numeric(demand, "uninsured_population", 0).clip(lower=0).to_numpy()
    disabled = numeric(demand, "disabled_population", 0).clip(lower=0).to_numpy()
    d_lat = demand.latitude.to_numpy(float)
    d_lon = demand.longitude.to_numpy(float)
    d_detour = demand.road_detour_factor.to_numpy(float)
    d_mph = demand.effective_speed_mph.to_numpy(float)
    baseline_minutes = demand["demand_id"].astype(str).map(
        baseline_map["nearest_hospital_drive_minutes"]
    ).to_numpy(float)

    source = source_tracts.copy()
    source["tract_geoid"] = source["tract_geoid"].astype("string")
    source = source.set_index("tract_geoid", drop=False)
    _, source_detour, source_mph = road_parameters(source.reset_index(drop=True), cfg.road_model)
    road_by_geoid = {
        str(g): (float(source_detour[i]), float(source_mph[i]))
        for i, g in enumerate(source.index.astype(str))
    }

    h_lat = hospitals.latitude.to_numpy(float) if len(hospitals) else np.array([])
    h_lon = hospitals.longitude.to_numpy(float) if len(hospitals) else np.array([])
    h_beds = hospitals.bed_count.to_numpy(float) if len(hospitals) else np.array([])

    rows: list[dict] = []
    d_radius = chord_radius(cfg.demand_prefilter_miles)
    h_radius = chord_radius(cfg.hospital_prefilter_miles)

    for pos, c in enumerate(candidates.itertuples(), start=1):
        cand_detour, cand_mph = road_by_geoid.get(str(c.source_tract_geoid), (1.25, 40.0))
        d_idx = np.asarray(demand_tree.query_ball_point(
            unit_xyz([c.latitude], [c.longitude])[0], r=d_radius
        ), dtype=int)
        if len(d_idx):
            direct = haversine_miles(c.latitude, c.longitude, d_lat[d_idx], d_lon[d_idx])
            pair_detour = 0.5 * (cand_detour + d_detour[d_idx])
            pair_mph = 0.5 * (cand_mph + d_mph[d_idx])
            cand_minutes = estimated_drive_minutes(direct, pair_detour, pair_mph)
            base = baseline_minutes[d_idx]
            saved = np.maximum(0.0, base - cand_minutes)
            pop = population[d_idx]
        else:
            cand_minutes = saved = pop = np.array([], dtype=float)

        row = {
            "site_id": str(c.site_id),
            "latitude": float(c.latitude),
            "longitude": float(c.longitude),
            "source_tract_geoid": str(c.source_tract_geoid),
            "state_fips": str(c.state_fips),
            "county_geoid": c.county_geoid,
            "candidate_source": c.candidate_source,
            "candidate_precision": c.candidate_precision,
            "road_snap_distance_miles": np.nan,
            "stage5_screening_need_score": float(c.stage5_screening_need_score),
            "stage5_population": float(c.stage5_population),
            "stage6a_score": float(c.stage6a_score),
            "routed_demand_points": 0,
            "modeled_demand_points": int(len(d_idx)),
            "weighted_drive_minutes_saved": float(np.sum(pop * saved)) if len(d_idx) else 0.0,
            "population_with_any_access_improvement": float(np.sum(pop[saved > 0])) if len(d_idx) else 0.0,
            "travel_time_model": TRAVEL_MODEL,
            "routing_refined": False,
            "refinement_recommended": True,
        }
        improved_pop = row["population_with_any_access_improvement"]
        row["population_weighted_mean_minutes_saved"] = (
            row["weighted_drive_minutes_saved"] / improved_pop if improved_pop > 0 else 0.0
        )

        for threshold in cfg.improvement_minutes:
            row[f"population_saving_{threshold}plus_minutes"] = (
                float(np.sum(pop[saved >= threshold])) if len(d_idx) else 0.0
            )
        for threshold in cfg.access_minutes:
            within = cand_minutes <= threshold
            newly = within & (baseline_minutes[d_idx] > threshold) if len(d_idx) else np.array([], dtype=bool)
            idx = d_idx[within] if len(d_idx) else np.array([], dtype=int)
            row[f"population_within_{threshold}min"] = float(np.sum(population[idx])) if len(idx) else 0.0
            row[f"newly_accessible_population_{threshold}min"] = float(np.sum(population[d_idx][newly])) if len(d_idx) else 0.0
            row[f"elderly_population_{threshold}min"] = float(np.sum(elderly[idx])) if len(idx) else 0.0
            row[f"poverty_population_{threshold}min"] = float(np.sum(poverty[idx])) if len(idx) else 0.0
            row[f"uninsured_population_{threshold}min"] = float(np.sum(uninsured[idx])) if len(idx) else 0.0
            row[f"disabled_population_{threshold}min"] = float(np.sum(disabled[idx])) if len(idx) else 0.0
            row[f"vulnerability_weighted_population_{threshold}min"] = float(np.sum(population[idx] * demographic[idx])) if len(idx) else 0.0

        # Existing supply around candidate, using the same approximate drive model.
        nearest_minutes = np.nan
        hidx = np.asarray(hospital_tree.query_ball_point(
            unit_xyz([c.latitude], [c.longitude])[0], r=h_radius
        ), dtype=int) if hospital_tree is not None else np.array([], dtype=int)
        if len(hidx):
            hmiles = haversine_miles(c.latitude, c.longitude, h_lat[hidx], h_lon[hidx])
            hminutes = estimated_drive_minutes(hmiles, cand_detour, cand_mph)
            nearest_minutes = float(np.nanmin(hminutes))
        else:
            hminutes = np.array([], dtype=float)
        row["nearest_existing_hospital_minutes"] = nearest_minutes
        for threshold in cfg.access_minutes:
            mask = hminutes <= threshold
            row[f"existing_hospitals_{threshold}min"] = int(mask.sum())
            row[f"existing_beds_{threshold}min"] = float(h_beds[hidx][mask].sum()) if len(hidx) else 0.0

        beds30 = row.get("existing_beds_30min", 0.0)
        pop30 = row.get("population_within_30min", 0.0)
        row["population_per_existing_bed_30min"] = (pop30 / beds30) if beds30 > 0 else np.nan
        row["no_existing_beds_30min"] = bool(beds30 <= 0 and pop30 > 0)
        rows.append(row)

        if cfg.candidate_progress_every and pos % cfg.candidate_progress_every == 0:
            print(f"  modeled {pos:,}/{len(candidates):,} candidates", flush=True)

    return pd.DataFrame(rows)


def add_national_scores(features: pd.DataFrame) -> pd.DataFrame:
    result = features.copy()
    result["access_improvement_score"] = percentile_score(result["weighted_drive_minutes_saved"]).fillna(0)
    result["new_access_score"] = percentile_score(result["newly_accessible_population_30min"]).fillna(0)

    pressure = pd.to_numeric(result["population_per_existing_bed_30min"], errors="coerce")
    finite = pressure.replace([np.inf, -np.inf], np.nan)
    ceiling = finite.quantile(0.995) if finite.notna().any() else 1.0
    pressure = finite.copy()
    pressure = pressure.mask(result["no_existing_beds_30min"].fillna(False), ceiling * 1.25 if ceiling > 0 else 1e9)
    result["capacity_gap_score"] = percentile_score(pressure).fillna(0)

    pop30 = pd.to_numeric(result["population_within_30min"], errors="coerce")
    vuln30 = pd.to_numeric(result["vulnerability_weighted_population_30min"], errors="coerce")
    result["vulnerability_catchment_mean"] = vuln30 / pop30.where(pop30 > 0)
    result["vulnerability_catchment_score"] = percentile_score(result["vulnerability_catchment_mean"]).fillna(0)

    result["stage6_access_score"] = result[[
        "access_improvement_score", "new_access_score", "capacity_gap_score",
        "vulnerability_catchment_score",
    ]].mean(axis=1, skipna=True)
    result["stage6_rank"] = result["stage6_access_score"].rank(method="first", ascending=False).astype(int)
    return result.sort_values("stage6_access_score", ascending=False).reset_index(drop=True)


def run_stage6_fast(
    root: Path,
    cfg: Stage6FastConfig,
    stage5_run: Path | None = None,
    stage6a_run: Path | None = None,
    states: list[str] | None = None,
) -> Path:
    stage5 = stage5_run.resolve() if stage5_run else latest_stage5(root)
    stage6a = stage6a_run.resolve() if stage6a_run else latest_stage6a(root)
    state_set = {str(x).zfill(2) for x in states} if states else None

    for p in [stage5 / "tract_features.parquet", stage5 / "facilities.parquet", stage6a / "shortlisted_tracts.parquet"]:
        if not p.exists():
            raise FileNotFoundError(f"Missing required input: {p}")

    out_root = root / "data" / "stage6"
    run = new_run_dir(out_root)
    manifest = {
        "status": "running",
        "stage5_run": str(stage5),
        "stage6a_run": str(stage6a),
        "states": sorted(state_set) if state_set else "all",
        "travel_time_model": TRAVEL_MODEL,
        "routing_refined": False,
        "config": asdict(cfg),
        "started_utc": utc_now(),
    }
    write_json(run / "manifest.json", manifest)

    try:
        print(f"Reading Stage 5: {stage5}", flush=True)
        tracts = gpd.read_parquet(stage5 / "tract_features.parquet")
        facilities = pd.read_parquet(stage5 / "facilities.parquet")
        shortlist = pd.read_parquet(stage6a / "shortlisted_tracts.parquet")

        print("Building fast Stage 6 demand and candidate datasets...", flush=True)
        demand = build_demand(tracts, cfg.road_model)
        if state_set:
            # Preserve cross-border demand by NOT filtering demand to states. Only candidates are filtered.
            pass
        hospitals = build_hospitals(facilities)
        candidates = build_candidates(tracts, shortlist, cfg, state_set)
        if candidates.empty:
            raise RuntimeError("No Stage 6 candidates survived Stage 6A for the requested states")

        print(f"Candidates: {len(candidates):,}; demand tracts: {len(demand):,}; hospitals: {len(hospitals):,}", flush=True)
        print("Computing approximate existing-hospital access...", flush=True)
        existing = compute_existing_access_fast(demand, hospitals, cfg)

        print("Computing approximate candidate access/capacity features...", flush=True)
        features = compute_candidate_features_fast(candidates, tracts, demand, existing, hospitals, cfg)
        features = add_national_scores(features)

        candidates.to_parquet(run / "candidate_sites.parquet", index=False, compression="zstd")
        features.to_parquet(run / "candidate_site_features.parquet", index=False, compression="zstd")
        existing.to_parquet(run / "existing_access.parquet", index=False, compression="zstd")

        # Small finalist handoff: Stage 7 can optimize configurations, then precise
        # routing can be done only for those finalists.
        top = features.head(min(250, len(features))).copy()
        top.to_parquet(run / "refinement_candidates.parquet", index=False, compression="zstd")

        summary = {
            "candidate_sites": int(len(candidates)),
            "candidate_feature_rows": int(len(features)),
            "demand_points": int(len(demand)),
            "existing_access_rows": int(len(existing)),
            "hospital_rows": int(len(hospitals)),
            "travel_time_model": TRAVEL_MODEL,
            "routing_refined": False,
            "refinement_candidates_written": int(len(top)),
            "notes": [
                "Stage 6 uses a rurality-adjusted straight-line road/travel-time approximation for speed.",
                "Candidate points are tract-level proxies and are not parcels or road-snapped sites.",
                "Stage 7 should optimize hospital configurations first, then precise road routing should be run only for finalists.",
            ],
        }
        write_json(run / "summary.json", summary)
        manifest.update({"status": "complete", "completed_utc": utc_now(), "summary": summary})
        write_json(run / "manifest.json", manifest)
        write_json(out_root / "latest_success.json", {
            "status": "complete",
            "run_directory": str(run.resolve()),
            "stage5_run": str(stage5),
            "stage6a_run": str(stage6a),
            "travel_time_model": TRAVEL_MODEL,
            "routing_refined": False,
            "completed_utc": manifest["completed_utc"],
        })
        print(f"Stage 6 FAST complete: {run}", flush=True)
        return run
    except Exception:
        manifest.update({"status": "failed", "failed_utc": utc_now()})
        write_json(run / "manifest.json", manifest)
        raise
