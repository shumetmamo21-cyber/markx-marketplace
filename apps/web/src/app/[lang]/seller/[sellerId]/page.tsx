import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CloseShopForm, SubmitApplicationForm } from "@/components/seller/SellerForms";
import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { fill, isLocale, type Messages } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";
import { getMe } from "@/lib/session";

import { sellerMenu } from "./menu";

export const metadata: Metadata = { robots: { index: false } };

// An application not yet sent, or sent back for documents, offers the send
// button; the API refuses any other (application_not_editable) and checks
// that nothing is missing (application_incomplete).
const ASKS_FOR_REVIEW = new Set(["draft", "needs_documents"]);

// The shop's overview (blueprint I.4, D.3): where the application stands,
// what MarkX checked, what is still missing (the API's list, for the owner),
// today's offer counts, and every screen this member's role opens.
export default async function SellerOverview({ params }: PageProps<"/[lang]/seller/[sellerId]">) {
  const { lang, sellerId } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const [seller, dashboard, me] = await Promise.all([
    api.GET("/api/v1/seller/{seller_id}", { params: { path: { seller_id: sellerId } } }),
    api.GET("/api/v1/seller/{seller_id}/dashboard", { params: { path: { seller_id: sellerId } } }),
    getMe(),
  ]);
  const s = t.seller;
  const shop = seller.data;
  if (!shop) return <p role="alert">{t.apiErrors.permission_denied}</p>;
  const membership = me?.sellers.find((m) => m.seller_id === sellerId);
  const screens = membership ? sellerMenu(lang, sellerId, membership, t).filter((item) => item.href !== `/${lang}/seller/${sellerId}`) : [];
  const checks = Object.entries(shop.checks).filter(([, done]) => done).map(([key]) => key);
  const d = dashboard.data;
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <header className="space-y-1">
        <h1 className="text-2xl font-extrabold">{shop.store.name}</h1>
        <p>{fill(s.homeStatus, { status: codeLabel(t, "sellerStatus", shop.status), review: codeLabel(t, "reviewState", shop.review_state) })}</p>
        <p className="text-sm text-slate">
          {fill(s.homeLevel, { level: shop.verification_level })} · {fill(s.homeRole, { role: codeLabel(t, "sellerRole", shop.role) })}
        </p>
        {shop.submitted_at ? <p className="text-sm text-slate">{fill(s.submittedOn, { date: formatDateTime(shop.submitted_at, lang) })}</p> : null}
        {shop.recheck_due_on ? <p className="text-sm text-slate">{fill(s.recheckDue, { date: shop.recheck_due_on })}</p> : null}
      </header>

      {shop.review_note ? <p className="rounded-card border border-clay bg-white p-3">{fill(s.reviewNote, { note: shop.review_note })}</p> : null}

      {shop.missing.length ? (
        <section aria-labelledby="missing" className="space-y-2 rounded-card border border-adey bg-white p-4">
          <h2 id="missing" className="font-bold">{s.missingTitle}</h2>
          <ul className="list-disc space-y-1 pl-5">
            {shop.missing.map((item) => (
              <li key={item}>
                {item.startsWith("document:") ? (
                  <Link href={`/${lang}/seller/${sellerId}/documents`} className="underline">{fill(s.missingDocument, { document: codeLabel(t, "docType", item.slice("document:".length)) })}</Link>
                ) : item === "payout_account" ? (
                  <Link href={`/${lang}/seller/${sellerId}/payout`} className="underline">{s.missingPayout}</Link>
                ) : (
                  item
                )}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {shop.status === "applied" && ASKS_FOR_REVIEW.has(shop.review_state) && shop.capabilities.includes("change_legal_details") ? (
        <SubmitApplicationForm sellerId={sellerId} t={{ seller: t.seller, apiErrors: t.apiErrors }} />
      ) : null}

      {d ? <p className="text-slate">{fill(s.counts, { active: d.active_offers, paused: d.paused_offers, stale: d.prices_to_confirm, low: d.low_stock_offers })}</p> : null}

      {checks.length ? (
        <section aria-labelledby="checked" className="rounded-card border border-line bg-white p-4">
          <h2 id="checked" className="mb-2 font-bold">{s.checksTitle}</h2>
          <ul className="grid gap-1 sm:grid-cols-2">
            {checks.map((key) => <li key={key}>{t.store[`check_${key}` as keyof Messages["store"]] ?? key}</li>)}
          </ul>
        </section>
      ) : null}

      {shop.capabilities.includes("transfer_or_close") && shop.status !== "closed" ? (
        <details className="rounded-card border border-clay bg-white p-4">
          <summary className="flex min-h-12 cursor-pointer items-center font-semibold text-clay">{s.closeTitle}</summary>
          <CloseShopForm lang={lang} sellerId={sellerId} t={{ seller: t.seller, apiErrors: t.apiErrors }} />
        </details>
      ) : null}

      <nav aria-labelledby="screens" className="space-y-2">
        <h2 id="screens" className="font-bold">{s.screensTitle}</h2>
        <ul className="grid gap-2 sm:grid-cols-2">
          {screens.map((item) => (
            <li key={item.href}>
              <Link href={item.href} className="flex min-h-12 items-center rounded-card border border-line bg-white px-4 font-semibold hover:border-ink">{item.label}</Link>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
