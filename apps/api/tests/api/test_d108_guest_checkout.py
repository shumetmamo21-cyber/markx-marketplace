"""Guest checkout (C-07; D-108), through the real API.

Sign-in is Telegram only (SI-1), so a buyer without Telegram, or anyone
while Telegram is blocked, orders as a guest with a name, a delivery address
and a phone number. The founder's rules, each proven here:

* the number is not confirmed, so a guest order never opens, joins or
  reveals the account that has that number;
* pay at the door only;
* the buying limits and the bot check apply, counted per phone number and
  per network address, and a guest always counts as a brand-new buyer;
* the guest gets the secure tracking link and nothing more;
* the shop sees exactly what it sees for a signed-in buyer.

Every test here fails on the code before D-108: the guest routes, settings
and columns do not exist there.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import Session as UserSession
from markx.accounts.models import StaffRole, User
from markx.core import botcheck, ratelimit, settings_store
from markx.core.config import Config, get_config
from markx.core.db import session_scope
from markx.notifications.models import Notification
from markx.orders import service
from markx.orders.models import Order, SellerOrder
from tests.bazaar import Bazaar, assert_stock_is_consistent, stock
from tests.conftest import ApiClient, error_code
from tests.factories import add_to_cart, address_body, checkout, new_idempotency_key, staff_client

GUEST_PHONE = "0911777001"
GUEST_E164 = "+251911777001"
RIDER = {"alpha": "seller_rider"}


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def _guest(bazaar: Bazaar, **overrides: Any) -> dict[str, Any]:
    return {
        "recipient_name": "Guest Buyer",
        "phone": GUEST_PHONE,
        "delivery_area_id": bazaar.area_id,
        "landmark": "Next to the Bole post office, green door",
        "driver_notes": "Call when you are at the door",
        **overrides,
    }


def _choices(deliveries: dict[str, str]) -> list[dict[str, str]]:
    return [{"store_slug": slug, "method": method} for slug, method in deliveries.items()]


def _quote(
    client: ApiClient, bazaar: Bazaar, deliveries: dict[str, str] = RIDER, **guest: Any
) -> Any:
    return client.post(
        "/checkout/guest/quote",
        json={"guest": _guest(bazaar, **guest), "deliveries": _choices(deliveries)},
    )


def _place(
    client: ApiClient,
    bazaar: Bazaar,
    deliveries: dict[str, str] = RIDER,
    *,
    key: str | None = None,
    bot_token: str | None = "solved",  # noqa: S107  (the fake check's "person", not a secret)
    payment_method: str = "cash",
    expected_total: int | None = None,
    lang: str = "en",
    **guest: Any,
) -> Any:
    """Quote, then place, as the guest checkout page does."""
    if expected_total is None:
        quote = _quote(client, bazaar, deliveries, **guest)
        assert quote.status_code == 200, quote.text
        expected_total = int(quote.json()["grand_total_santim"])
    return client.post(
        "/checkout/guest",
        params={"lang": lang},
        json={
            "guest": _guest(bazaar, **guest),
            "deliveries": _choices(deliveries),
            "payment_method": payment_method,
            "expected_total_santim": expected_total,
            "idempotency_key": key or new_idempotency_key(),
            "bot_token": bot_token,
        },
    )


def _visitor(ip: str = "203.0.113.10") -> ApiClient:
    return ApiClient(ip=ip)


def _guest_order(
    bazaar: Bazaar,
    *,
    offer: str = "a128",
    quantity: int = 1,
    ip: str = "203.0.113.10",
    **guest: Any,
) -> tuple[ApiClient, dict[str, Any]]:
    visitor = _visitor(ip)
    add_to_cart(visitor, getattr(bazaar, offer)["id"], quantity)
    placed = _place(visitor, bazaar, **guest)
    assert placed.status_code == 201, placed.text
    return visitor, dict(placed.json())


def _split(path: str) -> tuple[str, dict[str, str]]:
    route, _, query = path.removeprefix("/api/v1").partition("?")
    return route, dict(pair.split("=") for pair in query.split("&"))


def _track(path: str, lang: str = "en") -> dict[str, Any]:
    route, params = _split(path)
    page = ApiClient().get(route, params={**params, "lang": lang})
    assert page.status_code == 200, page.text
    return dict(page.json())


def _stored(db: DbSession, code: str) -> Order:
    db.rollback()
    order = db.scalar(select(Order).where(Order.code == code))
    assert order is not None
    return order


def _alpha_part(db: DbSession, order: Order) -> SellerOrder:
    part = db.scalar(select(SellerOrder).where(SellerOrder.order_id == order.id))
    assert part is not None
    return part


# -- what a guest gets ---------------------------------------------------------------------------


def test_the_guest_terms_say_what_a_guest_may_do(bazaar: Bazaar) -> None:
    terms = _visitor().get("/checkout/guest/terms")
    assert terms.status_code == 200, terms.text
    assert terms.json() == {
        "enabled": True,
        "max_order_value_santim": 5_000_000,
        "shop_collection": False,
    }


def test_a_guest_orders_with_a_name_an_address_and_a_phone_and_gets_only_the_tracking_link(
    bazaar: Bazaar, db: DbSession
) -> None:
    users_before = db.scalar(select(func.count()).select_from(User))
    sessions_before = db.scalar(select(func.count()).select_from(UserSession))
    visitor = _visitor()
    add_to_cart(visitor, bazaar.a128["id"], 2)
    placed = _place(visitor, bazaar)
    assert placed.status_code == 201, placed.text
    body = placed.json()
    # The secure tracking link and nothing more.
    assert set(body) == {"order_code", "tracking_path", "tracking_expires_at"}
    assert re.fullmatch(r"MX-[34679ACDEFGHJKMNPQRTUVWXY]{6}", body["order_code"])
    assert re.fullmatch(
        r"/api/v1/track/[0-9a-f-]{36}\?expires=\d+&signature=[A-Za-z0-9_-]{43}",
        body["tracking_path"],
    )
    assert placed.headers["cache-control"] == "no-store"
    # No account, no session, no sign-in.
    assert "markx_session" not in visitor.http.cookies
    assert visitor.get("/me").status_code == 401
    db.rollback()
    assert db.scalar(select(func.count()).select_from(User)) == users_before
    assert db.scalar(select(func.count()).select_from(UserSession)) == sessions_before
    order = _stored(db, body["order_code"])
    assert order.buyer_user_id is None
    assert order.guest_phone == GUEST_E164
    assert order.payment_mode == "direct"
    assert order.language == "en"
    assert order.guest_network_hash is not None
    assert len(order.guest_network_hash) == 32
    assert order.guest_browser_hash is not None
    assert len(order.guest_browser_hash) == 32
    assert order.address_snapshot["recipient_name"] == "Guest Buyer"
    assert order.address_snapshot["phone"] == GUEST_E164
    assert order.address_snapshot["address_id"] is None
    assert order.address_snapshot["gate_photo_id"] is None
    # The network address itself is not kept, only its keyed hash.
    assert "203.0.113.10" not in str(order.address_snapshot)
    assert order.guest_network_hash == service.guest_network_hash("203.0.113.10")
    # The link opens the order, as for a signed-in buyer, with no action.
    tracked = _track(body["tracking_path"])
    assert tracked["code"] == body["order_code"]
    assert tracked["is_guest"] is True
    assert tracked["status"] == "placed"
    assert tracked["grand_total_santim"] == 3_715_000
    assert tracked["tracking_path"] is None
    assert set(tracked["address"]) == {
        "zone_code", "zone_name_am", "zone_name_en", "area_name_am", "area_name_en", "city",
    }  # fmt: skip
    part = tracked["seller_orders"][0]
    assert (part["can_cancel"], part["can_confirm_received"], part["can_report_problem"]) == (
        False,
        False,
        False,
    )
    assert part["handover_code"] is None  # not before the parcel is ready
    # The cart is empty after the order.
    assert visitor.get("/cart").json()["line_count"] == 0


# -- the number is not confirmed: never open, join or reveal an account ----------------------------


def test_a_guest_using_the_number_of_an_existing_account_sees_nothing_of_it(
    bazaar: Bazaar, db: DbSession
) -> None:
    # An account has the number, a name, a saved address and an open order.
    holder, holder_address = bazaar.buyer(
        GUEST_PHONE, recipient_name="Account Holder Tigist", landmark="The holder's secret gate"
    )
    assert holder.patch("/me", json={"name": "Account Holder Tigist"}).status_code == 200
    add_to_cart(holder, bazaar.a256["id"], 1)
    own = checkout(holder, holder_address, RIDER)
    assert own.status_code == 201, own.text
    holder_order = own.json()
    holder_me = holder.get("/me").json()
    db.rollback()
    holder_id = uuid.UUID(holder_me["id"])
    notes_before = db.scalar(
        select(func.count()).select_from(Notification).where(Notification.user_id == holder_id)
    )
    users_before = db.scalar(select(func.count()).select_from(User))

    # A stranger orders as a guest with the same number. The account's open
    # order does not count against the guest: with the new-buyer cap of one
    # open order, counting it would refuse the guest and so reveal it.
    stranger, placed = _guest_order(bazaar, recipient_name="Someone Else Entirely")
    # A second guest, same goods, with a number nobody has.
    _, unused = _guest_order(bazaar, phone="0911777099", ip="203.0.113.11")

    # What the guest was told: no account, its name, address or orders.
    secrets = (
        "Account Holder", "Tigist", "holder's secret gate", holder_order["code"],
        holder_order["id"], holder_me["id"],
    )  # fmt: skip
    guest_view = _track(placed["tracking_path"])
    for page in (str(placed), str(guest_view)):
        for secret in secrets:
            assert secret not in page, secret
    # No oracle: the guest with the account's number is answered exactly as
    # the guest with an unused number, but for the order's own identifiers.
    assert set(placed) == set(unused)
    assert _masked(guest_view) == _masked(_track(unused["tracking_path"]))
    assert stranger.get("/me").status_code == 401
    assert "markx_session" not in stranger.http.cookies

    # Nothing was opened, joined or changed on the account.
    db.rollback()
    assert db.scalar(select(func.count()).select_from(User)) == users_before
    holder_row = db.get(User, holder_id)
    assert holder_row is not None
    assert holder_row.name == "Account Holder Tigist"
    guest_order = _stored(db, placed["order_code"])
    assert guest_order.buyer_user_id is None
    listed = [o["code"] for o in holder.get("/me/orders").json()]
    assert listed == [holder_order["code"]]
    assert holder.get(f"/me/orders/{guest_order.id}").status_code == 404
    assert service.open_order_count(db, holder_id) == 1
    assert (
        db.scalar(
            select(func.count()).select_from(Notification).where(Notification.user_id == holder_id)
        )
        == notes_before
    )
    # The account holder signs in again: still only their own order.
    again = ApiClient()
    again.sign_in(GUEST_PHONE)
    assert [o["code"] for o in again.get("/me/orders").json()] == [holder_order["code"]]


def _masked(view: dict[str, Any]) -> Any:
    """A tracking view with the order's own identifiers and times taken out."""
    volatile = {"id", "code", "created_at", "response_deadline", "payment_reference", "occurred_at"}

    def mask(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: ("*" if k in volatile else mask(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [mask(v) for v in value]
        return value

    return mask(view)


def test_a_number_used_only_by_guests_gives_a_new_account_with_nothing_of_theirs(
    bazaar: Bazaar, db: DbSession
) -> None:
    _, placed = _guest_order(bazaar, phone="0911777002", recipient_name="Guest Selam")
    person = ApiClient()
    person.sign_in("0911777002")
    assert person.get("/me/orders").json() == []
    me = person.get("/me").json()
    assert me["name"] in (None, "")
    db.rollback()
    assert _stored(db, placed["order_code"]).buyer_user_id is None
    assert (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == uuid.UUID(me["id"]))
            .where(Notification.template.like("order.%"))
        )
        == 0
    )


def test_guest_orders_and_an_accounts_orders_never_count_against_each_other(
    bazaar: Bazaar, db: DbSession
) -> None:
    # Guest orders with a number do not hold back the account that has it.
    _guest_order(bazaar)
    holder, address = bazaar.buyer(GUEST_PHONE)
    for offer in ("a128", "a256", "b128"):
        add_to_cart(holder, getattr(bazaar, offer)["id"], 1)
        deliveries = {"beta": "shop_collection"} if offer == "b128" else RIDER
        placed = checkout(holder, address, deliveries)
        assert placed.status_code == 201, placed.text  # three open orders, as for anyone
    # And the account's three open orders do not hold back a guest with its
    # number: the guest's own first order went through above, and a guest
    # from another number and address still orders.
    _guest_order(bazaar, phone="0911777003", ip="203.0.113.12")


# -- pay at the door only ----------------------------------------------------------------------------


def test_a_guest_pays_at_the_door_only(bazaar: Bazaar, db: DbSession) -> None:
    visitor = _visitor()
    add_to_cart(visitor, bazaar.a128["id"], 1)
    # The request has no way to choose another payment mode.
    quote = _quote(visitor, bazaar).json()
    sneaky = visitor.post(
        "/checkout/guest",
        json={
            "guest": _guest(bazaar), "deliveries": _choices(RIDER), "payment_method": "cash",
            "expected_total_santim": quote["grand_total_santim"],
            "idempotency_key": new_idempotency_key(), "payment_mode": "protected_prepay",
        },
    )  # fmt: skip
    assert sneaky.status_code == 422
    # Every Release 1 method is one the guest pays at the handover.
    for method in ("cash", "telebirr", "bank_transfer", "ethqr"):
        guest = _visitor(f"203.0.113.{20 + len(method)}")
        add_to_cart(guest, bazaar.a128["id"], 1)
        placed = _place(guest, bazaar, payment_method=method, phone=f"09117771{len(method):02d}")
        assert placed.status_code == 201, placed.text
        assert _stored(db, placed.json()["order_code"]).payment_mode == "direct"
    # The database refuses a guest order paid any other way.
    order = db.scalar(select(Order).where(Order.guest_phone.is_not(None)).limit(1))
    assert order is not None
    with pytest.raises(IntegrityError, match="ck_orders_guest_pays_at_the_door"):
        db.execute(
            update(Order).where(Order.id == order.id).values(payment_mode="protected_prepay")
        )
    db.rollback()


def test_a_guest_is_delivered_to_the_door_and_collection_waits_for_operations(
    bazaar: Bazaar, db: DbSession
) -> None:
    visitor = _visitor()
    add_to_cart(visitor, bazaar.a128["id"], 1)
    # Alpha offers collection too; a guest may not choose it.
    for response in (
        _quote(visitor, bazaar, {"alpha": "shop_collection"}),
        _place(visitor, bazaar, {"alpha": "shop_collection"}, expected_total=1_850_000),
    ):
        assert response.status_code == 409, response.text
        assert error_code(response) == "guest_collection_unavailable"
        assert response.json()["error"]["details"]["store_slugs"] == ["alpha"]
    # Beta only offers collection, so a guest cannot order from it.
    other = _visitor("203.0.113.30")
    add_to_cart(other, bazaar.b128["id"], 1)
    assert error_code(_quote(other, bazaar, {"beta": "shop_collection"})) == (
        "guest_collection_unavailable"
    )
    assert stock(db, bazaar.a128["id"]) == (5, 0)
    # Operations may allow collection; then it is paid at the shop on handover.
    settings_store.set_setting(db, "guest_checkout.shop_collection", True)
    db.commit()
    placed = _place(visitor, bazaar, {"alpha": "shop_collection"})
    assert placed.status_code == 201, placed.text


# -- a guest is always a brand-new buyer (AD-13) ------------------------------------------------------


def test_a_guest_always_counts_as_a_brand_new_buyer(bazaar: Bazaar, db: DbSession) -> None:
    # Signed-in accounts count as new for no days until the founder sets it...
    assert settings_store.get_int(db, "risk.new_account_days") == 0
    # ...but a guest always does: at most ETB 50,000 at the door.
    visitor = _visitor()
    add_to_cart(visitor, bazaar.a128["id"], 3)  # 3 × 18,500 + 150 = ETB 55,650
    for response in (
        _quote(visitor, bazaar),
        _place(visitor, bazaar, expected_total=5_565_000),
    ):
        assert response.status_code == 409, response.text
        assert error_code(response) == "new_buyer_order_too_large"
        assert response.json()["error"]["details"] == {"limit_santim": 5_000_000}
    assert stock(db, bazaar.a128["id"]) == (5, 0)
    add_to_cart(visitor, bazaar.a128["id"], 2)  # ETB 37,150
    assert _place(visitor, bazaar).status_code == 201
    # One open order per guest number, from any browser and any address.
    second = _visitor("203.0.113.40")
    add_to_cart(second, bazaar.a256["id"], 1)
    refused = _place(second, bazaar)
    assert refused.status_code == 409, refused.text
    assert error_code(refused) == "new_buyer_too_many_open_orders"
    assert refused.json()["error"]["details"] == {"limit": 1}
    settings_store.set_setting(db, "risk.new_account_max_open_orders", 2)
    db.commit()
    assert _place(second, bazaar).status_code == 201


# -- the buying limits, counted per phone number and per network address --------------------------------


def test_the_open_order_limit_counts_per_network_address(bazaar: Bazaar, db: DbSession) -> None:
    for n in range(3):  # three guests behind one address, three numbers
        _guest_order(bazaar, phone=f"091177720{n}", ip="203.0.113.50")
    fourth = _visitor("203.0.113.50")
    add_to_cart(fourth, bazaar.a128["id"], 1)
    refused = _place(fourth, bazaar, phone="0911777209")
    assert refused.status_code == 409, refused.text
    assert error_code(refused) == "guest_network_limit"
    assert refused.json()["error"]["details"] == {"limit_kind": "open_orders", "limit": 3}
    # Nothing of the other guests is named.
    for n in range(3):
        assert f"91177720{n}" not in refused.text
    # Another address is not affected; operations may raise the limit.
    elsewhere = _visitor("203.0.113.51")
    add_to_cart(elsewhere, bazaar.a128["id"], 1)
    assert _place(elsewhere, bazaar, phone="0911777209").status_code == 201
    settings_store.set_setting(db, "guest_checkout.max_open_orders_per_ip", 4)
    db.commit()
    assert _place(fourth, bazaar, phone="0911777208").status_code == 201


def test_the_existing_open_order_limit_still_applies_to_one_guest_number(
    bazaar: Bazaar, db: DbSession
) -> None:
    settings_store.set_setting(db, "risk.new_account_max_open_orders", 10)
    db.commit()
    for n in range(3):
        _guest_order(bazaar, ip=f"203.0.113.{60 + n}")
    fourth = _visitor("203.0.113.63")
    add_to_cart(fourth, bazaar.a128["id"], 1)
    refused = _place(fourth, bazaar)
    assert error_code(refused) == "too_many_open_orders"


def test_the_unit_limits_count_per_phone_number_and_per_network_address(
    bazaar: Bazaar, db: DbSession
) -> None:
    # Room for bigger orders, so the unit limits (5 of an offer, 10 of a shop) decide.
    settings_store.set_setting(db, "risk.new_account_max_order_value_santim", 100_000_000)
    settings_store.set_setting(db, "risk.new_account_max_open_orders", 10)
    db.commit()
    _guest_order(bazaar, quantity=3, ip="203.0.113.70")
    # The same number from another address: 3 + 3 > 5 of one offer.
    again = _visitor("203.0.113.71")
    add_to_cart(again, bazaar.a128["id"], 3)
    refused = _place(again, bazaar)
    assert error_code(refused) == "unconfirmed_offer_limit"
    # Another number from the first address: counted per address too.
    neighbour = _visitor("203.0.113.70")
    add_to_cart(neighbour, bazaar.a128["id"], 3)
    refused = _place(neighbour, bazaar, phone="0911777301")
    assert error_code(refused) == "guest_network_limit"
    assert refused.json()["error"]["details"] == {"limit_kind": "unconfirmed_offer", "limit": 5}
    # Two units fit under both.
    add_to_cart(neighbour, bazaar.a128["id"], 2)
    assert _place(neighbour, bazaar, phone="0911777301").status_code == 201
    assert_stock_is_consistent(db)


def test_the_order_value_cap_and_the_checkout_rate_apply_to_guests(
    bazaar: Bazaar, db: DbSession
) -> None:
    settings_store.set_setting(db, "orders.max_order_value_santim", 1_000_000)
    settings_store.set_setting(db, "guest_checkout.attempts_per_ip_per_hour", 2)
    db.commit()
    visitor = _visitor("203.0.113.80")
    add_to_cart(visitor, bazaar.a128["id"], 1)
    assert error_code(_place(visitor, bazaar)) == "order_too_large"
    assert error_code(_place(visitor, bazaar, phone="0911777401")) == "order_too_large"
    limited = _place(visitor, bazaar, phone="0911777402")
    assert limited.status_code == 429
    assert error_code(limited) == "rate_limited"
    assert ratelimit.current("checkout:guest:ip:203.0.113.80", timedelta(hours=1)) == 3


# -- the bot check -------------------------------------------------------------------------------------


def test_the_bot_check_runs_before_anything_is_held_counted_or_written(
    bazaar: Bazaar, db: DbSession
) -> None:
    visitor = _visitor("203.0.113.90")
    add_to_cart(visitor, bazaar.a128["id"], 1)
    refused = _place(visitor, bazaar, bot_token="bot")  # the fake check's robot
    assert refused.status_code == 403
    assert error_code(refused) == "bot_check_failed"
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Order)) == 0
    assert stock(db, bazaar.a128["id"]) == (5, 0)
    assert ratelimit.current("checkout:guest:ip:203.0.113.90", timedelta(hours=1)) == 0
    assert ratelimit.current(f"checkout:guest:phone:{GUEST_E164}", timedelta(hours=1)) == 0
    assert visitor.get("/cart").json()["line_count"] == 1


