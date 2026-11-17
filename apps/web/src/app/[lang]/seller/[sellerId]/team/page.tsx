import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { AddMemberForm, RemoveMemberButton } from "@/components/seller/SellerForms";
import { serverApi } from "@/lib/api/server";
import { isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";
import { getMe } from "@/lib/session";

export const metadata: Metadata = { robots: { index: false } };

// The shop's team (blueprint C.2, C.3). The API decides which roles may be
// given today (role_not_available), seats, and who may be removed (never the
// owner); the page lists the roles the API's schema knows and says its answer.
export default async function SellerTeamPage({ params }: PageProps<"/[lang]/seller/[sellerId]/team">) {
  const { lang, sellerId } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const [{ data, response }, me] = await Promise.all([
    api.GET("/api/v1/seller/{seller_id}/members", { params: { path: { seller_id: sellerId } } }),
    getMe(),
  ]);
  if (response.status === 403) return <p role="alert">{t.apiErrors.permission_denied}</p>;
  const s = t.seller;
  const text = { seller: t.seller, apiErrors: t.apiErrors };
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <h1 className="text-2xl font-extrabold">{s.teamTitle}</h1>
      <p className="text-slate">{s.teamLead}</p>
      <ul className="space-y-2">
        {(data ?? []).map((member) => (
          <li key={member.id} className="space-y-2 rounded-card border border-line bg-white p-3">
            <p className="flex flex-wrap items-center justify-between gap-2">
              <span>
                <span className="block font-semibold">{member.name ?? member.phone}{member.user_id === me?.id ? ` · ${s.memberYou}` : ""}</span>
                <span className="block text-sm text-slate">{member.phone}</span>
              </span>
              <span className="rounded-full border border-line px-3 py-1 text-sm font-semibold">{codeLabel(t, "sellerRole", member.role)}</span>
            </p>
            {member.role !== "owner" ? <RemoveMemberButton sellerId={sellerId} memberId={member.id} t={text} /> : null}
          </li>
        ))}
      </ul>
      <section className="rounded-card border border-line bg-white p-4">
        <AddMemberForm sellerId={sellerId} t={text} roles={t.labels.sellerRole} />
      </section>
    </div>
  );
}
