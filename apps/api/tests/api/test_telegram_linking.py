"""Connecting a person's Telegram with the bot's one-time link (D-093).

Telegram itself is never contacted: the webhook is called the way Telegram
would call it, with the test-only secret, and the bot's answers are read
from the webhook's reply. Nothing here proves a real bot works.
"""

from __future__ import annotations

import itertools
import logging
import re
import secrets
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from markx.accounts import telegram_link
from markx.accounts.models import (
    StaffRole,
    TelegramLinkToken,
    TelegramUpdate,
    User,
)
from markx.audit.models import AuditLog
from markx.core.config import Config, get_config
from markx.notifications import push
from markx.notifications import service as notifications
from markx.notifications.models import NotificationDelivery, Outbox
from markx.notifications.push import read_dev_push_outbox
from markx.worker.runner import run_once
from tests.conftest import (
    TEST_BOT_USERNAME,
    TEST_WEBHOOK_SECRET,
    ApiClient,
    error_code,
)
from tests.deployment.test_production_config import production
from tests.factories import make_seller, staff_client

PHONE = "0911234567"
OTHER = "0922334455"
TG = 700_100_200  # a Telegram user id; an int, as Telegram sends it
WEBHOOK = "/telegram/webhook"
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
LINK = re.compile(rf"^https://t\.me/{TEST_BOT_USERNAME}\?start=([A-Za-z0-9_-]{{43}})$")
_update_ids = itertools.count(10_000)


# -- helpers ---------------------------------------------------------------------------------


def _person(phone: str = PHONE) -> ApiClient:
    client = ApiClient()
    client.sign_in(phone)
    return client


def _start(client: ApiClient) -> tuple[dict[str, Any], str]:
    response = client.post("/me/telegram/link")
    assert response.status_code == 201, response.text
    body = response.json()
    match = LINK.fullmatch(body["link"])
    assert match, body["link"]
    return body, match.group(1)


def _message(
    text_: str,
    telegram_id: int = TG,
    *,
    chat_type: str = "private",
    is_bot: bool = False,
    chat_id: int | None = None,
    kind: str = "message",
    update_id: int | None = None,
) -> dict[str, Any]:
    return {
        "update_id": update_id if update_id is not None else next(_update_ids),
        kind: {
            "message_id": 7,
            "date": 1_790_000_000,
            "from": {"id": telegram_id, "is_bot": is_bot, "first_name": "Abebe"},
            "chat": {"id": chat_id if chat_id is not None else telegram_id, "type": chat_type},
            "text": text_,
        },
    }


def _webhook(
    body: Any, *, secret: str | None = TEST_WEBHOOK_SECRET, raw: bytes | None = None
) -> Any:
    # As Telegram calls it: no MarkX client header, no cookie, no CSRF token.
    caller = ApiClient(send_client_header=False, ip="198.51.100.7")
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers[SECRET_HEADER] = secret
    if raw is not None:
        return caller.post(WEBHOOK, content=raw, headers=headers)
    return caller.post(WEBHOOK, json=body, headers=headers)


def _open_link(token: str, telegram_id: int = TG) -> dict[str, Any]:
    """The person opens the link in Telegram and Telegram calls the webhook."""
    response = _webhook(_message(f"/start {token}", telegram_id))
    assert response.status_code == 200, response.text
    return dict(response.json())


def _replied(answer: dict[str, Any], outcome: telegram_link.Outcome | str) -> bool:
    return (
        answer.get("method") == "sendMessage" and answer["text"] == telegram_link.REPLIES[outcome]
    )


def _state(client: ApiClient) -> dict[str, Any]:
    response = client.get("/me/telegram")
    assert response.status_code == 200, response.text
    return dict(response.json())


def _user(db: Session, phone: str = PHONE) -> User:
    db.rollback()
    user = db.scalar(select(User).where(User.phone == "+251" + phone[1:]))
    assert user is not None
    return user


def _race(workers: int, task: Callable[[int], Any]) -> list[Any]:
    barrier = threading.Barrier(workers)

    def run(index: int) -> Any:
        barrier.wait(timeout=60)
        return task(index)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run, range(workers)))


def _drain() -> Any:
    return run_once(datetime.now(UTC), jobs=()).outbox


# -- the switch: off by default --------------------------------------------------------------


def test_telegram_linking_is_off_by_default() -> None:
    defaults = Config(_env_file=None)  # type: ignore[call-arg]
    assert defaults.telegram_linking_enabled is False
    assert defaults.telegram_linking_ready is False
    assert defaults.telegram_bot_username is None
    assert defaults.telegram_webhook_secret is None
    # The test environment, too, unless a test switches it on.
    assert get_config().telegram_linking_ready is False


