import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { StoreForm } from "@/components/seller/SellerForms";
import { serverApi } from "@/lib/api/server";
import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

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
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <h1 className="text-2xl font-extrabold">{t.seller.storeTitle}</h1>
      <StoreForm sellerId={sellerId} store={data} t={{ seller: t.seller, apiErrors: t.apiErrors }} />
    </div>
  );
}
