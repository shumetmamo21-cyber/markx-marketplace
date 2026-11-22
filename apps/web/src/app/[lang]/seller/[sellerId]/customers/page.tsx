import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { serverApi } from "@/lib/api/server";
import { formatDateTime, formatPrice } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { statusLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

export const metadata: Metadata = { robots: { index: false } };

// The shop's own customers (blueprint S-11; D-106): the people whose orders
// it confirmed, with only what their order pages already show it (name,
// phone, area), newest first. The API builds the list and decides who may
// see it (the members who see buyers' contacts, C.3); this shows it.
export default async function SellerCustomersPage({ params, searchParams }: PageProps<"/[lang]/seller/[sellerId]/customers">) {
  const { lang, sellerId } = await params;
  if (!isLocale(lang)) notFound();
  const raw = (await searchParams).q;
  const q = ((Array.isArray(raw) ? raw[0] : raw) ?? "").trim().slice(0, 60);
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/seller/{seller_id}/customers", {
    params: { path: { seller_id: sellerId }, query: { lang, q: q || undefined } },
  });
  const s = t.seller;
  if (response.status === 403) return <p role="alert">{t.apiErrors.permission_denied}</p>;
  const customers = data ?? [];
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-2xl font-extrabold">{s.customersTitle}</h1>
      <p className="text-slate">{s.customersLead}</p>
      <form method="get" role="search" className="flex flex-wrap items-end gap-2">
        <label className="min-w-0 flex-1 space-y-1">
          <span className="block text-sm font-semibold">{s.customersSearch}</span>
          <input name="q" defaultValue={q} maxLength={60} className="min-h-12 w-full rounded-card border border-line bg-white px-3" />
        </label>
        <button type="submit" className="min-h-12 rounded-card border border-ink px-4 font-semibold">{s.customersFind}</button>
      </form>
      {customers.length === 0 ? <p>{q ? s.customersNoMatch : s.customersNone}</p> : null}
      <ul className="space-y-3">
        {customers.map((customer) => (
          <li key={customer.phone} className="space-y-2 rounded-card border border-line bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="font-bold">{customer.name}</p>
                <p className="text-sm text-slate">{customer.area_name}</p>
              </div>
              <a href={`tel:${customer.phone}`} className="inline-flex min-h-12 items-center rounded-card border border-ink px-4 font-semibold">
                {fill(s.customerCall, { phone: customer.phone })}
              </a>
            </div>
            <p className="text-sm">
              {fill(s.customerOrders, { count: customer.orders, completed: customer.completed_orders })} · {fill(s.customerLast, { date: formatDateTime(customer.last_order_at, lang) })}
            </p>
            <ul className="flex flex-wrap gap-2 text-sm">
              {customer.recent_orders.map((order) => (
                <li key={order.seller_order_id}>
                  <Link href={`/${lang}/seller/${sellerId}/orders/${order.seller_order_id}`} className="inline-flex min-h-12 items-center rounded-full border border-line px-3 underline">
                    {fill(t.orders.code, { code: order.order_code })} · {statusLabel(t, order.status)} · {formatPrice(order.total_santim, lang)}
                  </Link>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}
