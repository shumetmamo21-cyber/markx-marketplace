import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { DocumentUploadForm, OpenDocumentButton } from "@/components/seller/SellerForms";
import { serverApi } from "@/lib/api/server";
import { formatDate, formatDateTime } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

export const metadata: Metadata = { robots: { index: false } };

// The owner's documents (blueprint D.3, C.3): what was sent, what MarkX
// decided and why, and an upload. Files open only behind a link the API signs
// for this person (D-062's pattern); where they are kept is F-01, undecided.
export default async function SellerDocumentsPage({ params }: PageProps<"/[lang]/seller/[sellerId]/documents">) {
  const { lang, sellerId } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/seller/{seller_id}/documents", { params: { path: { seller_id: sellerId } } });
  if (response.status === 403) return <p role="alert">{t.apiErrors.permission_denied}</p>;
  const s = t.seller;
  const text = { seller: t.seller, apiErrors: t.apiErrors };
  const documents = data ?? [];
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <h1 className="text-2xl font-extrabold">{s.documentsTitle}</h1>
      <p className="text-slate">{s.documentsLead}</p>
      {documents.length === 0 ? <p>{s.docNone}</p> : null}
      <ul className="space-y-2">
        {documents.map((document) => (
          <li key={document.id} className="space-y-2 rounded-card border border-line bg-white p-3">
            <p className="flex flex-wrap items-center justify-between gap-2">
              <span>
                <span className="block font-semibold">{codeLabel(t, "docType", document.doc_type)}</span>
                <span className="block text-sm text-slate">{formatDateTime(document.created_at, lang)}{document.expires_on ? ` · ${fill(s.docExpiresOn, { date: formatDate(document.expires_on, lang) })}` : ""}</span>
              </span>
              <span className="rounded-full border border-line px-3 py-1 text-sm font-semibold">{codeLabel(t, "documentStatus", document.review_status)}</span>
            </p>
            {document.review_note ? <p className="text-sm">{fill(s.reviewNote, { note: document.review_note })}</p> : null}
            <OpenDocumentButton sellerId={sellerId} documentId={document.id} t={text} />
          </li>
        ))}
      </ul>
      <section className="rounded-card border border-line bg-white p-4">
        <DocumentUploadForm sellerId={sellerId} t={text} types={t.labels.docType} />
      </section>
    </div>
  );
}
