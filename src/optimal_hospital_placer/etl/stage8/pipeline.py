from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from .common import new_run_dir, numeric, percentile_score, read_json, utc_now, write_json
from .config import SERVICES, Stage8Config
from .services import add_service_recommendations
from .travel import add_travel_metrics, travel_access_long


def latest_run(root: Path, stage: str) -> Path:
    pointer = root / "data" / stage / "latest_success.json"
    if not pointer.exists():
        raise FileNotFoundError(f"Missing {pointer}. Run {stage} first.")
    data = read_json(pointer)
    if data.get("status") != "complete":
        raise RuntimeError(f"{pointer} is not status=complete")
    return Path(data["run_directory"]).resolve()


def load_stage7(stage7_run: Path, source_table: str) -> pd.DataFrame:
    names = {
        "finalists": "finalists.parquet",
        "top-sites": "top_sites.parquet",
        "top_sites": "top_sites.parquet",
    }
    if source_table not in names:
        raise ValueError(f"Unknown source_table={source_table!r}; expected finalists or top-sites")
    path = stage7_run / names[source_table]
    if not path.exists():
        raise FileNotFoundError(f"Missing Stage 7 input: {path}")
    frame = pd.read_parquet(path)
    required = {
        "site_id", "latitude", "longitude", "source_tract_geoid",
        "overall_score", "proposed_beds", "population_within_30min",
        "newly_accessible_population_30min", "nearest_existing_hospital_minutes",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"Stage 7 input is missing required columns: {missing}")
    if frame["site_id"].duplicated().any():
        # Stage 8 is physical-site oriented. If a source with multiple configurations
        # slips through, preserve the best Stage 7 scenario per site.
        frame = frame.sort_values("overall_score", ascending=False).drop_duplicates("site_id", keep="first")
    return frame.reset_index(drop=True)


def load_stage5_source_demographics(root: Path, sites: pd.DataFrame) -> pd.DataFrame:
    try:
        stage5 = latest_run(root, "stage5")
    except Exception:
        return sites

    path = stage5 / "tract_features.parquet"
    if not path.exists():
        return sites

    tracts = pd.read_parquet(path)
    geoid_col = next((c for c in ["tract_geoid", "geoid", "GEOID"] if c in tracts.columns), None)
    if geoid_col is None:
        return sites

    desired = [
        geoid_col,
        "population_under_18_pct",
        "population_age_65_plus_pct",
        "poverty_pct",
        "uninsured_pct",
        "disability_pct",
    ]
    # Preserve RUCA/rurality columns if available so distance proxy mirrors Stage 6 better.
    desired += [c for c in tracts.columns if ("ruca" in c.lower() or "rural" in c.lower()) and c not in desired]
    desired = [c for c in desired if c in tracts.columns]

    demo = tracts[desired].copy()
    demo[geoid_col] = demo[geoid_col].astype(str)
    demo = demo.drop_duplicates(geoid_col)

    rename = {geoid_col: "source_tract_geoid"}
    for c in desired:
        if c == geoid_col:
            continue
        if c in {
            "population_under_18_pct", "population_age_65_plus_pct",
            "poverty_pct", "uninsured_pct", "disability_pct",
        }:
            rename[c] = f"source_{c}"
    demo = demo.rename(columns=rename)

    result = sites.copy()
    result["source_tract_geoid"] = result["source_tract_geoid"].astype(str)
    return result.merge(demo, on="source_tract_geoid", how="left", suffixes=("", "_stage5"))


def _frontend_priority(frame: pd.DataFrame) -> pd.Series:
    # Store a useful default, but the API should still re-rank/filter by viewport.
    return (
        0.65 * numeric(frame, "stage8_score", 0) +
        0.20 * percentile_score(numeric(frame, "newly_accessible_population_30min", 0)) +
        0.15 * numeric(frame, "service_fit_score", 0)
    ).clip(0, 1)


