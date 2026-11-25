import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { GuestCancel } from "@/components/GuestCancel";
import { serverApi } from "@/lib/api/server";
import { formatDateTime, formatPrice } from "@/lib/format";
import { cancelWords, guestMayCancel } from "@/lib/guest-cancel";
import { fill, isLocale } from "@/lib/i18n";
import { statusLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

export const metadata: Metadata = { robots: { index: false, follow: false }, referrer: "no-referrer" };

function one(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

// The order page from a secure link, without signing in (blueprint D.14,
// D-048). The API leaves out the recipient's details and every action; a
// forged or expired link is "not found". The handover code comes only on a
// guest's order, whose only page this is (C-07, D-108), and so does the one
// action: cancelling a shop's part before the shop answers (F-28, D-109).
export default async function TrackPage({ params, searchParams }: PageProps<"/[lang]/track/[id]">) {
  const { lang, id } = await params;
  if (!isLocale(lang)) notFound();
  const raw = await searchParams;
  const expires = Number.parseInt(one(raw.expires), 10);
  const signature = one(raw.signature);
  if (!Number.isFinite(expires) || signature.length < 20) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data: order } = await api.GET("/api/v1/track/{order_id}", {
    params: { path: { order_id: id }, query: { expires, signature, lang } },
  });
  if (!order) notFound();
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <header className="space-y-1">
        <h1 className="text-2xl font-extrabold">{fill(t.orders.code, { code: order.code })}</h1>
        <p className="text-slate">{fill(t.orders.placedOn, { date: formatDateTime(order.created_at, lang) })} · {statusLabel(t, order.status)}</p>
        {order.is_guest ? <p className="font-semibold">{t.orders.guestNote}</p> : null}
      </header>
      {order.seller_orders.map((part) => (
        <section key={part.id} aria-label={part.store_name} className="space-y-3 rounded-card border border-line bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-bold">{part.store_name}</h2>
            <span className="rounded-full border border-line px-3 py-1 text-sm font-semibold">{statusLabel(t, part.status)}</span>
          </div>
          {part.seller_contact ? <p className="text-sm">{fill(t.orders.sellerContact, { phone: part.seller_contact.phone })}</p> : null}
          {part.handover_code ? (
            <div className="space-y-1 rounded-card border border-ink p-3" data-handover-code="">
              <p className="font-semibold">{t.orders.handoverTitle}</p>
              <p className="price text-3xl font-extrabold tracking-[0.3em]">{part.handover_code}</p>
              <p className="text-sm">{t.orders.handoverWarning}</p>
            </div>
          ) : null}
          {guestMayCancel(order, part) ? (
            <GuestCancel orderId={order.id} partId={part.id} expires={expires} signature={signature} lang={lang} words={cancelWords(t, part.store_name)} />
          ) : null}
          <ul className="space-y-1 text-sm">
            {part.items.map((item) => (
              <li key={item.id} className="flex justify-between gap-3">
                <span>{item.quantity} × {item.title}</span>
                <span className="price">{formatPrice(item.line_total_santim, lang)}</span>
              </li>
            ))}
          </ul>
          <ol className="space-y-1 border-l-2 border-line pl-4 text-sm">
            {part.events.map((event, index) => (
              <li key={`${event.to_status}-${index}`}>
                <span className="font-semibold">{statusLabel(t, event.to_status)}</span>
                <span className="text-slate"> · {formatDateTime(event.occurred_at, lang)}</span>
              </li>
            ))}
          </ol>
        </section>
      ))}
      <p className="text-sm text-slate">{t.product.inspect}</p>
    </div>
  );
}
