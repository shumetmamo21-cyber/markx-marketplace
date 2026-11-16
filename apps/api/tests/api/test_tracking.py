"""The buyer's order page by secure link (blueprint D.14, C-10, P10).

The link cannot be guessed, needs no sign-in, shows only what the buyer
needs, and never the handover code.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from markx.core.errors import NotFound
from markx.notifications.models import Notification
from markx.orders import service
from markx.orders.models import Order
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.factories import add_to_cart, checkout


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def _placed(bazaar: Bazaar) -> tuple[ApiClient, dict[str, Any]]:
    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 2)
    add_to_cart(buyer, bazaar.b128["id"], 1)
    response = checkout(buyer, address_id, {"alpha": "seller_rider", "beta": "shop_collection"})
    assert response.status_code == 201, response.text
    return buyer, dict(response.json())


def _part(order: dict[str, Any], store: str) -> dict[str, Any]:
    return next(so for so in order["seller_orders"] if so["store_slug"] == store)


def _split(path: str) -> tuple[str, dict[str, str]]:
    route, _, query = path.removeprefix("/api/v1").partition("?")
    return route, dict(pair.split("=") for pair in query.split("&"))


def test_the_link_opens_the_order_without_sign_in_and_hides_what_it_must(
    bazaar: Bazaar, db: DbSession
) -> None:
    buyer, order = _placed(bazaar)
    # The buyer's own page carries the link, and so does the "placed" message
    # that goes out by Telegram or SMS.
    path = order["tracking_path"]
    assert re.fullmatch(
        r"/api/v1/track/[0-9a-f-]{36}\?expires=\d+&signature=[A-Za-z0-9_-]{43}", path
    )
    message = db.scalar(select(Notification).where(Notification.template == "order.placed"))
    assert message is not None
    assert message.params["tracking_path"].startswith(f"/api/v1/track/{order['id']}?")
    route, params = _split(path)

    visitor = ApiClient()
    page = visitor.get(route, params=params)
    assert page.status_code == 200, page.text
    assert page.headers["cache-control"] == "no-store"
    tracked = page.json()
    assert (tracked["code"], tracked["status"]) == (order["code"], "placed")
    assert tracked["grand_total_santim"] == 5_505_000
    assert tracked["tracking_path"] is None  # the page does not hand out more links
    # Where it goes, not to whom: no name, no phone, no pin, no notes.
    assert tracked["address"] == {
        "zone_code": "bole", "zone_name_am": tracked["address"]["zone_name_am"],
        "zone_name_en": tracked["address"]["zone_name_en"],
        "area_name_am": tracked["address"]["area_name_am"],
        "area_name_en": tracked["address"]["area_name_en"], "city": "Addis Ababa",
    }  # fmt: skip
    assert "Sara" not in page.text
    assert "+251911555001" not in page.text
    assert [i["quantity"] for i in _part(tracked, "alpha")["items"]] == [2]
    assert _part(tracked, "alpha")["seller_contact"] is None  # not before confirmation
    assert {so["can_cancel"] for so in tracked["seller_orders"]} == {False}

    # Alpha confirms, packs and dispatches: the timeline, the seller's and the
    # rider's contact appear; the code never does.
    alpha_id = _part(order, "alpha")["id"]
    base = f"/seller/{bazaar.a_id}/orders/{alpha_id}"
    assert bazaar.a.post(f"{base}/confirm").status_code == 200
    assert bazaar.a.post(f"{base}/ready").status_code == 200
    assert (
        bazaar.a.post(
            f"{base}/dispatch", json={"rider_name": "Dawit", "rider_phone": "0922000111"}
        ).status_code
        == 200
    )
    code = _part(buyer.get(f"/me/orders/{order['id']}").json(), "alpha")["handover_code"]
    assert code is not None
    page = visitor.get(route, params=params)
    alpha = _part(page.json(), "alpha")
    assert alpha["status"] == "out_for_delivery"
    assert alpha["handover_code"] is None
    assert code not in page.text
    assert alpha["seller_contact"]["phone"] == "+251911000001"
    assert alpha["shipment"]["rider_phone"] == "+251922000111"
    assert [e["status"] for e in alpha["shipment"]["events"]] == ["ready", "out_for_delivery"]
    assert [e["to_status"] for e in alpha["events"]] == [
        "placed",
        "confirmed",
        "ready",
        "out_for_delivery",
    ]
    assert alpha["can_confirm_received"] is False
    # The English page, as the message language may ask.
    english = visitor.get(route, params={**params, "lang": "en"}).json()
    assert _part(english, "alpha")["items"][0]["title"] == "Samsung Galaxy A16"


def test_a_forged_expired_or_retargeted_link_is_not_found(bazaar: Bazaar, db: DbSession) -> None:
    _, order = _placed(bazaar)
    _, other = _placed(bazaar)
    route, params = _split(order["tracking_path"])
    visitor = ApiClient()
    bad_signature = {
        **params,
        "signature": params["signature"][:-1] + ("A" if params["signature"][-1] != "A" else "B"),
    }
    assert visitor.get(route, params=bad_signature).status_code == 404
    assert error_code(visitor.get(route, params=bad_signature)) == "tracking_link_invalid"
    # A later expiry with the old signature, or the signature on another order.
    assert (
        visitor.get(
            route, params={**params, "expires": str(int(params["expires"]) + 1)}
        ).status_code
        == 404
    )
    other_route, _ = _split(other["tracking_path"])
    assert visitor.get(other_route, params=params).status_code == 404
    assert visitor.get(f"/track/{uuid.uuid4()}", params=params).status_code == 404
    assert visitor.get(route, params={"expires": params["expires"]}).status_code == 422
    # The same link, sixty-one days on, is dead; a fresh one from the page works.
    db.rollback()
    stored = db.get(Order, uuid.UUID(order["id"]))
    assert stored is not None
    late = datetime.now(UTC) + timedelta(days=61)
    with pytest.raises(NotFound) as expired:
        service.open_tracking_link(
            db, stored.id, expires=int(params["expires"]), signature=params["signature"], now=late
        )
    assert expired.value.code == "tracking_link_invalid"
    fresh = service.issue_tracking_link(stored, now=late)
    assert service.open_tracking_link(
        db, stored.id, expires=int(fresh.expires_at.timestamp()),
        signature=_split(fresh.path)[1]["signature"], now=late,
    ).id == stored.id  # fmt: skip
    # A link that claims to expire further ahead than any link is issued for is forged.
    far = int((datetime.now(UTC) + timedelta(days=90)).timestamp())
    with pytest.raises(NotFound) as forged:
        service.open_tracking_link(
            db, stored.id, expires=far, signature=service._tracking_signature(stored.id, far)
        )
    assert forged.value.code == "tracking_link_invalid"
    # Staff and sellers are not handed the buyer's link.
    assert bazaar.staff.get(f"/admin/orders/{order['code']}").json()["tracking_path"] is None
    assert "tracking_path" not in bazaar.a.get(f"/seller/{bazaar.a_id}/orders").text
