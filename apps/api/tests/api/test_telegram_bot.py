"""The seller bot and order messages in Telegram (D-102; blueprint S-07,
S-24, S-26, C-10, D.16).

Telegram is played as in `test_telegram_linking.py`: the webhook is called
the way Telegram would call it, with the test-only secret, and the bot's
answers are read from the webhook's reply. Messages MarkX starts itself go to
the fake push sender's file. Nothing is sent to or received from Telegram.
"""

from __future__ import annotations

import itertools
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from markx.accounts.models import User
from markx.core import settings_store
from markx.core.db import session_scope
from markx.notifications import texts as outside_texts
from markx.notifications.models import Notification, NotificationDelivery
from markx.notifications.push import read_dev_push_outbox
from markx.offers.models import Inventory, Offer
from markx.orders import service as orders
from markx.orders.models import Order, SellerOrder
from markx.performance import service as performance
from markx.sellers.models import Seller, SellerMember
from markx.telegram_bot import keyboards, products, texts
from markx.telegram_bot.service import offer_ref
from markx.worker.runner import run_once
from tests import telegram_play as tg
from tests.bazaar import A_PHONE, B_PHONE, Bazaar
from tests.conftest import ApiClient
from tests.factories import add_to_cart, checkout

NO_JOBS = ()
OWNER_TG = 720_000_001  # Alpha's owner
BETA_TG = 720_000_002  # Beta's owner
BUYER_TG = 720_000_100
_update_ids = itertools.count(30_000_000)
ETHIOPIC = re.compile(r"[ሀ-፿]")


@pytest.fixture(autouse=True)
def _telegram_on(telegram_linking: object) -> None:
    """The bot configured with test-only values."""


@pytest.fixture
def bazaar(db: Session) -> Bazaar:
    return Bazaar(db)


# -- helpers ---------------------------------------------------------------------------


def _user(db: Session, phone: str) -> User:
    db.rollback()
    local = "+251" + phone[1:]
    user = db.scalar(select(User).where(User.phone == local))
    assert user is not None
    return user


def _connect(db: Session, phone: str, telegram_id: int, language: str = "en") -> User:
    """Connected as signing in with Telegram leaves it (D-101)."""
    user = _user(db, phone)
    user.telegram_id = user.bound_telegram_id = telegram_id
    user.telegram_linked_at = datetime.now(UTC)
    user.language = language
    db.commit()
    return user


def _member(db: Session, seller_id: str, phone: str, role: str, telegram_id: int) -> User:
    from markx.accounts import service as accounts

    user = accounts.get_or_create_user_by_phone(db, accounts.parse_phone(phone), "en")
    db.add(SellerMember(seller_id=uuid.UUID(seller_id), user_id=user.id, role=role))
    db.commit()
    return _connect(db, phone, telegram_id)


def _order(bazaar: Bazaar, offer: str = "a128", mode: str = "seller_rider") -> dict[str, Any]:
    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, getattr(bazaar, offer)["id"], 1)
    seller = "alpha" if offer.startswith("a") else "beta"
    response = checkout(buyer, address_id, {seller: mode})
    assert response.status_code == 201, response.text
    return dict(response.json())


def _seller_order(db: Session, order: dict[str, Any]) -> SellerOrder:
    db.rollback()
    found = db.scalar(select(SellerOrder).where(SellerOrder.order_id == uuid.UUID(order["id"])))
    assert found is not None
    return found


def _drain() -> None:
    run_once(datetime.now(UTC), jobs=NO_JOBS)


def _pushed(telegram_id: int, template: str | None = None) -> list[dict[str, Any]]:
    """What the fake sent, with the words the real Bot API adapter would send
    (it renders them with `texts.render_telegram`)."""
    return [
        {
            **line,
            "text": outside_texts.render_telegram(
                line["template"], line["params"], line["language"]
            ),
        }
        for line in read_dev_push_outbox()
        if line["telegram_id"] == telegram_id and template in (None, line["template"])
    ]


def _buttons(markup: dict[str, Any] | None) -> list[str]:
    if markup is None:
        return []
    return [
        button.get("callback_data") or button["url"]
        for row in markup["inline_keyboard"]
        for button in row
    ]


def _callback(telegram_id: int, data: str, *, update_id: int | None = None) -> dict[str, Any]:
    return {
        "update_id": update_id if update_id is not None else next(_update_ids),
        "callback_query": {
            "id": "4711",
            "from": {"id": telegram_id, "is_bot": False, "first_name": "Abebe"},
            "message": {
                "message_id": 55,
                "date": 1_790_000_000,
                "chat": {"id": telegram_id, "type": "private"},
            },
            "data": data,
        },
    }


