"""Seller application, staff review and verification (blueprint D.3, AD-01, P6)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.audit.models import AuditLog
from markx.core import settings_store
from markx.sellers.models import Seller
from tests.conftest import ApiClient, error_code
from tests.factories import (
    REQUIRED_BUSINESS_DOCUMENTS,
    application_body,
    approve_seller,
    invite_seller,
    make_seller,
    payout_body,
    staff_client,
    start_application,
    submit_application,
    upload_document,
)

OPS = "0911000200"
ABEBE = "0911000001"
SARA = "0911000002"


@pytest.fixture
def staff(db: DbSession) -> ApiClient:
    return staff_client(db, OPS, StaffRole.OPERATIONS)


def _actions(db: DbSession) -> list[str]:
    return list(db.scalars(select(AuditLog.action).order_by(AuditLog.occurred_at, AuditLog.id)))


# -- the P6 completion criterion ---------------------------------------------------


def test_a_seller_goes_from_application_to_verified(staff: ApiClient, db: DbSession) -> None:
    invite_seller(staff, ABEBE)
    seller = ApiClient()
    seller.sign_in(ABEBE)
    assert seller.get("/seller/eligibility").json()["may_apply"] is True

    created = seller.post("/seller/applications", json=application_body())
    assert created.status_code == 201, created.text
    application = created.json()
    seller_id = application["id"]
    assert application["status"] == "applied"
    assert application["review_state"] == "draft"
    assert application["verification_level"] == 0
    assert application["role"] == "owner"
    assert application["store"]["slug"] == "abebe-phones"
    assert application["missing"] == [
        *(f"document:{d}" for d in REQUIRED_BUSINESS_DOCUMENTS),
        "payout_account",
    ]

    # Staff do not see a draft, and the public sees no store.
    assert staff.get("/admin/sellers").json() == []
    assert staff.get(f"/admin/sellers/{seller_id}").status_code == 404
    assert ApiClient().get("/catalog/stores/abebe-phones").status_code == 404

    submit_application(seller, seller_id)
    submitted = seller.get(f"/seller/{seller_id}").json()
    assert submitted["review_state"] == "pending"
    assert submitted["missing"] == []

    [queued] = staff.get("/admin/sellers", params={"review_state": "pending"}).json()
    assert queued["id"] == seller_id
    detail = staff.get(f"/admin/sellers/{seller_id}").json()
    assert detail["legal"]["tin"] == "0012345678"
    assert len(detail["documents"]) == 4
    assert detail["payout_accounts"][0]["account_last4"] == "6789"

    approved = approve_seller(staff, seller_id, level=2)
    assert approved["status"] == "active"
    assert approved["review_state"] == "approved"
    assert approved["verification_level"] == 2
    assert approved["recheck_due_on"] is not None
    assert all(approved["checks"].values())

    me = seller.get("/me").json()
    assert me["sellers"][0]["status"] == "active"
    assert me["sellers"][0]["verification_level"] == 2
    assert me["unread_notifications"] == 1

    store = ApiClient().get("/catalog/stores/abebe-phones")
    assert store.status_code == 200
    assert store.headers["cache-control"] == "public, max-age=60"
    page = store.json()
    assert page["verification_level"] == 2
    assert page["checks"]["shop_visited"] is True
    assert page["completed_orders"] == 0
    # The seller's phone number is not on the public page (blueprint C.5).
    assert "contact_phone" not in page
    assert "+251911000001" not in store.text

    actions = _actions(db)
    for expected in ("seller_invitation.create", "seller.apply", "seller_document.upload",
                     "seller_payout_account.set", "seller.submit", "seller_document.review",
                     "seller.approve"):  # fmt: skip
        assert expected in actions


# -- who may apply -----------------------------------------------------------------


def test_applying_needs_an_invitation_at_launch(staff: ApiClient) -> None:
    seller = ApiClient()
    seller.sign_in(ABEBE)
    assert seller.get("/seller/eligibility").json() == {
        "invite_only": True, "invited": False, "may_apply": False, "individual_enabled": False,
    }  # fmt: skip
    response = seller.post("/seller/applications", json=application_body())
    assert response.status_code == 403
    assert error_code(response) == "invitation_required"


def test_an_invitation_belongs_to_one_phone_number(staff: ApiClient) -> None:
    invite_seller(staff, ABEBE)
    other = ApiClient()
    other.sign_in(SARA)
    assert error_code(other.post("/seller/applications", json=application_body())) == (
        "invitation_required"
    )


def test_an_invitation_is_used_once(staff: ApiClient) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    assert seller.post(f"/seller/{seller_id}/close").status_code == 200
    again = seller.post("/seller/applications", json=application_body())
    assert error_code(again) == "invitation_required"
    [invitation] = staff.get("/admin/sellers/invitations").json()
    assert invitation["used_by_seller_id"] == seller_id


def test_a_revoked_or_expired_invitation_does_not_work(
    staff: ApiClient, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    invitation = invite_seller(staff, ABEBE)
    assert error_code(staff.post("/admin/sellers/invitations", json={"phone": ABEBE})) == (
        "invitation_exists"
    )
    assert staff.delete(f"/admin/sellers/invitations/{invitation['id']}").status_code == 200
    seller = ApiClient()
    seller.sign_in(ABEBE)
    assert error_code(seller.post("/seller/applications", json=application_body())) == (
        "invitation_required"
    )

    invite_seller(staff, ABEBE)
    from datetime import UTC, datetime, timedelta

    from markx.sellers import service

    later = datetime.now(UTC) + timedelta(days=15)
    monkeypatch.setattr(service, "_now", lambda: later)
    assert error_code(seller.post("/seller/applications", json=application_body())) == (
        "invitation_required"
    )
    # A lapsed invitation does not block a fresh one.
    assert staff.post("/admin/sellers/invitations", json={"phone": ABEBE}).status_code == 201


def test_without_invite_only_anyone_signed_in_may_apply(db: DbSession) -> None:
    settings_store.set_setting(db, "sellers.invite_only", False)
    db.commit()
    seller = ApiClient()
    seller.sign_in(ABEBE)
    assert seller.post("/seller/applications", json=application_body()).status_code == 201


def test_individual_sellers_are_switched_off_by_policy(staff: ApiClient, db: DbSession) -> None:
    invite_seller(staff, ABEBE)
    seller = ApiClient()
    seller.sign_in(ABEBE)
    body = application_body(kind="individual", tin=None, licence_number=None)
    response = seller.post("/seller/applications", json=body)
    assert response.status_code == 403
    assert error_code(response) == "individual_sellers_disabled"

    settings_store.set_setting(db, "sellers.individual_enabled", True)
    db.commit()
    assert seller.post("/seller/applications", json=body).status_code == 201


def test_a_visitor_cannot_apply() -> None:
    response = ApiClient().post("/seller/applications", json=application_body())
    assert response.status_code == 401


def test_a_staff_session_cannot_apply_or_run_a_store(staff: ApiClient) -> None:
    _, seller_id = start_application(staff, ABEBE)
    invite_seller(staff, OPS)
    response = staff.post("/seller/applications", json=application_body(tin="0099999999"))
    assert response.status_code == 403
    assert error_code(response) == "seller_session_required"
    assert error_code(staff.get(f"/seller/{seller_id}")) == "seller_session_required"


# -- validation --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"tin": None}, "tin_required"),
        ({"tin": "12345abcde"}, "tin_invalid"),
        ({"tin": "123456789012"}, "tin_invalid"),
        ({"contact_phone": "+14155550100"}, "phone_invalid"),
        ({"shop_latitude": 9.01}, "pin_incomplete"),
        ({"legal_name": "  "}, "validation_failed"),
        ({"kind": "charity"}, "validation_failed"),
        ({"store_slug": "Bad Slug"}, "validation_failed"),
        ({"status": "active"}, "validation_failed"),
        ({"verification_level": 3}, "validation_failed"),
    ],
)
def test_a_bad_application_is_refused(
    staff: ApiClient, overrides: dict[str, object], code: str
) -> None:
    invite_seller(staff, ABEBE)
    seller = ApiClient()
    seller.sign_in(ABEBE)
    response = seller.post("/seller/applications", json=application_body(**overrides))
    assert response.status_code == 422, response.text
    assert error_code(response) == code


def test_one_application_at_a_time(staff: ApiClient) -> None:
    seller, _ = start_application(staff, ABEBE)
    invite_seller(staff, ABEBE)
    response = seller.post("/seller/applications", json=application_body(tin="0099999999"))
    assert response.status_code == 409
    assert error_code(response) == "application_in_progress"


def test_a_tin_belongs_to_one_live_seller(staff: ApiClient) -> None:
    start_application(staff, ABEBE)
    invite_seller(staff, SARA)
    sara = ApiClient()
    sara.sign_in(SARA)
    response = sara.post("/seller/applications", json=application_body(trade_name="Sara Mobile"))
    assert response.status_code == 409
    assert error_code(response) == "tin_taken"
    # Nothing half-made is left behind, and the invitation is still usable.
    assert sara.get("/me").json()["sellers"] == []
    assert (
        sara.post(
            "/seller/applications", json=application_body(tin="0087654321", trade_name="Sara")
        ).status_code
        == 201
    )


def test_store_links_are_unique_and_made_from_the_trade_name(staff: ApiClient) -> None:
    start_application(staff, ABEBE)
    sara, second = start_application(staff, SARA, tin="0087654321")
    slug = sara.get(f"/seller/{second}").json()["store"]["slug"]
    assert slug.startswith("abebe-phones-")
    assert slug != "abebe-phones"

    invite_seller(staff, "0911000003")
    third = ApiClient()
    third.sign_in("0911000003")
    taken = third.post(
        "/seller/applications", json=application_body(tin="0011111111", store_slug="abebe-phones")
    )
    assert error_code(taken) == "store_slug_taken"
    amharic = third.post(
        "/seller/applications", json=application_body(tin="0011111111", trade_name="አበበ ስልክ")
    )
    assert amharic.status_code == 201
    assert amharic.json()["store"]["slug"].startswith("store")


def test_an_incomplete_application_cannot_be_submitted(staff: ApiClient) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    upload_document(seller, seller_id, "owner_id")
    response = seller.post(f"/seller/{seller_id}/submit")
    assert response.status_code == 422
    assert error_code(response) == "application_incomplete"
    assert response.json()["error"]["details"]["missing"] == [
        "document:business_licence", "document:tin_certificate", "document:shop_photo",
        "payout_account",
    ]  # fmt: skip


def test_details_are_frozen_once_submitted_except_the_contact_phone(staff: ApiClient) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    edited = seller.patch(f"/seller/{seller_id}/legal", json={"legal_name": "Abebe Trading PLC"})
    assert edited.status_code == 200
    assert edited.json()["legal_name"] == "Abebe Trading PLC"

    submit_application(seller, seller_id)
    locked = seller.patch(f"/seller/{seller_id}/legal", json={"tin": "0099999999"})
    assert locked.status_code == 409
    assert error_code(locked) == "application_locked"
    phone = seller.patch(f"/seller/{seller_id}/legal", json={"contact_phone": "0911999999"})
    assert phone.status_code == 200
    assert phone.json()["contact_phone"] == "+251911999999"
    assert error_code(seller.post(f"/seller/{seller_id}/submit")) == "application_not_editable"


# -- staff review ------------------------------------------------------------------


def test_staff_ask_for_more_documents_and_the_seller_resubmits(staff: ApiClient) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    submit_application(seller, seller_id)
    detail = staff.get(f"/admin/sellers/{seller_id}").json()
    licence = next(d for d in detail["documents"] if d["doc_type"] == "business_licence")

    no_note = staff.post(
        f"/admin/sellers/{seller_id}/documents/{licence['id']}/review",
        json={"decision": "rejected"},
    )
    assert error_code(no_note) == "note_required"
    staff.post(
        f"/admin/sellers/{seller_id}/documents/{licence['id']}/review",
        json={"decision": "rejected", "note": "The photo is too blurred to read."},
    )
    asked = staff.post(
        f"/admin/sellers/{seller_id}/request-documents",
        json={"reason": "Please send a sharper photo of the licence."},
    )
    assert asked.status_code == 200
    assert asked.json()["review_state"] == "needs_documents"

    view = seller.get(f"/seller/{seller_id}").json()
    assert view["review_state"] == "needs_documents"
    assert view["review_note"] == "Please send a sharper photo of the licence."
    assert view["missing"] == ["document:business_licence"]
    assert error_code(seller.post(f"/seller/{seller_id}/submit")) == "application_incomplete"

    assert upload_document(seller, seller_id, "business_licence").status_code == 201
    assert seller.post(f"/seller/{seller_id}/submit").status_code == 200
    assert approve_seller(staff, seller_id)["verification_level"] == 2


def test_a_level_needs_the_checks_behind_it(staff: ApiClient) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    submit_application(seller, seller_id)
    body = {"verification_level": 2, "shop_visited": True, "payout_account_name_matches": True}

    # No document has been accepted yet.
    response = staff.post(f"/admin/sellers/{seller_id}/approve", json=body)
    assert response.status_code == 409
    assert error_code(response) == "verification_requirements_unmet"
    assert response.json()["error"]["details"]["missing"] == [
        "identity_verified", "business_licence_verified", "tin_verified", "shop_photo_verified",
    ]  # fmt: skip
    # The refused approval left nothing behind, not even the recorded shop visit.
    assert staff.get(f"/admin/sellers/{seller_id}").json()["shop_visited_at"] is None

    documents = staff.get(f"/admin/sellers/{seller_id}").json()["documents"]
    for document in documents:
        staff.post(
            f"/admin/sellers/{seller_id}/documents/{document['id']}/review",
            json={"decision": "accepted"},
        )
    not_visited = staff.post(
        f"/admin/sellers/{seller_id}/approve", json={**body, "shop_visited": False}
    )
    assert not_visited.json()["error"]["details"]["missing"] == ["shop_visited"]
    unchecked = staff.post(
        f"/admin/sellers/{seller_id}/approve", json={**body, "payout_account_name_matches": False}
    )
    assert error_code(unchecked) == "payout_account_unchecked"
    level_three = staff.post(
        f"/admin/sellers/{seller_id}/approve", json={**body, "verification_level": 3}
    )
    assert level_three.status_code == 422

    # Identity alone is enough for level 1.
    level_one = staff.post(
        f"/admin/sellers/{seller_id}/approve", json={**body, "verification_level": 1,
                                                     "shop_visited": False},
    )  # fmt: skip
    assert level_one.status_code == 200
    assert level_one.json()["verification_level"] == 1


def test_an_expired_document_no_longer_counts(
    staff: ApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    from markx.sellers import service

    seller, seller_id = start_application(staff, ABEBE)
    for doc_type in REQUIRED_BUSINESS_DOCUMENTS:
        expiry = (datetime.now(UTC) + timedelta(days=30)).date().isoformat()
        form = {"expires_on": expiry} if doc_type == "business_licence" else {}
        assert upload_document(seller, seller_id, doc_type, **form).status_code == 201
    past = upload_document(seller, seller_id, "other", expires_on="2020-01-01")
    assert error_code(past) == "document_expired"
    seller.put(f"/seller/{seller_id}/payout-account", json=payout_body())
    seller.post(f"/seller/{seller_id}/submit")
    approve_seller(staff, seller_id)

    later = datetime.now(UTC) + timedelta(days=31)
    monkeypatch.setattr(service, "_now", lambda: later)
    checks = seller.get(f"/seller/{seller_id}").json()["checks"]
    assert checks["business_licence_verified"] is False
    assert checks["identity_verified"] is True
    # The yearly re-check cannot be signed off while a document has lapsed.
    recheck = staff.post(f"/admin/sellers/{seller_id}/recheck", json={"reason": "Annual check"})
    assert error_code(recheck) == "verification_requirements_unmet"


def test_rejection_closes_the_application_and_frees_the_tin(staff: ApiClient) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    submit_application(seller, seller_id)
    assert staff.post(f"/admin/sellers/{seller_id}/reject", json={"reason": "x"}).status_code == 422
    rejected = staff.post(
        f"/admin/sellers/{seller_id}/reject", json={"reason": "The licence is not in this name."}
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "closed"
    assert rejected.json()["review_state"] == "rejected"
    assert error_code(seller.get(f"/seller/{seller_id}")) == "seller_closed"
    membership = seller.get("/me").json()["sellers"][0]
    assert (membership["status"], membership["review_state"]) == ("closed", "rejected")

    # The same TIN can apply again with a corrected application.
    _, second = start_application(staff, SARA)
    assert second != seller_id


def test_decisions_apply_only_to_an_application_awaiting_review(staff: ApiClient) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    body = {"verification_level": 1, "payout_account_name_matches": True}
    # Still a draft: staff cannot even see it.
    assert staff.post(f"/admin/sellers/{seller_id}/approve", json=body).status_code == 409
    submit_application(seller, seller_id)
    approve_seller(staff, seller_id)
    for path, payload in (
        ("approve", body),
        ("reject", {"reason": "Too late to reject"}),
        ("request-documents", {"reason": "Too late to ask"}),
    ):
        response = staff.post(f"/admin/sellers/{seller_id}/{path}", json=payload)
        assert response.status_code == 409, path
        assert error_code(response) == "not_awaiting_review"
    assert error_code(
        staff.post(f"/admin/sellers/{seller_id}/reinstate", json={"reason": "abc"})
    ) == ("seller_not_suspended")


def test_staff_raise_and_lower_the_verification_level(staff: ApiClient, db: DbSession) -> None:
    _, seller_id = make_seller(staff, ABEBE, level=1)
    path = f"/admin/sellers/{seller_id}/verification-level"

    # Level 3 follows level 2; it cannot be jumped to (blueprint D.3).
    jump = staff.post(path, json={"level": 3, "reason": "Good seller"})
    assert error_code(jump) == "level_three_is_earned"
    # Level 2 needs the visited shop.
    unvisited = staff.post(path, json={"level": 2, "reason": "Documents are fine"})
    assert unvisited.json()["error"]["details"]["missing"] == ["shop_visited"]

    two = staff.post(path, json={"level": 2, "reason": "Shop visited", "shop_visited": True})
    assert two.json()["verification_level"] == 2
    three = staff.post(path, json={"level": 3, "reason": "Six months of clean orders"})
    assert three.json()["verification_level"] == 3
    down = staff.post(path, json={"level": 1, "reason": "Licence under query"})
    assert down.json()["verification_level"] == 1
    assert staff.post(path, json={"level": 4, "reason": "No such level"}).status_code == 422

    entry = db.scalars(
        select(AuditLog)
        .where(AuditLog.action == "seller.set_verification_level")
        .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
    ).first()
    assert entry is not None
    assert entry.actor_type == "staff"
    assert entry.before["verification_level"] == 3
    assert entry.after == {
        "status": "active", "review_state": "approved", "verification_level": 1,
        "reason": "Licence under query",
    }  # fmt: skip


def test_no_seller_route_lets_a_seller_set_its_own_level_or_status(staff: ApiClient) -> None:
    """Blueprint C.5: badges and levels are set by staff."""
    seller, seller_id = make_seller(staff, ABEBE, level=1)
    for path in ("verification-level", "approve", "suspend", "reinstate", "recheck"):
        response = seller.post(f"/admin/sellers/{seller_id}/{path}", json={})
        assert response.status_code == 403, path
        assert error_code(response) == "staff_only"
    for body in ({"verification_level": 3}, {"status": "active"}, {"review_state": "approved"}):
        assert seller.patch(f"/seller/{seller_id}/legal", json=body).status_code == 422
        assert seller.patch(f"/seller/{seller_id}/store", json=body).status_code == 422
    assert seller.get(f"/seller/{seller_id}").json()["verification_level"] == 1


def test_a_staff_member_cannot_decide_about_their_own_store(staff: ApiClient) -> None:
    """Nobody verifies themselves: the operations officer also owns a shop."""
    # Signed in by phone code, the officer is an ordinary applicant.
    invite_seller(staff, OPS)
    as_seller = ApiClient()
    as_seller.sign_in(OPS)
    seller_id = as_seller.post("/seller/applications", json=application_body()).json()["id"]
    submit_application(as_seller, seller_id)

    response = staff.post(
        f"/admin/sellers/{seller_id}/approve",
        json={"verification_level": 1, "payout_account_name_matches": True},
    )
    assert response.status_code == 403
    assert error_code(response) == "conflict_of_interest"
    document = staff.get(f"/admin/sellers/{seller_id}").json()["documents"][0]
    review = staff.post(
        f"/admin/sellers/{seller_id}/documents/{document['id']}/review",
        json={"decision": "accepted"},
    )
    assert error_code(review) == "conflict_of_interest"


def test_suspending_hides_the_store_and_reinstating_restores_it(staff: ApiClient) -> None:
    seller, seller_id = make_seller(staff, ABEBE)
    assert ApiClient().get("/catalog/stores/abebe-phones").status_code == 200

    suspended = staff.post(
        f"/admin/sellers/{seller_id}/suspend", json={"reason": "Repeated declined orders"}
    )
    assert suspended.json()["status"] == "suspended"
    assert ApiClient().get("/catalog/stores/abebe-phones").status_code == 404
    # The seller still reaches the dashboard, to see why.
    assert seller.get(f"/seller/{seller_id}").json()["status"] == "suspended"
    again = staff.post(f"/admin/sellers/{seller_id}/suspend", json={"reason": "Twice"})
    assert error_code(again) == "seller_not_active"

    staff.post(f"/admin/sellers/{seller_id}/reinstate", json={"reason": "Issue resolved"})
    assert ApiClient().get("/catalog/stores/abebe-phones").status_code == 200


def test_the_yearly_recheck_is_queued_and_signed_off(staff: ApiClient, db: DbSession) -> None:
    from datetime import date, timedelta

    _, seller_id = make_seller(staff, ABEBE)
    assert staff.get("/admin/sellers", params={"recheck_due": True}).json() == []
    seller = db.get(Seller, seller_id)
    assert seller is not None
    seller.recheck_due_on = date.today() - timedelta(days=1)
    db.commit()
    [due] = staff.get("/admin/sellers", params={"recheck_due": True}).json()
    assert due["id"] == seller_id

    done = staff.post(
        f"/admin/sellers/{seller_id}/recheck", json={"reason": "Licence renewed for 2019 E.C."}
    )
    assert done.status_code == 200
    assert staff.get("/admin/sellers", params={"recheck_due": True}).json() == []


def test_the_owner_closes_the_store_for_good(staff: ApiClient) -> None:
    seller, seller_id = make_seller(staff, ABEBE)
    closed = seller.post(f"/seller/{seller_id}/close")
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    assert ApiClient().get("/catalog/stores/abebe-phones").status_code == 404
    assert error_code(seller.get(f"/seller/{seller_id}")) == "seller_closed"
    for path in ("suspend", "reinstate"):
        assert (
            staff.post(f"/admin/sellers/{seller_id}/{path}", json={"reason": "abc"}).status_code
            == 409
        )


def test_the_staff_queue_pages_by_cursor(staff: ApiClient) -> None:
    ids = []
    for index, phone in enumerate(("0911000011", "0911000012", "0911000013")):
        client, seller_id = start_application(staff, phone, tin=f"00000000{index:02d}")
        submit_application(client, seller_id)
        ids.append(seller_id)
    first = staff.get("/admin/sellers", params={"limit": 2}).json()
    assert [row["id"] for row in first] == ids[:2]
    second = staff.get("/admin/sellers", params={"limit": 2, "after": first[-1]["id"]}).json()
    assert [row["id"] for row in second] == ids[2:]
    assert staff.get("/admin/sellers", params={"status": "active"}).json() == []


# -- the store -----------------------------------------------------------------------


def test_the_store_page_is_edited_by_the_seller(staff: ApiClient) -> None:
    seller, seller_id = make_seller(staff, ABEBE)
    response = seller.patch(
        f"/seller/{seller_id}/store",
        json={
            "name": "Abebe Phones & Accessories",
            "description": "Original phones with warranty.",
            "return_policy": "Returns within 3 days if unopened.",
            "working_hours": "Mon-Sat 2:00-12:00 (Ethiopian time)",
            "areas_served": ["Bole", "Kazanchis"],
            "telegram_channel": "@abebephones",
        },
    )
    assert response.status_code == 200, response.text
    page = ApiClient().get("/catalog/stores/abebe-phones").json()
    assert page["name"] == "Abebe Phones & Accessories"
    assert page["areas_served"] == ["Bole", "Kazanchis"]
    assert page["telegram_channel"] == "@abebephones"

    # The link is permanent once the store is public.
    moved = seller.patch(f"/seller/{seller_id}/store", json={"slug": "new-link"})
    assert error_code(moved) == "store_slug_locked"
    bad = seller.patch(f"/seller/{seller_id}/store", json={"telegram_channel": "https://t.me/x"})
    assert bad.status_code == 422


def test_an_applicant_may_still_choose_the_store_link(staff: ApiClient) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    start_application(staff, SARA, tin="0087654321", store_slug="sara-mobile")
    assert seller.patch(f"/seller/{seller_id}/store", json={"slug": "abebe"}).json()["slug"] == (
        "abebe"
    )
    taken = seller.patch(f"/seller/{seller_id}/store", json={"slug": "sara-mobile"})
    assert error_code(taken) == "store_slug_taken"
