"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useState } from "react";

import { browserApi, errorCode, sendForm } from "@/lib/api/browser";
import { apiErrorText, fill, type Messages } from "@/lib/i18n";

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

// -- catalogue curation (AD-02) --------------------------------------------------

export function ProposalDecision({ productId, approved, t }: { productId: string; approved: { id: string; name: string }[]; t: T }) {
  const a = t.admin;
  const path = { params: { path: { product_id: productId } } };
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <StaffForm t={t} label={a.approveProduct} onSubmit={() => browserApi.POST("/api/v1/admin/catalog/products/{product_id}/approve", path)}>
        {null}
      </StaffForm>
      <StaffForm t={t} label={a.archiveProduct} onSubmit={(form) => browserApi.POST("/api/v1/admin/catalog/products/{product_id}/archive", { ...path, body: { note: text(form, "note") || null } })}>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.archiveNote}</span><input name="note" maxLength={500} className={field} /></label>
      </StaffForm>
      {approved.length > 0 ? (
        <StaffForm t={t} label={a.mergeProduct} onSubmit={(form) => browserApi.POST("/api/v1/admin/catalog/products/{product_id}/merge", { ...path, body: { into_product_id: text(form, "into") } })}>
          <label className="block space-y-1">
            <span className="text-sm font-semibold">{a.mergeInto}</span>
            <select name="into" required defaultValue="" className={field}>
              <option value="" disabled>{a.chooseProduct}</option>
              {approved.map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}
            </select>
          </label>
        </StaffForm>
      ) : null}
    </div>
  );
}

// -- invitations (D.3, D-019) ------------------------------------------------------

export function InviteForm({ t }: { t: T }) {
  const a = t.admin;
  return (
    <StaffForm t={t} label={a.invite} onSubmit={(form) => browserApi.POST("/api/v1/admin/sellers/invitations", { body: { phone: text(form, "phone"), note: text(form, "note") || null } })}>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="space-y-1"><span className="block text-sm font-semibold">{a.invitePhone}</span><input name="phone" type="tel" required minLength={9} maxLength={24} className={field} /></label>
        <label className="space-y-1"><span className="block text-sm font-semibold">{a.inviteNote}</span><input name="note" maxLength={300} className={field} /></label>
      </div>
    </StaffForm>
  );
}

export function RevokeInvitationForm({ id, t }: { id: string; t: T }) {
  return (
    <StaffForm t={t} label={t.admin.revoke} onSubmit={() => browserApi.DELETE("/api/v1/admin/sellers/invitations/{invitation_id}", { params: { path: { invitation_id: id } } })}>
      {null}
    </StaffForm>
  );
}

// -- listing takedowns (AD-03, D-032) ----------------------------------------------

export function TakeDownForm({ offerId, t }: { offerId: string; t: T }) {
  const a = t.admin;
  return (
    <StaffForm t={t} label={a.takeDown} onSubmit={(form) => browserApi.POST("/api/v1/admin/offers/{offer_id}/remove", { params: { path: { offer_id: offerId } }, body: { reason: text(form, "reason") } })}>
      <label className="block space-y-1"><span className="text-sm font-semibold">{a.takeDownReason}</span><input name="reason" required minLength={3} maxLength={1000} className={field} /></label>
    </StaffForm>
  );
}

export function LiftHoldForm({ offerId, t }: { offerId: string; t: T }) {
  const a = t.admin;
  return (
    <StaffForm t={t} label={a.liftHold} onSubmit={(form) => browserApi.POST("/api/v1/admin/offers/{offer_id}/restore", { params: { path: { offer_id: offerId } }, body: { reason: text(form, "reason") } })}>
      <label className="block space-y-1"><span className="text-sm font-semibold">{a.liftReason}</span><input name="reason" required minLength={3} maxLength={1000} className={field} /></label>
    </StaffForm>
  );
}

// -- reviews and reports (AD-12, AD-16; D-066, D-067) ----------------------------

