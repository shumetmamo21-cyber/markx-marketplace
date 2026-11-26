"""Cart, checkout and order routes (blueprint F.5).

`/cart...`                       the server-side cart, for a signed-in buyer
                                 or an anonymous visitor
`/checkout...`                   the priced review step and placing the order
`/checkout/guest...`             the same for a guest, who gets the secure
                                 tracking link and nothing more (C-07, D-108)
`/me/orders...`                  the buyer's own orders
`/seller/{seller_id}/orders...`  one seller's part of orders, scoped by
                                 `require_seller`
`/admin/orders...`               the staff orders desk: find an order, dispatch
                                 a parcel, issue the buyer a new handover code
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated, Any, Literal

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
from markx.core import ratelimit, settings_store
from markx.core.config import get_config
from markx.core.errors import Conflict, PermissionDenied, ValidationFailed
from markx.core.http import Db, client_ip
from markx.orders import selectors, service
from markx.orders.models import Cart
from markx.orders.schemas import (
    AlternativeOut,
    CancelIn,
    CartItemIn,
    CartOut,
    CheckoutIn,
    DeclineIn,
    DispatchIn,
    GuestCheckoutIn,
    GuestCheckoutTermsOut,
    GuestDetailsIn,
    GuestOrderOut,
    GuestQuoteIn,
    HandoverIn,
    OpenProblemOut,
    OrderOut,
    PaymentRecordIn,
    ProblemIn,
    ProblemMessageIn,
    QuoteIn,
    QuoteOut,
    ReasonIn,
    ReorderOut,
    ResolveProblemIn,
    SellerCustomerOut,
    SellerOrderOut,
)
from markx.trust.models import CaseDecision

router = APIRouter()
seller_router = APIRouter(prefix="/seller/{seller_id}", tags=["seller: orders"])
admin_router = APIRouter(prefix="/admin/orders", tags=["admin: orders"])
OrderFinder = Annotated[Principal, Depends(require_staff(StaffCapability.FIND_ORDERS))]
CaseHandler = Annotated[Principal, Depends(require_staff(StaffCapability.HANDLE_CASES))]
OrderIntervener = Annotated[Principal, Depends(require_staff(StaffCapability.INTERVENE_IN_ORDERS))]

CART_COOKIE = "markx_cart"
CART_COOKIE_DAYS = 30
LangQuery = Annotated[str, Query(pattern="^(am|en)$")]
ZoneQuery = Annotated[str | None, Query(pattern=r"^[a-z][a-z0-9_]{1,39}$")]

OrderHandler = Annotated[SellerContext, Depends(require_seller(SellerCapability.HANDLE_ORDERS))]
ContactViewer = Annotated[
    SellerContext, Depends(require_seller(SellerCapability.SEE_BUYER_CONTACT))
]


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


def _choices(body: QuoteIn | GuestQuoteIn) -> dict[str, str]:
    return {choice.store_slug: choice.method for choice in body.deliveries}


@router.post("/checkout/quote", response_model=QuoteOut, tags=["checkout"])
def quote_checkout(
    body: QuoteIn,
    request: Request,
    response: Response,
    buyer: Buyer,
    db: Db,
    lang: LangQuery = "am",
) -> QuoteOut:
    """The review step: every price, fee and total, computed by the server,
    and the notice the buyer reads before placing the order (C-27), in
    `lang`."""
    cart = _cart(request, response, buyer, db, create=True)
    assert cart is not None
    quote = service.build_quote(
        db, buyer.user, cart, address_id=body.address_id, deliveries=_choices(body)
    )
    return QuoteOut.model_validate(selectors.quote_out(db, quote, lang, guest=False))


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


# -- guest checkout (C-07, D-108) ---------------------------------------------------


def _refuse_signed_in(principal: Principal | None) -> None:
    # A guest is a visitor. A signed-in person checks out from their account,
    # where their own limits apply; staff never shop with a staff session.
    _refuse_staff(principal)
    if principal is not None:
        raise Conflict(
            "guest_checkout_signed_in", "You are signed in: check out from your account instead."
        )


def _guest_fields(details: GuestDetailsIn) -> dict[str, Any]:
    """`service.guest_address`'s arguments, from the guest's form."""
    return {
        "recipient_name": details.recipient_name,
        "raw_phone": details.phone,
        "raw_phone2": details.phone2,
        "delivery_area_id": details.delivery_area_id,
        "landmark": details.landmark,
        "latitude": details.latitude,
        "longitude": details.longitude,
        "driver_notes": details.driver_notes,
    }


@router.get("/checkout/guest/terms", response_model=GuestCheckoutTermsOut, tags=["checkout"])
def guest_checkout_terms(db: Db) -> GuestCheckoutTermsOut:
    """What ordering as a guest offers today (C-07, AD-13): whether it is on,
    the largest order a guest may pay at the door, and whether a guest may
    collect at the shop."""
    return GuestCheckoutTermsOut(
        enabled=settings_store.get_bool(db, "guest_checkout.enabled"),
        max_order_value_santim=settings_store.get_int(
            db, "risk.new_account_max_order_value_santim"
        ),
        shop_collection=settings_store.get_bool(db, "guest_checkout.shop_collection"),
    )


@router.post("/checkout/guest/quote", response_model=QuoteOut, tags=["checkout"])
def quote_guest_checkout(
    body: GuestQuoteIn,
    request: Request,
    principal: OptionalPrincipal,
    db: Db,
    lang: LangQuery = "am",
) -> QuoteOut:
    """A guest's review step: every price, fee and total, computed by the
    server, for the delivery address the guest typed, and the notice the
    guest reads before placing the order (C-27), in `lang`."""
    _refuse_signed_in(principal)
    token = request.cookies.get(CART_COOKIE)
    cart = service.cart_for_token(db, token) if token else None
    if cart is None:
        raise ValidationFailed("cart_empty", "Your cart is empty.")
    guest = service.guest_address(db, **_guest_fields(body.guest))
    quote = service.build_guest_quote(db, cart, guest, deliveries=_choices(body))
    return QuoteOut.model_validate(selectors.quote_out(db, quote, lang, guest=True))


@router.post("/checkout/guest", response_model=GuestOrderOut, tags=["checkout"])
def place_guest_order(
    body: GuestCheckoutIn,
    request: Request,
    response: Response,
    principal: OptionalPrincipal,
    db: Db,
    lang: LangQuery = "am",
) -> GuestOrderOut:
    """Place a guest's order: 201 the first time; 200 with the same order
    when the same browser sends the same idempotency key again. The answer
    is the order's code and its secure tracking link, and nothing more: no
    account is made, found or signed in, whatever the phone number."""
    _refuse_signed_in(principal)
    token = request.cookies.get(CART_COOKIE)
    if not token:
        raise ValidationFailed("cart_empty", "Your cart is empty.")
    order, replayed = service.place_guest_order(
        db,
        cart_token=token,
        guest_fields=_guest_fields(body.guest),
        ip=client_ip(request),
        bot_token=body.bot_token,
        deliveries=_choices(body),
        payment_method=body.payment_method,
        expected_total_santim=body.expected_total_santim,
        idempotency_key=body.idempotency_key,
        language=lang,
    )
    response.status_code = 200 if replayed else 201
    response.headers["Cache-Control"] = "no-store"
    link = service.issue_tracking_link(order)
    return GuestOrderOut(
        order_code=order.code, tracking_path=link.path, tracking_expires_at=link.expires_at
    )


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


@router.post("/me/orders/{order_id}/reorder", response_model=ReorderOut, tags=["orders"])
def reorder_my_order(
    order_id: uuid.UUID,
    buyer: Buyer,
    request: Request,
    response: Response,
    db: Db,
    lang: LangQuery = "am",
) -> ReorderOut:
    """Order again in one tap (C-19): the order's items go back in the cart
    at today's prices; the buyer then checks out as usual."""
    cart = _cart(request, response, buyer, db, create=True)
    assert cart is not None
    return ReorderOut.model_validate(service.reorder(db, cart, buyer.user.id, order_id, lang))


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


