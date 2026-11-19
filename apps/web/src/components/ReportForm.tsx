"use client";

import { useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import type { components } from "@/lib/api/schema";
import { apiErrorText, type Messages } from "@/lib/i18n";

type Target = components["schemas"]["ReportTarget"];
type Reason = components["schemas"]["ReportReason"];
const REASONS: Reason[] = ["counterfeit", "prohibited", "wrong_information", "offensive", "fraud", "spam", "other"];

type Props = {
  /** A product, listing or review by its id; a shop by its link name. */
  target: { type: Exclude<Target, "store">; id: string } | { type: "store"; slug: string };
  t: Pick<Messages, "report" | "apiErrors"> & { reasons: Messages["labels"]["reportReason"] };
};

// A report link on every listing, shop and review (blueprint C-30, D-067).
// Anyone may send one, signed in or not; the API limits how many, refuses a
// second open report from the same person, and decides what is visible.
export function ReportForm({ target, t }: Props) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const title = t.report[target.type];
  if (message?.ok) return <p role="status" className="text-sm font-semibold">{message.text}</p>;
  return (
    <details className="text-sm">
      <summary className="inline-flex min-h-12 cursor-pointer items-center text-slate underline">{title}</summary>
      <form
        className="mt-2 space-y-3 rounded-card border border-line bg-white p-3"
        aria-label={title}
        onSubmit={async (event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const note = String(form.get("note") ?? "").trim();
          setBusy(true);
          setMessage(null);
          const { error } = await browserApi.POST("/api/v1/reports", {
            body: {
              target_type: target.type,
              ...(target.type === "store" ? { store_slug: target.slug } : { target_id: target.id }),
              reason: String(form.get("reason")) as Reason,
              note: note || null,
            },
          });
          setBusy(false);
          setMessage(error ? { ok: false, text: apiErrorText(t, errorCode(error)) } : { ok: true, text: t.report.thanks });
        }}
      >
        <label className="block space-y-1">
          <span className="font-semibold">{t.report.reason}</span>
          <select name="reason" className="min-h-12 w-full rounded-card border border-line bg-white px-3">
            {REASONS.map((reason) => <option key={reason} value={reason}>{t.reasons[reason]}</option>)}
          </select>
        </label>
        <label className="block space-y-1">
          <span className="font-semibold">{t.report.note}</span>
          <textarea name="note" maxLength={500} rows={2} className="w-full rounded-card border border-line bg-white p-3" />
        </label>
        <button type="submit" disabled={busy} className="min-h-12 rounded-card border border-ink px-4 font-semibold disabled:opacity-60">{t.report.send}</button>
        {message ? <p role="alert" className="font-semibold text-clay">{message.text}</p> : null}
      </form>
    </details>
  );
}
