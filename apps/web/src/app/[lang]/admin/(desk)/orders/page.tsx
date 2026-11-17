import { notFound } from "next/navigation";

import { DispatchForm, ReissueCodeForm, ResolveProblemForm } from "@/components/admin/StaffActions";
import { serverApi } from "@/lib/api/server";
import { formatDateTime, formatPrice } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { statusLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

const CODE = /^MX-[34679ACDEFGHJKMNPQRTUVWXY]{6}$/;

// The orders desk (P11): any order by its code, every part with its full
// timeline; dispatch, a new handover code, and problem decisions. Staff
// never see the handover code itself.
export default async function OrdersDeskPage({ params, searchParams }: PageProps<"/[lang]/admin/orders">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const raw = (await searchParams).code;
  const code = (typeof raw === "string" ? raw : "").trim().toUpperCase();
  const api = await serverApi();
  const found = CODE.test(code) ? await api.GET("/api/v1/admin/orders/{code}", { params: { path: { code }, query: { lang } } }) : null;
  const order = found?.data;
  const a = t.admin;
  const text = { admin: a, apiErrors: t.apiErrors };
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-extrabold">{a.ordersTitle}</h1>
      <form method="get" className="flex max-w-md items-end gap-2">
        <label className="flex-1 space-y-1">
          <span className="block text-sm font-semibold">{a.findCode}</span>
          <input name="code" defaultValue={code} placeholder="MX-…" className="min-h-12 w-full rounded-card border border-line bg-white px-3 uppercase" />
        </label>
        <button type="submit" className="min-h-12 rounded-card bg-adey px-5 font-bold">{a.find}</button>
      </form>
      {code && !order ? <p role="alert" className="text-clay">{a.notFound}</p> : null}
      {order ? (
        <div className="space-y-4">
          <p className="text-slate">
            {fill(t.orders.code, { code: order.code })} · {formatDateTime(order.created_at, lang)} · {statusLabel(t, order.status)} · {formatPrice(order.grand_total_santim, lang)}
          </p>
          {order.seller_orders.map((part) => (
            <section key={part.id} className="space-y-3 rounded-card border border-line bg-white p-4">
              <div className="flex flex-wrap justify-between gap-2">
                <h2 className="text-lg font-bold">{part.store_name}</h2>
                <span className="rounded-full border border-line px-3 py-1 text-sm font-semibold">{statusLabel(t, part.status)}</span>
              </div>
              <ul className="text-sm">
                {part.items.map((item) => <li key={item.id}>{item.quantity} × {item.title} · {formatPrice(item.line_total_santim, lang)}</li>)}
              </ul>
              {part.problem ? (
                <div className="space-y-2 rounded-card border border-clay p-3 text-sm">
                  <p className="font-semibold">{t.problemType[part.problem.problem_type as keyof typeof t.problemType] ?? part.problem.problem_type}</p>
                  <p>{part.problem.description}</p>
                  <ul className="space-y-1">{part.problem.messages.map((m, i) => <li key={i}><span className="font-semibold">{m.author_type}:</span> {m.body}</li>)}</ul>
                  {part.problem.decision ? <p className="font-semibold">{part.problem.decision === "seller_refunded" ? a.decisionRefunded : a.decisionNoAction} · {part.problem.decision_reason}</p> : null}
                </div>
              ) : null}
              {part.status === "disputed" ? (
                <div className="space-y-2 border-t border-line pt-3">
                  <h3 className="font-bold">{a.decideTitle}</h3>
                  <ResolveProblemForm sellerOrderId={part.id} t={text} />
                </div>
              ) : null}
              {["ready", "delivery_failed"].includes(part.status) && part.delivery_method !== "shop_collection" ? (
                <div className="border-t border-line pt-3"><DispatchForm sellerOrderId={part.id} t={text} /></div>
              ) : null}
              {["ready", "out_for_delivery", "delivery_failed"].includes(part.status) ? (
                <div className="border-t border-line pt-3"><ReissueCodeForm sellerOrderId={part.id} t={text} /></div>
              ) : null}
              <details>
                <summary className="flex min-h-12 cursor-pointer items-center font-semibold">{t.orders.timeline}</summary>
                <ol className="space-y-1 border-l-2 border-line pl-4 text-sm">
                  {part.events.map((event, i) => (
                    <li key={i}>
                      <span className="font-semibold">{statusLabel(t, event.to_status)}</span>
                      <span className="text-slate"> · {event.actor_type} · {formatDateTime(event.occurred_at, lang)}</span>
                      {event.reason ? <span className="block text-slate">{event.reason}</span> : null}
                    </li>
                  ))}
                </ol>
              </details>
            </section>
          ))}
        </div>
      ) : null}
    </div>
  );
}