SECRET = "0x4-test-only-not-a-real-turnstile-secret"


class _Cloudflare:
    """Stands in for Siteverify: solved for one action, and records calls."""

    def __init__(self, action: str) -> None:
        self.action = action
        self.calls: list[dict[str, str]] = []

    def __call__(self, url: str, fields: dict[str, str], timeout: float) -> tuple[int, bytes]:
        import json

        self.calls.append(dict(fields))
        answer = {"success": True, "hostname": "testserver", "action": self.action}
        return 200, json.dumps(answer).encode()


def _turnstile(monkeypatch: pytest.MonkeyPatch, action: str) -> _Cloudflare:
    config = get_config().model_copy(
        update={
            "bot_check_provider": "turnstile",
            "turnstile_secret_key": Config(turnstile_secret_key=SECRET).turnstile_secret_key,
            "turnstile_site_key": "0x4-test-only-site-key",
            "turnstile_allowed_hostnames": "testserver",
        }
    )
    cloudflare = _Cloudflare(action)
    monkeypatch.setattr(botcheck, "get_config", lambda: config)
    monkeypatch.setattr(botcheck, "urllib_transport", cloudflare)
    return cloudflare


def test_turnstile_must_have_been_solved_for_a_guest_order_not_for_signing_in(
    bazaar: Bazaar, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed_in_widget = _turnstile(monkeypatch, botcheck.SIGN_IN_ACTION)
    visitor = _visitor("203.0.113.91")
    add_to_cart(visitor, bazaar.a128["id"], 1)
    refused = _place(visitor, bazaar, bot_token="test-only-token")
    assert error_code(refused) == "bot_check_failed"
    assert signed_in_widget.calls[0]["response"] == "test-only-token"
    assert signed_in_widget.calls[0]["remoteip"] == "203.0.113.91"
    guest_widget = _turnstile(monkeypatch, botcheck.GUEST_CHECKOUT_ACTION)
    assert _place(visitor, bazaar, bot_token="test-only-token").status_code == 201
    assert len(guest_widget.calls) == 1


# -- the same submission twice -------------------------------------------------------------------------


def test_the_same_submission_from_the_same_browser_makes_one_order(
    bazaar: Bazaar, db: DbSession
) -> None:
    visitor = _visitor()
    add_to_cart(visitor, bazaar.a128["id"], 1)
    key = new_idempotency_key()
    first = _place(visitor, bazaar, key=key)
    assert first.status_code == 201, first.text
    # A retry after a dropped connection: its used bot token is not checked again.
    repeat = _place(visitor, bazaar, key=key, bot_token="bot", expected_total=1_865_000)
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["order_code"] == first.json()["order_code"]
    # Another browser with the same key gets its own order, never the first.
    other = _visitor("203.0.113.92")
    add_to_cart(other, bazaar.a256["id"], 1)
    theirs = _place(other, bazaar, key=key, phone="0911777501")
    assert theirs.status_code == 201, theirs.text
    assert theirs.json()["order_code"] != first.json()["order_code"]
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Order)) == 2


