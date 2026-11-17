import { describe, expect, it } from "vitest";

import am from "../../../../../messages/am.json";
import en from "../../../../../messages/en.json";
import { adminMenu } from "./menu";

// Blueprint C.4, as apps/api/markx/accounts/permissions.py holds it. The API
// sends a person's capabilities on /me; the menu must show exactly the screens
// those capabilities open, and the API refuses every other call anyway.
const CAPABILITIES: Record<string, string[]> = {
  super_admin: [
    "review_sellers", "view_documents", "curate_catalogue", "moderate_listings", "moderate_reviews",
    "find_orders", "intervene_in_orders", "handle_cases", "approve_money", "change_fees",
    "change_delivery_and_risk", "tune_search", "manage_staff_and_settings", "read_audit_log", "export_data",
  ],
  operations: [
    "review_sellers", "view_documents", "moderate_listings", "moderate_reviews", "find_orders",
    "intervene_in_orders", "handle_cases", "change_delivery_and_risk",
  ],
  support: ["moderate_reviews", "find_orders", "handle_cases"],
  catalogue: ["curate_catalogue", "moderate_listings", "moderate_reviews", "tune_search"],
  finance: ["find_orders", "approve_money", "change_fees", "read_audit_log", "export_data"],
};

const EXPECTED: Record<string, string[]> = {
  super_admin: [
    "problems", "orders", "dispatch", "dashboard", "sellers", "invitations", "catalog", "listings",
    "pictures", "reviews", "reports", "search", "audit", "exports", "ops", "settings", "staff",
  ],
  operations: ["problems", "orders", "dispatch", "dashboard", "sellers", "invitations", "listings", "pictures", "reviews", "reports", "ops", "settings"],
  support: ["problems", "orders", "dashboard", "reviews", "reports", "ops"],
  catalogue: ["catalog", "listings", "pictures", "reviews", "reports", "search"],
  finance: ["orders", "dashboard", "audit", "exports", "ops"],
};

describe("the admin menu", () => {
  for (const [role, capabilities] of Object.entries(CAPABILITIES)) {
    it(`shows ${role} exactly the screens its capabilities open`, () => {
      const paths = adminMenu("en", capabilities, en).map((item) => item.href.replace("/en/admin/", ""));
      expect(paths).toEqual(EXPECTED[role]);
    });
  }
  it("shows nothing to a role with no capability", () => {
    expect(adminMenu("en", [], en)).toEqual([]);
  });
  it("labels every item in both languages, and keeps the language in the address", () => {
    const english = adminMenu("en", CAPABILITIES.super_admin ?? [], en);
    const amharic = adminMenu("am", CAPABILITIES.super_admin ?? [], am);
    expect(amharic.map((item) => item.href.replace("/am/", "/en/"))).toEqual(english.map((item) => item.href));
    for (const item of [...english, ...amharic]) expect(item.label.length).toBeGreaterThan(1);
    expect(new Set(amharic.map((item) => item.label)).size).toBe(amharic.length);
  });
});
