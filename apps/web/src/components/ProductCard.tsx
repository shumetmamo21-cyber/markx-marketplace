import Link from "next/link";

import type { ProductCard as Card } from "@/lib/api/types";
import { formatPrice } from "@/lib/format";
import { fill, type Locale, type Messages } from "@/lib/i18n";

// The same card everywhere (blueprint D.9, I.5): name, "from ETB", number of
// sellers, best seller level and a freshness mark. Text before pictures.
export function ProductCard({ card, lang, t }: { card: Card; lang: Locale; t: Messages }) {
  const sellers = card.seller_count === 1 ? t.card.sellerOne : fill(t.card.sellerCount, { count: card.seller_count });
  return (
    <Link
      href={`/${lang}/p/${card.slug}`}
      className="flex h-full flex-col gap-2 rounded-card border border-line bg-card p-4 hover:border-ink"
    >
      {card.brand ? <span className="text-xs font-semibold uppercase tracking-wide text-slate">{card.brand}</span> : null}
      <span className="font-semibold leading-snug">{card.name}</span>
      <span className="mt-auto">
        {card.in_stock && card.min_price_santim !== null ? (
          <span className="price text-lg">{fill(t.card.from, { price: formatPrice(card.min_price_santim, lang) })}</span>
        ) : (
          <span className="font-semibold text-clay">{t.card.outOfStock}</span>
        )}
      </span>
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate">
        <span>{sellers}</span>
        {card.best_seller_level >= 2 ? (
          <span className="inline-flex items-center gap-1 font-semibold text-highland">
            <svg aria-hidden="true" viewBox="0 0 16 16" className="h-4 w-4"><path d="M3 8l3 3 7-7" fill="none" stroke="currentColor" strokeWidth="2" /></svg>
            {fill(t.card.level, { level: card.best_seller_level })}
          </span>
        ) : null}
        <span>{card.price_is_fresh ? t.card.fresh : t.card.stale}</span>
      </span>
    </Link>
  );
}
