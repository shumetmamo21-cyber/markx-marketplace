import Link from "next/link";
import { notFound } from "next/navigation";

import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

// Applications waiting for review (AD-01), oldest first as the API sends them.
export default async function SellerQueuePage({ params }: PageProps<"/[lang]/admin/sellers">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const [pending, missing] = await Promise.all([
    api.GET("/api/v1/admin/sellers", { params: { query: { review_state: "pending" } } }),
    api.GET("/api/v1/admin/sellers", { params: { query: { review_state: "needs_documents" } } }),
  ]);
  const rows = [...(pending.data ?? []), ...(missing.data ?? [])];
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-extrabold">{t.admin.sellersTitle}</h1>
      {rows.length === 0 ? <p className="text-slate">{t.admin.noSellers}</p> : null}
      <ul className="space-y-3">
        {rows.map((row) => (
          <li key={row.id}>
            <Link href={`/${lang}/admin/sellers/${row.id}`} className="block space-y-1 rounded-card border border-line bg-white p-4 hover:border-ink">
              <p className="font-bold">{row.trade_name} <span className="font-normal text-slate">· {row.legal_name}</span></p>
              <p className="text-sm text-slate">{codeLabel(t, "reviewState", row.review_state)}{row.submitted_at ? ` · ${fill(t.admin.submitted, { time: formatDateTime(row.submitted_at, lang) })}` : ""}</p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
