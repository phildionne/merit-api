import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import summarize_coverage_quality as summary_module


class SummarizeCoverageQualityTests(unittest.TestCase):
    def write_payload(self, payload: dict) -> Path:
        temp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        with temp:
            json.dump(payload, temp)
        return Path(temp.name)

    def sample_point(self, point_id: str, lng: float, lat: float) -> dict:
        return {"id": point_id, "coordinates": [lng, lat]}

    def test_rejects_missing_points_array(self):
        input_path = self.write_payload({})

        with self.assertRaisesRegex(ValueError, "points array"):
            summary_module._load_request_points(input_path)

    def test_rejects_out_of_range_coordinates(self):
        input_path = self.write_payload(
            {
                "points": [
                    self.sample_point("point-0", -71.2, 95.0),
                ]
            }
        )

        with self.assertRaisesRegex(ValueError, "Latitude must be between -90 and 90"):
            summary_module._load_request_points(input_path)

    def test_build_summary_aggregates_statuses_for_exact_request_points(self):
        input_path = self.write_payload(
            {
                "points": [
                    self.sample_point("point-0", -71.2, 46.8),
                    self.sample_point("point-1", -71.19, 46.81),
                ]
            }
        )

        fake_dataset = SimpleNamespace(name="/tmp/fake-dem.vrt", bounds=SimpleNamespace(left=-180, bottom=-90, right=180, top=90))

        with patch.object(summary_module.dem, "_open_dataset", return_value=fake_dataset):
            with patch.object(
                summary_module.dem,
                "sample_points",
                return_value=[
                    {"elevation_m": 10.0, "status": "ok"},
                    {"elevation_m": None, "status": "nodata"},
                ],
            ) as sample_points:
                summary = summary_module.build_summary(input_path)

        self.assertEqual(summary.point_count, 2)
        self.assertTrue(summary.points_within_dem_bounds)
        self.assertEqual(summary.quality["total"], 2)
        self.assertEqual(summary.quality["ok"], 1)
        self.assertEqual(summary.quality["nodata"], 1)
        self.assertEqual(summary.quality["out_of_coverage"], 0)
        self.assertAlmostEqual(summary.quality["coverage_ratio"], 0.5, places=10)
        self.assertEqual(
            sample_points.call_args.args[0],
            [(46.8, -71.2), (46.81, -71.19)],
        )

    def test_quality_matches_api_helper_output(self):
        statuses = ["ok", "ok", "nodata", "out_of_coverage"]
        expected = summary_module.profile_module.build_quality(statuses)

        input_path = self.write_payload(
            {
                "points": [
                    self.sample_point("point-0", -71.2, 46.8),
                    self.sample_point("point-1", -71.19, 46.81),
                    self.sample_point("point-2", -71.18, 46.82),
                    self.sample_point("point-3", -71.17, 46.83),
                ]
            }
        )

        fake_dataset = SimpleNamespace(name="/tmp/fake-dem.vrt", bounds=SimpleNamespace(left=-180, bottom=-90, right=180, top=90))

        with patch.object(summary_module.dem, "_open_dataset", return_value=fake_dataset):
            with patch.object(
                summary_module.dem,
                "sample_points",
                side_effect=[[{"elevation_m": None, "status": status} for status in statuses]],
            ):
                summary = summary_module.build_summary(input_path)

        self.assertEqual(summary.quality, expected)

    def test_build_summary_preserves_duplicate_coordinate_points_as_requested(self):
        input_path = self.write_payload(
            {
                "points": [
                    self.sample_point("point-a", -71.2, 46.8),
                    self.sample_point("point-b", -71.2, 46.8),
                ]
            }
        )

        fake_dataset = SimpleNamespace(name="/tmp/fake-dem.vrt", bounds=SimpleNamespace(left=-180, bottom=-90, right=180, top=90))

        with patch.object(summary_module.dem, "_open_dataset", return_value=fake_dataset):
            with patch.object(
                summary_module.dem,
                "sample_points",
                return_value=[
                    {"elevation_m": 10.0, "status": "ok"},
                    {"elevation_m": 10.0, "status": "ok"},
                ],
            ) as sample_points:
                summary = summary_module.build_summary(input_path)

        self.assertEqual(sample_points.call_count, 1)
        self.assertEqual(summary.quality["total"], 2)
        self.assertEqual(summary.quality["ok"], 2)


if __name__ == "__main__":
    unittest.main()