def test_while_off_the_settings_say_so_and_no_link_can_be_made(db: Session) -> None:
    client = _person()
    assert _state(client) == {
        "available": False, "telegram_messages_on": True,  # the laptop's fake provider
        "state": "not_connected", "connected_at": None, "expires_at": None, "link": None,
    }  # fmt: skip
    response = client.post("/me/telegram/link")
    assert response.status_code == 503
    assert error_code(response) == "telegram_linking_unavailable"
    assert db.scalar(select(func.count()).select_from(TelegramLinkToken)) == 0


def test_while_off_the_webhook_does_not_exist_even_with_the_secret(db: Session) -> None:
    response = _webhook(_message("/start " + "a" * 43))
    assert response.status_code == 404
    assert db.scalar(select(func.count()).select_from(TelegramUpdate)) == 0


def test_a_link_made_while_on_cannot_be_completed_once_switched_off(
    db: Session, telegram_linking: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _person()
    _, token = _start(client)
    monkeypatch.setattr(telegram_link, "get_config", get_config)  # switched off again
    assert _webhook(_message(f"/start {token}")).status_code == 404
    assert _user(db).telegram_id is None
    assert _state(client)["available"] is False


def test_while_off_linking_cannot_turn_on_telegram_notifications(db: Session) -> None:
    """Off, nobody can link, so nobody gets a Telegram message."""
    client = _person()
    assert client.post("/me/telegram/link").status_code == 503
    notifications.notify(db, _user(db).id, "seller.member_added", {})
    db.commit()
    assert _drain().done == 1
    db.rollback()
    delivery = db.scalars(select(NotificationDelivery)).one()
    assert (delivery.status, delivery.reason) == ("skipped", "no_telegram_linked")
    assert read_dev_push_outbox() == []


# -- who may ask -----------------------------------------------------------------------------


@pytest.mark.usefixtures("telegram_linking")
def test_signing_in_is_needed_for_every_telegram_route() -> None:
    anonymous = ApiClient()
    for method in ("GET", "DELETE"):
        response = anonymous.request(method, "/me/telegram")
        assert response.status_code == 401, method
    response = anonymous.post("/me/telegram/link")
    assert response.status_code == 401
    assert error_code(response) == "not_authenticated"


@pytest.mark.usefixtures("telegram_linking")
def test_a_staff_session_cannot_start_a_link(db: Session) -> None:
    staff = staff_client(db, "0911000200", StaffRole.OPERATIONS)
    response = staff.post("/me/telegram/link")
    assert response.status_code == 403
    assert error_code(response) == "customer_session_required"


@pytest.mark.usefixtures("telegram_linking")
def test_the_link_needs_the_anti_forgery_token() -> None:
    client = _person()
    client.send_csrf = False
    response = client.post("/me/telegram/link")
    assert response.status_code == 403
    assert error_code(response) == "csrf_token_invalid"


@pytest.mark.usefixtures("telegram_linking")
def test_a_store_team_member_can_neither_see_nor_change_a_colleagues_telegram(
    db: Session,
) -> None:
    """The connection belongs to the person, not the store: every route acts
    on the caller's own account, and nothing a store shows names it."""
    staff = staff_client(db, "0911000200", StaffRole.OPERATIONS)
    owner, seller_id = make_seller(staff, "0911000001")
    assert (
        owner.post(f"/seller/{seller_id}/members", json={"phone": "0911000050"}).status_code == 201
    )
    manager = _person("0911000050")
    _, token = _start(manager)
    _open_link(token)
    assert _state(manager)["state"] == "connected"

    # The owner sees only their own connection and disconnects only their own.
    assert _state(owner)["state"] == "not_connected"
    assert owner.delete("/me/telegram").status_code == 200
    assert _state(manager)["state"] == "connected"
    assert _user(db, "0911000050").telegram_id == TG
    # The store's member list says nothing about anyone's Telegram.
    members = owner.get(f"/seller/{seller_id}/members")
    assert members.status_code == 200
    assert "telegram" not in members.text.lower()
    assert str(TG) not in members.text


# -- the whole flow --------------------------------------------------------------------------


@pytest.mark.usefixtures("telegram_linking")
def test_a_person_connects_telegram_with_a_one_time_link(db: Session) -> None:
    client = _person()
    body, token = _start(client)
    assert body["available"] is True
    assert body["state"] == "pending"
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert timedelta(minutes=9) < expires_at - datetime.now(UTC) <= timedelta(minutes=10)
    # Waiting: the link is never shown again, only that one is waiting.
    assert _state(client) == {
        "available": True, "telegram_messages_on": True, "state": "pending",
        "connected_at": None, "expires_at": body["expires_at"], "link": None,
    }  # fmt: skip

    answer = _open_link(token)
    assert _replied(answer, telegram_link.Outcome.LINKED)
    assert answer["chat_id"] == TG

    state = _state(client)
    assert state["state"] == "connected"
    assert state["connected_at"] is not None
    assert str(TG) not in str(state)
    user = _user(db)
    assert user.telegram_id == TG
    assert user.telegram_linked_at is not None
    row = db.scalars(select(TelegramLinkToken)).one()
    assert (row.status, row.failure_reason) == ("consumed", None)
    assert row.finished_at is not None


@pytest.mark.usefixtures("telegram_linking")
def test_the_bot_command_may_name_the_bot() -> None:
    client = _person()
    _, token = _start(client)
    answer = _webhook(_message(f"/start@{TEST_BOT_USERNAME} {token}")).json()
    assert _replied(answer, telegram_link.Outcome.LINKED)
    assert _state(client)["state"] == "connected"


@pytest.mark.usefixtures("telegram_linking")
def test_an_account_already_connected_cannot_start_another_link() -> None:
    client = _person()
    _, token = _start(client)
    _open_link(token)
    response = client.post("/me/telegram/link")
    assert response.status_code == 409
    assert error_code(response) == "telegram_already_connected"


# -- the token --------------------------------------------------------------------------------


@pytest.mark.usefixtures("telegram_linking")
def test_tokens_are_random_and_only_their_keyed_hash_is_stored(
    db: Session, migrator_engine: Any
) -> None:
    tokens = set()
    for phone in ("0911000101", "0911000102", "0911000103"):
        _, token = _start(_person(phone))
        tokens.add(token)
    assert len(tokens) == 3
    db.rollback()
    stored = {row.token_hash for row in db.scalars(select(TelegramLinkToken))}
    assert stored == {telegram_link.token_hash(t) for t in tokens}
    for token in tokens:
        assert token.encode() not in stored
    # Nowhere in the table's text, nor in the audit log.
    with migrator_engine.connect() as connection:
        dump = " ".join(
            str(r) for r in connection.execute(text("select t::text from telegram_link_tokens t"))
        )
        audit = " ".join(
            str(r) for r in connection.execute(text("select a::text from audit_log a"))
        )
    for token in tokens:
        assert token not in dump
        assert token not in audit


@pytest.mark.usefixtures("telegram_linking")
def test_a_new_link_replaces_the_one_not_used_yet(db: Session) -> None:
    client = _person()
    _, old = _start(client)
    _, new = _start(client)
    assert old != new
    db.rollback()
    statuses = sorted(r.status for r in db.scalars(select(TelegramLinkToken)))
    assert statuses == ["pending", "revoked"]
    assert _replied(_open_link(old), telegram_link.Outcome.INVALID)
    assert _user(db).telegram_id is None
    assert _replied(_open_link(new), telegram_link.Outcome.LINKED)


@pytest.mark.usefixtures("telegram_linking")
def test_an_expired_link_is_refused_and_the_settings_say_expired(db: Session) -> None:
    client = _person()
    _, token = _start(client)
    db.execute(
        update(TelegramLinkToken).values(
            created_at=func.now() - timedelta(minutes=20),
            expires_at=func.now() - timedelta(minutes=10),
        )
    )
    db.commit()
    assert _replied(_open_link(token), telegram_link.Outcome.EXPIRED)
    assert _user(db).telegram_id is None
    assert _state(client)["state"] == "expired"
    # A new link works.
    _, fresh = _start(client)
    assert _replied(_open_link(fresh), telegram_link.Outcome.LINKED)


@pytest.mark.usefixtures("telegram_linking")
def test_a_link_works_once_and_a_replay_changes_nothing(db: Session) -> None:
    client = _person()
    _, token = _start(client)
    assert _replied(_open_link(token), telegram_link.Outcome.LINKED)
    # The same link again, as a new message: refused, nothing changes.
    assert _replied(_open_link(token), telegram_link.Outcome.INVALID)
    # Even after disconnecting, the old link cannot connect anyone again.
    assert client.delete("/me/telegram").status_code == 200
    assert _replied(_open_link(token, TG + 1), telegram_link.Outcome.INVALID)
    assert _user(db).telegram_id is None
    db.rollback()
    assert (
        db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "telegram.linked")
        )
        == 1
    )


