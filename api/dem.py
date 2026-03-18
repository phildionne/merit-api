import os
from functools import lru_cache
from typing import Dict, Optional, Sequence, Tuple

import rasterio

from .logging import get_logger

_DEM_PATH = os.getenv("DEM_PATH", "/data/mosaic/canada_elv.vrt")
_dataset = None
logger = get_logger(__name__)


def _open_dataset():
    global _dataset
    if _dataset is None:
        logger.info(
            "opening_dem_dataset",
            extra={
                "event": "opening_dem_dataset",
            },
        )
        _dataset = rasterio.open(_DEM_PATH)
        logger.info(
            "dem_dataset_opened",
            extra={
                "event": "dem_dataset_opened",
            },
        )
    return _dataset


def _in_bounds(ds, lat: float, lng: float) -> bool:
    left, bottom, right, top = ds.bounds
    return left <= lng <= right and bottom <= lat <= top


def _sample_raw(ds, lat: float, lng: float) -> Tuple[Optional[float], bool]:
    # rasterio expects (x, y) = (lng, lat)
    val = next(ds.sample([(lng, lat)]))[0]
    nodata = ds.nodata
    if nodata is not None and val == nodata:
        return None, True
    return float(val), False


def _sample_to_result(elev: Optional[float], nodata: bool) -> Dict[str, float | str | None]:
    if nodata:
        return {
            "elevation_m": None,
            "status": "nodata",
        }
    return {
        "elevation_m": elev,
        "status": "ok",
    }


def _sample_value_to_tuple(raw_value, nodata_value) -> Tuple[Optional[float], bool]:
    value = raw_value[0]
    if nodata_value is not None and value == nodata_value:
        return None, True
    return float(value), False


@lru_cache(maxsize=2048)
def _cached_sample(lat_r: float, lng_r: float) -> Tuple[Optional[float], bool]:
    ds = _open_dataset()
    return _sample_raw(ds, lat_r, lng_r)


def sample_point(lat: float, lng: float) -> Dict:
    ds = _open_dataset()
    if not _in_bounds(ds, lat, lng):
        return {
            "elevation_m": None,
            "status": "out_of_coverage",
        }

    lat_r = round(lat, 5)
    lng_r = round(lng, 5)
    elev, nodata = _cached_sample(lat_r, lng_r)
    return _sample_to_result(elev, nodata)


def sample_points(points: Sequence[tuple[float, float]]) -> list[Dict[str, float | str | None]]:
    if not points:
        return []

    ds = _open_dataset()
    results: list[Dict[str, float | str | None] | None] = [None] * len(points)
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
                results[idx] = dict(sample_result)

    if any(result is None for result in results):
        raise RuntimeError("missing DEM sample result")
    return [result for result in results if result is not None]
