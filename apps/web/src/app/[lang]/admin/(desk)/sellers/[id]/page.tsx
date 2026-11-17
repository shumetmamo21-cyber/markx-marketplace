import { notFound } from "next/navigation";

import { DocumentReview, SellerDecision } from "@/components/admin/StaffActions";
import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

// One application: legal details, documents opened through five-minute
// links (each access logged by the API), and the decision (AD-01).
export default async function SellerReviewPage({ params }: PageProps<"/[lang]/admin/sellers/[id]">) {
  const { lang, id } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data: seller } = await api.GET("/api/v1/admin/sellers/{seller_id}", { params: { path: { seller_id: id } } });
  if (!seller) notFound();
  const a = t.admin;
  const text = { admin: a, apiErrors: t.apiErrors };
  return (
    <div className="space-y-5">
      <header className="space-y-1">
        <h1 className="text-2xl font-extrabold">{seller.legal.trade_name}</h1>
        <p className="text-slate">{seller.status} · {seller.review_state}{seller.submitted_at ? ` · ${fill(a.submitted, { time: formatDateTime(seller.submitted_at, lang) })}` : ""}</p>
      </header>
      <section className="space-y-1 rounded-card border border-line bg-white p-4 text-sm">
        <h2 className="mb-1 font-bold">{a.legal}</h2>
        <p className="font-semibold">{seller.legal.legal_name}</p>
        {seller.legal.tin ? <p>{fill(a.tin, { tin: seller.legal.tin })}</p> : null}
        {seller.legal.licence_number ? <p>{fill(a.licence, { licence: seller.legal.licence_number })}</p> : null}
        <p>{fill(a.address, { address: seller.legal.shop_address })}</p>
        <p>{fill(a.contact, { phone: seller.legal.contact_phone })}</p>
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-bold">{a.documents}</h2>
        <ul className="grid gap-3 md:grid-cols-2">
          {seller.documents.map((document) => (
            <li key={document.id} className="space-y-2 rounded-card border border-line bg-white p-4">
              <p className="font-semibold">{document.doc_type}</p>
              <p className="text-sm text-slate">{fill(a.docStatus, { status: document.review_status })}{document.review_note ? ` · ${document.review_note}` : ""}</p>
              <DocumentReview sellerId={seller.id} documentId={document.id} t={text} />
            </li>
          ))}
        </ul>
      </section>
      {seller.review_state === "pending" || seller.review_state === "needs_documents" ? (
        <section className="rounded-card border border-ink bg-white p-4">
          <SellerDecision sellerId={seller.id} t={text} />
        </section>
      ) : null}
    </div>
  );
}
