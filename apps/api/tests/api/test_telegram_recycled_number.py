"""A recycled phone number never takes over an account (D-101, rule P-101-6).

Ethiopian phone companies give old numbers to new people. Once an account
has had a Telegram account, MarkX remembers which one (`bound_telegram_id`)
for ever, even after "Disconnect Telegram", which only stops messages. Only
that Telegram account may sign in to it again; any other Telegram account
bringing the same number is refused and told to contact support (F-24). An
account that never had a Telegram account may still be claimed by the first
Telegram sign-in with its number.

Telegram is played by `tests/telegram_play.py`; nothing reaches Telegram.
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from markx.accounts import telegram_link, telegram_sign_in
from markx.accounts.models import TelegramLinkToken, User
from markx.audit.models import AuditLog
from tests import telegram_play as tg
from tests.conftest import TEST_WEBHOOK_SECRET, ApiClient, error_code
from tests.factories import address_body, make_seller, make_zone, staff_client, telegram_init_data

A_TG = 710_300_100  # person A's Telegram account
STRANGER_TG = 710_300_999  # the stranger later given A's old number
PHONE = "251911556677"  # as Telegram sends it
E164 = "+251911556677"
LOCAL = "0911556677"
_update_ids = itertools.count(9_000_000)


@pytest.fixture(autouse=True)
def _telegram_on(telegram_linking: object) -> None:
    """The bot configured with test-only values."""


def _user(db: Session, phone: str = E164) -> User:
    db.rollback()
    user = db.scalar(select(User).where(User.phone == phone))
    assert user is not None
    return user


def _stranger_is_refused(db: Session, account_id: Any) -> None:
    """The stranger brings A's old number with their own Telegram account."""
    stranger = ApiClient()
    tg.open_link(tg.start(stranger), STRANGER_TG)
    answer = tg.share_phone(STRANGER_TG, PHONE)
    assert answer["text"] == telegram_sign_in.REPLIES["refused"]
    body = tg.check(stranger).json()
    assert (body["state"], body["reason"], body["me"]) == (
        "refused",
        "phone_on_other_telegram",
        None,
    )
    # No session, so nothing of A's can be read.
    assert stranger.get("/me").status_code == 401
    assert stranger.get("/me/addresses").status_code == 401
    # The account still belongs to A's Telegram account; the stranger got
    # neither it nor a new one.
    db.rollback()
    user = db.get(User, account_id)
    assert user is not None
    assert user.bound_telegram_id == A_TG
    assert user.telegram_id in (None, A_TG)
    assert db.scalar(select(User.id).where(User.bound_telegram_id == STRANGER_TG)) is None
    assert db.scalar(select(User.id).where(User.telegram_id == STRANGER_TG)) is None


def _connect_with_bot_link(client: ApiClient, telegram_id: int) -> dict[str, Any]:
    response = client.post("/me/telegram/link")
    assert response.status_code == 201, response.text
    token = response.json()["link"].rsplit("start=", 1)[1]
    caller = ApiClient(send_client_header=False, ip="198.51.100.7")
    answer = caller.post(
        "/telegram/webhook",
        json={
            "update_id": next(_update_ids),
            "message": {
                "message_id": 7,
                "date": 1_790_000_000,
                "from": {"id": telegram_id, "is_bot": False, "first_name": "Abebe"},
                "chat": {"id": telegram_id, "type": "private"},
                "text": f"/start {token}",
            },
        },
        headers={"X-Telegram-Bot-Api-Secret-Token": TEST_WEBHOOK_SECRET},
    )
    assert answer.status_code == 200, answer.text
    return dict(answer.json())


# -- the defect, step by step ---------------------------------------------------------------


def test_a_recycled_number_cannot_take_over_an_account_after_disconnect(db: Session) -> None:
    """The independent review's steps: A signs in with Telegram, presses
    "Disconnect Telegram", and later a stranger given A's old number signs in
    with Telegram. The stranger must not land in A's account."""
    staff = staff_client(db, "0911000300")
    zone = make_zone(staff)
    # A has a shop (made before SI-1, by phone) and signs in with Telegram.
    make_seller(staff, LOCAL)
    a = ApiClient()
    signed_in = tg.sign_in(a, A_TG, PHONE)
    account_id = signed_in["me"]["id"]
    assert signed_in["is_new_account"] is False
    # A saves an address.
    area_id = zone["areas"][0]["id"]
    assert a.post("/me/addresses", json=address_body(area_id)).status_code == 201

    # A presses "Disconnect Telegram".
    response = a.delete("/me/telegram")
    assert response.status_code == 200
    assert response.json()["state"] == "disconnected"
    user = _user(db)
    assert user.telegram_id is None, "disconnecting stops messages"

    # Later the phone company gives A's number to a stranger.
    _stranger_is_refused(db, user.id)
    assert _user(db).bound_telegram_id == A_TG, "MarkX remembers whose account it is"
    # A's address and shop are untouched and A can still sign in.
    again = tg.sign_in(ApiClient(), A_TG, PHONE)
    assert again["me"]["id"] == account_id


