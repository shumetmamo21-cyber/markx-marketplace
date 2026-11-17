import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { LegalForm } from "@/components/seller/SellerForms";
import { serverApi } from "@/lib/api/server";
import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

export const metadata: Metadata = { robots: { index: false } };

// The owner's legal details (blueprint C.3: the owner only). Once sent for
// checking they are locked; the API says so (application_locked).
export default async function SellerLegalPage({ params }: PageProps<"/[lang]/seller/[sellerId]/legal">) {
  const { lang, sellerId } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/seller/{seller_id}/legal", { params: { path: { seller_id: sellerId } } });
  if (response.status === 403 || !data) return <p role="alert">{t.apiErrors.permission_denied}</p>;
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <h1 className="text-2xl font-extrabold">{t.seller.legalTitle}</h1>
      <p className="text-slate">{t.seller.legalLead}</p>
      <LegalForm sellerId={sellerId} legal={data} t={{ seller: t.seller, apiErrors: t.apiErrors }} />
    </div>
  );
}
