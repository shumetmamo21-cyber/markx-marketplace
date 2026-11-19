import Link from "next/link";
import { notFound } from "next/navigation";

import { AddVariantForm, AliasForm, ProductTextForm, RemoveAliasButton } from "@/components/admin/StaffActions";
import { serverApi } from "@/lib/api/server";
import { isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

// One product for catalogue staff (AD-02): its text in both languages, its
// versions (a new one from the category's version-defining details), the
// other names buyers search for, and links to its pictures and listings.
export default async function StaffProductPage({ params }: PageProps<"/[lang]/admin/products/[id]">) {
  const { lang, id } = await params;
  if (!isLocale(lang) || !/^[0-9a-f-]{36}$/.test(id)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data: product, response } = await api.GET("/api/v1/admin/catalog/products/{product_id}", { params: { path: { product_id: id }, query: { lang } } });
  const a = t.admin;
  if (response.status === 403) return <p role="alert">{a.notAllowed}</p>;
  if (!product) notFound();
  const category = (await api.GET("/api/v1/catalog/categories/{slug}", { params: { path: { slug: product.category.slug }, query: { lang } } })).data;
  const defining = (category?.attributes ?? []).filter((x) => x.is_variant_defining && x.data_type === "option");
  const text = { admin: a, apiErrors: t.apiErrors };
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header className="space-y-1">
        <p><Link href={`/${lang}/admin/products?status=${product.status}`} className="font-semibold underline">{a.productsTitle}</Link></p>
        <h1 className="text-2xl font-extrabold">{product.name}</h1>
        <p className="text-slate">{codeLabel(t, "productStatus", product.status)} · {product.category.name}{product.brand ? ` · ${product.brand.name}` : ""}{product.model ? ` · ${product.model}` : ""}</p>
        <p className="flex flex-wrap gap-4 text-sm">
          <Link href={`/${lang}/admin/pictures?product=${product.slug}`} className="inline-flex min-h-12 items-center font-semibold underline">{a.navPictures}</Link>
          <Link href={`/${lang}/admin/listings?product=${product.slug}`} className="inline-flex min-h-12 items-center font-semibold underline">{a.navListings}</Link>
          {product.status === "approved" ? <Link href={`/${lang}/p/${product.slug}`} className="inline-flex min-h-12 items-center font-semibold underline">{a.productPage}</Link> : null}
        </p>
      </header>

      <section aria-labelledby="text" className="space-y-2 rounded-card border border-line bg-white p-4">
        <h2 id="text" className="font-bold">{a.productTextTitle}</h2>
        <ProductTextForm product={product} t={text} />
      </section>

      {product.specs.length ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-card border border-line bg-white p-4 text-sm">
          {product.specs.map((spec) => (
            <div key={spec.code} className="contents"><dt className="text-slate">{spec.name}</dt><dd className="font-semibold">{spec.display}</dd></div>
          ))}
        </dl>
      ) : null}

      <section aria-labelledby="variants" className="space-y-2 rounded-card border border-line bg-white p-4">
        <h2 id="variants" className="font-bold">{a.variantsTitle}</h2>
        <ul className="space-y-1 text-sm">
          {product.variants.map((variant) => (
            <li key={variant.id} className={variant.is_active ? "" : "text-slate line-through"}>{variant.label || product.name}{variant.model_code ? ` · ${variant.model_code}` : ""}</li>
          ))}
        </ul>
        {defining.length ? <AddVariantForm productId={product.id} attributes={defining.map((x) => ({ code: x.code, name: x.name, is_required: x.is_required, options: x.options }))} t={text} /> : null}
      </section>

      <section aria-labelledby="aliases" className="space-y-2 rounded-card border border-line bg-white p-4">
        <h2 id="aliases" className="font-bold">{a.aliasesTitle}</h2>
        <ul className="space-y-2">
          {product.aliases.map((alias) => (
            <li key={alias.id} className="flex flex-wrap items-center justify-between gap-2">
              <span>{alias.alias}</span>
              <RemoveAliasButton productId={product.id} aliasId={alias.id} t={text} />
            </li>
          ))}
        </ul>
        <AliasForm productId={product.id} t={text} />
      </section>
    </div>
  );
}
