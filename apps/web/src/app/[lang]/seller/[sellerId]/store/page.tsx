import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { StoreForm } from "@/components/seller/SellerForms";
import { StoreLogo } from "@/components/seller/StoreLogo";
import { SharePanel } from "@/components/SharePanel";
import { serverApi } from "@/lib/api/server";
import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";
import { publicOrigin, storeLines } from "@/lib/share";

export const metadata: Metadata = { robots: { index: false } };

// What buyers see on the shop's page (blueprint I.5): name, link, about,
// hours, areas, returns, Telegram. The API decides what may still change
// (the link is fixed once the shop is approved, store_slug_locked).
export default async function SellerStorePage({ params }: PageProps<"/[lang]/seller/[sellerId]/store">) {
  const { lang, sellerId } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/seller/{seller_id}/store", { params: { path: { seller_id: sellerId } } });
  if (response.status === 403 || !data) return <p role="alert">{t.apiErrors.permission_denied}</p>;
  // Share cards and the QR code (S-10): only once buyers can open the shop's
  // page, so a printed code never leads nowhere.
  const origin = publicOrigin(process.env);
  const shown = origin ? (await api.GET("/api/v1/catalog/stores/{slug}", { params: { path: { slug: data.slug } } })).data : undefined;
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <h1 className="text-2xl font-extrabold">{t.seller.storeTitle}</h1>
      <StoreLogo sellerId={sellerId} storeName={data.name} logoUrl={data.logo_url} t={{ seller: t.seller, store: t.store, apiErrors: t.apiErrors }} />
      {origin && shown ? <SharePanel origin={origin} lang={lang} kind="store" slug={shown.slug} name={shown.name} lines={storeLines(t, shown.verification_level)} t={t} heading={t.seller.shareTitle} /> : null}
      <StoreForm sellerId={sellerId} store={data} t={{ seller: t.seller, apiErrors: t.apiErrors }} />
    </div>
  );
}
