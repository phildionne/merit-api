from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from rasterio.errors import RasterioIOError

from . import dem
from .config import AppConfig
from .errors import ApiError, error_response, request_id_from_request
from .logging import clear_request_id, configure_logging, get_logger, set_request_id
from .models import (
    ElevationProfileResponse,
    ElevationsRequestBody,
    HealthResponse,
    ProfilePointResponse,
    QualityResponse,
    ReadyResponse,
    SourceMetaResponse,
)
from . import profile as profile_module

EARTH_RADIUS_M = profile_module.EARTH_RADIUS_M
CHAINAGE_EPSILON_M = profile_module.CHAINAGE_EPSILON_M
MAX_LINE_LENGTH_M = profile_module.MAX_LINE_LENGTH_M
_haversine_distance_m = profile_module.haversine_distance_m
_build_chainage_m = profile_module.build_chainage_m
_build_sample_chainages_m = profile_module.build_sample_chainages_m
_interpolate_samples_along_line = profile_module.interpolate_samples_along_line
_build_quality = profile_module.build_quality


def api_key_is_configured(config: AppConfig) -> bool:
    return bool(config.api_key)


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> None:
    config: AppConfig = request.app.state.config
    if not api_key_is_configured(config):
        raise ApiError("not_ready", "API key not configured", status.HTTP_503_SERVICE_UNAVAILABLE)
    if not x_api_key:
        raise ApiError("unauthorized", "Missing X-API-Key header", status.HTTP_401_UNAUTHORIZED)
    if x_api_key.strip() != config.api_key:
        raise ApiError("unauthorized", "Invalid API key", status.HTTP_401_UNAUTHORIZED)


def ensure_dataset_available() -> None:
    try:
        dem._open_dataset()
    except RasterioIOError:
        raise ApiError("not_ready", "DEM dataset not available", status.HTTP_503_SERVICE_UNAVAILABLE)


def dataset_is_available(dataset_opener) -> bool:
    try:
        dataset_opener()
        return True
    except RasterioIOError:
        return False


def _extract_line_coords(payload) -> list[tuple[float, float]]:
    return [(lat, lng) for lng, lat in payload.features[0].geometry.coordinates]


def _sample_profile_results(points: list[tuple[float, float]]) -> list[dict[str, float | str | None]]:
    try:
        return dem.sample_points(points)
    except RasterioIOError:
        raise ApiError("not_ready", "DEM dataset not available", status.HTTP_503_SERVICE_UNAVAILABLE)


def _build_profile_point(
    chainage_m: float,
    sampled_result: dict[str, float | str | None],
) -> ProfilePointResponse:
    return ProfilePointResponse(
        chainage_m=chainage_m,
        elevation_m=sampled_result["elevation_m"],
        status=sampled_result["status"],
    )


def _build_profile_response(
    line_coords: list[tuple[float, float]],
    coords: list[tuple[float, float]],
    chainages: list[float],
    line_length_m: float,
    request: Request,
    logger,
) -> ElevationProfileResponse:
    start_lat, start_lng = line_coords[0]
    end_lat, end_lng = line_coords[-1]
    endpoint_already_sampled = bool(chainages) and abs(chainages[-1] - line_length_m) <= CHAINAGE_EPSILON_M
    include_end_point = abs(line_length_m) > CHAINAGE_EPSILON_M and not endpoint_already_sampled

    sampled_coords = [(start_lat, start_lng), *coords]
    if include_end_point:
        sampled_coords.append((end_lat, end_lng))
    sampled_results = _sample_profile_results(sampled_coords)

    start_point = _build_profile_point(0.0, sampled_results[0])
    point_results = sampled_results[1 : 1 + len(coords)]
    points = [
        _build_profile_point(chainages[idx], result)
        for idx, result in enumerate(point_results)
    ]

    if endpoint_already_sampled and points:
        end_point = ProfilePointResponse(
            chainage_m=line_length_m,
            elevation_m=points[-1].elevation_m,
            status=points[-1].status,
        )
    elif abs(line_length_m) <= CHAINAGE_EPSILON_M:
        end_point = ProfilePointResponse(
            chainage_m=0.0,
            elevation_m=start_point.elevation_m,
            status=start_point.status,
        )
    else:
        end_point = _build_profile_point(line_length_m, sampled_results[-1])

    statuses = [start_point.status, *[point.status for point in points]]
    if include_end_point:
        statuses.append(end_point.status)
    request_id = request_id_from_request(request)
    coverage = QualityResponse(**_build_quality(statuses))

    logger.info(
        "elevation_profile_generated",
        extra={
            "event": "elevation_profile_generated",
            "request_id": request_id,
            "point_count": len(coords),
            "line_length_m": line_length_m,
            "coverage_ratio": coverage.coverage_ratio,
        },
    )

    return ElevationProfileResponse(
        version=1,
        source=SourceMetaResponse(generated_at=request.state.generated_at, request_id=request_id),
        line_length_m=line_length_m,
        quality=coverage,
        data={
            "start_point": start_point,
            "end_point": end_point,
            "points": points,
        },
    )


