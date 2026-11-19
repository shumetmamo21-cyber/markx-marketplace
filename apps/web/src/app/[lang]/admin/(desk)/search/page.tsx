import { notFound } from "next/navigation";

import { AddSynonymForm, RemoveSynonymButton } from "@/components/admin/StaffActions";
import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { getMessages } from "@/lib/messages";

// What buyers searched for and did not find, and the synonym tool (AD-07).
export default async function SearchToolsPage({ params }: PageProps<"/[lang]/admin/search">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const api = await serverApi();
  const [zero, synonyms] = await Promise.all([
    api.GET("/api/v1/admin/search/zero-results", { params: { query: { days: 7 } } }),
    api.GET("/api/v1/admin/search/synonyms", {}),
  ]);
  const a = t.admin;
  const text = { admin: a, apiErrors: t.apiErrors };
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">{a.searchTitle}</h1>
      <section className="space-y-2">
        <h2 className="text-lg font-bold">{a.zeroTitle}</h2>
        {(zero.data ?? []).length === 0 ? <p className="text-slate">{a.noZero}</p> : null}
        <ul className="divide-y divide-line rounded-card border border-line bg-white">
          {(zero.data ?? []).map((row) => (
            <li key={row.normalized} className="flex flex-wrap justify-between gap-2 p-3">
              <span className="font-semibold">{row.example}</span>
              <span className="text-sm text-slate">{fill(a.searches, { count: row.searches })} · {formatDateTime(row.last_searched_at, lang)}</span>
            </li>
          ))}
        </ul>
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-bold">{a.synonymsTitle}</h2>
        <AddSynonymForm t={text} />
        {(synonyms.data ?? []).length === 0 ? <p className="text-slate">{a.noSynonyms}</p> : null}
        <ul className="divide-y divide-line rounded-card border border-line bg-white">
          {(synonyms.data ?? []).map((row) => (
            <li key={row.id} className="flex flex-wrap items-center justify-between gap-2 px-3">
              <span>{row.term} → {row.expansion}</span>
              <RemoveSynonymButton id={row.id} t={text} />
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