export function ModerateReviewForm({ reviewId, status, t }: { reviewId: string; status: string; t: T }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.moderate}
      onSubmit={(form) =>
        browserApi.POST("/api/v1/admin/reviews/{review_id}/moderate", {
          params: { path: { review_id: reviewId } },
          body: { action: text(form, "action") as "publish" | "hide", reason: text(form, "reason") },
        })
      }
    >
      <div className="flex flex-wrap gap-4">
        <label className="flex min-h-12 items-center gap-2"><input type="radio" name="action" value="publish" defaultChecked={status !== "published"} className="h-5 w-5" />{a.publish}</label>
        <label className="flex min-h-12 items-center gap-2"><input type="radio" name="action" value="hide" defaultChecked={status === "published"} className="h-5 w-5" />{a.hide}</label>
      </div>
      <label className="block space-y-1"><span className="text-sm font-semibold">{a.moderationReason}</span><input name="reason" required minLength={3} maxLength={500} className={field} /></label>
    </StaffForm>
  );
}

export function ResolveReportForm({ reportId, t }: { reportId: string; t: T }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.resolve}
      onSubmit={(form) =>
        browserApi.POST("/api/v1/admin/reports/{report_id}/resolve", {
          params: { path: { report_id: reportId } },
          body: { outcome: text(form, "outcome") as "actioned" | "dismissed", note: text(form, "note"), all_on_target: form.get("all") === "on" },
        })
      }
    >
      <fieldset className="flex flex-wrap gap-4">
        <legend className="sr-only">{a.outcome}</legend>
        <label className="flex min-h-12 items-center gap-2"><input type="radio" name="outcome" value="actioned" className="h-5 w-5" />{a.actioned}</label>
        <label className="flex min-h-12 items-center gap-2"><input type="radio" name="outcome" value="dismissed" defaultChecked className="h-5 w-5" />{a.dismissed}</label>
      </fieldset>
      <label className="flex min-h-12 items-center gap-2"><input type="checkbox" name="all" defaultChecked className="h-5 w-5" />{a.allOnTarget}</label>
      <label className="block space-y-1"><span className="text-sm font-semibold">{a.resolutionNote}</span><input name="note" required minLength={3} maxLength={500} className={field} /></label>
    </StaffForm>
  );
}

// -- settings and staff accounts (AD-06, AD-13; D-065) ------------------------------

type SettingValue = boolean | number | string;

export function SettingForm({ settingKey, kind, value, t }: { settingKey: string; kind: string; value: SettingValue; t: T }) {
  const a = t.admin;
  const typed = (form: FormData): SettingValue => {
    const raw = text(form, "value");
    if (kind === "bool") return raw === "true";
    if (kind === "int") return Number(raw);
    return raw;
  };
  return (
    <StaffForm t={t} label={a.save} onSubmit={(form) => browserApi.PUT("/api/v1/admin/settings/{key}", { params: { path: { key: settingKey } }, body: { value: typed(form) } })}>
      {kind === "bool" ? (
        <select name="value" defaultValue={String(value)} aria-label={settingKey} className={field}>
          <option value="true">{a.on}</option>
          <option value="false">{a.off}</option>
        </select>
      ) : (
        <input name="value" aria-label={settingKey} type={kind === "int" ? "number" : "text"} step={kind === "int" ? 1 : undefined} required defaultValue={String(value)} className={field} />
      )}
    </StaffForm>
  );
}

const STAFF_ROLES = ["super_admin", "operations", "support", "catalogue", "finance"] as const;
type StaffRole = (typeof STAFF_ROLES)[number];

