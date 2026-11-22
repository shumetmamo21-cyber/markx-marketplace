import type { Messages } from "@/lib/i18n";

export type MenuItem = { href: string; label: string; primary: boolean };

/** The screens a shop member may open (blueprint I.4), work first. Each is
 * shown only to a role holding its capability (C.3), as /me sends them; the
 * API checks the same capability again on every call (require_seller). The
 * overview is every member's; `primary` items also sit in the phone's
 * bottom bar, the rest are reached from the overview. */
export function sellerMenu(
  lang: string,
  sellerId: string,
  membership: { capabilities: readonly string[]; store_slug: string | null },
  t: Pick<Messages, "seller">,
): MenuItem[] {
  const can = new Set(membership.capabilities);
  const s = t.seller;
  const base = `/${lang}/seller/${sellerId}`;
  const items: [string | null, string, string, boolean][] = [
    [null, "", s.navHome, true],
    ["handle_orders", "/orders", s.navOrders, true],
    ["manage_offers", "/offers", s.navOffers, true],
    ["reply_to_reviews", "/reviews", s.navReviews, true],
    ["see_buyer_contact", "/customers", s.navCustomers, false],
    ["see_performance", "/performance", s.navPerformance, false],
    ["edit_store", "/store", s.navStoreSettings, false],
    ["manage_staff", "/team", s.navTeam, false],
    ["change_legal_details", "/documents", s.navDocuments, false],
    ["change_legal_details", "/legal", s.navLegal, false],
    ["change_payout_account", "/payout", s.navPayout, false],
  ];
  return [
    ...items
      .filter(([capability]) => capability === null || can.has(capability))
      .map(([, path, label, primary]) => ({ href: `${base}${path}`, label, primary })),
    ...(membership.store_slug ? [{ href: `/${lang}/s/${membership.store_slug}`, label: s.navStore, primary: false }] : []),
    { href: `/${lang}`, label: s.navExit, primary: false },
  ];
}

/** Where the seller entry sends a member: the first piece of work their role
 * allows (orders, then offers, then reviews), or the overview. */
export function sellerLanding(items: MenuItem[], sellerId: string): string | undefined {
  const work = items.find((item) => item.primary && !item.href.endsWith(`/seller/${sellerId}`));
  return (work ?? items[0])?.href;
}
