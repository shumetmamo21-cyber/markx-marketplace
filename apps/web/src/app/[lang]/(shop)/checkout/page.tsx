import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { Checkout } from "@/components/Checkout";
import { serverApi } from "@/lib/api/server";
import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";
import { getMe } from "@/lib/session";

export const metadata: Metadata = { robots: { index: false } };

export default async function CheckoutPage({ params }: PageProps<"/[lang]/checkout">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const me = await getMe();
  if (!me) redirect(`/${lang}/sign-in?next=/${lang}/checkout`);
  const t = await getMessages(lang);
  const api = await serverApi();
  const [addresses, zones] = await Promise.all([
    api.GET("/api/v1/me/addresses", {}),
    api.GET("/api/v1/delivery/zones", {}),
  ]);
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <h1 className="text-2xl font-extrabold">{t.checkout.title}</h1>
      <Checkout lang={lang} t={t} addresses={addresses.data ?? []} zones={(zones.data ?? []).filter((z) => z.is_active)} />
    </div>
  );
}
