import { notFound } from "next/navigation";

import { serverApi } from "@/lib/api/server";
import { formatDateTime, formatPrice, formatShare } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { statusLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

const PERIODS = [1, 7, 30, 90] as const;

// The business dashboard (blueprint D.18, AD-14) over D-065's route: counts
// and amounts only, no personal data. Every figure is the API's; the page
// only lays them out.
export default async function DashboardPage({ params, searchParams }: PageProps<"/[lang]/admin/dashboard">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const raw = Number((await searchParams).days);
  const days = (PERIODS as readonly number[]).includes(raw) ? raw : 7;
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/admin/dashboard", { params: { query: { days } } });
  const a = t.admin;
  if (response.status === 403) return <p role="alert" className="font-semibold text-clay">{a.notAllowed}</p>;
  if (!data) return <p role="alert" className="font-semibold text-clay">{t.apiErrors.unknown}</p>;
  const share = (value: number | null) => (value == null ? a.notYet : formatShare(value));
  const tiles: [string, string][] = [
    [a.kOrders, String(data.orders)],
    [a.kSellerOrders, String(data.seller_orders)],
    [a.kCompletedValue, formatPrice(data.completed_value_santim, lang)],
    [a.kFees, formatPrice(data.fees_santim, lang)],
    [a.kMedianConfirm, data.median_minutes_to_confirm == null ? a.notYet : fill(a.minutes, { minutes: Math.round(data.median_minutes_to_confirm) })],
    [a.kAnswered, share(data.answered_share)],
    [a.kDelivered, share(data.delivery_success_share)],
    [a.kProblemsOpened, String(data.problems_opened)],
    [a.kProblemsOpen, String(data.problems_open)],
    [a.kLiveOffers, String(data.live_offers)],
    [a.kProductsWithOffers, String(data.products_with_offers)],
    [a.kOffersPerProduct, data.offers_per_product == null ? a.notYet : data.offers_per_product.toFixed(1)],
    [a.kFreshPrices, share(data.fresh_price_share)],
  ];
  const byStatus = Object.entries(data.seller_orders_by_status as Record<string, number>).sort((x, y) => y[1] - x[1]);
  const funnel: [string, number][] = [
    [a.fSearches, data.funnel.searches],
    [a.fZero, data.funnel.zero_result_searches],
    [a.fCarts, data.funnel.carts_filled],
    [a.fOrders, data.funnel.orders],
  ];
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold">{a.dashboardTitle}</h1>
          <p className="text-sm text-slate">{fill(a.fromTo, { from: formatDateTime(data.from_time, lang), to: formatDateTime(data.to_time, lang) })}</p>
        </div>
        <form method="get" className="flex items-end gap-2">
          <label className="space-y-1">
            <span className="block text-sm font-semibold">{a.period}</span>
            <select name="days" defaultValue={String(days)} className="min-h-12 rounded-card border border-line bg-white px-3">
              {PERIODS.map((n) => <option key={n} value={n}>{fill(a.days, { days: n })}</option>)}
            </select>
          </label>
          <button type="submit" className="min-h-12 rounded-card bg-ink px-5 font-bold text-paper">{a.show}</button>
        </form>
      </div>
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {tiles.map(([label, value]) => (
          <div key={label} className="rounded-card border border-line bg-white p-4">
            <dt className="text-sm text-slate">{label}</dt>
            <dd className="text-xl font-extrabold">{value}</dd>
          </div>
        ))}
      </dl>
      <section className="space-y-2">
        <h2 className="text-lg font-bold">{a.byStatus}</h2>
        <ul className="divide-y divide-line rounded-card border border-line bg-white">
          {byStatus.map(([status, count]) => (
            <li key={status} className="flex justify-between gap-2 p-3"><span>{statusLabel(t, status)}</span><span className="font-semibold">{count}</span></li>
          ))}
        </ul>
      </section>
      <section className="space-y-2">
        <h2 className="text-lg font-bold">{a.funnel}</h2>
        <ol className="divide-y divide-line rounded-card border border-line bg-white">
          {funnel.map(([label, count]) => (
            <li key={label} className="flex justify-between gap-2 p-3"><span>{label}</span><span className="font-semibold">{count}</span></li>
          ))}
        </ol>
      </section>
    </div>
  );
}
