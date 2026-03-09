import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import summarize_coverage_quality as summary_module


class SummarizeCoverageQualityTests(unittest.TestCase):
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

    def test_build_summary_aggregates_statuses_and_chunking(self):
        input_path = self.write_geojson(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-71.2, 46.8], [-71.19, 46.81], [-71.18, 46.82]],
                        }
                    }
                ],
            }
        )

        fake_dataset = SimpleNamespace(name="/tmp/fake-dem.vrt", bounds=SimpleNamespace(left=-80, bottom=40, right=-60, top=50))

        with patch.object(summary_module.dem, "_open_dataset", return_value=fake_dataset):
            with patch.object(
                summary_module.dem,
                "sample_point",
                side_effect=[
                    {"elevation_m": 10.0, "status": "ok"},
                    {"elevation_m": None, "status": "nodata"},
                    {"elevation_m": None, "status": "out_of_coverage"},
                ],
            ):
                with patch.object(summary_module.app_module, "MAX_BATCH", 2):
                    summary = summary_module.build_summary(input_path)

        self.assertEqual(summary.geometry_type, "LineString")
        self.assertEqual(summary.vertex_count, 3)
        self.assertTrue(summary.line_within_dem_bounds)
        self.assertTrue(summary.requires_chunking)
        self.assertEqual(summary.quality["total"], 3)
        self.assertEqual(summary.quality["ok"], 1)
        self.assertEqual(summary.quality["nodata"], 1)
        self.assertEqual(summary.quality["out_of_coverage"], 1)
        self.assertAlmostEqual(summary.quality["coverage_ratio"], 0.3333333333, places=10)

    def test_quality_matches_api_helper_output(self):
        statuses = ["ok", "ok", "nodata", "out_of_coverage"]

        expected = summary_module.app_module._build_quality(statuses).model_dump()

        fake_dataset = SimpleNamespace(name="/tmp/fake-dem.vrt", bounds=SimpleNamespace(left=-80, bottom=40, right=-60, top=50))
        input_path = self.write_geojson(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-71.2, 46.8], [-71.19, 46.81], [-71.18, 46.82], [-71.17, 46.83]],
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


if __name__ == "__main__":
    unittest.main()