# -- the tracking link, the handover code, and nothing more ----------------------------------------------


def test_the_guests_link_shows_the_handover_code_and_the_shop_hands_over_with_it(
    bazaar: Bazaar, db: DbSession
) -> None:
    _, placed = _guest_order(bazaar)
    order = _stored(db, placed["order_code"])
    part = _alpha_part(db, order)
    base = f"/seller/{bazaar.a_id}/orders/{part.id}"
    assert bazaar.a.post(f"{base}/confirm").status_code == 200
    assert _track(placed["tracking_path"])["seller_orders"][0]["handover_code"] is None
    assert bazaar.a.post(f"{base}/ready").status_code == 200
    dispatched = bazaar.a.post(
        f"{base}/dispatch", json={"rider_name": "Dawit", "rider_phone": "0922000111"}
    )
    assert dispatched.status_code == 200, dispatched.text
    tracked = _track(placed["tracking_path"])["seller_orders"][0]
    code = tracked["handover_code"]
    assert code is not None
    assert re.fullmatch(r"[0-9]{6}", code)
    assert tracked["shipment"]["rider_phone"] == "+251922000111"
    assert tracked["seller_contact"]["phone"] == "+251911000001"
    # Only the guest's link shows it: never the shop, never staff.
    assert code not in bazaar.a.get(base).text
    assert (
        bazaar.staff.get(f"/admin/orders/{placed['order_code']}").json()["seller_orders"][0][
            "handover_code"
        ]
        is None
    )
    # The rider takes the code at the door; the shop records the payment.
    handed = bazaar.a.post(f"{base}/handover", json={"code": code})
    assert handed.status_code == 200, handed.text
    assert handed.json()["status"] == "delivered"
    paid = bazaar.a.post(f"{base}/payment", json={"method": "cash"})
    assert paid.status_code == 200, paid.text
    after = _track(placed["tracking_path"])["seller_orders"][0]
    assert after["status"] == "delivered"
    assert after["handover_code"] is None
    # A guest cannot report a problem or confirm receipt: the window passes.
    assert after["can_report_problem"] is False
    assert after["can_confirm_received"] is False
    with session_scope() as session:
        done = service.complete_after_problem_window(
            session, now=datetime.now(UTC) + timedelta(days=4)
        )
    assert done == 1
    assert _track(placed["tracking_path"])["seller_orders"][0]["status"] == "completed"
    assert_stock_is_consistent(db)


