from sqlalchemy import create_engine

from markx import main
from tests.conftest import ApiClient


def test_health_reports_api_and_database_up(client: ApiClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "api": "up", "database": "up"}


def test_health_reports_database_down(client: ApiClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Nothing listens on port 1; connecting fails at once.
    dead = create_engine("postgresql+psycopg://nobody:nothing@127.0.0.1:1/none")
    monkeypatch.setattr(main, "get_engine", lambda: dead)
    response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "api": "up", "database": "down"}


def test_every_response_carries_a_request_id_and_security_headers(client: ApiClient) -> None:
    response = client.get("/healthz")
    assert len(response.headers["x-request-id"]) >= 16
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"


def test_a_supplied_request_id_is_kept_and_a_hostile_one_is_replaced(client: ApiClient) -> None:
    assert (
        client.get("/healthz", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"]
        == "abc-123"
    )
    hostile = client.get("/healthz", headers={"X-Request-ID": 'x"; drop table users'})
    assert hostile.headers["x-request-id"] != 'x"; drop table users'


def test_unknown_route_uses_the_single_error_format(client: ApiClient) -> None:
    response = client.get("/no-such-route")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["message_key"] == "errors.not_found"
    assert error["request_id"] == response.headers["x-request-id"]
    assert set(error) == {"code", "message_key", "message", "request_id", "details"}


def test_validation_errors_use_the_single_format_and_do_not_echo_values(client: ApiClient) -> None:
    response = client.post(
        "/auth/otp/request", json={"phone": "x", "language": "klingon", "extra": 1}
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    fields = {f["field"] for f in error["details"]["fields"]}
    assert {"phone", "language", "extra"} <= fields
    assert "klingon" not in response.text


def test_openapi_description_is_served(client: ApiClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/api/v1/healthz" in response.json()["paths"]
