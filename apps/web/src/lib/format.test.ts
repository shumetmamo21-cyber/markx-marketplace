import { describe, expect, it } from "vitest";

import { addisDay, formatDate, formatDateTime, formatPrice, formatRating, formatShare, timeAgo } from "./format";
import { fill } from "./i18n";

describe("formatPrice", () => {
  it("writes birr as the blueprint shows them (I.7)", () => {
    expect(formatPrice(1_250_000, "en")).toBe("ETB 12,500");
    expect(formatPrice(1_250_000, "am")).toBe("12,500 ብር");
  });
  it("shows santim only when there are some", () => {
    expect(formatPrice(1_250_050, "en")).toBe("ETB 12,500.50");
    expect(formatPrice(5, "en")).toBe("ETB 0.05");
  });
});

describe("timeAgo", () => {
  const now = new Date("2026-11-17T12:00:00Z");
  it("says how long ago a price was confirmed", () => {
    expect(timeAgo("2026-11-17T09:00:00Z", "en", now)).toBe("3 hours ago");
    expect(timeAgo("2026-11-15T12:00:00Z", "en", now)).toBe("2 days ago");
    expect(timeAgo("2026-11-17T11:59:50Z", "en", now)).toBe("this minute");
  });
  it("never shows a time in the future", () => {
    expect(timeAgo("2026-11-17T13:00:00Z", "en", now)).toBe("this minute");
  });
});

describe("fill", () => {
  it("replaces named placeholders and leaves unknown ones", () => {
    expect(fill("{count} sellers from {price}", { count: 3, price: "ETB 9" })).toBe(
      "3 sellers from ETB 9",
    );
    expect(fill("{missing}", {})).toBe("{missing}");
  });
});

describe("isPast", () => {
  it("compares with the given moment", async () => {
    const { isPast } = await import("./format");
    const now = new Date("2026-11-17T12:00:00Z");
    expect(isPast("2026-11-17T11:59:00Z", now)).toBe(true);
    expect(isPast("2026-11-17T12:01:00Z", now)).toBe(false);
  });
});

describe("formatShare", () => {
  it("shows a share from the API as a whole percentage", () => {
    expect(formatShare(0.873)).toBe("87%");
    expect(formatShare(0)).toBe("0%");
    expect(formatShare(1)).toBe("100%");
    expect(formatShare(0.005)).toBe("1%");
  });
  it("never shows more than all or less than none", () => {
    expect(formatShare(1.2)).toBe("100%");
    expect(formatShare(-0.1)).toBe("0%");
  });
});

describe("addisDay", () => {
  it("is the day in Addis Ababa, three hours ahead of UTC", () => {
    expect(addisDay(new Date("2026-11-17T12:00:00Z"))).toBe("2026-11-17");
    expect(addisDay(new Date("2026-11-17T21:30:00Z"))).toBe("2026-11-18");
    expect(addisDay(new Date("2026-12-31T20:59:00Z"))).toBe("2026-12-31");
  });
});

describe("formatRating", () => {
  it("shows the API's average to one place", () => {
    expect(formatRating(4.25)).toBe("4.3");
    expect(formatRating(4.24)).toBe("4.2");
    expect(formatRating(5)).toBe("5.0");
    expect(formatRating(1)).toBe("1.0");
  });
});

describe("formatDateTime (blueprint C-05, I.7)", () => {
  it("shows Amharic dates in the Ethiopian calendar, the Gregorian date in brackets, on the Ethiopian clock", () => {
    // 06:30 UTC is 9:30 in the morning in Addis Ababa: 3:30 on the Ethiopian clock.
    expect(formatDateTime("2026-11-22T06:30:00Z", "am")).toBe("13 ኅዳር 2019 (22 ኖቬም 2026) ጥዋት 3:30");
    // 21:30 UTC is already the next day in Addis Ababa, half past midnight.
    expect(formatDateTime("2026-11-22T21:30:00Z", "am")).toBe("14 ኅዳር 2019 (23 ኖቬም 2026) በሌሊት 6:30");
    expect(formatDateTime("2023-09-12T15:00:00Z", "am")).toBe("1 መስከረም 2016 (12 ሴፕቴ 2023) በምሽት 12:00");
  });
  it("leaves English dates Gregorian, on the 24-hour clock", () => {
    expect(formatDateTime("2026-11-22T06:30:00Z", "en")).toBe("22 Nov 2026, 09:30");
  });
});

describe("formatDate", () => {
  it("shows a calendar day in both calendars in Amharic, and Gregorian in English", () => {
    expect(formatDate("2026-11-16", "am")).toBe("7 ኅዳር 2019 (16 ኖቬም 2026)");
    expect(formatDate("2027-09-11", "am")).toBe("6 ጳጉሜን 2019 (11 ሴፕቴ 2027)");
    expect(formatDate("2026-11-16", "en")).toBe("16 Nov 2026");
  });
  it("shows anything that is not a real day as it came", () => {
    expect(formatDate("2026-02-30", "am")).toBe("2026-02-30");
    expect(formatDate("soon", "en")).toBe("soon");
  });
});
