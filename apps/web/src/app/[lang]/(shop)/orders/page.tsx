import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { serverApi } from "@/lib/api/server";
import { formatDateTime, formatPrice } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { statusLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";
import { getMe } from "@/lib/session";

export const metadata: Metadata = { robots: { index: false } };

export default async function OrdersPage({ params }: PageProps<"/[lang]/orders">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  if (!(await getMe())) redirect(`/${lang}/sign-in?next=/${lang}/orders`);
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data } = await api.GET("/api/v1/me/orders", { params: { query: { lang } } });
  const orders = data ?? [];
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <h1 className="text-2xl font-extrabold">{t.orders.title}</h1>
      {orders.length === 0 ? <p>{t.orders.empty}</p> : null}
      <ul className="space-y-3">
        {orders.map((order) => (
          <li key={order.id}>
            <Link href={`/${lang}/orders/${order.id}`} className="block space-y-1 rounded-card border border-line bg-white p-4 hover:border-ink">
              <p className="flex flex-wrap justify-between gap-2">
                <span className="font-bold">{fill(t.orders.code, { code: order.code })}</span>
                <span className="font-semibold">{statusLabel(t, order.status)}</span>
              </p>
              <p className="text-sm text-slate">{fill(t.orders.placedOn, { date: formatDateTime(order.created_at, lang) })}</p>
              <p className="price">{fill(t.orders.total, { total: formatPrice(order.grand_total_santim, lang) })}</p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
