"""C-27: the notice a buyer reads before placing an order (D-110), through the real API.

The review step of both checkouts, the signed-in buyer's and the guest's,
carries a short notice in the buyer's language: who sells, paying at the
door, checking the goods before paying, and how to raise a problem. The
words are the PROVISIONAL engineering draft (P-110-1) and live in one place,
`markx/orders/notice.py`, for the founder to replace.

Every test here fails on the code before D-110: the review step has no
notice there, and the notice module does not exist.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from sqlalchemy.orm import Session as DbSession

from markx.core import settings_store
from markx.orders import notice
from markx.sellers.models import Seller
from tests.bazaar import Bazaar
from tests.conftest import ApiClient
from tests.factories import add_to_cart

ETHIOPIC = re.compile(r"[ሀ-፿]")
RIDER = {"alpha": "seller_rider"}
TWO_SHOPS = {"alpha": "seller_rider", "beta": "shop_collection"}


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def _choices(deliveries: dict[str, str]) -> list[dict[str, str]]:
    return [{"store_slug": slug, "method": method} for slug, method in deliveries.items()]


def _quote(
    client: ApiClient, address_id: str, deliveries: dict[str, str], lang: str | None
) -> dict[str, Any]:
    params = {"lang": lang} if lang else {}
    response = client.post(
        "/checkout/quote",
        params=params,
        json={"address_id": address_id, "deliveries": _choices(deliveries)},
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def _guest_quote(bazaar: Bazaar, lang: str | None) -> dict[str, Any]:
    visitor = ApiClient()
    add_to_cart(visitor, bazaar.a128["id"], 1)
    params = {"lang": lang} if lang else {}
    response = visitor.post(
        "/checkout/guest/quote",
        params=params,
        json={
            "guest": {
                "recipient_name": "Guest Buyer",
                "phone": "0911777001",
                "delivery_area_id": bazaar.area_id,
                "landmark": "Next to the Bole post office, green door",
            },
            "deliveries": _choices(RIDER),
        },
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def _signed_in_quote(
    bazaar: Bazaar, lang: str | None, deliveries: dict[str, str] = RIDER
) -> dict[str, Any]:
    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, bazaar.a128["id"], 1)
    if "beta" in deliveries:
        add_to_cart(buyer, bazaar.b128["id"], 1)
    return _quote(buyer, address_id, deliveries, lang)


def _expected(language: str, *, guest: bool) -> list[str]:
    keys = [
        "who_sells",
        "pay_at_door",
        "check_goods",
        "problem_guest" if guest else "problem_account",
    ]
    return [notice.TEXT[language][key] for key in keys]


def _matches(template: str, shown: str) -> bool:
    """Whether `shown` is `template` with its placeholders filled in."""
    pattern = re.escape(template).replace(r"\{sellers\}", ".+").replace(r"\{hours\}", r"\d+")
    return re.fullmatch(pattern, shown) is not None


# -- the signed-in buyer's review step -------------------------------------------------------


def test_the_review_step_carries_the_notice_in_english(bazaar: Bazaar, db: DbSession) -> None:
    quote = _signed_in_quote(bazaar, "en")
    shown = quote["notice"]
    assert shown["title"] == "Before you place your order"
    assert shown["version"] == notice.VERSION
    assert shown["provisional"] is True
    assert len(shown["points"]) == 4
    for template, point in zip(_expected("en", guest=False), shown["points"], strict=True):
        assert _matches(template, point), point
    who, pay, check, problem = shown["points"]
    # Who sells: the shop's legal name, exactly as the review step shows it.
    assert quote["groups"][0]["seller_legal_name"] in who
    assert "MarkX" in who
    assert "pay" in pay
    assert "receive" in pay
    assert "Check the goods before you pay" in check
    assert "handover code" in check
    # How to raise a problem, with the window the order page really allows.
    hours = settings_store.get_int(db, "orders.problem_window_hours")
    assert f"within {hours} hours" in problem
    assert "order page" in problem
    assert not any("{" in point or "}" in point for point in shown["points"])


def test_the_review_step_carries_the_notice_in_amharic_by_default(
    bazaar: Bazaar, db: DbSession
) -> None:
    quote = _signed_in_quote(bazaar, None)  # no `lang`: Amharic, as everywhere
    shown = quote["notice"]
    assert shown["title"] == notice.TEXT["am"]["title"]
    assert ETHIOPIC.search(shown["title"])
    assert shown["provisional"] is True
    for template, point in zip(_expected("am", guest=False), shown["points"], strict=True):
        assert _matches(template, point), point
        assert ETHIOPIC.search(point)
    assert quote["groups"][0]["seller_legal_name"] in shown["points"][0]
    hours = settings_store.get_int(db, "orders.problem_window_hours")
    assert f"በ{hours} ሰዓት" in shown["points"][3]


def test_the_notice_names_every_shop_in_a_two_shop_order(bazaar: Bazaar, db: DbSession) -> None:
    # The test shops share one legal name; the second gets its own.
    beta_seller = db.get(Seller, uuid.UUID(bazaar.b_id))
    assert beta_seller is not None
    beta_seller.legal_name = "Beta Mobile Trading PLC"
    db.commit()
    english = _signed_in_quote(bazaar, "en", TWO_SHOPS)
    alpha, beta = (group["seller_legal_name"] for group in english["groups"])
    assert alpha != beta
    assert f"You are buying from {alpha} and {beta}." in english["notice"]["points"][0]
    amharic = _signed_in_quote(bazaar, "am", TWO_SHOPS)
    assert f"{alpha} እና {beta}" in amharic["notice"]["points"][0]


def test_the_notice_follows_the_problem_window_setting(bazaar: Bazaar, db: DbSession) -> None:
    settings_store.set_setting(db, "orders.problem_window_hours", 48)
    db.commit()
    problem = _signed_in_quote(bazaar, "en")["notice"]["points"][3]
    assert "within 48 hours" in problem
    assert "72" not in problem


# -- the guest's review step ------------------------------------------------------------------


@pytest.mark.parametrize("lang", ["en", "am"])
def test_a_guest_reads_the_notice_with_the_guests_way_to_raise_a_problem(
    bazaar: Bazaar, lang: str
) -> None:
    quote = _guest_quote(bazaar, lang)
    shown = quote["notice"]
    assert shown["title"] == notice.TEXT[lang]["title"]
    assert shown["provisional"] is True
    for template, point in zip(_expected(lang, guest=True), shown["points"], strict=True):
        assert _matches(template, point), point
    assert quote["groups"][0]["seller_legal_name"] in shown["points"][0]
    # A guest has no order page to report a problem on (C-07): the notice
    # never promises one.
    assert shown["points"][3] == notice.TEXT[lang]["problem_guest"]
    assert notice.TEXT[lang]["problem_account"] not in shown["points"]


def test_a_guest_quote_without_lang_is_in_amharic(bazaar: Bazaar) -> None:
    shown = _guest_quote(bazaar, None)["notice"]
    assert shown["title"] == notice.TEXT["am"]["title"]


# -- the words live in one place ---------------------------------------------------------------


def test_the_notice_has_the_same_points_in_both_languages() -> None:
    assert set(notice.TEXT) == {"en", "am"}
    assert set(notice.TEXT["en"]) == set(notice.TEXT["am"]) == {
        "title", "who_sells", "pay_at_door", "check_goods", "problem_account", "problem_guest",
    }  # fmt: skip
    for key in notice.TEXT["en"]:
        english, amharic = notice.TEXT["en"][key], notice.TEXT["am"][key]
        assert english.strip()
        assert amharic.strip()
        assert ETHIOPIC.search(amharic), key
        # The same placeholders in both languages.
        assert re.findall(r"\{\w+\}", english) == re.findall(r"\{\w+\}", amharic), key
    assert notice.PROVISIONAL is True


def test_a_legal_name_with_braces_is_shown_as_written(db: DbSession) -> None:
    shown = notice.order_notice(
        db, ["Abebe {hours} Trading", "Abebe {hours} Trading"], "en", guest=False
    )
    # Named once, as written; the problem window is filled only where it belongs.
    assert shown["points"][0].startswith("You are buying from Abebe {hours} Trading. ")
