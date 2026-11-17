import { describe, expect, it } from "vitest";

import am from "../../messages/am.json";
import en from "../../messages/en.json";
import { codeLabel } from "./labels";

// The codes the API defines (markx/accounts/models.py, markx/sellers/models.py,
// markx/catalog/models.py, markx/delivery/models.py, markx/ops/models.py,
// markx/notifications/models.py, markx/reviews/, markx/reports/). A new code
// in the API needs words here too.
const CODES = {
  staffRole: ["super_admin", "operations", "support", "catalogue", "finance"],
  reviewState: ["draft", "pending", "needs_documents", "approved", "rejected"],
  sellerStatus: ["applied", "active", "suspended", "closed"],
  documentStatus: ["pending", "accepted", "rejected"],
  productStatus: ["draft", "pending_review", "approved", "merged", "archived"],
  actorType: ["staff", "user", "system"],
  deliveryMode: ["seller_rider", "partner_courier", "shop_collection"],
  alertSeverity: ["warning", "critical"],
  outboxStatus: ["pending", "done", "failed"],
  reviewStatus: ["held", "published", "hidden"],
  heldReason: ["contact_details", "many_reviews_of_one_seller"],
  reportStatus: ["open", "actioned", "dismissed"],
  reportTarget: ["product", "offer", "store", "review"],
  reportReason: ["counterfeit", "prohibited", "wrong_information", "offensive", "fraud", "spam", "other"],
  imageKind: ["catalogue", "seller_real_photo"],
  imageStatus: ["processing", "ready", "failed", "removed"],
} as const;

describe("code labels", () => {
  it("give every API code words in both languages, never the code itself", () => {
    for (const [group, codes] of Object.entries(CODES)) {
      for (const code of codes) {
        for (const t of [en, am]) {
          const label = codeLabel(t, group as keyof typeof CODES, code);
          expect(label, `${group}.${code}`).not.toBe(code);
          expect(label.length, `${group}.${code}`).toBeGreaterThan(1);
        }
      }
    }
  });
  it("show an unknown code as it is", () => {
    expect(codeLabel(en, "staffRole", "night_shift")).toBe("night_shift");
  });
});
