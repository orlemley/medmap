from __future__ import annotations

from dataclasses import dataclass, field

from .road_model import ApproxRoadModel


@dataclass(frozen=True)
class Stage6FastConfig:
    # One tract representative point is the fast/default candidate. More than one
    # can be requested, but no road snapping is performed in this hackathon model.
    candidates_per_tract: int = 1

    # Straight-line neighborhoods used before the approximate drive model.
    demand_prefilter_miles: float = 70.0
    hospital_prefilter_miles: float = 110.0

    access_minutes: tuple[int, ...] = (15, 30, 45, 60)
    improvement_minutes: tuple[int, ...] = (10, 20, 30)

    # Existing baseline nearest hospital. Querying the nearest K spatial hospitals
    # makes the baseline cheap while still allowing road-factor reordering.
    baseline_nearest_hospitals_k: int = 12

    # Keep candidate computation memory bounded.
    candidate_progress_every: int = 250

    road_model: ApproxRoadModel = field(default_factory=ApproxRoadModel)
