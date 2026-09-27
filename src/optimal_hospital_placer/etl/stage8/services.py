from __future__ import annotations

import numpy as np
import pandas as pd

from .common import numeric, percentile_score, sat
from .config import SERVICES, Stage8Config


def _share(numer: pd.Series, denom: pd.Series) -> pd.Series:
    d = pd.to_numeric(denom, errors="coerce").replace(0, np.nan)
    return (pd.to_numeric(numer, errors="coerce") / d).replace([np.inf, -np.inf], np.nan).fillna(0).clip(0, 1)


def _score_inputs(frame: pd.DataFrame) -> dict[str, pd.Series]:
    pop30 = numeric(frame, "population_within_30min", 0)
    pop45 = numeric(frame, "population_within_45min", 0)
    elderly30 = numeric(frame, "elderly_population_30min", 0)
    poverty30 = numeric(frame, "poverty_population_30min", 0)
    uninsured30 = numeric(frame, "uninsured_population_30min", 0)
    disabled30 = numeric(frame, "disabled_population_30min", 0)

    source_under18_pct = numeric(frame, "source_population_under_18_pct", 0)
    source_under18 = (source_under18_pct / 100.0).clip(0, 1)

    return {
        "pop30": sat(pop30, 50_000),
        "pop45": sat(pop45, 100_000),
        "elderly_share": _share(elderly30, pop30),
        "poverty_share": _share(poverty30, pop30),
        "uninsured_share": _share(uninsured30, pop30),
        "disabled_share": _share(disabled30, pop30),
        "under18_share": source_under18,
        "access": numeric(frame, "access_score", numeric(frame, "stage6_access_score", 0)).clip(0, 1),
        "capacity": numeric(frame, "capacity_score", numeric(frame, "capacity_gap_score", 0)).clip(0, 1),
        "vulnerability": numeric(frame, "vulnerability_score", numeric(frame, "vulnerability_catchment_score", 0)).clip(0, 1),
        "drive": numeric(frame, "drive_access_score", 0).clip(0, 1),
        "isolation": numeric(frame, "stage8_isolation_score", 0).clip(0, 1),
        "beds": sat(numeric(frame, "proposed_beds", 0), 100.0),
    }


def service_scores(frame: pd.DataFrame) -> dict[str, pd.Series]:
    x = _score_inputs(frame)

    # Transparent heuristic service-need models. These are comparative planning
    # proxies, not clinical utilization forecasts.
    return {
        "emergency": (
            0.30*x["isolation"] + 0.25*x["drive"] + 0.20*x["pop30"] +
            0.15*x["vulnerability"] + 0.10*x["capacity"]
        ).clip(0, 1),
        "icu": (
            0.25*x["pop45"] + 0.25*x["elderly_share"] + 0.20*x["capacity"] +
            0.15*x["drive"] + 0.15*x["beds"]
        ).clip(0, 1),
        "general_surgery": (
            0.30*x["pop30"] + 0.25*x["capacity"] + 0.20*x["access"] +
            0.15*x["drive"] + 0.10*x["beds"]
        ).clip(0, 1),
        "maternity": (
            0.35*x["under18_share"] + 0.25*x["pop30"] + 0.15*x["uninsured_share"] +
            0.15*x["drive"] + 0.10*x["access"]
        ).clip(0, 1),
        "cardiology": (
            0.30*x["elderly_share"] + 0.25*x["pop45"] + 0.20*x["capacity"] +
            0.15*x["beds"] + 0.10*x["drive"]
        ).clip(0, 1),
        "stroke": (
            0.30*x["elderly_share"] + 0.25*x["isolation"] + 0.20*x["drive"] +
            0.15*x["pop30"] + 0.10*x["capacity"]
        ).clip(0, 1),
        "behavioral_health": (
            0.20*x["poverty_share"] + 0.20*x["uninsured_share"] +
            0.20*x["vulnerability"] + 0.20*x["pop30"] + 0.20*x["drive"]
        ).clip(0, 1),
        "pediatrics": (
            0.40*x["under18_share"] + 0.25*x["pop30"] + 0.15*x["vulnerability"] +
            0.10*x["drive"] + 0.10*x["access"]
        ).clip(0, 1),
        "advanced_imaging": (
            0.30*x["pop30"] + 0.20*x["capacity"] + 0.20*x["access"] +
            0.15*x["beds"] + 0.15*x["drive"]
        ).clip(0, 1),
        "oncology": (
            0.30*x["pop45"] + 0.25*x["elderly_share"] + 0.20*x["beds"] +
            0.15*x["capacity"] + 0.10*x["access"]
        ).clip(0, 1),
        "dialysis": (
            0.25*x["elderly_share"] + 0.15*x["poverty_share"] +
            0.15*x["disabled_share"] + 0.20*x["drive"] +
            0.15*x["capacity"] + 0.10*x["pop30"]
        ).clip(0, 1),
    }


