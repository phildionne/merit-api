import contextvars
import json
import logging
import logging.config
import os
from datetime import datetime, timezone
from typing import Any

request_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_configured = False


def set_request_id(request_id: str | None) -> None:
    request_id_context.set(request_id)


def get_request_id() -> str | None:
    return request_id_context.get()


def clear_request_id() -> None:
    request_id_context.set(None)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()
        if not hasattr(record, "service"):
            record.service = os.getenv("RAILWAY_SERVICE_NAME") or "merit-api"
        if not hasattr(record, "environment"):
            record.environment = os.getenv("RAILWAY_ENVIRONMENT_NAME")
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key in (
            "service",
            "environment",
            "request_id",
            "event",
            "method",
            "path",
            "status_code",
            "duration_ms",
            "client_ip",
            "point_count",
            "line_length_m",
            "coverage_ratio",
            "dem_ready",
            "api_key_configured",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def build_log_config() -> dict[str, Any]:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_context": {
                "()": "api.logging.RequestContextFilter",
            }
        },
        "formatters": {
            "json": {
                "()": "api.logging.JsonFormatter",
            }
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "filters": ["request_context"],
                "formatter": "json",
            }
        },
        "root": {
            "level": os.getenv("LOG_LEVEL", "INFO").upper(),
            "handlers": ["default"],
        },
        "loggers": {
            "gunicorn.error": {
                "level": os.getenv("LOG_LEVEL", "INFO").upper(),
                "handlers": ["default"],
                "propagate": False,
            },
            "gunicorn.access": {
                "level": os.getenv("LOG_LEVEL", "INFO").upper(),
                "handlers": ["default"],
                "propagate": False,
            },
            "uvicorn.error": {
                "level": os.getenv("LOG_LEVEL", "INFO").upper(),
                "handlers": ["default"],
                "propagate": False,
            },
            "uvicorn.access": {
                "level": os.getenv("LOG_LEVEL", "INFO").upper(),
                "handlers": ["default"],
                "propagate": False,
            },
        },
    }


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    logging.config.dictConfig(build_log_config())
    _configured = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
