"""Test harness.

Every run drops the test database, bootstraps the three roles again and applies
every migration from empty. Nothing is mocked below the HTTP layer: tests talk
to a real PostgreSQL through the same least-privileged role the API uses.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# Configuration is read once, at import. Set it before any markx module loads.
_PG_HOST = os.environ.get("MARKX_TEST_PGHOST", "127.0.0.1")
_PG_PORT = os.environ.get("MARKX_TEST_PGPORT", "5432")
_PG_SUPERUSER = os.environ.get("MARKX_TEST_PGUSER", "postgres")
_PG_SUPERPASS = os.environ.get("MARKX_TEST_PGPASSWORD", "postgres_dev_only")
_DB_NAME = "markx_test"
_STORAGE = Path(tempfile.mkdtemp(prefix="markx-test-storage-"))


def _url(role: str) -> str:
    return f"postgresql+psycopg://{role}:{role}_dev-only@{_PG_HOST}:{_PG_PORT}/{_DB_NAME}"


os.environ["MARKX_ENV"] = "test"
os.environ["MARKX_DATABASE_URL"] = _url("markx_app")
os.environ["MARKX_MIGRATION_DATABASE_URL"] = _url("markx_migrator")
os.environ["MARKX_STORAGE_DIR"] = str(_STORAGE)
os.environ["MARKX_PUBLIC_ORIGIN"] = "http://testserver"
os.environ["MARKX_TELEGRAM_BOT_TOKEN"] = "123456:TEST-ONLY-bot-token-not-a-real-secret"
os.environ["MARKX_LOG_LEVEL"] = "WARNING"
# A documentation-range address (RFC 5737) plays the reverse proxy (SEC-3).
os.environ["MARKX_TRUSTED_PROXIES"] = "127.0.0.1,::1,192.0.2.1"

from alembic import command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from markx import registry  # noqa: E402, F401
from markx.core.db import Base, get_engine, get_session_factory  # noqa: E402
from markx.main import app  # noqa: E402
from markx.notifications.push import dev_push_outbox_path  # noqa: E402
from markx.notifications.sms import dev_sms_inbox_path, read_dev_sms_inbox  # noqa: E402
from markx.ops.alerts import dev_alerts_path  # noqa: E402

API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = API_DIR.parents[1]


def _psql_env() -> dict[str, str]:
    return {
        **os.environ,
        "PGHOST": _PG_HOST,
        "PGPORT": _PG_PORT,
        "PGUSER": _PG_SUPERUSER,
        "PGPASSWORD": _PG_SUPERPASS,
    }


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    """Rebuild the test database from nothing: bootstrap, then every migration."""
    env = _psql_env()
    subprocess.run(
        ["psql", "-v", "ON_ERROR_STOP=1", "-q", "-d", "postgres", "-c",
         f"drop database if exists {_DB_NAME} with (force)"],
        check=True, env=env, capture_output=True,
    )  # fmt: skip
    subprocess.run(
        [str(REPO_ROOT / "infra" / "postgres" / "bootstrap.sh"), _DB_NAME],
        check=True, env=env, capture_output=True,
    )  # fmt: skip
    alembic_config = AlembicConfig(str(API_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(API_DIR / "migrations"))
    command.upgrade(alembic_config, "head")
    yield
    get_engine().dispose()


@pytest.fixture(scope="session")
def migrator_engine(_database: None) -> Iterator[Engine]:
    engine = create_engine(_url("markx_migrator"))
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def readonly_engine(_database: None) -> Iterator[Engine]:
    engine = create_engine(_url("markx_readonly"))
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_slate(migrator_engine: Engine) -> None:
    """Empty every table before each test, so tests cannot depend on each other."""
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with migrator_engine.begin() as connection:
        connection.execute(text(f"truncate {tables} restart identity cascade"))
    for fake_outbox in (dev_sms_inbox_path(), dev_push_outbox_path(), dev_alerts_path()):
        if fake_outbox.exists():
            fake_outbox.unlink()


@pytest.fixture
def db() -> Iterator[Session]:
    """A session on the application role, for arranging data and asserting on it."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# Test-only values for Telegram linking (D-093). Placeholders, not a real bot.
