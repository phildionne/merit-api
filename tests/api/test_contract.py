import asyncio
import json
import uuid
from collections import deque
from collections.abc import Callable
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from httpx import Response as HttpxResponse
from rasterio.errors import RasterioIOError

from merit_api import app as app_module
from merit_api.config import AppConfig


@pytest.fixture
def make_client() -> Callable[..., TestClient]:
    def _make_client(**overrides: object) -> TestClient:
        config = AppConfig(
            api_key=overrides.pop("api_key", "test-api-key"),
            max_request_body_bytes=overrides.pop("max_request_body_bytes", 2_000_000),
            allowed_origins=overrides.pop("allowed_origins", ["*"]),
            trust_x_request_id=overrides.pop("trust_x_request_id", True),
            enable_docs=overrides.pop("enable_docs", True),
        )
        assert not overrides
        return TestClient(app_module.create_app(config))

    return _make_client


def _assert_envelope(payload: dict[str, object], total_points: int) -> None:
    assert payload["version"] == 1
    assert "source" in payload
    assert "generated_at" in payload["source"]
    assert "request_id" in payload["source"]
    assert payload["source"]["generated_at"].endswith("Z")
    assert "line_length_m" not in payload
    assert "quality" in payload
    assert "data" in payload
    assert set(payload["data"].keys()) == {"points"}
    assert len(payload["data"]["points"]) == total_points
    for point in payload["data"]["points"]:
        assert set(point.keys()) == {"id", "elevation_m", "status"}


def _assert_error(response: HttpxResponse, code: str, status_code: int) -> dict[str, object]:
    assert response.status_code == status_code
    body = response.json()
    assert body["error"]["code"] == code
    assert "message" in body["error"]
    assert "request_id" in body
    assert response.headers["x-request-id"] == body["request_id"]
    return body


def _elevations_request(points: list[dict[str, object]]) -> dict[str, object]:
    return {"points": points}


def _sample_point(point_id: str, lng: float, lat: float) -> dict[str, object]:
    return {"id": point_id, "coordinates": [lng, lat]}


def test_health_is_liveness_only(make_client: Callable[..., TestClient]) -> None:
    with patch.object(app_module.dem, "_open_dataset", side_effect=RasterioIOError("dem missing")):
        with make_client() as client:
            response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "status": "alive"}


def test_ready_returns_service_specific_checks(
    make_client: Callable[..., TestClient],
) -> None:
    with patch.object(app_module.dem, "_open_dataset", side_effect=RasterioIOError("dem missing")):
        with make_client() as client:
            response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "status": "not_ready",
        "checks": {"api_key": True, "dem": False},
    }


def test_ready_returns_503_when_api_key_not_configured(
    make_client: Callable[..., TestClient],
) -> None:
    with patch.object(app_module.dem, "_open_dataset", return_value=object()):
        with make_client(api_key="") as client:
            response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "status": "not_ready",
        "checks": {"api_key": False, "dem": True},
    }


def test_post_elevations_requires_api_key(make_client: Callable[..., TestClient]) -> None:
    request_payload = _elevations_request([_sample_point("point-0", -71.2080, 46.8139)])

    with patch.object(app_module.dem, "_open_dataset", return_value=object()):
        with patch.object(
            app_module.dem,
            "sample_points",
            return_value=[{"elevation_m": 123.45, "status": "ok"}],
        ) as sample_points:
            with make_client() as client:
                unauthorized = client.post("/elevations", json=request_payload)
                authorized = client.post(
                    "/elevations",
                    headers={"X-API-Key": "test-api-key"},
                    json=request_payload,
                )

    _ = _assert_error(unauthorized, "unauthorized", 401)
    assert authorized.status_code == 200
    payload = authorized.json()
    _assert_envelope(payload, total_points=1)
    assert payload["data"]["points"][0] == {
        "id": "point-0",
        "elevation_m": 123.45,
        "status": "ok",
    }
    assert sample_points.call_count == 1
    assert sample_points.call_args.args[0] == [(46.8139, -71.2080)]


def test_post_elevations_returns_not_ready_when_server_api_key_missing(
    make_client: Callable[..., TestClient],
) -> None:
    with patch.object(app_module.dem, "_open_dataset", return_value=object()):
        with make_client(api_key="") as client:
            response = client.post(
                "/elevations",
                headers={"X-API-Key": "any-key"},
                json=_elevations_request([_sample_point("point-0", -71.2080, 46.8139)]),
            )

    body = _assert_error(response, "not_ready", 503)
    assert body["error"]["message"] == "API key not configured"


def test_post_elevations_returns_not_ready_when_dem_read_fails_during_sampling(
    make_client: Callable[..., TestClient],
) -> None:
    with patch.object(app_module.dem, "_open_dataset", return_value=object()):
        with patch.object(
            app_module.dem,
            "sample_points",
            side_effect=RasterioIOError("tile missing"),
        ):
            with make_client() as client:
                response = client.post(
                    "/elevations",
                    headers={"X-API-Key": "test-api-key"},
                    json=_elevations_request([_sample_point("point-0", -71.2080, 46.8139)]),
                )

    body = _assert_error(response, "not_ready", 503)
    assert body["error"]["message"] == "DEM dataset not available"


