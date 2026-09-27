from __future__ import annotations

from typing import Annotated
from pydantic import BaseModel, Field, model_validator


class OptimizeWeights(BaseModel):
    access: float = Field(0.22, ge=0)
    capacity: float = Field(0.18, ge=0)
    vulnerability: float = Field(0.12, ge=0)
    configuration_fit: float = Field(0.12, ge=0)
    cost_efficiency: float = Field(0.08, ge=0)
    drive_access: float = Field(0.16, ge=0)
    service_fit: float = Field(0.12, ge=0)

    @model_validator(mode="after")
    def nonzero(self):
        if sum(self.model_dump().values()) <= 0:
            raise ValueError("At least one optimization weight must be greater than zero")
        return self


class OptimizeRequest(BaseModel):
    weights: OptimizeWeights = Field(default_factory=OptimizeWeights)
    state: str | None = None
    bbox: str | None = Field(None, description="west,south,east,north")
    limit: int = Field(100, ge=1, le=2000)
    min_score: float | None = Field(None, ge=0, le=1)
    min_beds: int | None = Field(None, ge=0)
    max_beds: int | None = Field(None, ge=0)
    services: list[str] = Field(default_factory=list)
    require_all_services: bool = False
    routing_refined: bool | None = None
    diversify: bool = True
