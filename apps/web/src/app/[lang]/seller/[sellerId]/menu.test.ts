import { describe, expect, it } from "vitest";

import en from "../../../../../messages/en.json";
import { sellerLanding, sellerMenu } from "./menu";

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
  owner: ["", "/orders", "/offers", "/reviews", "/customers", "/performance", "/store", "/team", "/documents", "/legal", "/payout"],
  manager: ["", "/orders", "/offers", "/reviews", "/customers", "/performance", "/store", "/team"],
  catalogue: ["", "/offers", "/performance"],
  orders: ["", "/orders", "/reviews", "/customers", "/performance"],
  finance: ["", "/performance"],
};

const BASE = "/en/seller/s-1";

describe("sellerMenu", () => {
  for (const [role, capabilities] of Object.entries(CAPABILITIES)) {
    it(`shows a ${role} exactly the screens its role may open`, () => {
      const items = sellerMenu("en", "s-1", { capabilities, store_slug: "alpha" }, en);
      const screens = items.filter((item) => item.href.startsWith(BASE)).map((item) => item.href.slice(BASE.length));
      expect(screens).toEqual(EXPECTED[role]);
      // Every member can see the shop's public page and leave.
      expect(items.slice(-2).map((item) => item.href)).toEqual(["/en/s/alpha", "/en"]);
      // The phone's bottom bar holds at most four screens.
      expect(items.filter((item) => item.primary).length).toBeLessThanOrEqual(4);
    });
  }
  it("leaves out the public page of a shop that has none yet", () => {
    const items = sellerMenu("en", "s-1", { capabilities: CAPABILITIES.owner ?? [], store_slug: null }, en);
    expect(items.some((item) => item.label === en.seller.navStore)).toBe(false);
  });
  it("opens on the first work the role allows, else the overview", () => {
    const land = (role: string) => sellerLanding(sellerMenu("en", "s-1", { capabilities: CAPABILITIES[role] ?? [], store_slug: "alpha" }, en), "s-1");
    expect(land("owner")).toBe(`${BASE}/orders`);
    expect(land("catalogue")).toBe(`${BASE}/offers`);
    expect(land("finance")).toBe(BASE);
  });
});
