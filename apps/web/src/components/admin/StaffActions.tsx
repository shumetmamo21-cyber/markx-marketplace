"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import { apiErrorText, type Messages } from "@/lib/i18n";

type T = Pick<Messages, "admin" | "apiErrors">;
type Result = { error?: unknown };

const field = "min-h-12 w-full rounded-card border border-line bg-white px-3";
const button = "min-h-12 rounded-card bg-ink px-5 font-bold text-paper disabled:opacity-60";

/** One staff form: runs the call, shows the API's refusal in words, refreshes on success. */
function StaffForm({ t, onSubmit, children, label }: { t: T; onSubmit: (form: FormData) => Promise<Result>; children: ReactNode; label: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <form
      className="space-y-3"
      onSubmit={async (event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        setBusy(true);
        setMessage(null);
        const { error } = await onSubmit(form);
        setBusy(false);
        if (error) setMessage({ ok: false, text: apiErrorText(t, errorCode(error)) });
        else {
          setMessage({ ok: true, text: t.admin.done });
          router.refresh();
        }
      }}
    >
      {children}
      <button type="submit" disabled={busy} className={button}>{label}</button>
      {message ? <p role={message.ok ? "status" : "alert"} className={message.ok ? "font-semibold" : "font-semibold text-clay"}>{message.text}</p> : null}
    </form>
  );
}

const text = (form: FormData, name: string) => String(form.get(name) ?? "").trim();

export function ResolveProblemForm({ sellerOrderId, t }: { sellerOrderId: string; t: T }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.decide}
      onSubmit={(form) =>
        browserApi.POST("/api/v1/admin/orders/seller-orders/{seller_order_id}/resolve-problem", {
          params: { path: { seller_order_id: sellerOrderId } },
          body: {
            decision: text(form, "decision") as "no_action" | "seller_refunded",
            reason: text(form, "reason"),
            goods_returned: form.get("goods_returned") === "on",
          },
        })
      }
    >
      <fieldset className="space-y-2">
        <legend className="font-semibold">{a.decision}</legend>
        <label className="flex min-h-12 items-center gap-3"><input type="radio" name="decision" value="no_action" defaultChecked className="h-5 w-5" />{a.decisionNoAction}</label>
        <label className="flex min-h-12 items-center gap-3"><input type="radio" name="decision" value="seller_refunded" className="h-5 w-5" />{a.decisionRefunded}</label>
      </fieldset>
      <label className="flex min-h-12 items-center gap-3"><input type="checkbox" name="goods_returned" className="h-5 w-5" />{a.goodsReturned}</label>
      <label className="block space-y-1"><span className="text-sm font-semibold">{a.reason}</span><textarea name="reason" required minLength={3} maxLength={500} rows={3} className="w-full rounded-card border border-line bg-white p-3" /></label>
    </StaffForm>
  );
}

export function DispatchForm({ sellerOrderId, t }: { sellerOrderId: string; t: T }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.dispatch}
      onSubmit={(form) =>
        browserApi.POST("/api/v1/admin/orders/seller-orders/{seller_order_id}/dispatch", {
          params: { path: { seller_order_id: sellerOrderId } },
          body: { rider_name: text(form, "name") || null, rider_phone: text(form, "phone") || null },
        })
      }
    >
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="space-y-1"><span className="block text-sm font-semibold">{a.riderName}</span><input name="name" className={field} /></label>
        <label className="space-y-1"><span className="block text-sm font-semibold">{a.riderPhone}</span><input name="phone" type="tel" className={field} /></label>
      </div>
    </StaffForm>
  );
}

export function ReissueCodeForm({ sellerOrderId, t }: { sellerOrderId: string; t: T }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.reissue}
      onSubmit={(form) =>
        browserApi.POST("/api/v1/admin/orders/seller-orders/{seller_order_id}/reissue-code", {
          params: { path: { seller_order_id: sellerOrderId } },
          body: { reason: text(form, "reason") },
        })
      }
    >
      <label className="block space-y-1"><span className="text-sm font-semibold">{a.reissueReason}</span><input name="reason" required minLength={3} className={field} /></label>
    </StaffForm>
  );
}

