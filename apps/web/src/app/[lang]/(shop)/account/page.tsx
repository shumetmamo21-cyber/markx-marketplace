import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { AddAddress, DataRequestForm, MarkNotificationsRead, ProfileForm, RemoveAddress, SignOutEverywhere } from "@/components/AccountForms";
import { SignOutButton } from "@/components/SignOutButton";
import { TelegramConnection } from "@/components/TelegramConnection";
import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";
import { describeNotification } from "@/lib/notifications";
import { getMe } from "@/lib/session";

export const metadata: Metadata = { robots: { index: false } };

const NEWEST = 10;

// The buyer's account (blueprint I.5): name and language, saved addresses,
// messages from MarkX, their Telegram connection (D-093), their data (H.5)
// and signing out everywhere.
export default async function AccountPage({ params }: PageProps<"/[lang]/account">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const me = await getMe();
  if (!me) redirect(`/${lang}/sign-in?next=/${lang}/account`);
  const t = await getMessages(lang);
  const api = await serverApi();
  const [addresses, zones, notifications, requests, telegram] = await Promise.all([
    api.GET("/api/v1/me/addresses", {}),
    api.GET("/api/v1/delivery/zones", {}),
    api.GET("/api/v1/me/notifications", {}),
    api.GET("/api/v1/me/data-requests", {}),
    api.GET("/api/v1/me/telegram", {}),
  ]);
  const a = t.account;
  const text = { account: t.account, apiErrors: t.apiErrors };
  const messages = notifications.data ?? [];
  const Message = ({ n }: { n: (typeof messages)[number] }) => {
            const shown = describeNotification(t, lang, n);
            return (
              <li className={`rounded-card border bg-white p-3 ${n.read_at ? "border-line" : "border-ink"}`}>
                <p className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-semibold">{!n.read_at ? <><span className="mr-2 rounded-full bg-adey px-2 py-0.5 text-xs font-bold">{a.unread}</span>{" "}</> : null}{shown.text}</span>
                  <span className="text-sm text-slate">{formatDateTime(n.created_at, lang)}</span>
                </p>
                {shown.href ? <Link href={shown.href} className="inline-flex min-h-12 items-center text-sm font-semibold underline">{a.open}</Link> : null}
              </li>
            );
          };
  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-extrabold">{a.title}</h1>
        <p>{fill(t.auth.signedInAs, { phone: me.phone })}</p>
        <p className="flex flex-wrap gap-3">
          <Link href={`/${lang}/orders`} className="inline-flex min-h-12 items-center rounded-card bg-adey px-5 font-bold">{t.nav.orders}</Link>
          <Link href={`/${lang}/reviews`} className="inline-flex min-h-12 items-center rounded-card border border-ink px-4 font-semibold">{t.reviews.mine}</Link>
          {me.sellers.length ? <Link href={`/${lang}/seller`} className="inline-flex min-h-12 items-center rounded-card border border-ink px-4 font-semibold">{a.myShop}</Link> : null}
          <SignOutButton label={t.auth.signOut} home={`/${lang}`} />
        </p>
      </header>

      <section aria-labelledby="messages" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="messages" className="text-xl font-bold">{a.notificationsTitle}</h2>
          {messages.some((n) => !n.read_at) ? <MarkNotificationsRead t={text} /> : null}
        </div>
        {messages.length === 0 ? <p className="text-slate">{a.notificationsNone}</p> : null}
        <ul className="space-y-2">
          {messages.slice(0, NEWEST).map((n) => <Message key={n.id} n={n} />)}
        </ul>
        {messages.length > NEWEST ? (
          <details>
            <summary className="flex min-h-12 cursor-pointer items-center font-semibold underline">{fill(a.olderMessages, { count: messages.length - NEWEST })}</summary>
            <ul className="space-y-2">{messages.slice(NEWEST).map((n) => <Message key={n.id} n={n} />)}</ul>
          </details>
        ) : null}
      </section>

      {telegram.data ? <TelegramConnection initial={telegram.data} lang={lang} t={text} /> : null}

      <section aria-labelledby="profile" className="space-y-3 rounded-card border border-line bg-white p-4">
        <h2 id="profile" className="text-xl font-bold">{a.profileTitle}</h2>
        <ProfileForm name={me.name ?? null} language={me.language} t={text} />
      </section>

      <section aria-labelledby="addresses" className="space-y-3">
        <h2 id="addresses" className="text-xl font-bold">{a.addressesTitle}</h2>
        {(addresses.data ?? []).length === 0 ? <p className="text-slate">{a.addressesNone}</p> : null}
        <ul className="space-y-2">
          {(addresses.data ?? []).map((address) => (
            <li key={address.id} className="space-y-1 rounded-card border border-line bg-white p-3">
              <p className="font-semibold">{address.recipient_name} · {address.phone}</p>
              <p className="text-sm">{lang === "am" ? address.area_name_am : address.area_name_en} · {address.landmark}</p>
              {address.driver_notes ? <p className="text-sm text-slate">{address.driver_notes}</p> : null}
              <RemoveAddress addressId={address.id} t={text} />
            </li>
          ))}
        </ul>
        <details className="rounded-card border border-line bg-white p-4">
          <summary className="flex min-h-12 cursor-pointer items-center font-semibold">{a.addressAdd}</summary>
          <AddAddress lang={lang} zones={(zones.data ?? []).filter((z) => z.is_active)} t={{ checkout: t.checkout, apiErrors: t.apiErrors }} />
        </details>
      </section>

      <section aria-labelledby="privacy" className="space-y-3 rounded-card border border-line bg-white p-4">
        <h2 id="privacy" className="text-xl font-bold">{a.privacyTitle}</h2>
        <p className="text-sm text-slate">{a.privacyLead}</p>
        {(requests.data ?? []).length ? (
          <ul className="space-y-1 text-sm">
            {(requests.data ?? []).map((request) => (
              <li key={request.id}>
                {codeLabel(t, "dataRequestKind", request.kind)} · {codeLabel(t, "dataRequestStatus", request.status)} · {formatDateTime(request.created_at, lang)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm">{a.requestsNone}</p>
        )}
        <DataRequestForm t={text} kinds={t.labels.dataRequestKind} />
      </section>

      <section aria-labelledby="security" className="space-y-2">
        <h2 id="security" className="text-xl font-bold">{a.securityTitle}</h2>
        <p className="text-sm text-slate">{a.signOutEverywhereHint}</p>
        <SignOutEverywhere home={`/${lang}`} t={text} />
      </section>
    </div>
  );
}
