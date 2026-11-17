import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";
import { getMe } from "@/lib/session";

import { sellerMenu } from "./[sellerId]/menu";

// The seller dashboard opens on the orders that need an answer (I.4), or
// on the first screen this member's role may open.
export default async function SellerEntry({ params }: PageProps<"/[lang]/seller">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const me = await getMe();
  if (!me) redirect(`/${lang}/sign-in?next=/${lang}/seller`);
  const t = await getMessages(lang);
  const first = me.sellers[0];
  if (first) redirect(sellerMenu(lang, first.seller_id, first, t)[0]?.href ?? `/${lang}`);
  return (
    <main id="main" className="mx-auto max-w-md space-y-4 px-4 py-16">
      <h1 className="text-2xl font-extrabold">{t.seller.title}</h1>
      <p>{t.seller.notSeller}</p>
      <p className="text-slate">{t.seller.apply}</p>
      <Link href={`/${lang}`} className="font-semibold underline">{t.seller.navExit}</Link>
    </main>
  );
}
