import os
from collections.abc import Iterable, Iterator, Sequence
from typing import Literal, Protocol, TypedDict, cast

import rasterio

from .logging import get_logger

_DEM_PATH = os.getenv("DEM_PATH", "/data/mosaic/canada_elv.vrt")


class SampleDataset(Protocol):
    bounds: Sequence[float]
    nodata: float | int | None

    def sample(
        self,
        coords: Iterable[tuple[float, float]],
    ) -> Iterator[Sequence[float | int]]: ...


_dataset: SampleDataset | None = None
logger = get_logger(__name__)


class SamplePointResult(TypedDict):
    elevation_m: float | None
    status: Literal["ok", "nodata", "out_of_coverage"]


def _open_dataset() -> SampleDataset:
    global _dataset
    if _dataset is None:
        logger.info(
            "opening_dem_dataset",
            extra={
                "event": "opening_dem_dataset",
            },
        )
        _dataset = cast(SampleDataset, rasterio.open(_DEM_PATH))
        logger.info(
            "dem_dataset_opened",
            extra={
                "event": "dem_dataset_opened",
            },
        )
    return _dataset


def _in_bounds(ds: SampleDataset, lat: float, lng: float) -> bool:
    left, bottom, right, top = ds.bounds
    return left <= lng <= right and bottom <= lat <= top


def _sample_to_result(elev: float | None, nodata: bool) -> SamplePointResult:
    if nodata:
        return {
            "elevation_m": None,
            "status": "nodata",
        }
    return {
        "elevation_m": elev,
        "status": "ok",
    }


def _sample_value_to_tuple(
    raw_value: Sequence[float | int],
    nodata_value: float | int | None,
) -> tuple[float | None, bool]:
    value = raw_value[0]
    if nodata_value is not None and value == nodata_value:
        return None, True
    return float(value), False


def sample_points(
    points: Sequence[tuple[float, float]],
) -> list[SamplePointResult]:
    if not points:
        return []

    ds = _open_dataset()
    results: list[SamplePointResult | None] = [None] * len(points)
    grouped_indexes: dict[tuple[float, float], list[int]] = {}
    unique_in_bounds: list[tuple[float, float]] = []

    for idx, (lat, lng) in enumerate(points):
        if not _in_bounds(ds, lat, lng):
            results[idx] = {
                "elevation_m": None,
                "status": "out_of_coverage",
            }
            continue

        rounded = (round(lat, 5), round(lng, 5))
        if rounded not in grouped_indexes:
            grouped_indexes[rounded] = []
            unique_in_bounds.append(rounded)
        grouped_indexes[rounded].append(idx)

    if unique_in_bounds:
        nodata_value = ds.nodata
        samples = ds.sample([(lng_r, lat_r) for lat_r, lng_r in unique_in_bounds])
        for rounded, sample in zip(unique_in_bounds, samples):
            elev, nodata = _sample_value_to_tuple(sample, nodata_value)
            sample_result = _sample_to_result(elev, nodata)
            for idx in grouped_indexes[rounded]:
                results[idx] = {
                    "elevation_m": sample_result["elevation_m"],
                    "status": sample_result["status"],
                }

    if any(result is None for result in results):
        raise RuntimeError("missing DEM sample result")
    return [result for result in results if result is not None]
