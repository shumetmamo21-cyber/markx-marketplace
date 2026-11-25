import { describe, expect, it } from "vitest";

import am from "../../messages/am.json";
import en from "../../messages/en.json";
import { guestDeliveryOptions, guestDetails, guestErrorText, trackPageHref } from "./guest-checkout";
import { apiErrorText } from "./i18n";

const ORDER = "01a21079-6d70-704b-b511-d0d2eebd95a9";
const PATH = `/api/v1/track/${ORDER}?expires=1769400000&signature=${"A".repeat(43)}`;

describe("the tracking link a guest is given (C-07, D-108)", () => {
  it("opens the order page on this site, in the page's language", () => {
    expect(trackPageHref(PATH, "en")).toBe(`/en/track/${ORDER}?expires=1769400000&signature=${"A".repeat(43)}`);
    expect(trackPageHref(PATH, "am")).toMatch(/^\/am\/track\//);
  });
  it("is refused when it is not the API's own tracking path", () => {
    for (const bad of [
      "https://evil.example/api/v1/track/x",
      "/api/v1/me/orders",
      `/api/v1/track/${ORDER}?expires=1&signature=short`,
      `/api/v1/track/${ORDER}?expires=1&signature=${"A".repeat(43)}&next=//evil.example`,
      `/api/v1/track/../../admin?expires=1&signature=${"A".repeat(43)}`,
    ]) {
      expect(trackPageHref(bad, "en"), bad).toBeNull();
    }
  });
});

describe("a guest's delivery choices", () => {
  const options = [{ method: "seller_rider" }, { method: "partner_courier" }, { method: "shop_collection" }];
  it("are delivery to the door, while collection is not allowed (the founder's decision)", () => {
    expect(guestDeliveryOptions(options, false).map((o) => o.method)).toEqual(["seller_rider", "partner_courier"]);
    expect(guestDeliveryOptions([{ method: "shop_collection" }], false)).toEqual([]);
  });
  it("include collection once operations allow it", () => {
    expect(guestDeliveryOptions(options, true)).toHaveLength(3);
    expect(guestDeliveryOptions(null, true)).toEqual([]);
  });
});

describe("a guest's details", () => {
  it("are sent trimmed, with empty notes left out", () => {
    expect(guestDetails({ recipient: "  Sara  ", phone: " 0911 777 001 ", area: "a1", landmark: " Blue gate ", notes: "  " })).toEqual({
      recipient_name: "Sara",
      phone: "0911 777 001",
      delivery_area_id: "a1",
      landmark: "Blue gate",
      driver_notes: null,
    });
  });
});

describe("the refusals a guest may meet are words in both languages", () => {
  const codes = [
    "guest_checkout_off",
    "guest_checkout_signed_in",
    "guest_collection_unavailable",
    "guest_network_limit",
    "new_buyer_order_too_large",
    "new_buyer_too_many_open_orders",
    "bot_check_failed",
    "area_unknown",
    "map_pin_incomplete",
    // The existing limits a guest also meets, in the words every page shares.
    "too_many_open_orders",
    "unconfirmed_offer_limit",
    "order_too_large",
    "rate_limited",
  ];
  it.each(codes)("%s", (code) => {
    expect(guestErrorText(en, code)).not.toBe(en.apiErrors.unknown);
    expect(guestErrorText(am, code)).not.toBe(am.apiErrors.unknown);
    expect(guestErrorText(am, code)).not.toMatch(/[a-z_]{6,}/);
  });
  it("never shows the raw code for one it does not know", () => {
    expect(guestErrorText(en, "something_new_from_the_api")).toBe(en.apiErrors.unknown);
  });
});

describe("a new buyer's refusals are words on every checkout (AD-13)", () => {
  it.each(["new_buyer_order_too_large", "new_buyer_too_many_open_orders"])("%s", (code) => {
    // In the shared words, so the signed-in checkout says them too once the
    // founder sets how long an account counts as new.
    expect(apiErrorText(en, code)).not.toBe(en.apiErrors.unknown);
    expect(apiErrorText(am, code)).not.toMatch(/[a-z_]{6,}/);
  });
});
