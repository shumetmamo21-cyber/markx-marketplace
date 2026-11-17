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
            "default": spec.default,
            "value": get_setting(db, spec.key),
            "is_overridden": spec.key in stored,
        }
        for spec in _SPECS
    ]
