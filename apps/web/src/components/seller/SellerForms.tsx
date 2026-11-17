"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useState } from "react";

import { browserApi, errorCode, sendForm } from "@/lib/api/browser";
import type { components } from "@/lib/api/schema";
import { apiErrorText, type Messages } from "@/lib/i18n";

// The seller dashboard's forms (blueprint I.5, C.3). Each sends what the
// member typed and shows the API's answer in words; the API checks the role,
// the shop's state and every value again. Nothing here decides a rule.

type T = Pick<Messages, "seller" | "apiErrors">;
type Result = { error?: unknown };
type Schemas = components["schemas"];

const field = "min-h-12 w-full rounded-card border border-line bg-white px-3";
const area = "w-full rounded-card border border-line bg-white p-3";
const button = "min-h-12 rounded-card bg-ink px-5 font-bold text-paper disabled:opacity-60";

const text = (form: FormData, name: string) => String(form.get(name) ?? "").trim();
const optional = (form: FormData, name: string) => text(form, name) || null;

/** One form: runs the call, shows the refusal in words, refreshes on success. */
function SellerForm({ t, onSubmit, children, label, done, reset = false }: {
  t: T;
  onSubmit: (form: FormData) => Promise<Result>;
  children: ReactNode;
  label: string;
  done?: string;
  reset?: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <form
      className="space-y-3"
      onSubmit={async (event) => {
        event.preventDefault();
        const element = event.currentTarget;
        setBusy(true);
        setMessage(null);
        const { error } = await onSubmit(new FormData(element));
        setBusy(false);
        if (error) {
          setMessage({ ok: false, text: apiErrorText(t, errorCode(error)) });
          return;
        }
        if (reset) element.reset();
        setMessage({ ok: true, text: done ?? t.seller.saved });
        router.refresh();
      }}
    >
      {children}
      <button type="submit" disabled={busy} className={button}>{label}</button>
      {message ? <p role={message.ok ? "status" : "alert"} className={message.ok ? "font-semibold" : "font-semibold text-clay"}>{message.text}</p> : null}
    </form>
  );
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block space-y-1">
      <span className="block text-sm font-semibold">{label}</span>
      {children}
      {hint ? <span className="block text-sm text-slate">{hint}</span> : null}
    </label>
  );
}

// -- applying ------------------------------------------------------------------------

export function ApplicationForm({ lang, individualEnabled, t, kinds }: { lang: string; individualEnabled: boolean; t: T; kinds: Messages["labels"]["sellerKind"] }) {
  const router = useRouter();
  const s = t.seller;
  return (
    <SellerForm
      t={t}
      label={s.applySend}
      onSubmit={async (form) => {
        const { data, error } = await browserApi.POST("/api/v1/seller/applications", {
          body: {
            kind: (text(form, "kind") || "business") as Schemas["ApplicationIn"]["kind"],
            legal_name: text(form, "legal_name"),
            trade_name: text(form, "trade_name"),
            tin: optional(form, "tin"),
            licence_number: optional(form, "licence_number"),
            contact_phone: text(form, "contact_phone"),
            shop_address: text(form, "shop_address"),
            store_slug: optional(form, "store_slug"),
          },
        });
        if (data) router.push(`/${lang}/seller/${data.id}`);
        return { error };
      }}
    >
      {individualEnabled ? (
        <fieldset className="space-y-2">
          <legend className="text-sm font-semibold">{s.kind}</legend>
          {(["business", "individual"] as const).map((kind) => (
            <label key={kind} className="flex min-h-12 items-center gap-3">
              <input type="radio" name="kind" value={kind} defaultChecked={kind === "business"} className="h-5 w-5" />
              {kinds[kind]}
            </label>
          ))}
        </fieldset>
      ) : null}
      <Field label={s.legalName}><input name="legal_name" required maxLength={200} className={field} /></Field>
      <Field label={s.tradeName}><input name="trade_name" required maxLength={200} className={field} /></Field>
      <Field label={s.tin}><input name="tin" inputMode="numeric" minLength={10} maxLength={20} className={field} /></Field>
      <Field label={s.licence}><input name="licence_number" maxLength={60} className={field} /></Field>
      <Field label={s.contactPhone}><input name="contact_phone" type="tel" required minLength={9} maxLength={24} className={field} /></Field>
      <Field label={s.shopAddress}><textarea name="shop_address" required minLength={3} maxLength={500} rows={2} className={area} /></Field>
      <Field label={s.storeSlug} hint={s.storeSlugHint}><input name="store_slug" minLength={3} maxLength={60} pattern="[a-z0-9]+(-[a-z0-9]+)*" className={field} /></Field>
    </SellerForm>
  );
}