export function CreateStaffForm({ t, roleLabels }: { t: T; roleLabels: Record<StaffRole, string> }) {
  const a = t.admin;
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Shown once, from the API's answer; never stored or sent anywhere else.
  const [secret, setSecret] = useState<{ secret: string; uri: string } | null>(null);
  return (
    <div className="space-y-3">
      <form
        className="space-y-3"
        onSubmit={async (event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          setBusy(true);
          setError(null);
          setSecret(null);
          const { data, error: refused } = await browserApi.POST("/api/v1/admin/staff", {
            body: { phone: text(form, "phone"), name: text(form, "name"), role: text(form, "role") as StaffRole, password: String(form.get("password") ?? "") },
          });
          setBusy(false);
          if (refused || !data) setError(apiErrorText(t, errorCode(refused)));
          else {
            setSecret({ secret: data.totp_secret, uri: data.provisioning_uri });
            router.refresh();
          }
        }}
      >
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="space-y-1"><span className="block text-sm font-semibold">{a.staffName}</span><input name="name" required minLength={2} maxLength={100} className={field} /></label>
          <label className="space-y-1"><span className="block text-sm font-semibold">{a.staffPhone}</span><input name="phone" type="tel" required minLength={9} maxLength={24} className={field} /></label>
          <label className="space-y-1">
            <span className="block text-sm font-semibold">{a.staffRole}</span>
            <select name="role" defaultValue="support" className={field}>
              {STAFF_ROLES.map((role) => <option key={role} value={role}>{roleLabels[role]}</option>)}
            </select>
          </label>
          <label className="space-y-1"><span className="block text-sm font-semibold">{a.staffPassword}</span><input name="password" type="password" autoComplete="new-password" required minLength={12} maxLength={200} className={field} /></label>
        </div>
        <button type="submit" disabled={busy} className={button}>{a.createStaff}</button>
        {error ? <p role="alert" className="font-semibold text-clay">{error}</p> : null}
      </form>
      {secret ? (
        <section role="status" className="space-y-2 rounded-card border-2 border-ink bg-white p-4">
          <h3 className="font-bold">{a.secretTitle}</h3>
          <p className="text-sm">{a.secretLead}</p>
          <p><code className="break-all text-lg font-bold">{secret.secret}</code></p>
          <p className="text-sm">{a.secretUri} <code className="break-all">{secret.uri}</code></p>
        </section>
      ) : null}
    </div>
  );
}

export function StaffRoleForm({ staffId, role, t, roleLabels }: { staffId: string; role: string; t: T; roleLabels: Record<StaffRole, string> }) {
  const a = t.admin;
  return (
    <StaffForm t={t} label={a.changeRole} onSubmit={(form) => browserApi.POST("/api/v1/admin/staff/{staff_id}/role", { params: { path: { staff_id: staffId } }, body: { role: text(form, "role") as StaffRole } })}>
      <select name="role" defaultValue={role} aria-label={a.staffRole} className={field}>
        {STAFF_ROLES.map((r) => <option key={r} value={r}>{roleLabels[r]}</option>)}
      </select>
    </StaffForm>
  );
}

export function StaffActiveForm({ staffId, active, t }: { staffId: string; active: boolean; t: T }) {
  const a = t.admin;
  return (
    <StaffForm t={t} label={active ? a.switchOff : a.switchOn} onSubmit={(form) => browserApi.POST("/api/v1/admin/staff/{staff_id}/active", { params: { path: { staff_id: staffId } }, body: { active: !active, reason: text(form, "reason") } })}>
      <label className="block space-y-1"><span className="text-sm font-semibold">{a.switchReason}</span><input name="reason" required minLength={3} maxLength={500} className={field} /></label>
    </StaffForm>
  );
}

// -- exports (C.4, D.21; D-068) ---------------------------------------------------

export function ExportButton({ kind, firstDay, lastDay, t }: { kind: string; firstDay: string; lastDay: string; t: T }) {
  const a = t.admin;
  const [state, setState] = useState<{ busy: boolean; text: string | null; ok: boolean }>({ busy: false, text: null, ok: true });
  return (
    <div className="space-y-1">
      <button
        type="button"
        disabled={state.busy}
        className={button}
        onClick={async () => {
          setState({ busy: true, text: a.downloading, ok: true });
          const query = new URLSearchParams({ first_day: firstDay, last_day: lastDay });
          // A GET with the staff cookie; the API decides the period and the role.
          const response = await fetch(`/api/v1/admin/exports/${kind}?${query}`, { credentials: "same-origin" });
          if (!response.ok) {
            const body: unknown = await response.json().catch(() => null);
            setState({ busy: false, text: apiErrorText(t, errorCode(body)), ok: false });
            return;
          }
          const name = /filename="([^"]+)"/.exec(response.headers.get("content-disposition") ?? "")?.[1] ?? `markx-${kind}.csv`;
          const url = URL.createObjectURL(await response.blob());
          const link = document.createElement("a");
          link.href = url;
          link.download = name;
          link.click();
          URL.revokeObjectURL(url);
          setState({ busy: false, text: fill(a.downloaded, { file: name }), ok: true });
        }}
      >
        {a.download}
      </button>
      {state.text ? <p role={state.ok ? "status" : "alert"} className={state.ok ? "text-sm" : "text-sm font-semibold text-clay"}>{state.text}</p> : null}
    </div>
  );
}

