from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse


@dataclass(frozen=True)
class ApiError(Exception):
    code: str
    message: str
    status_code: int


def request_id_from_request(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return str(rid) if rid else str(uuid4())


def error_response(
    *,
    request: Request,
    code: str,
    message: str,
    status_code: int,
) -> JSONResponse:
    request_id = request_id_from_request(request)
    payload: dict[str, Any] = {
        "error": {"code": code, "message": message},
        "request_id": request_id,
    }
    response = JSONResponse(status_code=status_code, content=payload)
    response.headers["X-Request-ID"] = request_id
    return response