def _archetype_includes(frame: pd.DataFrame, service_id: str) -> pd.Series:
    mapping = {
        "emergency": "has_emergency",
        "icu": "proposed_icu_beds",
        "general_surgery": "has_surgery",
        "maternity": "has_maternity",
        "cardiology": "has_cardiology",
    }
    col = mapping.get(service_id)
    if col is None or col not in frame.columns:
        return pd.Series(False, index=frame.index)
    if col == "proposed_icu_beds":
        return numeric(frame, col, 0) > 0
    return frame[col].fillna(False).astype(bool)


def add_service_recommendations(frame: pd.DataFrame, cfg: Stage8Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    wide = frame.copy()
    scores = service_scores(wide)

    long_rows = []
    proposed_beds = numeric(wide, "proposed_beds", 0)

    for service in SERVICES:
        score = scores[service.service_id]
        threshold = min(1.0, max(0.0, service.recommendation_threshold + cfg.service_threshold_adjustment))
        size_ok = proposed_beds >= service.min_beds
        recommended = (score >= threshold) & size_ok
        archetype_has = _archetype_includes(wide, service.service_id)

        wide[f"service_{service.service_id}_score"] = score
        wide[f"service_{service.service_id}_recommended"] = recommended
        wide[f"service_{service.service_id}_archetype_includes"] = archetype_has
        wide[f"service_{service.service_id}_gap"] = recommended & ~archetype_has

        long_rows.append(pd.DataFrame({
            "site_id": wide["site_id"].astype(str),
            "candidate_id": wide.get("candidate_id", wide["site_id"]).astype(str),
            "configuration_id": wide.get("configuration_id", pd.Series("", index=wide.index)).astype(str),
            "service_id": service.service_id,
            "service_name": service.display_name,
            "service_score": score,
            "recommendation_threshold": threshold,
            "minimum_beds": service.min_beds,
            "size_eligible": size_ok,
            "recommended": recommended,
            "archetype_includes": archetype_has,
            "service_gap": recommended & ~archetype_has,
            "description": service.description,
        }))

    long = pd.concat(long_rows, ignore_index=True)

    # Keep at most N recommendations per physical site, prioritized by score.
    long["service_rank_within_site"] = long.groupby("site_id")["service_score"].rank(
        method="first", ascending=False
    ).astype(int)
    long["recommended"] = (
        long["recommended"] &
        long["service_rank_within_site"].le(cfg.max_recommended_services)
    )
    long["service_gap"] = long["recommended"] & ~long["archetype_includes"]

    # Sync final capped recommendations back to wide form.
    for service in SERVICES:
        sub = long.loc[long["service_id"].eq(service.service_id), ["site_id", "recommended", "service_gap"]]
        rec_map = sub.set_index("site_id")["recommended"]
        gap_map = sub.set_index("site_id")["service_gap"]
        wide[f"service_{service.service_id}_recommended"] = wide["site_id"].astype(str).map(rec_map).fillna(False).astype(bool)
        wide[f"service_{service.service_id}_gap"] = wide["site_id"].astype(str).map(gap_map).fillna(False).astype(bool)

    service_score_cols = [f"service_{s.service_id}_score" for s in SERVICES]
    rec_cols = [f"service_{s.service_id}_recommended" for s in SERVICES]
    gap_cols = [f"service_{s.service_id}_gap" for s in SERVICES]

    wide["recommended_service_count"] = wide[rec_cols].sum(axis=1).astype(int)
    wide["service_gap_count"] = wide[gap_cols].sum(axis=1).astype(int)

    # Service fit rewards strong service demand signals that the proposed scale can support.
    top3 = np.sort(wide[service_score_cols].to_numpy(float), axis=1)[:, -3:]
    wide["service_fit_score"] = np.nanmean(top3, axis=1)
    wide["service_model"] = cfg.service_model

    # Human/API friendly comma-separated list.
    def names_for_row(row):
        names = []
        for s in SERVICES:
            if bool(row[f"service_{s.service_id}_recommended"]):
                names.append(s.display_name)
        return ", ".join(names)

    wide["recommended_services"] = wide.apply(names_for_row, axis=1)
    return wide, long.sort_values(["site_id", "service_rank_within_site"]).reset_index(drop=True)
