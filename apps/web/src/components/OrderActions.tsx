"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import type { components } from "@/lib/api/schema";
import type { Messages } from "@/lib/i18n";

import { ProblemNotice } from "./Resilience";

type ProblemType = components["schemas"]["ProblemIn"]["problem_type"];
const PROBLEM_TYPES: ProblemType[] = ["not_received", "wrong_item", "not_as_described", "damaged", "suspected_fake", "other"];

type Props = {
  orderId: string;
  part: { id: string; can_cancel: boolean; can_confirm_received: boolean; can_report_problem: boolean };
  t: Messages["orders"];
  types: Messages["problemType"];
};

// The buyer's buttons on one seller's part. The API decides what is allowed;
// these only appear when it says so (can_*), and it checks again.
export function OrderActions({ orderId, part, t, types }: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  // The failed action's code and how to send it again.
  const [failed, setFailed] = useState<{ code: string; retry: () => void } | null>(null);
  const [reporting, setReporting] = useState(false);
  const base = { params: { path: { order_id: orderId, seller_order_id: part.id } } };

  const act = async (name: string, run: () => Promise<{ error?: unknown }>) => {
    setBusy(name);
    setFailed(null);
    const { error } = await run();
    setBusy(null);
    if (error) setFailed({ code: errorCode(error), retry: () => void act(name, run) });
    else router.refresh();
  };

  if (!part.can_cancel && !part.can_confirm_received && !part.can_report_problem) return null;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {part.can_confirm_received ? (
          <button type="button" disabled={busy !== null} onClick={() => act("received", () => browserApi.POST("/api/v1/me/orders/{order_id}/seller-orders/{seller_order_id}/confirm-received", base))} className="min-h-12 rounded-card bg-adey px-4 font-bold disabled:opacity-60">
            {busy === "received" ? t.receiving : t.received}
          </button>
        ) : null}
        {part.can_report_problem && !reporting ? (
          <button type="button" onClick={() => setReporting(true)} className="min-h-12 rounded-card border border-clay px-4 font-semibold text-clay">
            {t.problem}
          </button>
        ) : null}
        {part.can_cancel ? (
          <button type="button" disabled={busy !== null} onClick={() => act("cancel", () => browserApi.POST("/api/v1/me/orders/{order_id}/seller-orders/{seller_order_id}/cancel", { ...base, body: {} }))} className="min-h-12 rounded-card border border-ink px-4 font-semibold disabled:opacity-60">
            {busy === "cancel" ? t.cancelling : t.cancel}
          </button>
        ) : null}
      </div>
      {reporting ? (
        <form
          className="space-y-3 rounded-card border border-line p-3"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void act("problem", () =>
              browserApi.POST("/api/v1/me/orders/{order_id}/seller-orders/{seller_order_id}/problem", {
                ...base,
                body: { problem_type: String(form.get("type")) as ProblemType, description: String(form.get("description") ?? "").trim() },
              }),
            );
          }}
        >
          <label className="block space-y-1">
            <span className="text-sm font-semibold">{t.problemType}</span>
            <select name="type" className="min-h-12 w-full rounded-card border border-line bg-white px-3">
              {PROBLEM_TYPES.map((type) => <option key={type} value={type}>{types[type]}</option>)}
            </select>
          </label>
          <label className="block space-y-1">
            <span className="text-sm font-semibold">{t.problemDescription}</span>
            <textarea name="description" required minLength={3} maxLength={2000} rows={3} className="w-full rounded-card border border-line bg-white p-3" />
          </label>
          <button type="submit" disabled={busy !== null} className="min-h-12 rounded-card bg-clay px-4 font-bold text-white disabled:opacity-60">{t.problemSend}</button>
        </form>
      ) : null}
      {failed ? <ProblemNotice code={failed.code} text={t.actionFailed} retry={failed.retry} busy={busy !== null} className="text-clay" /> : null}
    </div>
  );
}