@pytest.mark.usefixtures("telegram_linking")
@pytest.mark.parametrize(
    "payload",
    [
        "A" * 43,  # well formed, never issued
        "short",
        "A" * 42 + "!",
        "A" * 44,
        "../../me",
    ],
)
def test_an_invalid_link_is_refused(payload: str, db: Session) -> None:
    client = _person()
    _start(client)
    answer = _open_link(payload)
    assert _replied(answer, telegram_link.Outcome.INVALID)
    assert _user(db).telegram_id is None
    assert _state(client)["state"] == "pending"


@pytest.mark.usefixtures("telegram_linking")
def test_start_without_a_link_only_explains_how_to_connect(db: Session) -> None:
    answer = _webhook(_message("/start")).json()
    assert _replied(answer, "help")
    assert (
        db.scalar(select(func.count()).select_from(User).where(User.telegram_id.is_not(None))) == 0
    )


# -- re-checked when Telegram calls back ------------------------------------------------------


@pytest.mark.usefixtures("telegram_linking")
def test_a_link_from_a_session_that_signed_out_is_refused(db: Session) -> None:
    client = _person()
    _, token = _start(client)
    assert client.post("/auth/sign-out").status_code == 200
    assert _replied(_open_link(token), telegram_link.Outcome.REFUSED)
    assert _user(db).telegram_id is None
    again = _person()
    assert _state(again)["state"] == "failed"
    db.rollback()
    assert db.scalars(select(TelegramLinkToken.failure_reason)).one() == "session_ended"


