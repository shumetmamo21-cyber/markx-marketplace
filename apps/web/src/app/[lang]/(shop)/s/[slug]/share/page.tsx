import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { SharePanel } from "@/components/SharePanel";
import { serverApi } from "@/lib/api/server";
import { fill, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";
import { publicOrigin, storeLines } from "@/lib/share";

export const metadata: Metadata = { robots: { index: false } };

// Share a shop (S-10; D-107): its link, QR code and cards on their own page.
export default async function ShareStorePage({ params }: PageProps<"/[lang]/s/[slug]/share">) {
  const { lang, slug } = await params;
  if (!isLocale(lang)) notFound();
  const origin = publicOrigin(process.env);
  const api = await serverApi();
  const { data: store } = await api.GET("/api/v1/catalog/stores/{slug}", { params: { path: { slug } } });
  if (!store || !origin) notFound();
  const t = await getMessages(lang);
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <p><Link href={`/${lang}/s/${store.slug}`} className="inline-flex min-h-12 items-center font-semibold underline">{store.name}</Link></p>
      <h1 className="text-2xl font-extrabold">{fill(t.share.titleOf, { name: store.name })}</h1>
      <SharePanel origin={origin} lang={lang} kind="store" slug={store.slug} name={store.name} lines={storeLines(t, store.verification_level)} t={t} />
    </div>
  );
}
