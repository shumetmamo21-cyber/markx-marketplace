"""Cart, checkout and order routes (blueprint F.5).

`/cart...`                       the server-side cart, for a signed-in buyer
                                 or an anonymous visitor
`/checkout...`                   the priced review step and placing the order
`/me/orders...`                  the buyer's own orders
`/seller/{seller_id}/orders...`  one seller's part of orders, scoped by
                                 `require_seller`
`/admin/orders...`               the staff orders desk: find an order, dispatch
                                 a parcel, issue the buyer a new handover code
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from markx.accounts.deps import (
    CurrentPrincipal,
    OptionalPrincipal,
    Principal,
    SellerContext,
    require_seller,
    require_staff,
)
from markx.accounts.models import SessionKind
from markx.accounts.permissions import SellerCapability, StaffCapability, seller_can
from markx.core import ratelimit
from markx.core.config import get_config
from markx.core.errors import PermissionDenied
from markx.core.http import Db
from markx.orders import selectors, service
from markx.orders.models import Cart
from markx.orders.schemas import (
    CancelIn,
    CartItemIn,
    CartOut,
    CheckoutIn,
    DeclineIn,
    DispatchIn,
    HandoverIn,
    OrderOut,
    PaymentRecordIn,
    QuoteIn,
    QuoteOut,
    ReasonIn,
    SellerOrderOut,
)

router = APIRouter()
seller_router = APIRouter(prefix="/seller/{seller_id}", tags=["seller: orders"])
admin_router = APIRouter(prefix="/admin/orders", tags=["admin: orders"])
OrderFinder = Annotated[Principal, Depends(require_staff(StaffCapability.FIND_ORDERS))]
OrderIntervener = Annotated[Principal, Depends(require_staff(StaffCapability.INTERVENE_IN_ORDERS))]

CART_COOKIE = "markx_cart"
CART_COOKIE_DAYS = 30
LangQuery = Annotated[str, Query(pattern="^(am|en)$")]
ZoneQuery = Annotated[str | None, Query(pattern=r"^[a-z][a-z0-9_]{1,39}$")]

OrderHandler = Annotated[SellerContext, Depends(require_seller(SellerCapability.HANDLE_ORDERS))]


def _refuse_staff(principal: Principal | None) -> None:
    # Staff powers and shopping never mix in one session (blueprint C.1): a
    # staff member who shops signs in with a phone code, like anyone.
    if principal is not None and principal.session.kind == SessionKind.STAFF:
        raise PermissionDenied(
            "customer_session_required", "Sign in with your phone code to shop on MarkX."
        )


def require_buyer(principal: CurrentPrincipal) -> Principal:
    _refuse_staff(principal)
    return principal


Buyer = Annotated[Principal, Depends(require_buyer)]


def _cart(
    request: Request, response: Response, principal: Principal | None, db: Db, *, create: bool
) -> Cart | None:
    """The caller's cart: their own if signed in, else the one their cookie
    names. A visitor's cart moves into their own the first time they arrive
    signed in."""
    _refuse_staff(principal)
    token = request.cookies.get(CART_COOKIE)
    if principal is not None:
        if token:
            service.merge_anonymous_cart(db, principal.user.id, token)
            response.delete_cookie(CART_COOKIE, path="/")
        return service.user_cart(db, principal.user.id, create=create)
    cart = service.cart_for_token(db, token) if token else None
    if cart is None and create:
        cart, token = service.create_anonymous_cart(db)
        response.set_cookie(
            CART_COOKIE,
            token,
            max_age=CART_COOKIE_DAYS * 24 * 3600,
            path="/",
            secure=get_config().cookie_secure,
            httponly=True,
            samesite="lax",
        )
    return cart


# -- cart ------------------------------------------------------------------------


@router.get("/cart", response_model=CartOut, tags=["cart"])
def read_cart(
    request: Request,
    response: Response,
    principal: OptionalPrincipal,
    db: Db,
    zone: ZoneQuery = None,
    lang: LangQuery = "am",
) -> CartOut:
    """The cart with today's prices and stock, and what changed (C-06)."""
    cart = _cart(request, response, principal, db, create=False)
    return CartOut.model_validate(selectors.cart_view(db, cart, lang, zone_code=zone))


