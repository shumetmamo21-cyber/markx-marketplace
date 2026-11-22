"""The Ethiopian calendar (C-05, D-106): the arithmetic, and the Amharic
weekly Telegram message that names its week in it. No database."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from markx.core.ethiopian import MONTHS_AM, EthiopianDate, amharic_date, to_ethiopian
from markx.notifications import texts as outside_texts

# Days taken from the calendar data in ICU (Node 22, `en-u-ca-ethiopic`).
KNOWN = [
    (date(2023, 9, 12), EthiopianDate(2016, 1, 1)),  # New Year, Meskerem 1
    (date(2023, 9, 11), EthiopianDate(2015, 13, 6)),  # Pagume 6 of a leap year
    (date(2024, 9, 11), EthiopianDate(2017, 1, 1)),
    (date(2027, 9, 11), EthiopianDate(2019, 13, 6)),
    (date(2027, 9, 12), EthiopianDate(2020, 1, 1)),
    (date(2026, 1, 7), EthiopianDate(2018, 4, 29)),  # Genna, Tahsas 29
    (date(2026, 11, 16), EthiopianDate(2019, 3, 7)),
    (date(2026, 11, 22), EthiopianDate(2019, 3, 13)),
    (date(2000, 2, 29), EthiopianDate(1992, 6, 21)),
    (date(1990, 1, 1), EthiopianDate(1982, 4, 23)),
    (date(2100, 12, 31), EthiopianDate(2093, 4, 21)),
]


@pytest.mark.parametrize(("gregorian", "ethiopian"), KNOWN)
def test_known_days(gregorian: date, ethiopian: EthiopianDate) -> None:
    assert to_ethiopian(gregorian) == ethiopian


def test_every_day_from_1900_to_2100_follows_the_calendars_rules() -> None:
    day, last = date(1900, 1, 1), date(2100, 12, 31)
    before = to_ethiopian(day - timedelta(days=1))
    while day <= last:
        now = to_ethiopian(day)
        if now.year == before.year and now.month == before.month:
            assert now.day == before.day + 1, day
        elif now.year == before.year:
            assert (now.month, now.day) == (before.month + 1, 1), day
            assert before.day == 30, day  # twelve months of thirty days
        else:
            assert (now.year, now.month, now.day) == (before.year + 1, 1, 1), day
            # Pagume has six days in the year before a year divisible by four.
            assert (before.month, before.day) == (13, 6 if before.year % 4 == 3 else 5), day
            assert (day.month, day.day) in ((9, 11), (9, 12)), day
        before, day = now, day + timedelta(days=1)


def test_a_date_in_amharic_words() -> None:
    assert amharic_date(date(2026, 11, 16)) == "7 ኅዳር 2019"
    assert amharic_date(date(2027, 9, 11)) == "6 ጳጉሜን 2019"
    assert len(MONTHS_AM) == 13


WEEK = {
    "week_start": "2026-11-16", "orders_received": 3, "orders_confirmed": 2,
    "completed": 1, "prices_to_confirm": 0,
}  # fmt: skip


def test_the_weekly_message_names_its_week_in_the_ethiopian_calendar_in_amharic() -> None:
    amharic = outside_texts.render_telegram("seller.weekly_report", WEEK, "am")
    assert "ከ7 ኅዳር 2019 (2026-11-16) ጀምሮ" in amharic
    english = outside_texts.render_telegram("seller.weekly_report", WEEK, "en")
    assert english.startswith("MarkX weekly report, week from 2026-11-16: 3 orders received")


@pytest.mark.parametrize("lang", ["am", "en"])
def test_the_weekly_message_refuses_a_day_that_does_not_exist(lang: str) -> None:
    with pytest.raises(outside_texts.UnsafeText):
        outside_texts.render_telegram(
            "seller.weekly_report", {**WEEK, "week_start": "2026-02-30"}, lang
        )
