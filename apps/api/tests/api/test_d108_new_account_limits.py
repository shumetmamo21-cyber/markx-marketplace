"""Limits for new accounts (AD-13; D-108), for signed-in buyers.

The founder's choice of 24 November 2026: a guest always counts as a
brand-new buyer (see test_d108_guest_checkout.py); a signed-in account counts
as one for `risk.new_account_days` after it was created, which was 0 until
the founder set it to 30 on 25 November 2026 (F-27; D-109, where these tests
run with the days at 0 unless they set them, as they were written:
tests/conftest.py). A brand-new buyer may pay at the door for orders up to a
smaller total (ETB 50,000) and may hold one open pay-at-the-door order at a
time. The other values are PROVISIONAL (P-108-2 to P-108-8), and every one
is a risk limit operations may change.

Every test here fails on the code before D-108: the settings do not exist.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole, User
from markx.core import settings_store
from markx.core.settings_am import DESCRIPTIONS_AM
from markx.orders import service
from tests.bazaar import Bazaar, stock
from tests.conftest import ApiClient, error_code
from tests.factories import add_to_cart, checkout, staff_client

RIDER = {"alpha": "seller_rider"}
COLLECT = {"beta": "shop_collection"}


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def _user(db: DbSession, client: ApiClient) -> User:
    db.rollback()
    user = db.get(User, uuid.UUID(client.get("/me").json()["id"]))
    assert user is not None
    return user


def _age(db: DbSession, client: ApiClient, days: float) -> None:
    """Make the account as old as `days`."""
    db.rollback()
    db.execute(
        text("update users set created_at = now() - make_interval(secs => :s) where id = :id"),
        {"s": days * 86_400, "id": client.get("/me").json()["id"]},
    )
    db.commit()


def test_no_signed_in_account_is_brand_new_until_the_founder_sets_the_days(
    bazaar: Bazaar, db: DbSession
) -> None:
    assert settings_store.get_int(db, "risk.new_account_days") == 0
    buyer, address = bazaar.buyer()
    assert service.is_brand_new(db, _user(db, buyer), now=datetime.now(UTC)) is False
    # Above a new buyer's ETB 50,000, and three open orders: as before.
    add_to_cart(buyer, bazaar.a128["id"], 3)
    assert checkout(buyer, address, RIDER).status_code == 201
    for _ in range(2):
        add_to_cart(buyer, bazaar.b128["id"], 1)
        assert checkout(buyer, address, COLLECT).status_code == 201


def test_with_the_days_set_a_new_account_pays_at_the_door_only_within_its_limits(
    bazaar: Bazaar, db: DbSession
) -> None:
    settings_store.set_setting(db, "risk.new_account_days", 30)
    db.commit()
    buyer, address = bazaar.buyer()
    assert service.is_brand_new(db, _user(db, buyer), now=datetime.now(UTC)) is True
    add_to_cart(buyer, bazaar.a128["id"], 3)  # 3 × 18,500 + 150 = ETB 55,650
    refused = checkout(buyer, address, RIDER)
    assert refused.status_code == 409, refused.text
    assert error_code(refused) == "new_buyer_order_too_large"
    assert refused.json()["error"]["details"] == {"limit_santim": 5_000_000}
    assert stock(db, bazaar.a128["id"]) == (5, 0)
    add_to_cart(buyer, bazaar.a128["id"], 2)  # ETB 37,150
    assert checkout(buyer, address, RIDER).status_code == 201
    # One open pay-at-the-door order at a time, collection included.
    add_to_cart(buyer, bazaar.b128["id"], 1)
    second = checkout(buyer, address, COLLECT)
    assert error_code(second) == "new_buyer_too_many_open_orders"
    assert second.json()["error"]["details"] == {"limit": 1}
    # Operations may change both limits.
    settings_store.set_setting(db, "risk.new_account_max_open_orders", 2)
    db.commit()
    assert checkout(buyer, address, COLLECT).status_code == 201


def test_an_account_older_than_the_days_has_the_ordinary_limits(
    bazaar: Bazaar, db: DbSession
) -> None:
    settings_store.set_setting(db, "risk.new_account_days", 30)
    db.commit()
    young, young_address = bazaar.buyer()
    _age(db, young, 29)
    add_to_cart(young, bazaar.a128["id"], 3)
    assert error_code(checkout(young, young_address, RIDER)) == "new_buyer_order_too_large"
    old, old_address = bazaar.buyer()
    _age(db, old, 31)
    assert service.is_brand_new(db, _user(db, old), now=datetime.now(UTC)) is False
    add_to_cart(old, bazaar.a128["id"], 3)
    assert checkout(old, old_address, RIDER).status_code == 201
    add_to_cart(old, bazaar.b128["id"], 1)
    assert checkout(old, old_address, COLLECT).status_code == 201
    # The ordinary limits still hold for it.
    settings_store.set_setting(db, "orders.max_open_direct_orders", 2)
    db.commit()
    add_to_cart(old, bazaar.b128["id"], 1)
    assert error_code(checkout(old, old_address, COLLECT)) == "too_many_open_orders"


def test_the_new_buyer_limits_are_provisional_settings(db: DbSession) -> None:
    for key, number in (
        ("risk.new_account_max_order_value_santim", "P-108-2"),
        ("risk.new_account_max_open_orders", "P-108-3"),
        ("guest_checkout.max_open_orders_per_ip", "P-108-4"),
        ("guest_checkout.attempts_per_ip_per_hour", "P-108-5"),
    ):
        spec = settings_store.SETTINGS[key]
        assert spec.description.startswith(f"PROVISIONAL ({number})"), key
        assert "before going live" in spec.description, key
        assert DESCRIPTIONS_AM[key].startswith(f"ጊዜያዊ ({number})"), key
    # The founder's decisions are settings too, and say whose decision they are:
    # P-108-1 became one on 25 November 2026 (F-27, D-109).
    for key in (
        "risk.new_account_days",
        "guest_checkout.enabled",
        "guest_checkout.shop_collection",
    ):
        assert "founder" in settings_store.SETTINGS[key].description, key
        assert "መሥራቹ" in DESCRIPTIONS_AM[key], key
    assert settings_store.SETTINGS["guest_checkout.enabled"].default is True
    assert settings_store.SETTINGS["guest_checkout.shop_collection"].default is False
    assert settings_store.SETTINGS["risk.new_account_days"].default == 30
    assert settings_store.SETTINGS["risk.new_account_max_order_value_santim"].default == 5_000_000
    assert settings_store.SETTINGS["risk.new_account_max_open_orders"].default == 1


def test_the_rules_are_marked_provisional_where_they_live() -> None:
    markx = Path(service.__file__).resolve().parents[1]
    orders = (markx / "orders" / "service.py").read_text(encoding="utf-8")
    assert "PROVISIONAL P-108-6" in orders
    assert "PROVISIONAL P-108-8" in orders
    assert "P-108-7" in (markx / "orders" / "selectors.py").read_text(encoding="utf-8")


NEW_KEYS = (
    "risk.new_account_days", "risk.new_account_max_order_value_santim",
    "risk.new_account_max_open_orders", "guest_checkout.enabled",
    "guest_checkout.shop_collection", "guest_checkout.max_open_orders_per_ip",
    "guest_checkout.attempts_per_ip_per_hour",
)  # fmt: skip


def test_operations_may_change_the_new_limits_and_every_change_is_audited(db: DbSession) -> None:
    operations = staff_client(db, "0911000301", StaffRole.OPERATIONS)
    support = staff_client(db, "0911000302", StaffRole.SUPPORT)
    rows = {row["key"]: row for row in operations.get("/admin/settings").json()}
    for key in NEW_KEYS:
        assert rows[key]["may_change"] is True, key
        assert rows[key]["description_am"], key
    # Support may neither read nor change them (C.4).
    assert error_code(support.get("/admin/settings")) == "permission_denied"
    for key in NEW_KEYS:
        refused = support.put(f"/admin/settings/{key}", json={"value": 1})
        assert refused.status_code == 403, (key, refused.text)
    changed = operations.put("/admin/settings/risk.new_account_days", json={"value": 30})
    assert changed.status_code == 200, changed.text
    assert (
        operations.put("/admin/settings/risk.new_account_days", json={"value": -1}).status_code
        == 422
    )
    entries = operations.get(
        "/admin/audit-log", params={"target_type": "setting", "target_id": "risk.new_account_days"}
    )
    # Operations may not read the audit log (finance and the super administrator do).
    assert entries.status_code == 403
    admin = staff_client(db, "0911000303", StaffRole.SUPER_ADMIN)
    logged = admin.get(
        "/admin/audit-log", params={"target_type": "setting", "target_id": "risk.new_account_days"}
    ).json()
    assert [(e["before"], e["after"]) for e in logged] == [({"value": 0}, {"value": 30})]
