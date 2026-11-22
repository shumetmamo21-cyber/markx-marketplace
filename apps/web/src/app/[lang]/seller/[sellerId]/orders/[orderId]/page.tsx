import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Countdown } from "@/components/Countdown";
import { PhotoUpload } from "@/components/PhotoUpload";
import { ProblemPhotos } from "@/components/ProblemPhotos";
import { SellerOrderActions } from "@/components/SellerOrderActions";
import { serverApi } from "@/lib/api/server";
import { formatDateTime, formatPrice } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { codeLabel, statusLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

export const metadata: Metadata = { robots: { index: false } };

export default async function SellerOrderPage({ params }: PageProps<"/[lang]/seller/[sellerId]/orders/[orderId]">) {
  const { lang, sellerId, orderId } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data: order } = await api.GET("/api/v1/seller/{seller_id}/orders/{seller_order_id}", {
    params: { path: { seller_id: sellerId, seller_order_id: orderId }, query: { lang } },
  });
  if (!order) notFound();
  const s = t.seller;
  const photos = order.problem
    ? ((await api.GET("/api/v1/seller/{seller_id}/orders/{seller_order_id}/problem/photos", { params: { path: { seller_id: sellerId, seller_order_id: orderId } } })).data ?? [])
    : [];
  // The buyer's gate photo (C-08; D-107): only when the API says this shop
  // is delivering the order to the door now; a five-minute private link.
  const gate = order.has_gate_photo
    ? (await api.GET("/api/v1/seller/{seller_id}/orders/{seller_order_id}/gate-photo", { params: { path: { seller_id: sellerId, seller_order_id: orderId } } })).data
    : undefined;
  const method = t.checkout[`method_${order.delivery_method}` as "method_seller_rider"] ?? order.delivery_method;

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <p><Link href={`/${lang}/seller/${sellerId}/orders`} className="font-semibold underline">{s.navOrders}</Link></p>
      <header className="space-y-1">
        <h1 className="text-2xl font-extrabold">{fill(t.orders.code, { code: order.order_code })}</h1>
        <p className="font-semibold">{statusLabel(t, order.status)}</p>
        <p className="text-sm text-slate">{fill(t.orders.placedOn, { date: formatDateTime(order.placed_at, lang) })}</p>
        {order.status === "placed" ? (
          <p>
            <Countdown deadline={order.response_deadline} byText={fill(s.answerBy, { time: formatDateTime(order.response_deadline, lang) })} leftText={s.answerLeft} lateText={s.answerLate} />
          </p>
        ) : null}
      </header>

      <SellerOrderActions sellerId={sellerId} order={order} t={{ seller: t.seller, checkout: t.checkout, apiErrors: t.apiErrors }} />

      <section className="space-y-2 rounded-card border border-line bg-white p-4">
        <h2 className="font-bold">{t.orders.items}</h2>
        <ul className="space-y-1 text-sm">
          {order.items.map((item) => (
            <li key={item.id} className="flex justify-between gap-3">
              <span>{item.quantity} × {item.title}{item.variant_label ? ` (${item.variant_label})` : ""}</span>
              <span className="price">{formatPrice(item.line_total_santim, lang)}</span>
            </li>
          ))}
          <li className="flex justify-between gap-3 text-slate"><span>{t.orders.deliveryFee}</span><span className="price">{formatPrice(order.delivery_fee_santim, lang)}</span></li>
          <li className="flex justify-between gap-3 font-semibold"><span>{t.orders.partTotal}</span><span className="price">{formatPrice(order.total_santim, lang)}</span></li>
        </ul>
        <p className="text-sm">
          {order.fee_santim !== null && order.fee_santim !== undefined
            ? fill(s.feeCharged, { amount: formatPrice(order.fee_santim, lang) })
            : fill(s.fee, { amount: formatPrice(order.estimated_fee_santim, lang) })}
          {" · "}
          <span className="font-semibold">{fill(s.payout, { amount: formatPrice(order.total_santim - (order.fee_santim ?? order.estimated_fee_santim), lang) })}</span>
        </p>
        <p className="text-sm text-slate">{fill(s.delivery, { method })}</p>
        {order.paid_at && order.paid_method ? (
          <p className="text-sm font-semibold">{fill(s.paid, { method: t.checkout[`pay_${order.paid_method}` as "pay_cash"] ?? order.paid_method })}</p>
        ) : null}
      </section>

      <section className="space-y-1 rounded-card border border-line bg-white p-4 text-sm">
        <h2 className="font-bold">{s.buyer}</h2>
        <p>{fill(s.buyerArea, { area: (lang === "am" ? order.delivery_area.area_name_am : order.delivery_area.area_name_en) ?? "" })}</p>
        {order.buyer ? (
          <>
            {order.buyer.recipient_name ? <p>{fill(s.recipient, { name: order.buyer.recipient_name })}</p> : null}
            {order.buyer.phone ? <p><a href={`tel:${order.buyer.phone}`} className="font-semibold underline">{fill(s.buyerPhone, { phone: order.buyer.phone })}</a></p> : null}
            {order.buyer.landmark ? <p>{fill(s.landmark, { landmark: order.buyer.landmark })}</p> : null}
            {order.buyer.driver_notes ? <p>{fill(s.notes, { notes: order.buyer.driver_notes })}</p> : null}
          </>
        ) : null}
        {gate ? (
          <div className="space-y-1 pt-2">
            <h3 className="font-semibold">{s.gatePhoto}</h3>
            <p className="text-slate">{s.gatePhotoLead}</p>
            {/* eslint-disable-next-line @next/next/no-img-element -- a private five-minute link from the API (D-107) */}
            <img src={gate.url} alt={s.gatePhotoAlt} className="max-h-72 w-auto max-w-full rounded-card border border-line object-contain" />
          </div>
        ) : null}
      </section>

      {order.problem ? (
        <section className="space-y-2 rounded-card border border-clay bg-white p-4 text-sm">
          <h2 className="font-bold">{s.problemTitle}</h2>
          <p className="font-semibold">{t.problemType[order.problem.problem_type as keyof typeof t.problemType] ?? order.problem.problem_type}</p>
          <p>{order.problem.description}</p>
          <ul className="space-y-1">
            {order.problem.messages.map((message, index) => (
              <li key={index} className="break-words"><span className="font-semibold">{codeLabel(t, "author", message.author_type)}:</span> {message.body}</li>
            ))}
          </ul>
          {photos.length ? (
            <div className="space-y-1">
              <h3 className="font-semibold">{t.orders.problemPhotos}</h3>
              <ProblemPhotos photos={photos} lang={lang} t={t} />
            </div>
          ) : null}
          {order.problem.decision ? (
            <p className="font-semibold">{fill(t.orders.problemDecision, { decision: t.decision[order.problem.decision as keyof typeof t.decision] ?? order.problem.decision })}</p>
          ) : null}
          {order.problem.status !== "resolved" ? (
            <div className="space-y-2 border-t border-line pt-3">
              <p className="text-slate">{t.orders.problemPhotoHint}</p>
              <PhotoUpload
                path={`/api/v1/seller/${sellerId}/orders/${orderId}/problem/photos`}
                label={t.orders.problemPhotoAdd}
                send={t.orders.problemPhotoSend}
                sent={t.orders.problemPhotoSent}
                t={{ apiErrors: t.apiErrors }}
              />
            </div>
          ) : null}
        </section>
      ) : null}

      <details className="rounded-card border border-line bg-white p-4">
        <summary className="cursor-pointer font-semibold">{t.orders.timeline}</summary>
        <ol className="mt-2 space-y-1 border-l-2 border-line pl-4 text-sm">
          {order.events.map((event, index) => (
            <li key={index}>
              <span className="font-semibold">{statusLabel(t, event.to_status)}</span>
              <span className="text-slate"> · {formatDateTime(event.occurred_at, lang)}</span>
              {event.reason ? <span className="block text-slate">{event.reason}</span> : null}
            </li>
          ))}
        </ol>
      </details>
    </div>
  );
}