def _press(telegram_id: int, data: str) -> dict[str, Any]:
    return tg.webhook(_callback(telegram_id, data))


def _say(telegram_id: int, text: str) -> dict[str, Any]:
    return tg.webhook(
        {
            "update_id": next(_update_ids),
            "message": {
                "message_id": 9,
                "date": 1_790_000_000,
                "from": {"id": telegram_id, "is_bot": False, "first_name": "Abebe"},
                "chat": {"id": telegram_id, "type": "private"},
                "text": text,
            },
        }
    )


def _status(db: Session, seller_order: SellerOrder) -> str:
    db.rollback()
    return str(db.scalar(select(SellerOrder.status).where(SellerOrder.id == seller_order.id)))


def _told(db: Session, template: str) -> int:
    db.rollback()
    return int(
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.template == template, Notification.channel == "in_app")
        )
        or 0
    )


# -- 1. the new-order alert, with its buttons, and the reminder ------------------------------


def test_a_new_order_reaches_the_shop_in_telegram_with_accept_and_decline(
    bazaar: Bazaar, db: Session
) -> None:
    _connect(db, A_PHONE, OWNER_TG, "en")
    order = _order(bazaar)
    seller_order = _seller_order(db, order)
    _drain()
    (alert,) = _pushed(OWNER_TG, "order.placed_for_seller")
    hex_id = seller_order.id.hex
    assert _buttons(alert["reply_markup"])[:3] == [f"a:{hex_id}", f"d:{hex_id}", "inbox"]
    assert alert["text"].startswith(f"MarkX: new order {order['code']}. Tap Accept or Decline")
    # The order code and the product names (F-26): no buyer, price or address.
    assert "Abebe" not in alert["text"]
    assert "birr" not in alert["text"].lower()


def test_the_reminder_before_an_order_expires_has_the_buttons_and_is_sent_once(
    bazaar: Bazaar, db: Session
) -> None:
    _connect(db, A_PHONE, OWNER_TG, "am")
    seller_order = _seller_order(db, _order(bazaar))
    _drain()
    near = seller_order.response_deadline - timedelta(minutes=5)
    for _ in range(3):  # the job runs again, as after a restart
        with session_scope() as session:
            orders.remind_approaching_deadline(session, now=near)
        _drain()
    (reminder,) = _pushed(OWNER_TG, "order.approaching_response_deadline")
    assert f"a:{seller_order.id.hex}" in _buttons(reminder["reply_markup"])
    assert ETHIOPIC.search(reminder["text"]), "the owner chose Amharic"
    assert _told(db, "order.approaching_response_deadline") == 1


# -- 2. the inbox and its buttons (S-07) ------------------------------------------------------


def test_the_owner_accepts_marks_ready_and_sends_from_telegram(bazaar: Bazaar, db: Session) -> None:
    _connect(db, A_PHONE, OWNER_TG, "en")
    order = _order(bazaar)
    seller_order = _seller_order(db, order)
    hex_id = seller_order.id.hex

    inbox = _say(OWNER_TG, "/orders")
    assert inbox["method"] == "sendMessage"
    assert order["code"] in inbox["text"]
    assert "waiting for your answer" in inbox["text"]
    assert f"o:{hex_id}" in _buttons(inbox["reply_markup"])

    answer = _press(OWNER_TG, f"a:{hex_id}")
    assert (answer["method"], answer["message_id"]) == ("editMessageText", 55)
    assert answer["text"].startswith(f"✅ You accepted order {order['code']}.")
    assert _status(db, seller_order) == "confirmed"
    assert _told(db, "order.seller_confirmed") == 1  # the buyer is told, as from the website
    assert f"r:{hex_id}" in _buttons(answer["reply_markup"])

    answer = _press(OWNER_TG, f"r:{hex_id}")
    assert _status(db, seller_order) == "ready"
    assert f"x:{hex_id}" in _buttons(answer["reply_markup"])
    answer = _press(OWNER_TG, f"x:{hex_id}")
    assert _status(db, seller_order) == "out_for_delivery"
    # The handover code is never typed into Telegram: the website takes it.
    assert "Never type it here" in answer["text"]
    assert not [b for b in _buttons(answer["reply_markup"]) if b.startswith(("a:", "r:", "x:"))]


