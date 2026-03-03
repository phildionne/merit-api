import math
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from rasterio.errors import RasterioIOError

from api import app as app_module


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self._api_key_patch = patch.object(app_module, "API_KEY", "test-api-key")
        self._api_key_patch.start()

    def tearDown(self):
        self._api_key_patch.stop()

    def assert_envelope(self, payload, total_points: int):
        self.assertEqual(payload["version"], 1)
        self.assertIn("source", payload)
        self.assertIn("generated_at", payload["source"])
        self.assertIn("request_id", payload["source"])
        self.assertTrue(payload["source"]["generated_at"].endswith("Z"))
        self.assertIn("line_length_m", payload)
        self.assertIn("points", payload)
        self.assertEqual(len(payload["points"]), total_points)
        self.assertIn("quality", payload)
        self.assertEqual(payload["quality"]["total"], total_points)

    def test_health_is_liveness_only(self):
        with patch.object(app_module.dem, "_open_dataset", side_effect=RasterioIOError("dem missing")):
            with TestClient(app_module.app) as client:
                response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "status": "alive"})

    def test_ready_returns_503_when_dem_unavailable(self):
        with patch.object(app_module.dem, "_open_dataset", side_effect=RasterioIOError("dem missing")):
            with TestClient(app_module.app) as client:
                response = client.get("/ready")
        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertEqual(payload["ok"], False)
        self.assertEqual(payload["dem_ready"], False)

    def test_ready_returns_200_when_dem_available(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with TestClient(app_module.app) as client:
                response = client.get("/ready")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["dem_ready"], True)

    def test_elevation_requires_api_key(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_point",
                return_value={"elevation_m": 123.45, "status": "ok"},
            ):
                with TestClient(app_module.app) as client:
                    unauthorized = client.get("/elevation?lat=46.8139&lng=-71.2080")
                    authorized = client.get(
                        "/elevation?lat=46.8139&lng=-71.2080",
                        headers={"X-API-Key": "test-api-key"},
                    )
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(authorized.status_code, 200)
        payload = authorized.json()
        self.assert_envelope(payload, total_points=1)
        self.assertEqual(payload["points"][0]["status"], "ok")
        self.assertEqual(payload["points"][0]["elevation_m"], 123.45)

    def test_elevation_out_of_coverage_returns_200(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_point",
                return_value={"elevation_m": None, "status": "out_of_coverage"},
            ):
                with TestClient(app_module.app) as client:
                    response = client.get(
                        "/elevation?lat=0&lng=0",
                        headers={"X-API-Key": "test-api-key"},
                    )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assert_envelope(payload, total_points=1)
        self.assertEqual(payload["points"][0]["status"], "out_of_coverage")
        self.assertIsNone(payload["points"][0]["elevation_m"])

    def test_elevations_alias_routes_work_for_get_and_post(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_point",
                side_effect=[
                    {"elevation_m": 10.0, "status": "ok"},
                    {"elevation_m": 11.0, "status": "ok"},
                    {"elevation_m": None, "status": "nodata"},
                ],
            ):
                with TestClient(app_module.app) as client:
                    get_response = client.get(
                        "/elevations?lat=46.8&lng=-71.2",
                        headers={"X-API-Key": "test-api-key"},
                    )
                    post_response = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json={
                            "points": [
                                {"lat": 46.8, "lng": -71.2},
                                {"lat": 46.81, "lng": -71.19},
                            ]
                        },
                    )
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(post_response.status_code, 200)

        get_payload = get_response.json()
        post_payload = post_response.json()
        self.assert_envelope(get_payload, total_points=1)
        self.assert_envelope(post_payload, total_points=2)
        self.assertEqual(get_payload["points"][0]["status"], "ok")
        self.assertEqual(post_payload["points"][0]["status"], "ok")
        self.assertEqual(post_payload["points"][1]["status"], "nodata")

    def test_post_mixed_status_quality_and_coverage_ratio(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_point",
                side_effect=[
                    {"elevation_m": 101.0, "status": "ok"},
                    {"elevation_m": None, "status": "nodata"},
                    {"elevation_m": None, "status": "out_of_coverage"},
                ],
            ):
                with TestClient(app_module.app) as client:
                    response = client.post(
                        "/elevation",
                        headers={"X-API-Key": "test-api-key"},
                        json={
                            "points": [
                                {"lat": 46.8, "lng": -71.2},
                                {"lat": 46.81, "lng": -71.19},
                                {"lat": 46.82, "lng": -71.18},
                            ]
                        },
                    )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assert_envelope(payload, total_points=3)
        self.assertEqual([point["status"] for point in payload["points"]], ["ok", "nodata", "out_of_coverage"])
        self.assertEqual(payload["quality"]["ok"], 1)
        self.assertEqual(payload["quality"]["nodata"], 1)
        self.assertEqual(payload["quality"]["out_of_coverage"], 1)
        self.assertAlmostEqual(payload["quality"]["coverage_ratio"], 0.3333333333, places=10)

    def test_chainage_is_geodesic_and_monotonic(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_point",
                side_effect=[
                    {"elevation_m": 1.0, "status": "ok"},
                    {"elevation_m": 2.0, "status": "ok"},
                ],
            ):
                with TestClient(app_module.app) as client:
                    response = client.post(
                        "/elevation",
                        headers={"X-API-Key": "test-api-key"},
                        json={"points": [{"lat": 0.0, "lng": 0.0}, {"lat": 0.0, "lng": 1.0}]},
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assert_envelope(payload, total_points=2)

        chainages = [point["chainage_m"] for point in payload["points"]]
        self.assertEqual(chainages[0], 0.0)
        self.assertGreater(chainages[1], chainages[0])

        expected_m = app_module.EARTH_RADIUS_M * math.radians(1.0)
        self.assertAlmostEqual(chainages[1], expected_m, delta=0.001)
        self.assertAlmostEqual(payload["line_length_m"], expected_m, delta=0.001)

    def test_request_id_echo_and_generation(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_point",
                return_value={"elevation_m": 8.0, "status": "ok"},
            ):
                with TestClient(app_module.app) as client:
                    echoed = client.get(
                        "/elevation?lat=46.8&lng=-71.2",
                        headers={"X-API-Key": "test-api-key", "X-Request-ID": "req-123"},
                    )
                    generated = client.get(
                        "/elevation?lat=46.8&lng=-71.2",
                        headers={"X-API-Key": "test-api-key"},
                    )

        self.assertEqual(echoed.status_code, 200)
        self.assertEqual(generated.status_code, 200)

        echoed_payload = echoed.json()
        generated_payload = generated.json()

        self.assertEqual(echoed_payload["source"]["request_id"], "req-123")
        generated_request_id = generated_payload["source"]["request_id"]
        self.assertTrue(generated_request_id)
        uuid.UUID(generated_request_id)

    def test_width_endpoint_removed_returns_404(self):
        with TestClient(app_module.app) as client:
            response = client.post(
                "/width",
                headers={"X-API-Key": "test-api-key"},
                json={"points": [{"id": "p1", "lat": 46.8139, "lng": -71.2080}]},
            )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