TEST_BOT_USERNAME = "markx_test_only_bot"
TEST_WEBHOOK_SECRET = "test-only-webhook-secret-0123456789abcdefghij"


@pytest.fixture
def telegram_linking(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Telegram linking switched on, as a configured server would have it.
    The test environment, like every environment, has it off by default."""
    from pydantic import SecretStr

    from markx.accounts import telegram_link
    from markx.core.config import get_config

    config = get_config().model_copy(
        update={
            "telegram_linking_enabled": True,
            "telegram_bot_username": TEST_BOT_USERNAME,
            "telegram_webhook_secret": SecretStr(TEST_WEBHOOK_SECRET),
        }
    )
    monkeypatch.setattr(telegram_link, "get_config", lambda: config)
    return config


@pytest.fixture
def sms_off(monkeypatch: pytest.MonkeyPatch) -> Any:
    """SMS switched off (`MARKX_SMS_PROVIDER=off`), as a server where
    everyone signs in with Telegram has it (D-101, decision SI-1). The test
    environment, like a laptop, has the fake SMS sender on by default."""
    from markx.accounts import router, service
    from markx.core.config import get_config
    from markx.notifications import delivery, sms

    config = get_config().model_copy(update={"sms_provider": "off"})
    for module in (service, router, delivery, sms):
        monkeypatch.setattr(module, "get_config", lambda: config)
    return config


class ApiClient:
    """Behaves like the web app: sends the MarkX client header on every request
    and echoes the CSRF cookie back as a header on requests that change data."""

    def __init__(
        self,
        *,
        send_client_header: bool = True,
        send_csrf: bool = True,
        ip: str = "203.0.113.10",
    ) -> None:
        # A documentation-range address (RFC 5737), so address-based rules run.
        self.http = TestClient(app, raise_server_exceptions=False, client=(ip, 50000))
        self.send_client_header = send_client_header
        self.send_csrf = send_csrf

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", None) or {})
        if self.send_client_header:
            headers.setdefault("X-MarkX-Client", "web")
        csrf = self.http.cookies.get("markx_csrf")
        if self.send_csrf and csrf and method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            headers.setdefault("X-CSRF-Token", csrf)
        if not path.startswith("/"):
            path = "/" + path
        return self.http.request(method, f"/api/v1{path}", headers=headers, **kwargs)

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self.request("PATCH", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    # -- helpers -----------------------------------------------------------

    def sign_in(self, phone: str, language: str = "en") -> dict[str, Any]:
        """The real sign-in: ask for a code, read it from the fake SMS inbox, verify it.
        A test that signs one number in twice is a person coming back later,
        so the resend cooldown (D-089) is let pass first; its own tests in
        test_sms_cooldown.py call the route directly."""
        let_resend_cooldown_pass(phone)
        response = self.post("/auth/otp/request", json={"phone": phone, "language": language})
        assert response.status_code == 200, response.text
        code = latest_code(phone)
        response = self.post("/auth/otp/verify", json={"phone": phone, "code": code})
        assert response.status_code == 200, response.text
        return dict(response.json())


def let_resend_cooldown_pass(phone: str) -> None:
    """Move a number's earlier SMS delivery records back by a day, as if the
    person came back later. Nothing else about them changes."""
    from markx.core.phone import normalize_phone
    from markx.notifications.sms import phone_reference

    with get_session_factory()() as session:
        session.execute(
            text(
                "update sms_messages set created_at = created_at - interval '1 day' "
                "where phone_ref = :ref"
            ),
            {"ref": phone_reference(normalize_phone(phone))},
        )
        session.commit()


def latest_code(phone: str) -> str:
    from markx.core.phone import normalize_phone

    messages = read_dev_sms_inbox(normalize_phone(phone))
    assert messages, f"no SMS was sent to {phone}"
    digits = [part.strip(".።፦:") for part in messages[-1]["text"].replace("፦", " ").split()]
    codes = [d for d in digits if len(d) == 6 and d.isdigit()]
    assert codes, messages[-1]["text"]
    return codes[0]


@pytest.fixture
def client() -> ApiClient:
    return ApiClient()


@pytest.fixture
def make_client() -> Any:
    """A factory, for tests that need several independent visitors."""
    return ApiClient


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])
