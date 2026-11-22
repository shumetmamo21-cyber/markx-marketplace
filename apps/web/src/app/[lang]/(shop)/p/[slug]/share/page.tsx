import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { SharePanel } from "@/components/SharePanel";
import { serverApi } from "@/lib/api/server";
import { fill, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";
import { productLines, publicOrigin } from "@/lib/share";

export const metadata: Metadata = { robots: { index: false } };

// Share a product (S-10; D-107): its own page, so the product page itself
// carries one link and stays within its weight (D.26).
export default async function ShareProductPage({ params }: PageProps<"/[lang]/p/[slug]/share">) {
  const { lang, slug } = await params;
  if (!isLocale(lang)) notFound();
  const origin = publicOrigin(process.env);
  const api = await serverApi();
  const [{ data: product }, { data: offers }] = await Promise.all([
    api.GET("/api/v1/catalog/products/{slug}", { params: { path: { slug }, query: { lang } } }),
    api.GET("/api/v1/catalog/products/{slug}/offers", { params: { path: { slug } } }),
  ]);
  if (!product || !origin) notFound();
  const t = await getMessages(lang);
  const shops = new Set((offers?.offers ?? []).map((offer) => offer.store_slug)).size;
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <p><Link href={`/${lang}/p/${product.slug}`} className="inline-flex min-h-12 items-center font-semibold underline">{product.name}</Link></p>
      <h1 className="text-2xl font-extrabold">{fill(t.share.titleOf, { name: product.name })}</h1>
      <SharePanel origin={origin} lang={lang} kind="product" slug={product.slug} name={product.name} lines={productLines(t, lang, offers?.lowest_price_santim ?? null, shops)} t={t} />
    </div>
  );
}