@router.put("/cart/items/{offer_id}", response_model=CartOut, tags=["cart"])
def set_cart_item(
    offer_id: uuid.UUID,
    body: CartItemIn,
    request: Request,
    response: Response,
    principal: OptionalPrincipal,
    db: Db,
    lang: LangQuery = "am",
) -> CartOut:
    cart = _cart(request, response, principal, db, create=True)
    assert cart is not None
    service.set_cart_item(db, cart, offer_id, body.quantity)
    return CartOut.model_validate(selectors.cart_view(db, cart, lang, zone_code=None))


@router.delete("/cart/items/{offer_id}", response_model=CartOut, tags=["cart"])
def remove_cart_item(
    offer_id: uuid.UUID,
    request: Request,
    response: Response,
    principal: OptionalPrincipal,
    db: Db,
    lang: LangQuery = "am",
) -> CartOut:
    cart = _cart(request, response, principal, db, create=False)
    if cart is not None:
        service.remove_cart_item(db, cart, offer_id)
    return CartOut.model_validate(selectors.cart_view(db, cart, lang, zone_code=None))


@router.delete("/cart", response_model=CartOut, tags=["cart"])
def clear_cart(
    request: Request,
    response: Response,
    principal: OptionalPrincipal,
    db: Db,
    lang: LangQuery = "am",
) -> CartOut:
    cart = _cart(request, response, principal, db, create=False)
    if cart is not None:
        service.clear_cart(db, cart)
    return CartOut.model_validate(selectors.cart_view(db, cart, lang, zone_code=None))


@router.post("/cart/accept-changes", response_model=CartOut, tags=["cart"])
def accept_cart_changes(
    request: Request,
    response: Response,
    principal: OptionalPrincipal,
    db: Db,
    lang: LangQuery = "am",
) -> CartOut:
    """The buyer has seen the new prices and wants to carry on."""
    cart = _cart(request, response, principal, db, create=False)
    if cart is not None:
        service.accept_cart_changes(db, cart)
    return CartOut.model_validate(selectors.cart_view(db, cart, lang, zone_code=None))


# -- checkout --------------------------------------------------------------------


def _choices(body: QuoteIn) -> dict[str, str]:
    return {choice.store_slug: choice.method for choice in body.deliveries}


@router.post("/checkout/quote", response_model=QuoteOut, tags=["checkout"])
def quote_checkout(
    body: QuoteIn, request: Request, response: Response, buyer: Buyer, db: Db
) -> QuoteOut:
    """The review step: every price, fee and total, computed by the server."""
    cart = _cart(request, response, buyer, db, create=True)
    assert cart is not None
    quote = service.build_quote(
        db, buyer.user, cart, address_id=body.address_id, deliveries=_choices(body)
    )
    return QuoteOut.model_validate(selectors.quote_out(quote))


@router.post("/checkout", response_model=OrderOut, tags=["checkout"])
def place_order(
    body: CheckoutIn,
    request: Request,
    response: Response,
    buyer: Buyer,
    db: Db,
    lang: LangQuery = "am",
) -> OrderOut:
    """Place the order. 201 the first time; 200 with the same order when the
    same idempotency key is sent again."""
    ratelimit.hit(f"checkout:{buyer.user.id}", 30, timedelta(hours=1))
    _cart(request, response, buyer, db, create=True)
    order, replayed = service.place_order(
        db,
        buyer.user,
        address_id=body.address_id,
        deliveries=_choices(body),
        payment_method=body.payment_method,
        expected_total_santim=body.expected_total_santim,
        idempotency_key=body.idempotency_key,
        channel="telegram" if buyer.session.transport == "header" else "web",
    )
    response.status_code = 200 if replayed else 201
    return OrderOut.model_validate(selectors.buyer_order(db, buyer.user.id, order.id, lang))


# -- the buyer's orders ------------------------------------------------------------


@router.get("/me/orders", response_model=list[OrderOut], tags=["orders"])
def list_my_orders(
    buyer: Buyer,
    db: Db,
    before: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    lang: LangQuery = "am",
) -> list[OrderOut]:
    rows = selectors.buyer_orders(db, buyer.user.id, lang, before=before, limit=limit)
    return [OrderOut.model_validate(row) for row in rows]


@router.get("/me/orders/{order_id}", response_model=OrderOut, tags=["orders"])
def read_my_order(order_id: uuid.UUID, buyer: Buyer, db: Db, lang: LangQuery = "am") -> OrderOut:
    return OrderOut.model_validate(selectors.buyer_order(db, buyer.user.id, order_id, lang))


