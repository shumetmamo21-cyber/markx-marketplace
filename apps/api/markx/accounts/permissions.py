"""Who may do what (blueprint C.3 and C.4).

The two tables below are the blueprint's permission tables, cell for cell.
They are held in code and covered by a test for every cell. Checks happen in
the API's service layer; the web app only hides what a user may not do.
"""

from __future__ import annotations

from enum import StrEnum

from markx.accounts.models import StaffRole
from markx.sellers.models import SellerRole


class SellerCapability(StrEnum):
    EDIT_STORE = "edit_store"
    MANAGE_OFFERS = "manage_offers"
    PROPOSE_PRODUCTS = "propose_products"
    HANDLE_ORDERS = "handle_orders"
    SEE_BUYER_CONTACT = "see_buyer_contact"
    REPLY_TO_REVIEWS = "reply_to_reviews"
    SEE_PERFORMANCE = "see_performance"
    SEE_STATEMENTS = "see_statements"
    BUY_PLANS = "buy_plans"
    MANAGE_STAFF = "manage_staff"
    CHANGE_PAYOUT_ACCOUNT = "change_payout_account"
    CHANGE_LEGAL_DETAILS = "change_legal_details"
    # Closing is built; a transfer of ownership is not (D-022).
    # PROVISIONAL (F-02, D-083), for when transfer is built: the store drops to
    # Level 0, its business documents (licence, TIN certificate, shop photo)
    # stay accepted, and the new owner supplies an identity document before
    # staff restore its level. Its offers are hidden until then.
    #   The engineer's guess at the founder's request; THE FOUNDER MUST CONFIRM
    #   OR CHANGE IT BEFORE MARKX GOES LIVE.
    TRANSFER_OR_CLOSE = "transfer_or_close"


class StaffCapability(StrEnum):
    REVIEW_SELLERS = "review_sellers"
    VIEW_DOCUMENTS = "view_documents"
    CURATE_CATALOGUE = "curate_catalogue"
    MODERATE_LISTINGS = "moderate_listings"
    MODERATE_REVIEWS = "moderate_reviews"
    FIND_ORDERS = "find_orders"
    INTERVENE_IN_ORDERS = "intervene_in_orders"
    HANDLE_CASES = "handle_cases"
    APPROVE_MONEY = "approve_money"
    CHANGE_FEES = "change_fees"
    CHANGE_DELIVERY_AND_RISK = "change_delivery_and_risk"
    TUNE_SEARCH = "tune_search"
    MANAGE_STAFF_AND_SETTINGS = "manage_staff_and_settings"
    READ_AUDIT_LOG = "read_audit_log"
    EXPORT_DATA = "export_data"


_O, _M, _C, _R, _F = (
    SellerRole.OWNER,
    SellerRole.MANAGER,
    SellerRole.CATALOGUE,
    SellerRole.ORDERS,
    SellerRole.FINANCE,
)

# Blueprint C.3, row by row.
SELLER_PERMISSIONS: dict[SellerCapability, frozenset[SellerRole]] = {
    SellerCapability.EDIT_STORE: frozenset({_O, _M}),
    SellerCapability.MANAGE_OFFERS: frozenset({_O, _M, _C}),
    SellerCapability.PROPOSE_PRODUCTS: frozenset({_O, _M, _C}),
    SellerCapability.HANDLE_ORDERS: frozenset({_O, _M, _R}),
    SellerCapability.SEE_BUYER_CONTACT: frozenset({_O, _M, _R}),
    SellerCapability.REPLY_TO_REVIEWS: frozenset({_O, _M, _R}),
    SellerCapability.SEE_PERFORMANCE: frozenset({_O, _M, _C, _R, _F}),
    SellerCapability.SEE_STATEMENTS: frozenset({_O, _F}),
    SellerCapability.BUY_PLANS: frozenset({_O, _M, _F}),
    SellerCapability.MANAGE_STAFF: frozenset({_O, _M}),
    SellerCapability.CHANGE_PAYOUT_ACCOUNT: frozenset({_O}),
    SellerCapability.CHANGE_LEGAL_DETAILS: frozenset({_O}),
    SellerCapability.TRANSFER_OR_CLOSE: frozenset({_O}),
}

_SA, _OP, _SU, _CA, _FI = (
    StaffRole.SUPER_ADMIN,
    StaffRole.OPERATIONS,
    StaffRole.SUPPORT,
    StaffRole.CATALOGUE,
    StaffRole.FINANCE,
)

# Blueprint C.4, row by row.
STAFF_PERMISSIONS: dict[StaffCapability, frozenset[StaffRole]] = {
    StaffCapability.REVIEW_SELLERS: frozenset({_SA, _OP}),
    StaffCapability.VIEW_DOCUMENTS: frozenset({_SA, _OP}),
    StaffCapability.CURATE_CATALOGUE: frozenset({_SA, _CA}),
    StaffCapability.MODERATE_LISTINGS: frozenset({_SA, _OP, _CA}),
    StaffCapability.MODERATE_REVIEWS: frozenset({_SA, _OP, _SU, _CA}),
    StaffCapability.FIND_ORDERS: frozenset({_SA, _OP, _SU, _FI}),
    StaffCapability.INTERVENE_IN_ORDERS: frozenset({_SA, _OP}),
    StaffCapability.HANDLE_CASES: frozenset({_SA, _OP, _SU}),
    StaffCapability.APPROVE_MONEY: frozenset({_SA, _FI}),
    StaffCapability.CHANGE_FEES: frozenset({_SA, _FI}),
    StaffCapability.CHANGE_DELIVERY_AND_RISK: frozenset({_SA, _OP}),
    StaffCapability.TUNE_SEARCH: frozenset({_SA, _CA}),
    StaffCapability.MANAGE_STAFF_AND_SETTINGS: frozenset({_SA}),
    StaffCapability.READ_AUDIT_LOG: frozenset({_SA, _FI}),
    StaffCapability.EXPORT_DATA: frozenset({_SA, _FI}),
}

# Release 1 has the owner and manager roles only; the other three arrive with
# paid plans in Release 2 (blueprint C.2, D.4).
RELEASE_1_SELLER_ROLES = frozenset({SellerRole.OWNER, SellerRole.MANAGER})


def seller_can(role: str, capability: SellerCapability) -> bool:
    """Deny by default: an unknown role or capability is never allowed."""
    try:
        return SellerRole(role) in SELLER_PERMISSIONS[capability]
    except (ValueError, KeyError):
        return False


def staff_can(role: str, capability: StaffCapability) -> bool:
    try:
        return StaffRole(role) in STAFF_PERMISSIONS[capability]
    except (ValueError, KeyError):
        return False


def staff_capabilities(role: str) -> list[str]:
    return sorted(cap.value for cap in StaffCapability if staff_can(role, cap))


def seller_capabilities(role: str) -> list[str]:
    return sorted(cap.value for cap in SellerCapability if seller_can(role, cap))
