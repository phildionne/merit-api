import unittest
from unittest.mock import patch

from api import dem


class FakeDataset:
    def __init__(self, sample_values, *, nodata=-9999.0):
        self.bounds = (-180.0, -90.0, 180.0, 90.0)
        self.nodata = nodata
        self._sample_values = sample_values
        self.sample_calls = []

    def sample(self, coords):
        coords_list = list(coords)
        self.sample_calls.append(coords_list)
        return iter(self._sample_values)


class DemSamplingTests(unittest.TestCase):
    def test_sample_points_dedupes_rounded_coordinates_and_preserves_order(self):
        dataset = FakeDataset([[11.0], [22.0]])
        points = [
            (45.123454, -71.123454),
            (45.123451, -71.123451),
            (46.0, -72.0),
        ]

        with patch.object(dem, "_open_dataset", return_value=dataset):
            results = dem.sample_points(points)

        self.assertEqual(
            dataset.sample_calls,
            [[(-71.12345, 45.12345), (-72.0, 46.0)]],
        )
        self.assertEqual(
            results,
            [
                {"elevation_m": 11.0, "status": "ok"},
                {"elevation_m": 11.0, "status": "ok"},
                {"elevation_m": 22.0, "status": "ok"},
            ],
        )

    def test_sample_points_skips_out_of_coverage_and_preserves_nodata(self):
        dataset = FakeDataset([[-9999.0]])
        points = [
            (95.0, 0.0),
            (45.0, -71.0),
        ]

        with patch.object(dem, "_open_dataset", return_value=dataset):
            results = dem.sample_points(points)

        self.assertEqual(dataset.sample_calls, [[(-71.0, 45.0)]])
        self.assertEqual(
            results,
            [
                {"elevation_m": None, "status": "out_of_coverage"},
                {"elevation_m": None, "status": "nodata"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
