import { fill, type Messages } from "./i18n";

type Notification = { template: string; params: Record<string, unknown> };

/** A notification in the reader's language: its template's words with the
 * order code filled in, and the page it leads to. A template the app has no
 * words for gets a generic line, never the code. */
export function describeNotification(t: Pick<Messages, "notifications">, lang: string, n: Notification): { text: string; href: string | null } {
  const words: Record<string, string> = t.notifications;
  const code = typeof n.params.order_code === "string" ? n.params.order_code : "";
  const text = fill(words[n.template.replace(/\./g, "_")] ?? t.notifications.unknown, { code });
  const p = n.params;
  if (typeof p.seller_id === "string" && typeof p.seller_order_id === "string") return { text, href: `/${lang}/seller/${p.seller_id}/orders/${p.seller_order_id}` };
  if (typeof p.order_id === "string") return { text, href: `/${lang}/orders/${p.order_id}` };
  if (typeof p.seller_id === "string") return { text, href: `/${lang}/seller/${p.seller_id}` };
  if (n.template.startsWith("review.")) return { text, href: `/${lang}/reviews` };
  return { text, href: null };
}
