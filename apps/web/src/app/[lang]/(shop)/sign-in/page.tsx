import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { SignInForm } from "@/components/SignInForm";
import { SignOutButton } from "@/components/SignOutButton";
import { TelegramSignIn } from "@/components/TelegramSignIn";
import { fill, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";
import { safeNext } from "@/lib/safe-next";
import { getMe, getSignInMethods } from "@/lib/session";

export const metadata: Metadata = { robots: { index: false } };

export default async function SignInPage({ params, searchParams }: PageProps<"/[lang]/sign-in">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const next = safeNext((await searchParams).next, `/${lang}/orders`);
  const me = await getMe();
  // Telegram for everyone (D-101, decision SI-1); the SMS code only while
  // the server has SMS switched on, as a backup.
  const methods = me ? null : await getSignInMethods();
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
          {methods?.telegram ? (
            <>
              <p className="text-slate">{t.auth.leadTelegram}</p>
              <TelegramSignIn lang={lang} t={{ auth: t.auth, apiErrors: t.apiErrors }} next={next} />
            </>
          ) : null}
          {methods?.sms ? (
            <section aria-labelledby="sms-sign-in" className="space-y-3">
              <h2 id="sms-sign-in" className={methods.telegram ? "pt-2 text-lg font-bold" : "sr-only"}>{t.auth.orSms}</h2>
              <p className="text-slate">{t.auth.lead}</p>
              <SignInForm
                lang={lang}
                t={t.auth}
                next={next}
                dev={process.env.NODE_ENV !== "production"}
                // The public Turnstile site key, read when the page is served (D-085).
                // The secret key is never here: only the API holds it.
                siteKey={process.env.MARKX_TURNSTILE_SITE_KEY || undefined}
              />
            </section>
          ) : null}
          {!methods?.telegram && !methods?.sms ? <p role="alert" className="font-semibold">{t.auth.unavailable}</p> : null}
        </>
      )}
    </div>
  );
}
