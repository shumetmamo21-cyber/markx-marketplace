"""Brand-new signed-in accounts have the new-buyer limits for 30 days (F-27; D-109).

The founder's decision of 25 November 2026 sets P-108-1 to 30: for the first
30 days after it was made, a signed-in account pays at the door only for
orders up to ETB 50,000 and holds one open pay-at-the-door order at a time
(AD-13; D-108), as a guest always does. From day 30 on, the ordinary limits
apply. Operations may still change the days in the settings screen,
audit-logged.

Every test here fails on the code before D-109: the days were 0 there.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session as DbSession

from markx.core import settings_store
from markx.core.settings_am import DESCRIPTIONS_AM
from markx.orders import service
from tests.api.test_d108_new_account_limits import COLLECT, RIDER, _age, _user
from tests.bazaar import Bazaar, stock
from tests.conftest import error_code
from tests.factories import add_to_cart, checkout

# These tests run with what MarkX ships: 30 new-account days (F-27).
pytestmark = pytest.mark.founders_new_account_days


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def test_the_founder_set_the_new_account_days_to_30(db: DbSession) -> None:
    spec = settings_store.SETTINGS["risk.new_account_days"]
    assert spec.default == 30
    assert settings_store.get_int(db, "risk.new_account_days") == 30
    # The founder's decision now, not a provisional value, in both languages.
    assert not spec.description.startswith("PROVISIONAL")
    assert "founder" in spec.description
    assert "F-27" in spec.description
    assert "30" in spec.description
    assert not DESCRIPTIONS_AM["risk.new_account_days"].startswith("ጊዜያዊ")
    assert "መሥራቹ" in DESCRIPTIONS_AM["risk.new_account_days"]
    assert "30" in DESCRIPTIONS_AM["risk.new_account_days"]


def test_an_account_made_today_has_the_new_buyer_limits(bazaar: Bazaar, db: DbSession) -> None:
    buyer, address = bazaar.buyer()
    assert service.is_brand_new(db, _user(db, buyer), now=datetime.now(UTC)) is True
    add_to_cart(buyer, bazaar.a128["id"], 3)  # 3 × 18,500 + 150 = ETB 55,650
    refused = checkout(buyer, address, RIDER)
    assert refused.status_code == 409, refused.text
    assert error_code(refused) == "new_buyer_order_too_large"
    assert refused.json()["error"]["details"] == {"limit_santim": 5_000_000}
    # Nothing was held for it.
    assert stock(db, bazaar.a128["id"]) == (5, 0)
    add_to_cart(buyer, bazaar.a128["id"], 2)  # ETB 37,150
    assert checkout(buyer, address, RIDER).status_code == 201
    # One open pay-at-the-door order at a time, collection included.
    add_to_cart(buyer, bazaar.b128["id"], 1)
    second = checkout(buyer, address, COLLECT)
    assert error_code(second) == "new_buyer_too_many_open_orders"
    assert second.json()["error"]["details"] == {"limit": 1}


@pytest.mark.parametrize(
    ("days_old", "brand_new"), [(0, True), (29.9, True), (30.01, False), (90, False)]
)
def test_the_limits_last_the_first_30_days_after_the_account_was_made(
    bazaar: Bazaar, db: DbSession, days_old: float, brand_new: bool
) -> None:
    buyer, address = bazaar.buyer()
    _age(db, buyer, days_old)
    assert service.is_brand_new(db, _user(db, buyer), now=datetime.now(UTC)) is brand_new
    add_to_cart(buyer, bazaar.a128["id"], 3)  # ETB 55,650, above a new buyer's ETB 50,000
    answer = checkout(buyer, address, RIDER)
    if brand_new:
        assert error_code(answer) == "new_buyer_order_too_large"
    else:
        # The ordinary limits: up to ETB 300,000 and three open orders.
        assert answer.status_code == 201, answer.text
        add_to_cart(buyer, bazaar.b128["id"], 1)
        assert checkout(buyer, address, COLLECT).status_code == 201


def test_operations_may_still_change_the_days(bazaar: Bazaar, db: DbSession) -> None:
    settings_store.set_setting(db, "risk.new_account_days", 0)
    db.commit()
    buyer, address = bazaar.buyer()
    assert service.is_brand_new(db, _user(db, buyer), now=datetime.now(UTC)) is False
    add_to_cart(buyer, bazaar.a128["id"], 3)
    assert checkout(buyer, address, RIDER).status_code == 201