export function SubmitApplicationForm({ sellerId, t }: { sellerId: string; t: T }) {
  return (
    <SellerForm t={t} label={t.seller.submit} done={t.seller.submitted} onSubmit={() => browserApi.POST("/api/v1/seller/{seller_id}/submit", { params: { path: { seller_id: sellerId } } })}>
      {null}
    </SellerForm>
  );
}

// -- documents -----------------------------------------------------------------------

export function DocumentUploadForm({ sellerId, t, types }: { sellerId: string; t: T; types: Messages["labels"]["docType"] }) {
  const s = t.seller;
  return (
    <SellerForm
      t={t}
      label={s.docUpload}
      done={s.docUploaded}
      reset
      onSubmit={async (form) => {
        if (!text(form, "expires_on")) form.delete("expires_on");
        const { ok, body } = await sendForm(`/api/v1/seller/${sellerId}/documents`, form);
        return ok ? {} : { error: body };
      }}
    >
      <Field label={s.docType}>
        <select name="doc_type" className={field}>
          {(Object.keys(types) as (keyof typeof types)[]).map((type) => <option key={type} value={type}>{types[type]}</option>)}
        </select>
      </Field>
      <Field label={s.docFile}><input name="file" type="file" accept="image/jpeg,image/png,image/webp" required className="block w-full max-w-full text-sm file:mr-3 file:min-h-12 file:rounded-card file:border file:border-ink file:bg-white file:px-4 file:font-semibold" /></Field>
      <Field label={s.docExpires}><input name="expires_on" type="date" className={field} /></Field>
    </SellerForm>
  );
}

/** Opens one of the shop's own documents behind a short-lived link the API
 * signs for this member (the link alone opens nothing). */
export function OpenDocumentButton({ sellerId, documentId, t }: { sellerId: string; documentId: string; t: T }) {
  const [problem, setProblem] = useState<string | null>(null);
  return (
    <span className="inline-flex flex-col">
      <button
        type="button"
        className="min-h-12 rounded-card border border-ink px-4 text-sm font-semibold"
        onClick={async () => {
          setProblem(null);
          const { data, error } = await browserApi.POST("/api/v1/seller/{seller_id}/documents/{document_id}/link", {
            params: { path: { seller_id: sellerId, document_id: documentId } },
          });
          if (data) window.open(data.url, "_blank", "noopener");
          else setProblem(apiErrorText(t, errorCode(error)));
        }}
      >
        {t.seller.docOpen}
      </button>
      {problem ? <span role="alert" className="text-sm font-semibold text-clay">{problem}</span> : null}
    </span>
  );
}

// -- the store, the legal details, the payout account ---------------------------------

export function StoreForm({ sellerId, store, t }: { sellerId: string; store: Schemas["StoreOut"]; t: T }) {
  const s = t.seller;
  return (
    <SellerForm
      t={t}
      label={s.save}
      onSubmit={(form) =>
        browserApi.PATCH("/api/v1/seller/{seller_id}/store", {
          params: { path: { seller_id: sellerId } },
          body: {
            name: text(form, "name"),
            ...(text(form, "slug") !== store.slug ? { slug: text(form, "slug") } : {}),
            description: text(form, "description"),
            working_hours: text(form, "working_hours"),
            areas_served: text(form, "areas_served").split("\n").map((line) => line.trim()).filter(Boolean),
            return_policy: text(form, "return_policy"),
            telegram_channel: text(form, "telegram_channel"),
          },
        })
      }
    >
      <Field label={s.storeName}><input name="name" required maxLength={200} defaultValue={store.name} className={field} /></Field>
      <Field label={s.storeLink} hint={s.storeSlugHint}><input name="slug" required minLength={3} maxLength={60} pattern="[a-z0-9]+(-[a-z0-9]+)*" defaultValue={store.slug} className={field} /></Field>
      <Field label={s.storeDescription}><textarea name="description" maxLength={5000} rows={4} defaultValue={store.description} className={area} /></Field>
      <Field label={s.storeHours}><input name="working_hours" maxLength={300} defaultValue={store.working_hours} className={field} /></Field>
      <Field label={s.storeAreas}><textarea name="areas_served" rows={3} defaultValue={store.areas_served.join("\n")} className={area} /></Field>
      <Field label={s.storeReturns}><textarea name="return_policy" maxLength={5000} rows={3} defaultValue={store.return_policy} className={area} /></Field>
      <Field label={s.storeTelegram}><input name="telegram_channel" pattern="@[A-Za-z0-9_]{5,32}" defaultValue={store.telegram_channel ?? ""} className={field} /></Field>
    </SellerForm>
  );
}

