import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CategoryChooser } from "@/components/admin/CategoryChooser";
import { ProductForm } from "@/components/ProductForm";
import { serverApi } from "@/lib/api/server";
import { flattenCategories } from "@/lib/categories";
import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

export const metadata: Metadata = { robots: { index: false } };

// A shop proposes a product missing from the catalogue (blueprint S-05): the
// same form staff use, sent as a proposal that nobody sees until catalogue
// staff approve it or merge it into an existing product.
export default async function ProposeProductPage({ params, searchParams }: PageProps<"/[lang]/seller/[sellerId]/offers/propose">) {
  const { lang, sellerId } = await params;
  if (!isLocale(lang)) notFound();
  const raw = (await searchParams).category;
  const slug = (Array.isArray(raw) ? raw[0] : raw) ?? "";
  const t = await getMessages(lang);
  const api = await serverApi();
  const [tree, brands, category] = await Promise.all([
    api.GET("/api/v1/catalog/categories", { params: { query: { lang } } }),
    api.GET("/api/v1/catalog/brands", {}),
    /^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug) ? api.GET("/api/v1/catalog/categories/{slug}", { params: { path: { slug }, query: { lang } } }) : Promise.resolve(null),
  ]);
  const c = t.catalogue;
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <p><Link href={`/${lang}/seller/${sellerId}/offers/new`} className="inline-flex min-h-12 items-center font-semibold underline">{t.seller.addOfferTitle}</Link></p>
      <h1 className="text-2xl font-extrabold">{t.seller.proposeTitle}</h1>
      <p className="text-slate">{t.seller.proposeLead}</p>
      {category?.data ? (
        <>
          <p className="font-semibold">{c.category}: {category.data.name}</p>
          <ProductForm lang={lang} mode={{ kind: "seller", sellerId }} category={category.data} brands={brands.data ?? []} t={{ catalogue: t.catalogue, apiErrors: t.apiErrors }} />
        </>
      ) : (
        <CategoryChooser categories={flattenCategories(tree.data ?? [])} label={c.category} button={c.continue} lead={c.chooseCategoryLead} />
      )}
    </div>
  );
}
