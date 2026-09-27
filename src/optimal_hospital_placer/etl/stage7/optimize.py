from __future__ import annotations

from dataclasses import asdict
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from .common import new_run_dir, numeric, percentile_score, read_json, utc_now, weighted_mean, write_json
from .config import DEFAULT_CONFIGURATIONS, HospitalConfiguration, Stage7Config


STAGE7_MODEL = "site_configuration_optimizer_v1"


def latest_stage6(root: Path) -> Path:
    pointer = root / "data" / "stage6" / "latest_success.json"
    if not pointer.exists():
        raise FileNotFoundError("Missing data/stage6/latest_success.json. Run Stage 6 first.")
    published = read_json(pointer)
    if published.get("status") != "complete":
        raise RuntimeError("Latest Stage 6 pointer is not status=complete")
    return Path(published["run_directory"]).resolve()


def load_stage6(stage6_run: Path) -> pd.DataFrame:
    path = stage6_run / "candidate_site_features.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing Stage 6 candidate features: {path}")
    frame = pd.read_parquet(path)
    required = {
        "site_id", "latitude", "longitude", "source_tract_geoid",
        "population_within_30min", "population_within_45min",
        "newly_accessible_population_30min", "existing_beds_30min",
        "access_improvement_score", "capacity_gap_score",
        "vulnerability_catchment_score", "stage6_access_score",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"Stage 6 output is missing required columns: {missing}")
    if frame["site_id"].duplicated().any():
        raise RuntimeError("Stage 6 candidate_site_features contains duplicate site_id values")
    return frame


def _bed_gap_fit(unmet_beds: pd.Series, proposed_beds: int) -> pd.Series:
    """1 when proposed capacity is close to modeled unmet capacity; 0 when no gap."""
    gap = pd.to_numeric(unmet_beds, errors="coerce").fillna(0).clip(lower=0)
    proposed = float(proposed_beds)
    larger = np.maximum(gap.to_numpy(float), proposed)
    smaller = np.minimum(gap.to_numpy(float), proposed)
    fit = np.divide(smaller, larger, out=np.zeros_like(larger), where=larger > 0)
    return pd.Series(fit, index=gap.index).clip(0, 1)


def _market_support(pop45: pd.Series, minimum: int) -> pd.Series:
    pop = pd.to_numeric(pop45, errors="coerce").fillna(0).clip(lower=0)
    if minimum <= 0:
        return pd.Series(1.0, index=pop.index)
    return (pop / float(minimum)).clip(0, 1)


def _oversize_penalty(pop45: pd.Series, minimum: int) -> pd.Series:
    """Soft penalty for configurations whose market is far below the archetype floor."""
    support = _market_support(pop45, minimum)
    # Full credit at/above minimum; smoothly falls below it.
    return np.sqrt(support).clip(0, 1)


