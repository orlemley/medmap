from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import math

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .common import (
    chord_radius,
    haversine_miles,
    percentile_score,
    read_json,
    state_fips_from_geoid,
    unit_xyz,
    utc_now,
    write_json,
    new_run_dir,
)


@dataclass(frozen=True)
class Stage6AScreenConfig:
    # Broad gate: intentionally permissive because this pass should avoid false negatives.
    min_population: int = 1000
    min_screening_score: float = 0.45
    min_nearest_hospital_miles: float = 10.0

    # Approximate road model. 6B replaces these estimates with Valhalla.
    urban_detour_factor: float = 1.22
    rural_detour_factor: float = 1.30
    urban_effective_mph: float = 28.0
    rural_effective_mph: float = 46.0

    # Coarse catchments used only for screening.
    catchment_minutes: tuple[int, ...] = (30, 45, 60)

    # Shortlisting policy. Keep both state-local leaders and severe-access outliers.
    top_n_per_state: int = 150
    top_fraction_per_state: float = 0.08
    severe_existing_drive_minutes: float = 35.0
    severe_min_population: int = 1500

    # Prevent unusually huge rural neighborhoods from dominating memory/time.
    max_neighbor_radius_miles: float = 70.0


# We intentionally make this fuzzy: Stage 5 schemas can evolve. These helpers use
# whatever rurality information is already present, and safely fall back when absent.
def _rurality_fraction(frame: pd.DataFrame) -> pd.Series:
    candidates = [
        "rurality", "rurality_score", "rural_fraction", "rural_population_fraction",
        "ruca_rural_fraction", "ruca_rurality", "rural_pct",
    ]
    for col in candidates:
        if col in frame.columns:
            s = pd.to_numeric(frame[col], errors="coerce").astype(float)
            # pct-style columns may be 0..100.
            if s.dropna().quantile(0.95) > 1.5:
                s = s / 100.0
            return s.clip(0, 1).fillna(0.0)

    # If a RUCA code exists, use a coarse urban/rural split. Codes >=4 are generally
    # progressively less urban; this is a screening heuristic only.
    for col in [c for c in frame.columns if "ruca" in c.lower()]:
        s = pd.to_numeric(frame[col], errors="coerce")
        if s.notna().any():
            return ((s - 1.0) / 9.0).clip(0, 1).fillna(0.0)

    return pd.Series(0.0, index=frame.index, dtype="float64")


def _numeric(frame: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[name], errors="coerce").fillna(default).astype(float)


def _demand_coordinates(tracts: gpd.GeoDataFrame) -> tuple[np.ndarray, np.ndarray]:
    if {"centroid_latitude", "centroid_longitude"}.issubset(tracts.columns):
        lat = pd.to_numeric(tracts["centroid_latitude"], errors="coerce").to_numpy(float)
        lon = pd.to_numeric(tracts["centroid_longitude"], errors="coerce").to_numpy(float)
        return lat, lon
    wgs = tracts.to_crs(4326)
    reps = wgs.geometry.representative_point()
    return reps.y.to_numpy(float), reps.x.to_numpy(float)