def test_a_guest_is_told_nothing_but_by_the_link_and_the_life_cycle_runs_without_a_buyer(
    bazaar: Bazaar, db: DbSession
) -> None:
    _, declined = _guest_order(bazaar)
    _, expiring = _guest_order(bazaar, phone="0911777601", ip="203.0.113.93")
    first = _alpha_part(db, _stored(db, declined["order_code"]))
    assert (
        bazaar.a.post(
            f"/seller/{bazaar.a_id}/orders/{first.id}/decline",
            json={"reason": "Out of stock today"},
        ).status_code
        == 200
    )
    with session_scope() as session:
        expired = service.expire_unanswered_orders(
            session, now=datetime.now(UTC) + timedelta(days=7)
        )
    assert expired == 1
    assert _track(expiring["tracking_path"])["seller_orders"][0]["status"] == "expired"
    assert _track(declined["tracking_path"])["seller_orders"][0]["status"] == "declined"
    # Every order message went to the shop's people; none to a buyer.
    db.rollback()
    handlers = {
        uuid.UUID(row)
        for row in db.scalars(
            text("select user_id::text from seller_members where seller_id = :id"),
            {"id": bazaar.a_id},
        )
    }
    recipients = set(
        db.scalars(select(Notification.user_id).where(Notification.template.like("order.%")))
    )
    assert recipients == handlers
    assert_stock_is_consistent(db)
    assert stock(db, bazaar.a128["id"]) == (5, 0)