def test_after_disconnecting_only_the_same_telegram_account_signs_in_again(db: Session) -> None:
    first = tg.sign_in(ApiClient(), A_TG, PHONE)
    a = ApiClient()
    tg.sign_in(a, A_TG, PHONE)
    assert a.delete("/me/telegram").status_code == 200
    again = tg.sign_in(ApiClient(), A_TG, PHONE)
    assert again["me"]["id"] == first["me"]["id"]
    assert again["is_new_account"] is False
    user = _user(db)
    # Signing in with its own Telegram account connects it again, as before.
    assert (user.telegram_id, user.bound_telegram_id) == (A_TG, A_TG)
    assert user.telegram_unlinked_at is None


def test_an_account_that_never_had_telegram_is_claimed_by_the_first_sign_in(db: Session) -> None:
    """As before: an account made by an invitation, by staff or by SMS, that
    never had a Telegram account, is connected to the first Telegram sign-in
    with its number, and belongs to that Telegram account from then on."""
    staff = staff_client(db, "0911000301")
    owner, seller_id = make_seller(staff, "0911000010")
    # The shop invites a team member by phone number (D-024): an account
    # made by invitation, with no Telegram account.
    response = owner.post(f"/seller/{seller_id}/members", json={"phone": LOCAL})
    assert response.status_code == 201, response.text
    invited = _user(db)
    assert invited.bound_telegram_id is None

    body = tg.sign_in(ApiClient(), STRANGER_TG, PHONE)
    assert body["me"]["id"] == str(invited.id)
    user = _user(db)
    assert (user.telegram_id, user.bound_telegram_id) == (STRANGER_TG, STRANGER_TG)
    # From then on it is that Telegram account's for good.
    browser = ApiClient()
    tg.open_link(tg.start(browser), A_TG)
    tg.share_phone(A_TG, PHONE)
    assert tg.check(browser).json()["reason"] == "phone_on_other_telegram"


# -- every other way a different Telegram account could reach an existing account ----------


def test_connected_with_the_bot_link_then_disconnected_is_still_protected(db: Session) -> None:
    """A signed in by SMS, connected Telegram with the bot's link (D-093),
    then disconnected: the account had a Telegram account, so it is A's."""
    a = ApiClient()
    a.sign_in(LOCAL)
    assert (
        telegram_link.REPLIES[telegram_link.Outcome.LINKED]
        == (_connect_with_bot_link(a, A_TG)["text"])
    )
    assert a.delete("/me/telegram").status_code == 200
    user = _user(db)
    assert (user.telegram_id, user.bound_telegram_id) == (None, A_TG)
    _stranger_is_refused(db, user.id)


def test_connected_in_the_mini_app_then_disconnected_is_still_protected(db: Session) -> None:
    a = ApiClient()
    a.sign_in(LOCAL)
    response = a.post("/me/telegram", json={"init_data": telegram_init_data(A_TG)})
    assert response.status_code == 200, response.text
    assert a.delete("/me/telegram").status_code == 200
    user = _user(db)
    assert (user.telegram_id, user.bound_telegram_id) == (None, A_TG)
    _stranger_is_refused(db, user.id)


def test_a_disconnected_account_cannot_be_connected_to_another_telegram_account(
    db: Session,
) -> None:
    """Neither the bot's link nor the Mini App moves an account to a second
    Telegram account after a disconnect: that would let the second one sign
    in. Changing Telegram account is for support (F-24)."""
    a = ApiClient()
    tg.sign_in(a, A_TG, PHONE)
    assert a.delete("/me/telegram").status_code == 200

    answer = _connect_with_bot_link(a, STRANGER_TG)
    assert answer["text"] == telegram_link.REPLIES[telegram_link.Outcome.REFUSED]
    db.rollback()
    latest = db.scalars(
        select(TelegramLinkToken).order_by(TelegramLinkToken.created_at.desc())
    ).first()
    assert latest is not None
    assert (latest.status, latest.failure_reason) == ("failed", "already_connected")
    response = a.post("/me/telegram", json={"init_data": telegram_init_data(STRANGER_TG)})
    assert response.status_code == 409
    assert error_code(response) == "telegram_already_linked"

    user = _user(db)
    assert (user.telegram_id, user.bound_telegram_id) == (None, A_TG)
    _stranger_is_refused(db, user.id)
    # The Mini App does not sign the second Telegram account in either.
    response = ApiClient().post(
        "/auth/telegram",
        json={"init_data": telegram_init_data(STRANGER_TG)},
        headers={"X-MarkX-Client": "tma"},
    )
    assert (response.status_code, error_code(response)) == (409, "telegram_not_linked")
    # Its own Telegram account may still be connected again.
    assert (
        telegram_link.REPLIES[telegram_link.Outcome.LINKED]
        == (_connect_with_bot_link(a, A_TG)["text"])
    )