def expand_configurations(
    sites: pd.DataFrame,
    cfg: Stage7Config,
    configurations: tuple[HospitalConfiguration, ...] = DEFAULT_CONFIGURATIONS,
) -> pd.DataFrame:
    base = sites.reset_index(drop=True).copy()
    pop30 = numeric(base, "population_within_30min", 0).clip(lower=0)
    pop45 = numeric(base, "population_within_45min", 0).clip(lower=0)
    existing_beds30 = numeric(base, "existing_beds_30min", 0).clip(lower=0)
    target_beds30 = pop30 * cfg.target_beds_per_1000 / 1000.0
    unmet_beds30 = (target_beds30 - existing_beds30).clip(lower=0)

    rows: list[pd.DataFrame] = []
    for hospital in configurations:
        part = base.copy()
        part["configuration_id"] = hospital.configuration_id
        part["configuration_name"] = hospital.display_name
        part["proposed_beds"] = hospital.beds
        part["proposed_icu_beds"] = hospital.icu_beds
        part["proposed_ed_bays"] = hospital.ed_bays
        part["has_emergency"] = hospital.has_emergency
        part["has_surgery"] = hospital.has_surgery
        part["has_maternity"] = hospital.has_maternity
        part["has_cardiology"] = hospital.has_cardiology
        part["estimated_capital_cost_musd"] = hospital.estimated_capital_cost_musd
        part["operating_cost_index"] = hospital.operating_cost_index
        part["min_catchment_population_45min"] = hospital.min_catchment_population_45min
        part["target_beds_30min"] = target_beds30.to_numpy()
        part["modeled_unmet_beds_30min"] = unmet_beds30.to_numpy()
        part["modeled_remaining_bed_gap_30min"] = np.maximum(
            0.0, unmet_beds30.to_numpy() - float(hospital.beds)
        )
        part["modeled_capacity_added_pct_of_gap"] = np.where(
            unmet_beds30.to_numpy() > 0,
            np.minimum(1.0, float(hospital.beds) / unmet_beds30.to_numpy()),
            0.0,
        )

        bed_fit = _bed_gap_fit(unmet_beds30, hospital.beds)
        support = _market_support(pop45, hospital.min_catchment_population_45min)
        size_safety = _oversize_penalty(pop45, hospital.min_catchment_population_45min)

        # Rural/small configurations get modest fit credit where existing access is poor;
        # large configurations get their fit primarily from market size/capacity gap.
        nearest = numeric(base, "nearest_existing_hospital_minutes", 0).clip(lower=0)
        isolation = (nearest / 45.0).clip(0, 1)
        if hospital.beds <= 50:
            access_alignment = 0.65 * isolation + 0.35 * numeric(base, "new_access_score", 0).clip(0, 1)
        else:
            access_alignment = 0.35 * isolation + 0.65 * numeric(base, "capacity_gap_score", 0).clip(0, 1)

        fit = (0.45 * bed_fit + 0.30 * support + 0.25 * access_alignment) * size_safety
        part["bed_gap_fit_score"] = bed_fit.to_numpy()
        part["market_support_score"] = support.to_numpy()
        part["access_alignment_score"] = np.asarray(access_alignment)
        part["configuration_fit_score"] = np.asarray(fit).clip(0, 1)

        raw_id = part["site_id"].astype(str) + "|" + hospital.configuration_id
        part["candidate_id"] = raw_id.map(lambda x: "S7-" + hashlib.sha1(x.encode()).hexdigest()[:16])
        rows.append(part)

    scenarios = pd.concat(rows, ignore_index=True)

    # Benefit proxy stays in native units until we normalize cost efficiency.
    access_benefit = numeric(scenarios, "weighted_drive_minutes_saved", 0).clip(lower=0)
    newly30 = numeric(scenarios, "newly_accessible_population_30min", 0).clip(lower=0)
    gap_covered = np.minimum(
        numeric(scenarios, "modeled_unmet_beds_30min", 0).clip(lower=0),
        numeric(scenarios, "proposed_beds", 0).clip(lower=0),
    )
    raw_benefit = (
        np.log1p(access_benefit)
        + 2.0 * np.log1p(newly30)
        + 4.0 * np.log1p(gap_covered)
    )
    cost = numeric(scenarios, "estimated_capital_cost_musd", 1).clip(lower=1)
    scenarios["cost_efficiency_raw"] = raw_benefit / cost
    scenarios["cost_efficiency_score"] = percentile_score(scenarios["cost_efficiency_raw"])

    scenarios["access_score"] = (
        0.65 * numeric(scenarios, "access_improvement_score", 0).clip(0, 1)
        + 0.35 * numeric(scenarios, "new_access_score", 0).clip(0, 1)
    )
    scenarios["capacity_score"] = numeric(scenarios, "capacity_gap_score", 0).clip(0, 1)
    scenarios["vulnerability_score"] = numeric(scenarios, "vulnerability_catchment_score", 0).clip(0, 1)

    scenarios["overall_score"] = weighted_mean(scenarios, [
        ("access_score", cfg.weight_access),
        ("capacity_score", cfg.weight_capacity),
        ("vulnerability_score", cfg.weight_vulnerability),
        ("configuration_fit_score", cfg.weight_configuration_fit),
        ("cost_efficiency_score", cfg.weight_cost_efficiency),
    ])

    # Avoid selecting implausibly oversized archetypes just because the site itself is strong.
    bad_fit = numeric(scenarios, "configuration_fit_score", 0) < cfg.minimum_configuration_fit
    scenarios.loc[bad_fit, "overall_score"] *= 0.25
    scenarios["configuration_feasible_proxy"] = ~bad_fit

    scenarios["stage7_model"] = STAGE7_MODEL
    scenarios["configuration_model"] = cfg.configuration_model
    scenarios["cost_model"] = cfg.cost_model
    scenarios["target_beds_per_1000_assumption"] = cfg.target_beds_per_1000
    scenarios["routing_refined"] = scenarios.get("routing_refined", False)
    scenarios["overall_rank"] = scenarios["overall_score"].rank(method="first", ascending=False).astype(int)
    scenarios["site_configuration_rank"] = scenarios.groupby("site_id")["overall_score"].rank(
        method="first", ascending=False
    ).astype(int)
    scenarios["state_rank"] = scenarios.groupby("state_fips")["overall_score"].rank(
        method="first", ascending=False
    ).astype(int)
    return scenarios.sort_values("overall_score", ascending=False).reset_index(drop=True)


def choose_top_sites(scenarios: pd.DataFrame) -> pd.DataFrame:
    top = scenarios.loc[scenarios["site_configuration_rank"].eq(1)].copy()
    top["site_rank"] = top["overall_score"].rank(method="first", ascending=False).astype(int)
    return top.sort_values("site_rank").reset_index(drop=True)


