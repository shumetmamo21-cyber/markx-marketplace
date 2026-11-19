import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ApplicationForm } from "@/components/seller/SellerForms";
import { serverApi } from "@/lib/api/server";
import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";
import { getMe } from "@/lib/session";

import { sellerLanding, sellerMenu } from "./[sellerId]/menu";

// The seller dashboard opens on the orders that need an answer (I.4), or on
// the first screen this member's role may open. Someone without a shop sees
// the application form if the API says they may apply (invite-only at
// launch), otherwise how to get an invitation.
export default async function SellerEntry({ params }: PageProps<"/[lang]/seller">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const me = await getMe();
  if (!me) redirect(`/${lang}/sign-in?next=/${lang}/seller`);
  const t = await getMessages(lang);
  const first = me.sellers[0];
  if (first) redirect(sellerLanding(sellerMenu(lang, first.seller_id, first, t), first.seller_id) ?? `/${lang}`);
  const api = await serverApi();
  const { data: eligibility } = await api.GET("/api/v1/seller/eligibility", {});
  const s = t.seller;
  return (
    <main id="main" className="mx-auto max-w-xl space-y-4 px-4 py-10">
      {eligibility?.may_apply ? (
        <>
          <h1 className="text-2xl font-extrabold">{s.applyTitle}</h1>
          <p className="text-slate">{s.applyLead}</p>
          <ApplicationForm lang={lang} individualEnabled={eligibility.individual_enabled} t={{ seller: t.seller, apiErrors: t.apiErrors }} kinds={t.labels.sellerKind} />
        </>
      ) : (
        <>
          <h1 className="text-2xl font-extrabold">{s.title}</h1>
          <p>{s.notSeller}</p>
          <p className="text-slate">{s.notInvited}</p>
        </>
      )}
      <Link href={`/${lang}`} className="inline-flex min-h-12 items-center font-semibold underline">{s.exit}</Link>
    </main>
  );
}
