"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

import { LOCALE_COOKIE, type Locale, otherLocale } from "@/lib/i18n";

// Always visible, and remembered (blueprint I.1, I.7).
export function LanguageSwitch({ lang, label, title }: { lang: Locale; label: string; title: string }) {
  const pathname = usePathname();
  const search = useSearchParams();
  const target = otherLocale(lang);
  const rest = pathname.replace(/^\/(am|en)(?=\/|$)/, "");
  const query = search.toString();
  return (
    <Link
      href={`/${target}${rest}${query ? `?${query}` : ""}`}
      hrefLang={target}
      lang={target}
      title={title}
      onClick={() => {
        document.cookie = `${LOCALE_COOKIE}=${target}; path=/; max-age=31536000; samesite=lax`;
      }}
      className="inline-flex min-h-12 items-center rounded-full border border-line px-3 text-sm font-semibold hover:bg-white"
    >
      {label}
    </Link>
  );
}
