import Link from "next/link";
import { notFound } from "next/navigation";

import { ResolveReportForm } from "@/components/admin/StaffActions";
import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { fill, isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

const STATUSES = ["open", "actioned", "dismissed"] as const;
const TARGETS = ["product", "offer", "store", "review"] as const;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const PAGE = 50;

// The reports queue (blueprint C-30, AD-16; D-067): flags on products,
// listings, shops and reviews. Staff close a report as acted on or dismissed,
// with a note, and by default every open report on the same thing at once.
export default async function ReportsPage({ params, searchParams }: PageProps<"/[lang]/admin/reports">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const query = await searchParams;
  const status = STATUSES.find((s) => s === query.status) ?? "open";
  const target = TARGETS.find((s) => s === query.target_type);
  const before = typeof query.before === "string" && UUID.test(query.before) ? query.before : undefined;
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/admin/reports", {
    params: { query: { status, limit: PAGE, ...(target ? { target_type: target } : {}), ...(before ? { before } : {}) } },
  });
  const a = t.admin;
  if (response.status === 403) return <p role="alert" className="font-semibold text-clay">{a.notAllowed}</p>;
  const text = { admin: a, apiErrors: t.apiErrors };
  const rows = data ?? [];
  const last = rows.at(-1);
  const field = "min-h-12 w-full rounded-card border border-line bg-white px-3";
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-extrabold">{a.reportsTitle}</h1>
      <form method="get" className="grid gap-2 sm:grid-cols-3 sm:items-end">
        <label className="space-y-1">
          <span className="block text-sm font-semibold">{a.statusFilter}</span>
          <select name="status" defaultValue={status} className={field}>
            {STATUSES.map((s) => <option key={s} value={s}>{codeLabel(t, "reportStatus", s)}</option>)}
          </select>
        </label>
        <label className="space-y-1">
          <span className="block text-sm font-semibold">{a.targetFilter}</span>
          <select name="target_type" defaultValue={target ?? ""} className={field}>
            <option value="">{a.anyTarget}</option>
            {TARGETS.map((s) => <option key={s} value={s}>{codeLabel(t, "reportTarget", s)}</option>)}
          </select>
        </label>
        <button type="submit" className="min-h-12 rounded-card bg-ink px-5 font-bold text-paper">{a.filter}</button>
      </form>
      {rows.length === 0 ? <p className="text-slate">{a.noReports}</p> : null}
      <ul className="space-y-3">
        {rows.map((report) => (
          <li key={report.id} className="space-y-2 rounded-card border border-line bg-white p-4">
            <p className="font-bold">
              {codeLabel(t, "reportTarget", report.target_type)} · {fill(a.reportedReason, { reason: codeLabel(t, "reportReason", report.reason) })}
            </p>
            <p className="text-sm text-slate">
              {formatDateTime(report.created_at, lang)} · {codeLabel(t, "reportStatus", report.status)}
              {report.from_signed_in_person ? "" : ` · ${a.anonymousReporter}`}
              {report.open_reports_on_target > 1 ? ` · ${fill(a.openOnTarget, { count: report.open_reports_on_target })}` : ""}
            </p>
            {report.excerpt ? <p className="whitespace-pre-line rounded-card bg-paper p-3">{report.excerpt}</p> : null}
            {report.note ? <p className="text-sm">{fill(a.reporterNote, { note: report.note })}</p> : null}
            <p className="flex flex-wrap gap-4 text-sm">
              {report.product_slug ? <Link href={`/${lang}/p/${report.product_slug}`} className="inline-block min-h-12 py-3 font-semibold underline">{a.viewProduct}</Link> : null}
              {report.store_slug ? <Link href={`/${lang}/s/${report.store_slug}`} className="inline-block min-h-12 py-3 font-semibold underline">{a.viewStore}</Link> : null}
            </p>
            {report.status === "open" ? (
              <ResolveReportForm reportId={report.id} t={text} />
            ) : report.resolved_at ? (
              <p className="text-sm">{fill(a.resolved, { time: formatDateTime(report.resolved_at, lang), note: report.resolution_note ?? "" })}</p>
            ) : null}
          </li>
        ))}
      </ul>
      {rows.length === PAGE && last ? (
        <Link href={`/${lang}/admin/reports?status=${status}${target ? `&target_type=${target}` : ""}&before=${last.id}`} className="inline-block min-h-12 rounded-card border border-ink px-4 py-3 font-semibold">{a.older}</Link>
      ) : null}
    </div>
  );
}