def test_declining_from_telegram_needs_a_reason_and_gives_the_stock_back(
    bazaar: Bazaar, db: Session
) -> None:
    _connect(db, A_PHONE, OWNER_TG, "en")
    seller_order = _seller_order(db, _order(bazaar))
    hex_id = seller_order.id.hex
    reserved = lambda: db.scalar(  # noqa: E731
        select(Inventory.reserved).where(Inventory.offer_id == uuid.UUID(bazaar.a128["id"]))
    )
    assert reserved() == 1

    choose = _press(OWNER_TG, f"d:{hex_id}")
    assert _status(db, seller_order) == "placed", "choosing a reason changes nothing yet"
    assert [f"dr:{n}:{hex_id}" for n in range(3)] == _buttons(choose["reply_markup"])[:3]

    _press(OWNER_TG, f"dr:0:{hex_id}")
    assert _status(db, seller_order) == "declined"
    db.rollback()
    assert db.scalar(
        select(SellerOrder.closed_reason).where(SellerOrder.id == seller_order.id)
    ) == ("Out of stock")
    assert reserved() == 0
    assert _told(db, "order.seller_declined") == 1
    # A reason number no button offers is ignored.
    assert _press(OWNER_TG, f"dr:7:{hex_id}") == {"ok": True}


# -- 3. the same permissions as the website, checked again at every press -------------------


@pytest.mark.parametrize("role", ["catalogue", "finance"])
def test_a_member_whose_role_does_not_handle_orders_is_refused_in_the_bot(
    role: str, bazaar: Bazaar, db: Session
) -> None:
    """The website refuses these roles on `/seller/{id}/orders/.../confirm`
    (blueprint C.3); the bot refuses them the same way, on the server."""
    _member(db, bazaar.a_id, "0911000071", role, 720_000_071)
    seller_order = _seller_order(db, _order(bazaar))
    answer = _press(720_000_071, f"a:{seller_order.id.hex}")
    assert answer["text"] == "Your role in this store does not allow this."
    assert _status(db, seller_order) == "placed"
    assert _told(db, "order.seller_confirmed") == 0
    # The website says the same to the same person.
    assert _say(720_000_071, "/orders")["text"] == texts.say("not_a_seller", "en")


def test_another_store_cannot_touch_an_order_it_does_not_own(bazaar: Bazaar, db: Session) -> None:
    _connect(db, B_PHONE, BETA_TG, "en")
    seller_order = _seller_order(db, _order(bazaar))  # Alpha's order
    for data in (
        f"a:{seller_order.id.hex}",
        f"dr:1:{seller_order.id.hex}",
        f"o:{seller_order.id.hex}",
    ):
        answer = _press(BETA_TG, data)
        # The same words as a missing order: Alpha's order is not revealed.
        assert answer["text"] == "That order was not found."
        assert seller_order.id.hex not in str(answer)
    assert _status(db, seller_order) == "placed"
    assert order_codes_not_in(_say(BETA_TG, "/orders")["text"], db)


def order_codes_not_in(text: str, db: Session) -> bool:
    db.rollback()
    return not any(code in text for code in db.scalars(select(Order.code)))


def test_a_member_removed_after_the_alert_is_refused_when_pressing(
    bazaar: Bazaar, db: Session
) -> None:
    handler = _member(db, bazaar.a_id, "0911000072", "orders", 720_000_072)
    seller_order = _seller_order(db, _order(bazaar))
    _drain()
    assert _pushed(720_000_072, "order.placed_for_seller"), "the handler got the alert"
    db.execute(
        update(SellerMember).where(SellerMember.user_id == handler.id).values(is_active=False)
    )
    db.commit()
    answer = _press(720_000_072, f"a:{seller_order.id.hex}")
    assert answer["text"] == "That order was not found."
    assert _status(db, seller_order) == "placed"


def test_a_disconnected_or_blocked_telegram_account_can_do_nothing(
    bazaar: Bazaar, db: Session
) -> None:
    owner = _connect(db, A_PHONE, OWNER_TG, "en")
    seller_order = _seller_order(db, _order(bazaar))
    # Disconnected (D-101): remembered, but no longer connected.
    owner.telegram_id = None
    owner.telegram_linked_at = None
    db.commit()
    from markx.accounts.telegram_link import REPLIES

    assert _press(OWNER_TG, f"a:{seller_order.id.hex}")["text"] == REPLIES["help"]
    assert _say(OWNER_TG, "/orders")["text"] == REPLIES["help"]
    assert _status(db, seller_order) == "placed"
    # Connected again but blocked by staff.
    owner = _connect(db, A_PHONE, OWNER_TG, "en")
    owner.status = "blocked"
    db.commit()
    assert _press(OWNER_TG, f"a:{seller_order.id.hex}")["text"] == REPLIES["help"]
    assert _status(db, seller_order) == "placed"


def test_a_closed_store_cannot_answer_orders_from_telegram(bazaar: Bazaar, db: Session) -> None:
    _connect(db, A_PHONE, OWNER_TG, "en")
    seller_order = _seller_order(db, _order(bazaar))
    db.execute(update(Seller).where(Seller.id == uuid.UUID(bazaar.a_id)).values(status="closed"))
    db.commit()
    assert _press(OWNER_TG, f"a:{seller_order.id.hex}")["text"] == "This store is closed."
    assert _status(db, seller_order) == "placed"


