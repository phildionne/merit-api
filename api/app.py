from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import dem

app = FastAPI(title="MERIT-Hydro Elevation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)


class Point(BaseModel):
    lat: float = Field(..., description="Latitude in EPSG:4326")
    lng: float = Field(..., description="Longitude in EPSG:4326")


class BatchRequest(BaseModel):
    points: List[Point]


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/elevation")
def elevation_get(lat: float, lng: float):
    try:
        return dem.sample_point(lat, lng, allow_oob=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/elevation")
def elevation_post(payload: BatchRequest):
    results = [dem.sample_point(p.lat, p.lng, allow_oob=True) for p in payload.points]
    return {"points": results}