@router.post(
    "/me/orders/{order_id}/seller-orders/{seller_order_id}/problem",
    response_model=OrderOut,
    tags=["orders"],
)
def report_a_problem(
    order_id: uuid.UUID,
    seller_order_id: uuid.UUID,
    body: ProblemIn,
    buyer: Buyer,
    db: Db,
    lang: LangQuery = "am",
) -> OrderOut:
    """ "Report a problem" inside the problem window (C-16). The part then
    waits for MarkX staff instead of completing by itself."""
    service.open_dispute(
        db, buyer.user, order_id, seller_order_id,
        problem_type=body.problem_type, description=body.description,
    )  # fmt: skip
    return OrderOut.model_validate(selectors.buyer_order(db, buyer.user.id, order_id, lang))


@router.post(
    "/me/orders/{order_id}/seller-orders/{seller_order_id}/problem/messages",
    response_model=OrderOut,
    tags=["orders"],
)
def add_to_my_problem(
    order_id: uuid.UUID,
    seller_order_id: uuid.UUID,
    body: ProblemMessageIn,
    buyer: Buyer,
    db: Db,
    lang: LangQuery = "am",
) -> OrderOut:
    service.buyer_add_to_dispute(db, buyer.user, order_id, seller_order_id, body=body.body)
    return OrderOut.model_validate(selectors.buyer_order(db, buyer.user.id, order_id, lang))