export function LegalForm({ sellerId, legal, t }: { sellerId: string; legal: Schemas["LegalOut"]; t: T }) {
  const s = t.seller;
  return (
    <SellerForm
      t={t}
      label={s.save}
      onSubmit={(form) =>
        browserApi.PATCH("/api/v1/seller/{seller_id}/legal", {
          params: { path: { seller_id: sellerId } },
          body: {
            legal_name: text(form, "legal_name"),
            trade_name: text(form, "trade_name"),
            tin: optional(form, "tin"),
            licence_number: optional(form, "licence_number"),
            contact_phone: text(form, "contact_phone"),
            shop_address: text(form, "shop_address"),
          },
        })
      }
    >
      <Field label={s.legalName}><input name="legal_name" required maxLength={200} defaultValue={legal.legal_name} className={field} /></Field>
      <Field label={s.tradeName}><input name="trade_name" required maxLength={200} defaultValue={legal.trade_name} className={field} /></Field>
      <Field label={s.tin}><input name="tin" inputMode="numeric" minLength={10} maxLength={20} defaultValue={legal.tin ?? ""} className={field} /></Field>
      <Field label={s.licence}><input name="licence_number" maxLength={60} defaultValue={legal.licence_number ?? ""} className={field} /></Field>
      <Field label={s.contactPhone}><input name="contact_phone" type="tel" required minLength={9} maxLength={24} defaultValue={legal.contact_phone} className={field} /></Field>
      <Field label={s.shopAddress}><textarea name="shop_address" required minLength={3} maxLength={500} rows={2} defaultValue={legal.shop_address} className={area} /></Field>
    </SellerForm>
  );
}

export function PayoutForm({ sellerId, t, kinds }: { sellerId: string; t: T; kinds: Messages["labels"]["payoutKind"] }) {
  const s = t.seller;
  return (
    <SellerForm
      t={t}
      label={s.payoutSave}
      reset
      onSubmit={(form) =>
        browserApi.PUT("/api/v1/seller/{seller_id}/payout-account", {
          params: { path: { seller_id: sellerId } },
          body: {
            kind: text(form, "kind") as Schemas["PayoutAccountIn"]["kind"],
            provider_name: text(form, "provider_name"),
            account_name: text(form, "account_name"),
            account_number: text(form, "account_number"),
          },
        })
      }
    >
      <Field label={s.payoutKind}>
        <select name="kind" className={field}>
          {(["bank", "wallet"] as const).map((kind) => <option key={kind} value={kind}>{kinds[kind]}</option>)}
        </select>
      </Field>
      <Field label={s.payoutProvider}><input name="provider_name" required maxLength={200} className={field} /></Field>
      <Field label={s.payoutAccountName}><input name="account_name" required maxLength={200} className={field} /></Field>
      <Field label={s.payoutAccountNumber}><input name="account_number" required inputMode="numeric" autoComplete="off" minLength={6} maxLength={40} className={field} /></Field>
    </SellerForm>
  );
}

// -- the team ------------------------------------------------------------------------

export function AddMemberForm({ sellerId, t, roles }: { sellerId: string; t: T; roles: Messages["labels"]["sellerRole"] }) {
  const s = t.seller;
  return (
    <SellerForm
      t={t}
      label={s.memberAdd}
      reset
      onSubmit={(form) =>
        browserApi.POST("/api/v1/seller/{seller_id}/members", {
          params: { path: { seller_id: sellerId } },
          body: { phone: text(form, "phone"), role: text(form, "role") as Schemas["MemberIn"]["role"] },
        })
      }
    >
      <Field label={s.memberPhone}><input name="phone" type="tel" required minLength={9} maxLength={24} className={field} /></Field>
      <Field label={s.memberRole}>
        <select name="role" className={field}>
          {(["manager", "catalogue", "orders", "finance"] as const).map((role) => <option key={role} value={role}>{roles[role]}</option>)}
        </select>
      </Field>
    </SellerForm>
  );
}