def test_a_guest_has_no_way_to_act_on_the_order(bazaar: Bazaar, db: DbSession) -> None:
    visitor, placed = _guest_order(bazaar)
    order = _stored(db, placed["order_code"])
    part = _alpha_part(db, order)
    actions = f"/me/orders/{order.id}/seller-orders/{part.id}"
    for response in (
        visitor.get(f"/me/orders/{order.id}"),
        visitor.get("/me/orders"),
        visitor.post(f"{actions}/cancel", json={}),
        visitor.post(f"{actions}/confirm-received"),
        visitor.post(
            f"{actions}/problem", json={"problem_type": "not_as_described", "description": "x" * 20}
        ),
    ):
        assert response.status_code == 401, response.text
    # The tracking page offers no action either, at any stage.
    part_view = _track(placed["tracking_path"])["seller_orders"][0]
    assert not any(
        part_view[flag] for flag in ("can_cancel", "can_confirm_received", "can_report_problem")
    )


# -- the shop sees exactly what it sees for a signed-in buyer -----------------------------------------------


_VOLATILE = {
    "id", "order_code", "placed_at", "response_deadline", "confirmed_at", "payment_reference",
    "occurred_at", "ready_at", "dispatched_at", "delivered_at", "seller_order_id",
    "first_order_at", "last_order_at",
}  # fmt: skip