def test_a_remembered_telegram_account_never_reaches_a_second_account(db: Session) -> None:
    """The other direction: after A disconnects, A's Telegram account cannot
    be connected to, or sign in to, somebody else's account."""
    a = ApiClient()
    tg.sign_in(a, A_TG, PHONE)
    assert a.delete("/me/telegram").status_code == 200
    b = ApiClient()
    b.sign_in("0922556677")

    answer = _connect_with_bot_link(b, A_TG)
    assert answer["text"] == telegram_link.REPLIES[telegram_link.Outcome.REFUSED]
    response = b.post("/me/telegram", json={"init_data": telegram_init_data(A_TG)})
    assert (response.status_code, error_code(response)) == (409, "telegram_already_linked")
    browser = ApiClient()
    tg.open_link(tg.start(browser), A_TG)
    tg.share_phone(A_TG, "251922556677")
    assert tg.check(browser).json()["reason"] == "phone_in_use"
    other = _user(db, "+251922556677")
    assert (other.telegram_id, other.bound_telegram_id) == (None, None)


def test_a_disconnected_person_with_a_new_number_keeps_their_account(db: Session) -> None:
    """A disconnected, then changed number at the phone company. Signing in
    with A's Telegram account and the new number reaches A's account (the
    number follows, P-101-6), not a new, empty one; A's old number is free
    for its next owner, who gets a new account of their own."""
    first = tg.sign_in(ApiClient(), A_TG, PHONE)
    a = ApiClient()
    tg.sign_in(a, A_TG, PHONE)
    assert a.delete("/me/telegram").status_code == 200

    moved = tg.sign_in(ApiClient(), A_TG, "251933556677")
    assert moved["me"]["id"] == first["me"]["id"]
    assert moved["is_new_account"] is False
    assert moved["me"]["phone"] == "+251933556677"
    stranger = tg.sign_in(ApiClient(), STRANGER_TG, PHONE)
    assert stranger["is_new_account"] is True
    assert stranger["me"]["id"] != first["me"]["id"]


def test_a_refused_number_on_a_disconnected_account_does_not_reconnect_it(db: Session) -> None:
    """A refused sign-in by the account's own Telegram account (a new number
    that belongs to someone else) leaves Telegram disconnected."""
    a = ApiClient()
    tg.sign_in(a, A_TG, PHONE)
    assert a.delete("/me/telegram").status_code == 200
    ApiClient().sign_in("0922556677")
    browser = ApiClient()
    tg.open_link(tg.start(browser), A_TG)
    tg.share_phone(A_TG, "251922556677")
    assert tg.check(browser).json()["reason"] == "phone_in_use"
    user = _user(db)
    assert (user.telegram_id, user.bound_telegram_id) == (None, A_TG)


# -- the database is the last word ----------------------------------------------------------


def test_the_database_never_forgets_or_changes_an_accounts_telegram_account(
    db: Session,
) -> None:
    tg.sign_in(ApiClient(), A_TG, PHONE)
    user_id = _user(db).id
    for statement in (
        "update users set telegram_id = null, telegram_linked_at = null, bound_telegram_id = null",
        "update users set telegram_id = null, telegram_linked_at = null, "
        f"bound_telegram_id = {STRANGER_TG}",
        f"update users set telegram_id = {STRANGER_TG}",
    ):
        with pytest.raises(IntegrityError):
            db.execute(text(statement))
        db.rollback()
    user = db.get(User, user_id)
    assert user is not None
    assert (user.telegram_id, user.bound_telegram_id) == (A_TG, A_TG)


def test_the_database_allows_one_account_per_remembered_telegram_account(db: Session) -> None:
    tg.sign_in(ApiClient(), A_TG, PHONE)
    ApiClient().sign_in("0922556677")
    with pytest.raises(IntegrityError):
        db.execute(
            text(f"update users set bound_telegram_id = {A_TG} where phone = '+251922556677'")
        )
    db.rollback()


def test_no_answer_to_the_browser_names_the_remembered_telegram_account() -> None:
    a = ApiClient()
    tg.sign_in(a, A_TG, PHONE)
    for response in (a.get("/me"), a.delete("/me/telegram"), a.get("/me/telegram")):
        assert str(A_TG) not in response.text
        assert "bound" not in response.text


def test_audit_trail_never_holds_the_telegram_id(db: Session) -> None:
    a = ApiClient()
    tg.sign_in(a, A_TG, PHONE)
    a.delete("/me/telegram")
    tg.sign_in(ApiClient(), A_TG, PHONE)
    _stranger_is_refused(db, _user(db).id)
    db.rollback()
    trail = " ".join(str((e.action, e.before, e.after)) for e in db.scalars(select(AuditLog)))
    assert str(A_TG) not in trail
    assert str(STRANGER_TG) not in trail
