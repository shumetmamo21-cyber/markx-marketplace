"""The Ethiopian calendar (blueprint C-05, I.7; D-106).

The website shows dates in Amharic in the Ethiopian calendar with the
Gregorian date in brackets (`apps/web/src/lib/ethiopian.ts`, the same
arithmetic). The API needs it where it writes a date into words itself: the
weekly Telegram message (S-26) names the week it covers.

Pure arithmetic on whole days. The tests check it against fixed dates taken
from the calendar data in ICU and against the calendar's own rules for every
day from 1900 to 2100. The month names are those of the same data (CLDR).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Meskerem 1 of year 0 (Amete Mihret) as a proleptic Gregorian ordinal: with
# it, the last year of every four-year cycle is the leap year (year % 4 == 3).
_EPOCH = date(7, 8, 28).toordinal()

MONTHS_AM = (
    "መስከረም", "ጥቅምት", "ኅዳር", "ታኅሣሥ", "ጥር", "የካቲት", "መጋቢት",
    "ሚያዝያ", "ግንቦት", "ሰኔ", "ሐምሌ", "ነሐሴ", "ጳጉሜን",
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class EthiopianDate:
    year: int
    month: int  # 1 to 13; the 13th, Pagume, has 5 days, 6 in a leap year
    day: int


def to_ethiopian(day: date) -> EthiopianDate:
    days = day.toordinal() - _EPOCH
    cycle, in_cycle = divmod(days, 1461)
    year_in_cycle = in_cycle // 365 - in_cycle // 1460
    day_of_year = in_cycle % 365 + 365 * (in_cycle // 1460)
    return EthiopianDate(4 * cycle + year_in_cycle, day_of_year // 30 + 1, day_of_year % 30 + 1)


def amharic_date(day: date) -> str:
    """The day, the month's name and the year: "7 ኅዳር 2019"."""
    found = to_ethiopian(day)
    return f"{found.day} {MONTHS_AM[found.month - 1]} {found.year}"
