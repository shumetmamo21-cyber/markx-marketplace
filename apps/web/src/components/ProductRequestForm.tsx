"use client";

import { useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import type { Messages } from "@/lib/i18n";

import { ProblemNotice } from "./Resilience";

type Status = "idle" | "sending" | "sent" | "failed";

// "No result leads to a product-request form" (blueprint I.5, D.8).
export function ProductRequestForm({ query, t }: { query: string; t: Messages["search"] }) {
  const [status, setStatus] = useState<Status>("idle");
  const [code, setCode] = useState("unknown");
  if (status === "sent") {
    return <p role="status" className="font-semibold text-highland">{t.requestSent}</p>;
  }
  return (
    <form
      className="space-y-3"
      onSubmit={async (event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        setStatus("sending");
        const note = String(form.get("note") ?? "").trim();
        const phone = String(form.get("phone") ?? "").trim();
        const { error } = await browserApi.POST("/api/v1/product-requests", {
          body: {
            query: String(form.get("query") ?? query),
            note: note || null,
            contact_phone: phone || null,
          },
        });
        setCode(errorCode(error));
        setStatus(error ? "failed" : "sent");
      }}
    >
      <input type="hidden" name="query" value={query} />
      <label className="block space-y-1">
        <span className="text-sm font-semibold">{t.requestNote}</span>
        <input name="note" maxLength={500} className="min-h-12 w-full rounded-card border border-line bg-white px-3" />
      </label>
      <label className="block space-y-1">
        <span className="text-sm font-semibold">{t.requestPhone}</span>
        <input name="phone" type="tel" inputMode="tel" autoComplete="tel" className="min-h-12 w-full rounded-card border border-line bg-white px-3" />
      </label>
      {status === "failed" ? <ProblemNotice code={code} text={t.requestFailed} retry="submit" className="text-clay" /> : null}
      <button
        type="submit"
        disabled={status === "sending"}
        className="min-h-12 rounded-card bg-ink px-5 font-bold text-paper disabled:opacity-60"
      >
        {t.requestSend}
      </button>
    </form>
  );
}
