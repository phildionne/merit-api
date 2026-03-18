from fastapi.testclient import TestClient

from api.app import create_app
from api.config import AppConfig


def test_docs_can_be_disabled_explicitly() -> None:
    app = create_app(
        AppConfig(
            api_key="secret",
            enable_docs=False,
        )
    )

    with TestClient(app) as client:
        docs_response = client.get("/docs")
        openapi_response = client.get("/openapi.json")

    assert docs_response.status_code == 404
    assert openapi_response.status_code == 404


def test_x_request_id_is_ignored_when_config_disables_trust() -> None:
    app = create_app(
        AppConfig(
            api_key="secret",
            trust_x_request_id=False,
        )
    )

    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "client-supplied"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "client-supplied"


def test_x_request_id_is_echoed_when_config_trusts_header() -> None:
    app = create_app(
        AppConfig(
            api_key="secret",
            trust_x_request_id=True,
        )
    )

    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "client-supplied"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "client-supplied"
