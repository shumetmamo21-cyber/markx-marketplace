import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { SignInForm } from "@/components/SignInForm";
import { SignOutButton } from "@/components/SignOutButton";
import { fill, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";
import { safeNext } from "@/lib/safe-next";
import { getMe } from "@/lib/session";

export const metadata: Metadata = { robots: { index: false } };

export default async function SignInPage({ params, searchParams }: PageProps<"/[lang]/sign-in">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const next = safeNext((await searchParams).next, `/${lang}/orders`);
  const me = await getMe();
  return (
    <div className="mx-auto max-w-md space-y-5">
      <h1 className="text-2xl font-extrabold">{me ? t.nav.account : t.auth.title}</h1>
      {me ? (
        <div className="space-y-4 rounded-card border border-line bg-white p-5">
          <p>{fill(t.auth.signedInAs, { phone: me.phone })}</p>
          <p className="flex flex-wrap gap-3">
            <Link href={`/${lang}/orders`} className="inline-flex min-h-12 items-center rounded-card bg-adey px-5 font-bold">{t.nav.orders}</Link>
            <Link href={`/${lang}/account`} className="inline-flex min-h-12 items-center rounded-card border border-ink px-4 font-semibold">{t.account.title}</Link>
            <SignOutButton label={t.auth.signOut} home={`/${lang}`} />
          </p>
        </div>
      ) : (
        <>
          <p className="text-slate">{t.auth.lead}</p>
          <SignInForm lang={lang} t={t.auth} next={next} dev={process.env.NODE_ENV !== "production"} />
        </>
      )}
    </div>
  );
}
