import type { Messages } from "@/lib/i18n";

export type MenuItem = { href: string; label: string };

/** The work queues a staff role may open, queues first (blueprint I.4). Each
 * item is shown only to a role that holds its capability (C.4); the API checks
 * the same capability again on every call. */
export function adminMenu(lang: string, capabilities: readonly string[], t: Pick<Messages, "admin">): MenuItem[] {
  const can = new Set(capabilities);
  const a = t.admin;
  const items: [string, string, string][] = [
    ["handle_cases", "problems", a.navProblems],
    ["find_orders", "orders", a.navOrders],
    ["review_sellers", "sellers", a.navSellers],
    ["review_sellers", "invitations", a.navInvitations],
    ["curate_catalogue", "catalog", a.navCatalog],
    ["moderate_listings", "listings", a.navListings],
    ["tune_search", "search", a.navSearch],
    ["read_audit_log", "audit", a.navAudit],
  ];
  return items
    .filter(([capability]) => can.has(capability))
    .map(([, path, label]) => ({ href: `/${lang}/admin/${path}`, label }));
}
