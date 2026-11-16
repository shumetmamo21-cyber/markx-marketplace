"""Money as whole santim (blueprint G.1). One birr is 100 santim.

Never a float and never a rounded decimal: 0.1 + 0.2 != 0.3 in binary floating
point, and the error compounds across cart lines, fees and refunds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

SUPPORTED_CURRENCIES = ("ETB",)
SANTIM_PER_BIRR = 100
BPS_DENOMINATOR = 10_000  # 100% in basis points; 250 bps is 2.50%

Language = Literal["am", "en"]

_BIRR_INPUT = re.compile(r"^(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?$")


@dataclass(frozen=True, slots=True, order=False)
class Money:
    amount: int
    currency: str = "ETB"

    def __post_init__(self) -> None:
        # bool is a subclass of int; a True/False amount is always a bug.
        if not isinstance(self.amount, int) or isinstance(self.amount, bool):
            raise TypeError(f"amount must be an integer number of santim, got {self.amount!r}")
        if self.currency not in SUPPORTED_CURRENCIES:
            raise ValueError(f"unsupported currency {self.currency!r}")

    @classmethod
    def zero(cls, currency: str = "ETB") -> Money:
        return cls(0, currency)

    @classmethod
    def from_birr_text(cls, text: str, currency: str = "ETB") -> Money:
        """Parse what a seller types: "12500", "12,500" or "12,500.50"."""
        match = _BIRR_INPUT.fullmatch(text.strip())
        if match is None:
            raise ValueError(f"not a valid birr amount: {text!r}")
        birr = int(match.group(1).replace(",", ""))
        santim_text = match.group(2) or ""
        santim = int(santim_text.ljust(2, "0")) if santim_text else 0
        return cls(birr * SANTIM_PER_BIRR + santim, currency)

    def _require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(f"currency mismatch: {self.currency} and {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, quantity: int) -> Money:
        if not isinstance(quantity, int) or isinstance(quantity, bool):
            raise TypeError("money can only be multiplied by a whole quantity")
        return Money(self.amount * quantity, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount <= other.amount

    def portion_bps(self, bps: int) -> Money:
        """A share of this amount in basis points, rounded half up to a santim."""
        if not isinstance(bps, int) or isinstance(bps, bool) or not 0 <= bps <= BPS_DENOMINATOR:
            raise ValueError(f"basis points must be a whole number from 0 to 10000, got {bps!r}")
        if self.amount < 0:
            raise ValueError("a share of a negative amount is not defined")
        return Money((self.amount * bps + BPS_DENOMINATOR // 2) // BPS_DENOMINATOR, self.currency)

    def format(self, language: Language = "en") -> str:
        """ "ETB 12,500" in English and "12,500 ብር" in Amharic (blueprint I.7)."""
        sign = "-" if self.amount < 0 else ""
        birr, santim = divmod(abs(self.amount), SANTIM_PER_BIRR)
        number = f"{birr:,}" if santim == 0 else f"{birr:,}.{santim:02d}"
        if language == "am":
            return f"{sign}{number} ብር"
        return f"{sign}{self.currency} {number}"
