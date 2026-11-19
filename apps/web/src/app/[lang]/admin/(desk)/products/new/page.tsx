import { notFound } from "next/navigation";

import { CategoryChooser } from "@/components/admin/CategoryChooser";
import { ProductForm } from "@/components/ProductForm";
import { serverApi } from "@/lib/api/server";
import { flattenCategories } from "@/lib/categories";
import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

// A new product (AD-02): the category first, since it decides the details
// and versions; then the product form over that category's attributes.
export default async function NewProductPage({ params, searchParams }: PageProps<"/[lang]/admin/products/new">) {
  const { lang } = await params;
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
      <h1 className="text-2xl font-extrabold">{t.admin.productNew}</h1>
      {category?.data ? (
        <>
          <p className="font-semibold">{c.category}: {category.data.name}</p>
          <ProductForm lang={lang} mode={{ kind: "staff" }} category={category.data} brands={brands.data ?? []} t={{ catalogue: t.catalogue, apiErrors: t.apiErrors }} />
        </>
      ) : (
        <CategoryChooser categories={flattenCategories(tree.data ?? [])} label={c.category} button={c.continue} lead={c.chooseCategoryLead} />
      )}
    </div>
  );
}