@pytest.mark.usefixtures("telegram_linking")
def test_a_link_for_an_account_blocked_meanwhile_is_refused(db: Session) -> None:
    client = _person()
    _, token = _start(client)
    db.execute(update(User).values(status="blocked"))
    db.commit()
    assert _replied(_open_link(token), telegram_link.Outcome.REFUSED)
    assert _user(db).telegram_id is None
    db.rollback()
    assert db.scalars(select(TelegramLinkToken.failure_reason)).one() == "account_inactive"


# -- one Telegram account, one MarkX account -------------------------------------------------


@pytest.mark.usefixtures("telegram_linking")
def test_a_telegram_account_cannot_be_linked_to_a_second_markx_account(db: Session) -> None:
    first, second = _person(PHONE), _person(OTHER)
    _, token = _start(first)
    _open_link(token)
    _, token = _start(second)
    answer = _open_link(token)  # the same Telegram account
    assert _replied(answer, telegram_link.Outcome.REFUSED)
    # The answer is the same whatever the reason; it does not say "in use".
    assert telegram_link.REPLIES[telegram_link.Outcome.REFUSED] == answer["text"]
    assert _user(db, OTHER).telegram_id is None
    assert _user(db, PHONE).telegram_id == TG
    state = _state(second)
    assert state["state"] == "failed"
    assert set(state) == {
        "available", "telegram_messages_on", "state", "connected_at", "expires_at", "link",
    }  # fmt: skip


@pytest.mark.usefixtures("telegram_linking")
def test_two_accounts_linking_one_telegram_account_at_once_link_only_one(db: Session) -> None:
    phones = [f"09110002{n:02d}" for n in range(6)]
    tokens = [_start(_person(phone))[1] for phone in phones]
    answers = _race(len(tokens), lambda i: _webhook(_message(f"/start {tokens[i]}")).json())
    linked = [a for a in answers if _replied(a, telegram_link.Outcome.LINKED)]
    refused = [a for a in answers if _replied(a, telegram_link.Outcome.REFUSED)]
    assert (len(linked), len(refused)) == (1, len(tokens) - 1)
    db.rollback()
    assert db.scalar(select(func.count()).select_from(User).where(User.telegram_id == TG)) == 1
    assert sorted(db.scalars(select(TelegramLinkToken.status))) == (
        ["consumed"] + ["failed"] * (len(tokens) - 1)
    )


@pytest.mark.usefixtures("telegram_linking")
def test_one_link_opened_twice_at_once_is_used_once(db: Session) -> None:
    client = _person()
    _, token = _start(client)
    answers = _race(4, lambda i: _webhook(_message(f"/start {token}", TG + i)).json())
    assert sum(_replied(a, telegram_link.Outcome.LINKED) for a in answers) == 1
    assert sum(_replied(a, telegram_link.Outcome.INVALID) for a in answers) == 3
    db.rollback()
    assert (
        db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "telegram.linked")
        )
        == 1
    )