def _shop_view(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("*" if k in _VOLATILE else _shop_view(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_shop_view(v) for v in value]
    return value


def test_the_shop_sees_a_guest_order_exactly_as_a_signed_in_buyers(
    bazaar: Bazaar, db: DbSession
) -> None:
    details = {
        "recipient_name": "Hana Tesfaye", "phone": "0911777701", "landmark": "Behind Edna Mall",
        "driver_notes": "The blue gate",
    }  # fmt: skip
    # A signed-in buyer (number 0911777700) whose saved address is exactly
    # what the guest types, delivery phone included.
    buyer = ApiClient()
    buyer.sign_in("0911777700")
    saved = buyer.post("/me/addresses", json=address_body(bazaar.area_id, **details))
    assert saved.status_code == 201, saved.text
    address = saved.json()["id"]
    add_to_cart(buyer, bazaar.a128["id"], 1)
    assert checkout(buyer, address, RIDER).status_code == 201
    _guest_order(bazaar, **details)
    rows = bazaar.a.get(f"/seller/{bazaar.a_id}/orders").json()
    assert len(rows) == 2
    guest_part, account_part = rows  # newest first
    assert _shop_view(guest_part) == _shop_view(account_part)
    assert guest_part["buyer"] is None  # not before the shop confirms (C.5)
    for row in rows:
        assert bazaar.a.post(f"/seller/{bazaar.a_id}/orders/{row['id']}/confirm").status_code == 200
    seen = [bazaar.a.get(f"/seller/{bazaar.a_id}/orders/{row['id']}").json() for row in rows]
    assert _shop_view(seen[0]) == _shop_view(seen[1])
    assert seen[0]["buyer"] == {
        "recipient_name": "Hana Tesfaye", "phone": "+251911777701", "phone2": None,
        "landmark": "Behind Edna Mall", "latitude": None, "longitude": None,
        "driver_notes": "The blue gate",
    }  # fmt: skip
    assert "is_guest" not in bazaar.a.get(f"/seller/{bazaar.a_id}/orders").text
    # The shop's customer list shows both orders the same way, by the number.
    customers = bazaar.a.get(f"/seller/{bazaar.a_id}/customers").json()
    assert [c["phone"] for c in customers] == ["+251911777701"]
    assert customers[0]["orders"] == 2
    recent = _shop_view(customers[0]["recent_orders"])
    assert recent[0] == recent[1]
    # The shop's people were told of both orders in the same words.
    db.rollback()
    placed_alerts = db.scalars(
        select(Notification).where(Notification.template == "order.placed_for_seller")
    ).all()
    assert len(placed_alerts) == 2
    assert {tuple(sorted(n.params)) for n in placed_alerts} == {
        ("order_code", "seller_id", "seller_order_id")
    }
    assert {n.user_id for n in placed_alerts} == {placed_alerts[0].user_id}


# -- switched off, and only for visitors ---------------------------------------------------------------------


def test_guest_checkout_can_be_switched_off_and_is_only_for_visitors(
    bazaar: Bazaar, db: DbSession
) -> None:
    visitor = _visitor()
    add_to_cart(visitor, bazaar.a128["id"], 1)
    settings_store.set_setting(db, "guest_checkout.enabled", False)
    db.commit()
    assert visitor.get("/checkout/guest/terms").json()["enabled"] is False
    for response in (_quote(visitor, bazaar), _place(visitor, bazaar, expected_total=1_865_000)):
        assert response.status_code == 403
        assert error_code(response) == "guest_checkout_off"
    settings_store.set_setting(db, "guest_checkout.enabled", True)
    db.commit()
    # A signed-in buyer checks out from their account, where their limits apply.
    buyer, _ = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 1)
    assert error_code(_quote(buyer, bazaar)) == "guest_checkout_signed_in"
    assert error_code(_place(buyer, bazaar, expected_total=1_865_000)) == "guest_checkout_signed_in"
    # Staff never shop with a staff session.
    staff = staff_client(db, "0911000299", StaffRole.OPERATIONS)
    assert error_code(_quote(staff, bazaar)) == "customer_session_required"
    # An empty or missing cart.
    assert error_code(_quote(_visitor("203.0.113.94"), bazaar)) == "cart_empty"
    db.rollback()
    assert (
        db.scalar(select(func.count()).select_from(Order).where(Order.guest_phone.is_not(None)))
        == 0
    )


def test_a_guests_details_are_checked_as_a_saved_address_is(bazaar: Bazaar) -> None:
    visitor = _visitor()
    add_to_cart(visitor, bazaar.a128["id"], 1)
    assert error_code(_quote(visitor, bazaar, phone="0611234567")) == "phone_invalid"
    assert error_code(_quote(visitor, bazaar, phone="+447911123456")) == "phone_invalid"
    assert error_code(_quote(visitor, bazaar, delivery_area_id=str(uuid.uuid4()))) == "area_unknown"
    assert error_code(_quote(visitor, bazaar, latitude=9.0)) == "map_pin_incomplete"
    assert _quote(visitor, bazaar, landmark="x").status_code == 422
    assert _quote(visitor, bazaar, recipient_name="").status_code == 422
    # The same fields as a saved address, so the web app's form fits both.
    assert set(_guest(bazaar)) <= set(address_body(bazaar.area_id)) | {"recipient_name"}


# -- the database's own rules ----------------------------------------------------------------------------------


def test_the_database_holds_the_guest_order_rules(bazaar: Bazaar, db: DbSession) -> None:
    _, placed = _guest_order(bazaar)
    order = _stored(db, placed["order_code"])
    some_user = db.scalar(select(User.id).limit(1))
    for values, constraint in (
        ({"buyer_user_id": some_user}, "ck_orders_one_buyer"),  # both an account and a guest
        # Neither: no account and no guest (the keys go with the guest).
        (
            {"guest_phone": None, "guest_network_hash": None, "guest_browser_hash": None},
            "ck_orders_one_buyer",
        ),
        ({"guest_phone": None}, "ck_orders_guest_keys_with_guest"),
        ({"guest_phone": "0911777001"}, "ck_orders_guest_phone_international_format"),
        ({"guest_network_hash": b"short"}, "ck_orders_guest_key_lengths"),
        ({"guest_browser_hash": None}, "ck_orders_guest_keys_with_guest"),
    ):
        with pytest.raises(IntegrityError, match=constraint):
            db.execute(update(Order).where(Order.id == order.id).values(**values))
        db.rollback()
    # One order per browser and key.
    clone = _stored(db, placed["order_code"])
    with pytest.raises(IntegrityError, match="uq_orders_guest_browser_idempotency_key"):
        db.execute(
            text(
                "insert into orders (id, code, guest_phone, guest_network_hash, "
                "guest_browser_hash, payment_mode, items_total_santim, delivery_total_santim, "
                "grand_total_santim, address_snapshot, delivery_zone_id, idempotency_key) "
                "select :id, 'MX-777777', guest_phone, guest_network_hash, guest_browser_hash, "
                "payment_mode, items_total_santim, delivery_total_santim, grand_total_santim, "
                "address_snapshot, delivery_zone_id, idempotency_key from orders where id = :src"
            ),
            {"id": uuid.uuid4(), "src": clone.id},
        )
    db.rollback()
