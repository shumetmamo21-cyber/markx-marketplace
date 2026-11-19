import type { Messages } from "@/lib/i18n";

export type MenuItem = { href: string; label: string };

/** The work queues a staff role may open, queues first (blueprint I.4). Each
 * item is shown only to a role that holds its capability, or one of them
 * (C.4); the API checks the same capability again on every call. */
export function adminMenu(lang: string, capabilities: readonly string[], t: Pick<Messages, "admin">): MenuItem[] {
  const can = new Set(capabilities);
  const a = t.admin;
  const items: [string | string[], string, string][] = [
    ["handle_cases", "problems", a.navProblems],
    ["find_orders", "orders", a.navOrders],
    ["intervene_in_orders", "dispatch", a.navDispatch],
    ["find_orders", "dashboard", a.navDashboard],
    ["review_sellers", "sellers", a.navSellers],
    ["review_sellers", "invitations", a.navInvitations],
    ["curate_catalogue", "catalog", a.navCatalog],
    ["curate_catalogue", "products", a.navProducts],
    ["curate_catalogue", "setup", a.navSetup],
    ["moderate_listings", "listings", a.navListings],
    ["moderate_listings", "pictures", a.navPictures],
    ["moderate_reviews", "reviews", a.navReviews],
    ["moderate_reviews", "reports", a.navReports],
    ["tune_search", "search", a.navSearch],
    ["read_audit_log", "audit", a.navAudit],
    ["export_data", "exports", a.navExports],
    ["find_orders", "ops", a.navOps],
    // The super administrator changes any setting; operations the risk limits.
    ["change_delivery_and_risk", "delivery", a.navDelivery],
    [["manage_staff_and_settings", "change_delivery_and_risk"], "settings", a.navSettings],
    ["manage_staff_and_settings", "staff", a.navStaff],
  ];
  return items
    .filter(([capability]) => (Array.isArray(capability) ? capability : [capability]).some((c) => can.has(c)))
    .map(([, path, label]) => ({ href: `/${lang}/admin/${path}`, label }));
}
