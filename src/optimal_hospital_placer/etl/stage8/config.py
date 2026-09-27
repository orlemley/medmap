from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceDefinition:
    service_id: str
    display_name: str
    min_beds: int
    recommendation_threshold: float
    description: str


SERVICES: tuple[ServiceDefinition, ...] = (
    ServiceDefinition("emergency", "Emergency Department", 0, 0.48,
                      "Emergency access proxy emphasizing isolation, new access, and local need."),
    ServiceDefinition("icu", "Intensive Care Unit", 25, 0.55,
                      "ICU proxy emphasizing population, elderly demand, capacity gap, and access."),
    ServiceDefinition("general_surgery", "General Surgery", 25, 0.52,
                      "Surgical-service proxy emphasizing market size, access, and bed-capacity gap."),
    ServiceDefinition("maternity", "Maternity / Labor & Delivery", 50, 0.56,
                      "Maternity proxy using local youth share, market size, insurance vulnerability, and access."),
    ServiceDefinition("cardiology", "Cardiology", 100, 0.58,
                      "Cardiology proxy emphasizing elderly demand, regional market size, and capacity gap."),
    ServiceDefinition("stroke", "Stroke Capability", 50, 0.56,
                      "Stroke-service proxy emphasizing elderly demand, isolation, access improvement, and population."),
    ServiceDefinition("behavioral_health", "Behavioral Health", 25, 0.52,
                      "Behavioral-health proxy using socioeconomic vulnerability, population, and access."),
    ServiceDefinition("pediatrics", "Pediatrics", 25, 0.53,
                      "Pediatric proxy using local under-18 share, population, vulnerability, and access."),
    ServiceDefinition("advanced_imaging", "Advanced Imaging", 25, 0.50,
                      "Imaging proxy emphasizing population, capacity gap, access, and hospital scale."),
    ServiceDefinition("oncology", "Oncology", 100, 0.61,
                      "Oncology proxy emphasizing regional population, older population, and hospital scale."),
    ServiceDefinition("dialysis", "Dialysis", 25, 0.55,
                      "Dialysis proxy emphasizing older/vulnerable population, isolation, and capacity gap."),
)


@dataclass(frozen=True)
class Stage8Config:
    # Stage 7 source. "finalists" is ideal when you intentionally retained thousands.
    source_table: str = "finalists"
    max_sites: int = 0  # 0 = all rows in source table

    # Default composite. Component fields remain available for API reweighting.
    weight_stage7: float = 0.55
    weight_drive_access: float = 0.25
    weight_service_fit: float = 0.20

    # Recommendation behavior.
    service_threshold_adjustment: float = 0.0
    max_recommended_services: int = 8

    # Same transparent road approximation family used by fast Stage 6.
    urban_detour_factor: float = 1.20
    rural_detour_factor: float = 1.34
    urban_effective_mph: float = 29.0
    rural_effective_mph: float = 52.0

    model_name: str = "finalist_service_travel_refinement_v1"
    distance_model: str = "stage6_time_consistent_distance_proxy_v1"
    service_model: str = "service_gap_proxy_v1"
