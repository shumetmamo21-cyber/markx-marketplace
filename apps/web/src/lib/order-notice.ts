// C-27 (blueprint D.10; D-110): the notice a buyer reads before placing an
// order. Its words are the API's (`markx/orders/notice.py`, the one place the
// founder changes them), sent with the review step in the buyer's language.
// These are the pure parts of the notice, tested in order-notice.test.ts.

import type { components } from "./api/schema";

export type OrderNotice = components["schemas"]["OrderNoticeOut"];

/** The notice's points worth showing: each trimmed, empty ones left out. */
export function noticePoints(notice: OrderNotice | null | undefined): string[] {
  return (notice?.points ?? []).map((point) => point.trim()).filter((point) => point.length > 0);
}

/** Whether the review step may offer "Place order": only once the buyer has
 * the notice in front of them, with a title and every point to read. */
export function noticeReady(notice: OrderNotice | null | undefined): boolean {
  return Boolean(notice && notice.title.trim() && noticePoints(notice).length > 0);
}