// -- pictures (AD-03; D-062) -------------------------------------------------------

export function UploadPictureForm({ productId, t }: { productId: string; t: T }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.upload}
      onSubmit={async (form) => {
        const sent = await sendForm(`/api/v1/admin/catalog/products/${encodeURIComponent(productId)}/images`, form);
        return sent.ok ? {} : { error: sent.body ?? { error: { code: "unknown" } } };
      }}
    >
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="space-y-1"><span className="block text-sm font-semibold">{a.pictureFile}</span><input name="file" type="file" accept="image/jpeg,image/png,image/webp" required className={field} /></label>
        <label className="space-y-1"><span className="block text-sm font-semibold">{a.picturePosition}</span><input name="position" type="number" min={0} max={100} defaultValue={0} className={field} /></label>
      </div>
    </StaffForm>
  );
}

export function RemovePictureForm({ imageId, t }: { imageId: string; t: T }) {
  const a = t.admin;
  return (
    <StaffForm t={t} label={a.removePicture} onSubmit={(form) => browserApi.POST("/api/v1/admin/catalog/images/{image_id}/remove", { params: { path: { image_id: imageId } }, body: { reason: text(form, "reason") } })}>
      <label className="block space-y-1"><span className="text-sm font-semibold">{a.removeReason}</span><input name="reason" required minLength={3} maxLength={500} className={field} /></label>
    </StaffForm>
  );
}

// -- a shop's level and standing (AD-01, C.5, C.6) ---------------------------------

/** Staff change an approved shop's level, record its periodic re-check,
 * suspend or reinstate it, always with a written reason the audit log keeps.
 * The page offers each where the shop's state allows it; the API checks the
 * state, the checks behind a level and conflicts of interest again. */
export function SellerStanding({ sellerId, status, approved, level, t }: { sellerId: string; status: string; approved: boolean; level: number; t: T }) {
  const a = t.admin;
  const path = { params: { path: { seller_id: sellerId } } };
  const reason = (name: string, label: string) => (
    <label className="block space-y-1"><span className="text-sm font-semibold">{label}</span><input name={name} required minLength={3} maxLength={1000} className={field} /></label>
  );
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {approved && status !== "closed" ? (
        <section className="space-y-2">
          <h3 className="font-bold">{a.setLevelTitle}</h3>
          <StaffForm
            t={t}
            label={a.setLevel}
            onSubmit={(form) =>
              browserApi.POST("/api/v1/admin/sellers/{seller_id}/verification-level", {
                ...path,
                body: { level: Number(form.get("level")), reason: text(form, "reason"), shop_visited: form.get("visited") === "on" },
              })
            }
          >
            <fieldset className="space-y-1">
              <legend className="text-sm font-semibold">{a.newLevel}</legend>
              {[a.level0, a.level1, a.level2, a.level3].map((label, value) => (
                <label key={value} className="flex min-h-12 items-center gap-2"><input type="radio" name="level" value={value} defaultChecked={value === level} className="h-5 w-5" />{label}</label>
              ))}
            </fieldset>
            <label className="flex min-h-12 items-center gap-2"><input type="checkbox" name="visited" className="h-5 w-5" />{a.shopVisited}</label>
            {reason("reason", a.reason)}
          </StaffForm>
        </section>
      ) : null}
      {approved && status !== "closed" ? (
        <section className="space-y-2">
          <h3 className="font-bold">{a.recheckTitle}</h3>
          <StaffForm t={t} label={a.recheck} onSubmit={(form) => browserApi.POST("/api/v1/admin/sellers/{seller_id}/recheck", { ...path, body: { reason: text(form, "reason") } })}>
            {reason("reason", a.recheckNote)}
          </StaffForm>
        </section>
      ) : null}
      {status === "active" ? (
        <section className="space-y-2">
          <h3 className="font-bold">{a.suspendTitle}</h3>
          <p className="text-sm text-slate">{a.suspendHint}</p>
          <StaffForm t={t} label={a.suspend} onSubmit={(form) => browserApi.POST("/api/v1/admin/sellers/{seller_id}/suspend", { ...path, body: { reason: text(form, "reason") } })}>
            {reason("reason", a.reason)}
          </StaffForm>
        </section>
      ) : null}
      {status === "suspended" ? (
        <section className="space-y-2">
          <h3 className="font-bold">{a.reinstateTitle}</h3>
          <StaffForm t={t} label={a.reinstate} onSubmit={(form) => browserApi.POST("/api/v1/admin/sellers/{seller_id}/reinstate", { ...path, body: { reason: text(form, "reason") } })}>
            {reason("reason", a.reason)}
          </StaffForm>
        </section>
      ) : null}
    </div>
  );
}