def run_stage8(
    root: Path,
    cfg: Stage8Config,
    stage7_run: Path | None = None,
    states: list[str] | None = None,
) -> Path:
    stage7 = stage7_run.resolve() if stage7_run else latest_run(root, "stage7")
    sites = load_stage7(stage7, cfg.source_table)

    if states:
        wanted = {str(s).zfill(2) for s in states}
        if "state_fips" not in sites.columns:
            raise RuntimeError("Stage 7 source has no state_fips column")
        sites = sites.loc[sites["state_fips"].astype(str).str.zfill(2).isin(wanted)].copy()

    if cfg.max_sites > 0:
        sites = sites.sort_values("overall_score", ascending=False).head(cfg.max_sites).copy()

    if sites.empty:
        raise RuntimeError("No Stage 7 finalist sites remain for Stage 8")

    sites = load_stage5_source_demographics(root, sites)

    out_root = root / "data" / "stage8"
    run = new_run_dir(out_root)
    manifest = {
        "status": "running",
        "stage7_run": str(stage7),
        "config": asdict(cfg),
        "source_rows": len(sites),
        "states": states or "all",
        "started_utc": utc_now(),
    }
    write_json(run / "manifest.json", manifest)

    try:
        print(f"Reading Stage 7: {stage7}", flush=True)
        print(f"Refining {len(sites):,} physical sites with service + travel features...", flush=True)

        refined = add_travel_metrics(sites, cfg)
        refined, service_long = add_service_recommendations(refined, cfg)

        # Final Stage 8 score: keep Stage 7 as the majority signal, but make
        # drive/access and service need materially affect the final ordering.
        stage7_score = numeric(refined, "overall_score", 0).clip(0, 1)
        refined["stage8_score"] = (
            cfg.weight_stage7 * stage7_score +
            cfg.weight_drive_access * numeric(refined, "drive_access_score", 0).clip(0, 1) +
            cfg.weight_service_fit * numeric(refined, "service_fit_score", 0).clip(0, 1)
        ).clip(0, 1)

        refined["stage8_rank"] = refined["stage8_score"].rank(method="first", ascending=False).astype(int)
        if "state_fips" in refined.columns:
            refined["stage8_state_rank"] = refined.groupby(
                refined["state_fips"].astype(str).str.zfill(2)
            )["stage8_score"].rank(method="first", ascending=False).astype(int)
        refined["frontend_priority_score"] = _frontend_priority(refined)
        refined["stage8_model"] = cfg.model_name

        # A routing-refinement tier flag lets the frontend/API distinguish
        # "worth precise routing" from the much larger discoverable pool.
        # This is intentionally percentile-based rather than a tiny hard global cutoff.
        refined["precise_routing_priority"] = (
            refined["stage8_score"] >= refined["stage8_score"].quantile(0.98)
        ) | (
            refined.get("stage8_state_rank", pd.Series(999999, index=refined.index)) <= 3
        )

        travel_long = travel_access_long(refined)

        refined = refined.sort_values("stage8_score", ascending=False).reset_index(drop=True)
        refined.to_parquet(run / "final_candidates.parquet", index=False, compression="zstd")
        service_long.to_parquet(run / "service_recommendations.parquet", index=False, compression="zstd")
        travel_long.to_parquet(run / "travel_access_summary.parquet", index=False, compression="zstd")
        refined.loc[refined["precise_routing_priority"]].to_parquet(
            run / "precise_routing_queue.parquet", index=False, compression="zstd"
        )

        assumptions = {
            "stage8_model": cfg.model_name,
            "distance_model": cfg.distance_model,
            "service_model": cfg.service_model,
            "travel_note": (
                "Stage 8 consumes Stage 6 modeled drive times/catchments and derives drive-distance "
                "proxies using the same urban/rural effective-speed family. These are not exact routed miles."
            ),
            "routing_note": (
                "routing_refined=false means modeled travel. precise_routing_priority marks sites suitable "
                "for later site-local Valhalla refinement without removing other discoverable candidates."
            ),
            "service_note": (
                "Department recommendations are transparent comparative planning heuristics, not clinical "
                "utilization forecasts or claims that a service is medically/financially required."
            ),
            "services": [
                {
                    "service_id": s.service_id,
                    "display_name": s.display_name,
                    "minimum_beds": s.min_beds,
                    "recommendation_threshold": s.recommendation_threshold,
                    "description": s.description,
                } for s in SERVICES
            ],
        }
        write_json(run / "assumptions.json", assumptions)

        summary = {
            "status": "complete",
            "source_stage7": str(stage7),
            "sites": int(len(refined)),
            "service_rows": int(len(service_long)),
            "travel_rows": int(len(travel_long)),
            "precise_routing_priority_sites": int(refined["precise_routing_priority"].sum()),
            "routing_refined_sites": int(refined["routing_refined"].fillna(False).astype(bool).sum()),
            "mean_recommended_services": float(refined["recommended_service_count"].mean()),
            "top_stage8_score": float(refined["stage8_score"].max()),
            "completed_utc": utc_now(),
        }
        write_json(run / "summary.json", summary)

        manifest.update({
            "status": "complete",
            "completed_utc": utc_now(),
            "outputs": {
                "final_candidates": str(run / "final_candidates.parquet"),
                "service_recommendations": str(run / "service_recommendations.parquet"),
                "travel_access_summary": str(run / "travel_access_summary.parquet"),
                "precise_routing_queue": str(run / "precise_routing_queue.parquet"),
            },
        })
        write_json(run / "manifest.json", manifest)

        pointer = {
            "status": "complete",
            "run_directory": str(run.resolve()),
            "completed_utc": utc_now(),
            "stage8_model": cfg.model_name,
        }
        write_json(out_root / "latest_success.json", pointer)

        print(f"Stage 8 complete: {run}", flush=True)
        print(f"  final candidates: {len(refined):,}", flush=True)
        print(f"  precise-routing priority: {int(refined['precise_routing_priority'].sum()):,}", flush=True)
        return run

    except Exception as exc:
        manifest["status"] = "failed"
        manifest["failed_utc"] = utc_now()
        manifest["error"] = repr(exc)
        write_json(run / "manifest.json", manifest)
        raise
