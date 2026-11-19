"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { browserApi, errorCode } from "@/lib/api/browser";
import type { components } from "@/lib/api/schema";
import { apiErrorText, fill, type Messages } from "@/lib/i18n";

type Schemas = components["schemas"];
type Attribute = Schemas["AttributeOut"];

type Props = {
  lang: string;
  /** Staff create a product (draft or published); a shop proposes one. */
  mode: { kind: "staff" } | { kind: "seller"; sellerId: string };
  category: { id: string; attributes: Attribute[] };
  brands: Schemas["BrandOut"][];
  t: Pick<Messages, "catalogue" | "apiErrors">;
};

const field = "min-h-12 w-full rounded-card border border-line bg-white px-3";
const MAX_LINES = 12;

function label(t: Props["t"], attribute: Attribute): string {
  const name = attribute.unit ? fill(t.catalogue.withUnit, { name: attribute.name, unit: attribute.unit }) : attribute.name;
  return attribute.is_required ? fill(t.catalogue.required, { name }) : name;
}

/** One value input for a detail of the category: a list, a number or a text. */
function ValueInput({ name, attribute, t }: { name: string; attribute: Attribute; t: Props["t"] }) {
  if (attribute.data_type === "option") {
    return (
      <select name={name} defaultValue="" className={field}>
        <option value="">{t.catalogue.chooseOption}</option>
        {attribute.options.map((option) => <option key={option.code} value={option.code}>{option.label}</option>)}
      </select>
    );
  }
  if (attribute.data_type === "number") return <input name={name} type="number" step="any" inputMode="decimal" className={field} />;
  return <input name={name} maxLength={200} className={field} />;
}

// A product for the catalogue (blueprint D.5, D.6): its names in both
// languages, the category's details, and the versions buyers choose from,
// which the category's version-defining details tell apart. The API checks
// every value, every required detail and every duplicate; staff may publish
// at once, and a shop's product always waits for staff (S-05).
export function ProductForm({ lang, mode, category, brands, t }: Props) {
  const router = useRouter();
  const c = t.catalogue;
  const [lines, setLines] = useState(1);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const details = category.attributes.filter((a) => !a.is_variant_defining);
  const defining = category.attributes.filter((a) => a.is_variant_defining);

  return (
    <form
      className="space-y-4"
      onSubmit={async (event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const value = (name: string) => String(form.get(name) ?? "").trim();
        const specs: Record<string, string | number> = {};
        for (const attribute of details) {
          const raw = value(`spec_${attribute.code}`);
          if (raw) specs[attribute.code] = attribute.data_type === "number" ? Number(raw) : raw;
        }
        const variants: Schemas["VariantIn"][] = [];
        for (let line = 0; line < lines; line++) {
          const attribute_values: Record<string, string> = {};
          for (const attribute of defining) {
            const raw = value(`variant_${line}_${attribute.code}`);
            if (raw) attribute_values[attribute.code] = raw;
          }
          const model_code = value(`variant_${line}_model`) || null;
          if (Object.keys(attribute_values).length || model_code) variants.push({ attribute_values, model_code });
        }
        const body: Schemas["ProductIn"] = {
          category_id: category.id,
          name_am: value("name_am"),
          name_en: value("name_en"),
          description_am: value("description_am"),
          description_en: value("description_en"),
          brand_id: value("brand_id") || null,
          model: value("model") || null,
          specs,
          variants,
          status: mode.kind === "staff" && form.get("publish") === "on" ? "approved" : "draft",
        };
        setBusy(true);
        setMessage(null);
        if (mode.kind === "staff") {
          const { data, error } = await browserApi.POST("/api/v1/admin/catalog/products", { body });
          setBusy(false);
          if (error || !data) return setMessage({ ok: false, text: apiErrorText(t, errorCode(error)) });
          router.push(`/${lang}/admin/products/${data.id}`);
          return;
        }
        const { error } = await browserApi.POST("/api/v1/seller/{seller_id}/product-proposals", { params: { path: { seller_id: mode.sellerId } }, body });
        setBusy(false);
        if (error) return setMessage({ ok: false, text: apiErrorText(t, errorCode(error)) });
        setMessage({ ok: true, text: c.proposed });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-1"><span className="text-sm font-semibold">{c.nameAm}</span><input name="name_am" lang="am" required maxLength={160} className={field} /></label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{c.nameEn}</span><input name="name_en" lang="en" required maxLength={160} className={field} /></label>
        <label className="block space-y-1">
          <span className="text-sm font-semibold">{c.brand}</span>
          <select name="brand_id" defaultValue="" className={field}>
            <option value="">{c.noBrand}</option>
            {brands.map((brand) => <option key={brand.id} value={brand.id}>{brand.name}</option>)}
          </select>
        </label>
        <label className="block space-y-1"><span className="text-sm font-semibold">{c.model}</span><input name="model" maxLength={120} className={field} /></label>
      </div>
      <label className="block space-y-1"><span className="text-sm font-semibold">{c.descriptionAm}</span><textarea name="description_am" lang="am" maxLength={5000} rows={3} className="w-full rounded-card border border-line bg-white p-3" /></label>
      <label className="block space-y-1"><span className="text-sm font-semibold">{c.descriptionEn}</span><textarea name="description_en" lang="en" maxLength={5000} rows={3} className="w-full rounded-card border border-line bg-white p-3" /></label>

      {details.length ? (
        <fieldset className="space-y-2">
          <legend className="font-bold">{c.specsTitle}</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            {details.map((attribute) => (
              <label key={attribute.id} className="block space-y-1">
                <span className="text-sm font-semibold">{label(t, attribute)}</span>
                <ValueInput name={`spec_${attribute.code}`} attribute={attribute} t={t} />
              </label>
            ))}
          </div>
        </fieldset>
      ) : null}

      {defining.length ? (
        <fieldset className="space-y-2">
          <legend className="font-bold">{c.variantsTitle}</legend>
          <p className="text-sm text-slate">{c.variantsLead}</p>
          {Array.from({ length: lines }, (_, line) => (
            <div key={line} className="space-y-2 rounded-card border border-line p-3">
              <p className="text-sm font-semibold">{fill(c.variant, { number: line + 1 })}</p>
              <div className="grid gap-3 sm:grid-cols-3">
                {defining.map((attribute) => (
                  <label key={attribute.id} className="block space-y-1">
                    <span className="text-sm">{label(t, attribute)}</span>
                    <ValueInput name={`variant_${line}_${attribute.code}`} attribute={attribute} t={t} />
                  </label>
                ))}
                <label className="block space-y-1"><span className="text-sm">{c.modelCode}</span><input name={`variant_${line}_model`} maxLength={80} className={field} /></label>
              </div>
            </div>
          ))}
          {lines < MAX_LINES ? (
            <button type="button" onClick={() => setLines(lines + 1)} className="min-h-12 rounded-card border border-ink px-4 font-semibold">{c.addVariantLine}</button>
          ) : null}
        </fieldset>
      ) : null}

      {mode.kind === "staff" ? (
        <label className="flex min-h-12 items-center gap-3"><input type="checkbox" name="publish" className="h-5 w-5" />{c.publishNow}</label>
      ) : null}
      <button type="submit" disabled={busy} className="min-h-12 rounded-card bg-ink px-5 font-bold text-paper disabled:opacity-60">{mode.kind === "staff" ? c.create : c.propose}</button>
      {message ? <p role={message.ok ? "status" : "alert"} className={message.ok ? "font-semibold" : "font-semibold text-clay"}>{message.text}</p> : null}
    </form>
  );
}
