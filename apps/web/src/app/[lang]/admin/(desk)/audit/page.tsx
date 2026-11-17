import Link from "next/link";
import { notFound } from "next/navigation";

import { serverApi } from "@/lib/api/server";
import { formatDateTime } from "@/lib/format";
import { isLocale } from "@/lib/i18n";
import { codeLabel } from "@/lib/labels";
import { getMessages } from "@/lib/messages";

// The patterns the API accepts (D-065); anything else is not sent.
const ACTION = /^[a-z_]+(\.[a-z_]+)*\.?$/;
const TARGET_TYPE = /^[a-z_]+$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const PAGE = 50;

function one(value: string | string[] | undefined): string {
  return (typeof value === "string" ? value : "").trim();
}

// The audit trail (blueprint C.4, D.18 AD-17) over the API's audit-log viewer
// (D-065): read only, newest first, for the super administrator and finance.
// The API refuses every other role, and the page says so.
export default async function AuditPage({ params, searchParams }: PageProps<"/[lang]/admin/audit">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const t = await getMessages(lang);
  const query = await searchParams;
  const filters = {
    target_type: one(query.target_type),
    target_id: one(query.target_id),
    action: one(query.action),
    before: one(query.before),
  };
  const api = await serverApi();
  const { data, response } = await api.GET("/api/v1/admin/audit-log", {
    params: {
      query: {
        limit: PAGE,
        ...(filters.target_type.length <= 60 && TARGET_TYPE.test(filters.target_type) ? { target_type: filters.target_type } : {}),
        ...(filters.target_id && filters.target_id.length <= 80 ? { target_id: filters.target_id } : {}),
        ...(filters.action.length <= 80 && ACTION.test(filters.action) ? { action: filters.action } : {}),
        ...(UUID.test(filters.before) ? { before: filters.before } : {}),
      },
    },
  });
  const a = t.admin;
  if (response.status === 403) return <p role="alert" className="font-semibold text-clay">{a.notAllowed}</p>;
  const rows = data ?? [];
  const last = rows.at(-1);
  const older = new URLSearchParams(
    Object.entries({ ...filters, before: last?.id ?? "" }).filter(([, value]) => value) as [string, string][],
  );
  const field = "min-h-12 w-full rounded-card border border-line bg-white px-3";
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-extrabold">{a.auditTitle}</h1>
      <p className="text-slate">{a.auditLead}</p>
      <form method="get" className="grid gap-2 sm:grid-cols-4 sm:items-end">
        <label className="space-y-1"><span className="block text-sm font-semibold">{a.filterTargetType}</span><input name="target_type" defaultValue={filters.target_type} className={field} /></label>
        <label className="space-y-1"><span className="block text-sm font-semibold">{a.filterTargetId}</span><input name="target_id" defaultValue={filters.target_id} className={field} /></label>
        <label className="space-y-1"><span className="block text-sm font-semibold">{a.filterAction}</span><input name="action" defaultValue={filters.action} className={field} /></label>
        <button type="submit" className="min-h-12 rounded-card bg-ink px-5 font-bold text-paper">{a.filter}</button>
      </form>
      {rows.length === 0 ? <p className="text-slate">{a.noAudit}</p> : null}
      <ol className="space-y-2">
        {rows.map((row) => (
          <li key={row.id} className="space-y-1 rounded-card border border-line bg-white p-3 text-sm">
            <p className="font-semibold">{row.action} <span className="font-normal text-slate">· {row.target_type} {row.target_id}</span></p>
            <p className="text-slate">
              {formatDateTime(row.occurred_at, lang)} · {row.actor_type === "system" ? a.actorSystem : codeLabel(t, "actorType", row.actor_type)}
            </p>
            {row.before != null ? <p className="break-all"><span className="font-semibold">{a.before}: </span><code>{JSON.stringify(row.before)}</code></p> : null}
            {row.after != null ? <p className="break-all"><span className="font-semibold">{a.after}: </span><code>{JSON.stringify(row.after)}</code></p> : null}
          </li>
        ))}
      </ol>
      {rows.length === PAGE && last ? (
        <Link href={`/${lang}/admin/audit?${older.toString()}`} className="inline-block min-h-12 rounded-card border border-ink px-4 py-3 font-semibold">{a.older}</Link>
      ) : null}
    </div>
  );
}
