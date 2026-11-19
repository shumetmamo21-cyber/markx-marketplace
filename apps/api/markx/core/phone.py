"""Ethiopian mobile numbers (blueprint D.2, G.1, P.1).

People type the same number many ways. All of them are stored one way:
+2519XXXXXXXX (Ethio telecom) or +2517XXXXXXXX (Safaricom Ethiopia).
"""

from __future__ import annotations

import re

_SEPARATORS = re.compile(r"[\s\-().]")
_NATIONAL = re.compile(r"^(?:\+251|00251|251|0)?([79]\d{8})$")


class InvalidPhoneNumber(ValueError):
    pass


def normalize_phone(raw: str) -> str:
    """Return the number in international form, or raise InvalidPhoneNumber."""
    if not isinstance(raw, str):
        raise InvalidPhoneNumber("phone number must be text")
    compact = _SEPARATORS.sub("", raw.strip())
    match = _NATIONAL.fullmatch(compact)
    if match is None:
        raise InvalidPhoneNumber("not an Ethiopian mobile number")
    return f"+251{match.group(1)}"


def is_valid_phone(raw: str) -> bool:
    try:
        normalize_phone(raw)
    except InvalidPhoneNumber:
        return False
    return True


def mask_phone(phone: str) -> str:
    """For logs and screens that must not show a whole number: +2519••••4567."""
    if len(phone) < 9:
        return "•" * len(phone)
    return f"{phone[:5]}••••{phone[-4:]}"