def pareto_frontier(scenarios: pd.DataFrame) -> pd.Series:
    """Small O(n^2) Pareto calculation for the already-filtered top-site set."""
    cols_max = ["access_score", "capacity_score", "vulnerability_score", "configuration_fit_score", "cost_efficiency_score"]
    arr = scenarios[cols_max].fillna(0).to_numpy(float)
    n = len(arr)
    optimal = np.ones(n, dtype=bool)
    for i in range(n):
        if not optimal[i]:
            continue
        dominates_i = np.all(arr >= arr[i], axis=1) & np.any(arr > arr[i], axis=1)
        dominates_i[i] = False
        if dominates_i.any():
            optimal[i] = False
    return pd.Series(optimal, index=scenarios.index)


def run_stage7(
    root: Path,
    cfg: Stage7Config,
    stage6_run: Path | None = None,
    states: list[str] | None = None,
) -> Path:
    stage6 = stage6_run.resolve() if stage6_run else latest_stage6(root)
    sites = load_stage6(stage6)
    if states:
        wanted = {str(x).zfill(2) for x in states}
        sites = sites.loc[sites["state_fips"].astype(str).str.zfill(2).isin(wanted)].copy()
    if sites.empty:
        raise RuntimeError("No Stage 6 candidate sites remain for Stage 7")

    out_root = root / "data" / "stage7"
    run = new_run_dir(out_root)
    manifest = {
        "status": "running",
        "stage6_run": str(stage6),
        "stage7_model": STAGE7_MODEL,
        "config": asdict(cfg),
        "configurations": [x.to_dict() for x in DEFAULT_CONFIGURATIONS],
        "states": states or "all",
        "started_utc": utc_now(),
    }
    write_json(run / "manifest.json", manifest)

    try:
        print(f"Reading Stage 6: {stage6}", flush=True)
        print(f"Evaluating {len(sites):,} sites x {len(DEFAULT_CONFIGURATIONS)} hospital configurations...", flush=True)
        scenarios = expand_configurations(sites, cfg)
        top_sites = choose_top_sites(scenarios)
        top_sites["pareto_optimal"] = pareto_frontier(top_sites)

        finalists = top_sites.head(min(cfg.finalist_unique_sites, len(top_sites))).copy()
        refinement = top_sites.head(min(cfg.refinement_unique_sites, len(top_sites))).copy()
        refinement["refinement_priority"] = np.arange(1, len(refinement) + 1)
        refinement["refinement_reason"] = "top_stage7_unique_site"

        scenarios.to_parquet(run / "candidate_hospitals.parquet", index=False, compression="zstd")
        top_sites.to_parquet(run / "top_sites.parquet", index=False, compression="zstd")
        finalists.to_parquet(run / "finalists.parquet", index=False, compression="zstd")
        refinement.to_parquet(run / "routing_refinement_queue.parquet", index=False, compression="zstd")

        assumptions = {
            "target_beds_per_1000": cfg.target_beds_per_1000,
            "cost_model": cfg.cost_model,
            "configuration_model": cfg.configuration_model,
            "note": "Hospital archetypes, bed target, and costs are planning proxies for comparative optimization, not project-level forecasts or clinical standards.",
            "configurations": [x.to_dict() for x in DEFAULT_CONFIGURATIONS],
        }
        write_json(run / "assumptions.json", assumptions)

        summary = {
            "source_sites": int(len(sites)),
            "hospital_configurations": int(len(DEFAULT_CONFIGURATIONS)),
            "candidate_hospital_scenarios": int(len(scenarios)),
            "unique_sites": int(len(top_sites)),
            "pareto_optimal_top_sites": int(top_sites["pareto_optimal"].sum()),
            "finalists_written": int(len(finalists)),
            "routing_refinement_sites": int(len(refinement)),
            "best_candidate_id": str(scenarios.iloc[0]["candidate_id"]),
            "best_site_id": str(scenarios.iloc[0]["site_id"]),
            "best_configuration_id": str(scenarios.iloc[0]["configuration_id"]),
            "best_overall_score": float(scenarios.iloc[0]["overall_score"]),
            "notes": [
                "Stage 7 ranks site + hospital-configuration scenarios using Stage 6 approximate accessibility features.",
                "The default overall score is reweightable at API time because component scores are stored separately.",
                "Precise road-network routing should be run only for routing_refinement_queue.parquet sites, then finalist scores can be refreshed.",
            ],
        }
        write_json(run / "summary.json", summary)
        manifest.update({"status": "complete", "completed_utc": utc_now(), "summary": summary})
        write_json(run / "manifest.json", manifest)
        write_json(out_root / "latest_success.json", {
            "status": "complete",
            "run_directory": str(run.resolve()),
            "stage6_run": str(stage6),
            "stage7_model": STAGE7_MODEL,
            "completed_utc": manifest["completed_utc"],
        })
        print(f"Stage 7 complete: {run}", flush=True)
        print(f"  {run / 'candidate_hospitals.parquet'}", flush=True)
        print(f"  {run / 'top_sites.parquet'}", flush=True)
        print(f"  {run / 'routing_refinement_queue.parquet'}", flush=True)
        return run
    except Exception:
        manifest.update({"status": "failed", "failed_utc": utc_now()})
        write_json(run / "manifest.json", manifest)
        raise
