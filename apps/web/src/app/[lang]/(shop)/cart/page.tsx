import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CartView } from "@/components/CartView";
import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

export const metadata: Metadata = { robots: { index: false } };

export default async function CartPage({ params }: PageProps<"/[lang]/cart">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <h1 className="text-2xl font-extrabold">{t.cart.title}</h1>
      <CartView lang={lang} t={t.cart} conditions={t.condition} />
    </div>
  );
}
