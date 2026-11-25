// A guest cancels one shop's part of their order from the tracking link,
// before the shop answers (F-28, the founder's decision of 25 November 2026;
// D-109). The API decides: it marks a part `can_cancel` only on a guest's
// order and only while the shop has not answered, and checks again when the
// guest asks. These are the pure parts of the button, tested in
// guest-cancel.test.ts.

import { fill, type Messages } from "./i18n";

/** Every refusal the API's cancel may answer with, each with words. */
export const CANCEL_REFUSALS = [
  "order_cannot_be_cancelled",
  "tracking_link_invalid",
  "order_paid_contact_support",
  "order_not_found",
] as const;

/** Whether the tracking page shows this part's cancel button. */
export function guestMayCancel(order: { is_guest: boolean }, part: { can_cancel: boolean }): boolean {
  return order.is_guest && part.can_cancel;
}

/** Only the words the button needs, so the page sends the browser no more. */
export function cancelWords(t: Pick<Messages, "guest" | "orders" | "apiErrors">, shop: string) {
  const own: Record<string, string> = t.guest.errors;
  const shared: Record<string, string> = t.apiErrors;
  const refusals: Record<string, string> = {};
  for (const code of CANCEL_REFUSALS) refusals[code] = own[code] ?? shared[code] ?? t.orders.actionFailed;
  return {
    hint: t.guest.cancelHint,
    ask: fill(t.guest.cancelAsk, { shop }),
    yes: t.guest.cancelYes,
    no: t.guest.cancelNo,
    cancel: t.orders.cancel,
    cancelling: t.orders.cancelling,
    failed: t.orders.actionFailed,
    refusals,
  };
}

export type CancelWords = ReturnType<typeof cancelWords>;

/** A refused cancel in words; never the raw code. */
export function cancelRefusalText(words: CancelWords, code: string): string {
  return words.refusals[code] ?? words.failed;
}