@router.post(
    "/me/orders/{order_id}/seller-orders/{seller_order_id}/cancel",
    response_model=OrderOut,
    tags=["orders"],
)
def cancel_my_seller_order(
    order_id: uuid.UUID,
    seller_order_id: uuid.UUID,
    body: CancelIn,
    buyer: Buyer,
    db: Db,
    lang: LangQuery = "am",
) -> OrderOut:
    service.cancel_by_buyer(db, buyer.user, order_id, seller_order_id, reason=body.reason)
    return OrderOut.model_validate(selectors.buyer_order(db, buyer.user.id, order_id, lang))


@router.post(
    "/me/orders/{order_id}/seller-orders/{seller_order_id}/confirm-received",
    response_model=OrderOut,
    tags=["orders"],
)
def confirm_my_seller_order_received(
    order_id: uuid.UUID,
    seller_order_id: uuid.UUID,
    buyer: Buyer,
    db: Db,
    lang: LangQuery = "am",
) -> OrderOut:
    """ "The goods are right": the part completes now rather than when the
    problem window closes."""
    service.confirm_received(db, buyer.user, order_id, seller_order_id)
    return OrderOut.model_validate(selectors.buyer_order(db, buyer.user.id, order_id, lang))


# -- the seller's orders -----------------------------------------------------------


def _may_see_contact(context: SellerContext) -> bool:
    return seller_can(context.member.role, SellerCapability.SEE_BUYER_CONTACT)


def _seller_order_out(
    db: Db, context: SellerContext, seller_order_id: uuid.UUID, lang: str
) -> SellerOrderOut:
    return SellerOrderOut.model_validate(
        selectors.seller_order(
            db, context.seller.id, seller_order_id, lang, may_see_contact=_may_see_contact(context)
        )
    )


@seller_router.get("/orders", response_model=list[SellerOrderOut])
def list_seller_orders(
    context: OrderHandler,
    db: Db,
    status: Literal[
        "placed", "confirmed", "paid", "ready", "out_for_delivery", "delivered", "completed",
        "declined", "expired", "cancelled", "delivery_failed", "returned", "disputed", "refunded",
    ] | None = None,
    before: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    lang: LangQuery = "am",
) -> list[SellerOrderOut]:  # fmt: skip
    rows = selectors.seller_orders(
        db, context.seller.id, lang, status=status, before=before, limit=limit,
        may_see_contact=_may_see_contact(context),
    )  # fmt: skip
    return [SellerOrderOut.model_validate(row) for row in rows]


@seller_router.get("/orders/{seller_order_id}", response_model=SellerOrderOut)
def read_seller_order(
    seller_order_id: uuid.UUID, context: OrderHandler, db: Db, lang: LangQuery = "am"
) -> SellerOrderOut:
    return _seller_order_out(db, context, seller_order_id, lang)


@seller_router.post("/orders/{seller_order_id}/confirm", response_model=SellerOrderOut)
def confirm_seller_order(
    seller_order_id: uuid.UUID, context: OrderHandler, db: Db, lang: LangQuery = "am"
) -> SellerOrderOut:
    """ "I have it, at this price": the order is confirmed (S-07)."""
    service.seller_respond(db, context.seller, context.member, seller_order_id, accept=True)
    return _seller_order_out(db, context, seller_order_id, lang)


@seller_router.post("/orders/{seller_order_id}/decline", response_model=SellerOrderOut)
def decline_seller_order(
    seller_order_id: uuid.UUID,
    body: DeclineIn,
    context: OrderHandler,
    db: Db,
    lang: LangQuery = "am",
) -> SellerOrderOut:
    service.seller_respond(
        db, context.seller, context.member, seller_order_id, accept=False, reason=body.reason
    )
    return _seller_order_out(db, context, seller_order_id, lang)


@seller_router.post("/orders/{seller_order_id}/ready", response_model=SellerOrderOut)
def mark_seller_order_ready(
    seller_order_id: uuid.UUID, context: OrderHandler, db: Db, lang: LangQuery = "am"
) -> SellerOrderOut:
    """Packed and waiting for the rider or the buyer (G.6)."""
    service.mark_ready(db, context.seller, context.member, seller_order_id)
    return _seller_order_out(db, context, seller_order_id, lang)