export function RemoveMemberButton({ sellerId, memberId, t }: { sellerId: string; memberId: string; t: T }) {
  return (
    <SellerForm
      t={t}
      label={t.seller.memberRemove}
      onSubmit={() => browserApi.DELETE("/api/v1/seller/{seller_id}/members/{member_id}", { params: { path: { seller_id: sellerId, member_id: memberId } } })}
    >
      {null}
    </SellerForm>
  );
}

// -- a new offer ---------------------------------------------------------------------

export function AddOfferForm({ lang, sellerId, variants, defaultLowStock, t, conditions }: {
  lang: string;
  sellerId: string;
  variants: { id: string; label: string }[];
  /** The API's own default, read from its description by the page. */
  defaultLowStock: number | undefined;
  t: T;
  conditions: Messages["condition"];
}) {
  const router = useRouter();
  const s = t.seller;
  return (
    <SellerForm
      t={t}
      label={s.addOfferSend}
      onSubmit={async (form) => {
        const { data, error } = await browserApi.POST("/api/v1/seller/{seller_id}/offers", {
          params: { path: { seller_id: sellerId }, query: { lang: lang as "am" | "en" } },
          body: {
            variant_id: text(form, "variant_id"),
            condition: text(form, "condition") as Schemas["OfferIn"]["condition"],
            price_santim: Math.round(Number(text(form, "price")) * 100),
            quantity: Number(text(form, "quantity")),
            warranty_months: Number(text(form, "warranty_months") || 0),
            warranty_note: optional(form, "warranty_note"),
            delivers_by_seller_rider: form.get("rider") === "on",
            delivers_by_partner_courier: form.get("courier") === "on",
            offers_shop_collection: form.get("collection") === "on",
            low_stock_threshold: Number(text(form, "low_stock_threshold")),
          },
        });
        if (data) router.push(`/${lang}/seller/${sellerId}/offers`);
        return { error };
      }}
    >
      <Field label={s.addOfferVariant}>
        <select name="variant_id" className={field}>
          {variants.map((variant) => <option key={variant.id} value={variant.id}>{variant.label}</option>)}
        </select>
      </Field>
      <Field label={s.addOfferCondition}>
        <select name="condition" className={field}>
          {(["new", "open_box", "refurbished", "used"] as const).map((condition) => <option key={condition} value={condition}>{conditions[condition]}</option>)}
        </select>
      </Field>
      <Field label={s.addOfferPrice}><input name="price" type="number" required min={1} step="0.01" inputMode="decimal" className={field} /></Field>
      <Field label={s.addOfferQuantity}><input name="quantity" type="number" required min={0} step={1} inputMode="numeric" className={field} /></Field>
      <Field label={s.addOfferWarranty}><input name="warranty_months" type="number" min={0} max={120} step={1} defaultValue={0} inputMode="numeric" className={field} /></Field>
      <Field label={s.addOfferWarrantyNote}><input name="warranty_note" maxLength={300} className={field} /></Field>
      <fieldset className="space-y-1">
        <legend className="text-sm font-semibold">{s.addOfferDelivery}</legend>
        <label className="flex min-h-12 items-center gap-3"><input type="checkbox" name="collection" defaultChecked className="h-5 w-5" />{s.addOfferCollection}</label>
        <label className="flex min-h-12 items-center gap-3"><input type="checkbox" name="rider" className="h-5 w-5" />{s.addOfferRider}</label>
        <label className="flex min-h-12 items-center gap-3"><input type="checkbox" name="courier" className="h-5 w-5" />{s.addOfferCourier}</label>
      </fieldset>
      <Field label={s.addOfferLowStock}><input name="low_stock_threshold" type="number" required min={0} max={10000} step={1} defaultValue={defaultLowStock} inputMode="numeric" className={field} /></Field>
    </SellerForm>
  );
}