def test_post_elevations_out_of_coverage_returns_200(
    make_client: Callable[..., TestClient],
) -> None:
    with patch.object(app_module.dem, "_open_dataset", return_value=object()):
        with patch.object(
            app_module.dem,
            "sample_points",
            return_value=[{"elevation_m": None, "status": "out_of_coverage"}],
        ):
            with make_client() as client:
                response = client.post(
                    "/elevations",
                    headers={"X-API-Key": "test-api-key"},
                    json=_elevations_request([_sample_point("point-0", -71.2080, 46.8139)]),
                )

    assert response.status_code == 200
    payload = response.json()
    _assert_envelope(payload, total_points=1)
    assert payload["data"]["points"][0] == {
        "id": "point-0",
        "elevation_m": None,
        "status": "out_of_coverage",
    }


def test_post_mixed_status_quality_and_coverage_ratio(
    make_client: Callable[..., TestClient],
) -> None:
    request_payload = _elevations_request(
        [
            _sample_point("point-0", -71.2080, 46.8139),
            _sample_point("point-1", -71.2050, 46.8145),
            _sample_point("point-2", -71.2000, 46.8150),
            _sample_point("point-3", -71.1990, 46.8160),
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
            with make_client() as client:
                response = client.post(
                    "/elevations",
                    headers={"X-API-Key": "test-api-key"},
                    json=request_payload,
                )

    assert response.status_code == 200
    payload = response.json()
    _assert_envelope(payload, total_points=4)
    assert payload["data"]["points"] == [
        {"id": "point-0", "elevation_m": 150.0, "status": "ok"},
        {"id": "point-1", "elevation_m": 101.0, "status": "ok"},
        {"id": "point-2", "elevation_m": None, "status": "nodata"},
        {"id": "point-3", "elevation_m": None, "status": "out_of_coverage"},
    ]
    assert payload["quality"]["total"] == 4
    assert payload["quality"]["ok"] == 2
    assert payload["quality"]["nodata"] == 1
    assert payload["quality"]["out_of_coverage"] == 1
    assert payload["quality"]["coverage_ratio"] == pytest.approx(0.5)


def test_repeated_coordinates_with_different_ids_preserve_order(
    make_client: Callable[..., TestClient],
) -> None:
    request_payload = _elevations_request(
        [
            _sample_point("point-a", -71.2080, 46.8139),
            _sample_point("point-b", -71.2080, 46.8139),
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
            with make_client() as client:
                response = client.post(
                    "/elevations",
                    headers={"X-API-Key": "test-api-key"},
                    json=request_payload,
                )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["points"] == [
        {"id": "point-a", "elevation_m": 10.0, "status": "ok"},
        {"id": "point-b", "elevation_m": 10.0, "status": "ok"},
    ]
    assert sample_points.call_args.args[0] == [
        (46.8139, -71.2080),
        (46.8139, -71.2080),
    ]


def test_removed_and_unsupported_elevation_routes_return_default_statuses(
    make_client: Callable[..., TestClient],
) -> None:
    with make_client() as client:
        get_elevation = client.get("/elevation")
        post_elevation = client.post(
            "/elevation",
            headers={"X-API-Key": "test-api-key"},
            json=_elevations_request([_sample_point("point-0", -71.2080, 46.8139)]),
        )
        get_elevations = client.get("/elevations")

    assert get_elevation.status_code == 404
    assert post_elevation.status_code == 404
    assert get_elevations.status_code == 405


def test_invalid_request_body_shapes_map_to_common_error_envelope(
    make_client: Callable[..., TestClient],
) -> None:
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
                _sample_point("duplicate", -71.2080, 46.8139),
                _sample_point("duplicate", -71.2050, 46.8145),
            ]
        },
        {"points": [dict(_sample_point("point-0", -71.2080, 46.8139), extra=True)]},
        {"points": [_sample_point("point-0", -71.2080, 46.8139)], "extra": True},
    ]

    with make_client() as client:
        for payload in invalid_payloads:
            response = client.post(
                "/elevations",
                headers={"X-API-Key": "test-api-key"},
                json=payload,
            )
            _ = _assert_error(response, "invalid_request", 400)


def test_large_point_batch_is_accepted_when_request_body_fits(
    make_client: Callable[..., TestClient],
) -> None:
    points = [
        _sample_point(f"point-{idx}", -71.2080 + idx * 1e-6, 46.8139 + idx * 1e-6)
        for idx in range(1500)
    ]

    with patch.object(app_module.dem, "_open_dataset", return_value=object()):
        with patch.object(
            app_module.dem,
            "sample_points",
            side_effect=lambda coords: [
                {"elevation_m": float(idx), "status": "ok"} for idx, _ in enumerate(coords)
            ],
        ) as sample_points:
            with make_client() as client:
                response = client.post(
                    "/elevations",
                    headers={"X-API-Key": "test-api-key"},
                    json=_elevations_request(points),
                )

    assert response.status_code == 200
    body = response.json()
    _assert_envelope(body, total_points=1500)
    assert body["quality"]["total"] == 1500
    assert body["quality"]["ok"] == 1500
    assert sample_points.call_count == 1


def test_request_body_larger_than_limit_returns_413(
    make_client: Callable[..., TestClient],
) -> None:
    oversized_payload = _elevations_request(
        [_sample_point("point-with-a-very-long-identifier", -71.2080, 46.8139)]
    )

    with make_client(max_request_body_bytes=64) as client:
        response = client.post(
            "/elevations",
            headers={"X-API-Key": "test-api-key"},
            json=oversized_payload,
        )

    body = _assert_error(response, "payload_too_large", 413)
    assert body["error"]["message"] == "Request body too large; max is 64 bytes"


def test_chunked_request_without_content_length_streams_to_route() -> None:
    payload = b'{"points":[{"id":"point-0","coordinates":[-71.208,46.8139]}]}'
    app = app_module.create_app(AppConfig(api_key="test-api-key", max_request_body_bytes=1_000_000))

    async def run_request() -> tuple[list[dict[str, object]], int]:
        messages = deque(
            [
                {"type": "http.request", "body": payload[:24], "more_body": True},
                {"type": "http.request", "body": payload[24:48], "more_body": True},
                {"type": "http.request", "body": payload[48:], "more_body": False},
            ]
        )
        sent: list[dict[str, object]] = []
        response_complete = asyncio.Event()

        async def receive() -> dict[str, object]:
            if messages:
                return messages.popleft()
            _ = await response_complete.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, object]) -> None:
            sent.append(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
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
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    payload_json = json.loads(body)

    assert start["status"] == 200
    assert sample_points_call_count == 1
    assert payload_json["quality"]["total"] == 1
    assert payload_json["data"]["points"] == [
        {"id": "point-0", "elevation_m": 10.0, "status": "ok"}
    ]


def test_chunked_request_body_larger_than_limit_returns_413() -> None:
    payload = (
        b'{"points":[{"id":"point-0","coordinates":[-71.208,46.8139]},'
        b'{"id":"point-1","coordinates":[-71.205,46.8145]}]}'
    )
    app = app_module.create_app(AppConfig(api_key="test-api-key", max_request_body_bytes=64))

    async def run_request() -> tuple[list[dict[str, object]], int, int, int]:
        messages = deque(
            [
                {"type": "http.request", "body": payload[:32], "more_body": True},
                {"type": "http.request", "body": payload[32:96], "more_body": True},
                {"type": "http.request", "body": payload[96:], "more_body": False},
            ]
        )
        sent: list[dict[str, object]] = []
        receive_calls = 0
        response_complete = asyncio.Event()

        async def receive() -> dict[str, object]:
            nonlocal receive_calls
            receive_calls += 1
            if messages:
                return messages.popleft()
            _ = await response_complete.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, object]) -> None:
            sent.append(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
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
            with patch.object(app_module.dem, "sample_points", return_value=[]) as sample_points:
                await app(scope, receive, send)
        return sent, receive_calls, sample_points.call_count, len(messages)

    messages, receive_calls, sample_points_call_count, remaining_messages = asyncio.run(
        run_request()
    )
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    payload_json = json.loads(body)

    assert start["status"] == 413
    assert payload_json["error"]["code"] == "payload_too_large"
    assert payload_json["error"]["message"] == "Request body too large; max is 64 bytes"
    assert payload_json["request_id"]
    assert sample_points_call_count == 0
    assert receive_calls < 3
    assert remaining_messages > 0


def test_request_id_echo_and_generation(make_client: Callable[..., TestClient]) -> None:
    request_payload = _elevations_request([_sample_point("point-0", -71.2080, 46.8139)])

    with patch.object(app_module.dem, "_open_dataset", return_value=object()):
        with patch.object(
            app_module.dem,
            "sample_points",
            return_value=[{"elevation_m": 8.0, "status": "ok"}],
        ):
            with make_client() as client:
                echoed = client.post(
                    "/elevations",
                    headers={"X-API-Key": "test-api-key", "X-Request-ID": "req-123"},
                    json=request_payload,
                )
                generated = client.post(
                    "/elevations",
                    headers={"X-API-Key": "test-api-key"},
                    json=request_payload,
                )

    assert echoed.status_code == 200
    assert generated.status_code == 200

    echoed_payload = echoed.json()
    generated_payload = generated.json()

    assert echoed.headers["x-request-id"] == "req-123"
    assert echoed_payload["source"]["request_id"] == "req-123"
    generated_request_id = generated_payload["source"]["request_id"]
    assert generated_request_id
    _ = uuid.UUID(generated_request_id)
    assert generated.headers["x-request-id"] == generated_request_id


def test_width_endpoint_removed_returns_404(make_client: Callable[..., TestClient]) -> None:
    with make_client() as client:
        response = client.post(
            "/width",
            headers={"X-API-Key": "test-api-key"},
            json=_elevations_request([_sample_point("point-0", -71.2080, 46.8139)]),
        )

    assert response.status_code == 404
