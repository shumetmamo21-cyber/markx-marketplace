"""Reports on listings, stores and reviews (blueprint C-30, AD-16, H.4; D-067):
anyone flags what they can see, once per person while it is open; staff
work the queue and resolve every report on a target with a note; the
reporters hear the outcome; nothing is deleted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.audit.models import AuditLog
from markx.core.db import session_scope
from markx.notifications.models import Notification
from markx.ops import service as ops
from markx.ops.models import OpsAlert
from markx.trust.models import Report
from tests.api.test_reviews import Bought
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.factories import make_product, staff_client


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def _report(client: ApiClient, target_type: str, reason: str = "counterfeit", **target: Any) -> Any:
    return client.post("/reports", json={"target_type": target_type, "reason": reason, **target})


def test_anyone_reports_what_they_can_see_and_nothing_else(bazaar: Bazaar) -> None:
    visitor = ApiClient()
    product = _report(visitor, "product", target_id=bazaar.product["id"], note="Box looks fake")
    assert product.status_code == 201, product.text
    assert set(product.json()) == {"id", "status", "created_at"}
    assert (
        _report(visitor, "offer", "wrong_information", target_id=bazaar.a128["id"]).status_code
        == 201
    )
    assert _report(visitor, "store", "fraud", store_slug="beta").status_code == 201
    bought = Bought(bazaar, [(bazaar.a128, 1)])
    (item,) = bought.items()
    review = bought.review(item, body="Fine.").json()
    assert _report(visitor, "review", "offensive", target_id=review["id"]).status_code == 201

    # Things a buyer cannot see cannot be reported (or probed for).
    draft = make_product(
        bazaar.staff, bazaar.catalog, model="3310", name_am="ኖኪያ 3310", name_en="Nokia 3310",
        status="draft", brand_id=None,
    )  # fmt: skip
    assert (
        error_code(_report(visitor, "product", target_id=draft["id"])) == "report_target_not_found"
    )
    taken_down = bazaar.staff.post(
        f"/admin/offers/{bazaar.b128['id']}/remove", json={"reason": "Counterfeit"}
    )
    assert taken_down.status_code == 200, taken_down.text
    assert error_code(_report(visitor, "offer", target_id=bazaar.b128["id"])) == (
        "report_target_not_found"
    )
    assert error_code(_report(visitor, "store", store_slug="no-such-store")) == (
        "report_target_not_found"
    )
    # A malformed report is refused before anything is looked up.
    assert (
        _report(
            visitor, "product", reason="i_dont_like_it", target_id=bazaar.product["id"]
        ).status_code
        == 422
    )
    assert _report(visitor, "product", store_slug="alpha").status_code == 422
    assert _report(visitor, "offer").status_code == 422
    # Staff use their own tools, not the public form.
    assert error_code(_report(bazaar.staff, "product", target_id=bazaar.product["id"])) == (
        "customer_session_required"
    )


def test_one_open_report_per_person_and_a_limit_per_address(bazaar: Bazaar) -> None:
    buyer, _ = bazaar.buyer()
    assert _report(buyer, "product", target_id=bazaar.product["id"]).status_code == 201
    again = _report(buyer, "product", "spam", target_id=bazaar.product["id"])
    assert again.status_code == 409
    assert error_code(again) == "already_reported"
    visitor = ApiClient(ip="198.51.100.20")
    for _ in range(10):
        assert _report(visitor, "store", store_slug="alpha").status_code == 201
    flood = _report(visitor, "store", store_slug="alpha")
    assert flood.status_code == 429


def test_staff_work_the_queue_and_resolve_every_report_on_a_target(
    bazaar: Bazaar, db: DbSession
) -> None:
    first, _ = bazaar.buyer()
    second, _ = bazaar.buyer()
    offer = bazaar.a128["id"]
    for client in (first, second, ApiClient()):
        assert _report(client, "offer", "counterfeit", target_id=offer).status_code == 201
    assert (
        _report(first, "product", "wrong_information", target_id=bazaar.product["id"]).status_code
        == 201
    )

    finance = staff_client(db, "0911000301", StaffRole.FINANCE)
    assert finance.get("/admin/reports").status_code == 403
    support = staff_client(db, "0911000300", StaffRole.SUPPORT)
    queue = support.get("/admin/reports").json()
    assert [row["target_type"] for row in queue] == ["offer", "offer", "offer", "product"]
    oldest = queue[0]
    assert (oldest["product_slug"], oldest["store_slug"], oldest["open_reports_on_target"]) == (
        bazaar.product["slug"], "alpha", 3,
    )  # fmt: skip
    assert [row["from_signed_in_person"] for row in queue[:3]] == [True, True, False]
    assert (
        support.get("/admin/reports", params={"target_type": "product"}).json()[0][
            "open_reports_on_target"
        ]
        == 1
    )

    closed = support.post(
        f"/admin/reports/{oldest['id']}/resolve",
        json={"outcome": "actioned", "note": "Offer taken down; the seller is asked for proof."},
    )
    assert closed.status_code == 200, closed.text
    assert [(r["status"], r["open_reports_on_target"]) for r in closed.json()] == [
        ("actioned", 0)
    ] * 3
    again = support.post(f"/admin/reports/{oldest['id']}/resolve",
                         json={"outcome": "dismissed", "note": "Again"})  # fmt: skip
    assert error_code(again) == "report_closed"
    assert [row["target_type"] for row in support.get("/admin/reports").json()] == ["product"]
    done = support.get("/admin/reports", params={"status": "actioned"}).json()
    assert len(done) == 3
    assert done[0]["resolution_note"].startswith("Offer taken down")

    db.rollback()
    (entry,) = db.scalars(select(AuditLog).where(AuditLog.action == "report.actioned"))
    assert len(entry.after["reports"]) == 3
    told = db.scalars(select(Notification).where(Notification.template == "report.resolved")).all()
    assert len(told) == 2  # the two signed-in reporters; the visitor cannot be told
    assert {n.params["outcome"] for n in told} == {"actioned"}

    # One report at a time, when staff choose.
    (product_report,) = support.get("/admin/reports").json()
    one = support.post(
        f"/admin/reports/{product_report['id']}/resolve",
        json={"outcome": "dismissed", "note": "The specifications are right.",
              "all_on_target": False},
    )  # fmt: skip
    assert [r["status"] for r in one.json()] == ["dismissed"]
    assert db.scalars(select(Report)).all()  # nothing was deleted


def test_reports_left_waiting_raise_an_alert(bazaar: Bazaar, db: DbSession) -> None:
    assert _report(ApiClient(), "store", "fraud", store_slug="alpha").status_code == 201
    with session_scope() as session:
        assert ops.watch(session, datetime.now(UTC)) == 0
        assert ops.watch(session, datetime.now(UTC) + timedelta(days=3)) == 1
    db.rollback()
    (alert,) = db.scalars(select(OpsAlert))
    assert alert.key == "reports.waiting"
    assert "1 report(s) on 1 listing(s)" in alert.summary
