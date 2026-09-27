from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ApproxRoadModel:
    """Fast screening approximation for automobile travel.

    These are explicit modeling assumptions, not observed road travel times.
    Stage 7 (or a finalist-refinement job) can replace them with precise routing
    for the small number of candidates that survive optimization.
    """

    urban_detour_factor: float = 1.20
    rural_detour_factor: float = 1.34
    urban_effective_mph: float = 29.0
    rural_effective_mph: float = 52.0
    minimum_effective_mph: float = 10.0


def numeric(frame: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[name], errors="coerce").fillna(default).astype(float)


def rurality_fraction(frame: pd.DataFrame) -> pd.Series:
    """Extract a 0..1 rurality proxy from whichever Stage-5/RUCA field exists."""
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

    # RUCA primary codes: 1-3 metropolitan, 4-6 micropolitan/small town,
    # 7-10 increasingly rural. This mapping is only a computational proxy.
    for col in [c for c in frame.columns if "ruca" in c.lower()]:
        s = pd.to_numeric(frame[col], errors="coerce")
        if s.notna().any():
            return ((s - 1.0) / 9.0).clip(0, 1).fillna(0.0)

    return pd.Series(0.0, index=frame.index, dtype="float64")


def road_parameters(frame: pd.DataFrame, model: ApproxRoadModel) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rural = rurality_fraction(frame).to_numpy(float)
    detour = model.urban_detour_factor + rural * (model.rural_detour_factor - model.urban_detour_factor)
    mph = model.urban_effective_mph + rural * (model.rural_effective_mph - model.urban_effective_mph)
    mph = np.maximum(mph, model.minimum_effective_mph)
    return rural, detour, mph


def estimated_drive_minutes(
    straight_line_miles,
    detour_factor,
    effective_mph,
    minimum_effective_mph: float = 10.0,
):
    miles = np.asarray(straight_line_miles, dtype=float)
    detour = np.asarray(detour_factor, dtype=float)
    mph = np.maximum(np.asarray(effective_mph, dtype=float), minimum_effective_mph)
    return miles * detour / mph * 60.0
