import Link from "next/link";
import { Suspense } from "react";

import type { Locale, Messages } from "@/lib/i18n";

import { LanguageSwitch } from "./LanguageSwitch";
import { SearchForm } from "./SearchForm";
import { Wordmark } from "./Wordmark";

export function SiteHeader({ lang, t, query, signedIn = false }: { lang: Locale; t: Messages; query?: string; signedIn?: boolean }) {
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-paper/95 backdrop-blur">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:bg-white focus:p-2">
        {t.nav.skip}
      </a>
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-3 md:flex-row md:items-center">
        <div className="flex items-center justify-between gap-3">
          <Link href={`/${lang}`} className="rounded-md" aria-label={t.brand.wordmark}>
            <Wordmark label={t.brand.tagline} />
          </Link>
          <div className="flex items-center gap-2 md:hidden">
            <Suspense fallback={null}>
              <LanguageSwitch lang={lang} label={t.nav.language} title={t.nav.languageLabel} />
            </Suspense>
          </div>
        </div>
        <div className="flex-1">
          <SearchForm lang={lang} t={t} query={query} />
        </div>
        <nav aria-label={t.nav.account} className="hidden items-center gap-2 md:flex">
          <Link href={`/${lang}/cart`} className="inline-flex min-h-12 items-center px-3 font-semibold hover:underline">
            {t.nav.cart}
          </Link>
          {signedIn ? (
            <Link href={`/${lang}/orders`} className="inline-flex min-h-12 items-center px-3 font-semibold hover:underline">
              {t.nav.orders}
            </Link>
          ) : null}
          <Link href={`/${lang}/sign-in`} className="inline-flex min-h-12 items-center px-3 font-semibold hover:underline">
            {signedIn ? t.nav.account : t.nav.signIn}
          </Link>
          <Suspense fallback={null}>
            <LanguageSwitch lang={lang} label={t.nav.language} title={t.nav.languageLabel} />
          </Suspense>
        </nav>
      </div>
      <div className="tibeb" aria-hidden="true" />
    </header>
  );
}
