from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field


def _parse_allowed_origins(raw: str | None) -> list[str]:
    value = (raw or "*").strip()
    if value == "*":
        return ["*"]
    origins = [origin.strip() for origin in value.split(",") if origin.strip()]
    return origins or ["*"]


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class AppConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_key: str = ""
    max_request_body_bytes: int = Field(default=2_000_000, ge=1)
    allowed_origins: list[str] = Field(default_factory=lambda: ["*"])
    trust_x_request_id: bool = True
    enable_docs: bool = True

    @classmethod
    def from_env(cls) -> "AppConfig":
        env = os.environ
        return cls(
            api_key=(env.get("API_KEY") or "").strip(),
            max_request_body_bytes=int(env.get("MAX_REQUEST_BODY_BYTES", "2000000")),
            allowed_origins=_parse_allowed_origins(env.get("ALLOWED_ORIGINS")),
            trust_x_request_id=_parse_bool(
                env.get("MERIT_TRUST_X_REQUEST_ID"), default=True
            ),
            enable_docs=_parse_bool(env.get("MERIT_ENABLE_DOCS"), default=True),
        )
