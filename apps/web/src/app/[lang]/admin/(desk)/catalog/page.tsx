import { notFound } from "next/navigation";

import { ProposalDecision } from "@/components/admin/StaffActions";
import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

// Products sellers proposed, waiting for a catalogue curator (AD-02, D.5):
// approve, turn down with a note, or merge into the approved product it
// duplicates. Nothing is shown to buyers until a curator approves it.
export default async function ProposalsPage({ params }: PageProps<"/[lang]/admin/catalog">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const [pending, approved] = await Promise.all([
    api.GET("/api/v1/admin/catalog/products", { params: { query: { status: "pending_review", limit: 200, lang } } }),
    api.GET("/api/v1/admin/catalog/products", { params: { query: { status: "approved", limit: 200, lang } } }),
  ]);
  const a = t.admin;
  if (pending.response.status === 403) return <p role="alert" className="font-semibold text-clay">{a.notAllowed}</p>;
  const text = { admin: a, apiErrors: t.apiErrors };
  const rows = pending.data ?? [];
  const survivors = (approved.data ?? []).map((row) => ({ id: row.id, name: row.name }));
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-extrabold">{a.catalogTitle}</h1>
      {rows.length === 0 ? <p className="text-slate">{a.noProposals}</p> : null}
      <ul className="space-y-4">
        {rows.map((row) => (
          <li key={row.id} className="space-y-3 rounded-card border border-line bg-white p-4">
            <div>
              <p className="font-bold">{row.name}</p>
              <p className="text-sm text-slate">
                {row.proposed_by_seller_id ? a.proposedBySeller : a.proposedByStaff} · {formatDateTime(row.created_at, lang)} · {row.slug}
              </p>
            </div>
            <ProposalDecision productId={row.id} approved={survivors} t={text} />
          </li>
        ))}
      </ul>
    </div>
  );
}
