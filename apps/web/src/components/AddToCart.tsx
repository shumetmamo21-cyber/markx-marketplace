"use client";

import Link from "next/link";
import { useState } from "react";

import { browserApi } from "@/lib/api/browser";

type Labels = { add: string; adding: string; added: string; failed: string; cart: string };

// The cart lives on the server (D-036); a visitor gets one through a cookie.
export function AddToCart({ offerId, cartHref, labels, quantity = 1 }: { offerId: string; cartHref: string; labels: Labels; quantity?: number }) {
  const [state, setState] = useState<"idle" | "adding" | "added" | "failed">("idle");
  if (state === "added") {
    return (
      <p role="status" className="text-sm font-semibold">
        {labels.added} · <Link href={cartHref} className="underline">{labels.cart}</Link>
      </p>
    );
  }
  return (
    <div className="space-y-1">
      <button
        type="button"
        disabled={state === "adding"}
        onClick={async () => {
          setState("adding");
          const { error } = await browserApi.PUT("/api/v1/cart/items/{offer_id}", {
            params: { path: { offer_id: offerId } },
            body: { quantity },
          });
          setState(error ? "failed" : "added");
        }}
        className="min-h-12 w-full rounded-card bg-adey px-4 font-bold disabled:opacity-60"
      >
        {state === "adding" ? labels.adding : labels.add}
      </button>
      {state === "failed" ? <p role="alert" className="text-sm text-clay">{labels.failed}</p> : null}
    </div>
  );
}
