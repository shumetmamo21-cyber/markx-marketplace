import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { StaffSignInForm } from "@/components/admin/StaffSignInForm";
import { Wordmark } from "@/components/Wordmark";
import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

export const metadata: Metadata = { robots: { index: false, follow: false } };

export default async function StaffSignInPage({ params }: PageProps<"/[lang]/admin/sign-in">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  return (
    <main id="main" className="mx-auto max-w-sm space-y-5 px-4 py-12">
      <Wordmark label={t.brand.tagline} />
      <h1 className="text-2xl font-extrabold">{t.admin.signInTitle}</h1>
      <p className="text-slate">{t.admin.signInLead}</p>
      <StaffSignInForm next={`/${lang}/admin`} t={{ admin: t.admin, apiErrors: t.apiErrors }} />
    </main>
  );
}
