import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { StaffSignInForm } from "@/components/admin/StaffSignInForm";
import { StaffStepForm } from "@/components/admin/StaffStepForm";
import { TelegramSignIn } from "@/components/TelegramSignIn";
import { Wordmark } from "@/components/Wordmark";
import { fill, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";
import { getMe, getSignInMethods } from "@/lib/session";

export const metadata: Metadata = { robots: { index: false, follow: false } };

// Staff sign in with Telegram, then add their existing second step: the
// password and the authenticator code (D-101, decision SI-1). Phone,
// password and code without Telegram only while SMS is switched on, as the
// backup (P-101-8).
export default async function StaffSignInPage({ params }: PageProps<"/[lang]/admin/sign-in">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const me = await getMe();
  if (me?.session_kind === "staff" && me.staff) redirect(`/${lang}/admin`);
  const methods = me ? null : await getSignInMethods();
  const forms = { admin: t.admin, apiErrors: t.apiErrors };
  return (
    <main id="main" className="mx-auto max-w-sm space-y-5 px-4 py-12">
      <Wordmark label={t.brand.tagline} />
      <h1 className="text-2xl font-extrabold">{me ? t.admin.stepTitle : t.admin.signInTitle}</h1>
      {me ? (
        <>
          <p className="text-slate">{fill(t.admin.stepLead, { phone: me.phone })}</p>
          <StaffStepForm next={`/${lang}/admin`} t={forms} />
        </>
      ) : (
        <>
          {methods?.telegram ? (
            <>
              <p className="text-slate">{t.admin.signInLeadTelegram}</p>
              <TelegramSignIn lang={lang} t={{ auth: t.auth, apiErrors: t.apiErrors }} next={`/${lang}/admin/sign-in`} />
            </>
          ) : null}
          {methods?.staff_phone_password ? (
            <section aria-labelledby="staff-phone-password" className="space-y-3">
              <h2 id="staff-phone-password" className={methods.telegram ? "pt-2 text-lg font-bold" : "sr-only"}>{t.admin.orPhonePassword}</h2>
              <p className="text-slate">{t.admin.signInLead}</p>
              <StaffSignInForm next={`/${lang}/admin`} t={forms} />
            </section>
          ) : null}
          {!methods?.telegram && !methods?.staff_phone_password ? <p role="alert" className="font-semibold">{t.auth.unavailable}</p> : null}
        </>
      )}
    </main>
  );
}
