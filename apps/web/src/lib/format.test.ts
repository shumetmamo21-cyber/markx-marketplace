import { describe, expect, it } from "vitest";

import { formatPrice, formatShare, timeAgo } from "./format";
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