@pytest.mark.usefixtures("telegram_linking")
def test_asking_for_links_at_once_leaves_exactly_one_waiting(db: Session) -> None:
    client = _person()
    copies = []
    for _ in range(4):
        copy = ApiClient()
        copy.http.cookies = client.http.cookies
        copies.append(copy)
    statuses = _race(4, lambda i: copies[i].post("/me/telegram/link").status_code)
    assert set(statuses) == {201}
    db.rollback()
    assert (
        db.scalar(
            select(func.count())
            .select_from(TelegramLinkToken)
            .where(TelegramLinkToken.status == "pending")
        )
        == 1
    )


# -- disconnecting ---------------------------------------------------------------------------


@pytest.mark.usefixtures("telegram_linking")
def test_disconnecting_unlinks_telegram_and_never_touches_sign_in(db: Session) -> None:
    client = _person()
    _, token = _start(client)
    _open_link(token)
    response = client.delete("/me/telegram")
    assert response.status_code == 200
    assert response.json()["state"] == "disconnected"
    user = _user(db)
    assert (user.telegram_id, user.telegram_linked_at) == (None, None)
    assert user.telegram_unlinked_at is not None
    # Still signed in, and signing in by phone code still works.
    assert client.get("/me").status_code == 200
    assert _state(_person())["state"] == "disconnected"
    # The same Telegram account may be connected again, by a new link.
    _, token = _start(client)
    assert _replied(_open_link(token), telegram_link.Outcome.LINKED)


@pytest.mark.usefixtures("telegram_linking")
def test_disconnecting_cancels_a_link_not_used_yet(db: Session) -> None:
    client = _person()
    _, token = _start(client)
    assert client.delete("/me/telegram").json()["state"] == "not_connected"
    assert _replied(_open_link(token), telegram_link.Outcome.INVALID)
    assert _user(db).telegram_id is None


