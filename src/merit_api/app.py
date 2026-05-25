from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from rasterio.errors import RasterioIOError

from . import dem
from . import profile as profile_module
from .config import AppConfig
from .errors import ApiError, error_response, request_id_from_request
from .logging import clear_request_id, configure_logging, get_logger, set_request_id
from .models import (
    ElevationPointsDataResponse,
    ElevationPointsResponse,
    ElevationsRequestBody,
    HealthResponse,
    QualityResponse,
    ReadyResponse,
    SampledPointResponse,
    SourceMetaResponse,
)


def api_key_is_configured(config: AppConfig) -> bool:
    return bool(config.api_key)


def require_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    config: AppConfig = request.app.state.config
    if not api_key_is_configured(config):
        raise ApiError("not_ready", "API key not configured", status.HTTP_503_SERVICE_UNAVAILABLE)
    if not x_api_key:
        raise ApiError("unauthorized", "Missing X-API-Key header", status.HTTP_401_UNAUTHORIZED)
    if x_api_key.strip() != config.api_key:
        raise ApiError("unauthorized", "Invalid API key", status.HTTP_401_UNAUTHORIZED)


def dataset_is_available(dataset_opener: Callable[[], object]) -> bool:
    try:
        _ = dataset_opener()
        return True
    except RasterioIOError:
        return False


def _sample_point_results(
    points: list[tuple[float, float]],
) -> list[dem.SamplePointResult]:
    try:
        return dem.sample_points(points)
    except RasterioIOError:
        raise ApiError(
            "not_ready",
            "DEM dataset not available",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )


def _extract_request_points(
    payload: ElevationsRequestBody,
) -> tuple[list[str], list[tuple[float, float]]]:
    point_ids: list[str] = []
    coords: list[tuple[float, float]] = []

    for point in payload.points:
        lng, lat = point.coordinates
        point_ids.append(point.id)
        coords.append((lat, lng))
    return point_ids, coords


def _build_points_response(
    point_ids: list[str],
    sampled_results: list[dem.SamplePointResult],
    request: Request,
    logger: logging.Logger,
) -> ElevationPointsResponse:
    if len(point_ids) != len(sampled_results):
        raise RuntimeError("mismatched DEM sample results")

    points = [
        SampledPointResponse(
            id=point_id,
            elevation_m=result["elevation_m"],
            status=result["status"],
        )
        for point_id, result in zip(point_ids, sampled_results)
    ]
    request_id = request_id_from_request(request)
    coverage = QualityResponse(**profile_module.build_quality(point.status for point in points))

    logger.info(
        "elevations_sampled",
        extra={
            "event": "elevations_sampled",
            "request_id": request_id,
            "point_count": len(points),
            "coverage_ratio": coverage.coverage_ratio,
        },
    )

    return ElevationPointsResponse(
        version=1,
        source=SourceMetaResponse(generated_at=request.state.generated_at, request_id=request_id),
        data=ElevationPointsDataResponse(points=points),
        quality=coverage,
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

    async def request_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
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
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        )
                except ValueError:
                    pass
            else:
                received_bytes = 0
                buffered_chunks: list[bytes] = []

                async for chunk in request.stream():
                    received_bytes += len(chunk)
                    if received_bytes > cfg_local.max_request_body_bytes:
                        return error_response(
                            request=request,
                            code="payload_too_large",
                            message=f"Request body too large; max is {cfg_local.max_request_body_bytes} bytes",
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        )
                    buffered_chunks.append(chunk)

                request._body = b"".join(buffered_chunks)

        response: Response | None = None
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

        if response is None:
            raise RuntimeError("request middleware completed without a response")
        assert response is not None
        response.headers["X-Request-ID"] = request_id_from_request(request)
        log_level = (
            logging.INFO
            if response.status_code < 400
            else logging.WARNING
            if response.status_code < 500
            else logging.ERROR
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

    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(
            request=request,
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
        )

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

    def health() -> HealthResponse:
        return HealthResponse(ok=True, status="alive")

    def ready(response: Response) -> ReadyResponse:
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

    def elevation_post(
        payload: ElevationsRequestBody,
        request: Request,
    ) -> ElevationPointsResponse:
        point_ids, coords = _extract_request_points(payload)
        sampled_results = _sample_point_results(coords)
        return _build_points_response(point_ids, sampled_results, request, logger)

    _ = app.middleware("http")(request_middleware)
    _ = app.exception_handler(ApiError)(handle_api_error)
    _ = app.exception_handler(RequestValidationError)(handle_validation_error)
    _ = app.exception_handler(Exception)(handle_unexpected_error)
    _ = app.get("/health", response_model=HealthResponse)(health)
    _ = app.get("/ready", response_model=ReadyResponse)(ready)
    _ = app.post(
        "/elevations",
        dependencies=[Depends(require_api_key)],
        response_model=ElevationPointsResponse,
    )(elevation_post)

    return app


def app_factory() -> FastAPI:
    return create_app()


app = create_app()
