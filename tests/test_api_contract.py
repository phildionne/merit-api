import asyncio
import json
import math
import unittest
import uuid
from collections import deque
from unittest.mock import patch

from fastapi.testclient import TestClient
from rasterio.errors import RasterioIOError

from api import app as app_module
from api.config import AppConfig


class ApiContractTests(unittest.TestCase):
    def make_client(self, **overrides) -> TestClient:
        config = AppConfig(
            api_key=overrides.pop("api_key", "test-api-key"),
            max_request_body_bytes=overrides.pop("max_request_body_bytes", 2_000_000),
            allowed_origins=overrides.pop("allowed_origins", ["*"]),
            trust_x_request_id=overrides.pop("trust_x_request_id", True),
            enable_docs=overrides.pop("enable_docs", True),
        )
        assert not overrides
        return TestClient(app_module.create_app(config))

    def assert_envelope(self, payload, total_points: int):
        self.assertEqual(payload["version"], 1)
        self.assertIn("source", payload)
        self.assertIn("generated_at", payload["source"])
        self.assertIn("request_id", payload["source"])
        self.assertTrue(payload["source"]["generated_at"].endswith("Z"))
        self.assertIn("line_length_m", payload)
        self.assertIn("quality", payload)
        self.assertIn("data", payload)
        self.assertEqual(set(payload["data"].keys()), {"start_point", "end_point", "points"})
        self.assertEqual(
            set(payload["data"]["start_point"].keys()),
            {"chainage_m", "elevation_m", "status"},
        )
        self.assertEqual(
            set(payload["data"]["end_point"].keys()),
            {"chainage_m", "elevation_m", "status"},
        )
        self.assertEqual(len(payload["data"]["points"]), total_points)

    def assert_error(self, response, code: str, status_code: int):
        self.assertEqual(response.status_code, status_code)
        body = response.json()
        self.assertEqual(body["error"]["code"], code)
        self.assertIn("message", body["error"])
        self.assertIn("request_id", body)
        self.assertEqual(response.headers["x-request-id"], body["request_id"])
        return body

    def line_feature_collection(self, coordinates):
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coordinates,
                    },
                    "properties": None,
                }
            ],
        }

    def elevations_request(self, coordinates, density_m: float = 200.0):
        return {
            "geojson": self.line_feature_collection(coordinates),
            "density_m": density_m,
        }

    def eastward_line(self, distance_m: float):
        delta_lng = math.degrees(distance_m / app_module.EARTH_RADIUS_M)
        return [[0.0, 0.0], [delta_lng, 0.0]]

    def test_health_is_liveness_only(self):
        with patch.object(app_module.dem, "_open_dataset", side_effect=RasterioIOError("dem missing")):
            with self.make_client() as client:
                response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "status": "alive"})

    def test_ready_returns_service_specific_checks(self):
        with patch.object(app_module.dem, "_open_dataset", side_effect=RasterioIOError("dem missing")):
            with self.make_client() as client:
                response = client.get("/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "ok": False,
                "status": "not_ready",
                "checks": {"api_key": True, "dem": False},
            },
        )

    def test_ready_returns_503_when_api_key_not_configured(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with self.make_client(api_key="") as client:
                response = client.get("/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "ok": False,
                "status": "not_ready",
                "checks": {"api_key": False, "dem": True},
            },
        )

    def test_post_elevations_requires_api_key(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_points",
                return_value=[
                    {"elevation_m": 123.45, "status": "ok"},
                    {"elevation_m": 123.45, "status": "ok"},
                ],
            ):
                with self.make_client() as client:
                    payload = self.elevations_request(self.eastward_line(200.0))
                    unauthorized = client.post("/elevations", json=payload)
                    authorized = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=payload,
                    )
        self.assert_error(unauthorized, "unauthorized", 401)
        self.assertEqual(authorized.status_code, 200)
        payload = authorized.json()
        self.assert_envelope(payload, total_points=1)
        self.assertEqual(payload["data"]["points"][0]["status"], "ok")
        self.assertEqual(payload["data"]["points"][0]["elevation_m"], 123.45)
        self.assertAlmostEqual(payload["data"]["points"][0]["chainage_m"], 200.0, delta=0.001)

    def test_post_elevations_returns_not_ready_when_server_api_key_missing(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with self.make_client(api_key="") as client:
                response = client.post(
                    "/elevations",
                    headers={"X-API-Key": "any-key"},
                    json=self.elevations_request(self.eastward_line(200.0)),
                )

        body = self.assert_error(response, "not_ready", 503)
        self.assertEqual(body["error"]["message"], "API key not configured")

    def test_post_elevations_returns_not_ready_when_dem_read_fails_during_sampling(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(app_module.dem, "sample_points", side_effect=RasterioIOError("tile missing")):
                with self.make_client() as client:
                    response = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=self.elevations_request(self.eastward_line(200.0)),
                    )

        body = self.assert_error(response, "not_ready", 503)
        self.assertEqual(body["error"]["message"], "DEM dataset not available")

    def test_post_elevations_out_of_coverage_returns_200(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_points",
                return_value=[
                    {"elevation_m": None, "status": "out_of_coverage"},
                    {"elevation_m": None, "status": "out_of_coverage"},
                ],
            ):
                with self.make_client() as client:
                    response = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=self.elevations_request(self.eastward_line(200.0)),
                    )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assert_envelope(payload, total_points=1)
        self.assertEqual(payload["data"]["points"][0]["status"], "out_of_coverage")
        self.assertIsNone(payload["data"]["points"][0]["elevation_m"])

    def test_short_line_returns_empty_points(self):
        end_lng = math.degrees(100.0 / app_module.EARTH_RADIUS_M)
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_points",
                return_value=[
                    {"elevation_m": 10.0, "status": "ok"},
                    {"elevation_m": 20.0, "status": "ok"},
                ],
            ) as sample_points:
                with self.make_client() as client:
                    response = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=self.elevations_request(self.eastward_line(100.0)),
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assert_envelope(payload, total_points=0)
        self.assertAlmostEqual(payload["line_length_m"], 100.0, delta=0.001)
        self.assertEqual(
            payload["data"]["start_point"],
            {"chainage_m": 0.0, "elevation_m": 10.0, "status": "ok"},
        )
        self.assertEqual(
            payload["data"]["end_point"],
            {"chainage_m": payload["line_length_m"], "elevation_m": 20.0, "status": "ok"},
        )
        self.assertEqual(payload["data"]["points"], [])
        self.assertEqual(payload["quality"]["total"], 2)
        self.assertEqual(payload["quality"]["ok"], 2)
        self.assertEqual(payload["quality"]["nodata"], 0)
        self.assertEqual(payload["quality"]["out_of_coverage"], 0)
        self.assertEqual(payload["quality"]["coverage_ratio"], 1.0)
        self.assertEqual(sample_points.call_count, 1)
        self.assertEqual(sample_points.call_args.args[0], [(0.0, 0.0), (0.0, end_lng)])

    def test_zero_length_line_reuses_start_sample_for_end_point(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_points",
                return_value=[{"elevation_m": 10.0, "status": "ok"}],
            ) as sample_points:
                with self.make_client() as client:
                    response = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=self.elevations_request([[0.0, 0.0], [0.0, 0.0]]),
                    )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["line_length_m"], 0.0)
        self.assertEqual(body["data"]["points"], [])
        self.assertEqual(
            body["data"]["start_point"],
            {"chainage_m": 0.0, "elevation_m": 10.0, "status": "ok"},
        )
        self.assertEqual(
            body["data"]["end_point"],
            {"chainage_m": 0.0, "elevation_m": 10.0, "status": "ok"},
        )
        self.assertEqual(body["quality"]["total"], 1)
        self.assertEqual(body["quality"]["ok"], 1)
        self.assertEqual(body["quality"]["coverage_ratio"], 1.0)
        self.assertEqual(sample_points.call_count, 1)
        self.assertEqual(sample_points.call_args.args[0], [(0.0, 0.0)])

    def test_removed_and_unsupported_elevation_routes_return_default_statuses(self):
        with self.make_client() as client:
            get_elevation = client.get("/elevation")
            post_elevation = client.post(
                "/elevation",
                headers={"X-API-Key": "test-api-key"},
                json=self.elevations_request(self.eastward_line(200.0)),
            )
            get_elevations = client.get("/elevations")

        self.assertEqual(get_elevation.status_code, 404)
        self.assertEqual(post_elevation.status_code, 404)
        self.assertEqual(get_elevations.status_code, 405)

    def test_post_mixed_status_quality_and_coverage_ratio(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_points",
                return_value=[
                    {"elevation_m": 150.0, "status": "ok"},
                    {"elevation_m": 101.0, "status": "ok"},
                    {"elevation_m": None, "status": "nodata"},
                    {"elevation_m": None, "status": "out_of_coverage"},
                ],
            ):
                with self.make_client() as client:
                    response = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=self.elevations_request(self.eastward_line(600.0)),
                    )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assert_envelope(payload, total_points=3)
        self.assertEqual(
            [point["status"] for point in payload["data"]["points"]],
            ["ok", "nodata", "out_of_coverage"],
        )
        self.assertEqual(payload["quality"]["total"], 4)
        self.assertEqual(payload["quality"]["ok"], 2)
        self.assertEqual(payload["quality"]["nodata"], 1)
        self.assertEqual(payload["quality"]["out_of_coverage"], 1)
        self.assertAlmostEqual(payload["quality"]["coverage_ratio"], 0.5, places=10)
        self.assertEqual(
            [point["chainage_m"] for point in payload["data"]["points"]],
            [200.0, 400.0, 600.0],
        )
        self.assertEqual(
            payload["data"]["start_point"],
            {"chainage_m": 0.0, "elevation_m": 150.0, "status": "ok"},
        )
        self.assertEqual(payload["data"]["end_point"]["chainage_m"], 600.0)
        self.assertEqual(payload["data"]["end_point"]["status"], "out_of_coverage")

    def test_density_samples_line_at_fixed_intervals(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_points",
                return_value=[
                    {"elevation_m": 9.0, "status": "ok"},
                    {"elevation_m": 1.0, "status": "ok"},
                    {"elevation_m": 2.0, "status": "ok"},
                    {"elevation_m": 3.0, "status": "ok"},
                    {"elevation_m": 4.0, "status": "ok"},
                    {"elevation_m": 5.0, "status": "ok"},
                ],
            ):
                with self.make_client() as client:
                    response = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=self.elevations_request(self.eastward_line(1000.0)),
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assert_envelope(payload, total_points=5)
        self.assertEqual(
            [point["chainage_m"] for point in payload["data"]["points"]],
            [200.0, 400.0, 600.0, 800.0, 1000.0],
        )
        self.assertAlmostEqual(payload["line_length_m"], 1000.0, delta=0.001)
        self.assertEqual(
            payload["data"]["start_point"],
            {"chainage_m": 0.0, "elevation_m": 9.0, "status": "ok"},
        )
        self.assertEqual(
            payload["data"]["end_point"],
            {"chainage_m": 1000.0, "elevation_m": 5.0, "status": "ok"},
        )

    def test_interpolates_across_multisegment_line(self):
        delta_100 = math.degrees(100.0 / app_module.EARTH_RADIUS_M)
        delta_200 = math.degrees(200.0 / app_module.EARTH_RADIUS_M)
        delta_300 = math.degrees(300.0 / app_module.EARTH_RADIUS_M)
        line = [
            [0.0, 0.0],
            [delta_300, 0.0],
            [delta_300, delta_300],
        ]

        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_points",
                return_value=[
                    {"elevation_m": 13.0, "status": "ok"},
                    {"elevation_m": 10.0, "status": "ok"},
                    {"elevation_m": 11.0, "status": "ok"},
                    {"elevation_m": 12.0, "status": "ok"},
                ],
            ) as sample_points:
                with self.make_client() as client:
                    response = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=self.elevations_request(line),
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assert_envelope(payload, total_points=3)
        self.assertEqual(sample_points.call_count, 1)
        sampled_coords = sample_points.call_args.args[0]
        self.assertEqual(len(sampled_coords), 4)
        self.assertAlmostEqual(sampled_coords[0][0], 0.0, delta=1e-9)
        self.assertAlmostEqual(sampled_coords[0][1], 0.0, delta=1e-9)
        self.assertAlmostEqual(sampled_coords[1][0], 0.0, delta=1e-9)
        self.assertAlmostEqual(sampled_coords[1][1], delta_200, delta=1e-9)
        self.assertAlmostEqual(sampled_coords[2][0], delta_100, delta=1e-9)
        self.assertAlmostEqual(sampled_coords[2][1], delta_300, delta=1e-9)
        self.assertAlmostEqual(sampled_coords[3][0], delta_300, delta=1e-9)
        self.assertAlmostEqual(sampled_coords[3][1], delta_300, delta=1e-9)
        self.assertEqual(
            payload["data"]["start_point"],
            {"chainage_m": 0.0, "elevation_m": 13.0, "status": "ok"},
        )
        self.assertEqual(
            payload["data"]["end_point"],
            {"chainage_m": 600.0, "elevation_m": 12.0, "status": "ok"},
        )

    def test_interpolates_diagonal_segment_geodesically(self):
        start_lat = 10.0
        start_lng = 0.0
        end_lat = 50.0
        end_lng = 60.0
        line_length_m = app_module._haversine_distance_m(start_lat, start_lng, end_lat, end_lng)
        midpoint_chainage_m = line_length_m / 2.0
        phi1 = math.radians(start_lat)
        phi2 = math.radians(end_lat)
        delta_lng_r = math.radians(end_lng - start_lng)
        bx = math.cos(phi2) * math.cos(delta_lng_r)
        by = math.cos(phi2) * math.sin(delta_lng_r)
        expected_mid_lat = math.degrees(
            math.atan2(
                math.sin(phi1) + math.sin(phi2),
                math.sqrt((math.cos(phi1) + bx) ** 2 + by**2),
            )
        )
        expected_mid_lng = start_lng + math.degrees(math.atan2(by, math.cos(phi1) + bx))

        with patch.object(app_module, "MAX_LINE_LENGTH_M", line_length_m + 1.0):
            with patch.object(app_module.dem, "_open_dataset", return_value=object()):
                with patch.object(
                    app_module.dem,
                    "sample_points",
                    return_value=[
                        {"elevation_m": 30.0, "status": "ok"},
                        {"elevation_m": 10.0, "status": "ok"},
                        {"elevation_m": 20.0, "status": "ok"},
                    ],
                ) as sample_points:
                    with self.make_client() as client:
                        response = client.post(
                            "/elevations",
                            headers={"X-API-Key": "test-api-key"},
                            json=self.elevations_request(
                                [[start_lng, start_lat], [end_lng, end_lat]],
                                density_m=midpoint_chainage_m,
                            ),
                        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(sample_points.call_count, 1)
        sampled_coords = sample_points.call_args.args[0]
        self.assertEqual(len(sampled_coords), 3)
        self.assertAlmostEqual(sampled_coords[1][0], expected_mid_lat, delta=1e-9)
        self.assertAlmostEqual(sampled_coords[1][1], expected_mid_lng, delta=1e-9)
        self.assertNotAlmostEqual(sampled_coords[1][0], 30.0, delta=1e-3)
        self.assertNotAlmostEqual(sampled_coords[1][1], 22.5, delta=1e-3)

    def test_invalid_request_body_shapes_map_to_common_error_envelope(self):
        invalid_payloads = [
            {"geojson": self.line_feature_collection(self.eastward_line(200.0))},
            {"geojson": {"points": [{"lat": 46.8139, "lng": -71.2080}]}, "density_m": 200},
            {"geojson": {"type": "FeatureCollection", "features": []}, "density_m": 200},
            {
                "geojson": {
                    "type": "FeatureCollection",
                    "features": [self.line_feature_collection(self.eastward_line(200.0))["features"][0]] * 2,
                },
                "density_m": 200,
            },
            {
                "geojson": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
                            "properties": None,
                        }
                    ],
                },
                "density_m": 200,
            },
            {"geojson": self.line_feature_collection([[0.0], [1.0]]), "density_m": 200},
            {"geojson": self.line_feature_collection([[0.0, 95.0], [1.0, 0.0]]), "density_m": 200},
        ]

        with self.make_client() as client:
            for payload in invalid_payloads:
                response = client.post(
                    "/elevations",
                    headers={"X-API-Key": "test-api-key"},
                    json=payload,
                )
                self.assert_error(response, "invalid_request", 400)

    def test_density_must_exceed_100m(self):
        with self.make_client() as client:
            response = client.post(
                "/elevations",
                headers={"X-API-Key": "test-api-key"},
                json=self.elevations_request(self.eastward_line(200.0), density_m=100.0),
            )
        self.assert_error(response, "invalid_request", 400)

    def test_dense_input_line_is_accepted_when_request_body_fits(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_points",
                return_value=[
                    {"elevation_m": 10.0, "status": "ok"},
                    {"elevation_m": 20.0, "status": "ok"},
                ],
            ):
                dense_line = [[idx * 1e-6, 0.0] for idx in range(1500)]
                with self.make_client() as client:
                    response = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=self.elevations_request(dense_line, density_m=1000000),
                    )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data"]["points"], [])
        self.assertEqual(body["quality"]["total"], 2)
        self.assertEqual(body["quality"]["ok"], 2)

    def test_line_longer_than_50km_returns_invalid_request_without_sampling(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_points",
                return_value=[],
            ) as sample_points:
                with self.make_client() as client:
                    response = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=self.elevations_request(self.eastward_line(50001.0)),
                    )

        body = self.assert_error(response, "invalid_request", 400)
        self.assertEqual(body["error"]["message"], "Line length exceeds max of 50000.0 m")
        self.assertEqual(sample_points.call_count, 0)

    def test_request_body_larger_than_limit_returns_413(self):
        with self.make_client(max_request_body_bytes=64) as client:
            response = client.post(
                "/elevations",
                headers={"X-API-Key": "test-api-key"},
                json=self.elevations_request(self.eastward_line(200.0)),
            )

        body = self.assert_error(response, "payload_too_large", 413)
        self.assertEqual(body["error"]["message"], "Request body too large; max is 64 bytes")

    def test_chunked_request_without_content_length_streams_to_route(self):
        payload = (
            b'{"geojson":{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"LineString",'
            b'"coordinates":[[0,0],[0.01,0]]},"properties":null}]},"density_m":200}'
        )
        app = app_module.create_app(AppConfig(api_key="test-api-key", max_request_body_bytes=1_000_000))

        async def run_request():
            messages = deque(
                [
                    {"type": "http.request", "body": payload[:32], "more_body": True},
                    {"type": "http.request", "body": payload[32:96], "more_body": True},
                    {"type": "http.request", "body": payload[96:], "more_body": False},
                ]
            )
            sent = []

            async def receive():
                if messages:
                    return messages.popleft()
                return {"type": "http.disconnect"}

            async def send(message):
                sent.append(message)

            scope = {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/elevations",
                "raw_path": b"/elevations",
                "query_string": b"",
                "headers": [
                    (b"host", b"testserver"),
                    (b"content-type", b"application/json"),
                    (b"x-api-key", b"test-api-key"),
                ],
                "client": ("testclient", 50000),
                "server": ("testserver", 80),
            }

            with patch.object(app_module.dem, "_open_dataset", return_value=object()):
                with patch.object(
                    app_module.dem,
                    "sample_points",
                    return_value=[
                        {"elevation_m": 10.0, "status": "ok"},
                        {"elevation_m": 20.0, "status": "ok"},
                    ],
                ) as sample_points:
                    await app(scope, receive, send)
            return sent, sample_points.call_count

        messages, sample_points_call_count = asyncio.run(run_request())

        start = next(message for message in messages if message["type"] == "http.response.start")
        body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        payload_json = json.loads(body)

        self.assertEqual(start["status"], 200)
        self.assertEqual(sample_points_call_count, 1)
        self.assertEqual(payload_json["quality"]["total"], 3)

    def test_chunked_request_body_larger_than_limit_returns_413(self):
        payload = (
            b'{"geojson":{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"LineString",'
            b'"coordinates":[[0,0],[1,1]]},"properties":null}]},"density_m":200}'
        )
        app = app_module.create_app(AppConfig(api_key="test-api-key", max_request_body_bytes=64))

        async def run_request():
            messages = deque(
                [
                    {"type": "http.request", "body": payload[:32], "more_body": True},
                    {"type": "http.request", "body": payload[32:96], "more_body": True},
                    {"type": "http.request", "body": payload[96:], "more_body": False},
                ]
            )
            sent = []
            receive_calls = 0

            async def receive():
                nonlocal receive_calls
                receive_calls += 1
                if messages:
                    return messages.popleft()
                return {"type": "http.disconnect"}

            async def send(message):
                sent.append(message)

            scope = {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/elevations",
                "raw_path": b"/elevations",
                "query_string": b"",
                "headers": [
                    (b"host", b"testserver"),
                    (b"content-type", b"application/json"),
                    (b"x-api-key", b"test-api-key"),
                ],
                "client": ("testclient", 50000),
                "server": ("testserver", 80),
            }

            with patch.object(app_module.dem, "_open_dataset", return_value=object()):
                with patch.object(app_module.dem, "sample_points", return_value=[]) as sample_points:
                    await app(scope, receive, send)
            return sent, receive_calls, sample_points.call_count, len(messages)

        messages, receive_calls, sample_points_call_count, remaining_messages = asyncio.run(run_request())

        start = next(message for message in messages if message["type"] == "http.response.start")
        body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        payload_json = json.loads(body)

        self.assertEqual(start["status"], 413)
        self.assertEqual(payload_json["error"]["code"], "payload_too_large")
        self.assertEqual(payload_json["error"]["message"], "Request body too large; max is 64 bytes")
        self.assertTrue(payload_json["request_id"])
        self.assertEqual(sample_points_call_count, 0)
        self.assertLess(receive_calls, 3)
        self.assertGreater(remaining_messages, 0)

    def test_request_id_echo_and_generation(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_points",
                return_value=[
                    {"elevation_m": 8.0, "status": "ok"},
                    {"elevation_m": 8.0, "status": "ok"},
                ],
            ):
                with self.make_client() as client:
                    payload = self.elevations_request(self.eastward_line(200.0))
                    echoed = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key", "X-Request-ID": "req-123"},
                        json=payload,
                    )
                    generated = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=payload,
                    )

        self.assertEqual(echoed.status_code, 200)
        self.assertEqual(generated.status_code, 200)

        echoed_payload = echoed.json()
        generated_payload = generated.json()

        self.assertEqual(echoed.headers["x-request-id"], "req-123")
        self.assertEqual(echoed_payload["source"]["request_id"], "req-123")
        generated_request_id = generated_payload["source"]["request_id"]
        self.assertTrue(generated_request_id)
        uuid.UUID(generated_request_id)
        self.assertEqual(generated.headers["x-request-id"], generated_request_id)

    def test_width_endpoint_removed_returns_404(self):
        with self.make_client() as client:
            response = client.post(
                "/width",
                headers={"X-API-Key": "test-api-key"},
                json=self.elevations_request(self.eastward_line(200.0)),
            )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
