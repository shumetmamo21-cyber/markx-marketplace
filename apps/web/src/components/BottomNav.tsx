import Link from "next/link";

import type { Locale, Messages } from "@/lib/i18n";

// Thumb reach on a phone (blueprint I.4): every item has a text label.
export function BottomNav({ lang, t }: { lang: Locale; t: Messages }) {
  const items = [
    { href: `/${lang}`, label: t.nav.home, icon: "M3 11l9-7 9 7v9a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z" },
    { href: `/${lang}/search`, label: t.nav.categories, icon: "M4 5h7v6H4zM13 5h7v6h-7zM4 13h7v6H4zM13 13h7v6h-7z" },
    { href: `/${lang}/cart`, label: t.nav.cart, icon: "M3 4h2l2 11h11l2-8H6M9 20a1 1 0 100-2 1 1 0 000 2zm8 0a1 1 0 100-2 1 1 0 000 2z" },
    { href: `/${lang}/orders`, label: t.nav.orders, icon: "M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6" },
    { href: `/${lang}/account`, label: t.nav.account, icon: "M12 12a4 4 0 100-8 4 4 0 000 8zm-7 9a7 7 0 0114 0" },
  ];
  return (
    <nav
      aria-label={t.nav.home}
      className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-white pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      <ul className="grid grid-cols-5">
        {items.map((item) => (
          <li key={item.href}>
            <Link href={item.href} className="flex min-h-14 flex-col items-center justify-center gap-0.5 text-xs font-semibold">
              <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round">
                <path d={item.icon} />
              </svg>
              {item.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
