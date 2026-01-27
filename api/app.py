import os
from typing import List

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, model_validator

from . import dem

app = FastAPI(title="MERIT-Hydro Elevation API")

API_KEY = (os.getenv("API_KEY") or "").strip()
MAX_BATCH = int(os.getenv("MAX_BATCH", "1000"))
_origins_env = (os.getenv("ALLOWED_ORIGINS") or "*").strip()
ALLOWED_ORIGINS = ["*"] if _origins_env == "*" else [o.strip() for o in _origins_env.split(",") if o.strip()]

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


@app.on_event("startup")
def startup_checks():
    if not API_KEY:
        raise RuntimeError("API_KEY must be set for the API to start")
    dem._open_dataset()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/elevation", dependencies=[Depends(require_api_key)])
def elevation_get(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    try:
        return dem.sample_point(lat, lng, allow_oob=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/elevation", dependencies=[Depends(require_api_key)])
def elevation_post(payload: BatchRequest):
    results = [dem.sample_point(p.lat, p.lng, allow_oob=True) for p in payload.points]
    return {"points": results}
