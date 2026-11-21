"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import type { components } from "@/lib/api/schema";
import { apiErrorText, fill, type Messages } from "@/lib/i18n";

import { ProblemNotice } from "./Resilience";

type Order = components["schemas"]["SellerOrderOut"];
type Payment = components["schemas"]["PaymentRecordIn"]["method"];
type Kind = "confirm" | "decline" | "ready" | "dispatch" | "handover" | "failed" | "return" | "payment" | "reply";

// Only once the goods are handed over, as the API decides (F-09, D-087): never in advance.
const PAYABLE = ["delivered", "completed", "disputed"];

/** What this seller may do next, by the life cycle (G.6); the API checks again. */
export function nextActions(order: Order): Kind[] {
  const collection = order.delivery_method === "shop_collection";
  const byStatus: Record<string, Kind[]> = {
    placed: ["confirm", "decline"],
    confirmed: ["ready"],
    ready: collection ? ["handover"] : ["dispatch"],
    out_for_delivery: ["handover", "failed"],
    delivery_failed: ["dispatch", "return"],
  };
  const actions = [...(byStatus[order.status] ?? [])];
  if (PAYABLE.includes(order.status) && !order.paid_at) actions.push("payment");
  if (order.problem && order.problem.status !== "resolved") actions.push("reply");
  return actions;
}

