import { describe, expect, it } from "vitest";

import { noticePoints, noticeReady, type OrderNotice } from "./order-notice";

const NOTICE: OrderNotice = {
  version: "c27-draft-2026-11-26",
  provisional: true,
  title: "Before you place your order",
  points: [
    "You are buying from Abebe Electronics PLC.",
    "  You pay the shop when you receive your order.  ",
    "",
    "Check the goods before you pay.",
  ],
};

describe("the notice before ordering (C-27, D-110)", () => {
  it("shows every point the API sent, trimmed, and leaves out empty ones", () => {
    expect(noticePoints(NOTICE)).toEqual([
      "You are buying from Abebe Electronics PLC.",
      "You pay the shop when you receive your order.",
      "Check the goods before you pay.",
    ]);
    expect(noticePoints(null)).toEqual([]);
    expect(noticePoints(undefined)).toEqual([]);
  });

  it("offers Place order only once the notice is there to read", () => {
    expect(noticeReady(NOTICE)).toBe(true);
    // An answer without the notice (an older API, a broken reply): no button.
    expect(noticeReady(undefined)).toBe(false);
    expect(noticeReady(null)).toBe(false);
    expect(noticeReady({ ...NOTICE, points: [] })).toBe(false);
    expect(noticeReady({ ...NOTICE, points: ["  ", ""] })).toBe(false);
    expect(noticeReady({ ...NOTICE, title: " " })).toBe(false);
  });
});
