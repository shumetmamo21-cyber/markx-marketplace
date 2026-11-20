"""Feature switches and limits (blueprint F.2, Q.6 "Switches").

Every setting has a default in code, so a fresh database behaves sensibly. A
row in the `settings` table overrides the default. Staff change settings in the
admin console, and every change is written to the audit log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from markx.core.errors import NotFound, ValidationFailed
from markx.core.models import Setting
from markx.core.settings_am import DESCRIPTIONS_AM

Kind = Literal["bool", "int", "str"]


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    default: bool | int | str
    kind: Kind
    description: str
    minimum: int | None = None
    maximum: int | None = None


_SPECS: tuple[SettingSpec, ...] = (
    # Sellers
    SettingSpec(
        "sellers.invite_only", True, "bool", "Only invited sellers may apply (blueprint D.3)."
    ),
    SettingSpec(
        "sellers.individual_enabled",
        False,
        "bool",
        "Individual sellers may apply. Off until the founder's legal check (section O, question 10).",
    ),
    SettingSpec(
        "sellers.min_level_to_publish",
        2,
        "int",
        "Verification level a seller needs before its offers are shown.",
        0,
        3,
    ),
    SettingSpec(
        "sellers.invitation_valid_days",
        14,
        "int",
        "Days an invitation to apply stays open.",
        1,
        90,
    ),
    SettingSpec(
        "sellers.starter_seats",
        2,
        "int",
        "Members a seller on the free plan may have, the owner included (blueprint D.4).",
        1,
        50,
    ),
    SettingSpec(
        "sellers.payout_cooling_off_hours",
        72,
        "int",
        "Hours before a changed payout account takes effect (S-13).",
        0,
        720,
    ),
    SettingSpec(
        "sellers.recheck_after_days",
        365,
        "int",
        "Days after which a seller's verification is checked again (blueprint D.3).",
        30,
        730,
    ),
    SettingSpec(
        "sellers.document_max_bytes",
        5_000_000,
        "int",
        "Largest document photo a seller may upload, in bytes.",
        10_000,
        20_000_000,
    ),
    # Offers
    SettingSpec(
        "offers.sink_after_days",
        3,
        "int",
        "An offer whose price was not confirmed for this many days sinks in the ranking.",
        1,
        60,
    ),
    SettingSpec(
        "offers.stale_after_days",
        14,
        "int",
        "An offer whose price was not confirmed for this many days is hidden (blueprint D.7).",
        1,
        90,
    ),
    # Orders
    SettingSpec(
        "orders.response_window_minutes",
        30,
        "int",
        "How long a seller has to answer an order, in business hours.",
        5,
        1440,
    ),
    SettingSpec(
        "orders.business_open_hour",
        8,
        "int",
        "Business day start, Addis Ababa time (24-hour clock).",
        0,
        23,
    ),
    SettingSpec(
        "orders.business_close_hour",
        20,
        "int",
        "Business day end, Addis Ababa time (24-hour clock).",
        1,
        24,
    ),
    SettingSpec(
        "orders.fulfilment_hold_days",
        14,
        "int",
        "Days a confirmed order keeps its stock held while it is packed and delivered.",
        1,
        90,
    ),
    SettingSpec(
        "orders.problem_window_hours",
        72,
        "int",
        "How long after delivery a buyer may report a problem.",
        1,
        720,
    ),
    SettingSpec(
        "orders.problem_decision_hours",
        48,
        "int",
        "Hours staff have to decide a reported problem (blueprint D.17).",
        1,
        720,
    ),
    SettingSpec(
        "orders.max_open_direct_orders",
        3,
        "int",
        "Open pay-at-the-door orders one buyer may hold (blueprint D.10, AD-13).",
        1,
        50,
    ),
    SettingSpec(
        "orders.max_order_value_santim",
        30_000_000,
        "int",
        "Largest order total accepted, in santim (AD-13).",
        100,
        10_000_000_000,
    ),
    # Order life-cycle hardening (D-099). PROVISIONAL (P-099-1 to P-099-6,
    # D-099): every value below is the engineer's safe default, a business
    # choice THE FOUNDER MUST CONFIRM OR CHANGE BEFORE MARKX GOES LIVE.
    #   M6: a part on the road or after a failed handover that nobody moves on
    #   is reported to staff once its limit passes, and stops taking one of the
    #   buyer's open-order places. It is never ended and its stock is never
    #   released by the system (`orders.service.stalled_delivery`).
    SettingSpec(
        "orders.out_for_delivery_limit_hours",
        48,
        "int",
        "PROVISIONAL (P-099-1), to be confirmed before going live: hours a part may stay out "
        "for delivery (never less than its promised delivery time) before staff are asked to "
        "follow it up; it then stops counting against the buyer's open orders. Its stock stays "
        "held until the shop or staff settle it.",
        1,
        720,
    ),
    SettingSpec(
        "orders.delivery_failed_limit_hours",
        72,
        "int",
        "PROVISIONAL (P-099-2), to be confirmed before going live: hours a part may wait after "
        "a failed handover, neither retried nor returned, before staff are asked to follow it "
        "up; it then stops counting against the buyer's open orders. Its stock stays held "
        "until the shop or staff settle it.",
        1,
        720,
    ),
    #   H2: how much of a shop's stock one buyer's unanswered orders may hold,
    #   and a pause after repeated cancellations (`orders.service.place_order`).
    SettingSpec(
        "orders.max_unconfirmed_units_per_offer",
        5,
        "int",
        "PROVISIONAL (P-099-3), to be confirmed before going live: units of one offer that "
        "one buyer's orders may hold while the shop has not yet confirmed them.",
        1,
        100,
    ),
    SettingSpec(
        "orders.max_unconfirmed_units_per_seller",
        10,
        "int",
        "PROVISIONAL (P-099-4), to be confirmed before going live: units of one shop's stock, "
        "all its offers together, that one buyer's orders may hold while the shop has not yet "
        "confirmed them.",
        1,
        200,
    ),
    SettingSpec(
        "orders.cancellations_before_cooldown",
        3,
        "int",
        "PROVISIONAL (P-099-5), to be confirmed before going live: orders a buyer may cancel "
        "within the cool-down period below before new orders are refused for a while.",
        1,
        50,
    ),
    SettingSpec(
        "orders.cancellation_cooldown_hours",
        24,
        "int",
        "PROVISIONAL (P-099-6), to be confirmed before going live: the period in which "
        "cancellations are counted; a buyer in a cool-down may order again once fewer than the "
        "allowed number of cancellations fall within it.",
        1,
        720,
    ),
    # Seller performance (blueprint S-26; D-069)
    SettingSpec(
        "sellers.weekly_report_enabled",
        True,
        "bool",
        "Send every trading store its weekly performance message (S-26) after each "
        "week ends, Monday to Sunday in Addis Ababa time.",
    ),
    # Reviews (blueprint D.15, H.4; D-066)
    SettingSpec(
        "reviews.window_days",
        60,
        "int",
        "Days after a part completes during which its buyer may review it, and edit "
        "the review until the seller replies.",
        1,
        365,
    ),
    SettingSpec(
        "reviews.per_buyer_per_day",
        10,
        "int",
        "Reviews one buyer may write in a day (blueprint D.15: rate limits against fake reviews).",
        1,
        100,
    ),
    SettingSpec(
        "reviews.hold_after_same_seller",
        3,
        "int",
        "A buyer's review of a seller they already reviewed this many times in 30 days "
        "waits for staff before it is shown (a pattern check, D.15).",
        1,
        50,
    ),
    # Pictures (blueprint F.6, S-06, C-16; D-062)
    SettingSpec(
        "images.max_upload_bytes",
        8_000_000,
        "int",
        "Largest photo accepted for upload, in bytes. Phones compress before sending "
        "(S-06), so a real photo is far smaller.",
        100_000,
        25_000_000,
    ),
    SettingSpec(
        "images.max_catalogue_per_product",
        12,
        "int",
        "Catalogue pictures one product may have, not counting removed ones.",
        1,
        50,
    ),
    SettingSpec(
        "images.max_real_photos_per_seller",
        6,
        "int",
        "Real photos one seller may show on one product, not counting removed ones (D.5).",
        1,
        20,
    ),
    SettingSpec(
        "images.max_problem_photos_per_side",
        5,
        "int",
        "Evidence photos the buyer, and separately the seller, may add to one problem (C-16).",
        1,
        20,
    ),
    # Search (blueprint H.2: "throttles on search"; D-059)
    SettingSpec(
        "search.requests_per_ip_per_minute",
        120,
        "int",
        "Searches one network address may run per minute; more are refused for the rest "
        "of the minute (blueprint H.2, D-059).",
        10,
        100_000,
    ),
    SettingSpec(
        "search.suggestions_per_ip_per_minute",
        300,
        "int",
        "Name suggestions one network address may ask for per minute, as a buyer types "
        "(blueprint H.2, D-059).",
        10,
        100_000,
    ),
    # Retention. PROVISIONAL (F-08, D-083): search logs 180 days, rate-limit
    # counters a day after their window; the job is `retention.prune`.
    #   The engineer's guess at the founder's request; THE FOUNDER MUST CONFIRM
    #   OR CHANGE BOTH BEFORE MARKX GOES LIVE.
    SettingSpec(
        "retention.search_queries_days",
        180,
        "int",
        "PROVISIONAL (F-08), to be confirmed before going live: days a search is kept for "
        "the zero-result report; a daily job deletes older ones.",
        30,
        3650,
    ),
    SettingSpec(
        "retention.rate_limit_counters_days",
        1,
        "int",
        "PROVISIONAL (F-08), to be confirmed before going live: days a rate-limit counter "
        "is kept after its window has ended; a daily job deletes older ones.",
        1,
        30,
    ),
    # Sign-in
    SettingSpec(
        "auth.otp_per_phone_per_hour",
        5,
        "int",
        "Login codes one phone number may request per hour.",
        1,
        100,
    ),
    SettingSpec(
        "auth.otp_per_ip_per_hour",
        20,
        "int",
        "Login codes one network address may request per hour.",
        1,
        1000,
    ),
    SettingSpec(
        "auth.sms_daily_budget",
        500,
        "int",
        "SMS messages MarkX may send per day; sending stops when spent (blueprint D.2).",
        0,
        1_000_000,
    ),
    SettingSpec(
        "auth.otp_resend_cooldown_seconds",
        60,
        "int",
        "Seconds a phone number must wait before another login code is sent to it (D-089).",
        0,
        3600,
    ),
    SettingSpec(
        "sms.failure_alert_percent",
        20,
        "int",
        "Share of the last hour's SMS that failed or went unconfirmed, in percent, at which "
        "the founder is alerted (D-089).",
        1,
        100,
    ),
    SettingSpec(
        "sms.failure_alert_min_messages",
        5,
        "int",
        "SMS attempts the last hour must hold before the failure share is judged (D-089).",
        1,
        10_000,
    ),
    SettingSpec(
        "sms.unfinished_alert_minutes",
        15,
        "int",
        "Minutes an SMS may wait without a final status before the founder is alerted (D-089).",
        1,
        1440,
    ),
    # Notifications (D-092). SMS for notifications is OFF until the founder
    # chooses a provider and approves what it costs (N-1); its budget is its
    # own, so order alerts can never use up the sign-in codes' budget.
    SettingSpec(
        "notifications.sms_enabled",
        False,
        "bool",
        "Send order notifications by SMS as well as in the app. Off until the founder chooses "
        "a channel and approves the cost (N-1, D-092).",
    ),
    SettingSpec(
        "notifications.sms_only_without_telegram",
        True,
        "bool",
        "When notification SMS is on, send it only to people Telegram cannot reach: not "
        "linked, or no Telegram provider configured (D-092).",
    ),
    SettingSpec(
        "notifications.sms_daily_budget",
        200,
        "int",
        "Notification SMS MarkX may send per day, separate from the sign-in codes' budget; "
        "sending stops when spent (D-092).",
        0,
        1_000_000,
    ),
    SettingSpec(
        "notifications.sms_per_person_per_hour",
        6,
        "int",
        "Notification SMS one person may receive per hour (D-092).",
        1,
        100,
    ),
    SettingSpec(
        "notifications.sms_cooldown_seconds",
        120,
        "int",
        "Seconds between two notification SMS to the same number; one that comes sooner is "
        "skipped, the in-app message stays (D-092).",
        0,
        3600,
    ),
    SettingSpec(
        "notifications.failure_alert_min",
        3,
        "int",
        "Notifications that failed or went unconfirmed on an outside channel in the last hour "
        "at which the founder is alerted (D-092).",
        1,
        10_000,
    ),
    SettingSpec(
        "notifications.stale_alert_minutes",
        30,
        "int",
        "Minutes a notification may wait half-sent before the founder is alerted (D-092).",
        5,
        1440,
    ),
    SettingSpec(
        "orders.response_reminder_minutes",
        10,
        "int",
        "Minutes before an unanswered order's deadline at which its shop is reminded, once "
        "(D-092).",
        1,
        720,
    ),
    # Trust
    SettingSpec(
        "disputes.decision_due_hours",
        48,
        "int",
        "Hours within which staff decide a problem case (blueprint D.17).",
        1,
        720,
    ),
    # Payments
    SettingSpec(
        "payments.protected_enabled",
        False,
        "bool",
        "Protected checkout through a licensed provider. Release 2; needs Gate C.",
    ),
)

SETTINGS: dict[str, SettingSpec] = {spec.key: spec for spec in _SPECS}


def _coerce(spec: SettingSpec, value: Any) -> bool | int | str:
    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise ValidationFailed("setting_invalid", f"{spec.key} must be true or false")
        return value
    if spec.kind == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValidationFailed("setting_invalid", f"{spec.key} must be a whole number")
        if spec.minimum is not None and value < spec.minimum:
            raise ValidationFailed("setting_invalid", f"{spec.key} must be at least {spec.minimum}")
        if spec.maximum is not None and value > spec.maximum:
            raise ValidationFailed("setting_invalid", f"{spec.key} must be at most {spec.maximum}")
        return value
    if not isinstance(value, str):
        raise ValidationFailed("setting_invalid", f"{spec.key} must be text")
    return value


def get_setting(db: Session, key: str) -> bool | int | str:
    spec = SETTINGS.get(key)
    if spec is None:
        raise KeyError(f"unknown setting {key!r}")
    row = db.get(Setting, key)
    if row is None:
        return spec.default
    try:
        return _coerce(spec, row.value)
    except ValidationFailed:
        # A hand-edited bad value must not take the site down; fall back.
        return spec.default


def get_int(db: Session, key: str) -> int:
    value = get_setting(db, key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"setting {key!r} is not a whole number")
    return value


def get_bool(db: Session, key: str) -> bool:
    value = get_setting(db, key)
    if not isinstance(value, bool):
        raise TypeError(f"setting {key!r} is not a switch")
    return value


def set_setting(db: Session, key: str, value: Any) -> tuple[Any, Any]:
    """Store a new value. Returns (before, after) for the audit log."""
    spec = SETTINGS.get(key)
    if spec is None:
        raise NotFound("setting_not_found", f"no setting named {key}")
    new_value = _coerce(spec, value)
    before = get_setting(db, key)
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=new_value, description=spec.description))
    else:
        row.value = new_value
    db.flush()
    return before, new_value


def list_settings(db: Session) -> list[dict[str, Any]]:
    stored = {row.key: row.value for row in db.query(Setting).all()}
    return [
        {
            "key": spec.key,
            "kind": spec.kind,
            "description": spec.description,
            "description_am": DESCRIPTIONS_AM[spec.key],
            "default": spec.default,
            "value": get_setting(db, spec.key),
            "is_overridden": spec.key in stored,
        }
        for spec in _SPECS
    ]
