import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { GuestCheckout } from "@/components/GuestCheckout";
import { serverApi } from "@/lib/api/server";
import { formatPrice } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";
import { getGuestCheckoutTerms, getMe } from "@/lib/session";

export const metadata: Metadata = { robots: { index: false } };

// Ordering as a guest (C-07, D-108): for a buyer without Telegram, or anyone
// while Telegram is blocked. A signed-in person checks out from their account.
export default async function GuestCheckoutPage({ params }: PageProps<"/[lang]/checkout/guest">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  if (await getMe()) redirect(`/${lang}/checkout`);
  const t = await getMessages(lang);
  const terms = await getGuestCheckoutTerms();
  const signIn = `/${lang}/sign-in?next=/${lang}/checkout`;
  if (!terms.enabled) {
    return (
      <div className="mx-auto max-w-2xl space-y-5">
        <h1 className="text-2xl font-extrabold">{t.guest.title}</h1>
        <p role="alert" className="font-semibold">{t.guest.unavailable}</p>
        <Link href={signIn} className="inline-flex min-h-12 items-center rounded-card bg-adey px-5 font-bold">{t.auth.title}</Link>
      </div>
    );
  }
  const api = await serverApi();
  const { data: zones } = await api.GET("/api/v1/delivery/zones", {});
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <header className="space-y-2">
        <h1 className="text-2xl font-extrabold">{t.guest.title}</h1>
        <p className="text-slate">{t.guest.lead}</p>
        <p className="text-sm text-slate">{fill(t.guest.limit, { amount: formatPrice(terms.max_order_value_santim, lang) })}</p>
        <Link href={signIn} className="inline-flex min-h-12 items-center font-semibold underline">{t.guest.signInInstead}</Link>
      </header>
      <GuestCheckout
        lang={lang}
        t={{ guest: t.guest, checkout: t.checkout, cart: t.cart, apiErrors: t.apiErrors }}
        zones={(zones ?? []).filter((z) => z.is_active)}
        terms={terms}
        // The public Turnstile site key, read when the page is served (D-085).
        siteKey={process.env.MARKX_TURNSTILE_SITE_KEY || undefined}
      />
    </div>
  );
}
