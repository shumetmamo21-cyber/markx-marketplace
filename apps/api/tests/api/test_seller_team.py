"""Seller members, roles and the payout account (blueprint C.3, D.4, S-09, S-13)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.core import settings_store
from markx.core.security import decrypt_text
from markx.notifications.models import Notification
from markx.sellers import service
from markx.sellers.models import SellerPayoutAccount
from tests.conftest import ApiClient, error_code
from tests.factories import make_seller, payout_body, staff_client, upload_document

OPS = "0911000200"
OWNER = "0911000001"
MANAGER = "0911000050"


@pytest.fixture
def staff(db: DbSession) -> ApiClient:
    return staff_client(db, OPS, StaffRole.OPERATIONS)


@pytest.fixture
def shop(staff: ApiClient) -> tuple[ApiClient, str]:
    return make_seller(staff, OWNER)


def _add_manager(owner: ApiClient, seller_id: str, phone: str = MANAGER) -> ApiClient:
    response = owner.post(f"/seller/{seller_id}/members", json={"phone": phone})
    assert response.status_code == 201, response.text
    manager = ApiClient()
    manager.sign_in(phone)
    return manager


# -- members ---------------------------------------------------------------------


def test_the_owner_adds_a_manager_by_phone_number(
    shop: tuple[ApiClient, str], db: DbSession
) -> None:
    owner, seller_id = shop
    response = owner.post(f"/seller/{seller_id}/members", json={"phone": "0911 000 050"})
    assert response.status_code == 201
    assert response.json()["role"] == "manager"
    assert response.json()["phone"] == "+251911000050"
    assert [m["role"] for m in owner.get(f"/seller/{seller_id}/members").json()] == [
        "owner", "manager",
    ]  # fmt: skip

    # The person had no account; they sign in for the first time and find the store.
    manager = ApiClient()
    me = manager.sign_in(MANAGER)["me"]
    assert [(s["seller_id"], s["role"]) for s in me["sellers"]] == [(seller_id, "manager")]
    assert "edit_store" in me["sellers"][0]["capabilities"]
    assert "change_payout_account" not in me["sellers"][0]["capabilities"]
    assert me["unread_notifications"] == 1
    assert db.scalar(select(Notification.template).where(Notification.user_id == me["id"])) == (
        "seller.member_added"
    )


def test_a_manager_runs_the_store_but_not_its_legal_side(shop: tuple[ApiClient, str]) -> None:
    """Blueprint C.3, the owner and manager columns, through the real routes."""
    owner, seller_id = shop
    manager = _add_manager(owner, seller_id)
    base = f"/seller/{seller_id}"

    assert manager.get(base).json()["role"] == "manager"
    assert manager.get(base).json()["missing"] == []
    assert manager.patch(f"{base}/store", json={"description": "Open daily"}).status_code == 200
    assert manager.get(f"{base}/members").status_code == 200

    denied = [
        manager.get(f"{base}/legal"),
        manager.patch(f"{base}/legal", json={"contact_phone": MANAGER}),
        manager.get(f"{base}/documents"),
        upload_document(manager, seller_id, "other"),
        manager.get(f"{base}/payout-accounts"),
        manager.put(f"{base}/payout-account", json=payout_body()),
        manager.post(f"{base}/submit"),
        manager.post(f"{base}/close"),
    ]
    for response in denied:
        assert response.status_code == 403, response.text
        assert error_code(response) == "permission_denied"


def test_the_free_plan_has_two_seats(shop: tuple[ApiClient, str], db: DbSession) -> None:
    owner, seller_id = shop
    _add_manager(owner, seller_id)
    full = owner.post(f"/seller/{seller_id}/members", json={"phone": "0911000051"})
    assert full.status_code == 409
    assert error_code(full) == "seat_limit_reached"

    settings_store.set_setting(db, "sellers.starter_seats", 3)
    db.commit()
    assert owner.post(f"/seller/{seller_id}/members", json={"phone": "0911000051"}).status_code == (
        201
    )


def test_only_the_manager_role_can_be_given_in_release_one(shop: tuple[ApiClient, str]) -> None:
    owner, seller_id = shop
    for role in ("catalogue", "orders", "finance"):
        response = owner.post(f"/seller/{seller_id}/members", json={"phone": MANAGER, "role": role})
        assert response.status_code == 422
        assert error_code(response) == "role_not_available"
    # Ownership cannot be handed out, and an unknown role is not a role.
    for role in ("owner", "admin"):
        response = owner.post(f"/seller/{seller_id}/members", json={"phone": MANAGER, "role": role})
        assert response.status_code == 422
        assert error_code(response) == "validation_failed"
    again = owner.post(f"/seller/{seller_id}/members", json={"phone": OWNER})
    assert error_code(again) == "already_member"
    assert error_code(owner.post(f"/seller/{seller_id}/members", json={"phone": "12345"})) == (
        "validation_failed"
    )


def test_the_owner_can_never_be_removed(shop: tuple[ApiClient, str], db: DbSession) -> None:
    owner, seller_id = shop
    manager = _add_manager(owner, seller_id)
    owner_member, manager_member = owner.get(f"/seller/{seller_id}/members").json()

    by_manager = manager.delete(f"/seller/{seller_id}/members/{owner_member['id']}")
    assert by_manager.status_code == 409
    assert error_code(by_manager) == "owner_cannot_be_removed"
    by_self = owner.delete(f"/seller/{seller_id}/members/{owner_member['id']}")
    assert error_code(by_self) == "owner_cannot_be_removed"

    # And the database allows one owner at most, whatever the code does.
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError, match="uq_seller_members_one_owner"):
        db.execute(
            text("update seller_members set role = 'owner' where id = :id"),
            {"id": manager_member["id"]},
        )
    db.rollback()


def test_a_manager_can_leave_and_be_added_again(shop: tuple[ApiClient, str]) -> None:
    owner, seller_id = shop
    manager = _add_manager(owner, seller_id)
    member_id = owner.get(f"/seller/{seller_id}/members").json()[1]["id"]

    assert manager.delete(f"/seller/{seller_id}/members/{member_id}").status_code == 200
    assert manager.get(f"/seller/{seller_id}").status_code == 404
    assert len(owner.get(f"/seller/{seller_id}/members").json()) == 1
    # Removing twice finds nothing to remove.
    assert owner.delete(f"/seller/{seller_id}/members/{member_id}").status_code == 404

    assert owner.post(f"/seller/{seller_id}/members", json={"phone": MANAGER}).status_code == 201
    assert manager.get(f"/seller/{seller_id}").status_code == 200


# -- payout account --------------------------------------------------------------


def test_the_account_number_is_encrypted_and_never_sent_back(
    shop: tuple[ApiClient, str], db: DbSession
) -> None:
    owner, seller_id = shop
    [account] = owner.get(f"/seller/{seller_id}/payout-accounts").json()
    assert account["account_last4"] == "6789"
    assert account["status"] == "active"
    assert "account_number" not in account
    assert "1000123456789" not in owner.get(f"/seller/{seller_id}/payout-accounts").text

    row = db.scalar(select(SellerPayoutAccount))
    assert row is not None
    assert b"1000123456789" not in bytes(row.account_number_encrypted)
    assert decrypt_text(row.account_number_encrypted) == "1000123456789"
    raw = db.execute(text("select account_number_encrypted from seller_payout_accounts")).scalar()
    assert b"1000123456789" not in bytes(raw)


def test_a_changed_account_waits_out_a_cooling_off_period(
    shop: tuple[ApiClient, str], db: DbSession
) -> None:
    owner, seller_id = shop
    changed = owner.put(
        f"/seller/{seller_id}/payout-account",
        json=payout_body(kind="wallet", provider_name="telebirr", account_number="0911 000 001"),
    )
    assert changed.status_code == 200, changed.text
    pending = changed.json()
    assert pending["status"] == "pending"
    wait = datetime.fromisoformat(pending["effective_from"]) - datetime.now(UTC)
    assert timedelta(hours=71) < wait <= timedelta(hours=72)

    accounts = owner.get(f"/seller/{seller_id}/payout-accounts").json()
    assert [(a["status"], a["account_last4"]) for a in accounts] == [
        ("active", "6789"), ("pending", "0001"),
    ]  # fmt: skip
    # The owner is told, in case the change was not theirs.
    assert db.scalar(
        select(Notification.id).where(Notification.template == "seller.payout_account_changed")
    )

    # A second change replaces the waiting one; the active account is untouched.
    owner.put(f"/seller/{seller_id}/payout-account", json=payout_body(account_number="5555554444"))
    accounts = owner.get(f"/seller/{seller_id}/payout-accounts").json()
    assert [(a["status"], a["account_last4"]) for a in accounts] == [
        ("active", "6789"), ("pending", "4444"),
    ]  # fmt: skip

    # Before the period ends the job changes nothing; after it, the new account is active.
    assert service.activate_due_payout_accounts(db) == 0
    assert (
        service.activate_due_payout_accounts(db, now=datetime.now(UTC) + timedelta(hours=73)) == 1
    )
    db.commit()
    accounts = owner.get(f"/seller/{seller_id}/payout-accounts").json()
    assert [(a["status"], a["account_last4"]) for a in accounts] == [("active", "4444")]


@pytest.mark.parametrize("number", ["12345", "12ab5678", "1" * 31, ""])
def test_a_bad_account_number_is_refused(shop: tuple[ApiClient, str], number: str) -> None:
    owner, seller_id = shop
    response = owner.put(
        f"/seller/{seller_id}/payout-account", json=payout_body(account_number=number)
    )
    assert response.status_code == 422


def test_the_database_allows_one_active_account_per_seller(
    shop: tuple[ApiClient, str], db: DbSession
) -> None:
    from sqlalchemy.exc import IntegrityError

    owner, seller_id = shop
    owner.put(f"/seller/{seller_id}/payout-account", json=payout_body(account_number="5555554444"))
    with pytest.raises(IntegrityError, match="uq_seller_payout_accounts_one_active"):
        db.execute(text("update seller_payout_accounts set status = 'active'"))
    db.rollback()
