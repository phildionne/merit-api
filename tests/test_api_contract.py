import unittest
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
                return_value={
                    "lat": 46.8139,
                    "lng": -71.2080,
                    "elevation_m": 123.45,
                    "nodata": False,
                },
            ):
                with TestClient(app_module.app) as client:
                    unauthorized = client.get("/elevation?lat=46.8139&lng=-71.2080")
                    authorized = client.get(
                        "/elevation?lat=46.8139&lng=-71.2080",
                        headers={"X-API-Key": "test-api-key"},
                    )
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(authorized.json()["elevation_m"], 123.45)

    def test_elevation_out_of_bounds_is_400(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(app_module.dem, "sample_point", side_effect=ValueError("Point is outside dataset bounds")):
                with TestClient(app_module.app) as client:
                    response = client.get(
                        "/elevation?lat=0&lng=0",
                        headers={"X-API-Key": "test-api-key"},
                    )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Point is outside dataset bounds")

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
