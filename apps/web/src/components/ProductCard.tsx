import Link from "next/link";

import type { DeliveredToZone, ProductCard as Card } from "@/lib/api/types";
import { formatPrice } from "@/lib/format";
import { fill, type Locale, type Messages } from "@/lib/i18n";

// The same card everywhere (blueprint D.9, I.5): photo, name, "from ETB",
// number of sellers, best seller level and a freshness mark. The photo is the
// API's small thumbnail (within 320 px and 30 KB, D-062), loaded lazily, and
// left out when the product has none; the text never waits for it. In lite
// mode (C-12) there is no photo at all. When the search names the buyer's
// area (C-03), the card also says the total to their door and how fast, from
// the API: `door` is that, `null` when it does not deliver there.
export function ProductCard({ card, lang, t, lite = false, door }: { card: Card; lang: Locale; t: Messages; lite?: boolean; door?: DeliveredToZone | null }) {
  const sellers = card.seller_count === 1 ? t.card.sellerOne : fill(t.card.sellerCount, { count: card.seller_count });
  return (
    <Link
      href={`/${lang}/p/${card.slug}`}
      className="flex h-full flex-col gap-2 rounded-card border border-line bg-card p-4 hover:border-ink"
    >
      {card.thumb_url && !lite ? (
        <span className="flex h-28 items-center justify-center overflow-hidden rounded-card bg-white">
          {/* eslint-disable-next-line @next/next/no-img-element -- the worker already made it small (D-062) */}
          <img src={card.thumb_url} alt="" loading="lazy" decoding="async" className="h-full w-full object-contain" />
        </span>
      ) : null}
      {card.brand ? <span className="text-xs font-semibold uppercase tracking-wide text-slate">{card.brand}</span> : null}
      <span className="font-semibold leading-snug">{card.name}</span>
      <span className="mt-auto">
        {card.in_stock && card.min_price_santim !== null ? (
          <span className="price text-lg">{fill(t.card.from, { price: formatPrice(card.min_price_santim, lang) })}</span>
        ) : (
          <span className="font-semibold text-clay">{t.card.outOfStock}</span>
        )}
      </span>
      {door ? (
        <span className="space-y-0.5 text-sm">
          <span className="block font-semibold">{fill(t.card.toDoor, { price: formatPrice(door.total_santim, lang) })}</span>
          <span className="block text-slate">{fill(t.card.arrivesWithin, { hours: door.fastest_hours })}</span>
        </span>
      ) : door === null ? (
        <span className="text-sm text-slate">{t.card.noDelivery}</span>
      ) : null}
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
