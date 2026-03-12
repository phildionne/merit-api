import os
from functools import lru_cache
from typing import Dict, Optional, Tuple

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
    if nodata:
        return {
            "elevation_m": None,
            "status": "nodata",
        }
    return {
        "elevation_m": elev,
        "status": "ok",
    }
