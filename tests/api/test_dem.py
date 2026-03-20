from collections.abc import Iterable, Iterator, Sequence
from unittest.mock import patch

from merit_api import dem


class FakeDataset:
    bounds: tuple[float, float, float, float]
    nodata: float
    _sample_values: list[list[float]]

    def __init__(self, sample_values: list[list[float]], *, nodata: float = -9999.0) -> None:
        self.bounds = (-180.0, -90.0, 180.0, 90.0)
        self.nodata = nodata
        self._sample_values = sample_values
        self.sample_calls: list[list[tuple[float, float]]] = []

    def sample(self, coords: Iterable[tuple[float, float]]) -> Iterator[Sequence[float]]:
        coords_list = list(coords)
        self.sample_calls.append(coords_list)
        return iter(self._sample_values)


def test_sample_points_dedupes_rounded_coordinates_and_preserves_order() -> None:
    dataset = FakeDataset([[11.0], [22.0]])
    points = [
        (45.123454, -71.123454),
        (45.123451, -71.123451),
        (46.0, -72.0),
    ]

    with patch.object(dem, "_open_dataset", return_value=dataset):
        results = dem.sample_points(points)

    assert dataset.sample_calls == [[(-71.12345, 45.12345), (-72.0, 46.0)]]
    assert results == [
        {"elevation_m": 11.0, "status": "ok"},
        {"elevation_m": 11.0, "status": "ok"},
        {"elevation_m": 22.0, "status": "ok"},
    ]


def test_sample_points_skips_out_of_coverage_and_preserves_nodata() -> None:
    dataset = FakeDataset([[-9999.0]])
    points = [
        (95.0, 0.0),
        (45.0, -71.0),
    ]

    with patch.object(dem, "_open_dataset", return_value=dataset):
        results = dem.sample_points(points)

    assert dataset.sample_calls == [[(-71.0, 45.0)]]
    assert results == [
        {"elevation_m": None, "status": "out_of_coverage"},
        {"elevation_m": None, "status": "nodata"},
    ]