def test_the_order_rules_hold_in_the_bot(bazaar: Bazaar, db: Session) -> None:
    """Too late, already answered, and a move the state diagram forbids are
    refused by the same service the website calls."""
    _connect(db, A_PHONE, OWNER_TG, "en")
    late = _seller_order(db, _order(bazaar))
    db.execute(
        update(SellerOrder)
        .where(SellerOrder.id == late.id)
        .values(response_deadline=datetime.now(UTC) - timedelta(minutes=1))
    )
    db.commit()
    answer = _press(OWNER_TG, f"a:{late.id.hex}")
    assert answer["text"].startswith("The time to answer order")
    assert _status(db, late) == "placed"

    early = _seller_order(db, _order(bazaar, "a256"))
    answer = _press(OWNER_TG, f"r:{early.id.hex}")  # ready before it was accepted
    assert answer["text"].startswith("Order ")
    assert "cannot do that now" in answer["text"]
    assert _status(db, early) == "placed"
    _press(OWNER_TG, f"a:{early.id.hex}")
    again = _press(OWNER_TG, f"a:{early.id.hex}")
    assert "is no longer waiting for your answer" in again["text"]
    assert _told(db, "order.seller_confirmed") == 1


def test_a_collection_order_is_handed_over_on_the_website_only(bazaar: Bazaar, db: Session) -> None:
    _connect(db, B_PHONE, BETA_TG, "en")
    seller_order = _seller_order(db, _order(bazaar, "b128", "shop_collection"))
    _press(BETA_TG, f"a:{seller_order.id.hex}")
    ready = _press(BETA_TG, f"r:{seller_order.id.hex}")
    assert "waiting for the buyer to collect" in ready["text"]
    assert f"x:{seller_order.id.hex}" not in _buttons(ready["reply_markup"])
    refused = _press(BETA_TG, f"x:{seller_order.id.hex}")
    assert "enter their handover code in MarkX" in refused["text"]
    assert _status(db, seller_order) == "ready"


# -- 4. never twice, never lost, after a restart ---------------------------------------------


def test_a_press_telegram_delivers_twice_acts_once_and_still_answers(
    bazaar: Bazaar, db: Session
) -> None:
    """Telegram sends an update again when it did not get the answer (a
    restart, a timeout). The order is accepted once, the buyer told once, and
    the repeated delivery is answered with the order as it now is."""
    _connect(db, A_PHONE, OWNER_TG, "en")
    seller_order = _seller_order(db, _order(bazaar))
    update_ = _callback(OWNER_TG, f"a:{seller_order.id.hex}")
    first = tg.webhook(update_)
    second = tg.webhook(update_)
    assert first["text"].startswith("✅ You accepted")
    assert "accepted, to pack" in second["text"]
    assert not second["text"].startswith("✅")
    assert _status(db, seller_order) == "confirmed"
    assert _told(db, "order.seller_confirmed") == 1
    # The worker restarting delivers each message once: nothing is sent again.
    _drain()
    _drain()
    db.rollback()
    accepted = db.scalars(
        select(NotificationDelivery.status).where(
            NotificationDelivery.template == "order.placed_for_seller",
            NotificationDelivery.channel == "telegram",
        )
    ).all()
    assert accepted == ["accepted"]
    assert len(_pushed(OWNER_TG, "order.placed_for_seller")) == 1


def test_a_price_change_telegram_delivers_twice_is_made_once(bazaar: Bazaar, db: Session) -> None:
    _connect(db, A_PHONE, OWNER_TG, "en")
    ref = offer_ref(uuid.UUID(bazaar.a128["id"]))
    update_ = {
        "update_id": next(_update_ids),
        "message": {
            "message_id": 9,
            "date": 1_790_000_000,
            "from": {"id": OWNER_TG, "is_bot": False},
            "chat": {"id": OWNER_TG, "type": "private"},
            "text": f"/price {ref} 17999.50",
        },
    }
    assert tg.webhook(update_)["text"] == f"✅ {ref}: the price is now ETB 17,999.50."
    assert tg.webhook(update_)["text"] == f"✅ {ref}: the price is now ETB 17,999.50."
    db.rollback()
    from markx.offers.models import OfferPriceHistory

    changes = select(func.count()).where(OfferPriceHistory.new_price_santim == 1_799_950)
    assert db.scalar(changes) == 1


# -- 5. the commands (S-24) ------------------------------------------------------------------