@seller_router.post("/orders/{seller_order_id}/dispatch", response_model=SellerOrderOut)
def dispatch_seller_order(
    seller_order_id: uuid.UUID,
    body: DispatchIn,
    context: OrderHandler,
    db: Db,
    lang: LangQuery = "am",
) -> SellerOrderOut:
    """With the rider (S-12). Also the retry after a failed handover."""
    service.seller_dispatch(
        db, context.seller, context.member, seller_order_id,
        rider_name=body.rider_name, rider_phone=body.rider_phone,
    )  # fmt: skip
    return _seller_order_out(db, context, seller_order_id, lang)


@seller_router.post("/orders/{seller_order_id}/handover", response_model=SellerOrderOut)
def hand_over_seller_order(
    seller_order_id: uuid.UUID,
    body: HandoverIn,
    context: OrderHandler,
    db: Db,
    lang: LangQuery = "am",
) -> SellerOrderOut:
    """Enter the buyer's handover code (C-15). Wrong attempts are limited."""
    service.seller_confirm_delivery(
        db, context.seller, context.member, seller_order_id, code=body.code
    )
    return _seller_order_out(db, context, seller_order_id, lang)


@seller_router.post("/orders/{seller_order_id}/delivery-failed", response_model=SellerOrderOut)
def report_seller_order_delivery_failed(
    seller_order_id: uuid.UUID,
    body: ReasonIn,
    context: OrderHandler,
    db: Db,
    lang: LangQuery = "am",
) -> SellerOrderOut:
    service.report_delivery_failed(
        db, context.seller, context.member, seller_order_id, reason=body.reason
    )
    return _seller_order_out(db, context, seller_order_id, lang)


@seller_router.post("/orders/{seller_order_id}/return", response_model=SellerOrderOut)
def return_seller_order(
    seller_order_id: uuid.UUID,
    body: ReasonIn,
    context: OrderHandler,
    db: Db,
    lang: LangQuery = "am",
) -> SellerOrderOut:
    """The goods are back on the shelf; the stock returns."""
    service.return_to_seller(
        db, context.seller, context.member, seller_order_id, reason=body.reason
    )
    return _seller_order_out(db, context, seller_order_id, lang)


@seller_router.post("/orders/{seller_order_id}/payment", response_model=SellerOrderOut)
def record_seller_order_payment(
    seller_order_id: uuid.UUID,
    body: PaymentRecordIn,
    context: OrderHandler,
    request: Request,
    db: Db,
    lang: LangQuery = "am",
) -> SellerOrderOut:
    """The buyer paid the seller directly (D.12): the seller's word, recorded."""
    service.record_direct_payment(
        db, context.seller, context.member, context.principal.actor(request), seller_order_id,
        method=body.method,
    )  # fmt: skip
    return _seller_order_out(db, context, seller_order_id, lang)


# -- the staff orders desk -----------------------------------------------------------


@admin_router.get("/{code}", response_model=OrderOut)
def staff_read_order(
    code: Annotated[str, Path(pattern=r"^MX-[34679ACDEFGHJKMNPQRTUVWXY]{6}$")],
    staff: OrderFinder,
    db: Db,
    lang: LangQuery = "am",
) -> OrderOut:
    """Any order by its code, with every part and its full timeline (P11)."""
    return OrderOut.model_validate(selectors.staff_order(db, code, lang))


@admin_router.post("/seller-orders/{seller_order_id}/dispatch", response_model=OrderOut)
def staff_dispatch_seller_order(
    seller_order_id: uuid.UUID,
    body: DispatchIn,
    staff: OrderIntervener,
    request: Request,
    db: Db,
    lang: LangQuery = "am",
) -> OrderOut:
    seller_order = service.staff_dispatch(
        db, staff.actor(request), seller_order_id,
        rider_name=body.rider_name, rider_phone=body.rider_phone,
    )  # fmt: skip
    return OrderOut.model_validate(selectors.staff_order_by_id(db, seller_order.order_id, lang))


@admin_router.post("/seller-orders/{seller_order_id}/reissue-code", response_model=OrderOut)
def staff_reissue_handover_code(
    seller_order_id: uuid.UUID,
    body: ReasonIn,
    staff: OrderIntervener,
    request: Request,
    db: Db,
    lang: LangQuery = "am",
) -> OrderOut:
    """A new handover code for the buyer, after a lockout or a leak."""
    seller_order = service.staff_reissue_handover_code(
        db, staff.actor(request), seller_order_id, reason=body.reason
    )
    return OrderOut.model_validate(selectors.staff_order_by_id(db, seller_order.order_id, lang))
