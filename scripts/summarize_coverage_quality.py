#!/usr/bin/env python3
import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL_DEM_PATH = REPO_ROOT / "data" / "mosaic" / "canada_elv.vrt"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if "DEM_PATH" not in os.environ and DEFAULT_LOCAL_DEM_PATH.exists():
    os.environ["DEM_PATH"] = str(DEFAULT_LOCAL_DEM_PATH)

from api import dem  # noqa: E402
from api import profile as profile_module  # noqa: E402


@dataclass(frozen=True)
class CoverageSummary:
    input_path: str
    dem_path: str
    density_m: float
    geometry_type: str
    vertex_count: int
    line_bbox: dict[str, float]
    dem_bounds: dict[str, float]
    line_within_dem_bounds: bool
    quality: dict[str, int | float]
    narrative: list[str]

    def to_dict(self) -> dict:
        return {
            "input_path": self.input_path,
            "dem_path": self.dem_path,
            "density_m": self.density_m,
            "geometry_type": self.geometry_type,
            "vertex_count": self.vertex_count,
            "line_bbox": self.line_bbox,
            "dem_bounds": self.dem_bounds,
            "line_within_dem_bounds": self.line_within_dem_bounds,
            "quality": self.quality,
            "narrative": self.narrative,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize elevation coverage quality for a GeoJSON LineString using the repo DEM."
    )
    parser.add_argument("input_path", help="Path to a GeoJSON FeatureCollection with a single LineString feature.")
    parser.add_argument(
        "--density-m",
        type=float,
        default=200.0,
        help="Sampling density in meters used to mirror POST /elevations (must be > 100).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the summary as JSON instead of plain text.",
    )
    return parser


def _load_linestring_coords(input_path: Path) -> list[tuple[float, float]]:
    with input_path.open() as fh:
        payload = json.load(fh)

    if payload.get("type") != "FeatureCollection":
        raise ValueError("Input must be a GeoJSON FeatureCollection.")

    features = payload.get("features")
    if not isinstance(features, list) or len(features) != 1:
        raise ValueError("Input must contain exactly one feature.")

    geometry = (features[0] or {}).get("geometry") or {}
    geometry_type = geometry.get("type")
    if geometry_type != "LineString":
        raise ValueError(f"Input feature geometry must be LineString, got {geometry_type!r}.")

    coords = geometry.get("coordinates")
    if not isinstance(coords, list) or not coords:
        raise ValueError("LineString coordinates must be a non-empty array.")

    normalized: list[tuple[float, float]] = []
    for index, coord in enumerate(coords):
        if not isinstance(coord, list) or len(coord) < 2:
            raise ValueError(f"Coordinate at index {index} is invalid.")
        lng = float(coord[0])
        lat = float(coord[1])
        normalized.append((lng, lat))
    return normalized


def _bbox(coords: Sequence[tuple[float, float]]) -> dict[str, float]:
    lngs = [coord[0] for coord in coords]
    lats = [coord[1] for coord in coords]
    return {
        "left": min(lngs),
        "bottom": min(lats),
        "right": max(lngs),
        "top": max(lats),
    }


def _bounds_to_dict(bounds) -> dict[str, float]:
    return {
        "left": float(bounds.left),
        "bottom": float(bounds.bottom),
        "right": float(bounds.right),
        "top": float(bounds.top),
    }


def _is_within_bounds(line_bbox: dict[str, float], dem_bounds: dict[str, float]) -> bool:
    return (
        line_bbox["left"] >= dem_bounds["left"]
        and line_bbox["right"] <= dem_bounds["right"]
        and line_bbox["bottom"] >= dem_bounds["bottom"]
        and line_bbox["top"] <= dem_bounds["top"]
    )


def _sample_statuses(coords: Iterable[tuple[float, float]]) -> list[str]:
    statuses: list[str] = []
    for lng, lat in coords:
        sample = dem.sample_point(lat, lng)
        statuses.append(sample["status"])
    return statuses


def _build_profile_statuses(coords: Sequence[tuple[float, float]], density_m: float) -> list[str]:
    if density_m <= 100.0:
        raise ValueError("density_m must be greater than 100.0 meters.")

    line_coords = [(lat, lng) for lng, lat in coords]
    vertex_chainages = profile_module.build_chainage_m(line_coords)
    line_length_m = vertex_chainages[-1] if vertex_chainages else 0.0
    sample_chainages = profile_module.build_sample_chainages_m(line_length_m, density_m)
    sampled_line_coords = profile_module.interpolate_samples_along_line(
        line_coords,
        vertex_chainages,
        sample_chainages,
    )
    sampled_coords = [(lng, lat) for lat, lng in sampled_line_coords]

    statuses = _sample_statuses([coords[0]])
    statuses.extend(_sample_statuses(sampled_coords))

    endpoint_already_sampled = bool(sample_chainages) and math.isclose(
        sample_chainages[-1],
        line_length_m,
        abs_tol=profile_module.CHAINAGE_EPSILON_M,
    )
    if not math.isclose(line_length_m, 0.0, abs_tol=profile_module.CHAINAGE_EPSILON_M) and not endpoint_already_sampled:
        statuses.extend(_sample_statuses([coords[-1]]))

    return statuses


def build_summary(input_path: Path, density_m: float = 200.0) -> CoverageSummary:
    coords = _load_linestring_coords(input_path)
    if density_m <= 100.0:
        raise ValueError("density_m must be greater than 100.0 meters.")
    ds = dem._open_dataset()

    line_bbox = _bbox(coords)
    dem_bounds = _bounds_to_dict(ds.bounds)
    within_bounds = _is_within_bounds(line_bbox, dem_bounds)
    statuses = _build_profile_statuses(coords, density_m)
    quality = profile_module.build_quality(statuses)

    narrative = [
        f"The input line has {len(coords)} vertices and geometry type LineString.",
        f"Quality was sampled along the API profile at density {density_m:g} m.",
        "The line is fully inside the DEM bounds." if within_bounds else "The line extends outside the DEM bounds.",
        "The line contains nodata gaps." if quality["nodata"] else "The line contains no nodata gaps.",
    ]

    return CoverageSummary(
        input_path=str(input_path),
        dem_path=str(getattr(ds, "name", os.environ.get("DEM_PATH", ""))),
        density_m=density_m,
        geometry_type="LineString",
        vertex_count=len(coords),
        line_bbox=line_bbox,
        dem_bounds=dem_bounds,
        line_within_dem_bounds=within_bounds,
        quality=quality,
        narrative=narrative,
    )


def _format_text(summary: CoverageSummary) -> str:
    quality = summary.quality
    lines = [
        f"Input: {summary.input_path}",
        f"DEM: {summary.dem_path}",
        f"Density (m): {summary.density_m}",
        f"Geometry: {summary.geometry_type}",
        f"Vertices: {summary.vertex_count}",
        "Quality:",
        f"  total={quality['total']}",
        f"  ok={quality['ok']}",
        f"  nodata={quality['nodata']}",
        f"  out_of_coverage={quality['out_of_coverage']}",
        f"  coverage_ratio={quality['coverage_ratio']}",
        f"Within DEM bounds: {summary.line_within_dem_bounds}",
        "Narrative:",
    ]
    lines.extend(f"  - {line}" for line in summary.narrative)
    return "\n".join(lines)


def main() -> int:
    args = _parser().parse_args()
    try:
        summary = build_summary(Path(args.input_path), density_m=args.density_m)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
    else:
        print(_format_text(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