def screen_stage5_tracts(tracts: gpd.GeoDataFrame, cfg: Stage6AScreenConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = tracts.copy().reset_index(drop=True)
    frame["tract_geoid"] = frame["tract_geoid"].astype("string")
    frame["state_fips"] = state_fips_from_geoid(frame["tract_geoid"])

    lat, lon = _demand_coordinates(frame)
    frame["candidate_latitude"] = lat
    frame["candidate_longitude"] = lon

    pop = _numeric(frame, "population", 0)
    screening = _numeric(frame, "screening_need_score", 0)
    demographic = _numeric(frame, "demographic_need_score", 0)
    stage5_access = _numeric(frame, "access_gap_score", 0)
    nearest_miles = _numeric(frame, "distance_to_nearest_hospital_miles", 0)
    beds25 = _numeric(frame, "nearby_known_beds_25mi", 0)
    hospitals25 = _numeric(frame, "nearby_hospitals_25mi", 0)
    shortage = _numeric(frame, "shortage_area_coverage_fraction", 0)
    rural = _rurality_fraction(frame)

    detour = cfg.urban_detour_factor + rural * (cfg.rural_detour_factor - cfg.urban_detour_factor)
    mph = cfg.urban_effective_mph + rural * (cfg.rural_effective_mph - cfg.urban_effective_mph)
    estimated_existing_minutes = np.where(
        mph > 0,
        nearest_miles.to_numpy() * detour.to_numpy() / mph.to_numpy() * 60.0,
        np.nan,
    )

    broad_gate = (
        (pop >= cfg.min_population)
        & ((screening >= cfg.min_screening_score) | (nearest_miles >= cfg.min_nearest_hospital_miles))
    ) | (
        (estimated_existing_minutes >= cfg.severe_existing_drive_minutes)
        & (pop >= max(500, cfg.severe_min_population // 2))
    )

    candidate_idx = np.flatnonzero(broad_gate.to_numpy())
    valid_demand = np.isfinite(lat) & np.isfinite(lon) & (pop.to_numpy() > 0)
    demand_idx = np.flatnonzero(valid_demand)
    demand_xyz = unit_xyz(lat[demand_idx], lon[demand_idx])
    tree = cKDTree(demand_xyz)

    poverty = _numeric(frame, "population_below_poverty", 0).to_numpy()
    uninsured = _numeric(frame, "uninsured_population", 0).to_numpy()
    elderly = _numeric(frame, "population_age_65_plus", 0).to_numpy()
    disabled = _numeric(frame, "disabled_population", 0).to_numpy()
    population = pop.to_numpy()

    rows: list[dict] = []
    max_minutes = max(cfg.catchment_minutes)
    for pos, idx in enumerate(candidate_idx, start=1):
        c_lat = float(lat[idx])
        c_lon = float(lon[idx])
        if not (math.isfinite(c_lat) and math.isfinite(c_lon)):
            continue

        cand_detour = float(detour.iloc[idx])
        cand_mph = float(mph.iloc[idx])
        max_radius = min(
            cfg.max_neighbor_radius_miles,
            max_minutes / 60.0 * cand_mph / max(cand_detour, 0.01),
        )
        neighbor_local = tree.query_ball_point(unit_xyz([c_lat], [c_lon])[0], r=chord_radius(max_radius))
        if not neighbor_local:
            neighbor_global = np.array([], dtype=int)
        else:
            neighbor_global = demand_idx[np.asarray(neighbor_local, dtype=int)]

        if len(neighbor_global):
            direct = haversine_miles(c_lat, c_lon, lat[neighbor_global], lon[neighbor_global])
            # Blend road characteristics of candidate and demand tract for a cheap proxy.
            pair_detour = 0.5 * (cand_detour + detour.to_numpy()[neighbor_global])
            pair_mph = 0.5 * (cand_mph + mph.to_numpy()[neighbor_global])
            approx_minutes = direct * pair_detour / np.maximum(pair_mph, 5.0) * 60.0
            baseline = estimated_existing_minutes[neighbor_global]
            saved = np.maximum(0.0, baseline - approx_minutes)
        else:
            approx_minutes = np.array([], dtype=float)
            saved = np.array([], dtype=float)

        result = {
            "tract_geoid": str(frame.at[idx, "tract_geoid"]),
            "state_fips": str(frame.at[idx, "state_fips"]),
            "county_geoid": str(frame.at[idx, "county_geoid"]) if "county_geoid" in frame.columns else None,
            "candidate_latitude": c_lat,
            "candidate_longitude": c_lon,
            "population": float(pop.iloc[idx]),
            "stage5_screening_need_score": float(screening.iloc[idx]),
            "stage5_access_gap_score": float(stage5_access.iloc[idx]),
            "stage5_demographic_need_score": float(demographic.iloc[idx]),
            "shortage_area_coverage_fraction": float(shortage.iloc[idx]),
            "estimated_existing_drive_minutes": float(estimated_existing_minutes[idx]),
            "stage5_nearest_hospital_miles": float(nearest_miles.iloc[idx]),
            "nearby_hospitals_25mi": float(hospitals25.iloc[idx]),
            "nearby_known_beds_25mi": float(beds25.iloc[idx]),
            "approx_weighted_drive_minutes_saved": float(np.sum(population[neighbor_global] * saved)) if len(neighbor_global) else 0.0,
            "approx_population_saving_10plus_minutes": float(np.sum(population[neighbor_global][saved >= 10])) if len(neighbor_global) else 0.0,
            "approx_population_saving_20plus_minutes": float(np.sum(population[neighbor_global][saved >= 20])) if len(neighbor_global) else 0.0,
        }

        for minutes in cfg.catchment_minutes:
            within = approx_minutes <= minutes
            new = within & (baseline > minutes) if len(neighbor_global) else np.array([], dtype=bool)
            ng = neighbor_global[within] if len(neighbor_global) else np.array([], dtype=int)
            result[f"approx_population_{minutes}min"] = float(np.sum(population[ng])) if len(ng) else 0.0
            result[f"approx_newly_accessible_population_{minutes}min"] = float(np.sum(population[neighbor_global][new])) if len(neighbor_global) else 0.0
            result[f"approx_poverty_population_{minutes}min"] = float(np.sum(poverty[ng])) if len(ng) else 0.0
            result[f"approx_uninsured_population_{minutes}min"] = float(np.sum(uninsured[ng])) if len(ng) else 0.0
            result[f"approx_elderly_population_{minutes}min"] = float(np.sum(elderly[ng])) if len(ng) else 0.0
            result[f"approx_disabled_population_{minutes}min"] = float(np.sum(disabled[ng])) if len(ng) else 0.0

        rows.append(result)

    screened = pd.DataFrame(rows)
    if screened.empty:
        return screened, screened.copy()

    # Rank components across the national screened population so state scores are comparable.
    screened["approx_access_benefit_score"] = percentile_score(screened["approx_weighted_drive_minutes_saved"]).fillna(0)
    screened["approx_new_access_score"] = percentile_score(screened["approx_newly_accessible_population_30min"]).fillna(0)

    beds_per_capita_proxy = screened["nearby_known_beds_25mi"] / screened["population"].clip(lower=1)
    screened["approx_capacity_gap_score"] = percentile_score(beds_per_capita_proxy, higher_is_more_need=False).fillna(0)

    vulnerability_proxy = (
        0.35 * screened["stage5_demographic_need_score"]
        + 0.25 * screened["shortage_area_coverage_fraction"].clip(0, 1)
        + 0.20 * percentile_score(screened["approx_poverty_population_30min"]).fillna(0)
        + 0.20 * percentile_score(screened["approx_uninsured_population_30min"]).fillna(0)
    )
    screened["approx_vulnerability_score"] = vulnerability_proxy.clip(0, 1)

    screened["stage6a_score"] = (
        0.30 * screened["approx_access_benefit_score"]
        + 0.20 * screened["approx_new_access_score"]
        + 0.15 * screened["approx_capacity_gap_score"]
        + 0.15 * screened["approx_vulnerability_score"]
        + 0.10 * screened["stage5_screening_need_score"]
        + 0.10 * screened["stage5_access_gap_score"]
    ).clip(0, 1)

    screened["state_rank"] = screened.groupby("state_fips")["stage6a_score"].rank(method="first", ascending=False).astype(int)
    screened["state_percentile"] = screened.groupby("state_fips")["stage6a_score"].rank(method="average", pct=True)
    screened["severe_access_keep"] = (
        (screened["estimated_existing_drive_minutes"] >= cfg.severe_existing_drive_minutes)
        & (screened["population"] >= cfg.severe_min_population)
    )
    screened["shortlisted"] = (
        (screened["state_rank"] <= cfg.top_n_per_state)
        | (screened["state_percentile"] >= 1.0 - cfg.top_fraction_per_state)
        | screened["severe_access_keep"]
    )

    screened = screened.sort_values(["state_fips", "stage6a_score"], ascending=[True, False]).reset_index(drop=True)
    shortlist = screened.loc[screened["shortlisted"]].copy().reset_index(drop=True)
    return screened, shortlist


def latest_stage5(root: Path) -> Path:
    pointer = root / "data" / "stage5" / "latest_success.json"
    if not pointer.exists():
        raise FileNotFoundError("Missing data/stage5/latest_success.json")
    return Path(read_json(pointer)["run_directory"]).resolve()


def run_stage6a(root: Path, stage5_run: Path | None, cfg: Stage6AScreenConfig) -> Path:
    stage5 = stage5_run.resolve() if stage5_run else latest_stage5(root)
    source = stage5 / "tract_features.parquet"
    if not source.exists():
        raise FileNotFoundError(f"Missing {source}")

    out_root = root / "data" / "stage6a"
    run = new_run_dir(out_root)
    manifest = {
        "status": "running",
        "stage5_run": str(stage5),
        "config": asdict(cfg),
        "started_utc": utc_now(),
    }
    write_json(run / "manifest.json", manifest)

    try:
        tracts = gpd.read_parquet(source)
        screened, shortlist = screen_stage5_tracts(tracts, cfg)
        screened.to_parquet(run / "screened_tracts.parquet", index=False)
        shortlist.to_parquet(run / "shortlisted_tracts.parquet", index=False)

        by_state = shortlist.groupby("state_fips").size().sort_index().to_dict() if len(shortlist) else {}
        summary = {
            "screened_tracts": int(len(screened)),
            "shortlisted_tracts": int(len(shortlist)),
            "shortlist_fraction": float(len(shortlist) / len(screened)) if len(screened) else 0.0,
            "shortlisted_by_state": {str(k): int(v) for k, v in by_state.items()},
        }
        write_json(run / "summary.json", summary)
        manifest.update({"status": "complete", "completed_utc": utc_now(), "summary": summary})
        write_json(run / "manifest.json", manifest)
        write_json(out_root / "latest_success.json", {
            "status": "complete",
            "run_directory": str(run.resolve()),
            "stage5_run": str(stage5),
            "completed_utc": manifest["completed_utc"],
        })
        return run
    except Exception:
        manifest.update({"status": "failed", "failed_utc": utc_now()})
        write_json(run / "manifest.json", manifest)
        raise
