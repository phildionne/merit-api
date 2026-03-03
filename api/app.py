import math
import os
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Sequence, Tuple

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_serializer, model_validator
from rasterio.errors import RasterioIOError

from . import dem

app = FastAPI(title="MERIT-Hydro API")

API_KEY = (os.getenv("API_KEY") or "").strip()
MAX_BATCH = int(os.getenv("MAX_BATCH", "1000"))
_origins_env = (os.getenv("ALLOWED_ORIGINS") or "*").strip()
ALLOWED_ORIGINS = ["*"] if _origins_env == "*" else [o.strip() for o in _origins_env.split(",") if o.strip()]
EARTH_RADIUS_M = 6371008.8

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: str = Depends(api_key_header)) -> None:
    if not API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key not configured",
        )
    if api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )


class Point(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude in EPSG:4326")
    lng: float = Field(..., ge=-180, le=180, description="Longitude in EPSG:4326")


class BatchRequest(BaseModel):
    points: List[Point]

    @model_validator(mode="after")
    def validate_size(self):
        if len(self.points) > MAX_BATCH:
            raise ValueError(f"Too many points; max is {MAX_BATCH}")
        return self


class HealthResponse(BaseModel):
    ok: bool
    status: Literal["alive"]


class ReadyResponse(BaseModel):
    ok: bool
    dem_ready: bool


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


class ElevationProfileResponse(BaseModel):
    version: Literal[1]
    source: SourceMetaResponse
    line_length_m: float
    points: List[ProfilePointResponse]
    quality: QualityResponse


@app.on_event("startup")
def startup_checks():
    if not API_KEY:
        raise RuntimeError("API_KEY must be set for the API to start")


def ensure_dataset_available() -> None:
    try:
        dem._open_dataset()
    except RasterioIOError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DEM dataset not available",
        )


def dataset_is_available(dataset_opener) -> bool:
    try:
        dataset_opener()
        return True
    except RasterioIOError:
        return False


def _haversine_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = lat2_r - lat1_r
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_M * c


def _build_chainage_m(points: Sequence[Tuple[float, float]]) -> List[float]:
    if not points:
        return []

    chainage = [0.0]
    total = 0.0
    for idx in range(1, len(points)):
        prev_lat, prev_lng = points[idx - 1]
        lat, lng = points[idx]
        total += _haversine_distance_m(prev_lat, prev_lng, lat, lng)
        chainage.append(total)
    return chainage


def _build_quality(statuses: Sequence[str]) -> QualityResponse:
    total = len(statuses)
    ok = statuses.count("ok")
    nodata = statuses.count("nodata")
    out_of_coverage = statuses.count("out_of_coverage")
    coverage_ratio = round(ok / total, 10) if total > 0 else 0.0
    return QualityResponse(
        total=total,
        ok=ok,
        nodata=nodata,
        out_of_coverage=out_of_coverage,
        coverage_ratio=coverage_ratio,
    )


def _build_profile_response(coords: Sequence[Tuple[float, float]], request: Request) -> ElevationProfileResponse:
    results = [dem.sample_point(lat, lng) for lat, lng in coords]
    chainages = _build_chainage_m(coords)

    points = [
        ProfilePointResponse(
            chainage_m=chainages[idx],
            elevation_m=result["elevation_m"],
            status=result["status"],
        )
        for idx, result in enumerate(results)
    ]
    statuses = [point.status for point in points]
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())

    return ElevationProfileResponse(
        version=1,
        source=SourceMetaResponse(generated_at=datetime.now(timezone.utc), request_id=request_id),
        line_length_m=chainages[-1] if chainages else 0.0,
        points=points,
        quality=_build_quality(statuses),
    )


@app.get("/health", response_model=HealthResponse)
def health():
    # Liveness only: process is up and can serve requests.
    return HealthResponse(ok=True, status="alive")


@app.get("/ready", response_model=ReadyResponse)
def ready(response: Response):
    dem_ready = dataset_is_available(dem._open_dataset)
    if not dem_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(
        ok=dem_ready,
        dem_ready=dem_ready,
    )


@app.post("/elevations", dependencies=[Depends(require_api_key)], response_model=ElevationProfileResponse)
def elevation_post(payload: BatchRequest, request: Request):
    ensure_dataset_available()
    coords = [(point.lat, point.lng) for point in payload.points]
    return _build_profile_response(coords, request)
