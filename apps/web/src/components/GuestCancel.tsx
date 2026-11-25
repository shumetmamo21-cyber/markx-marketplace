"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import { cancelRefusalText, type CancelWords } from "@/lib/guest-cancel";
import type { Locale } from "@/lib/i18n";

import { ProblemNotice } from "./Resilience";

type Props = {
  orderId: string;
  partId: string;
  expires: number;
  signature: string;
  lang: Locale;
  words: CancelWords;
};

// A guest's cancel button on one shop's part of the tracking page (F-28,
// D-109). It appears only when the API says the part may be cancelled (a
// guest's order the shop has not answered), asks once more, and the API
// checks again: a shop that answered in the meantime wins, and the guest is
// told so in words.
export function GuestCancel({ orderId, partId, expires, signature, lang, words }: Props) {
  const router = useRouter();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  const cancel = async () => {
    setBusy(true);
    setFailed(null);
    const { error } = await browserApi.POST("/api/v1/track/{order_id}/seller-orders/{seller_order_id}/cancel", {
      params: { path: { order_id: orderId, seller_order_id: partId }, query: { expires, signature, lang } },
    });
    setBusy(false);
    if (error) {
      setAsking(false);
      setFailed(errorCode(error));
    } else {
      router.refresh();
    }
  };

  return (
    <div className="space-y-2" data-guest-cancel="">
      <p className="text-sm text-slate">{words.hint}</p>
      {asking ? (
        <div className="space-y-2 rounded-card border border-ink p-3">
          <p className="font-semibold">{words.ask}</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy} onClick={() => void cancel()} data-cancel-yes="" className="min-h-12 rounded-card bg-clay px-4 font-bold text-white disabled:opacity-60">
              {busy ? words.cancelling : words.yes}
            </button>
            <button type="button" disabled={busy} onClick={() => setAsking(false)} className="min-h-12 rounded-card border border-ink px-4 font-semibold disabled:opacity-60">
              {words.no}
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => {
            setFailed(null);
            setAsking(true);
          }}
          className="min-h-12 rounded-card border border-ink px-4 font-semibold"
        >
          {words.cancel}
        </button>
      )}
      {failed ? <ProblemNotice code={failed} text={cancelRefusalText(words, failed)} retry={() => void cancel()} busy={busy} className="text-clay" /> : null}
    </div>
  );
}