export function SellerOrderActions({ sellerId, order, t }: { sellerId: string; order: Order; t: Pick<Messages, "seller" | "checkout" | "apiErrors"> }) {
  const s = t.seller;
  const router = useRouter();
  const [open, setOpen] = useState<Kind | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<{ code: string; text: string; retry: () => void } | null>(null);
  const path = { params: { path: { seller_id: sellerId, seller_order_id: order.id } } };

  const run = async (call: () => Promise<{ error?: unknown }>) => {
    setBusy(true);
    setProblem(null);
    const { error } = await call();
    setBusy(false);
    if (!error) {
      setOpen(null);
      router.refresh();
      return;
    }
    const body = (error as { error?: { code?: string; details?: { attempts_left?: number } } }).error;
    const code = errorCode(error);
    // Shown with "try again" only when the connection or the server failed.
    const retry = () => void run(call);
    if (code === "handover_code_wrong") setProblem({ code, text: fill(s.codeWrong, { left: body?.details?.attempts_left ?? 0 }), retry });
    else if (code === "handover_code_locked") setProblem({ code, text: s.codeLocked, retry });
    else setProblem({ code, text: fill(s.actionFailed, { reason: apiErrorText(t, code) }), retry });
  };

  const actions = nextActions(order);
  if (!actions.length) return null;
  const label: Record<Kind, string> = {
    confirm: s.confirm, decline: s.decline, ready: s.markReady, dispatch: s.dispatch, handover: s.handover,
    failed: s.deliveryFailed, return: s.returned, payment: s.recordPayment, reply: s.problemReply,
  };
  const field = "min-h-12 w-full rounded-card border border-line bg-white px-3";
  const submit = "min-h-12 rounded-card bg-ink px-5 font-bold text-paper disabled:opacity-60";

  return (
    <section className="space-y-3 rounded-card border border-ink bg-white p-4" aria-label={s.title}>
      <div className="flex flex-wrap gap-2">
        {actions.map((kind) =>
          kind === "confirm" || kind === "ready" ? (
            <button
              key={kind}
              type="button"
              disabled={busy}
              onClick={() => run(() => browserApi.POST(kind === "confirm" ? "/api/v1/seller/{seller_id}/orders/{seller_order_id}/confirm" : "/api/v1/seller/{seller_id}/orders/{seller_order_id}/ready", path))}
              className="min-h-12 rounded-card bg-adey px-5 font-bold disabled:opacity-60"
            >
              {label[kind]}
            </button>
          ) : (
            <button
              key={kind}
              type="button"
              aria-expanded={open === kind}
              onClick={() => setOpen(open === kind ? null : kind)}
              className={`min-h-12 rounded-card border px-4 font-semibold ${kind === "decline" || kind === "failed" ? "border-clay text-clay" : "border-ink"}`}
            >
              {label[kind]}
            </button>
          ),
        )}
      </div>

      {open === "decline" || open === "failed" || open === "return" ? (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            const reason = String(new FormData(event.currentTarget).get("reason") ?? "").trim();
            const url = {
              decline: "/api/v1/seller/{seller_id}/orders/{seller_order_id}/decline",
              failed: "/api/v1/seller/{seller_id}/orders/{seller_order_id}/delivery-failed",
              return: "/api/v1/seller/{seller_id}/orders/{seller_order_id}/return",
            }[open] as "/api/v1/seller/{seller_id}/orders/{seller_order_id}/decline";
            void run(() => browserApi.POST(url, { ...path, body: { reason } }));
          }}
        >
          <label className="block space-y-1">
            <span className="text-sm font-semibold">{open === "decline" ? s.declineReason : open === "failed" ? s.failedReason : s.returnReason}</span>
            <input name="reason" required minLength={3} maxLength={500} className={field} />
          </label>
          <button type="submit" disabled={busy} className={submit}>{s.send}</button>
        </form>
      ) : null}

      {open === "dispatch" ? (
        <form
          className="grid gap-2 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const name = String(form.get("name") ?? "").trim();
            const phone = String(form.get("phone") ?? "").trim();
            void run(() => browserApi.POST("/api/v1/seller/{seller_id}/orders/{seller_order_id}/dispatch", { ...path, body: { rider_name: name || null, rider_phone: phone || null } }));
          }}
        >
          <label className="space-y-1"><span className="block text-sm font-semibold">{s.riderName}</span><input name="name" maxLength={200} className={field} /></label>
          <label className="space-y-1"><span className="block text-sm font-semibold">{s.riderPhone}</span><input name="phone" type="tel" inputMode="tel" className={field} /></label>
          <button type="submit" disabled={busy} className={`${submit} sm:col-span-2`}>{s.dispatch}</button>
        </form>
      ) : null}

      {open === "handover" ? (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            const code = String(new FormData(event.currentTarget).get("code") ?? "").trim();
            void run(() => browserApi.POST("/api/v1/seller/{seller_id}/orders/{seller_order_id}/handover", { ...path, body: { code } }));
          }}
        >
          <p className="text-sm">{s.handoverHint}</p>
          <p className="text-sm text-slate">{fill(s.attemptsLeft, { left: order.handover_attempts_left })}</p>
          <label className="block space-y-1">
            <span className="text-sm font-semibold">{s.codeLabel}</span>
            <input name="code" required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="off" className={`${field} text-center text-2xl tracking-[0.4em]`} />
          </label>
          <button type="submit" disabled={busy} className={submit}>{s.handover}</button>
        </form>
      ) : null}

      {open === "payment" ? (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            const method = String(new FormData(event.currentTarget).get("method")) as Payment;
            void run(() => browserApi.POST("/api/v1/seller/{seller_id}/orders/{seller_order_id}/payment", { ...path, body: { method } }));
          }}
        >
          <label className="block space-y-1">
            <span className="text-sm font-semibold">{s.paymentMethod}</span>
            <select name="method" defaultValue={order.payment_method ?? "cash"} className={field}>
              {(["cash", "telebirr", "bank_transfer", "ethqr"] as const).map((m) => <option key={m} value={m}>{t.checkout[`pay_${m}`]}</option>)}
            </select>
          </label>
          <button type="submit" disabled={busy} className={submit}>{s.recordPayment}</button>
        </form>
      ) : null}

      {open === "reply" ? (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            const body = String(new FormData(event.currentTarget).get("body") ?? "").trim();
            void run(() => browserApi.POST("/api/v1/seller/{seller_id}/orders/{seller_order_id}/problem/reply", { ...path, body: { body } }));
          }}
        >
          <label className="block space-y-1">
            <span className="text-sm font-semibold">{s.problemReply}</span>
            <textarea name="body" required minLength={3} maxLength={2000} rows={3} className="w-full rounded-card border border-line bg-white p-3" />
          </label>
          <button type="submit" disabled={busy} className={submit}>{s.send}</button>
        </form>
      ) : null}

      {problem ? <ProblemNotice code={problem.code} text={problem.text} retry={problem.retry} busy={busy} /> : null}
    </section>
  );
}
