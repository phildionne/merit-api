from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator


class LineStringGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["LineString"]
    coordinates: list[tuple[float, float]]

    @model_validator(mode="after")
    def validate_coordinates(self) -> "LineStringGeometry":
        if len(self.coordinates) < 2:
            raise ValueError("LineString must contain at least two coordinates")

        for lng, lat in self.coordinates:
            if not -180 <= lng <= 180:
                raise ValueError("Longitude must be between -180 and 180")
            if not -90 <= lat <= 90:
                raise ValueError("Latitude must be between -90 and 90")
        return self


class GeoJsonFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["Feature"]
    geometry: LineStringGeometry
    properties: dict[str, Any] | None = None


class FeatureCollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["FeatureCollection"]
    features: list[GeoJsonFeature]

    @model_validator(mode="after")
    def validate_feature_count(self) -> "FeatureCollectionRequest":
        if len(self.features) != 1:
            raise ValueError("FeatureCollection must contain exactly one feature")
        return self


class ElevationsRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    geojson: FeatureCollectionRequest
    density_m: float = Field(gt=100.0)


class HealthResponse(BaseModel):
    ok: bool
    status: Literal["alive"]


class ReadyResponse(BaseModel):
    ok: bool
    status: Literal["ready", "not_ready"]
    checks: dict[str, bool]


class ProfilePointResponse(BaseModel):
    chainage_m: float
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


class ElevationProfileDataResponse(BaseModel):
    start_point: ProfilePointResponse
    end_point: ProfilePointResponse
    points: list[ProfilePointResponse]


class ElevationProfileResponse(BaseModel):
    version: Literal[1]
    source: SourceMetaResponse
    line_length_m: float
    quality: QualityResponse
    data: ElevationProfileDataResponse
