"""Staff conflict of interest (blueprint C.5; audit H1; D-098).

A member of staff never acts on a store they belong to, on an order they
placed, or on a review or report they wrote. For every staff action that
decides or changes something about a store, an order, an offer, a review or
a report: the insider is refused with a message that another member of
staff must handle it, the attempt is in the audit log, nothing changed, and
an unrelated member of staff is still allowed.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.audit.models import AuditLog
from markx.trust.conflict import REFUSED_ACTION
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.factories import (
    add_to_cart,
    checkout,
    make_buyer,
    phone_body,
    staff_client,
    start_application,
    submit_application,
)
from tests.unit.test_images import phone_jpeg

INSIDER = "0911000301"  # staff, and on Alpha's team
OUTSIDER = "0911000302"  # staff, no tie to anything here
SHOPPER = "0911000303"  # staff, and a buyer in their own right
APPLICANT = "0911000304"  # staff, and applying to open a shop

OWN_STORE = "conflict_of_interest"
OWN_ORDER = "conflict_own_order"
OWN_SUBMISSION = "conflict_own_submission"


class Market(Bazaar):
    def __init__(self, db: DbSession) -> None:
        super().__init__(db)
        self.db = db
        self.insider = staff_client(db, INSIDER, StaffRole.SUPER_ADMIN)
        self.outsider = staff_client(db, OUTSIDER, StaffRole.SUPER_ADMIN)
        self.shopper_staff = staff_client(db, SHOPPER, StaffRole.SUPER_ADMIN)
        # The insider is added to Alpha's team by its owner, by phone number:
        # the same person, so the same account.
        added = self.a.post(f"/seller/{self.a_id}/members", json={"phone": INSIDER})
        assert added.status_code == 201, added.text
        # The shopper signs in by phone code as any buyer does.
        self.shopper, self.shopper_address = make_buyer(SHOPPER, self.area_id)

    def refusals(self, attempted: str) -> list[AuditLog]:
        self.db.rollback()
        return [
            row
            for row in self.db.scalars(
                select(AuditLog)
                .where(AuditLog.action == REFUSED_ACTION)
                .order_by(AuditLog.occurred_at)
            )
            if row.after["attempted"] == attempted
        ]

    def assert_refused(
        self, response: Any, code: str, attempted: str, *, by: str = INSIDER, count: int = 1
    ) -> None:
        assert response.status_code == 403, response.text
        assert error_code(response) == code
        assert "another staff member" in response.json()["error"]["message"]
        rows = self.refusals(attempted)
        assert len(rows) == count, rows
        row = rows[-1]
        assert row.actor_type == "staff"
        assert row.actor_user_id == self.user_id(by)
        assert (
            row.after["reason"]
            == {
                OWN_STORE: "own_store",
                OWN_ORDER: "own_order",
                OWN_SUBMISSION: "own_submission",
            }[code]
        )

    def user_id(self, phone: str) -> Any:
        from markx.accounts.models import User
        from markx.core.phone import normalize_phone

        return self.db.scalar(select(User.id).where(User.phone == normalize_phone(phone)))

    # -- orders ---------------------------------------------------------------

    def order(self, buyer: ApiClient, address_id: str, *, method: str = "seller_rider") -> Any:
        """One unit from Alpha. Returns (order id, seller order id)."""
        add_to_cart(buyer, self.a128["id"], 1)
        placed = checkout(buyer, address_id, {"alpha": method})
        assert placed.status_code == 201, placed.text
        return placed.json()["id"], placed.json()["seller_orders"][0]["id"]

    def advance(self, so_id: str, *steps: str) -> None:
        for step in steps:
            done = self.a.post(f"/seller/{self.a_id}/orders/{so_id}/{step}", json={})
            assert done.status_code == 200, (step, done.text)

    def hand_over(self, buyer: ApiClient, order_id: str, so_id: str) -> None:
        code = buyer.get(f"/me/orders/{order_id}").json()["seller_orders"][0]["handover_code"]
        handed = self.a.post(f"/seller/{self.a_id}/orders/{so_id}/handover", json={"code": code})
        assert handed.status_code == 200, handed.text

    def status(self, buyer: ApiClient, order_id: str) -> str:
        return str(buyer.get(f"/me/orders/{order_id}").json()["seller_orders"][0]["status"])

    def disputed(self, buyer: ApiClient, address_id: str) -> tuple[str, str]:
        order_id, so_id = self.order(buyer, address_id)
        self.advance(so_id, "confirm", "ready", "dispatch")
        self.hand_over(buyer, order_id, so_id)
        reported = buyer.post(
            f"/me/orders/{order_id}/seller-orders/{so_id}/problem",
            json={"problem_type": "damaged", "description": "The screen arrived cracked."},
        )
        assert reported.status_code == 200, reported.text
        return order_id, so_id

    def reviewed(self, buyer: ApiClient, address_id: str) -> str:
        """A completed collection order, reviewed by `buyer`. Returns the review id."""
        order_id, so_id = self.order(buyer, address_id, method="shop_collection")
        self.advance(so_id, "confirm", "ready")
        self.hand_over(buyer, order_id, so_id)
        received = buyer.post(f"/me/orders/{order_id}/seller-orders/{so_id}/confirm-received")
        assert received.status_code == 200, received.text
        item = buyer.get(f"/me/orders/{order_id}").json()["seller_orders"][0]["items"][0]["id"]
        review = buyer.post(
            f"/me/orders/{order_id}/items/{item}/review",
            json={"product_rating": 4, "seller_rating": 5, "body": ""},
        )
        assert review.status_code == 201, review.text
        return str(review.json()["id"])


@pytest.fixture
def market(db: DbSession) -> Market:
    return Market(db)


# -- the shared rule ---------------------------------------------------------------


def test_a_refusal_is_recorded_even_though_the_request_rolls_back(market: Market) -> None:
    """The refused request changes nothing, yet its attempt stays on record."""
    path = f"/admin/offers/{market.a128['id']}/remove"
    refused = market.insider.post(path, json={"reason": "Looks fake"})
    market.assert_refused(refused, OWN_STORE, "offer.staff_remove")
    (row,) = market.refusals("offer.staff_remove")
    assert (row.target_type, row.target_id) == ("offer", market.a128["id"])
    assert row.after["seller_id"] == market.a_id
    # Asking twice is recorded twice.
    market.assert_refused(
        market.insider.post(path, json={"reason": "Again"}), OWN_STORE, "offer.staff_remove",
        count=2,
    )  # fmt: skip


def test_someone_who_left_the_team_is_no_longer_refused(market: Market) -> None:
    members = market.a.get(f"/seller/{market.a_id}/members").json()
    insider = next(m for m in members if m["phone"].endswith(INSIDER[-4:]))
    removed = market.a.delete(f"/seller/{market.a_id}/members/{insider['id']}")
    assert removed.status_code in (200, 204), removed.text
    taken = market.insider.post(
        f"/admin/offers/{market.a128['id']}/remove", json={"reason": "Counterfeit reported"}
    )
    assert taken.status_code == 200, taken.text


# -- offers: take down and restore ------------------------------------------------------


def test_offer_takedown_and_restore(market: Market) -> None:
    offer = market.a128["id"]
    remove, restore = f"/admin/offers/{offer}/remove", f"/admin/offers/{offer}/restore"
    market.assert_refused(
        market.insider.post(remove, json={"reason": "Looks fake"}), OWN_STORE, "offer.staff_remove"
    )
    assert market.staff.get("/admin/offers/held").json() == []
    assert market.outsider.post(remove, json={"reason": "Counterfeit"}).status_code == 200

    market.assert_refused(
        market.insider.post(restore, json={"reason": "Proof sent"}),
        OWN_STORE, "offer.staff_restore",
    )  # fmt: skip
    assert len(market.staff.get("/admin/offers/held").json()) == 1
    assert market.outsider.post(restore, json={"reason": "Proof sent"}).status_code == 200


# -- seller verification (the check that existed before, now shared) -------------------------


@pytest.mark.parametrize(
    ("path", "body", "attempted"),
    [
        ("suspend", {"reason": "Declined orders"}, "seller.suspend"),
        (
            "verification-level",
            {"level": 1, "reason": "Downgrade"},
            "seller.set_verification_level",
        ),
        ("recheck", {"reason": "Annual check"}, "seller.recheck"),
    ],
)
def test_decisions_about_an_active_store(
    market: Market, path: str, body: dict[str, Any], attempted: str
) -> None:
    url = f"/admin/sellers/{market.a_id}/{path}"
    before = market.staff.get(f"/admin/sellers/{market.a_id}").json()
    market.assert_refused(market.insider.post(url, json=body), OWN_STORE, attempted)
    after = market.staff.get(f"/admin/sellers/{market.a_id}").json()
    assert (after["status"], after["verification_level"]) == (
        before["status"], before["verification_level"],
    )  # fmt: skip
    allowed = market.outsider.post(url, json=body)
    assert allowed.status_code == 200, allowed.text


def test_reinstating_a_store(market: Market) -> None:
    url = f"/admin/sellers/{market.a_id}"
    assert market.outsider.post(f"{url}/suspend", json={"reason": "Checks"}).status_code == 200
    market.assert_refused(
        market.insider.post(f"{url}/reinstate", json={"reason": "Fine"}), OWN_STORE,
        "seller.reinstate",
    )  # fmt: skip
    assert market.staff.get(url).json()["status"] == "suspended"
    assert market.outsider.post(f"{url}/reinstate", json={"reason": "Fine"}).status_code == 200


@pytest.mark.parametrize(
    ("path", "body", "attempted"),
    [
        ("request-documents", {"reason": "The licence is blurred"}, "seller.request_documents"),
        ("reject", {"reason": "Not a phone shop"}, "seller.reject"),
        ("approve", {"verification_level": 1, "payout_account_name_matches": True},
         "seller.approve"),
    ],
)  # fmt: skip
def test_decisions_about_an_application(
    market: Market, db: DbSession, path: str, body: dict[str, Any], attempted: str
) -> None:
    applicant_staff = staff_client(db, APPLICANT, StaffRole.SUPER_ADMIN)
    client, seller_id = start_application(market.staff, APPLICANT, tin="0000000009")
    submit_application(client, seller_id)
    documents = market.staff.get(f"/admin/sellers/{seller_id}").json()["documents"]
    review = f"/admin/sellers/{seller_id}/documents/{documents[0]['id']}/review"
    market.assert_refused(
        applicant_staff.post(review, json={"decision": "accepted"}), OWN_STORE,
        "seller_document.review", by=APPLICANT,
    )  # fmt: skip
    if path == "approve":
        for document in documents:
            accepted = market.outsider.post(
                f"/admin/sellers/{seller_id}/documents/{document['id']}/review",
                json={"decision": "accepted"},
            )
            assert accepted.status_code == 200, accepted.text
    url = f"/admin/sellers/{seller_id}/{path}"
    market.assert_refused(applicant_staff.post(url, json=body), OWN_STORE, attempted, by=APPLICANT)
    assert market.staff.get(f"/admin/sellers/{seller_id}").json()["status"] == "applied"
    allowed = market.outsider.post(url, json=body)
    assert allowed.status_code == 200, allowed.text


# -- orders: staff dispatch, handover code, problems -------------------------------------


def test_staff_dispatch(market: Market) -> None:
    buyer, address_id = market.buyer()
    order_id, so_id = market.order(buyer, address_id)
    market.advance(so_id, "confirm", "ready")
    path = f"/admin/orders/seller-orders/{so_id}/dispatch"
    market.assert_refused(market.insider.post(path, json={}), OWN_STORE, "seller_order.dispatch")
    assert market.status(buyer, order_id) == "ready"
    assert market.outsider.post(path, json={}).status_code == 200

    own_order, own_so = market.order(market.shopper, market.shopper_address)
    market.advance(own_so, "confirm", "ready")
    own_path = f"/admin/orders/seller-orders/{own_so}/dispatch"
    market.assert_refused(
        market.shopper_staff.post(own_path, json={}), OWN_ORDER, "seller_order.dispatch",
        by=SHOPPER, count=2,
    )  # fmt: skip
    assert market.status(market.shopper, own_order) == "ready"
    assert market.outsider.post(own_path, json={}).status_code == 200


def test_reissuing_a_handover_code(market: Market) -> None:
    body = {"reason": "Buyer locked out"}
    buyer, address_id = market.buyer()
    order_id, so_id = market.order(buyer, address_id)
    market.advance(so_id, "confirm", "ready", "dispatch")
    code = buyer.get(f"/me/orders/{order_id}").json()["seller_orders"][0]["handover_code"]
    path = f"/admin/orders/seller-orders/{so_id}/reissue-code"
    market.assert_refused(
        market.insider.post(path, json=body), OWN_STORE, "shipment.reissue_handover_code"
    )
    assert buyer.get(f"/me/orders/{order_id}").json()["seller_orders"][0]["handover_code"] == code
    assert market.outsider.post(path, json=body).status_code == 200
    assert buyer.get(f"/me/orders/{order_id}").json()["seller_orders"][0]["handover_code"] != code

    # A member of staff locked out of their own order cannot reset the lock.
    _, own_so = market.order(market.shopper, market.shopper_address)
    market.advance(own_so, "confirm", "ready", "dispatch")
    own_path = f"/admin/orders/seller-orders/{own_so}/reissue-code"
    market.assert_refused(
        market.shopper_staff.post(own_path, json=body), OWN_ORDER,
        "shipment.reissue_handover_code", by=SHOPPER, count=2,
    )  # fmt: skip
    assert market.outsider.post(own_path, json=body).status_code == 200


def test_resolving_a_problem(market: Market) -> None:
    body = {
        "decision": "seller_refunded",
        "reason": "Photos show the crack",
        "goods_returned": True,
    }
    buyer, address_id = market.buyer()
    order_id, so_id = market.disputed(buyer, address_id)
    path = f"/admin/orders/seller-orders/{so_id}/resolve-problem"
    market.assert_refused(market.insider.post(path, json=body), OWN_STORE, "dispute.resolve")
    assert market.status(buyer, order_id) == "disputed"
    assert market.outsider.post(path, json=body).status_code == 200
    assert market.status(buyer, order_id) == "refunded"

    own_order, own_so = market.disputed(market.shopper, market.shopper_address)
    own_path = f"/admin/orders/seller-orders/{own_so}/resolve-problem"
    market.assert_refused(
        market.shopper_staff.post(own_path, json=body), OWN_ORDER, "dispute.resolve",
        by=SHOPPER, count=2,
    )  # fmt: skip
    assert market.status(market.shopper, own_order) == "disputed"
    assert market.outsider.post(own_path, json=body).status_code == 200


# -- reviews ---------------------------------------------------------------------------


def test_moderating_a_review(market: Market) -> None:
    body = {"action": "hide", "reason": "Off topic"}
    buyer, address_id = market.buyer()
    review_id = market.reviewed(buyer, address_id)
    path = f"/admin/reviews/{review_id}/moderate"
    market.assert_refused(market.insider.post(path, json=body), OWN_STORE, "review.hide")
    assert market.outsider.post(path, json=body).status_code == 200

    # Nobody moderates their own review, of any store.
    own = market.reviewed(market.shopper, market.shopper_address)
    own_path = f"/admin/reviews/{own}/moderate"
    market.assert_refused(
        market.shopper_staff.post(own_path, json=body), OWN_SUBMISSION, "review.hide",
        by=SHOPPER, count=2,
    )  # fmt: skip
    assert market.outsider.post(own_path, json=body).status_code == 200


# -- reports ---------------------------------------------------------------------------


def _report(client: ApiClient, target_type: str, **target: Any) -> str:
    filed = client.post("/reports", json={"target_type": target_type, "reason": "fraud", **target})
    assert filed.status_code == 201, filed.text
    return str(filed.json()["id"])


@pytest.mark.parametrize("target", ["store", "offer", "review"])
def test_handling_a_report_about_ones_own_store(market: Market, target: str) -> None:
    if target == "store":
        report = _report(ApiClient(), "store", store_slug="alpha")
    elif target == "offer":
        report = _report(ApiClient(), "offer", target_id=market.a128["id"])
    else:
        buyer, address_id = market.buyer()
        report = _report(ApiClient(), "review", target_id=market.reviewed(buyer, address_id))
    body = {"outcome": "dismissed", "note": "Nothing wrong"}
    path = f"/admin/reports/{report}/resolve"
    market.assert_refused(market.insider.post(path, json=body), OWN_STORE, "report.dismissed")
    assert market.outsider.post(path, json=body).status_code == 200


def test_handling_ones_own_report_or_a_report_about_ones_own_review(market: Market) -> None:
    body = {"outcome": "actioned", "note": "Store warned"}
    # PROVISIONAL (D-098): whoever filed a report may not close it, so a member
    # of staff cannot file and then action a report against a rival store.
    own = _report(market.shopper, "store", store_slug="beta")
    market.assert_refused(
        market.shopper_staff.post(f"/admin/reports/{own}/resolve", json=body),
        OWN_SUBMISSION, "report.actioned", by=SHOPPER,
    )  # fmt: skip
    review = market.reviewed(market.shopper, market.shopper_address)
    about_mine = _report(ApiClient(), "review", target_id=review)
    market.assert_refused(
        market.shopper_staff.post(f"/admin/reports/{about_mine}/resolve", json=body),
        OWN_SUBMISSION, "report.actioned", by=SHOPPER, count=2,
    )  # fmt: skip
    for report in (own, about_mine):
        allowed = market.outsider.post(f"/admin/reports/{report}/resolve", json=body)
        assert allowed.status_code == 200, allowed.text


# -- pictures and product proposals (found beyond the audit's list) --------------------------


def test_taking_down_a_stores_real_photo(market: Market) -> None:
    added = market.a.post(
        f"/seller/{market.a_id}/products/{market.product['id']}/photos",
        files={"file": ("photo.jpg", phone_jpeg(), "image/jpeg")},
    )
    assert added.status_code == 202, added.text
    path = f"/admin/catalog/images/{added.json()['id']}/remove"
    body = {"reason": "Shows a competitor's logo"}
    market.assert_refused(market.insider.post(path, json=body), OWN_STORE, "product_image.remove")
    assert market.outsider.post(path, json=body).status_code == 200


def _proposal(market: Market, n: int) -> str:
    body = phone_body(
        market.catalog, name_en=f"Tecno Spark {n}", name_am=f"ቴክኖ ስፓርክ {n}", model=f"KJ{n}"
    )
    proposed = market.a.post(f"/seller/{market.a_id}/product-proposals", json=body)
    assert proposed.status_code == 201, proposed.text
    return str(proposed.json()["id"])


@pytest.mark.parametrize(("action", "attempted"), [
    ("approve", "product.approve"), ("archive", "product.archive"), ("merge", "product.merge"),
])  # fmt: skip
def test_deciding_on_a_product_ones_own_store_proposed(
    market: Market, action: str, attempted: str
) -> None:
    product = _proposal(market, 20)
    path = f"/admin/catalog/products/{product}/{action}"
    body = {"into_product_id": market.product["id"]} if action == "merge" else {}
    market.assert_refused(market.insider.post(path, json=body), OWN_STORE, attempted)
    detail = market.staff.get(f"/admin/catalog/products/{product}").json()
    assert detail["status"] == "pending_review"
    allowed = market.outsider.post(path, json=body)
    assert allowed.status_code == 200, allowed.text