// -- delivery zones, areas and fees (AD-05; change_delivery_and_risk) --------------

export function NewZoneForm({ t }: { t: T }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.zoneNew}
      onSubmit={(form) =>
        browserApi.POST("/api/v1/admin/delivery/zones", {
          body: { code: text(form, "code"), name_am: text(form, "name_am"), name_en: text(form, "name_en"), position: Number(text(form, "position") || 0) },
        })
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.zoneCode}</span><input name="code" required pattern="[a-z][a-z0-9_]{1,39}" className={field} /></label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.position}</span><input name="position" type="number" min={0} max={10000} defaultValue={0} className={field} /></label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.nameAm}</span><input name="name_am" lang="am" required maxLength={80} className={field} /></label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.nameEn}</span><input name="name_en" lang="en" required maxLength={80} className={field} /></label>
      </div>
    </StaffForm>
  );
}

export function ZoneForm({ zone, t }: { zone: { id: string; name_am: string; name_en: string; position: number; is_active: boolean }; t: T }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.zoneSave}
      onSubmit={(form) =>
        browserApi.PATCH("/api/v1/admin/delivery/zones/{zone_id}", {
          params: { path: { zone_id: zone.id } },
          body: { name_am: text(form, "name_am"), name_en: text(form, "name_en"), position: Number(text(form, "position") || 0), is_active: form.get("active") === "on" },
        })
      }
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.nameAm}</span><input name="name_am" lang="am" required maxLength={80} defaultValue={zone.name_am} className={field} /></label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.nameEn}</span><input name="name_en" lang="en" required maxLength={80} defaultValue={zone.name_en} className={field} /></label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.position}</span><input name="position" type="number" min={0} max={10000} defaultValue={zone.position} className={field} /></label>
      </div>
      <label className="flex min-h-12 items-center gap-3"><input type="checkbox" name="active" defaultChecked={zone.is_active} className="h-5 w-5" />{a.zoneActive}</label>
    </StaffForm>
  );
}

export function NewAreaForm({ zoneId, t }: { zoneId: string; t: T }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.areaAdd}
      onSubmit={(form) =>
        browserApi.POST("/api/v1/admin/delivery/zones/{zone_id}/areas", {
          params: { path: { zone_id: zoneId } },
          body: { name_am: text(form, "name_am"), name_en: text(form, "name_en"), position: Number(text(form, "position") || 0) },
        })
      }
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.nameAm}</span><input name="name_am" lang="am" required maxLength={80} className={field} /></label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.nameEn}</span><input name="name_en" lang="en" required maxLength={80} className={field} /></label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.position}</span><input name="position" type="number" min={0} max={10000} defaultValue={0} className={field} /></label>
      </div>
    </StaffForm>
  );
}

export function AreaSwitch({ areaId, active, t }: { areaId: string; active: boolean; t: T }) {
  return (
    <StaffForm
      t={t}
      label={active ? t.admin.areaOff : t.admin.areaOn}
      onSubmit={() => browserApi.PATCH("/api/v1/admin/delivery/areas/{area_id}", { params: { path: { area_id: areaId } }, body: { is_active: !active } })}
    >
      {null}
    </StaffForm>
  );
}

export function RateForm({ zoneId, method, rate, t }: { zoneId: string; method: "seller_rider" | "partner_courier"; rate: { fee_santim: number; promised_hours: number; is_active: boolean } | undefined; t: T }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.rateSave}
      onSubmit={(form) =>
        browserApi.PUT("/api/v1/admin/delivery/zones/{zone_id}/rates", {
          params: { path: { zone_id: zoneId } },
          body: { method, fee_santim: Math.round(Number(text(form, "fee")) * 100), promised_hours: Number(text(form, "hours")), is_active: form.get("active") === "on" },
        })
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.rateFee}</span><input name="fee" type="number" required min={0} step="0.01" inputMode="decimal" defaultValue={rate ? rate.fee_santim / 100 : ""} className={field} /></label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.rateHours}</span><input name="hours" type="number" required min={1} max={720} inputMode="numeric" defaultValue={rate?.promised_hours ?? ""} className={field} /></label>
      </div>
      <label className="flex min-h-12 items-center gap-3"><input type="checkbox" name="active" defaultChecked={rate ? rate.is_active : true} className="h-5 w-5" />{a.rateActive}</label>
    </StaffForm>
  );
}

