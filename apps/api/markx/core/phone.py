"""Ethiopian mobile numbers (blueprint D.2, G.1, P.1).

People type the same number many ways. All of them are stored one way:
+2519XXXXXXXX (Ethio telecom) or +2517XXXXXXXX (Safaricom Ethiopia).

Digits typed in another script (Arabic-Indic ٠٩١١…, Persian, Devanagari,
full-width ０９１１… from some phone keyboards) are read as the digits 0 to 9
they stand for (D-098, B-3). Anything else that is not 0 to 9 is refused here,
so the database, which accepts only 0 to 9, never sees it. Ethiopic numerals
(፩ to ፱) have no zero and are not used for phone numbers; they are refused.
"""

from __future__ import annotations

import re
import unicodedata

_SEPARATORS = re.compile(r"[\s\-().]")
_NATIONAL = re.compile(r"^(?:\+251|00251|251|0)?([79][0-9]{8})$")


class InvalidPhoneNumber(ValueError):
    pass


def _plain_digits(raw: str) -> str:
    """Every decimal digit, in any script, as the ASCII digit 0 to 9."""
    return "".join(
        str(unicodedata.decimal(c)) if not c.isascii() and unicodedata.category(c) == "Nd" else c
        for c in raw
    )


def normalize_phone(raw: str) -> str:
    """Return the number in international form, or raise InvalidPhoneNumber."""
    if not isinstance(raw, str):
        raise InvalidPhoneNumber("phone number must be text")
    compact = _SEPARATORS.sub("", _plain_digits(raw).strip())
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
