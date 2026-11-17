import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";

import { LanguageSwitch } from "@/components/LanguageSwitch";
import { Wordmark } from "@/components/Wordmark";
import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";
import { getMe } from "@/lib/session";

import { sellerMenu } from "./menu";

// The seller's own frame (I.4): a bottom bar on phones. Whether this person
// may act for this shop is the API's decision on every call (require_seller);
// this check only spares a non-member a screen of refusals.
export default async function SellerLayout({ children, params }: LayoutProps<"/[lang]/seller/[sellerId]">) {
  const { lang, sellerId } = await params;
  if (!isLocale(lang)) notFound();
  const me = await getMe();
  if (!me) redirect(`/${lang}/sign-in?next=/${lang}/seller`);
  const t = await getMessages(lang);
  const membership = me.sellers.find((s) => s.seller_id === sellerId);
  if (!membership) {
    return (
      <main id="main" className="mx-auto max-w-md space-y-4 px-4 py-16">
        <p>{t.seller.notMember}</p>
        <Link href={`/${lang}/seller`} className="font-semibold underline">{t.seller.title}</Link>
      </main>
    );
  }
  const items = sellerMenu(lang, sellerId, membership, t);
  return (
    <>
      <header className="sticky top-0 z-20 border-b border-line bg-ink text-paper">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <Wordmark label={t.brand.tagline} />
            <span className="truncate font-semibold">{membership.trade_name}</span>
          </div>
          <Suspense fallback={null}>
            <LanguageSwitch lang={lang} label={t.nav.language} title={t.nav.languageLabel} />
          </Suspense>
        </div>
        <nav aria-label={t.seller.title} className="mx-auto hidden max-w-5xl gap-1 px-4 pb-2 md:flex">
          {items.map((item) => (
            <Link key={item.href} href={item.href} className="rounded-full px-3 py-2 font-semibold hover:bg-white/10">{item.label}</Link>
          ))}
        </nav>
        <div className="tibeb" aria-hidden="true" />
      </header>
      <main id="main" className="mx-auto max-w-5xl px-4 py-6 pb-24 md:pb-6">{children}</main>
      <nav aria-label={t.seller.title} className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-white pb-[env(safe-area-inset-bottom)] md:hidden">
        <ul className="grid" style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}>
          {items.map((item) => (
            <li key={item.href}>
              <Link href={item.href} className="flex min-h-14 items-center justify-center px-1 text-center text-sm font-semibold">{item.label}</Link>
            </li>
          ))}
        </ul>
      </nav>
    </>
  );
}
