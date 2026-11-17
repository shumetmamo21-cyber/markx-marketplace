import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PayoutForm } from "@/components/seller/SellerForms";
import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

export const metadata: Metadata = { robots: { index: false } };

// Where the shop is paid (blueprint S-13, owner only). The API keeps the
// number encrypted and shows its last four digits; a change waits out a
// cooling-off period before it replaces the account in use.
export default async function SellerPayoutPage({ params }: PageProps<"/[lang]/seller/[sellerId]/payout">) {
  const { lang, sellerId } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/seller/{seller_id}/payout-accounts", { params: { path: { seller_id: sellerId } } });
  if (response.status === 403) return <p role="alert">{t.apiErrors.permission_denied}</p>;
  const s = t.seller;
  const accounts = data ?? [];
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <h1 className="text-2xl font-extrabold">{s.payoutTitle}</h1>
      <p className="text-slate">{s.payoutLead}</p>
      {accounts.length === 0 ? <p>{s.payoutNone}</p> : null}
      <ul className="space-y-2">
        {accounts.map((account) => (
          <li key={account.id} className="flex flex-wrap items-center justify-between gap-2 rounded-card border border-line bg-white p-3">
            <span>
              <span className="block font-semibold">{account.provider_name} · {codeLabel(t, "payoutKind", account.kind)}</span>
              <span className="block text-sm">{account.account_name} · {fill(s.payoutEnding, { last4: account.account_last4 })}</span>
              <span className="block text-sm text-slate">{fill(s.payoutFrom, { date: formatDateTime(account.effective_from, lang) })}</span>
            </span>
            <span className="rounded-full border border-line px-3 py-1 text-sm font-semibold">{codeLabel(t, "payoutStatus", account.status)}</span>
          </li>
        ))}
      </ul>
      <section className="rounded-card border border-line bg-white p-4">
        <PayoutForm sellerId={sellerId} t={{ seller: t.seller, apiErrors: t.apiErrors }} kinds={t.labels.payoutKind} />
      </section>
    </div>
  );
}
