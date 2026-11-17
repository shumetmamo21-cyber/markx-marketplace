"use client";

import { useRouter } from "next/navigation";
import { useId, useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import { apiErrorText, type Messages } from "@/lib/i18n";

// The buyer adds to their own open problem (C-16); the shop and MarkX see it.
export function ProblemMessageForm({ orderId, sellerOrderId, t }: { orderId: string; sellerOrderId: string; t: Pick<Messages, "orders" | "apiErrors"> }) {
  const router = useRouter();
  const id = useId();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <form
      className="space-y-2"
      onSubmit={async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const body = String(new FormData(form).get("body") ?? "").trim();
        setBusy(true);
        setMessage(null);
        const { error } = await browserApi.POST("/api/v1/me/orders/{order_id}/seller-orders/{seller_order_id}/problem/messages", {
          params: { path: { order_id: orderId, seller_order_id: sellerOrderId } },
          body: { body },
        });
        setBusy(false);
        if (error) {
          setMessage({ ok: false, text: apiErrorText(t, errorCode(error)) });
          return;
        }
        form.reset();
        setMessage({ ok: true, text: t.orders.messageSent });
        router.refresh();
      }}
    >
      <label htmlFor={`${id}-body`} className="block font-semibold">{t.orders.problemMessage}</label>
      <textarea id={`${id}-body`} name="body" required minLength={1} maxLength={2000} rows={2} className="w-full rounded-card border border-line bg-white p-3" />
      <button type="submit" disabled={busy} className="min-h-12 rounded-card border border-ink px-4 font-semibold disabled:opacity-60">{t.orders.problemMessageSend}</button>
      {message ? <p role={message.ok ? "status" : "alert"} className={message.ok ? "font-semibold" : "font-semibold text-clay"}>{message.text}</p> : null}
    </form>
  );
}
