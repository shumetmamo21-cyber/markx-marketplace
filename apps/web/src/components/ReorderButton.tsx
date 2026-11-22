"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import type { Reorder } from "@/lib/api/types";
import { formatPrice } from "@/lib/format";
import { fill, type Locale, type Messages } from "@/lib/i18n";

import { ProblemNotice } from "./Resilience";

type Text = Pick<Messages["orders"], "reorder" | "reordering" | "reorderLead" | "reorderDone" | "reorderPriceChanged" | "reorderUnavailable" | "reorderCartFull" | "reorderOtherShops" | "reorderGoToCart" | "reorderFailed">;

// Order again in one tap (blueprint C-19; D-106). The API puts the order's
// items back in the cart at today's prices and says what it could not; the
// cart re-checks everything as always. When every item went in, the buyer
// lands on the cart at once; otherwise this says what changed first.
export function ReorderButton({ orderId, lang, t }: { orderId: string; lang: Locale; t: Text }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [result, setResult] = useState<Reorder | null>(null);
  const cart = `/${lang}/cart`;
  const reorder = async () => {
    setBusy(true);
    setFailed(null);
    const { data, error } = await browserApi.POST("/api/v1/me/orders/{order_id}/reorder", {
      params: { path: { order_id: orderId }, query: { lang } },
    });
    setBusy(false);
    if (error || !data) {
      setFailed(errorCode(error));
      return;
    }
    if (data.missing.length === 0 && data.added.every((line) => line.unit_price_santim === line.paid_unit_price_santim)) {
      router.push(cart);
      return;
    }
    setResult(data);
  };
  if (result) {
    const changed = result.added.filter((line) => line.unit_price_santim !== line.paid_unit_price_santim);
    return (
      <div role="status" className="space-y-2 rounded-card border border-line bg-white p-4 text-sm">
        {result.added.length ? <p className="font-semibold">{fill(t.reorderDone, { count: result.added.length })}</p> : null}
        {changed.length ? (
          <ul className="list-disc space-y-1 pl-5">
            {changed.map((line) => (
              <li key={line.offer_id}>
                {fill(t.reorderPriceChanged, { title: line.title, now: formatPrice(line.unit_price_santim, lang), paid: formatPrice(line.paid_unit_price_santim, lang) })}
              </li>
            ))}
          </ul>
        ) : null}
        {result.missing.length ? (
          <ul className="space-y-1">
            {result.missing.map((line) => (
              <li key={line.offer_id} className="text-clay">
                {fill(line.reason === "cart_full" ? t.reorderCartFull : t.reorderUnavailable, { title: line.title })}
                {line.product_slug ? (
                  <> · <Link href={`/${lang}/p/${line.product_slug}`} className="font-semibold underline">{t.reorderOtherShops}</Link></>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
        {result.added.length ? (
          <Link href={cart} className="inline-flex min-h-12 items-center rounded-card bg-adey px-4 font-bold">{t.reorderGoToCart}</Link>
        ) : null}
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <button type="button" onClick={reorder} disabled={busy} className="min-h-12 w-full rounded-card bg-adey px-4 font-bold disabled:opacity-60 sm:w-auto">
        {busy ? t.reordering : t.reorder}
      </button>
      <p className="text-sm text-slate">{t.reorderLead}</p>
      {failed ? <ProblemNotice code={failed} text={t.reorderFailed} retry={reorder} className="text-sm text-clay" /> : null}
    </div>
  );
}
