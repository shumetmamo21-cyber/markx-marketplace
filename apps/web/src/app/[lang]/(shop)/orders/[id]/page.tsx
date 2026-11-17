import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { OrderActions } from "@/components/OrderActions";
import { PhotoUpload } from "@/components/PhotoUpload";
import { ProblemMessageForm } from "@/components/ProblemMessageForm";
import { ProblemPhotos } from "@/components/ProblemPhotos";
import { ReviewForm } from "@/components/ReviewForm";
import { serverApi } from "@/lib/api/server";
import { formatDateTime, formatPrice } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { codeLabel, statusLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";
import { getMe } from "@/lib/session";

export const metadata: Metadata = { robots: { index: false } };

export default async function OrderPage({ params }: PageProps<"/[lang]/orders/[id]">) {
  const { lang, id } = await params;
  if (!isLocale(lang)) notFound();
  if (!(await getMe())) redirect(`/${lang}/sign-in?next=/${lang}/orders/${id}`);
  const t = await getMessages(lang);
  const api = await serverApi();
  const [{ data: order, response }, pending] = await Promise.all([
    api.GET("/api/v1/me/orders/{order_id}", { params: { path: { order_id: id }, query: { lang } } }),
    api.GET("/api/v1/me/reviews/pending", { params: { query: { lang } } }),
  ]);
  if (response.status === 404 || response.status === 422 || !order) notFound();
  const o = t.orders;
  // Items the API says are waiting for a review (completed, window open).
  const toRate = new Set((pending.data ?? []).filter((item) => item.order_id === order.id).map((item) => item.order_item_id));
  const reviewText = { reviews: t.reviews, apiErrors: t.apiErrors };
  // Evidence photos, each link signed for this buyer (C-16, D-062).
  const photos = new Map(
    await Promise.all(
      order.seller_orders.filter((part) => part.problem).map(async (part) => {
        const { data } = await api.GET("/api/v1/me/orders/{order_id}/seller-orders/{seller_order_id}/problem/photos", {
          params: { path: { order_id: order.id, seller_order_id: part.id } },
        });
        return [part.id, data ?? []] as const;
      }),
    ),
  );

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <header className="space-y-1">
        <h1 className="text-2xl font-extrabold">{fill(o.code, { code: order.code })}</h1>
        <p className="text-slate">{fill(o.placedOn, { date: formatDateTime(order.created_at, lang) })} · {statusLabel(t, order.status)}</p>
        <p className="price text-lg">{fill(o.total, { total: formatPrice(order.grand_total_santim, lang) })}</p>
      </header>

      {order.seller_orders.map((part) => (
        <section key={part.id} aria-label={part.store_name} className="space-y-4 rounded-card border border-line bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-bold">{part.store_name}</h2>
            <span className="rounded-full border border-line px-3 py-1 text-sm font-semibold">{statusLabel(t, part.status)}</span>
          </div>

          {part.handover_code ? (
            <div className="space-y-2 rounded-card border-2 border-ink bg-paper p-4">
              <p className="font-bold">{o.handoverTitle}</p>
              <p className="price text-center text-4xl tracking-[0.3em]" aria-label={part.handover_code.split("").join(" ")}>{part.handover_code}</p>
              <p className="text-sm">{o.handoverWarning}</p>
            </div>
          ) : null}

          {part.seller_contact ? (
            <div className="space-y-1 text-sm">
              <p><a href={`tel:${part.seller_contact.phone}`} className="font-semibold underline">{fill(o.sellerContact, { phone: part.seller_contact.phone })}</a></p>
              <p>{fill(o.shopAddress, { address: part.seller_contact.shop_address })}</p>
            </div>
          ) : null}
          {part.shipment.rider_name || part.shipment.rider_phone ? (
            <p className="text-sm">{fill(o.rider, { name: part.shipment.rider_name ?? "", phone: part.shipment.rider_phone ?? "" })}</p>
          ) : null}
          {part.shipment.promised_hours && ["confirmed", "ready", "out_for_delivery"].includes(part.status) ? (
            <p className="text-sm text-slate">{fill(o.expected, { hours: part.shipment.promised_hours })}</p>
          ) : null}

          <div>
            <h3 className="mb-1 font-semibold">{o.items}</h3>
            <ul className="space-y-1 text-sm">
              {part.items.map((item) => (
                <li key={item.id} className="flex justify-between gap-3">
                  <span>{item.quantity} × {item.title}{item.variant_label ? ` (${item.variant_label})` : ""}</span>
                  <span className="price">{formatPrice(item.line_total_santim, lang)}</span>
                </li>
              ))}
              <li className="flex justify-between gap-3 text-slate"><span>{o.deliveryFee}</span><span className="price">{formatPrice(part.delivery_fee_santim, lang)}</span></li>
              <li className="flex justify-between gap-3 font-semibold"><span>{o.partTotal}</span><span className="price">{formatPrice(part.total_santim, lang)}</span></li>
            </ul>
            {part.items.filter((item) => toRate.has(item.id)).map((item) => (
              <details key={item.id} className="mt-3 rounded-card border border-adey p-3">
                <summary className="flex min-h-12 cursor-pointer items-center font-semibold">{t.reviews.rate}: {item.title}</summary>
                <ReviewForm target={{ kind: "write", orderId: order.id, itemId: item.id }} t={reviewText} />
              </details>
            ))}
            {part.payment_method ? (
              <p className="mt-1 text-sm text-slate">
                {fill(o.payment, { method: t.checkout[`pay_${part.payment_method}` as "pay_cash"] ?? part.payment_method })}
                {part.paid_at ? ` · ${o.paidAt}` : ""}
              </p>
            ) : null}
          </div>

          {part.problem ? (
            <div className="space-y-3 rounded-card border border-clay p-3 text-sm">
              <p className="font-semibold">{fill(o.problemOpen, { type: t.problemType[part.problem.problem_type as keyof typeof t.problemType] ?? part.problem.problem_type })}</p>
              <p className="whitespace-pre-line break-words">{part.problem.description}</p>
              {part.problem.messages.length ? (
                <div className="space-y-1">
                  <h3 className="font-semibold">{o.problemMessages}</h3>
                  <ul className="space-y-1">
                    {part.problem.messages.map((message, index) => (
                      <li key={index} className="break-words"><span className="font-semibold">{codeLabel(t, "author", message.author_type)}:</span> {message.body}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {(photos.get(part.id) ?? []).length ? (
                <div className="space-y-1">
                  <h3 className="font-semibold">{o.problemPhotos}</h3>
                  <ProblemPhotos photos={photos.get(part.id) ?? []} lang={lang} t={t} />
                </div>
              ) : null}
              {part.problem.decision ? (
                <p className="font-semibold">{fill(o.problemDecision, { decision: t.decision[part.problem.decision as keyof typeof t.decision] ?? part.problem.decision })}</p>
              ) : null}
              {part.problem.status !== "resolved" ? (
                <div className="space-y-3 border-t border-line pt-3">
                  <ProblemMessageForm orderId={order.id} sellerOrderId={part.id} t={{ orders: t.orders, apiErrors: t.apiErrors }} />
                  <p className="text-slate">{o.problemPhotoHint}</p>
                  <PhotoUpload
                    path={`/api/v1/me/orders/${order.id}/seller-orders/${part.id}/problem/photos`}
                    label={o.problemPhotoAdd}
                    send={o.problemPhotoSend}
                    sent={o.problemPhotoSent}
                    t={{ apiErrors: t.apiErrors }}
                  />
                </div>
              ) : null}
            </div>
          ) : null}

          <details>
            <summary className="flex min-h-12 cursor-pointer items-center font-semibold">{o.timeline}</summary>
            <ol className="space-y-2 border-l-2 border-line pl-4 text-sm">
              {part.events.map((event, index) => (
                <li key={`${event.to_status}-${index}`}>
                  <span className="font-semibold">{statusLabel(t, event.to_status)}</span>
                  <span className="text-slate"> · {formatDateTime(event.occurred_at, lang)}</span>
                  {event.reason ? <span className="block text-slate">{event.reason}</span> : null}
                </li>
              ))}
            </ol>
          </details>

          <OrderActions
            orderId={order.id}
            part={{ id: part.id, can_cancel: part.can_cancel, can_confirm_received: part.can_confirm_received, can_report_problem: part.can_report_problem }}
            t={o}
            types={t.problemType}
          />
        </section>
      ))}

      <p><Link href={`/${lang}/reviews`} className="inline-flex min-h-12 items-center font-semibold underline">{t.reviews.mine}</Link></p>

      {order.tracking_path ? (
        <section className="space-y-1 text-sm">
          <a href={order.tracking_path.replace("/api/v1/track/", `/${lang}/track/`)} className="font-semibold underline">{o.tracking}</a>
          <p className="text-slate">{o.trackingHint}</p>
        </section>
      ) : null}
    </div>
  );
}
