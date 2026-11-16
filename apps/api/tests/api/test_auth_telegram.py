"""Telegram Mini App sign-in: signature and timestamp verified on the server (D.2, H.3)."""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import User
from tests.conftest import ApiClient, error_code
from tests.factories import telegram_init_data

PHONE = "0911234567"
TMA = {"X-MarkX-Client": "tma"}


def _linked_account(telegram_id: int) -> ApiClient:
    client = ApiClient()
    client.sign_in(PHONE)
    response = client.post("/me/telegram", json={"init_data": telegram_init_data(telegram_id)})
    assert response.status_code == 200, response.text
    return client


def test_a_linked_telegram_identity_signs_in(db: DbSession) -> None:
    _linked_account(777001)
    response = ApiClient().post(
        "/auth/telegram", json={"init_data": telegram_init_data(777001)}, headers=TMA
    )
    assert response.status_code == 200
    token = response.json()["session_token"]
    assert token
    assert "set-cookie" not in response.headers
    me = ApiClient().get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["phone"] == "+251911234567"
    assert db.scalars(select(User)).one().telegram_id == 777001


def test_tampered_start_up_data_is_rejected() -> None:
    _linked_account(777001)
    good = telegram_init_data(777001)
    # Claim to be another Telegram user while keeping the old signature.
    tampered = good.replace("777001", "777002")
    response = ApiClient().post("/auth/telegram", json={"init_data": tampered}, headers=TMA)
    assert response.status_code == 403
    assert error_code(response) == "telegram_signature_invalid"


def test_data_signed_with_another_bot_token_is_rejected() -> None:
    _linked_account(777001)
    forged = telegram_init_data(777001, bot_token="999999:attacker-controlled-token")
    response = ApiClient().post("/auth/telegram", json={"init_data": forged}, headers=TMA)
    assert response.status_code == 403
    assert error_code(response) == "telegram_signature_invalid"


def test_missing_hash_or_garbage_is_rejected() -> None:
    for bad in ["auth_date=1&user=%7B%7D", "not-even-a-query-string", "hash=abc"]:
        response = ApiClient().post("/auth/telegram", json={"init_data": bad}, headers=TMA)
        assert response.status_code == 403, bad
        assert error_code(response) == "telegram_signature_invalid"


def test_old_start_up_data_is_rejected() -> None:
    _linked_account(777001)
    stale = telegram_init_data(777001, auth_date=int(time.time()) - 2 * 3600)
    response = ApiClient().post("/auth/telegram", json={"init_data": stale}, headers=TMA)
    assert response.status_code == 403
    assert error_code(response) == "telegram_data_expired"
    future = telegram_init_data(777001, auth_date=int(time.time()) + 3600)
    response = ApiClient().post("/auth/telegram", json={"init_data": future}, headers=TMA)
    assert response.status_code == 403
    assert error_code(response) == "telegram_data_expired"


def test_an_unlinked_identity_must_confirm_a_phone_first() -> None:
    response = ApiClient().post(
        "/auth/telegram", json={"init_data": telegram_init_data(555)}, headers=TMA
    )
    assert response.status_code == 409
    assert error_code(response) == "telegram_not_linked"


def test_one_telegram_identity_per_account_and_one_account_per_identity() -> None:
    first = _linked_account(777001)
    # The same account cannot take a second Telegram identity.
    response = first.post("/me/telegram", json={"init_data": telegram_init_data(777002)})
    assert response.status_code == 409
    assert error_code(response) == "telegram_already_linked"
    # Another account cannot take an identity that is already linked.
    second = ApiClient()
    second.sign_in("0922334455")
    response = second.post("/me/telegram", json={"init_data": telegram_init_data(777001)})
    assert response.status_code == 409
    assert error_code(response) == "telegram_already_linked"
    # Linking the same identity again is harmless.
    assert (
        first.post("/me/telegram", json={"init_data": telegram_init_data(777001)}).status_code
        == 200
    )