def test_the_commands_list_listings_and_change_price_and_stock(bazaar: Bazaar, db: Session) -> None:
    _connect(db, A_PHONE, OWNER_TG, "en")
    offer_id = uuid.UUID(bazaar.a128["id"])
    ref = offer_ref(offer_id)
    help_ = _say(OWNER_TG, "/help")["text"]
    for command in ("/orders", "/offers", "/price", "/stock", "/checkin"):
        assert command in help_
    assert _say(OWNER_TG, "/start")["text"] == help_

    listed = _say(OWNER_TG, "/offers")
    assert ref in listed["text"]
    assert "ETB 18,500" in listed["text"]
    assert "checkin" in _buttons(listed["reply_markup"])

    assert "ETB 19,000" in _say(OWNER_TG, f"/price {ref.lower()} 19000")["text"]
    db.rollback()
    assert db.scalar(select(Offer.price_santim).where(Offer.id == offer_id)) == 1_900_000
    assert (
        _say(OWNER_TG, f"/stock {ref} 9")["text"] == f"✅ {ref}: 9 in stock, 9 available to buyers."
    )
    # The website's rules: no zero price, no stock below what open orders hold.
    assert _say(OWNER_TG, f"/price {ref} 0")["text"] == "Enter a price above zero."
    _order(bazaar)
    refused = _say(OWNER_TG, f"/stock {ref} 0")["text"]
    assert refused.startswith("Some units are held for open orders")
    db.rollback()
    assert db.scalar(select(Inventory.on_hand).where(Inventory.offer_id == offer_id)) == 9
    assert _say(OWNER_TG, "/price nonsense")["text"].startswith("Send it like this")
    assert _say(OWNER_TG, "/stock ABCDEF 1")["text"].startswith("No listing of yours")

    checked = _say(OWNER_TG, "/checkin")["text"]
    assert checked == "✅ Thank you: 2 listing(s) confirmed as still right today."


def test_an_orders_member_may_not_change_prices_and_another_store_is_invisible(
    bazaar: Bazaar, db: Session
) -> None:
    _member(db, bazaar.a_id, "0911000073", "orders", 720_000_073)
    _connect(db, B_PHONE, BETA_TG, "en")
    ref = offer_ref(uuid.UUID(bazaar.a128["id"]))
    # The orders role may not manage offers (C.3), on the website or here.
    assert (
        _say(720_000_073, f"/price {ref} 1")["text"]
        == "Your role in this store does not allow this."
    )
    assert _say(720_000_073, "/checkin")["text"] == "Your role in this store does not allow this."
    # Beta's owner cannot even find Alpha's listing.
    assert _say(BETA_TG, f"/price {ref} 1")["text"].startswith("No listing of yours")
    assert ref not in _say(BETA_TG, "/offers")["text"]
    db.rollback()
    assert db.scalar(
        select(Offer.price_santim).where(Offer.id == uuid.UUID(bazaar.a128["id"]))
    ) == (1_850_000)


def test_a_stranger_or_a_bad_update_changes_nothing(bazaar: Bazaar, db: Session) -> None:
    seller_order = _seller_order(db, _order(bazaar))
    from markx.accounts.telegram_link import REPLIES

    # Not connected: told how to connect, in both languages; nothing named.
    assert _press(720_999_999, f"a:{seller_order.id.hex}")["text"] == REPLIES["help"]
    # Unknown commands from a stranger stay ignored (D-093).
    assert _say(720_999_999, "/link something") == {"ok": True}
    _connect(db, A_PHONE, OWNER_TG, "en")
    bad = _callback(OWNER_TG, f"a:{seller_order.id.hex}")
    bad["callback_query"]["message"]["chat"] = {"id": -100, "type": "group"}
    assert tg.webhook(bad) == {"ok": True}
    assert _press(OWNER_TG, "a:not-an-id") == {"ok": True}
    assert _press(OWNER_TG, "x" * 65) == {"ok": True}
    assert _status(db, seller_order) == "placed"


# -- 6. order updates to buyers (C-10) -------------------------------------------------------


def test_the_buyer_follows_the_order_in_telegram_in_their_language(
    bazaar: Bazaar, db: Session
) -> None:
    _connect(db, A_PHONE, OWNER_TG, "en")
    order = _order(bazaar)
    buyer_id = db.scalar(select(Order.buyer_user_id).where(Order.id == uuid.UUID(order["id"])))
    buyer = db.get(User, buyer_id)
    assert buyer is not None
    buyer.telegram_id = buyer.bound_telegram_id = BUYER_TG
    buyer.telegram_linked_at = datetime.now(UTC)
    buyer.language = "am"
    db.commit()
    seller_order = _seller_order(db, order)
    for verb in ("a", "r", "x"):
        _press(OWNER_TG, f"{verb}:{seller_order.id.hex}")
    _drain()
    got = {line["template"]: line for line in _pushed(BUYER_TG)}
    assert set(got) == {
        "order.placed", "order.seller_confirmed", "order.ready", "order.out_for_delivery",
    }  # fmt: skip
    for line in got.values():
        assert order["code"] in line["text"]
        assert ETHIOPIC.search(line["text"])
        assert line["text"] != outside_texts.GENERIC_TEXT["am"]
    # The first opens the secure tracking link, without sign-in (D.14) ...
    (track,) = _buttons(got.pop("order.placed")["reply_markup"])
    assert track.startswith(f"http://testserver/am/track/{order['id']}?expires=")
    assert ApiClient().get(track.replace("http://testserver/am/", "/")).status_code == 200
    # ... the rest the order page, which asks the buyer to sign in.
    for line in got.values():
        (link,) = _buttons(line["reply_markup"])
        assert link == f"http://testserver/am/orders/{order['id']}"


