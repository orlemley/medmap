from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class HospitalConfiguration:
    configuration_id: str
    display_name: str
    beds: int
    icu_beds: int
    ed_bays: int
    has_emergency: bool
    has_surgery: bool
    has_maternity: bool
    has_cardiology: bool
    min_catchment_population_45min: int
    fixed_capital_cost_musd: float
    capital_cost_per_bed_musd: float
    operating_cost_index: float

    @property
    def estimated_capital_cost_musd(self) -> float:
        return self.fixed_capital_cost_musd + self.beds * self.capital_cost_per_bed_musd

    def to_dict(self) -> dict:
        data = asdict(self)
        data["estimated_capital_cost_musd"] = self.estimated_capital_cost_musd
        return data


# These are transparent planning archetypes, not claims about a universal hospital standard.
DEFAULT_CONFIGURATIONS: tuple[HospitalConfiguration, ...] = (
    HospitalConfiguration(
        "rural_25", "Rural / critical-access proxy", 25, 4, 8,
        True, True, False, False,
        10_000, 55.0, 1.15, 0.45,
    ),
    HospitalConfiguration(
        "community_50", "Small community hospital", 50, 6, 12,
        True, True, False, False,
        20_000, 85.0, 1.05, 0.60,
    ),
    HospitalConfiguration(
        "community_100", "Community hospital", 100, 12, 20,
        True, True, True, False,
        45_000, 135.0, 0.95, 0.78,
    ),
    HospitalConfiguration(
        "regional_200", "Regional hospital", 200, 24, 32,
        True, True, True, True,
        90_000, 220.0, 0.90, 1.00,
    ),
    HospitalConfiguration(
        "regional_300", "Large regional hospital", 300, 36, 44,
        True, True, True, True,
        150_000, 310.0, 0.88, 1.20,
    ),
)


@dataclass(frozen=True)
class Stage7Config:
    # Planning assumption only; intentionally configurable.
    target_beds_per_1000: float = 2.5

    # Default composite score. API can reweight the stored components later.
    weight_access: float = 0.30
    weight_capacity: float = 0.25
    weight_vulnerability: float = 0.15
    weight_configuration_fit: float = 0.20
    weight_cost_efficiency: float = 0.10

    # Keep enough finalists for UI/API exploration and optional precise routing.
    finalist_unique_sites: int = 50
    refinement_unique_sites: int = 20

    # Prevent a very poor configuration fit from winning solely due to site need.
    minimum_configuration_fit: float = 0.05

    cost_model: str = "planning_proxy_v1"
    configuration_model: str = "hospital_archetypes_v1"
