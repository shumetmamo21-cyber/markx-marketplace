import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AddOfferForm } from "@/components/seller/SellerForms";
import description from "@/lib/api/openapi.json";
import { serverApi } from "@/lib/api/server";
import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

export const metadata: Metadata = { robots: { index: false } };

// The API's own default for the low-stock warning, from its description.
const DEFAULT_LOW_STOCK: number | undefined = description.components.schemas.OfferIn.properties.low_stock_threshold.default;

function one(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value)?.trim() ?? "";
}

// Add an offer (blueprint I.5, S-05): find the product in the catalogue, pick
// the version, then condition, price, stock and delivery. The API checks the
// role, the shop's level (used goods need level 2), duplicates and limits.
export default async function NewOfferPage({ params, searchParams }: PageProps<"/[lang]/seller/[sellerId]/offers/new">) {
  const { lang, sellerId } = await params;
  if (!isLocale(lang)) notFound();
  const raw = await searchParams;
  const query = one(raw.q).slice(0, 100);
  const slug = one(raw.product);
  const t = await getMessages(lang);
  const s = t.seller;
  const api = await serverApi();
  const base = `/${lang}/seller/${sellerId}/offers/new`;
  const product = /^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug)
    ? (await api.GET("/api/v1/catalog/products/{slug}", { params: { path: { slug }, query: { lang } } })).data
    : undefined;
  const found = !product && query ? (await api.GET("/api/v1/search", { params: { query: { q: query, lang, limit: 20 } } })).data : undefined;

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <h1 className="text-2xl font-extrabold">{s.addOfferTitle}</h1>
      {product ? (
        <section className="space-y-3 rounded-card border border-line bg-white p-4">
          <p className="text-lg font-bold">{product.name}</p>
          <AddOfferForm
            lang={lang}
            sellerId={sellerId}
            variants={product.variants.filter((v) => v.is_active).map((v) => ({ id: v.id, label: v.label }))}
            defaultLowStock={DEFAULT_LOW_STOCK}
            t={{ seller: t.seller, apiErrors: t.apiErrors }}
            conditions={t.condition}
          />
          <p><Link href={base} className="inline-flex min-h-12 items-center font-semibold underline">{s.addOfferAnother}</Link></p>
        </section>
      ) : (
        <>
          <p className="text-slate">{s.addOfferLead}</p>
          <form method="get" className="flex items-end gap-2">
            <label className="min-w-0 flex-1 space-y-1">
              <span className="block text-sm font-semibold">{s.addOfferFind}</span>
              <input name="q" defaultValue={query} required maxLength={100} className="min-h-12 w-full rounded-card border border-line bg-white px-3" />
            </label>
            <button type="submit" className="min-h-12 shrink-0 rounded-card bg-adey px-5 font-bold">{s.addOfferSearch}</button>
          </form>
          {found ? (
            found.results.length ? (
              <ul className="space-y-2">
                {found.results.map((card) => (
                  <li key={card.product_id} className="flex flex-wrap items-center justify-between gap-2 rounded-card border border-line bg-white p-3">
                    <span>
                      <span className="block font-semibold">{card.name}</span>
                      <span className="block text-sm text-slate">{[card.brand, card.category_path].filter(Boolean).join(" · ")}</span>
                    </span>
                    <Link href={`${base}?product=${card.slug}`} className="inline-flex min-h-12 items-center rounded-card border border-ink px-4 font-semibold">{s.addOfferPick}</Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p>{s.addOfferNone}</p>
            )
          ) : null}
        </>
      )}
    </div>
  );
}
