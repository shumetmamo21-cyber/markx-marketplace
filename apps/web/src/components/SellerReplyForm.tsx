"use client";

import { useRouter } from "next/navigation";
import { useId, useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import { apiErrorText, type Messages } from "@/lib/i18n";

// The shop's one reply to a review, which it may reword (blueprint S-16).
// The API checks the member's role and that the review is published.
export function SellerReplyForm({ sellerId, reviewId, current, t }: { sellerId: string; reviewId: string; current: string | null; t: Pick<Messages, "seller" | "apiErrors"> }) {
  const router = useRouter();
  const id = useId();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const s = t.seller;
  return (
    <form
      className="space-y-2"
      onSubmit={async (event) => {
        event.preventDefault();
        const body = String(new FormData(event.currentTarget).get("body") ?? "").trim();
        setBusy(true);
        setMessage(null);
        const { error } = await browserApi.POST("/api/v1/seller/{seller_id}/reviews/{review_id}/reply", {
          params: { path: { seller_id: sellerId, review_id: reviewId } },
          body: { body },
        });
        setBusy(false);
        if (error) setMessage({ ok: false, text: apiErrorText(t, errorCode(error)) });
        else {
          setMessage({ ok: true, text: s.saved });
          router.refresh();
        }
      }}
    >
      <label htmlFor={`${id}-reply`} className="block text-sm font-semibold">{s.replyLabel}</label>
      <textarea id={`${id}-reply`} name="body" required minLength={1} maxLength={1000} rows={3} defaultValue={current ?? ""} className="w-full rounded-card border border-line bg-white p-3" />
      <button type="submit" disabled={busy} className="min-h-12 rounded-card bg-ink px-4 font-bold text-paper disabled:opacity-60">{current ? s.replyChange : s.replySend}</button>
      {message ? <p role={message.ok ? "status" : "alert"} className={message.ok ? "font-semibold" : "font-semibold text-clay"}>{message.text}</p> : null}
    </form>
  );
}