@router.get(
    "/me/orders/{order_id}/seller-orders/{seller_order_id}/alternatives",
    response_model=list[AlternativeOut],
    tags=["orders"],
)
def my_seller_order_alternatives(
    order_id: uuid.UUID, seller_order_id: uuid.UUID, buyer: Buyer, db: Db
) -> list[AlternativeOut]:
    """The next-best offer for each line of a part the seller declined or let
    expire (C-26)."""
    return [
        AlternativeOut.model_validate(row)
        for row in selectors.buyer_alternatives(db, buyer.user.id, order_id, seller_order_id)
    ]


@router.get("/track/{order_id}", response_model=OrderOut, tags=["orders"])
def track_order(
    order_id: uuid.UUID,
    expires: Annotated[int, Query(ge=0)],
    signature: Annotated[str, Query(min_length=20, max_length=64)],
    response: Response,
    db: Db,
    lang: LangQuery = "am",
) -> OrderOut:
    """The buyer's order page from a secure link, without signing in (D.14).
    It shows the handover code only on a guest's order, whose only page it
    is (C-07, D-108); never on a signed-in buyer's."""
    order = service.open_tracking_link(db, order_id, expires=expires, signature=signature)
    response.headers["Cache-Control"] = "no-store"
    return OrderOut.model_validate(selectors.tracking_view(db, order, lang))


@router.post(
    "/track/{order_id}/seller-orders/{seller_order_id}/cancel",
    response_model=OrderOut,
    tags=["orders"],
)
def guest_cancel_from_tracking_link(
    order_id: uuid.UUID,
    seller_order_id: uuid.UUID,
    expires: Annotated[int, Query(ge=0)],
    signature: Annotated[str, Query(min_length=20, max_length=64)],
    response: Response,
    db: Db,
    lang: LangQuery = "am",
) -> OrderOut:
    """A guest cancels one shop's part of their order from the secure link,
    before the shop answers (F-28, D-109). Only a guest's order: a signed-in
    buyer cancels from their own page. The answer is the link's page."""
    order = service.cancel_by_guest(
        db, order_id, seller_order_id, expires=expires, signature=signature
    )
    response.headers["Cache-Control"] = "no-store"
    return OrderOut.model_validate(selectors.tracking_view(db, order, lang))


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


@seller_router.get("/customers", response_model=list[SellerCustomerOut])
def list_seller_customers(
    context: ContactViewer,
    db: Db,
    q: Annotated[str | None, Query(max_length=60)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    lang: LangQuery = "am",
) -> list[SellerCustomerOut]:
    """The people this shop has served (S-11), newest first: only what its
    own order pages already show it. `q` finds a name or a phone number."""
    rows = selectors.seller_customers(db, context.seller.id, lang, query=q, limit=limit)
    return [SellerCustomerOut.model_validate(row) for row in rows]


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


@seller_router.post("/orders/{seller_order_id}/problem/reply", response_model=SellerOrderOut)
def reply_to_seller_order_problem(
    seller_order_id: uuid.UUID,
    body: ProblemMessageIn,
    context: OrderHandler,
    db: Db,
    lang: LangQuery = "am",
) -> SellerOrderOut:
    """The seller's answer to a problem the buyer reported (S-16)."""
    service.seller_reply_to_dispute(
        db, context.seller, context.member, seller_order_id, body=body.body
    )
    return _seller_order_out(db, context, seller_order_id, lang)


# -- the staff orders desk -----------------------------------------------------------


@admin_router.get("/problems", response_model=list[OpenProblemOut])
def staff_open_problems(
    staff: CaseHandler, db: Db, limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> list[OpenProblemOut]:
    """Reported problems waiting for a decision, the most urgent first (AD-09)."""
    return [
        OpenProblemOut.model_validate(row) for row in selectors.staff_open_problems(db, limit=limit)
    ]


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


@admin_router.post("/seller-orders/{seller_order_id}/resolve-problem", response_model=OrderOut)
def staff_resolve_problem(
    seller_order_id: uuid.UUID,
    body: ResolveProblemIn,
    staff: CaseHandler,
    request: Request,
    db: Db,
    lang: LangQuery = "am",
) -> OrderOut:
    """Decide a reported problem, with a written reason (D.17). Release 1
    records the outcome; MarkX moves no money."""
    seller_order = service.resolve_dispute(
        db, staff.actor(request), seller_order_id,
        decision=CaseDecision(body.decision), reason=body.reason,
        goods_returned=body.goods_returned,
    )  # fmt: skip
    return OrderOut.model_validate(selectors.staff_order_by_id(db, seller_order.order_id, lang))
