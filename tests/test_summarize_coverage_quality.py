import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import summarize_coverage_quality as summary_module


class SummarizeCoverageQualityTests(unittest.TestCase):
    def eastward_line(self, distance_m: float):
        delta_lng = math.degrees(distance_m / summary_module.profile_module.EARTH_RADIUS_M)
        return [[0.0, 0.0], [delta_lng, 0.0]]

    def write_geojson(self, payload: dict) -> Path:
        temp = tempfile.NamedTemporaryFile("w", suffix=".geojson", delete=False)
        with temp:
            json.dump(payload, temp)
        return Path(temp.name)

    def test_rejects_non_linestring_geometry(self):
        input_path = self.write_geojson(
            {
                "type": "FeatureCollection",
                "features": [{"geometry": {"type": "Point", "coordinates": [-71.2, 46.8]}}],
            }
        )

        with self.assertRaisesRegex(ValueError, "LineString"):
            summary_module._load_linestring_coords(input_path)

    def test_build_summary_aggregates_statuses(self):
        input_path = self.write_geojson(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "geometry": {
                            "type": "LineString",
                            "coordinates": self.eastward_line(450.0),
                        }
                    }
                ],
            }
        )

        fake_dataset = SimpleNamespace(name="/tmp/fake-dem.vrt", bounds=SimpleNamespace(left=-1, bottom=-1, right=1, top=1))

        with patch.object(summary_module.dem, "_open_dataset", return_value=fake_dataset):
            with patch.object(
                summary_module.dem,
                "sample_point",
                side_effect=[
                    {"elevation_m": 10.0, "status": "ok"},
                    {"elevation_m": None, "status": "nodata"},
                    {"elevation_m": None, "status": "out_of_coverage"},
                    {"elevation_m": 20.0, "status": "ok"},
                ],
            ):
                summary = summary_module.build_summary(input_path)

        self.assertEqual(summary.geometry_type, "LineString")
        self.assertEqual(summary.density_m, 200.0)
        self.assertEqual(summary.vertex_count, 2)
        self.assertTrue(summary.line_within_dem_bounds)
        self.assertEqual(summary.quality["total"], 4)
        self.assertEqual(summary.quality["ok"], 2)
        self.assertEqual(summary.quality["nodata"], 1)
        self.assertEqual(summary.quality["out_of_coverage"], 1)
        self.assertAlmostEqual(summary.quality["coverage_ratio"], 0.5, places=10)

    def test_quality_matches_api_helper_output(self):
        statuses = ["ok", "ok", "nodata", "out_of_coverage"]

        expected = summary_module.profile_module.build_quality(statuses)

        fake_dataset = SimpleNamespace(name="/tmp/fake-dem.vrt", bounds=SimpleNamespace(left=-1, bottom=-1, right=1, top=1))
        input_path = self.write_geojson(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "geometry": {
                            "type": "LineString",
                            "coordinates": self.eastward_line(450.0),
                        }
                    }
                ],
            }
        )

        with patch.object(summary_module.dem, "_open_dataset", return_value=fake_dataset):
            with patch.object(
                summary_module.dem,
                "sample_point",
                side_effect=[{"elevation_m": None, "status": status_value} for status_value in statuses],
            ):
                summary = summary_module.build_summary(input_path)

        self.assertEqual(summary.quality, expected)

    def test_build_summary_samples_interior_profile_points_not_only_vertices(self):
        input_path = self.write_geojson(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "geometry": {
                            "type": "LineString",
                            "coordinates": self.eastward_line(250.0),
                        }
                    }
                ],
            }
        )

        fake_dataset = SimpleNamespace(name="/tmp/fake-dem.vrt", bounds=SimpleNamespace(left=-1, bottom=-1, right=1, top=1))

        with patch.object(summary_module.dem, "_open_dataset", return_value=fake_dataset):
            with patch.object(
                summary_module.dem,
                "sample_point",
                side_effect=[
                    {"elevation_m": 10.0, "status": "ok"},
                    {"elevation_m": None, "status": "nodata"},
                    {"elevation_m": 20.0, "status": "ok"},
                ],
            ) as sample_point:
                summary = summary_module.build_summary(input_path, density_m=200.0)

        self.assertEqual(sample_point.call_count, 3)
        self.assertEqual(summary.quality["total"], 3)
        self.assertEqual(summary.quality["nodata"], 1)
        self.assertAlmostEqual(summary.quality["coverage_ratio"], 0.6666666667, places=10)

    def test_build_summary_rejects_density_at_or_below_api_minimum(self):
        input_path = self.write_geojson(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "geometry": {
                            "type": "LineString",
                            "coordinates": self.eastward_line(250.0),
                        }
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "density_m must be greater than 100.0 meters."):
            summary_module.build_summary(input_path, density_m=100.0)


if __name__ == "__main__":
    unittest.main()
