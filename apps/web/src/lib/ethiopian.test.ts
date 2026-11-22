import { describe, expect, it } from "vitest";

import { ETHIOPIAN_MONTHS, addisParts, ethiopianClockText, ethiopianDateText, toEthiopian } from "./ethiopian";

// The calendar data built into Node (ICU, from CLDR) is the reference: the
// arithmetic must give the same day, month and month name for every day.
const icuDay = new Intl.DateTimeFormat("en-u-ca-ethiopic", { timeZone: "UTC", year: "numeric", month: "numeric", day: "numeric" });
const icuMonth = new Intl.DateTimeFormat("am-ET-u-ca-ethiopic", { timeZone: "UTC", month: "long" });
const icuDayPart = new Intl.DateTimeFormat("am-ET", { timeZone: "UTC", hour: "numeric", minute: "2-digit", dayPeriod: "long" });

describe("toEthiopian", () => {
  it("agrees with the calendar data in ICU on every day from 1900 to 2100", () => {
    let checked = 0;
    for (let time = Date.UTC(1900, 0, 1, 12); time <= Date.UTC(2100, 11, 31, 12); time += 86_400_000) {
      const day = new Date(time);
      const parts = Object.fromEntries(icuDay.formatToParts(day).map((part) => [part.type, part.value]));
      const mine = toEthiopian(day.getUTCFullYear(), day.getUTCMonth() + 1, day.getUTCDate());
      if (mine.year !== Number(parts.year) || mine.month !== Number(parts.month) || mine.day !== Number(parts.day)) {
        expect({ day: day.toISOString().slice(0, 10), mine }).toEqual({ day: day.toISOString().slice(0, 10), mine: parts });
      }
      if (ETHIOPIAN_MONTHS[mine.month - 1] !== icuMonth.format(day)) {
        expect(ETHIOPIAN_MONTHS[mine.month - 1]).toBe(icuMonth.format(day));
      }
      checked += 1;
    }
    expect(checked).toBe(73_414);
  });
  it("knows the days everyone knows", () => {
    expect(toEthiopian(2023, 9, 12)).toEqual({ year: 2016, month: 1, day: 1 }); // New Year, Meskerem 1
    expect(toEthiopian(2023, 9, 11)).toEqual({ year: 2015, month: 13, day: 6 }); // Pagume 6 of a leap year
    expect(toEthiopian(2026, 1, 7)).toEqual({ year: 2018, month: 4, day: 29 }); // Genna, Tahsas 29
    expect(ethiopianDateText(toEthiopian(2026, 11, 22))).toBe("13 ኅዳር 2019");
  });
});

describe("ethiopianClockText", () => {
  it("counts the hours from sunrise: 9:00 in the morning is 3:00 (blueprint I.7)", () => {
    expect(ethiopianClockText(9, 0)).toBe("ጥዋት 3:00");
    expect(ethiopianClockText(6, 0)).toBe("ጥዋት 12:00");
    expect(ethiopianClockText(7, 15)).toBe("ጥዋት 1:15");
    expect(ethiopianClockText(12, 0)).toBe("ከሰዓት 6:00");
    expect(ethiopianClockText(15, 45)).toBe("ከሰዓት 9:45");
    expect(ethiopianClockText(18, 0)).toBe("በምሽት 12:00");
    expect(ethiopianClockText(23, 59)).toBe("በምሽት 5:59");
    expect(ethiopianClockText(0, 30)).toBe("በሌሊት 6:30");
    expect(ethiopianClockText(5, 5)).toBe("በሌሊት 11:05");
  });
  it("names each part of the day with ICU's Amharic words", () => {
    for (let hour = 0; hour < 24; hour += 1) {
      const words = icuDayPart.formatToParts(new Date(Date.UTC(2026, 10, 22, hour, 5))).find((part) => part.type === "dayPeriod")?.value;
      expect(ethiopianClockText(hour, 5).split(" ")[0], `hour ${hour}`).toBe(words);
    }
  });
});

describe("addisParts", () => {
  it("is the day and time in Addis Ababa, three hours ahead of UTC", () => {
    expect(addisParts("2026-11-22T21:30:00Z")).toEqual({ year: 2026, month: 11, day: 23, hour: 0, minute: 30 });
    expect(addisParts("2026-11-22T06:30:00+00:00")).toEqual({ year: 2026, month: 11, day: 22, hour: 9, minute: 30 });
  });
});
