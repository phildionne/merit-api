#!/usr/bin/env python3
import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
DEFAULT_LOCAL_DEM_PATH = REPO_ROOT / "data" / "mosaic" / "canada_elv.vrt"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

if "DEM_PATH" not in os.environ and DEFAULT_LOCAL_DEM_PATH.exists():
    os.environ["DEM_PATH"] = str(DEFAULT_LOCAL_DEM_PATH)

from merit_api import dem  # noqa: E402
from merit_api import profile as profile_module  # noqa: E402
from merit_api.models import ElevationsRequestBody  # noqa: E402


@dataclass(frozen=True)
class CoverageSummary:
    input_path: str
    dem_path: str
    point_count: int
    points_bbox: dict[str, float]
    dem_bounds: dict[str, float]
    points_within_dem_bounds: bool
    quality: profile_module.QualitySummary
    narrative: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "input_path": self.input_path,
            "dem_path": self.dem_path,
            "point_count": self.point_count,
            "points_bbox": self.points_bbox,
            "dem_bounds": self.dem_bounds,
            "points_within_dem_bounds": self.points_within_dem_bounds,
            "quality": self.quality,
            "narrative": self.narrative,
        }


class BoundsLike(Protocol):
    left: float
    bottom: float
    right: float
    top: float


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize elevation coverage quality for a point collection using the repo DEM."
    )
    _ = parser.add_argument("input_path", help="Path to a JSON payload matching POST /elevations.")
    _ = parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the summary as JSON instead of plain text.",
    )
    return parser


def _load_request_points(input_path: Path) -> list[tuple[str, float, float]]:
    with input_path.open() as fh:
        request = ElevationsRequestBody.model_validate(json.load(fh))
    return [(point.id, *point.coordinates) for point in request.points]


def _bbox(points: Sequence[tuple[str, float, float]]) -> dict[str, float]:
    lngs = [point[1] for point in points]
    lats = [point[2] for point in points]
    return {
        "left": min(lngs),
        "bottom": min(lats),
        "right": max(lngs),
        "top": max(lats),
    }


def _bounds_to_dict(bounds: BoundsLike) -> dict[str, float]:
    return {
        "left": float(bounds.left),
        "bottom": float(bounds.bottom),
        "right": float(bounds.right),
        "top": float(bounds.top),
    }


def _is_within_bounds(points_bbox: dict[str, float], dem_bounds: dict[str, float]) -> bool:
    return (
        points_bbox["left"] >= dem_bounds["left"]
        and points_bbox["right"] <= dem_bounds["right"]
        and points_bbox["bottom"] >= dem_bounds["bottom"]
        and points_bbox["top"] <= dem_bounds["top"]
    )


def build_summary(input_path: Path) -> CoverageSummary:
    points = _load_request_points(input_path)
    ds = dem._open_dataset()

    points_bbox = _bbox(points)
    dem_bounds = _bounds_to_dict(ds.bounds)
    within_bounds = _is_within_bounds(points_bbox, dem_bounds)
    sampled = dem.sample_points([(lat, lng) for _, lng, lat in points])
    quality = profile_module.build_quality([result["status"] for result in sampled])

    narrative = [
        f"The input contains {len(points)} explicit API points.",
        "Quality was sampled from the exact points that POST /elevations would request.",
        "All points are inside the DEM bounds."
        if within_bounds
        else "Some points extend outside the DEM bounds.",
        "The point collection contains nodata gaps."
        if quality["nodata"]
        else "The point collection contains no nodata gaps.",
    ]

    return CoverageSummary(
        input_path=str(input_path),
        dem_path=str(getattr(ds, "name", os.environ.get("DEM_PATH", ""))),
        point_count=len(points),
        points_bbox=points_bbox,
        dem_bounds=dem_bounds,
        points_within_dem_bounds=within_bounds,
        quality=quality,
        narrative=narrative,
    )


def _format_text(summary: CoverageSummary) -> str:
    quality = summary.quality
    lines = [
        f"Input: {summary.input_path}",
        f"DEM: {summary.dem_path}",
        f"Points: {summary.point_count}",
        "Quality:",
        f"  total={quality['total']}",
        f"  ok={quality['ok']}",
        f"  nodata={quality['nodata']}",
        f"  out_of_coverage={quality['out_of_coverage']}",
        f"  coverage_ratio={quality['coverage_ratio']}",
        f"Within DEM bounds: {summary.points_within_dem_bounds}",
        "Narrative:",
    ]
    lines.extend(f"  - {line}" for line in summary.narrative)
    return "\n".join(lines)


def main() -> int:
    args = _parser().parse_args()
    try:
        summary = build_summary(Path(args.input_path))
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
