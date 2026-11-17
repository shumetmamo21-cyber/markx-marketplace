import type { Messages } from "@/lib/i18n";

export type MenuItem = { href: string; label: string };

/** The screens a shop member may open (blueprint I.4), work first. Each is
 * shown only to a role holding its capability (C.3), as /me sends them; the
 * API checks the same capability again on every call (require_seller). */
export function sellerMenu(
  lang: string,
  sellerId: string,
  membership: { capabilities: readonly string[]; store_slug: string | null },
  t: Pick<Messages, "seller">,
): MenuItem[] {
  const can = new Set(membership.capabilities);
  const s = t.seller;
  const base = `/${lang}/seller/${sellerId}`;
  const items: [string, string, string][] = [
    ["handle_orders", "orders", s.navOrders],
    ["manage_offers", "offers", s.navOffers],
    ["reply_to_reviews", "reviews", s.navReviews],
  ];
  return [
    ...items.filter(([capability]) => can.has(capability)).map(([, path, label]) => ({ href: `${base}/${path}`, label })),
    ...(membership.store_slug ? [{ href: `/${lang}/s/${membership.store_slug}`, label: s.navStore }] : []),
    { href: `/${lang}`, label: s.navExit },
  ];
}