# -- 7. the weekly message (S-26) ------------------------------------------------------------


def test_the_weekly_message_reads_as_figures_in_telegram(bazaar: Bazaar, db: Session) -> None:
    _connect(db, A_PHONE, OWNER_TG, "en")
    _connect(db, B_PHONE, BETA_TG, "am")
    seller_order = _seller_order(db, _order(bazaar))
    _press(OWNER_TG, f"a:{seller_order.id.hex}")
    next_week = datetime.now(UTC) + timedelta(days=7)
    settings_store.set_setting(db, "sellers.weekly_report_enabled", True)
    db.commit()
    with session_scope() as session:
        assert performance.send_weekly_reports(session, next_week) == 2
    _drain()
    _drain()  # a restart: still once
    (alpha,) = _pushed(OWNER_TG, "seller.weekly_report")
    week = performance.last_complete_week(next_week).isoformat()
    assert alpha["text"].startswith(
        f"MarkX weekly report, week from {week}: 1 orders received, 1 accepted, 0 completed."
    )
    assert _buttons(alpha["reply_markup"]) == ["checkin"]
    (beta,) = _pushed(BETA_TG, "seller.weekly_report")
    assert ETHIOPIC.search(beta["text"])
    assert "0" in beta["text"]


def test_the_weekly_message_is_not_sent_to_someone_who_left_the_store(
    bazaar: Bazaar, db: Session
) -> None:
    gone = _member(db, bazaar.a_id, "0911000074", "manager", 720_000_074)
    next_week = datetime.now(UTC) + timedelta(days=7)
    with session_scope() as session:
        performance.send_weekly_reports(session, next_week)
    db.execute(update(SellerMember).where(SellerMember.user_id == gone.id).values(is_active=False))
    db.commit()
    _drain()
    assert _pushed(720_000_074) == []
    db.rollback()
    reason = db.scalar(
        select(NotificationDelivery.reason)
        .join(Notification, Notification.id == NotificationDelivery.notification_id)
        .where(Notification.user_id == gone.id, NotificationDelivery.channel == "telegram")
    )
    assert reason == "recipient_not_authorized"


# -- 7b. what was ordered (F-26, decided by the founder; D-104) -------------------------------

PRODUCT_EN = "Samsung Galaxy A16"
PRODUCT_AM = "ሳምሰንግ ጋላክሲ A16"


def _buyer_details(db: Session, order: dict[str, Any]) -> list[str]:
    """Everything about the buyer a message must never carry."""
    db.rollback()
    placed = db.get(Order, uuid.UUID(order["id"]))
    assert placed is not None
    buyer = db.get(User, placed.buyer_user_id)
    assert buyer is not None
    details = [buyer.phone, buyer.phone[4:], "0" + buyer.phone[4:]]
    details += [
        str(v) for v in placed.address_snapshot.values() if isinstance(v, str) and len(v) > 3
    ]
    details += [
        p["handover_code"] for p in order.get("seller_orders", []) if p.get("handover_code")
    ]
    if buyer.name:
        details.append(buyer.name)
    return [d for d in details if d]


def test_the_new_order_alert_and_the_reminder_name_the_products_in_the_owners_language(
    bazaar: Bazaar, db: Session
) -> None:
    _connect(db, A_PHONE, OWNER_TG, "en")
    order = _order(bazaar)
    seller_order = _seller_order(db, order)
    _drain()
    (alert,) = _pushed(OWNER_TG, "order.placed_for_seller")
    assert alert["text"].endswith(f"\nProducts: {PRODUCT_EN}")
    # Amharic for the reminder: the owner changed language in between.
    _connect(db, A_PHONE, OWNER_TG, "am")
    with session_scope() as session:
        orders.remind_approaching_deadline(
            session, now=seller_order.response_deadline - timedelta(minutes=5)
        )
    _drain()
    (reminder,) = _pushed(OWNER_TG, "order.approaching_response_deadline")
    assert reminder["text"].endswith(f"\nምርቶች፦ {PRODUCT_AM}")
    for message in (alert, reminder):
        for detail in _buyer_details(db, order):
            assert detail not in message["text"], detail
        assert "18,500" not in message["text"], "no price"
        assert "18500" not in message["text"], "no price"
    # Every other message about one of the store's orders names them too.
    with session_scope() as session:
        orders.expire_unanswered_orders(
            session, now=seller_order.response_deadline + timedelta(minutes=1)
        )
    _drain()
    (expired,) = _pushed(OWNER_TG, "order.expired_unanswered")
    assert expired["text"].endswith(f"\nምርቶች፦ {PRODUCT_AM}")


