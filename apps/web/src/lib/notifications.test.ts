import { describe, expect, it } from "vitest";

import am from "../../messages/am.json";
import en from "../../messages/en.json";
import { describeNotification } from "./notifications";

// Every template the API sends (markx/*/service.py: notifications.notify,
// including the ones a condition chooses, like order.ready_for_collection).
// A new template in the API needs words here too.
const TEMPLATES = [
  "auth.new_sign_in", "dispute.decided", "dispute.decided_for_seller", "offer.removed_by_staff", "offer.restored_by_staff", "order.cancelled_by_buyer",
  "order.cancelled_not_fulfilled", "order.cancelled_not_fulfilled_for_seller", "order.completed",
  "order.completed_for_seller", "order.delivered", "order.delivery_failed", "order.expired_unanswered",
  "order.approaching_response_deadline", "order.handover_code_reissued", "order.next_best_offer", "order.out_for_delivery", "order.payment_recorded",
  "order.placed", "order.placed_for_seller", "order.problem_buyer_added", "order.problem_reported",
  "order.problem_reported_for_seller", "order.problem_seller_replied", "order.ready", "order.ready_for_collection",
  "order.refunded", "order.refunded_for_seller",
  "order.returned", "order.seller_confirmed", "order.seller_declined", "order.seller_did_not_answer",
  "report.resolved", "review.received_for_seller", "review.seller_replied", "seller.application_approved",
  "seller.application_rejected", "seller.documents_requested", "seller.member_added", "seller.payout_account_changed",
  "seller.reinstated", "seller.suspended", "seller.verification_level_changed", "seller.weekly_report",
];

describe("notifications", () => {
  it("have words for every template in both languages", () => {
    for (const template of TEMPLATES) {
      for (const t of [en, am]) {
        expect(describeNotification(t, "en", { template, params: {} }).text, template).not.toBe(t.notifications.unknown);
      }
    }
  });
  it("fill in the order code and lead to the right page", () => {
    const buyer = describeNotification(en, "en", { template: "order.placed", params: { order_id: "o-1", seller_order_id: "s-1", order_code: "MX-ABC123" } });
    expect(buyer).toEqual({ text: "Order MX-ABC123 is placed. The shop will answer soon.", href: "/en/orders/o-1" });
    const shop = describeNotification(en, "am", { template: "order.placed_for_seller", params: { seller_id: "x", seller_order_id: "s-1", order_code: "MX-ABC123" } });
    expect(shop.href).toBe("/am/seller/x/orders/s-1");
    expect(describeNotification(en, "en", { template: "review.seller_replied", params: {} }).href).toBe("/en/reviews");
  });
  it("never show a template code the app does not know", () => {
    expect(describeNotification(en, "en", { template: "something.new", params: {} })).toEqual({ text: en.notifications.unknown, href: null });
  });
});