def create_app(config: AppConfig | None = None) -> FastAPI:
    configure_logging()
    cfg = config or AppConfig.from_env()
    docs_url = "/docs" if cfg.enable_docs else None
    redoc_url = "/redoc" if cfg.enable_docs else None
    openapi_url = "/openapi.json" if cfg.enable_docs else None
    logger = get_logger(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            "application_started",
            extra={
                "event": "application_started",
                "api_key_configured": api_key_is_configured(app.state.config),
            },
        )
        yield

    app = FastAPI(
        title="MERIT-Hydro API",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        lifespan=lifespan,
    )
    app.state.config = cfg
    app.state.logger = logger

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_middleware(request: Request, call_next):  # type: ignore[no-redef]
        cfg_local: AppConfig = request.app.state.config
        request_id = None
        if cfg_local.trust_x_request_id:
            header_id = request.headers.get("X-Request-ID")
            if header_id:
                request_id = header_id.strip()
        request.state.request_id = request_id or str(uuid.uuid4())
        request.state.generated_at = datetime.now(timezone.utc)
        set_request_id(request.state.request_id)

        start = time.perf_counter()
        if request.method in {"POST", "PUT", "PATCH"}:
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > cfg_local.max_request_body_bytes:
                        return error_response(
                            request=request,
                            code="payload_too_large",
                            message=f"Request body too large; max is {cfg_local.max_request_body_bytes} bytes",
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        )
                except ValueError:
                    pass
            else:
                original_receive = request._receive
                received_bytes = 0
                buffered_messages = []

                while True:
                    message = await original_receive()
                    buffered_messages.append(message)
                    if message["type"] == "http.request":
                        received_bytes += len(message.get("body", b""))
                        if received_bytes > cfg_local.max_request_body_bytes:
                            return error_response(
                                request=request,
                                code="payload_too_large",
                                message=f"Request body too large; max is {cfg_local.max_request_body_bytes} bytes",
                                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            )
                        if not message.get("more_body", False):
                            break
                    else:
                        break

                buffered_iter = iter(buffered_messages)

                async def replay_receive():
                    return next(buffered_iter, {"type": "http.disconnect"})

                request._receive = replay_receive

        response = None
        try:
            response = await call_next(request)
        except ApiError as exc:
            response = error_response(
                request=request,
                code=exc.code,
                message=exc.message,
                status_code=exc.status_code,
            )
        except Exception:
            logger.exception(
                "request_failed",
                extra={
                    "event": "request_failed",
                    "request_id": request_id_from_request(request),
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - start) * 1000.0, 3),
                    "client_ip": request.client.host if request.client else None,
                },
            )
            raise
        finally:
            if response is None:
                clear_request_id()

        response.headers["X-Request-ID"] = request_id_from_request(request)
        log_level = (
            logging.INFO
            if response.status_code < 400
            else logging.WARNING if response.status_code < 500 else logging.ERROR
        )
        logger.log(
            log_level,
            "request_completed",
            extra={
                "event": "request_completed",
                "request_id": request_id_from_request(request),
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000.0, 3),
                "client_ip": request.client.host if request.client else None,
            },
        )
        clear_request_id()
        return response

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(
            request=request,
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        _ = exc
        return error_response(
            request=request,
            code="invalid_request",
            message="Invalid request payload",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_error",
            extra={
                "event": "unhandled_error",
                "request_id": request_id_from_request(request),
                "path": request.url.path,
                "method": request.method,
            },
        )
        _ = exc
        return error_response(
            request=request,
            code="internal_error",
            message="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    @app.get("/health", response_model=HealthResponse)
    def health():
        return HealthResponse(ok=True, status="alive")

    @app.get("/ready", response_model=ReadyResponse)
    def ready(response: Response):
        dem_ready = dataset_is_available(dem._open_dataset)
        api_key_ready = api_key_is_configured(cfg)
        checks = {"api_key": api_key_ready, "dem": dem_ready}
        service_ready = all(checks.values())
        if not service_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        logger.info(
            "readiness_checked",
            extra={
                "event": "readiness_checked",
                "dem_ready": dem_ready,
                "api_key_configured": api_key_ready,
            },
        )
        return ReadyResponse(
            ok=service_ready,
            status="ready" if service_ready else "not_ready",
            checks=checks,
        )

    @app.post("/elevations", dependencies=[Depends(require_api_key)], response_model=ElevationProfileResponse)
    def elevation_post(
        payload: ElevationsRequestBody,
        request: Request,
    ):
        ensure_dataset_available()
        line_coords = _extract_line_coords(payload.geojson)
        vertex_chainages = _build_chainage_m(line_coords)
        line_length_m = vertex_chainages[-1] if vertex_chainages else 0.0
        if line_length_m > MAX_LINE_LENGTH_M + CHAINAGE_EPSILON_M:
            raise ApiError(
                "invalid_request",
                f"Line length exceeds max of {MAX_LINE_LENGTH_M} m",
                status.HTTP_400_BAD_REQUEST,
            )
        sample_chainages = _build_sample_chainages_m(line_length_m, payload.density_m)
        coords = _interpolate_samples_along_line(line_coords, vertex_chainages, sample_chainages)
        return _build_profile_response(line_coords, coords, sample_chainages, line_length_m, request, logger)

    return app


def app_factory() -> FastAPI:
    return create_app()


app = create_app()
