"use client";

import { useRouter } from "next/navigation";
import { useId, useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import { apiErrorText, fill, type Messages } from "@/lib/i18n";

import { ProblemNotice } from "./Resilience";

type Props = {
  /** A new review of one item of a completed order, or a change to one. */
  target:
    | { kind: "write"; orderId: string; itemId: string }
    | { kind: "edit"; reviewId: string; productRating: number; sellerRating: number; body: string };
  t: Pick<Messages, "reviews" | "apiErrors">;
};

function StarChoice({ name, legend, initial, t }: { name: string; legend: string; initial?: number; t: Props["t"] }) {
  return (
    <fieldset className="space-y-1">
      <legend className="font-semibold">{legend}</legend>
      <div className="flex flex-wrap gap-2">
        {[1, 2, 3, 4, 5].map((stars) => (
          <label key={stars} className="flex min-h-12 min-w-12 cursor-pointer items-center justify-center gap-1 rounded-card border border-line bg-white px-3 has-[:checked]:border-ink has-[:checked]:bg-ink has-[:checked]:text-paper has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ink has-[:focus-visible]:ring-offset-2">
            <input type="radio" name={name} value={stars} required defaultChecked={initial === stars} className="sr-only" />
            <span aria-hidden="true">{stars} ★</span>
            <span className="sr-only">{fill(t.reviews.star, { stars })}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

// Rating a purchase (blueprint C-18): the product and the shop, one to five,
// and a few words if the buyer wants. Whether a review may be written or
// changed is the API's decision (completed order, open window, no reply yet).
export function ReviewForm({ target, t }: Props) {
  const router = useRouter();
  const id = useId();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string; code: string } | null>(null);
  const r = t.reviews;
  const editing = target.kind === "edit";
  return (
    <form
      className="space-y-3"
      onSubmit={async (event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const body = {
          product_rating: Number(form.get("product_rating")),
          seller_rating: Number(form.get("seller_rating")),
          body: String(form.get("body") ?? "").trim(),
        };
        setBusy(true);
        setMessage(null);
        const { error } =
          target.kind === "write"
            ? await browserApi.POST("/api/v1/me/orders/{order_id}/items/{item_id}/review", {
                params: { path: { order_id: target.orderId, item_id: target.itemId } },
                body,
              })
            : await browserApi.PUT("/api/v1/me/reviews/{review_id}", { params: { path: { review_id: target.reviewId } }, body });
        setBusy(false);
        if (error) setMessage({ ok: false, text: apiErrorText(t, errorCode(error)), code: errorCode(error) });
        else {
          setMessage({ ok: true, text: r.saved, code: "" });
          router.refresh();
        }
      }}
    >
      <StarChoice name="product_rating" legend={r.rateProduct} initial={editing ? target.productRating : undefined} t={t} />
      <StarChoice name="seller_rating" legend={r.rateSeller} initial={editing ? target.sellerRating : undefined} t={t} />
      <label htmlFor={`${id}-body`} className="block font-semibold">{r.body}</label>
      <textarea id={`${id}-body`} name="body" maxLength={2000} rows={3} defaultValue={editing ? target.body : ""} className="w-full rounded-card border border-line bg-white p-3" />
      <button type="submit" disabled={busy} className="min-h-12 rounded-card bg-adey px-5 font-bold disabled:opacity-60">{editing ? r.save : r.send}</button>
      {message?.ok ? <p role="status" className="font-semibold">{message.text}</p> : null}
      {message && !message.ok ? <ProblemNotice code={message.code} text={message.text} retry="submit" busy={busy} /> : null}
    </form>
  );
}
