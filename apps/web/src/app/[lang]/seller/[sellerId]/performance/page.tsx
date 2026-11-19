import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { serverApi } from "@/lib/api/server";
import { formatPrice, formatRating, formatShare } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

export const metadata: Metadata = { robots: { index: false } };

const PERIODS = [7, 30, 90] as const;

// How the shop is doing (blueprint S-26, K.5; D-073): the API's figures for
// 7, 30 or 90 days, and the weekly messages it sent. Nothing is computed here.
export default async function SellerPerformancePage({ params, searchParams }: PageProps<"/[lang]/seller/[sellerId]/performance">) {
  const { lang, sellerId } = await params;
  if (!isLocale(lang)) notFound();
  const raw = (await searchParams).days;
  const days = PERIODS.find((p) => String(p) === (Array.isArray(raw) ? raw[0] : raw)) ?? 30;
  const t = await getMessages(lang);
  const api = await serverApi();
  const path = { seller_id: sellerId };
  const [figures, weekly] = await Promise.all([
    api.GET("/api/v1/seller/{seller_id}/performance", { params: { path, query: { days } } }),
    api.GET("/api/v1/seller/{seller_id}/weekly-reports", { params: { path, query: { limit: 12 } } }),
  ]);
  const s = t.seller;
  if (figures.response.status === 403) return <p role="alert">{t.apiErrors.permission_denied}</p>;
  const f = figures.data;
  const share = (value: number | null | undefined) => (value === null || value === undefined ? s.perfNone : formatShare(value));
  const tiles: [string, string | number][] = f
    ? [
        [s.perfReceived, f.orders_received],
        [s.perfConfirmed, f.orders_confirmed],
        [s.perfDeclined, f.orders_declined],
        [s.perfUnanswered, f.orders_unanswered],
        [s.perfCancelled, f.orders_cancelled_by_buyer],
        [s.perfCancelledUnfulfilled, f.orders_cancelled_unfulfilled],
        [s.perfConfirmShare, share(f.confirmation_share)],
        [s.perfMedianConfirm, f.median_minutes_to_confirm === null || f.median_minutes_to_confirm === undefined ? s.perfNone : fill(s.perfMinutes, { minutes: Math.round(f.median_minutes_to_confirm) })],
        [s.perfDelivered, f.delivered],
        [s.perfDeliveryFailed, f.delivery_failed],
        [s.perfDeliveryShare, share(f.delivery_success_share)],
        [s.perfCompleted, f.completed],
        [s.perfCompletedValue, formatPrice(f.completed_value_santim, lang)],
        [s.perfProblems, f.problems_reported],
        [s.perfRefunded, f.refunded],
        [s.perfNewReviews, f.new_reviews],
        [s.perfRating, f.rating_average === null || f.rating_average === undefined ? s.perfNone : `${formatRating(f.rating_average)} (${f.rating_count})`],
        [s.perfOffers, f.active_offers],
        [s.perfStale, f.prices_to_confirm],
        [s.perfLowStock, f.low_stock_offers],
      ]
    : [];
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-extrabold">{s.performanceTitle}</h1>
      <p className="max-w-prose text-slate">{s.performanceLead}</p>
      <ul className="flex flex-wrap gap-2">
        {PERIODS.map((p) => (
          <li key={p}>
            <Link href={`/${lang}/seller/${sellerId}/performance?days=${p}`} aria-current={p === days ? "page" : undefined} className={`inline-flex min-h-12 items-center rounded-full border px-4 font-semibold ${p === days ? "border-ink bg-ink text-paper" : "border-line bg-white"}`}>
              {fill(s.performanceDays, { days: p })}
            </Link>
          </li>
        ))}
      </ul>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {tiles.map(([label, value]) => (
          <div key={label} className="rounded-card border border-line bg-white p-3">
            <dt className="text-sm text-slate">{label}</dt>
            <dd className="text-xl font-extrabold">{value}</dd>
          </div>
        ))}
      </dl>
      <section aria-labelledby="weekly" className="space-y-2">
        <h2 id="weekly" className="text-lg font-bold">{s.weeklyTitle}</h2>
        {(weekly.data ?? []).length === 0 ? <p className="text-slate">{s.weeklyNone}</p> : null}
        <ul className="space-y-1">
          {(weekly.data ?? []).map((report) => (
            <li key={report.id} className="rounded-card border border-line bg-white p-3 text-sm">
              {fill(s.weeklyLine, { date: report.week_start, received: report.figures.orders_received, completed: report.figures.completed, problems: report.figures.problems_reported })}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