// -- catalogue setup (AD-02; curate_catalogue) -------------------------------------

const slugPattern = "[a-z0-9]+(-[a-z0-9]+)*";

function TwoNames({ t, am = "name_am", en = "name_en", labels }: { t: T; am?: string; en?: string; labels?: [string, string] }) {
  const a = t.admin;
  return (
    <>
      <label className="block space-y-1"><span className="text-sm font-semibold">{labels?.[0] ?? a.nameAm}</span><input name={am} lang="am" required maxLength={160} className={field} /></label>
      <label className="block space-y-1"><span className="text-sm font-semibold">{labels?.[1] ?? a.nameEn}</span><input name={en} lang="en" required maxLength={160} className={field} /></label>
    </>
  );
}

export function NewCategoryForm({ parents, t }: { parents: { id: string; label: string }[]; t: T }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.categoryNew}
      onSubmit={(form) =>
        browserApi.POST("/api/v1/admin/catalog/categories", {
          body: {
            slug: text(form, "slug"), name_am: text(form, "name_am"), name_en: text(form, "name_en"),
            parent_id: text(form, "parent_id") || null, position: Number(text(form, "position") || 0),
            default_commission_bps: Number(text(form, "commission") || 0),
          },
        })
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-1">
          <span className="text-sm font-semibold">{a.categoryParent}</span>
          <select name="parent_id" defaultValue="" className={field}>
            <option value="">{a.categoryTop}</option>
            {parents.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.categorySlug}</span><input name="slug" required minLength={2} maxLength={80} pattern={slugPattern} className={field} /></label>
        <TwoNames t={t} />
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.position}</span><input name="position" type="number" min={0} max={10000} defaultValue={0} className={field} /></label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.categoryCommission}</span><input name="commission" type="number" min={0} max={10000} defaultValue={0} className={field} /></label>
      </div>
    </StaffForm>
  );
}

export function CategoryForm({ category, t }: { category: { id: string; position: number; is_active: boolean }; t: T }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.categorySave}
      onSubmit={(form) =>
        browserApi.PATCH("/api/v1/admin/catalog/categories/{category_id}", {
          params: { path: { category_id: category.id } },
          body: { position: Number(text(form, "position") || 0), is_active: form.get("active") === "on", ...(text(form, "name_am") ? { name_am: text(form, "name_am") } : {}), ...(text(form, "name_en") ? { name_en: text(form, "name_en") } : {}) },
        })
      }
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.nameAm}</span><input name="name_am" lang="am" maxLength={160} className={field} /></label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.nameEn}</span><input name="name_en" lang="en" maxLength={160} className={field} /></label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.position}</span><input name="position" type="number" min={0} max={10000} defaultValue={category.position} className={field} /></label>
      </div>
      <label className="flex min-h-12 items-center gap-3"><input type="checkbox" name="active" defaultChecked={category.is_active} className="h-5 w-5" />{a.categoryActive}</label>
    </StaffForm>
  );
}

const OPTION_ROWS = 4;