def test_disconnecting_works_even_when_linking_is_switched_off(
    db: Session, telegram_linking: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _person()
    _, token = _start(client)
    _open_link(token)
    monkeypatch.setattr(telegram_link, "get_config", get_config)
    state = _state(client)
    assert (state["available"], state["state"]) == (False, "connected")
    assert client.delete("/me/telegram").json()["state"] == "disconnected"
    assert _user(db).telegram_id is None


@pytest.mark.usefixtures("telegram_linking")
def test_after_disconnecting_no_new_notification_goes_to_telegram(db: Session) -> None:
    client = _person()
    _, token = _start(client)
    _open_link(token)
    user_id = _user(db).id
    notifications.notify(db, user_id, "seller.member_added", {})
    db.commit()
    _drain()
    assert len(read_dev_push_outbox()) == 1  # linked: pushed (fake provider)

    assert client.delete("/me/telegram").status_code == 200
    notifications.notify(db, user_id, "seller.member_removed", {})
    db.commit()
    _drain()
    assert len(read_dev_push_outbox()) == 1  # nothing more
    db.rollback()
    latest = db.scalar(
        select(NotificationDelivery).where(NotificationDelivery.template == "seller.member_removed")
    )
    assert latest is not None
    assert (latest.status, latest.reason) == ("skipped", "no_telegram_linked")


# -- notifications ---------------------------------------------------------------------------


@pytest.mark.usefixtures("telegram_linking")
def test_connecting_does_not_resend_what_was_already_recorded(db: Session) -> None:
    client = _person()
    user_id = _user(db).id
    notifications.notify(db, user_id, "seller.member_added", {})
    db.commit()
    _drain()
    db.rollback()
    before = [
        (d.id, d.status, d.reason, d.attempts) for d in db.scalars(select(NotificationDelivery))
    ]
    assert [b[1:3] for b in before] == [("skipped", "no_telegram_linked")]
    outbox_rows = db.scalar(select(func.count()).select_from(Outbox))

    _, token = _start(client)
    _open_link(token)
    assert _drain().done == 0
    db.rollback()
    after = [
        (d.id, d.status, d.reason, d.attempts) for d in db.scalars(select(NotificationDelivery))
    ]
    assert after == before
    assert db.scalar(select(func.count()).select_from(Outbox)) == outbox_rows
    assert read_dev_push_outbox() == []


@pytest.mark.usefixtures("telegram_linking")
def test_a_linked_person_gets_nothing_by_telegram_until_a_provider_is_configured(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Linking alone sends nothing: without a push provider every Telegram
    delivery is `unavailable` (D-092), and the in-app message is there."""
    unconfigured = get_config().model_copy(update={"telegram_push_provider": "none"})
    monkeypatch.setattr(push, "get_config", lambda: unconfigured)
    client = _person()
    _, token = _start(client)
    _open_link(token)
    notifications.notify(db, _user(db).id, "seller.member_added", {})
    db.commit()
    _drain()
    db.rollback()
    delivery = db.scalars(select(NotificationDelivery)).one()
    assert (delivery.status, delivery.reason) == ("unavailable", "telegram_provider_not_configured")
    assert read_dev_push_outbox() == []
    # And the person's settings say so, rather than implying messages arrive.
    state = _state(client)
    assert (state["state"], state["telegram_messages_on"]) == ("connected", False)


# -- the webhook: who may call it --------------------------------------------------------------


@pytest.mark.usefixtures("telegram_linking")
def test_the_webhook_refuses_a_call_without_the_secret(db: Session) -> None:
    client = _person()
    _, token = _start(client)
    response = _webhook(_message(f"/start {token}"), secret=None)
    assert response.status_code == 401
    assert error_code(response) == "telegram_webhook_unauthorized"
    assert _user(db).telegram_id is None
    assert db.scalar(select(func.count()).select_from(TelegramUpdate)) == 0


@pytest.mark.usefixtures("telegram_linking")
@pytest.mark.parametrize(
    "secret",
    [
        "x",
        TEST_WEBHOOK_SECRET[:-1],
        TEST_WEBHOOK_SECRET + "x",
        TEST_WEBHOOK_SECRET.upper(),
        "",
    ],
)
def test_the_webhook_refuses_a_wrong_secret(secret: str, db: Session) -> None:
    client = _person()
    _, token = _start(client)
    response = _webhook(_message(f"/start {token}"), secret=secret)
    assert response.status_code == 401
    assert _user(db).telegram_id is None
    assert _state(client)["state"] == "pending"


@pytest.mark.usefixtures("telegram_linking")
def test_the_secret_is_checked_before_the_body_is_read() -> None:
    response = _webhook(None, secret=None, raw=b"{not json")
    assert response.status_code == 401
    response = _webhook(None, secret="wrong", raw=b"x" * (telegram_link.MAX_UPDATE_BYTES + 10))
    assert response.status_code == 401


@pytest.mark.usefixtures("telegram_linking")
def test_repeated_calls_with_a_wrong_secret_are_throttled() -> None:
    statuses = [
        _webhook({"update_id": 1}, secret="wrong").status_code
        for _ in range(telegram_link.REFUSED_WEBHOOK_CALLS_PER_HOUR + 1)
    ]
    assert statuses[:-1] == [401] * telegram_link.REFUSED_WEBHOOK_CALLS_PER_HOUR
    assert statuses[-1] == 429


# -- the webhook: what it accepts --------------------------------------------------------------


@pytest.mark.usefixtures("telegram_linking")
@pytest.mark.parametrize(
    "raw",
    [
        b"{not json",
        b"[]",
        b'"update"',
        b"{}",
        b'{"update_id": "12"}',
        b'{"update_id": true}',
        b'{"update_id": -5}',
        b'{"update_id": 0}',
        b'{"update_id": 1.5}',
        b'{"update_id": 99999999999999999999999}',
        b"\xff\xfe",
    ],
)
def test_a_malformed_update_is_refused_safely(raw: bytes, db: Session) -> None:
    response = _webhook(None, raw=raw)
    assert response.status_code == 400
    assert error_code(response) == "telegram_update_invalid"
    assert db.scalar(select(func.count()).select_from(TelegramUpdate)) == 0


@pytest.mark.usefixtures("telegram_linking")
def test_an_oversized_update_is_refused() -> None:
    raw = b'{"update_id": 5, "pad": "' + b"x" * telegram_link.MAX_UPDATE_BYTES + b'"}'
    response = _webhook(None, raw=raw)
    assert response.status_code == 413


@pytest.mark.usefixtures("telegram_linking")
def test_a_repeated_update_is_handled_once(db: Session) -> None:
    client = _person()
    _, token = _start(client)
    update_ = _message(f"/start {token}")
    first = _webhook(update_).json()
    again = _webhook(update_).json()
    assert _replied(first, telegram_link.Outcome.LINKED)
    assert again == {"ok": True}
    db.rollback()
    assert db.scalar(select(func.count()).select_from(TelegramUpdate)) == 1


@pytest.mark.usefixtures("telegram_linking")
def test_the_same_update_delivered_twice_at_once_is_handled_once(db: Session) -> None:
    client = _person()
    _, token = _start(client)
    update_ = _message(f"/start {token}")
    answers = _race(3, lambda _: _webhook(update_).json())
    assert sum(_replied(a, telegram_link.Outcome.LINKED) for a in answers) == 1
    assert answers.count({"ok": True}) == 2
    assert _user(db).telegram_id == TG


@pytest.mark.usefixtures("telegram_linking")
@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda t: _message(f"/start {t}", kind="edited_message"), id="edited"),
        pytest.param(lambda t: _message(f"/start {t}", kind="channel_post"), id="channel_post"),
        pytest.param(
            lambda t: _message(f"/start {t}", chat_type="group", chat_id=-100), id="group"
        ),
        pytest.param(
            lambda t: _message(f"/start {t}", chat_type="supergroup", chat_id=-1001),
            id="supergroup",
        ),
        pytest.param(lambda t: _message(f"/start {t}", is_bot=True), id="from_a_bot"),
        pytest.param(lambda t: _message(f"/start {t}", chat_id=TG + 1), id="someone_elses_chat"),
        pytest.param(lambda t: _message(f"hello /start {t}"), id="not_a_command"),
        pytest.param(lambda t: _message(f"/link {t}"), id="another_command"),
        pytest.param(lambda t: _message(f"/start {t} extra"), id="extra_words"),
        pytest.param(
            lambda t: {"update_id": next(_update_ids), "callback_query": {"id": "1", "data": t}},
            id="callback_query",
        ),
        pytest.param(
            lambda t: {
                "update_id": next(_update_ids),
                "message": {"chat": {"id": TG, "type": "private"}, "text": f"/start {t}"},
            },
            id="no_sender",
        ),
        pytest.param(
            lambda t: {
                "update_id": next(_update_ids),
                "message": {
                    "from": {"id": str(TG), "is_bot": False},
                    "chat": {"id": str(TG), "type": "private"},
                    "text": f"/start {t}",
                },
            },
            id="ids_as_text",
        ),
        pytest.param(
            lambda t: {
                "update_id": next(_update_ids),
                "message": {
                    "from": {"id": TG, "is_bot": False},
                    "chat": {"id": TG, "type": "private"},
                    "photo": [{"file_id": t}],
                    "caption": f"/start {t}",
                },
            },
            id="photo_caption",
        ),
    ],
)
def test_nothing_but_start_in_a_private_chat_from_a_person_changes_anything(
    build: Callable[[str], dict[str, Any]], db: Session
) -> None:
    client = _person()
    _, token = _start(client)
    response = _webhook(build(token))
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert _user(db).telegram_id is None
    assert _state(client)["state"] == "pending"
    # The link still works afterwards: an ignored update did not use it.
    assert _replied(_open_link(token), telegram_link.Outcome.LINKED)


@pytest.mark.usefixtures("telegram_linking")
def test_one_telegram_account_trying_many_links_is_throttled(db: Session) -> None:
    for _ in range(telegram_link.ATTEMPTS_PER_TELEGRAM_ACCOUNT_PER_HOUR):
        assert _replied(_open_link(secrets.token_urlsafe(32)), telegram_link.Outcome.INVALID)
    client = _person()
    _, token = _start(client)
    assert _open_link(token) == {"ok": True}  # silently ignored
    assert _user(db).telegram_id is None
    # Another Telegram account is not affected.
    assert _replied(_open_link(token, TG + 9), telegram_link.Outcome.LINKED)


@pytest.mark.usefixtures("telegram_linking")
def test_asking_for_too_many_links_is_throttled() -> None:
    client = _person()
    for _ in range(telegram_link.LINKS_PER_ACCOUNT_PER_HOUR):
        assert client.post("/me/telegram/link").status_code == 201
    response = client.post("/me/telegram/link")
    assert response.status_code == 429


# -- privacy ----------------------------------------------------------------------------------


@pytest.mark.usefixtures("telegram_linking")
def test_no_token_secret_or_telegram_id_reaches_the_logs_or_the_audit_trail(
    db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    first, second = _person(PHONE), _person(OTHER)
    _, token = _start(first)
    _open_link(token)
    _, refused = _start(second)
    _open_link(refused)  # in use elsewhere
    _open_link(refused)  # replayed
    _webhook({"update_id": 3}, secret="wrong-secret-value")
    first.delete("/me/telegram")
    logged = caplog.text + " ".join(str(r.__dict__) for r in caplog.records)
    for secret_value in (token, refused, TEST_WEBHOOK_SECRET, str(TG), "wrong-secret-value"):
        assert secret_value not in logged
    db.rollback()
    trail = [
        (a.action, a.after)
        for a in db.scalars(select(AuditLog).where(AuditLog.action.like("telegram.%")))
    ]
    assert {action for action, _ in trail} == {
        "telegram.link_requested", "telegram.linked", "telegram.link_refused", "telegram.unlinked",
    }  # fmt: skip
    for secret_value in (token, refused, str(TG)):
        assert secret_value not in str(trail)


@pytest.mark.usefixtures("telegram_linking")
def test_no_answer_to_the_browser_names_the_telegram_account() -> None:
    client = _person()
    _, token = _start(client)
    _open_link(token)
    for response in (client.get("/me/telegram"), client.get("/me"), client.delete("/me/telegram")):
        assert str(TG) not in response.text
        assert "Abebe" not in response.text


# -- configuration ----------------------------------------------------------------------------


def _refused(**settings: Any) -> str:
    with pytest.raises(ValidationError) as caught:
        Config(_env_file=None, **settings)  # type: ignore[call-arg]
    return str(caught.value)


def test_switching_linking_on_needs_the_bot_username_and_the_webhook_secret() -> None:
    problem = _refused(telegram_linking_enabled=True)
    assert "MARKX_TELEGRAM_BOT_USERNAME must be set" in problem
    assert "MARKX_TELEGRAM_WEBHOOK_SECRET must be set" in problem
    problem = _refused(telegram_linking_enabled=True, telegram_bot_username=TEST_BOT_USERNAME)
    assert "MARKX_TELEGRAM_WEBHOOK_SECRET must be set" in problem
    ready = Config(
        _env_file=None,  # type: ignore[call-arg]
        telegram_linking_enabled=True,
        telegram_bot_username="@" + TEST_BOT_USERNAME,
        telegram_webhook_secret=TEST_WEBHOOK_SECRET,
    )
    assert ready.telegram_linking_ready
    assert ready.telegram_bot_username == TEST_BOT_USERNAME
    assert TEST_WEBHOOK_SECRET not in repr(ready)


@pytest.mark.parametrize("username", ["markx", "bot", "markx bot", "markx_store", "a" * 40 + "bot"])
def test_a_bot_username_must_look_like_one(username: str) -> None:
    assert "MARKX_TELEGRAM_BOT_USERNAME" in _refused(telegram_bot_username=username)


@pytest.mark.parametrize(
    "secret", ["short", "x" * 31, "has spaces in it " * 3, "é" * 40, "x" * 257]
)
def test_a_webhook_secret_must_be_long_and_plain(secret: str) -> None:
    problem = _refused(telegram_webhook_secret=secret)
    assert "MARKX_TELEGRAM_WEBHOOK_SECRET" in problem
    assert secret not in problem


def test_a_real_server_refuses_a_placeholder_webhook_secret() -> None:
    real_secret = secrets.token_urlsafe(48)
    for placeholder in (TEST_WEBHOOK_SECRET, "dev-only-" + "x" * 40):
        with pytest.raises(ValidationError) as caught:
            Config(
                **production(
                    telegram_linking_enabled=True,
                    telegram_bot_username="markx_real_bot",
                    telegram_webhook_secret=placeholder,
                )
            )
        assert "must be a real random secret" in str(caught.value)
        assert placeholder not in str(caught.value)
    real = Config(
        **production(
            telegram_linking_enabled=True,
            telegram_bot_username="markx_real_bot",
            telegram_webhook_secret=real_secret,
        )
    )
    assert real.telegram_linking_ready
    # Linked accounts but nothing to carry messages: said at start-up.
    assert any("Telegram linking is on" in w for w in real.startup_warnings())


def test_a_real_server_has_linking_off_and_no_push_provider_unless_configured() -> None:
    real = Config(**production())
    assert real.telegram_linking_ready is False
    assert real.push_provider == "none"
    assert not any("Telegram linking is on" in w for w in real.startup_warnings())


def test_a_real_server_never_takes_the_fake_push_provider_even_with_linking_on() -> None:
    with pytest.raises(ValidationError) as caught:
        Config(
            **production(
                telegram_linking_enabled=True,
                telegram_bot_username="markx_real_bot",
                telegram_webhook_secret=secrets.token_urlsafe(48),
                telegram_push_provider="fake",
            )
        )
    assert "MARKX_TELEGRAM_PUSH_PROVIDER must be none or bot_api" in str(caught.value)


def test_secret_str_keeps_the_webhook_secret_out_of_the_configuration_dump() -> None:
    config = Config(
        _env_file=None,  # type: ignore[call-arg]
        telegram_webhook_secret=SecretStr(TEST_WEBHOOK_SECRET),
    )
    assert TEST_WEBHOOK_SECRET not in str(config.model_dump())
