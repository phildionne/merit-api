import asyncio
import json
import unittest
import uuid
from collections import deque
from unittest.mock import patch

from api import app as app_module
from api.config import AppConfig
from fastapi.testclient import TestClient
from rasterio.errors import RasterioIOError


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
        self.assertNotIn("line_length_m", payload)
        self.assertIn("quality", payload)
        self.assertIn("data", payload)
        self.assertEqual(set(payload["data"].keys()), {"points"})
        self.assertEqual(len(payload["data"]["points"]), total_points)
        for point in payload["data"]["points"]:
            self.assertEqual(set(point.keys()), {"id", "elevation_m", "status"})

    def assert_error(self, response, code: str, status_code: int):
        self.assertEqual(response.status_code, status_code)
        body = response.json()
        self.assertEqual(body["error"]["code"], code)
        self.assertIn("message", body["error"])
        self.assertIn("request_id", body)
        self.assertEqual(response.headers["x-request-id"], body["request_id"])
        return body

    def elevations_request(self, points):
        return {"points": points}

    def sample_point(self, point_id: str, lng: float, lat: float):
        return {"id": point_id, "coordinates": [lng, lat]}

    def test_health_is_liveness_only(self):
        with patch.object(
            app_module.dem, "_open_dataset", side_effect=RasterioIOError("dem missing")
        ):
            with self.make_client() as client:
                response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "status": "alive"})

    def test_ready_returns_service_specific_checks(self):
        with patch.object(
            app_module.dem, "_open_dataset", side_effect=RasterioIOError("dem missing")
        ):
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
        request_payload = self.elevations_request(
            [self.sample_point("point-0", -71.2080, 46.8139)]
        )
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_points",
                return_value=[{"elevation_m": 123.45, "status": "ok"}],
            ) as sample_points:
                with self.make_client() as client:
                    unauthorized = client.post("/elevations", json=request_payload)
                    authorized = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=request_payload,
                    )
        self.assert_error(unauthorized, "unauthorized", 401)
        self.assertEqual(authorized.status_code, 200)
        payload = authorized.json()
        self.assert_envelope(payload, total_points=1)
        self.assertEqual(
            payload["data"]["points"][0],
            {"id": "point-0", "elevation_m": 123.45, "status": "ok"},
        )
        self.assertEqual(sample_points.call_count, 1)
        self.assertEqual(sample_points.call_args.args[0], [(46.8139, -71.2080)])

    def test_post_elevations_returns_not_ready_when_server_api_key_missing(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with self.make_client(api_key="") as client:
                response = client.post(
                    "/elevations",
                    headers={"X-API-Key": "any-key"},
                    json=self.elevations_request(
                        [self.sample_point("point-0", -71.2080, 46.8139)]
                    ),
                )

        body = self.assert_error(response, "not_ready", 503)
        self.assertEqual(body["error"]["message"], "API key not configured")

    def test_post_elevations_returns_not_ready_when_dem_read_fails_during_sampling(
        self,
    ):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_points",
                side_effect=RasterioIOError("tile missing"),
            ):
                with self.make_client() as client:
                    response = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=self.elevations_request(
                            [self.sample_point("point-0", -71.2080, 46.8139)]
                        ),
                    )

        body = self.assert_error(response, "not_ready", 503)
        self.assertEqual(body["error"]["message"], "DEM dataset not available")

    def test_post_elevations_out_of_coverage_returns_200(self):
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_points",
                return_value=[{"elevation_m": None, "status": "out_of_coverage"}],
            ):
                with self.make_client() as client:
                    response = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=self.elevations_request(
                            [self.sample_point("point-0", -71.2080, 46.8139)]
                        ),
                    )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assert_envelope(payload, total_points=1)
        self.assertEqual(
            payload["data"]["points"][0],
            {"id": "point-0", "elevation_m": None, "status": "out_of_coverage"},
        )

    def test_post_mixed_status_quality_and_coverage_ratio(self):
        request_payload = self.elevations_request(
            [
                self.sample_point("point-0", -71.2080, 46.8139),
                self.sample_point("point-1", -71.2050, 46.8145),
                self.sample_point("point-2", -71.2000, 46.8150),
                self.sample_point("point-3", -71.1990, 46.8160),
            ]
        )
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
                        json=request_payload,
                    )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assert_envelope(payload, total_points=4)
        self.assertEqual(
            payload["data"]["points"],
            [
                {"id": "point-0", "elevation_m": 150.0, "status": "ok"},
                {"id": "point-1", "elevation_m": 101.0, "status": "ok"},
                {"id": "point-2", "elevation_m": None, "status": "nodata"},
                {"id": "point-3", "elevation_m": None, "status": "out_of_coverage"},
            ],
        )
        self.assertEqual(payload["quality"]["total"], 4)
        self.assertEqual(payload["quality"]["ok"], 2)
        self.assertEqual(payload["quality"]["nodata"], 1)
        self.assertEqual(payload["quality"]["out_of_coverage"], 1)
        self.assertAlmostEqual(payload["quality"]["coverage_ratio"], 0.5, places=10)

    def test_repeated_coordinates_with_different_ids_preserve_order(self):
        request_payload = self.elevations_request(
            [
                self.sample_point("point-a", -71.2080, 46.8139),
                self.sample_point("point-b", -71.2080, 46.8139),
            ]
        )
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_points",
                return_value=[
                    {"elevation_m": 10.0, "status": "ok"},
                    {"elevation_m": 10.0, "status": "ok"},
                ],
            ) as sample_points:
                with self.make_client() as client:
                    response = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=request_payload,
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["data"]["points"],
            [
                {"id": "point-a", "elevation_m": 10.0, "status": "ok"},
                {"id": "point-b", "elevation_m": 10.0, "status": "ok"},
            ],
        )
        self.assertEqual(
            sample_points.call_args.args[0],
            [(46.8139, -71.2080), (46.8139, -71.2080)],
        )

    def test_removed_and_unsupported_elevation_routes_return_default_statuses(self):
        with self.make_client() as client:
            get_elevation = client.get("/elevation")
            post_elevation = client.post(
                "/elevation",
                headers={"X-API-Key": "test-api-key"},
                json=self.elevations_request(
                    [self.sample_point("point-0", -71.2080, 46.8139)]
                ),
            )
            get_elevations = client.get("/elevations")

        self.assertEqual(get_elevation.status_code, 404)
        self.assertEqual(post_elevation.status_code, 404)
        self.assertEqual(get_elevations.status_code, 405)

    def test_invalid_request_body_shapes_map_to_common_error_envelope(self):
        invalid_payloads = [
            {},
            {"points": []},
            {"points": [{"coordinates": [-71.2080, 46.8139]}]},
            {"points": [{"id": "point-0"}]},
            {"points": [{"id": "", "coordinates": [-71.2080, 46.8139]}]},
            {"points": [{"id": "point-0", "coordinates": [-71.2080]}]},
            {"points": [{"id": "point-0", "coordinates": [-71.2080, 46.8139, 10.0]}]},
            {"points": [{"id": "point-0", "coordinates": [-71.2080, 95.0]}]},
            {
                "points": [
                    self.sample_point("duplicate", -71.2080, 46.8139),
                    self.sample_point("duplicate", -71.2050, 46.8145),
                ]
            },
            {
                "points": [
                    dict(self.sample_point("point-0", -71.2080, 46.8139), extra=True)
                ]
            },
            {
                "points": [self.sample_point("point-0", -71.2080, 46.8139)],
                "extra": True,
            },
        ]

        with self.make_client() as client:
            for payload in invalid_payloads:
                response = client.post(
                    "/elevations",
                    headers={"X-API-Key": "test-api-key"},
                    json=payload,
                )
                self.assert_error(response, "invalid_request", 400)

    def test_large_point_batch_is_accepted_when_request_body_fits(self):
        points = [
            self.sample_point(
                f"point-{idx}", -71.2080 + idx * 1e-6, 46.8139 + idx * 1e-6
            )
            for idx in range(1500)
        ]
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_points",
                side_effect=lambda coords: [
                    {"elevation_m": float(idx), "status": "ok"}
                    for idx, _ in enumerate(coords)
                ],
            ) as sample_points:
                with self.make_client() as client:
                    response = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=self.elevations_request(points),
                    )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assert_envelope(body, total_points=1500)
        self.assertEqual(body["quality"]["total"], 1500)
        self.assertEqual(body["quality"]["ok"], 1500)
        self.assertEqual(sample_points.call_count, 1)

    def test_request_body_larger_than_limit_returns_413(self):
        oversized_payload = self.elevations_request(
            [self.sample_point("point-with-a-very-long-identifier", -71.2080, 46.8139)]
        )
        with self.make_client(max_request_body_bytes=64) as client:
            response = client.post(
                "/elevations",
                headers={"X-API-Key": "test-api-key"},
                json=oversized_payload,
            )

        body = self.assert_error(response, "payload_too_large", 413)
        self.assertEqual(
            body["error"]["message"], "Request body too large; max is 64 bytes"
        )

    def test_chunked_request_without_content_length_streams_to_route(self):
        payload = b'{"points":[{"id":"point-0","coordinates":[-71.208,46.8139]}]}'
        app = app_module.create_app(
            AppConfig(api_key="test-api-key", max_request_body_bytes=1_000_000)
        )

        async def run_request():
            messages = deque(
                [
                    {"type": "http.request", "body": payload[:24], "more_body": True},
                    {"type": "http.request", "body": payload[24:48], "more_body": True},
                    {"type": "http.request", "body": payload[48:], "more_body": False},
                ]
            )
            sent = []
            response_complete = asyncio.Event()

            async def receive():
                if messages:
                    return messages.popleft()
                await response_complete.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                sent.append(message)
                if message["type"] == "http.response.body" and not message.get(
                    "more_body", False
                ):
                    response_complete.set()

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
                    return_value=[{"elevation_m": 10.0, "status": "ok"}],
                ) as sample_points:
                    await app(scope, receive, send)
            return sent, sample_points.call_count

        messages, sample_points_call_count = asyncio.run(run_request())

        start = next(
            message for message in messages if message["type"] == "http.response.start"
        )
        body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        payload_json = json.loads(body)

        self.assertEqual(start["status"], 200)
        self.assertEqual(sample_points_call_count, 1)
        self.assertEqual(payload_json["quality"]["total"], 1)
        self.assertEqual(
            payload_json["data"]["points"],
            [{"id": "point-0", "elevation_m": 10.0, "status": "ok"}],
        )

    def test_chunked_request_body_larger_than_limit_returns_413(self):
        payload = b'{"points":[{"id":"point-0","coordinates":[-71.208,46.8139]},{"id":"point-1","coordinates":[-71.205,46.8145]}]}'
        app = app_module.create_app(
            AppConfig(api_key="test-api-key", max_request_body_bytes=64)
        )

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
            response_complete = asyncio.Event()

            async def receive():
                nonlocal receive_calls
                receive_calls += 1
                if messages:
                    return messages.popleft()
                await response_complete.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                sent.append(message)
                if message["type"] == "http.response.body" and not message.get(
                    "more_body", False
                ):
                    response_complete.set()

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
                    app_module.dem, "sample_points", return_value=[]
                ) as sample_points:
                    await app(scope, receive, send)
            return sent, receive_calls, sample_points.call_count, len(messages)

        messages, receive_calls, sample_points_call_count, remaining_messages = (
            asyncio.run(run_request())
        )

        start = next(
            message for message in messages if message["type"] == "http.response.start"
        )
        body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        payload_json = json.loads(body)

        self.assertEqual(start["status"], 413)
        self.assertEqual(payload_json["error"]["code"], "payload_too_large")
        self.assertEqual(
            payload_json["error"]["message"], "Request body too large; max is 64 bytes"
        )
        self.assertTrue(payload_json["request_id"])
        self.assertEqual(sample_points_call_count, 0)
        self.assertLess(receive_calls, 3)
        self.assertGreater(remaining_messages, 0)

    def test_request_id_echo_and_generation(self):
        request_payload = self.elevations_request(
            [self.sample_point("point-0", -71.2080, 46.8139)]
        )
        with patch.object(app_module.dem, "_open_dataset", return_value=object()):
            with patch.object(
                app_module.dem,
                "sample_points",
                return_value=[{"elevation_m": 8.0, "status": "ok"}],
            ):
                with self.make_client() as client:
                    echoed = client.post(
                        "/elevations",
                        headers={
                            "X-API-Key": "test-api-key",
                            "X-Request-ID": "req-123",
                        },
                        json=request_payload,
                    )
                    generated = client.post(
                        "/elevations",
                        headers={"X-API-Key": "test-api-key"},
                        json=request_payload,
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
                json=self.elevations_request(
                    [self.sample_point("point-0", -71.2080, 46.8139)]
                ),
            )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
