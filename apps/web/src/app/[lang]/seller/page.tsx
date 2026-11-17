import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";
import { getMe } from "@/lib/session";

// The seller dashboard opens on the orders that need an answer (I.4).
export default async function SellerEntry({ params }: PageProps<"/[lang]/seller">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const me = await getMe();
  if (!me) redirect(`/${lang}/sign-in?next=/${lang}/seller`);
  const first = me.sellers[0];
  if (first) redirect(`/${lang}/seller/${first.seller_id}/orders`);
  const t = await getMessages(lang);
  return (
    <main id="main" className="mx-auto max-w-md space-y-4 px-4 py-16">
      <h1 className="text-2xl font-extrabold">{t.seller.title}</h1>
      <p>{t.seller.notSeller}</p>
      <p className="text-slate">{t.seller.apply}</p>
      <Link href={`/${lang}`} className="font-semibold underline">{t.seller.navExit}</Link>
    </main>
  );
}
