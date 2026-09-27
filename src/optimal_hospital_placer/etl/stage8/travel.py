from __future__ import annotations

import numpy as np
import pandas as pd

from .common import numeric, percentile_score, sat
from .config import Stage8Config


def _rurality_fraction(frame: pd.DataFrame) -> pd.Series:
    candidates = [
        "rurality", "rurality_score", "rural_fraction", "rural_population_fraction",
        "ruca_rural_fraction", "ruca_rurality", "rural_pct",
    ]
    for col in candidates:
        if col in frame.columns:
            s = pd.to_numeric(frame[col], errors="coerce").astype(float)
            if s.dropna().size and s.dropna().quantile(0.95) > 1.5:
                s = s / 100.0
            return s.clip(0, 1).fillna(0.0)

    # Generic RUCA numeric fallback.
    for col in [c for c in frame.columns if "ruca" in c.lower()]:
        s = pd.to_numeric(frame[col], errors="coerce")
        if s.notna().any():
            return ((s - 1.0) / 9.0).clip(0, 1).fillna(0.0)

    # Unknown rurality gets a middle-of-the-road speed rather than silently assuming dense urban.
    return pd.Series(0.5, index=frame.index, dtype="float64")


def add_travel_metrics(frame: pd.DataFrame, cfg: Stage8Config) -> pd.DataFrame:
    result = frame.copy()
    rural = _rurality_fraction(result)
    detour = cfg.urban_detour_factor + rural * (cfg.rural_detour_factor - cfg.urban_detour_factor)
    mph = cfg.urban_effective_mph + rural * (cfg.rural_effective_mph - cfg.urban_effective_mph)

    result["stage8_rurality_proxy"] = rural
    result["stage8_detour_factor"] = detour
    result["stage8_effective_speed_mph"] = mph

    nearest_min = numeric(result, "nearest_existing_hospital_minutes", np.nan)
    nearest_min = nearest_min.replace(0.0, np.nan) if "nearest_existing_hospital_minutes" not in result.columns else nearest_min
    result["nearest_existing_hospital_estimated_drive_miles"] = nearest_min * mph / 60.0
    result["nearest_existing_hospital_estimated_straightline_miles"] = (
        result["nearest_existing_hospital_estimated_drive_miles"] / detour.replace(0, np.nan)
    )

    for threshold in (15, 30, 45, 60):
        result[f"modeled_drive_miles_{threshold}min"] = mph * (threshold / 60.0)
        result[f"modeled_straightline_radius_miles_{threshold}min"] = (
            result[f"modeled_drive_miles_{threshold}min"] / detour
        )

    # Explicit travel/access component for final ranking.
    isolation = sat(numeric(result, "nearest_existing_hospital_minutes", 0), 25.0)
    mean_saved = sat(numeric(result, "population_weighted_mean_minutes_saved", 0), 12.0)
    saved20 = percentile_score(numeric(result, "population_saving_20plus_minutes", 0))
    newly30 = percentile_score(numeric(result, "newly_accessible_population_30min", 0))
    result["stage8_isolation_score"] = isolation
    result["stage8_mean_time_saved_score"] = mean_saved
    result["stage8_population_saved_20min_score"] = saved20
    result["stage8_new_access_30min_score"] = newly30
    result["drive_access_score"] = (
        0.30 * isolation +
        0.25 * mean_saved +
        0.20 * saved20 +
        0.25 * newly30
    ).clip(0, 1)

    result["distance_model"] = cfg.distance_model
    # Preserve Stage 6 provenance if available.
    if "travel_time_model" not in result.columns:
        result["travel_time_model"] = "unknown_stage6_model"
    if "routing_refined" not in result.columns:
        result["routing_refined"] = False
    return result


def travel_access_long(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for threshold in (15, 30, 45, 60):
        part = pd.DataFrame({
            "site_id": frame["site_id"].astype(str),
            "candidate_id": frame.get("candidate_id", frame["site_id"]).astype(str),
            "latitude": pd.to_numeric(frame["latitude"], errors="coerce"),
            "longitude": pd.to_numeric(frame["longitude"], errors="coerce"),
            "minutes": threshold,
            "modeled_drive_miles": pd.to_numeric(
                frame.get(f"modeled_drive_miles_{threshold}min"), errors="coerce"
            ),
            "modeled_straightline_radius_miles": pd.to_numeric(
                frame.get(f"modeled_straightline_radius_miles_{threshold}min"), errors="coerce"
            ),
            "population": pd.to_numeric(
                frame.get(f"population_within_{threshold}min", 0), errors="coerce"
            ).fillna(0),
            "newly_accessible_population": pd.to_numeric(
                frame.get(f"newly_accessible_population_{threshold}min", 0), errors="coerce"
            ).fillna(0),
            "existing_hospitals": pd.to_numeric(
                frame.get(f"existing_hospitals_{threshold}min", 0), errors="coerce"
            ).fillna(0),
            "existing_beds": pd.to_numeric(
                frame.get(f"existing_beds_{threshold}min", 0), errors="coerce"
            ).fillna(0),
            "travel_time_model": frame["travel_time_model"].astype(str),
            "routing_refined": frame["routing_refined"].astype(bool),
        })
        rows.append(part)
    return pd.concat(rows, ignore_index=True)
