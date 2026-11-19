"""Short public codes people read aloud (blueprint G.1, P.1).

Order codes look like MX-7K3F9Q. The alphabet leaves out every character that
is confused when read or typed: 0/O, 1/I/L, 2/Z, 5/S and 8/B.
"""

from __future__ import annotations

import re
import secrets

ORDER_CODE_ALPHABET = "34679ACDEFGHJKMNPQRTUVWXY"
ORDER_CODE_PREFIX = "MX-"
ORDER_CODE_LENGTH = 6

_ORDER_CODE = re.compile(rf"^MX-[{ORDER_CODE_ALPHABET}]{{{ORDER_CODE_LENGTH}}}$")


def new_order_code() -> str:
    body = "".join(secrets.choice(ORDER_CODE_ALPHABET) for _ in range(ORDER_CODE_LENGTH))
    return f"{ORDER_CODE_PREFIX}{body}"


def is_order_code(value: str) -> bool:
    return _ORDER_CODE.fullmatch(value) is not None


def normalize_order_code(raw: str) -> str | None:
    """Accept "mx7k3f9q", "MX 7K3F9Q" or "MX-7K3F9Q"; return canonical form or None."""
    compact = re.sub(r"[\s\-]", "", raw.strip().upper())
    if compact.startswith("MX"):
        compact = compact[2:]
    candidate = f"{ORDER_CODE_PREFIX}{compact}"
    return candidate if is_order_code(candidate) else None


def new_numeric_code(digits: int = 6) -> str:
    """A uniformly random decimal code, keeping leading zeros."""
    return f"{secrets.randbelow(10**digits):0{digits}d}"
