"""Phone numbers typed with digits from another script (B-3, D-098).

Some phone keyboards type Arabic-Indic (٠١٢), Persian (۰۱۲) or full-width
(０１２) digits. They are read as the digits 0 to 9 they stand for, at every
place MarkX reads a phone number. Characters that are not decimal digits,
such as the Ethiopic numerals ፩ to ፱ (which have no zero), are refused with
the usual clear message. Before this fix a number whose last eight digits
were in another script got past the check and the database refused it: a
server error.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole, User
from markx.sellers.models import Seller
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code, latest_code, let_resend_cooldown_pass
from tests.factories import (
    STAFF_PASSWORD,
    address_body,
    application_body,
    invite_seller,
    make_staff,
    staff_client,
)

ARABIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
PERSIAN = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
FULL_WIDTH = str.maketrans("0123456789", "０１２３４５６７８９")


def arabic(phone: str) -> str:
    return phone.translate(ARABIC)


def persian(phone: str) -> str:
    return phone.translate(PERSIAN)


def full_width(phone: str) -> str:
    return phone.translate(FULL_WIDTH)


def mixed(phone: str) -> str:
    """The form that used to cause the server error: the first two digits
    plain, the rest in another script."""
    return phone[:2] + arabic(phone[2:])


SCRIPTS = [arabic, persian, full_width, mixed]
# Ethiopic numerals: not decimal digits, never used in phone numbers.
ETHIOPIC = "፱፩፩፪፫፬፭፮፯"


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def _ok(response: Any, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json()


def _phone_invalid(response: Any) -> None:
    assert response.status_code == 422, response.text
    assert error_code(response) == "phone_invalid"


# -- signing in ----------------------------------------------------------------------------


@pytest.mark.parametrize("script", SCRIPTS)
def test_a_buyer_signs_in_with_other_digits_and_reaches_the_same_account(
    db: DbSession, script: Any
) -> None:
    plain = "0911777001"
    ApiClient().sign_in(plain)
    typed = script(plain)
    client = ApiClient()
    let_resend_cooldown_pass(plain)
    _ok(client.post("/auth/otp/request", json={"phone": typed}))
    code = latest_code(plain)
    _ok(client.post("/auth/otp/verify", json={"phone": typed, "code": code}))
    db.rollback()
    users = db.scalars(select(User).where(User.phone == "+251911777001")).all()
    assert len(users) == 1
    assert client.get("/me").json()["id"] == str(users[0].id)


def test_a_code_request_with_ethiopic_numerals_is_refused_clearly() -> None:
    _phone_invalid(ApiClient().post("/auth/otp/request", json={"phone": ETHIOPIC}))
    _phone_invalid(ApiClient().post("/auth/otp/verify", json={"phone": ETHIOPIC, "code": "123456"}))


@pytest.mark.parametrize("script", SCRIPTS)
def test_staff_sign_in_with_other_digits(db: DbSession, script: Any) -> None:
    import pyotp

    plain = "0911777002"
    secret = make_staff(db, plain, StaffRole.SUPPORT)
    signed_in = ApiClient().post(
        "/auth/staff/sign-in",
        json={"phone": script(plain), "password": STAFF_PASSWORD,
              "totp_code": pyotp.TOTP(secret).now()},
    )  # fmt: skip
    _ok(signed_in)
    refused = ApiClient().post(
        "/auth/staff/sign-in",
        json={"phone": ETHIOPIC, "password": STAFF_PASSWORD, "totp_code": "000000"},
    )
    assert refused.status_code == 401  # the usual answer; never a server error


# -- staff accounts, invitations -----------------------------------------------------------


@pytest.mark.parametrize("script", SCRIPTS)
def test_creating_a_staff_account_with_other_digits(db: DbSession, script: Any) -> None:
    admin = staff_client(db, "0911777003", StaffRole.SUPER_ADMIN)
    body = {"name": "Hana", "role": "support", "password": "a long staff passphrase"}
    created = _ok(admin.post("/admin/staff", json={"phone": script("0911777004"), **body}), 201)
    assert created["staff"]["phone_last4"] == "7004"
    _phone_invalid(admin.post("/admin/staff", json={"phone": ETHIOPIC, **body}))


@pytest.mark.parametrize("script", SCRIPTS)
def test_inviting_a_seller_with_other_digits(db: DbSession, script: Any) -> None:
    admin = staff_client(db, "0911777005", StaffRole.SUPER_ADMIN)
    invited = _ok(admin.post("/admin/sellers/invitations", json={"phone": script("0911777006")}),
                  201)  # fmt: skip
    assert invited["phone"] == "+251911777006"
    _phone_invalid(admin.post("/admin/sellers/invitations", json={"phone": ETHIOPIC}))


# -- addresses -----------------------------------------------------------------------------


@pytest.mark.parametrize("script", SCRIPTS)
def test_an_address_with_other_digits(bazaar: Bazaar, script: Any) -> None:
    buyer = ApiClient()
    buyer.sign_in("0911777007")
    body = address_body(bazaar.area_id, phone=script("0911555001"), phone2=script("0711555002"))
    saved = _ok(buyer.post("/me/addresses", json=body), 201)
    assert (saved["phone"], saved["phone2"]) == ("+251911555001", "+251711555002")
    _phone_invalid(buyer.post("/me/addresses", json={**body, "phone": ETHIOPIC}))
    _phone_invalid(buyer.post("/me/addresses", json={**body, "phone2": ETHIOPIC}))


# -- sellers: application, contact phone, team ----------------------------------------------


@pytest.mark.parametrize("script", SCRIPTS)
def test_a_seller_application_and_its_contact_phone_with_other_digits(
    db: DbSession, script: Any
) -> None:
    admin = staff_client(db, "0911777008", StaffRole.SUPER_ADMIN)
    invite_seller(admin, "0911777009")
    seller = ApiClient()
    seller.sign_in("0911777009")
    _phone_invalid(
        seller.post("/seller/applications", json=application_body(contact_phone=ETHIOPIC))
    )
    applied = seller.post(
        "/seller/applications", json=application_body(contact_phone=script("0911777010"))
    )
    seller_id = _ok(applied, 201)["id"]
    db.rollback()
    assert db.get(Seller, seller_id).contact_phone == "+251911777010"  # type: ignore[union-attr]
    changed = seller.patch(
        f"/seller/{seller_id}/legal", json={"contact_phone": script("0711777011")}
    )
    assert _ok(changed)["contact_phone"] == "+251711777011"
    _phone_invalid(seller.patch(f"/seller/{seller_id}/legal", json={"contact_phone": ETHIOPIC}))


@pytest.mark.parametrize("script", SCRIPTS)
def test_adding_a_team_member_with_other_digits(bazaar: Bazaar, script: Any) -> None:
    members = f"/seller/{bazaar.a_id}/members"
    added = _ok(bazaar.a.post(members, json={"phone": script("0911777012")}), 201)
    assert added["phone"] == "+251911777012"
    _phone_invalid(bazaar.a.post(members, json={"phone": ETHIOPIC}))
    # The new member signs in with the plain number and is on the team.
    member = ApiClient()
    member.sign_in("0911777012")
    assert member.get(f"/seller/{bazaar.a_id}").status_code == 200


# -- "can't find it? ask for it" -------------------------------------------------------------


@pytest.mark.parametrize("script", SCRIPTS)
def test_a_product_request_with_other_digits(bazaar: Bazaar, db: DbSession, script: Any) -> None:
    from markx.catalog.models import ProductRequest

    visitor = ApiClient()
    body = {"query": "Nokia 3310", "contact_phone": script("0911777013")}
    _ok(visitor.post("/product-requests", json=body), 201)
    _phone_invalid(visitor.post("/product-requests", json={**body, "contact_phone": ETHIOPIC}))
    db.rollback()
    assert db.scalars(select(ProductRequest.contact_phone)).all() == ["+251911777013"]


# -- the rider's phone at dispatch -----------------------------------------------------------


def _ready_alpha_order(bazaar: Bazaar) -> str:
    from tests.factories import add_to_cart, checkout

    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 1)
    placed = _ok(checkout(buyer, address_id, {"alpha": "seller_rider"}), 201)
    so_id = str(placed["seller_orders"][0]["id"])
    for step in ("confirm", "ready"):
        _ok(bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{so_id}/{step}", json={}))
    return so_id


@pytest.mark.parametrize("script", SCRIPTS)
def test_the_sellers_rider_phone_with_other_digits(bazaar: Bazaar, script: Any) -> None:
    so_id = _ready_alpha_order(bazaar)
    path = f"/seller/{bazaar.a_id}/orders/{so_id}/dispatch"
    _phone_invalid(bazaar.a.post(path, json={"rider_phone": ETHIOPIC}))
    sent = _ok(
        bazaar.a.post(path, json={"rider_name": "Dawit", "rider_phone": script("0922000111")})
    )
    assert sent["shipment"]["rider_phone"] == "+251922000111"


@pytest.mark.parametrize("script", SCRIPTS)
def test_the_staff_rider_phone_with_other_digits(bazaar: Bazaar, script: Any) -> None:
    so_id = _ready_alpha_order(bazaar)
    path = f"/admin/orders/seller-orders/{so_id}/dispatch"
    _phone_invalid(bazaar.staff.post(path, json={"rider_phone": ETHIOPIC}))
    _ok(
        bazaar.staff.post(path, json={"rider_name": "Courier", "rider_phone": script("0933000111")})
    )


# -- the development SMS inbox ---------------------------------------------------------------


@pytest.mark.parametrize("script", SCRIPTS)
def test_the_development_sms_inbox_reads_other_digits(script: Any) -> None:
    ApiClient().sign_in("0911777014")
    inbox = _ok(ApiClient().get("/dev/sms-inbox", params={"phone": script("0911777014")}))
    assert inbox
    _phone_invalid(ApiClient().get("/dev/sms-inbox", params={"phone": ETHIOPIC}))
