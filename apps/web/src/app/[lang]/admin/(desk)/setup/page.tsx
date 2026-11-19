import { notFound } from "next/navigation";

import { CategoryAttributeForm, CategoryForm, NewAttributeForm, NewBrandForm, NewCategoryForm, NewOptionForm, RemoveTermButton, RestrictedTermForm } from "@/components/admin/StaffActions";
import { serverApi } from "@/lib/api/server";
import { flattenCategories } from "@/lib/categories";
import { isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

// Catalogue setup (blueprint D.5, D.6, AD-02, H.3): the categories, the
// details (attributes) products in each have, the brands, and the goods not
// allowed. Catalogue staff only; every change is checked and logged by the API.
export default async function CatalogueSetupPage({ params }: PageProps<"/[lang]/admin/setup">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const [categories, attributes, brands, terms] = await Promise.all([
    api.GET("/api/v1/admin/catalog/categories", { params: { query: { lang } } }),
    api.GET("/api/v1/admin/catalog/attributes", { params: { query: { lang } } }),
    api.GET("/api/v1/catalog/brands", {}),
    api.GET("/api/v1/admin/catalog/restricted-terms", {}),
  ]);
  const a = t.admin;
  if (categories.response.status === 403) return <p role="alert">{a.notAllowed}</p>;
  const text = { admin: a, apiErrors: t.apiErrors };
  const flat = flattenCategories(categories.data ?? []);
  const choices = flat.map((c) => ({ id: c.id, label: c.label }));
  const attributeChoices = (attributes.data ?? []).map((x) => ({ id: x.id, label: `${x.name} (${x.code})` }));
  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-extrabold">{a.setupTitle}</h1>

      <section aria-labelledby="categories" className="space-y-3">
        <h2 id="categories" className="text-lg font-bold">{a.categoriesTitle}</h2>
        <ul className="space-y-2">
          {flat.map((category) => (
            <li key={category.id} className="rounded-card border border-line bg-white p-3" style={{ marginInlineStart: `${category.depth * 1}rem` }}>
              <details>
                <summary className="flex min-h-12 cursor-pointer flex-wrap items-center gap-2 font-semibold">
                  {category.name} <span className="text-sm font-normal text-slate">({category.slug})</span>
                  {!category.is_active ? <span className="rounded-full border border-clay px-2 text-sm text-clay">{a.categoryOff}</span> : null}
                </summary>
                <CategoryForm category={category} t={text} />
              </details>
            </li>
          ))}
        </ul>
        <div className="rounded-card border border-ink bg-white p-4"><NewCategoryForm parents={choices} t={text} /></div>
      </section>

      <section aria-labelledby="attributes" className="space-y-3">
        <h2 id="attributes" className="text-lg font-bold">{a.attributesTitle}</h2>
        <ul className="grid gap-2 md:grid-cols-2">
          {(attributes.data ?? []).map((attribute) => (
            <li key={attribute.id} className="space-y-2 rounded-card border border-line bg-white p-3">
              <p className="font-semibold">{attribute.name} <span className="text-sm font-normal text-slate">({attribute.code} · {codeLabel(t, "attributeType", attribute.data_type)}{attribute.unit ? ` · ${attribute.unit}` : ""})</span></p>
              {attribute.options.length ? <p className="text-sm">{attribute.options.map((o) => o.label).join(", ")}</p> : null}
              {attribute.data_type === "option" ? (
                <details><summary className="inline-flex min-h-12 cursor-pointer items-center text-sm font-semibold underline">{a.optionNew}</summary><NewOptionForm attributeId={attribute.id} t={text} /></details>
              ) : null}
            </li>
          ))}
        </ul>
        <div className="rounded-card border border-ink bg-white p-4"><NewAttributeForm t={text} types={t.labels.attributeType} /></div>
        {choices.length && attributeChoices.length ? (
          <div className="space-y-2 rounded-card border border-line bg-white p-4">
            <h3 className="font-bold">{a.linkTitle}</h3>
            <CategoryAttributeForm categories={choices} attributes={attributeChoices} t={text} />
          </div>
        ) : null}
      </section>

      <section aria-labelledby="brands" className="space-y-3">
        <h2 id="brands" className="text-lg font-bold">{a.brandsTitle}</h2>
        <p>{(brands.data ?? []).map((b) => b.name).join(" · ")}</p>
        <div className="max-w-md"><NewBrandForm t={text} /></div>
      </section>

      <section aria-labelledby="terms" className="space-y-3">
        <h2 id="terms" className="text-lg font-bold">{a.termsTitle}</h2>
        <p className="text-sm text-slate">{a.termsLead}</p>
        <ul className="grid gap-2 sm:grid-cols-2">
          {(terms.data ?? []).map((term) => (
            <li key={term.id} className="flex flex-wrap items-center justify-between gap-2 rounded-card border border-line bg-white p-2">
              <span><span className="font-semibold">{term.term}</span>{term.reason ? <span className="text-sm text-slate"> · {term.reason}</span> : null}</span>
              <RemoveTermButton termId={term.id} t={text} />
            </li>
          ))}
        </ul>
        <RestrictedTermForm t={text} />
      </section>
    </div>
  );
}
