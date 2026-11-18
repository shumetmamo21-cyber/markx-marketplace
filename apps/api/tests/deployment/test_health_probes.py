"""Liveness and readiness (D-091): what each says, when, and that neither
tells a public caller anything but a fixed set of words."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine, text

from markx.ops import health
from tests.conftest import ApiClient

PUBLIC_WORDS = {
    "status": {"ready", "not_ready"},
    "database": {"up", "down"},
    "schema": {"current", "behind", "ahead", "unknown"},
    "storage": {"up", "down", "not_used"},
}


def _only_public_words(body: dict[str, Any]) -> None:
    assert set(body) == set(PUBLIC_WORDS)
    for key, value in body.items():
        assert value in PUBLIC_WORDS[key]


@pytest.fixture(autouse=True)
def _fresh_probe() -> None:
    health.storage_probe.reset()


@pytest.fixture
def dead_database(monkeypatch: pytest.MonkeyPatch) -> None:
    # Nothing listens on port 1; connecting fails at once.
    dead = create_engine("postgresql+psycopg://nobody:nothing@127.0.0.1:1/none")
    monkeypatch.setattr(health, "get_engine", lambda: dead)


def test_liveness_answers(client: ApiClient) -> None:
    response = client.get("/healthz/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_liveness_does_not_depend_on_the_database(client: ApiClient, dead_database: None) -> None:
    assert client.get("/healthz/live").status_code == 200
    assert client.get("/healthz/ready").status_code == 503


def test_ready_when_the_database_and_schema_are_current(client: ApiClient) -> None:
    response = client.get("/healthz/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "up",
        "schema": "current",
        # The tests keep files in local folders; a real server never does.
        "storage": "not_used",
    }


def test_not_ready_while_the_database_is_down(client: ApiClient, dead_database: None) -> None:
    response = client.get("/healthz/ready")
    assert response.status_code == 503
    body = response.json()
    _only_public_words(body)
    assert body["database"] == "down"
    assert "127.0.0.1" not in response.text
    assert "nobody" not in response.text


def test_not_ready_while_a_migration_is_missing(
    client: ApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This release expects a revision the database does not have yet."""
    monkeypatch.setattr(health, "expected_schema_heads", lambda: frozenset({"9999"}))
    monkeypatch.setattr(
        health, "known_revisions", lambda: frozenset({"9999", *_applied_revisions()})
    )
    response = client.get("/healthz/ready")
    assert response.status_code == 503
    assert response.json()["schema"] == "behind"
    assert "9999" not in response.text


def test_not_ready_when_the_database_is_newer_than_this_release(
    client: ApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rolled-back image against a database a newer release migrated."""
    monkeypatch.setattr(health, "expected_schema_heads", lambda: frozenset({"0001"}))
    monkeypatch.setattr(health, "known_revisions", lambda: frozenset({"0001"}))
    response = client.get("/healthz/ready")
    assert response.status_code == 503
    assert response.json()["schema"] == "ahead"


def test_the_expected_heads_come_from_the_shipped_migrations() -> None:
    heads = health.expected_schema_heads()
    assert len(heads) == 1
    assert heads == frozenset(_applied_revisions())


def test_not_ready_while_a_file_store_is_down(
    client: ApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health.storage_probe, "state", lambda **_: "down")
    response = client.get("/healthz/ready")
    assert response.status_code == 503
    assert response.json()["storage"] == "down"


def test_the_storage_probe_asks_the_provider_at_most_once_per_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def probe() -> str:
        calls.append(1)
        return "up"

    monkeypatch.setattr(health, "_probe_storage", probe)
    monkeypatch.setattr(
        health,
        "get_config",
        lambda: type("C", (), {"file_storage_provider": "minio"})(),
    )
    probe_ = health._StorageProbe()
    for moment in (100.0, 101.0, 100.0 + health.STORAGE_PROBE_TTL - 0.1):
        assert probe_.state(now=moment) == "up"
    assert len(calls) == 1
    assert probe_.state(now=100.0 + health.STORAGE_PROBE_TTL + 0.1) == "up"
    assert len(calls) == 2


def test_the_existing_health_route_is_unchanged(client: ApiClient) -> None:
    """External monitors already point at /healthz (D-064)."""
    assert client.get("/healthz").json() == {"status": "ok", "api": "up", "database": "up"}


def _applied_revisions() -> list[str]:
    from markx.core.db import get_engine

    with get_engine().connect() as connection:
        return list(connection.scalars(text("select version_num from alembic_version")))
