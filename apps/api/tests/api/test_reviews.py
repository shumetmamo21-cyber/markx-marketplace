"""Reviews and ratings (blueprint D.15, C-18, S-16, AD-12, H.4; D-066): only a
completed order's buyer reviews, once per item, inside the window; pattern
checks hold suspicious reviews for staff; the seller replies but never
removes; staff moderate with a reason; rating totals follow in the
background and count published reviews only.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole, User
from markx.audit.models import AuditLog
from markx.core import settings_store
from markx.core.errors import Conflict
from markx.notifications.models import Notification
from markx.reviews import service as reviews
from markx.sellers.models import SellerMember
from markx.trust.models import RatingSummary
from markx.worker.runner import run_once
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.factories import add_to_cart, checkout, staff_client

NO_JOBS = ()


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


class Bought:
    """A buyer's order collected at the shop and confirmed: every part
    `completed`, in real time. `lines` is a list of (offer, quantity)."""

    def __init__(self, bazaar: Bazaar, lines: list[tuple[dict[str, Any], int]],
                 *, complete: bool = True) -> None:  # fmt: skip
        self.buyer, address_id = bazaar.buyer()
        stores = set()
        for offer, quantity in lines:
            add_to_cart(self.buyer, offer["id"], quantity)
            stores.add("alpha" if offer["id"] in (bazaar.a128["id"], bazaar.a256["id"]) else "beta")
        placed = checkout(self.buyer, address_id, dict.fromkeys(stores, "shop_collection"))
        assert placed.status_code == 201, placed.text
        self.order = placed.json()
        clients = {"alpha": (bazaar.a, bazaar.a_id), "beta": (bazaar.b, bazaar.b_id)}
        for part in self.order["seller_orders"]:
            client, seller_id = clients[part["store_slug"]]
            base = f"/seller/{seller_id}/orders/{part['id']}"
            for step in ("confirm", "ready"):
                assert client.post(f"{base}/{step}").status_code == 200
            code = self.part(part["store_slug"])["handover_code"]
            assert client.post(f"{base}/handover", json={"code": code}).status_code == 200
            if complete:
                done = self.buyer.post(
                    f"/me/orders/{self.order['id']}/seller-orders/{part['id']}/confirm-received"
                )
                assert done.status_code == 200, done.text

    def part(self, store: str) -> dict[str, Any]:
        mine = self.buyer.get(f"/me/orders/{self.order['id']}").json()
        return next(p for p in mine["seller_orders"] if p["store_slug"] == store)

    def items(self) -> list[str]:
        mine = self.buyer.get(f"/me/orders/{self.order['id']}").json()
        return [item["id"] for part in mine["seller_orders"] for item in part["items"]]

    def review(self, item_id: str, **body: Any) -> Any:
        payload = {"product_rating": 4, "seller_rating": 5, "body": "", **body}
        return self.buyer.post(
            f"/me/orders/{self.order['id']}/items/{item_id}/review", json=payload
        )


def _recount() -> None:
    run_once(datetime.now(UTC), jobs=NO_JOBS)


def _public(bazaar: Bazaar) -> dict[str, Any]:
    response = ApiClient().get(f"/catalog/products/{bazaar.product['slug']}/reviews")
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_a_completed_items_buyer_reviews_it_once_and_the_totals_follow(
    bazaar: Bazaar, db: DbSession
) -> None:
    waiting = Bought(bazaar, [(bazaar.a128, 1)], complete=False)
    (item,) = waiting.items()
    # Handed over but not yet completed: not yet.
    assert error_code(waiting.review(item)) == "review_not_open"
    assert waiting.buyer.get("/me/reviews/pending").json() == []

    bought = Bought(bazaar, [(bazaar.a128, 2), (bazaar.b128, 1)])
    pending = bought.buyer.get("/me/reviews/pending").json()
    assert {(p["store_slug"], p["order_code"]) for p in pending} == {
        ("alpha", bought.order["code"]), ("beta", bought.order["code"]),
    }  # fmt: skip
    alpha_item = next(p["order_item_id"] for p in pending if p["store_slug"] == "alpha")
    written = bought.review(alpha_item, product_rating=4, seller_rating=5, body="Works well.")
    assert written.status_code == 201, written.text
    assert (written.json()["status"], written.json()["order_code"]) == (
        "published", bought.order["code"],
    )  # fmt: skip
    assert error_code(bought.review(alpha_item)) == "review_exists"
    assert [p["store_slug"] for p in bought.buyer.get("/me/reviews/pending").json()] == ["beta"]

    # Shown at once; the totals follow when the worker has recounted.
    page = _public(bazaar)
    (shown,) = page["reviews"]
    assert (shown["body"], shown["store_slug"], shown["product_rating"]) == (
        "Works well.",
        "alpha",
        4,
    )
    assert set(shown) == {
        "id",
        "product_rating",
        "seller_rating",
        "body",
        "variant_label",
        "store_slug",
        "created_at",
        "seller_reply",
        "seller_replied_at",
    }  # fmt: skip  -- no name, phone or order code of the buyer
    assert page["summary"]["count"] == 0
    _recount()
    assert _public(bazaar)["summary"] == {
        "count": 1, "average": 4.0, "stars": {"1": 0, "2": 0, "3": 0, "4": 1, "5": 0},
    }  # fmt: skip
    store = ApiClient().get("/catalog/stores/alpha/reviews").json()
    assert (store["summary"]["count"], store["summary"]["average"]) == (1, 5.0)
    assert ApiClient().get("/catalog/stores/beta/reviews").json()["summary"]["count"] == 0
    # The store's members who may answer were told.
    db.rollback()
    told = db.scalars(
        select(Notification.template).where(Notification.template == "review.received_for_seller")
    ).all()
    assert len(told) == 1


def test_only_the_buyer_inside_the_window_and_never_the_stores_own_people(
    bazaar: Bazaar, db: DbSession
) -> None:
    bought = Bought(bazaar, [(bazaar.a128, 1)])
    (item,) = bought.items()
    stranger, _ = bazaar.buyer()
    refused = stranger.post(
        f"/me/orders/{bought.order['id']}/items/{item}/review",
        json={"product_rating": 1, "seller_rating": 1},
    )
    assert error_code(refused) == "order_not_found"
    assert error_code(bazaar.staff.post(
        f"/me/orders/{bought.order['id']}/items/{item}/review",
        json={"product_rating": 1, "seller_rating": 1},
    )) == "customer_session_required"  # fmt: skip

    # The window: closed after `reviews.window_days`.
    user = db.scalar(select(User).where(User.phone == "+251911555001"))
    assert user is not None
    later = datetime.now(UTC) + timedelta(days=61)
    with pytest.raises(Conflict) as closed:
        reviews.write_review(db, user, uuid.UUID(bought.order["id"]), uuid.UUID(item),
                             product_rating=5, seller_rating=5, body="", now=later)  # fmt: skip
    assert closed.value.code == "review_window_closed"
    db.rollback()

    # A buyer who later joins the store cannot review it.
    db.add(SellerMember(seller_id=uuid.UUID(bazaar.a_id), user_id=user.id, role="manager"))
    db.commit()
    assert error_code(bought.review(item)) == "own_store_review"


def test_suspicious_reviews_wait_for_staff_and_are_never_counted_meanwhile(
    bazaar: Bazaar, db: DbSession
) -> None:
    """H.4: contact details in the text, or many reviews of one seller."""
    settings_store.set_setting(db, "reviews.hold_after_same_seller", 1)
    db.commit()
    bought = Bought(bazaar, [(bazaar.a128, 1), (bazaar.a256, 1), (bazaar.b128, 1)])
    alpha_items = [p["order_item_id"] for p in bought.buyer.get("/me/reviews/pending").json()
                   if p["store_slug"] == "alpha"]  # fmt: skip
    beta_item = next(p["order_item_id"] for p in bought.buyer.get("/me/reviews/pending").json()
                     if p["store_slug"] == "beta")  # fmt: skip
    first = bought.review(alpha_items[0], body="Good phone.")
    second = bought.review(alpha_items[1], body="Also good.")
    contact = bought.review(beta_item, body="Cheaper if you call 0911 22 33 44 directly")
    assert first.json()["status"] == "published"
    assert (second.json()["status"], second.json()["held_reason"]) == (
        "held", "many_reviews_of_one_seller",
    )  # fmt: skip
    assert (contact.json()["status"], contact.json()["held_reason"]) == ("held", "contact_details")
    _recount()
    assert [r["body"] for r in _public(bazaar)["reviews"]] == ["Good phone."]
    assert _public(bazaar)["summary"]["count"] == 1
    # The store does not see a held review yet.
    assert [r["body"] for r in bazaar.b.get(f"/seller/{bazaar.b_id}/reviews").json()] == []

    support = staff_client(db, "0911000300", StaffRole.SUPPORT)
    queue = support.get("/admin/reviews").json()
    assert {r["held_reason"] for r in queue} == {"many_reviews_of_one_seller", "contact_details"}
    published = support.post(
        f"/admin/reviews/{second.json()['id']}/moderate",
        json={"action": "publish", "reason": "A real second purchase"},
    )
    assert published.json()["status"] == "published"
    hidden = support.post(
        f"/admin/reviews/{contact.json()['id']}/moderate",
        json={"action": "hide", "reason": "Moves buyers off MarkX"},
    )
    assert (hidden.json()["status"], hidden.json()["moderation_reason"]) == (
        "hidden", "Moves buyers off MarkX",
    )  # fmt: skip
    _recount()
    assert _public(bazaar)["summary"]["count"] == 2
    db.rollback()
    actions = db.scalars(
        select(AuditLog.action).where(AuditLog.target_type == "review").order_by(AuditLog.id)
    ).all()
    assert actions == ["review.publish", "review.hide"]


def test_a_buyer_writes_only_so_many_reviews_a_day(bazaar: Bazaar, db: DbSession) -> None:
    settings_store.set_setting(db, "reviews.per_buyer_per_day", 1)
    db.commit()
    bought = Bought(bazaar, [(bazaar.a128, 1), (bazaar.b128, 1)])
    first, second = bought.items()
    assert bought.review(first).status_code == 201
    over = bought.review(second)
    assert over.status_code == 429
    assert error_code(over) == "review_limit"


def test_the_seller_replies_once_and_the_buyer_edits_until_then(
    bazaar: Bazaar, db: DbSession
) -> None:
    bought = Bought(bazaar, [(bazaar.a128, 1)])
    (item,) = bought.items()
    review = bought.review(item, product_rating=2, body="Scratched.").json()
    edited = bought.buyer.put(
        f"/me/reviews/{review['id']}", json={"product_rating": 3, "seller_rating": 4,
                                             "body": "Scratched, but they swapped it."},
    )  # fmt: skip
    assert edited.status_code == 200, edited.text
    assert edited.json()["product_rating"] == 3

    # Beta cannot see or answer Alpha's review, even through Alpha's id.
    assert bazaar.b.get(f"/seller/{bazaar.b_id}/reviews").json() == []
    stolen = bazaar.b.post(f"/seller/{bazaar.b_id}/reviews/{review['id']}/reply",
                           json={"body": "Not ours"})  # fmt: skip
    assert stolen.status_code == 404
    assert bazaar.b.post(f"/seller/{bazaar.a_id}/reviews/{review['id']}/reply",
                         json={"body": "x"}).status_code == 404  # fmt: skip

    answered = bazaar.a.post(f"/seller/{bazaar.a_id}/reviews/{review['id']}/reply",
                             json={"body": "Sorry, glad we could swap it."})  # fmt: skip
    assert answered.status_code == 200, answered.text
    assert answered.json()["seller_reply"] == "Sorry, glad we could swap it."
    assert answered.json()["order_code"] is None  # the store never sees the order code
    late = bought.buyer.put(f"/me/reviews/{review['id']}",
                            json={"product_rating": 1, "seller_rating": 1, "body": "x"})  # fmt: skip
    assert error_code(late) == "review_answered"
    db.rollback()
    told = db.scalars(
        select(Notification.template).where(Notification.template == "review.seller_replied")
    ).all()
    assert len(told) == 1
    (shown,) = _public(bazaar)["reviews"]
    assert shown["seller_reply"] == "Sorry, glad we could swap it."


def test_staff_moderation_follows_c4_and_hidden_reviews_leave_the_totals(
    bazaar: Bazaar, db: DbSession
) -> None:
    bought = Bought(bazaar, [(bazaar.a128, 1)])
    (item,) = bought.items()
    review = bought.review(item, product_rating=1, body="Bad.").json()
    _recount()
    assert _public(bazaar)["summary"]["count"] == 1
    finance = staff_client(db, "0911000301", StaffRole.FINANCE)
    assert finance.get("/admin/reviews").status_code == 403
    catalogue = staff_client(db, "0911000302", StaffRole.CATALOGUE)
    no_reason = catalogue.post(f"/admin/reviews/{review['id']}/moderate", json={"action": "hide"})
    assert no_reason.status_code == 422
    hidden = catalogue.post(f"/admin/reviews/{review['id']}/moderate",
                            json={"action": "hide", "reason": "Abusive language"})  # fmt: skip
    assert hidden.status_code == 200
    assert _public(bazaar)["reviews"] == []
    _recount()
    assert _public(bazaar)["summary"]["count"] == 0
    # The buyer sees what happened; a hidden review cannot be edited back.
    (mine,) = bought.buyer.get("/me/reviews").json()
    assert (mine["status"], mine["moderation_reason"]) == ("hidden", "Abusive language")
    again = bought.buyer.put(f"/me/reviews/{review['id']}",
                             json={"product_rating": 5, "seller_rating": 5, "body": ""})  # fmt: skip
    assert error_code(again) == "review_hidden"
    # A store can reply only to a published review, and has no way to remove one.
    reply = bazaar.a.post(f"/seller/{bazaar.a_id}/reviews/{review['id']}/reply",
                          json={"body": "Hm"})  # fmt: skip
    assert error_code(reply) == "review_not_published"
    assert bazaar.a.delete(f"/seller/{bazaar.a_id}/reviews/{review['id']}").status_code in (
        404,
        405,
    )


def test_the_daily_recount_repairs_any_total(
    bazaar: Bazaar, db: DbSession, migrator_engine: Engine
) -> None:
    bought = Bought(bazaar, [(bazaar.a128, 1)])
    (item,) = bought.items()
    bought.review(item, product_rating=5)
    _recount()
    with migrator_engine.begin() as connection:
        connection.execute(
            text("update rating_summaries set review_count = 2, rating_sum = 6, count_3 = 1, "
                 "count_5 = 1 where subject_type = 'product'")
        )  # fmt: skip
    assert _public(bazaar)["summary"]["count"] == 2
    report = run_once(datetime.now(UTC))
    assert next(o for o in report.jobs if o.name == "reviews.recount_all").result == 2
    db.rollback()
    (product,) = db.scalars(
        select(RatingSummary).where(RatingSummary.subject_type == "product")
    ).all()
    assert (product.review_count, product.rating_sum, product.count_5) == (1, 5, 1)


def test_each_reader_is_told_what_they_may_do_with_a_review(bazaar: Bazaar, db: DbSession) -> None:
    """`can_edit` and `can_reply` (D-072) follow the service's own rules, so
    the web app shows a form only where the API would accept it."""
    bought = Bought(bazaar, [(bazaar.a128, 1), (bazaar.a256, 1)])
    first_item, second_item = bought.items()
    written = bought.review(first_item, body="Fine.").json()
    assert (written["can_edit"], written["can_reply"]) == (True, False)
    (seen,) = bazaar.a.get(f"/seller/{bazaar.a_id}/reviews").json()
    assert (seen["can_edit"], seen["can_reply"]) == (False, True)

    # Answered: the buyer may no longer change it; the store may reword.
    answered = bazaar.a.post(
        f"/seller/{bazaar.a_id}/reviews/{written['id']}/reply", json={"body": "Thank you."}
    ).json()
    assert (answered["can_edit"], answered["can_reply"]) == (False, True)
    (mine,) = bought.buyer.get("/me/reviews").json()
    assert (mine["can_edit"], mine["can_reply"]) == (False, False)
    assert error_code(bought.buyer.put(
        f"/me/reviews/{written['id']}", json={"product_rating": 1, "seller_rating": 1}
    )) == "review_answered"  # fmt: skip

    # Hidden by staff: nobody may act on it; staff never get the buyer's powers.
    other = bought.review(second_item, body="Rude words.").json()
    support = staff_client(db, "0911000303", StaffRole.SUPPORT)
    hidden = support.post(
        f"/admin/reviews/{other['id']}/moderate", json={"action": "hide", "reason": "Rude"}
    ).json()
    assert (hidden["can_edit"], hidden["can_reply"]) == (False, False)
    by_id = {r["id"]: r for r in bought.buyer.get("/me/reviews").json()}
    assert by_id[other["id"]]["can_edit"] is False
    store_view = {r["id"]: r for r in bazaar.a.get(f"/seller/{bazaar.a_id}/reviews").json()}
    assert store_view[other["id"]]["can_reply"] is False
    assert error_code(bazaar.a.post(
        f"/seller/{bazaar.a_id}/reviews/{other['id']}/reply", json={"body": "No"}
    )) == "review_not_published"  # fmt: skip


def test_the_buyer_is_told_when_the_window_to_change_a_review_has_closed(
    bazaar: Bazaar, db: DbSession
) -> None:
    bought = Bought(bazaar, [(bazaar.a128, 1)])
    (item,) = bought.items()
    written = bought.review(item).json()
    assert written["can_edit"] is True
    settings_store.set_setting(db, "reviews.window_days", 1)
    db.execute(
        text("update seller_orders set completed_at = completed_at - interval '2 days' "
             "where order_id = :order"),
        {"order": bought.order["id"]},
    )  # fmt: skip
    db.commit()
    (mine,) = bought.buyer.get("/me/reviews").json()
    assert mine["can_edit"] is False
    refused = bought.buyer.put(
        f"/me/reviews/{written['id']}", json={"product_rating": 1, "seller_rating": 1}
    )
    assert error_code(refused) == "review_window_closed"


def test_search_filters_by_the_products_rating(bazaar: Bazaar) -> None:
    """D.8's rating filter (D-080): the product's average from its published
    reviews; a product nobody rated is left out while the filter is on."""

    def slugs(min_rating: int) -> list[str]:
        found = ApiClient().get("/search", params={"q": "", "min_rating": min_rating})
        assert found.status_code == 200, found.text
        return [r["slug"] for r in found.json()["results"]]

    _recount()
    assert bazaar.product["slug"] not in slugs(1)
    bought = Bought(bazaar, [(bazaar.a128, 1)])
    (item,) = bought.items()
    assert bought.review(item, product_rating=4).status_code == 201
    _recount()
    assert bazaar.product["slug"] in slugs(4)
    assert bazaar.product["slug"] not in slugs(5)
    assert ApiClient().get("/search", params={"min_rating": 6}).status_code == 422