export function DocumentReview({ sellerId, documentId, t }: { sellerId: string; documentId: string; t: T }) {
  const a = t.admin;
  const [opening, setOpening] = useState(false);
  return (
    <div className="space-y-2">
      <button
        type="button"
        disabled={opening}
        onClick={async () => {
          setOpening(true);
          const { data } = await browserApi.POST("/api/v1/admin/sellers/{seller_id}/documents/{document_id}/link", {
            params: { path: { seller_id: sellerId, document_id: documentId } },
          });
          setOpening(false);
          if (data) window.open(data.url, "_blank", "noopener,noreferrer");
        }}
        className="min-h-12 rounded-card border border-ink px-4 font-semibold"
      >
        {a.viewDocument}
      </button>
      <StaffForm
        t={t}
        label={a.accept}
        onSubmit={(form) =>
          browserApi.POST("/api/v1/admin/sellers/{seller_id}/documents/{document_id}/review", {
            params: { path: { seller_id: sellerId, document_id: documentId } },
            body: form.get("decision") === "rejected" ? { decision: "rejected", note: text(form, "note") } : { decision: "accepted" },
          })
        }
      >
        <div className="flex flex-wrap gap-4">
          <label className="flex min-h-12 items-center gap-2"><input type="radio" name="decision" value="accepted" defaultChecked className="h-5 w-5" />{a.accept}</label>
          <label className="flex min-h-12 items-center gap-2"><input type="radio" name="decision" value="rejected" className="h-5 w-5" />{a.reject}</label>
        </div>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.rejectNote}</span><input name="note" className={field} /></label>
      </StaffForm>
    </div>
  );
}

export function SellerDecision({ sellerId, t }: { sellerId: string; t: T }) {
  const a = t.admin;
  const path = { params: { path: { seller_id: sellerId } } };
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <section className="space-y-2">
        <h3 className="font-bold">{a.approveTitle}</h3>
        <StaffForm
          t={t}
          label={a.approve}
          onSubmit={(form) =>
            browserApi.POST("/api/v1/admin/sellers/{seller_id}/approve", {
              ...path,
              body: {
                verification_level: form.get("level") === "2" ? 2 : 1,
                shop_visited: form.get("visited") === "on",
                payout_account_name_matches: form.get("payout") === "on",
              },
            })
          }
        >
          <fieldset className="space-y-1">
            <legend className="text-sm font-semibold">{a.level}</legend>
            <label className="flex min-h-12 items-center gap-2"><input type="radio" name="level" value="1" className="h-5 w-5" />{a.level1}</label>
            <label className="flex min-h-12 items-center gap-2"><input type="radio" name="level" value="2" defaultChecked className="h-5 w-5" />{a.level2}</label>
          </fieldset>
          <label className="flex min-h-12 items-center gap-2"><input type="checkbox" name="visited" className="h-5 w-5" />{a.shopVisited}</label>
          <label className="flex min-h-12 items-center gap-2"><input type="checkbox" name="payout" className="h-5 w-5" />{a.payoutMatches}</label>
        </StaffForm>
      </section>
      <section className="space-y-2">
        <h3 className="font-bold">{a.requestDocuments}</h3>
        <StaffForm t={t} label={a.requestDocuments} onSubmit={(form) => browserApi.POST("/api/v1/admin/sellers/{seller_id}/request-documents", { ...path, body: { reason: text(form, "reason") } })}>
          <label className="block space-y-1"><span className="text-sm font-semibold">{a.requestReason}</span><input name="reason" required minLength={3} className={field} /></label>
        </StaffForm>
      </section>
      <section className="space-y-2">
        <h3 className="font-bold">{a.rejectApplication}</h3>
        <StaffForm t={t} label={a.rejectApplication} onSubmit={(form) => browserApi.POST("/api/v1/admin/sellers/{seller_id}/reject", { ...path, body: { reason: text(form, "reason") } })}>
          <label className="block space-y-1"><span className="text-sm font-semibold">{a.rejectReason}</span><input name="reason" required minLength={3} className={field} /></label>
        </StaffForm>
      </section>
    </div>
  );
}

export function AddSynonymForm({ t }: { t: T }) {
  const a = t.admin;
  return (
    <StaffForm t={t} label={a.addSynonym} onSubmit={(form) => browserApi.POST("/api/v1/admin/search/synonyms", { body: { term: text(form, "term"), expansion: text(form, "expansion") } })}>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="space-y-1"><span className="block text-sm font-semibold">{a.term}</span><input name="term" required maxLength={100} className={field} /></label>
        <label className="space-y-1"><span className="block text-sm font-semibold">{a.expansion}</span><input name="expansion" required maxLength={100} className={field} /></label>
      </div>
    </StaffForm>
  );
}

export function RemoveSynonymButton({ id, t }: { id: string; t: T }) {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={async () => {
        await browserApi.DELETE("/api/v1/admin/search/synonyms/{synonym_id}", { params: { path: { synonym_id: id } } });
        router.refresh();
      }}
      className="min-h-12 px-3 font-semibold underline"
    >
      {t.admin.remove}
    </button>
  );
}