export function NewAttributeForm({ t, types }: { t: T; types: Messages["labels"]["attributeType"] }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.attributeNew}
      onSubmit={(form) => {
        const options = Array.from({ length: OPTION_ROWS }, (_, i) => ({ code: text(form, `option_${i}_code`), label_am: text(form, `option_${i}_am`), label_en: text(form, `option_${i}_en`) })).filter((o) => o.code);
        return browserApi.POST("/api/v1/admin/catalog/attributes", {
          body: {
            code: text(form, "code"), data_type: text(form, "data_type") as "text" | "number" | "option",
            name_am: text(form, "name_am"), name_en: text(form, "name_en"), unit: text(form, "unit") || null, options,
          },
        });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.attributeCode}</span><input name="code" required pattern="[a-z][a-z0-9_]{0,39}" className={field} /></label>
        <label className="block space-y-1">
          <span className="text-sm font-semibold">{a.attributeType}</span>
          <select name="data_type" className={field}>
            {(["option", "number", "text"] as const).map((type) => <option key={type} value={type}>{types[type]}</option>)}
          </select>
        </label>
        <TwoNames t={t} />
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.attributeUnit}</span><input name="unit" maxLength={20} className={field} /></label>
      </div>
      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold">{a.optionNew}</legend>
        {Array.from({ length: OPTION_ROWS }, (_, i) => (
          <div key={i} className="grid gap-2 sm:grid-cols-3">
            <input name={`option_${i}_code`} aria-label={`${a.optionCode} ${i + 1}`} placeholder={a.optionCode} pattern="[a-z0-9][a-z0-9_]{0,39}" className={field} />
            <input name={`option_${i}_am`} lang="am" aria-label={`${a.labelAm} ${i + 1}`} placeholder={a.labelAm} maxLength={160} className={field} />
            <input name={`option_${i}_en`} lang="en" aria-label={`${a.labelEn} ${i + 1}`} placeholder={a.labelEn} maxLength={160} className={field} />
          </div>
        ))}
      </fieldset>
    </StaffForm>
  );
}

export function NewOptionForm({ attributeId, t }: { attributeId: string; t: T }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.optionNew}
      onSubmit={(form) =>
        browserApi.POST("/api/v1/admin/catalog/attributes/{attribute_id}/options", {
          params: { path: { attribute_id: attributeId } },
          body: { code: text(form, "code"), label_am: text(form, "label_am"), label_en: text(form, "label_en") },
        })
      }
    >
      <div className="grid gap-2 sm:grid-cols-3">
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.optionCode}</span><input name="code" required pattern="[a-z0-9][a-z0-9_]{0,39}" className={field} /></label>
        <TwoNames t={t} am="label_am" en="label_en" labels={[a.labelAm, a.labelEn]} />
      </div>
    </StaffForm>
  );
}

export function CategoryAttributeForm({ categories, attributes, t }: { categories: { id: string; label: string }[]; attributes: { id: string; label: string }[]; t: T }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.linkSave}
      onSubmit={(form) =>
        browserApi.PUT("/api/v1/admin/catalog/categories/{category_id}/attributes/{attribute_id}", {
          params: { path: { category_id: text(form, "category_id"), attribute_id: text(form, "attribute_id") } },
          body: {
            is_required: form.get("required") === "on", is_filterable: form.get("filterable") === "on",
            is_variant_defining: form.get("variant") === "on", position: Number(text(form, "position") || 0),
          },
        })
      }
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.linkCategory}</span><select name="category_id" required className={field}>{categories.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}</select></label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.linkAttribute}</span><select name="attribute_id" required className={field}>{attributes.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</select></label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.position}</span><input name="position" type="number" min={0} max={10000} defaultValue={0} className={field} /></label>
      </div>
      <label className="flex min-h-12 items-center gap-3"><input type="checkbox" name="required" className="h-5 w-5" />{a.linkRequired}</label>
      <label className="flex min-h-12 items-center gap-3"><input type="checkbox" name="filterable" className="h-5 w-5" />{a.linkFilterable}</label>
      <label className="flex min-h-12 items-center gap-3"><input type="checkbox" name="variant" className="h-5 w-5" />{a.linkVariant}</label>
    </StaffForm>
  );
}

export function NewBrandForm({ t }: { t: T }) {
  const a = t.admin;
  return (
    <StaffForm t={t} label={a.brandNew} onSubmit={(form) => browserApi.POST("/api/v1/admin/catalog/brands", { body: { name: text(form, "name") } })}>
      <label className="block space-y-1"><span className="text-sm font-semibold">{a.brandName}</span><input name="name" required maxLength={160} className={field} /></label>
    </StaffForm>
  );
}

export function RestrictedTermForm({ t }: { t: T }) {
  const a = t.admin;
  return (
    <StaffForm t={t} label={a.termNew} onSubmit={(form) => browserApi.POST("/api/v1/admin/catalog/restricted-terms", { body: { term: text(form, "term"), reason: text(form, "reason") } })}>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.restrictedTerm}</span><input name="term" required maxLength={160} className={field} /></label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.termReason}</span><input name="reason" maxLength={300} className={field} /></label>
      </div>
    </StaffForm>
  );
}