def test_the_product_names_are_never_stored_with_the_notification_or_sent_by_sms(
    bazaar: Bazaar, db: Session
) -> None:
    _connect(db, A_PHONE, OWNER_TG, "en")
    _order(bazaar)
    _drain()
    (alert,) = _pushed(OWNER_TG, "order.placed_for_seller")
    assert PRODUCT_EN in alert["text"]
    db.rollback()
    for params in db.scalars(
        select(Notification.params).where(Notification.template == "order.placed_for_seller")
    ):
        assert outside_texts.PRODUCTS_PARAM not in params
        assert PRODUCT_EN not in str(params)
    # SMS takes the order code alone, whatever it is given.
    sms = outside_texts.render(
        "order.placed_for_seller",
        {**alert["params"], outside_texts.PRODUCTS_PARAM: PRODUCT_EN},
        "en",
    )
    assert PRODUCT_EN not in sms


def test_the_buyer_and_another_store_never_get_the_product_line(
    bazaar: Bazaar, db: Session
) -> None:
    _connect(db, A_PHONE, OWNER_TG, "en")
    _connect(db, B_PHONE, BETA_TG, "en")
    order = _order(bazaar)
    buyer_id = db.scalar(select(Order.buyer_user_id).where(Order.id == uuid.UUID(order["id"])))
    buyer = db.get(User, buyer_id)
    assert buyer is not None
    buyer.telegram_id = buyer.bound_telegram_id = BUYER_TG
    buyer.telegram_linked_at = datetime.now(UTC)
    db.commit()
    seller_order = _seller_order(db, order)
    _press(OWNER_TG, f"a:{seller_order.id.hex}")
    _drain()
    assert _pushed(BUYER_TG), "the buyer was told in Telegram"
    for line in _pushed(BUYER_TG):
        assert outside_texts.PRODUCTS_PARAM not in line["params"]
        assert "Products:" not in line["text"]
    # Beta hears nothing about Alpha's order (its own approval message only).
    assert not [line for line in _pushed(BETA_TG) if line["template"].startswith("order.")]
    assert all(outside_texts.PRODUCTS_PARAM not in line["params"] for line in _pushed(BETA_TG))
    assert PRODUCT_EN not in _say(BETA_TG, "/orders")["text"]


def test_the_orders_inbox_and_an_orders_card_name_the_products(bazaar: Bazaar, db: Session) -> None:
    _connect(db, A_PHONE, OWNER_TG, "en")
    order = _order(bazaar)
    seller_order = _seller_order(db, order)
    inbox = _say(OWNER_TG, "/orders")["text"]
    assert f"{order['code']}: waiting for your answer" in inbox
    assert f"\n   Products: {PRODUCT_EN}" in inbox
    card = _press(OWNER_TG, f"o:{seller_order.id.hex}")["text"]
    assert f"Products: {PRODUCT_EN}" in card
    for detail in _buyer_details(db, order):
        assert detail not in inbox, detail
        assert detail not in card, detail
    _connect(db, A_PHONE, OWNER_TG, "am")
    assert f"ምርቶች፦ {PRODUCT_AM}" in _say(OWNER_TG, "/orders")["text"]


def test_long_and_many_product_names_are_shortened_sensibly() -> None:
    long_name = "Samsung Galaxy A16 5G Dual SIM 128 GB Black with Original Charger"
    short = products.shorten(long_name)
    assert len(short) <= products.NAME_LIMIT
    assert short.endswith("…")
    assert short == "Samsung Galaxy A16 5G Dual SIM 128 GB…", "cut at a word near the end"
    assert products.shorten("A" * 60) == "A" * 39 + "…", "one long word is cut at the limit"
    assert products.describe(["Phone\nwith\ttabs  and\x00 nulls"], "en") == (
        "Phone with tabs and nulls"
    )
    names = ["Phone A", "phone a", "Case B", "Charger C", "Cable D", "Screen E"]
    assert products.describe(names, "en") == "Phone A, Case B, Charger C and 2 more"
    assert products.describe(names, "am") == "Phone A፣ Case B፣ Charger C እና ሌሎች 2"
    assert products.describe(["", "  "], "en") == ""
    worst = products.describe([long_name * 3] * 2 + [str(n) * 80 for n in range(9)], "am")
    assert len(worst) <= products.MAX_TEXT
    assert outside_texts.render_telegram(
        "order.placed_for_seller",
        {"order_code": "MX-ACDEFG", "seller_order_id": "x", outside_texts.PRODUCTS_PARAM: worst},
        "am",
    ).endswith(worst)


