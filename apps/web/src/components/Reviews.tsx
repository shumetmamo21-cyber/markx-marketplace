import Link from "next/link";
import type { ReactNode } from "react";

import type { components } from "@/lib/api/schema";
import { formatDateTime, formatRating } from "@/lib/format";
import { fill, type Locale, type Messages } from "@/lib/i18n";

type Summary = components["schemas"]["RatingSummaryOut"];
type PublicReview = components["schemas"]["PublicReviewOut"];
type T = Pick<Messages, "reviews">;

/** Stars as a picture with its number in words for screen readers. */
export function Stars({ value, t }: { value: number; t: T }) {
  const whole = Math.min(Math.max(Math.round(value), 0), 5);
  return (
    <span role="img" aria-label={fill(t.reviews.stars, { stars: value })} className="tracking-tight text-ink">
      <span aria-hidden="true">{"★".repeat(whole)}</span>
      <span aria-hidden="true" className="text-line">{"★".repeat(5 - whole)}</span>
    </span>
  );
}

/** The totals the API keeps (blueprint C-18): the average, how many, and how
 * many gave each star. Numbers only: the page judges nothing. */
export function RatingSummary({ summary, t }: { summary: Summary; t: T }) {
  const r = t.reviews;
  if (!summary.count || summary.average === null || summary.average === undefined) return <p className="text-slate">{r.none}</p>;
  const counts: Record<string, number> = summary.stars;
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
      <p className="space-y-1">
        <span className="block text-3xl font-extrabold">{fill(r.average, { average: formatRating(summary.average) })}</span>
        <Stars value={summary.average} t={t} />
        <span className="block text-sm text-slate">{summary.count === 1 ? r.countOne : fill(r.count, { count: summary.count })}</span>
      </p>
      <ul className="min-w-48 flex-1 space-y-1 text-sm">
        {[5, 4, 3, 2, 1].map((star) => {
          const count = counts[String(star)] ?? 0;
          return (
            <li key={star} className="flex items-center gap-2">
              <span className="w-24 shrink-0">{fill(r.starRow, { stars: star, count })}</span>
              <span aria-hidden="true" className="h-2 flex-1 overflow-hidden rounded-full bg-line">
                <span className="block h-full bg-ink" style={{ width: `${Math.round((count / summary.count) * 100)}%` }} />
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** One published review. On a product page it links to the shop it was
 * bought from (`linkShop`); `report` is the report form for it, if any. */
export function ReviewItem({ review, lang, t, shopName, linkShop, report }: { review: PublicReview; lang: Locale; t: T; shopName: string; linkShop: boolean; report?: ReactNode }) {
  const r = t.reviews;
  return (
    <li className="space-y-2 rounded-card border border-line bg-white p-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <span>{r.product} <Stars value={review.product_rating} t={t} /></span>
        <span>{r.seller} <Stars value={review.seller_rating} t={t} /></span>
        <span className="text-slate">{formatDateTime(review.created_at, lang)}</span>
      </div>
      <p className="text-sm text-slate">
        {[review.variant_label, r.fromOrder].filter(Boolean).join(" · ")}
        {linkShop ? (
          <> · <Link href={`/${lang}/s/${review.store_slug}`} className="underline">{fill(r.shopLink, { store: shopName })}</Link></>
        ) : null}
      </p>
      {review.body ? <p className="whitespace-pre-line break-words">{review.body}</p> : null}
      {review.seller_reply ? (
        <div className="rounded-card border-l-4 border-ink bg-paper p-3 text-sm">
          <p className="font-semibold">{r.reply} · {shopName}</p>
          <p className="whitespace-pre-line break-words">{review.seller_reply}</p>
        </div>
      ) : null}
      {report}
    </li>
  );
}
