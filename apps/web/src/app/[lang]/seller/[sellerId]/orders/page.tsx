import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Countdown } from "@/components/Countdown";
import { serverApi } from "@/lib/api/server";
import type { components, operations } from "@/lib/api/schema";
import { formatDateTime, formatPrice } from "@/lib/format";
import { apiErrorText, fill, isLocale } from "@/lib/i18n";
import { statusLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

type Status = NonNullable<NonNullable<operations["list_seller_orders_api_v1_seller__seller_id__orders_get"]["parameters"]["query"]>["status"]>;
type SellerOrder = components["schemas"]["SellerOrderOut"];

export const metadata: Metadata = { robots: { index: false } };

// Tabs over the API's status filter; "on the way" and "done" combine several.
const TABS: Record<string, Status[]> = {
  placed: ["placed"],
  confirmed: ["confirmed"],
  ready: ["ready"],
  on_the_way: ["out_for_delivery", "delivery_failed"],
  done: ["delivered", "disputed", "completed"],
  all: [],
};

export default async function SellerOrdersPage({ params, searchParams }: PageProps<"/[lang]/seller/[sellerId]/orders">) {
  const { lang, sellerId } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const tabParam = (await searchParams).tab;
  const tab = typeof tabParam === "string" && tabParam in TABS ? tabParam : "placed";
  const api = await serverApi();
  const statuses = TABS[tab] ?? [];
  const results = await Promise.all(
    (statuses.length ? statuses : [undefined]).map((status) =>
      api.GET("/api/v1/seller/{seller_id}/orders", { params: { path: { seller_id: sellerId }, query: { lang, status, limit: 50 } } }),
    ),
  );
  const failed = results.find((r) => r.error);
  const orders: SellerOrder[] = results.flatMap((r) => r.data ?? []).sort((a, b) => (a.placed_at < b.placed_at ? 1 : -1));
  const s = t.seller;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-extrabold">{s.navOrders}</h1>
      <nav className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1" aria-label={s.navOrders}>
        {Object.keys(TABS).map((key) => (
          <Link
            key={key}
            href={`/${lang}/seller/${sellerId}/orders?tab=${key}`}
            aria-current={key === tab ? "page" : undefined}
            className={`inline-flex min-h-12 shrink-0 items-center rounded-full border px-4 font-semibold ${key === tab ? "border-ink bg-ink text-paper" : "border-line bg-white"}`}
          >
            {s[`tab_${key}` as "tab_placed"]}
          </Link>
        ))}
      </nav>
      {failed ? <p role="alert" className="text-clay">{apiErrorText(t, (failed.error as { error?: { code?: string } })?.error?.code ?? "unknown")}</p> : null}
      {orders.length === 0 && !failed ? <p className="text-slate">{s.empty}</p> : null}
      <ul className="space-y-3">
        {orders.map((order) => (
          <li key={order.id}>
            <Link href={`/${lang}/seller/${sellerId}/orders/${order.id}`} className="block space-y-1 rounded-card border border-line bg-white p-4 hover:border-ink">
              <p className="flex flex-wrap justify-between gap-2">
                <span className="font-bold">{fill(t.orders.code, { code: order.order_code })}</span>
                <span className="font-semibold">{statusLabel(t, order.status)}</span>
              </p>
              <p className="text-sm">
                {order.items.map((item) => `${item.quantity} × ${item.title}`).join(", ")}
              </p>
              <p className="flex flex-wrap gap-x-4 text-sm text-slate">
                <span className="price text-ink">{fill(s.payout, { amount: formatPrice(order.total_santim - order.estimated_fee_santim, lang) })}</span>
                <span>{fill(s.buyerArea, { area: (lang === "am" ? order.delivery_area.area_name_am : order.delivery_area.area_name_en) ?? "" })}</span>
              </p>
              {order.status === "placed" ? (
                <p className="text-sm">
                  <Countdown
                    deadline={order.response_deadline}
                    byText={fill(s.answerBy, { time: formatDateTime(order.response_deadline, lang) })}
                    leftText={s.answerLeft}
                    lateText={s.answerLate}
                  />
                </p>
              ) : null}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
