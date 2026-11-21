"use client";

import Link from "next/link";
import { useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";

import { ProblemNotice } from "./Resilience";

type Labels = { add: string; adding: string; added: string; failed: string; cart: string };

// The cart lives on the server (D-036); a visitor gets one through a cookie.
export function AddToCart({ offerId, cartHref, labels, quantity = 1 }: { offerId: string; cartHref: string; labels: Labels; quantity?: number }) {
  const [state, setState] = useState<"idle" | "adding" | "added" | "failed">("idle");
  const [code, setCode] = useState("unknown");
  const add = async () => {
    setState("adding");
    const { error } = await browserApi.PUT("/api/v1/cart/items/{offer_id}", {
      params: { path: { offer_id: offerId } },
      body: { quantity },
    });
    setCode(errorCode(error));
    setState(error ? "failed" : "added");
  };
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
        onClick={add}
        className="min-h-12 w-full rounded-card bg-adey px-4 font-bold disabled:opacity-60"
      >
        {state === "adding" ? labels.adding : labels.add}
      </button>
      {state === "failed" ? <ProblemNotice code={code} text={labels.failed} retry={add} className="text-sm text-clay" /> : null}
    </div>
  );
}
