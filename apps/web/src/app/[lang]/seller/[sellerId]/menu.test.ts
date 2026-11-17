import { describe, expect, it } from "vitest";

import en from "../../../../../messages/en.json";
import { sellerMenu } from "./menu";

// Blueprint C.3, as apps/api/markx/accounts/permissions.py holds it; /me
// sends each membership's capabilities. Release 1 has owners and managers.
const CAPABILITIES: Record<string, string[]> = {
  owner: [
    "edit_store", "manage_offers", "propose_products", "handle_orders", "see_buyer_contact",
    "reply_to_reviews", "see_performance", "see_statements", "buy_plans", "manage_staff",
    "change_payout_account", "change_legal_details", "transfer_or_close",
  ],
  manager: [
    "edit_store", "manage_offers", "propose_products", "handle_orders", "see_buyer_contact",
    "reply_to_reviews", "see_performance", "buy_plans", "manage_staff",
  ],
  catalogue: ["manage_offers", "propose_products", "see_performance"],
  orders: ["handle_orders", "see_buyer_contact", "reply_to_reviews", "see_performance"],
  finance: ["see_performance", "see_statements", "buy_plans"],
};

const EXPECTED: Record<string, string[]> = {
  owner: ["orders", "offers", "reviews"],
  manager: ["orders", "offers", "reviews"],
  catalogue: ["offers"],
  orders: ["orders", "reviews"],
  finance: [],
};

describe("sellerMenu", () => {
  for (const [role, capabilities] of Object.entries(CAPABILITIES)) {
    it(`shows a ${role} exactly the screens its role may open`, () => {
      const items = sellerMenu("en", "s-1", { capabilities, store_slug: "alpha" }, en);
      const screens = items.filter((item) => item.href.startsWith("/en/seller/s-1/")).map((item) => item.href.slice("/en/seller/s-1/".length));
      expect(screens).toEqual(EXPECTED[role]);
      // Every member can see the shop's public page and leave.
      expect(items.slice(-2).map((item) => item.href)).toEqual(["/en/s/alpha", "/en"]);
    });
  }
  it("leaves out the public page of a shop that has none yet", () => {
    const items = sellerMenu("en", "s-1", { capabilities: CAPABILITIES.owner ?? [], store_slug: null }, en);
    expect(items.map((item) => item.label)).toEqual([en.seller.navOrders, en.seller.navOffers, en.seller.navReviews, en.seller.navExit]);
  });
});
