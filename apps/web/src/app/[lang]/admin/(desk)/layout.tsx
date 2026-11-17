import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";

import { LanguageSwitch } from "@/components/LanguageSwitch";
import { SignOutButton } from "@/components/SignOutButton";
import { Wordmark } from "@/components/Wordmark";
import { fill, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";
import { getMe } from "@/lib/session";

export const metadata: Metadata = { robots: { index: false, follow: false } };

// The admin dashboard (blueprint I.4): a side menu on wide screens, queues
// first. Only a staff session gets in; every API call checks the role's
// capability again (C.4), so a menu item hidden here is also refused there.
export default async function AdminLayout({ children, params }: LayoutProps<"/[lang]/admin">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const me = await getMe();
  if (!me || me.session_kind !== "staff" || !me.staff) redirect(`/${lang}/admin/sign-in`);
  const t = await getMessages(lang);
  const can = new Set(me.staff.capabilities);
  const items = [
    can.has("handle_cases") && { href: `/${lang}/admin/problems`, label: t.admin.navProblems },
    can.has("find_orders") && { href: `/${lang}/admin/orders`, label: t.admin.navOrders },
    can.has("review_sellers") && { href: `/${lang}/admin/sellers`, label: t.admin.navSellers },
    can.has("tune_search") && { href: `/${lang}/admin/search`, label: t.admin.navSearch },
  ].filter((item): item is { href: string; label: string } => Boolean(item));
  return (
    <div className="min-h-dvh md:grid md:grid-cols-[14rem_1fr]">
      <aside className="border-b border-line bg-ink text-paper md:min-h-dvh md:border-b-0">
        <div className="flex items-center justify-between gap-2 p-4 md:block md:space-y-3">
          <div>
            <Wordmark label={t.brand.tagline} />
            <p className="text-sm opacity-80">{t.admin.title}</p>
          </div>
          <Suspense fallback={null}>
            <LanguageSwitch lang={lang} label={t.nav.language} title={t.nav.languageLabel} />
          </Suspense>
        </div>
        <nav aria-label={t.admin.title} className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:px-2">
          {items.map((item) => (
            <Link key={item.href} href={item.href} className="shrink-0 rounded-card px-3 py-3 font-semibold hover:bg-white/10">{item.label}</Link>
          ))}
        </nav>
        <div className="hidden space-y-2 p-4 text-sm md:block">
          <p className="opacity-80">{fill(t.admin.role, { role: me.staff.role })}</p>
        </div>
      </aside>
      <main id="main" className="min-w-0 space-y-4 p-4 md:p-8">
        <div className="flex justify-end">
          <SignOutButton label={t.admin.signOut} home={`/${lang}/admin/sign-in`} />
        </div>
        {children}
      </main>
    </div>
  );
}