def test_a_telegram_text_refuses_product_names_that_are_not_one_short_line() -> None:
    seller = {"order_code": "MX-ACDEFG", "seller_order_id": "x"}
    for bad in ("", "Phone\n+251911223344", "x" * 201, 7, ["Phone"]):
        with pytest.raises(outside_texts.UnsafeText):
            outside_texts.render_telegram(
                "order.placed_for_seller", {**seller, outside_texts.PRODUCTS_PARAM: bad}, "en"
            )
    # Only a store's order message: never the buyer's, never the weekly one.
    for template, params in (
        ("order.placed", {"order_code": "MX-ACDEFG"}),
        ("seller.weekly_report", {"week_start": "2026-11-16"}),
    ):
        with pytest.raises(outside_texts.UnsafeText):
            outside_texts.render_telegram(
                template, {**params, outside_texts.PRODUCTS_PARAM: "Phone"}, "en"
            )
    # A name that looks like a placeholder stays text.
    words = outside_texts.render_telegram(
        "order.placed_for_seller", {**seller, outside_texts.PRODUCTS_PARAM: "{code} {week}"}, "en"
    )
    assert words.endswith("Products: {code} {week}")


# -- 8. every word in both languages, and nothing personal ----------------------------------


def test_every_bot_text_exists_in_english_and_amharic() -> None:
    for key, words in texts.TEXTS.items():
        assert set(words) == {"en", "am"}, key
        assert words["en"].strip(), key
        assert words["am"].strip(), key
        assert ETHIOPIC.search(words["am"]) or key.startswith("btn_") or key == "order_line", key
        assert set(re.findall(r"\{(\w+)\}", words["en"])) == set(
            re.findall(r"\{(\w+)\}", words["am"])
        ), key
    for template, words in outside_texts.TELEGRAM_TEXTS.items():
        assert set(words) == {"en", "am"}, template
        assert ETHIOPIC.search(words["am"]), template


def test_a_telegram_text_takes_only_codes_dates_and_whole_numbers() -> None:
    good = {
        "week_start": "2026-11-16", "orders_received": 3, "orders_confirmed": 2,
        "completed": 1, "prices_to_confirm": 0,
    }  # fmt: skip
    assert "3 orders received" in outside_texts.render_telegram("seller.weekly_report", good, "en")
    for key, bad in [
        ("orders_received", "3 (call 0911…)"),
        ("orders_received", True),
        ("orders_received", -1),
        ("week_start", "Abebe"),
    ]:
        with pytest.raises(outside_texts.UnsafeText):
            outside_texts.render_telegram("seller.weekly_report", {**good, key: bad}, "en")
    with pytest.raises(outside_texts.UnsafeText):
        outside_texts.render_telegram("order.ready", {"order_code": "0911223344"}, "en")


def test_every_button_fits_telegrams_limit() -> None:
    some = uuid.uuid4()
    for markup in (
        keyboards.markup([keyboards.answer_row("am", some)]),
        keyboards.markup(keyboards.reason_rows("am", some)),
    ):
        for data in _buttons(markup):
            assert len(data.encode()) <= 64
            assert keyboards.CALLBACK.fullmatch(data)


def test_every_order_message_has_its_own_words_in_telegram() -> None:
    """C-10 and S-07: no order message reaches Telegram as the generic "You
    have a new message". The templates are read from the order code itself,
    so a new one without words fails here."""
    import pathlib

    source = (pathlib.Path(orders.__file__)).read_text(encoding="utf-8")
    notify = r"(?:_notify_buyer|_notify_seller|notifications\.notify)\("
    sent = set(re.findall(notify + r'[^"]*"((?:order|dispute)\.[a-z_]+)"', source))
    # `mark_ready` chooses its template in a variable first.
    sent |= set(re.findall(r'"(order\.ready(?:_for_collection)?)"', source))
    assert {"order.placed", "order.placed_for_seller", "order.ready", "order.delivered"} <= sent
    assert len(sent) >= 27
    for template in sorted(sent):
        for language in ("en", "am"):
            words = outside_texts.render_telegram(template, {"order_code": "MX-ACDEFG"}, language)
            assert words != outside_texts.GENERIC_TEXT[language], template
            assert "MX-ACDEFG" in words, template
