import { describe, expect, it } from "vitest";

import am from "../../messages/am.json";
import en from "../../messages/en.json";
import { CANCEL_REFUSALS, cancelRefusalText, cancelWords, guestMayCancel } from "./guest-cancel";
import { guestErrorText } from "./guest-checkout";

describe("a guest's cancel button on the tracking page (F-28, D-109)", () => {
  it("shows only on a guest's order, for a part the API says may be cancelled", () => {
    expect(guestMayCancel({ is_guest: true }, { can_cancel: true })).toBe(true);
    // After the shop answers, the API says no, and there is no button.
    expect(guestMayCancel({ is_guest: true }, { can_cancel: false })).toBe(false);
    // A signed-in buyer's link never acts (D-048): they cancel from their own page.
    expect(guestMayCancel({ is_guest: false }, { can_cancel: true })).toBe(false);
  });

  it.each([
    ["English", en],
    ["Amharic", am],
  ] as const)("speaks %s and names the shop", (_, t) => {
    const words = cancelWords(t, "Piassa Electronics");
    expect(words.ask).toContain("Piassa Electronics");
    for (const text of [words.hint, words.ask, words.yes, words.no, words.cancel, words.cancelling]) {
      expect(text.trim().length).toBeGreaterThan(2);
      expect(text).not.toMatch(/\{\w+\}/);
    }
    expect(new Set([words.yes, words.no, words.cancel]).size).toBe(3);
  });

  it.each(CANCEL_REFUSALS)("says why a cancel was refused, in both languages: %s", (code) => {
    for (const t of [en, am]) {
      const text = cancelRefusalText(cancelWords(t, "Piassa"), code);
      expect(text).not.toBe(t.orders.actionFailed);
      expect(text).not.toBe(t.apiErrors.unknown);
    }
    expect(cancelRefusalText(cancelWords(am, "Piassa"), code)).not.toMatch(/[a-z_]{6,}/);
  });

  it("never shows the raw code for a refusal it does not know", () => {
    expect(cancelRefusalText(cancelWords(en, "Piassa"), "something_new_from_the_api")).toBe(en.orders.actionFailed);
  });
});

describe("the cool-downs a guest may meet at checkout are words in both languages (D-109)", () => {
  it.each(["guest_network_cooldown", "cancellation_cooldown"])("%s", (code) => {
    expect(guestErrorText(en, code)).not.toBe(en.apiErrors.unknown);
    expect(guestErrorText(am, code)).not.toBe(am.apiErrors.unknown);
    expect(guestErrorText(am, code)).not.toMatch(/[a-z_]{6,}/);
  });
});
