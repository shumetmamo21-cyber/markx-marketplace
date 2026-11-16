"""A test for every cell of the blueprint's two permission tables (C.3, C.4).

The grids below are transcribed from the blueprint independently of the code:
"x" is the blueprint's ✓ and "-" is its –. If the code and the blueprint ever
disagree, a cell here fails.
"""

from __future__ import annotations

import pytest

from markx.accounts.models import StaffRole
from markx.accounts.permissions import (
    SellerCapability,
    StaffCapability,
    seller_can,
    staff_can,
)
from markx.sellers.models import SellerRole

SELLER_ROLES = ("owner", "manager", "catalogue", "orders", "finance")
#                                                    O M C R F   (blueprint C.3)
SELLER_GRID = {
    SellerCapability.EDIT_STORE:            "x x - - -",
    SellerCapability.MANAGE_OFFERS:         "x x x - -",
    SellerCapability.PROPOSE_PRODUCTS:      "x x x - -",
    SellerCapability.HANDLE_ORDERS:         "x x - x -",
    SellerCapability.SEE_BUYER_CONTACT:     "x x - x -",
    SellerCapability.REPLY_TO_REVIEWS:      "x x - x -",
    SellerCapability.SEE_PERFORMANCE:       "x x x x x",
    SellerCapability.SEE_STATEMENTS:        "x - - - x",
    SellerCapability.BUY_PLANS:             "x x - - x",
    SellerCapability.MANAGE_STAFF:          "x x - - -",
    SellerCapability.CHANGE_PAYOUT_ACCOUNT: "x - - - -",
    SellerCapability.CHANGE_LEGAL_DETAILS:  "x - - - -",
    SellerCapability.TRANSFER_OR_CLOSE:     "x - - - -",
}  # fmt: skip

STAFF_ROLES = ("super_admin", "operations", "support", "catalogue", "finance")
#                                                       SA OP SU CA FI   (blueprint C.4)
STAFF_GRID = {
    StaffCapability.REVIEW_SELLERS:            "x x - - -",
    StaffCapability.VIEW_DOCUMENTS:            "x x - - -",
    StaffCapability.CURATE_CATALOGUE:          "x - - x -",
    StaffCapability.MODERATE_LISTINGS:         "x x - x -",
    StaffCapability.MODERATE_REVIEWS:          "x x x x -",
    StaffCapability.FIND_ORDERS:               "x x x - x",
    StaffCapability.INTERVENE_IN_ORDERS:       "x x - - -",
    StaffCapability.HANDLE_CASES:              "x x x - -",
    StaffCapability.APPROVE_MONEY:             "x - - - x",
    StaffCapability.CHANGE_FEES:               "x - - - x",
    StaffCapability.CHANGE_DELIVERY_AND_RISK:  "x x - - -",
    StaffCapability.TUNE_SEARCH:               "x - - x -",
    StaffCapability.MANAGE_STAFF_AND_SETTINGS: "x - - - -",
    StaffCapability.READ_AUDIT_LOG:            "x - - - x",
    StaffCapability.EXPORT_DATA:               "x - - - x",
}  # fmt: skip

SELLER_CELLS = [
    (capability, role, mark == "x")
    for capability, row in SELLER_GRID.items()
    for role, mark in zip(SELLER_ROLES, row.split(), strict=True)
]
STAFF_CELLS = [
    (capability, role, mark == "x")
    for capability, row in STAFF_GRID.items()
    for role, mark in zip(STAFF_ROLES, row.split(), strict=True)
]


@pytest.mark.parametrize(("capability", "role", "allowed"), SELLER_CELLS)
def test_seller_permission_cell(capability: SellerCapability, role: str, allowed: bool) -> None:
    assert seller_can(role, capability) is allowed


@pytest.mark.parametrize(("capability", "role", "allowed"), STAFF_CELLS)
def test_staff_permission_cell(capability: StaffCapability, role: str, allowed: bool) -> None:
    assert staff_can(role, capability) is allowed


def test_the_grids_cover_every_capability_and_role() -> None:
    assert set(SELLER_GRID) == set(SellerCapability)
    assert set(STAFF_GRID) == set(StaffCapability)
    assert set(SELLER_ROLES) == {r.value for r in SellerRole}
    assert set(STAFF_ROLES) == {r.value for r in StaffRole}
    assert len(SELLER_CELLS) == 13 * 5
    assert len(STAFF_CELLS) == 15 * 5


def test_unknown_roles_are_denied_by_default() -> None:
    for capability in SellerCapability:
        assert not seller_can("intern", capability)
        assert not seller_can("", capability)
    for capability in StaffCapability:
        assert not staff_can("contractor", capability)
        assert not staff_can("owner", capability)  # a seller role is not a staff role


def test_the_super_administrator_holds_every_staff_capability() -> None:
    assert all(staff_can("super_admin", capability) for capability in StaffCapability)


def test_the_owner_holds_every_seller_capability() -> None:
    assert all(seller_can("owner", capability) for capability in SellerCapability)