export function RemoveTermButton({ termId, t }: { termId: string; t: T }) {
  return (
    <StaffForm t={t} label={t.admin.termRemove} onSubmit={() => browserApi.DELETE("/api/v1/admin/catalog/restricted-terms/{term_id}", { params: { path: { term_id: termId } } })}>
      {null}
    </StaffForm>
  );
}

// -- one product (AD-02) -----------------------------------------------------------

export function ProductTextForm({ product, t }: { product: { id: string; name_am: string; name_en: string; description_am: string; description_en: string }; t: T }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.productTextSave}
      onSubmit={(form) =>
        browserApi.PUT("/api/v1/admin/catalog/products/{product_id}/text", {
          params: { path: { product_id: product.id } },
          body: { name_am: text(form, "name_am"), name_en: text(form, "name_en"), description_am: text(form, "description_am"), description_en: text(form, "description_en") },
        })
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.nameAm}</span><input name="name_am" lang="am" required maxLength={160} defaultValue={product.name_am} className={field} /></label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{a.nameEn}</span><input name="name_en" lang="en" required maxLength={160} defaultValue={product.name_en} className={field} /></label>
      </div>
      <label className="block space-y-1"><span className="text-sm font-semibold">{a.descriptionAm}</span><textarea name="description_am" lang="am" maxLength={5000} rows={3} defaultValue={product.description_am} className="w-full rounded-card border border-line bg-white p-3" /></label>
      <label className="block space-y-1"><span className="text-sm font-semibold">{a.descriptionEn}</span><textarea name="description_en" lang="en" maxLength={5000} rows={3} defaultValue={product.description_en} className="w-full rounded-card border border-line bg-white p-3" /></label>
    </StaffForm>
  );
}

export function AddVariantForm({ productId, attributes, t }: { productId: string; attributes: { code: string; name: string; is_required: boolean; options: { code: string; label: string }[] }[]; t: T }) {
  const a = t.admin;
  return (
    <StaffForm
      t={t}
      label={a.variantAdd}
      onSubmit={(form) => {
        const attribute_values: Record<string, string> = {};
        for (const attribute of attributes) if (text(form, attribute.code)) attribute_values[attribute.code] = text(form, attribute.code);
        return browserApi.POST("/api/v1/admin/catalog/products/{product_id}/variants", {
          params: { path: { product_id: productId } },
          body: { attribute_values, model_code: text(form, "model_code") || null },
        });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        {attributes.map((attribute) => (
          <label key={attribute.code} className="block space-y-1">
            <span className="text-sm font-semibold">{attribute.name}</span>
            {/* Only a required detail must be chosen: every version sets the same details, so one the others leave empty stays empty (variants_inconsistent). */}
            <select name={attribute.code} required={attribute.is_required} defaultValue="" className={field}>
              <option value="">—</option>
              {attribute.options.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
            </select>
          </label>
        ))}
        <label className="block space-y-1"><span className="text-sm font-semibold">{t.admin.modelCode}</span><input name="model_code" maxLength={80} className={field} /></label>
      </div>
    </StaffForm>
  );
}

export function AliasForm({ productId, t }: { productId: string; t: T }) {
  const a = t.admin;
  return (
    <StaffForm t={t} label={a.aliasAdd} onSubmit={(form) => browserApi.POST("/api/v1/admin/catalog/products/{product_id}/aliases", { params: { path: { product_id: productId } }, body: { alias: text(form, "alias") } })}>
      <label className="block space-y-1"><span className="text-sm font-semibold">{a.alias}</span><input name="alias" required maxLength={160} className={field} /></label>
    </StaffForm>
  );
}

export function RemoveAliasButton({ productId, aliasId, t }: { productId: string; aliasId: string; t: T }) {
  return (
    <StaffForm t={t} label={t.admin.aliasRemove} onSubmit={() => browserApi.DELETE("/api/v1/admin/catalog/products/{product_id}/aliases/{alias_id}", { params: { path: { product_id: productId, alias_id: aliasId } } })}>
      {null}
    </StaffForm>
  );
}
