from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_serializer, model_validator


class ElevationPointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    coordinates: tuple[float, float]

    @model_validator(mode="after")
    def validate_point(self) -> "ElevationPointRequest":
        if not self.id.strip():
            raise ValueError("Point id must be a non-empty string")

        lng, lat = self.coordinates
        if not -180 <= lng <= 180:
            raise ValueError("Longitude must be between -180 and 180")
        if not -90 <= lat <= 90:
            raise ValueError("Latitude must be between -90 and 90")
        return self


class ElevationsRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: list[ElevationPointRequest]

    @model_validator(mode="after")
    def validate_points(self) -> "ElevationsRequestBody":
        if not self.points:
            raise ValueError("points must contain at least one point")

        point_ids = [point.id for point in self.points]
        if len(point_ids) != len(set(point_ids)):
            raise ValueError("Point ids must be unique")
        return self


class HealthResponse(BaseModel):
    ok: bool
    status: Literal["alive"]


class ReadyResponse(BaseModel):
    ok: bool
    status: Literal["ready", "not_ready"]
    checks: dict[str, bool]


class SampledPointResponse(BaseModel):
    id: str
    elevation_m: float | None = None
    status: Literal["ok", "nodata", "out_of_coverage"]


class SourceMetaResponse(BaseModel):
    generated_at: datetime
    request_id: str

    @field_serializer("generated_at")
    def serialize_generated_at(self, generated_at: datetime) -> str:
        return generated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class QualityResponse(BaseModel):
    total: int
    ok: int
    nodata: int
    out_of_coverage: int
    coverage_ratio: float


class ElevationPointsDataResponse(BaseModel):
    points: list[SampledPointResponse]


class ElevationPointsResponse(BaseModel):
    version: Literal[1]
    source: SourceMetaResponse
    data: ElevationPointsDataResponse
    quality: QualityResponse
